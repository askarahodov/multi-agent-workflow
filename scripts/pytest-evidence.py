#!/usr/bin/env python3
"""Produce minimal test evidence; read a single bounded JSON artifact ZIP.
No extraction, executable content, failure text, stdout or environment dump.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

LIMIT = 16 * 1024 * 1024
SHA = re.compile(r"^[a-f0-9]{40}$")
SUITES = {"agent-management", "orchestration-server", "quality-gates",
          "runtime-hardening", "tools", "agent-runtime", "root"}
FRONTEND_SUITES = {"vitest", "browser-mock", "compose-browser", "compose-ticket"}


def fail(message):
    raise ValueError(message)


def produce(source, destination, suite):
    if suite not in SUITES:
        fail("unknown suite")
    with open(source, "rb") as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        fail("invalid or oversized pytest XML")
    root = ET.fromstring(raw)
    if root.tag not in {"testsuites", "testsuite"}:
        fail("unexpected pytest XML root")
    tests = {}
    for case in root.iter("testcase"):
        name = case.get("name")
        classname = case.get("classname")
        if not name or not classname or len(name) + len(classname) > 2048:
            fail("missing or oversized test identity")
        identity = classname + "::" + name
        if identity in tests:
            fail("duplicate test identity")
        markers = [child.tag for child in case if child.tag in {"failure", "error", "skipped"}]
        if len(markers) > 1:
            fail("ambiguous test result")
        tests[identity] = markers[0] if markers else "passed"
    if not tests or len(tests) > 20000:
        fail("missing or oversized test set")
    if any(result in {"failure", "error"} for result in tests.values()):
        fail("failed test in successful job report")
    write_report(tests, destination, suite)


def write_report(tests, destination, suite):
    if not tests or len(tests) > 20000:
        fail("missing or oversized test set")
    head = os.environ["RTM_HEAD_SHA"]
    base = os.environ.get("RTM_BASE_SHA") or None
    checkout = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    run_id = int(os.environ["GITHUB_RUN_ID"])
    attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])
    if not SHA.fullmatch(head) or (base is not None and not SHA.fullmatch(base)) or not SHA.fullmatch(checkout) or min(run_id, attempt) < 1:
        fail("invalid CI provenance")
    payload = {"schema_version": 1, "suite": suite, "head_sha": head,
               "base_sha": base, "checkout_sha": checkout, "run_id": run_id,
               "run_attempt": attempt, "tests": tests}
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode()
    if len(data) > LIMIT:
        fail("oversized evidence")
    Path(destination).write_bytes(data + b"\n")


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate JSON key")
        result[key] = value
    return result


def produce_frontend(source, destination, suite):
    if suite not in FRONTEND_SUITES:
        fail("unknown frontend suite")
    with open(source, "rb") as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        fail("oversized frontend report")
    report = json.loads(raw, object_pairs_hook=unique_json)
    tests = {}
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    frontend = root / "apps" / "frontend"

    def file_id(name):
        if not isinstance(name, str) or not name:
            fail("missing test file")
        path = Path(name)
        if not path.is_absolute():
            path = (frontend / "e2e" / path if suite != "vitest" and not name.startswith("e2e/") else frontend / path)
        path = path.resolve()
        if not path.is_relative_to(frontend.resolve()):
            fail("test file outside frontend")
        return path.relative_to(frontend.resolve()).as_posix()

    def add(identity, status):
        if not identity or len(identity) > 2048 or identity in tests:
            fail("missing, oversized or duplicate frontend identity")
        tests[identity] = status

    if suite == "vitest":
        if report.get("success") is not True or not isinstance(report.get("testResults"), list):
            fail("unsuccessful Vitest report")
        for result in report["testResults"]:
            filename = file_id(result["name"])
            for case in result["assertionResults"]:
                title = case["fullName"]
                if not isinstance(title, str) or not title:
                    fail("missing Vitest title")
                status = case["status"]
                if status == "passed":
                    # A retried pass is not an unqualified passing result.
                    status = "flaky" if case.get("retryCount", 0) else "passed"
                elif status in {"pending", "todo", "skipped", "disabled"}:
                    status = "skipped"
                else:
                    fail("non-passing Vitest report")
                add(filename + "::" + title, status)
    else:
        # Playwright JSON has separate expectedStatus, outcome and results.
        # Never turn an expected failure or a retry into PASS.
        def walk(node, titles):
            title = node.get("title")
            path = titles + ([title] if isinstance(title, str) and title else [])
            for spec in node.get("specs", []):
                filename = file_id(spec["file"])
                name = spec["title"]
                if not isinstance(name, str) or not name:
                    fail("missing Playwright title")
                for case in spec["tests"]:
                    project = case.get("projectName") or "default"
                    if not isinstance(project, str):
                        fail("invalid Playwright project")
                    identity = filename + "::" + json.dumps(path + [name, project], ensure_ascii=False, separators=(",", ":"))
                    outcome = case["status"]
                    attempts = case["results"]
                    expected = case["expectedStatus"]
                    if outcome == "unexpected":
                        fail("unexpected Playwright result")
                    if outcome == "skipped":
                        status = "skipped"
                    elif outcome == "flaky":
                        status = "flaky"
                    elif outcome == "expected" and expected != "passed":
                        status = "expected-failure"
                    elif outcome == "expected" and expected == "passed" and len(attempts) == 1 and attempts[0]["status"] == "passed" and attempts[0].get("retry", 0) == 0:
                        status = "passed"
                    else:
                        fail("unknown Playwright result")
                    add(identity, status)
            for child in node.get("suites", []):
                walk(child, path)

        if not isinstance(report.get("suites"), list) or report.get("errors"):
            fail("unsuccessful Playwright report")
        for node in report["suites"]:
            walk(node, [])
    write_report(tests, destination, suite)


def read_zip():
    raw = sys.stdin.buffer.read(LIMIT + 1)
    if len(raw) > LIMIT:
        fail("oversized artifact")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename not in {"maw-pytest.json", "maw-frontend.json"}:
            fail("unexpected artifact members")
        entry = members[0]
        if entry.file_size > LIMIT or entry.flag_bits & 1:
            fail("oversized or encrypted artifact member")
        with archive.open(entry) as stream:
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT:
            fail("oversized artifact member")
        # Reject duplicate keys, including duplicate test IDs.
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    fail("duplicate JSON key")
                result[key] = value
            return result
        parsed = json.loads(data, object_pairs_hook=unique)
        sys.stdout.write(json.dumps(parsed, ensure_ascii=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("produce")
    p.add_argument("source")
    p.add_argument("destination")
    p.add_argument("suite", choices=sorted(SUITES))
    f = subs.add_parser("frontend")
    f.add_argument("source")
    f.add_argument("destination")
    f.add_argument("suite", choices=sorted(FRONTEND_SUITES))
    subs.add_parser("read")
    args = parser.parse_args()
    try:
        if args.command == "produce":
            produce(args.source, args.destination, args.suite)
        elif args.command == "frontend":
            produce_frontend(args.source, args.destination, args.suite)
        else:
            read_zip()
    except (ValueError, OSError, KeyError, TypeError, AttributeError, RuntimeError, ET.ParseError, zipfile.BadZipFile):
        print("pytest evidence BLOCKED: invalid report, provenance or artifact", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
