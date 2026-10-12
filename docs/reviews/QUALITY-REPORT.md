{
  "status": "failed",
  "tests": [
    {
      "name": "tester",
      "category": "quality_gate",
      "result": "failed",
      "executed": true,
      "evidence": "unit: failed (exit 1); integration: failed (exit 1)"
    },
    {
      "name": "reviewer",
      "category": "quality_gate",
      "result": "failed",
      "executed": true,
      "evidence": "architecture/style violations found"
    },
    {
      "name": "release_prep",
      "category": "quality_gate",
      "result": "passed",
      "executed": true,
      "evidence": "release candidate 0.1.0-rc ready and verifiable"
    }
  ],
  "commands": [],
  "failures": [
    {
      "id": "tester",
      "category": "quality_gate_failure",
      "command": "N/A",
      "expected": "passed",
      "actual": "failed",
      "evidence": "unit: failed (exit 1); integration: failed (exit 1)",
      "suspected_cause": "See evidence",
      "affected_files": []
    },
    {
      "id": "reviewer",
      "category": "quality_gate_failure",
      "command": "N/A",
      "expected": "passed",
      "actual": "failed",
      "evidence": "architecture/style violations found",
      "suspected_cause": "See evidence",
      "affected_files": []
    }
  ],
  "reproducibility": [],
  "coverage_if_available": null
}