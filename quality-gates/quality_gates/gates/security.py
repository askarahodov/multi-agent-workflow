"""Security gate: dependency checks and secret detection.

Two evidence categories:

* ``dep``  -- parses dependency manifests (``requirements.txt``/``pyproject.toml``)
   and flags packages pinned to versions known to be vulnerable (a small,
   auditable embedded advisory list; real deployments can point the gate at an
   external advisory feed via ``context["advisories"]``).
* ``secret`` -- scans the workspace for high-confidence secret patterns (API
   keys, private keys, cloud credentials) and flags any matches found outside
   ``.gitignore``/``.env.example``-style files.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .base import Finding, Gate, GateResult, GATE_REGISTRY
from .walk import iter_files

# pattern -> (reason, severity). Deliberately conservative; only high-entropy
# or structurally unambiguous secrets are matched to limit false positives.
SECRET_PATTERNS: dict[str, tuple[str, str]] = {
    r"\bAKIA[0-9A-Z]{16}\b": ("AWS access key", "critical"),
    r"\bghp_[A-Za-z0-9]{36}\b": ("GitHub personal access token", "critical"),
    r"\b(sk|pk)_(live|test)_[A-Za-z0-9]{20,}\b": ("Stripe-style secret key", "high"),
    r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----": ("private key block", "critical"),
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b": ("Slack token", "high"),
    r"AIza[0-9A-Za-z_-]{35}": ("Google API key", "high"),
}

# Files that legitimately contain secret-shaped placeholders.
SKIP_FILES = {".gitignore", ".env.example", ".env.sample", ".env.template"}

# Embed a tiny, auditable advisory list: package name -> vulnerable versions.
# This is a demonstration data set; production integrations replace it with a
# live advisory feed via context["advisories"].
DEFAULT_ADVISORIES: dict[str, list[str]] = {
    "example-vuln-lib": ["1.0.0", "1.0.1"],
    "legacy-dep": ["0.9.x"],
}


class SecurityGate:
    name = "security"
    description = "Scans for vulnerabilities: dependency checks and secret detection."

    def execute(self, workspace: str, context: dict[str, Any] | None = None) -> GateResult:
        ctx = context or {}
        root = Path(workspace)
        started = time.perf_counter()
        findings: list[Finding] = []
        all_passed = True

        # --- Dependency check -----------------------------------------------------
        advisories = ctx.get("advisories") or DEFAULT_ADVISORIES
        dep_problems: list[dict[str, Any]] = []
        for manifest in ("requirements.txt", "pyproject.toml"):
            path = root / manifest
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                m = re.match(r"^\s*([A-Za-z0-9_.-]+)[<>=~!]+\s*([^\s,;]+)", line)
                if not m:
                    continue
                name, ver = m.group(1).lower(), m.group(2)
                for pkg, versions in advisories.items():
                    if name == pkg and _version_hit(ver, versions):
                        dep_problems.append({"package": name, "version": ver, "manifest": manifest})

        dep_ok = not dep_problems
        all_passed = all_passed and dep_ok
        findings.append(
            Finding(
                category="dep",
                key="dependency-scan",
                passed=dep_ok,
                summary=(
                    "no known-vulnerable dependencies detected"
                    if dep_ok
                    else f"{len(dep_problems)} vulnerable dependency reference(s)"
                ),
                detail={"vulnerable": dep_problems},
            )
        )

        # --- Secret detection ------------------------------------------------------
        secret_hits: list[dict[str, Any]] = []
        for path in iter_files(root):
            if path.name in SKIP_FILES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pattern, (reason, severity) in SECRET_PATTERNS.items():
                for m in re.finditer(pattern, text):
                    # Redact the secret value itself from evidence.
                    snippet = m.group(0)
                    redacted = snippet[:4] + "…" + snippet[-4:] if len(snippet) > 8 else "…"
                    secret_hits.append(
                        {"file": str(path), "pattern": pattern, "reason": reason,
                         "severity": severity, "matched": redacted}
                    )

        secret_ok = not secret_hits
        all_passed = all_passed and secret_ok
        findings.append(
            Finding(
                category="secret",
                key="secret-scan",
                passed=secret_ok,
                summary=(
                    "no secrets detected"
                    if secret_ok
                    else f"{len(secret_hits)} potential secret(s) detected"
                ),
                detail={"hits": secret_hits[:50]},
            )
        )

        duration_ms = (time.perf_counter() - started) * 1000
        return GateResult(
            gate=self.name,
            passed=all_passed,
            summary="dependency and secret scans pass"
            if all_passed
            else "security findings require attention",
            findings=findings,
            duration_ms=duration_ms,
        )


def _version_hit(version: str, candidates: list[str]) -> bool:
    """Exact match or simple ``0.9.x`` prefix match against advisory versions."""
    if version in candidates:
        return True
    for cand in candidates:
        if cand.endswith(".x") and version.startswith(cand[:-1]):
            return True
    return False


GATE_REGISTRY.register(SecurityGate)
