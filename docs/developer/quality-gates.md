# Quality Gates

Comprehensive guide to the quality gate system that ensures code quality, security, and reliability.

## Gate Pipeline Overview

```
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  Security Gate  │──►│  Review Gate    │──►│  Quality Gate   │──►│  Release Gate   │
└─────────────────┘   └─────────────────┘   └─────────────────┘   └─────────────────┘
       │                     │                     │                     │
  • Dependency scan    • Linting (ruff)      • Unit tests         • Git tag
  • Secret detection   • Type check (mypy)   • Coverage ≥80%      • Docker push
  • SAST (bandit)      • Format check        • Integration tests  • GitHub Release
  • License check      • Diff review         • Performance        • Artifacts
```

## Gate Execution

### Automatic (via Kanban)

Gates run automatically at task transitions:

| Transition | Gates Executed |
|------------|----------------|
| `running` → `review` | Security → Review |
| `review` → `done` | Quality |
| `done` (release task) | Release |

### Manual (CLI)

```bash
# Run all gates on current directory
hermes-quality-gate run --all

# Run specific gate
hermes-quality-gate run --gate security
hermes-quality-gate run --gate review
hermes-quality-gate run --gate quality

# With custom config
hermes-quality-gate run --config quality-gates.yaml
```

### In CI/CD

```yaml
# .github/workflows/quality.yml
name: Quality Gates

on: [push, pull_request]

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run security gate
        run: |
          pip install -e .[quality]
          hermes-quality-gate run --gate security

  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run review gate
        run: hermes-quality-gate run --gate review

  quality:
    runs-on: ubuntu-latest
    needs: [security, review]
    steps:
      - uses: actions/checkout@v4
      - name: Run quality gate
        run: hermes-quality-gate run --gate quality
```

---

## Security Gate

### Checks Performed

| Check | Tool | Severity | Config |
|-------|------|----------|--------|
| Dependency vulnerabilities | `safety` | Critical/High | `requirements.txt`, `pyproject.toml` |
| Container vulnerabilities | `trivy` | Critical/High | Docker images |
| Secrets in code | `trufflehog` / `gitleaks` | Critical | All files |
| SAST (Python) | `bandit` | High/Medium | `src/**/*.py` |
| License compliance | `pip-licenses` | Warning | `requirements.txt` |

### Configuration (`quality-gates/security.yaml`)

```yaml
security_gate:
  enabled: true
  fail_on: [critical, high]
  
  dependency_scan:
    enabled: true
    tool: safety
    severity_threshold: high
    ignore_ids: []  # CVE IDs to ignore
  
  container_scan:
    enabled: true
    tool: trivy
    severity_threshold: high
    scan_images: true
  
  secret_scan:
    enabled: true
    tools: [trufflehog, gitleaks]
    fail_on_detected: true
    exclude_paths:
      - "*.md"
      - "test_*.py"
      - ".venv/"
  
  sast:
    enabled: true
    tool: bandit
    severity_threshold: medium
    exclude_paths:
      - "tests/"
      - "migrations/"
  
  license_check:
    enabled: true
    allowed_licenses: [MIT, Apache-2.0, BSD-3-Clause, BSD-2-Clause, ISC]
    fail_on_disallowed: false
```

### Running Security Gate

```bash
# Full security scan
hermes-quality-gate security

# Specific checks
hermes-quality-gate security --check dependencies
hermes-quality-gate security --check secrets
hermes-quality-gate security --check sast

# Output formats
hermes-quality-gate security --format json  # For CI parsing
hermes-quality-gate security --format sarif # For GitHub Security tab
```

### Common Issues & Fixes

#### Vulnerable Dependency
```bash
# Update vulnerable package
pip install --upgrade vulnerable-package

# Or pin to safe version in requirements.txt
# vulnerable-package>=1.2.3,<2.0.0
```

#### Secret Detected
```bash
# Remove secret from code
# Use environment variables instead
# API_KEY = os.environ["API_KEY"]

# If false positive, add to .trufflehogignore
echo "path/to/file.py" >> .trufflehogignore
```

#### Bandit False Positive
```python
# Add nosec comment for known-safe patterns
# nosec: B101 - assert used for testing
assert user.is_admin()  # nosec

# Or configure bandit in pyproject.toml
[tool.bandit]
exclude_dirs = ["tests", "migrations"]
skips = ["B101", "B601"]
```

---

## Review Gate

### Checks Performed

