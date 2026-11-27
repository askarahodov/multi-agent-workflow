#!/usr/bin/env python3
"""Produce minimal pytest evidence; read a single bounded JSON artifact ZIP.
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


def read_zip():
    raw = sys.stdin.buffer.read(LIMIT + 1)
    if len(raw) > LIMIT:
        fail("oversized artifact")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename != "maw-pytest.json":
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
    subs.add_parser("read")
    args = parser.parse_args()
    try:
        if args.command == "produce":
            produce(args.source, args.destination, args.suite)
        else:
            read_zip()
    except (ValueError, OSError, KeyError, RuntimeError, ET.ParseError, zipfile.BadZipFile):
        print("pytest evidence BLOCKED: invalid report, provenance or artifact", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