| Check | Tool | Config |
|-------|------|--------|
| Python linting | `ruff` | `pyproject.toml` `[tool.ruff]` |
| Type checking | `mypy` | `pyproject.toml` `[tool.mypy]` |
| Format check | `ruff format` | `pyproject.toml` `[tool.ruff.format]` |
| Import sorting | `ruff` (I001) | `pyproject.toml` `[tool.ruff.lint.isort]` |
| Complexity | `ruff` (C901) | `max-complexity = 10` |
| Diff review | Custom | Changed files only |

### Configuration (`quality-gates/review.yaml`)

```yaml
review_gate:
  enabled: true
  fail_on_error: true
  fail_on_warning: false
  
  linters:
    ruff:
      enabled: true
      config_file: pyproject.toml
      max_line_length: 120
      select: [E, F, I, UP, B, C4, SIM, T20]
      ignore: [E501, ERA001]  # Line length, comment style
    
    mypy:
      enabled: true
      config_file: pyproject.toml
      strict: true
      ignore_missing_imports: false
  
  formatters:
    ruff_format:
      enabled: true
      check_only: true  # Don't auto-fix in gate
  
  diff_review:
    enabled: true
    max_files: 50
    max_lines_per_file: 500
    ignore_patterns:
      - "*.lock"
      - "*.generated.*"
      - "migrations/*.py"
```

### Running Review Gate

```bash
# Full review
hermes-quality-gate review

# Lint only
hermes-quality-gate review --lint-only

# Type check only
hermes-quality-gate review --type-check

# Format check only
hermes-quality-gate review --format-check

# Show diff
hermes-quality-gate review --diff HEAD~1
```

### Common Issues & Fixes

#### Ruff Import Sorting (I001)
```bash
# Auto-fix
ruff check --select I --fix .

# Or configure in pyproject.toml
[tool.ruff.lint.isort]
known_first_party = ["my_package"]
```

#### MyPy Errors
```bash
# Run with details
mypy --show-error-codes src/

# Common fixes:
# - Add type annotations
# - Install stubs: pip install types-requests
# - Use # type: ignore[code] for specific lines
```

#### Line Length (E501)
```bash
# Configure in pyproject.toml
[tool.ruff]
line-length = 120

# Or auto-format
ruff format .
```

---

## Quality Gate

### Checks Performed

| Check | Tool | Threshold |
|-------|------|-----------|
| Unit tests | `pytest` | All pass |
| Coverage (line) | `pytest-cov` | ≥80% |
| Coverage (branch) | `pytest-cov` | ≥70% (optional) |
| Integration tests | `pytest` | All pass |
| Performance benchmarks | `pytest-benchmark` | No regression |
| Mutation testing | `mutmut` | ≥80% (optional) |

### Configuration (`quality-gates/quality.yaml`)

```yaml
quality_gate:
  enabled: true
  fail_on_coverage_below: true
  
  unit_tests:
    enabled: true
    command: "pytest -x -v"
    timeout: 120
    coverage:
      enabled: true
      type: line  # or branch
      threshold: 80
      fail_under: 80
      exclude:
        - "tests/"
        - "migrations/"
        - "*/conftest.py"
  
  integration_tests:
    enabled: true
    command: "pytest tests/integration -v"
    timeout: 300
    require_services: true  # Docker compose up
  
  benchmarks:
    enabled: false
    command: "pytest tests/benchmarks --benchmark-only"
    compare_with: "main"  # Compare with main branch
  
  mutation_testing:
    enabled: false
    tool: mutmut
    threshold: 80
    timeout: 600
```

### Running Quality Gate

```bash
# Full quality gate
hermes-quality-gate quality

# Unit tests only
hermes-quality-gate quality --unit-only

# With coverage report
hermes-quality-gate quality --coverage-report html

# Integration tests (requires services)
docker compose -f docker-compose.test.yml up -d
hermes-quality-gate quality --integration
docker compose -f docker-compose.test.yml down
```

### Coverage Configuration

```toml
# pyproject.toml
[tool.pytest.ini_options]
addopts = "--cov=src --cov-report=term-missing --cov-report=xml"
testpaths = ["tests"]

[tool.coverage.run]
source = ["src"]
omit = ["tests/*", "*/conftest.py", "*/migrations/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
```

---

## Release Gate

### Checks Performed

| Check | Description |
|-------|-------------|
| Git tag exists | Verifies signed tag |
| Tag matches version | `package.json`, `pyproject.toml` |
| Artifacts built | Source tarball, wheels, Docker images |
| Checksums generated | SHA256 for all artifacts |
| Release notes exist | `RELEASE_NOTES_vX.Y.Z.md` |
| Changelog updated | `CHANGELOG.md` has version section |

### Configuration (`quality-gates/release.yaml`)

```yaml
release_gate:
  enabled: true
  
  git:
    verify_signed_tag: true
    tag_prefix: "v"
    require_annotated: true
  
  version_consistency:
    enabled: true
    files:
      - "package.json"
      - "pyproject.toml"
      - "src/__version__.py"
  
  artifacts:
    enabled: true
    required:
      - "source_tarball"
      - "wheel"
      - "docker_images"
    checksum_algorithm: "sha256"
  
  release_notes:
    enabled: true
    required_sections:
      - "Overview"
      - "New Features"
      - "Improvements"
      - "Bug Fixes"
      - "Breaking Changes"
      - "Upgrade Guide"
  
  github_release:
    enabled: true
    draft: false
    prerelease: false
    generate_notes: false
```

### Running Release Gate

```bash
# Verify release artifacts
hermes-quality-gate release --tag v0.1.0-rc1

# Create release (requires permissions)
hermes-quality-gate release --create --tag v0.1.0-rc1
```

---

## Gate Results & Reporting

### Output Formats

```bash
# JSON for CI parsing
hermes-quality-gate run --all --format json > results.json

# JUnit XML for test reporting
hermes-quality-gate quality --format junit > test-results.xml

# SARIF for security
hermes-quality-gate security --format sarif > security.sarif

# Human readable (default)
hermes-quality-gate run --all
```

### Result Structure

```json
{
  "gate": "quality",
  "status": "passed",
  "duration_seconds": 45.2,
  "checks": [
    {
      "name": "unit_tests",
      "status": "passed",
      "duration": 30.1,
      "details": {
        "tests_run": 42,
        "passed": 42,
        "failed": 0,
        "coverage": {
          "line": 92.5,
          "branch": 87.3
        }
      }
    },
    {
      "name": "integration_tests",
      "status": "passed",
      "duration": 15.1,
      "details": {
        "tests_run": 8,
        "passed": 8
      }
    }
  ],
  "summary": "All quality checks passed (92.5% coverage)"
}
```

### CI Integration

```yaml
# GitHub Actions - upload SARIF
- name: Upload security results
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: security.sarif

# GitHub Actions - coverage
- name: Upload coverage
  uses: codecov/codecov-action@v3
  with:
    files: ./coverage.xml
```

---

## Custom Gates

### Creating a Custom Gate

```python
# quality_gates/gates/custom_gate.py
from quality_gates.gates.base import BaseGate, GateResult

class CustomGate(BaseGate):
    name = "custom"
    description = "Custom quality checks"
    
    async def run(self, workspace: Path, config: GateConfig) -> GateResult:
        issues = []
        
        # Custom check 1
        if not (workspace / "REQUIRED_FILE").exists():
            issues.append(GateIssue(
                severity="error",
                message="REQUIRED_FILE missing",
                file="REQUIRED_FILE"
            ))
        
        # Custom check 2
        for py_file in workspace.rglob("*.py"):
            content = py_file.read_text()
            if "TODO" in content and "FIXME" not in content:
                issues.append(GateIssue(
                    severity="warning",
                    message="TODO without FIXME reference",
                    file=str(py_file)
                ))
        
        return GateResult(
            passed=not any(i.severity == "error" for i in issues),
            issues=issues,
            metadata={"files_checked": len(list(workspace.rglob("*.py")))}
        )
```

### Registering Custom Gate

```yaml
# quality-gates/custom.yaml
custom_gate:
  enabled: true
  module: quality_gates.gates.custom_gate
  class: CustomGate
  config:
    required_files: ["README.md", "LICENSE", "REQUIRED_FILE"]
```

---

## Best Practices

### 1. Gate Order Matters
Run fast gates first (security, lint) → slow gates last (tests, integration)

### 2. Fail Fast
```yaml
# Stop on first failure
quality_gate:
  fail_fast: true
```

### 3. Cache Dependencies
```yaml
# In CI
- name: Cache pip
  uses: actions/cache@v3
  with:
    path: ~/.cache/pip
    key: pip-${{ hashFiles('requirements.txt') }}
```

### 4. Parallelize Independent Gates
```yaml
jobs:
  security:
    # runs independently
  review:
    # runs independently
  quality:
    needs: [security, review]  # depends on both
```

### 5. Gate as Code Review Aid
```bash
# Pre-push hook
#!/bin/bash
hermes-quality-gate run --gate review --diff HEAD~1
```

---

*See also: [Agent Development](agent-development.md) | [API Reference](api-reference.md) | [Architecture Decisions](architecture-decisions/adr-index.md)*