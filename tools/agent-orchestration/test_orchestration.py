"""
Basic tests for multi-agent orchestration tooling.
"""

import os
import sys
import subprocess
from pathlib import Path
import pytest

PACKAGE_DIR = Path(__file__).resolve().parent
DOCSTRING = '"""'

# Add the module to the import path
sys.path.insert(0, str(PACKAGE_DIR / "orchestration_tools"))

# Import the modules under test
from agent_workspace import create_worktree, cleanup_worktree, get_agent_status, get_all_worktrees
from kanban_tools import create_child_tasks, attach_artifacts, get_task_graph


def test_agent_workspace_module_exists():
    from orchestration_tools import agent_workspace
    assert agent_workspace is not None


def test_kanban_tools_module_exists():
    from orchestration_tools import kanban_tools
    assert kanban_tools is not None


def test_core_functions_are_callable():
    assert callable(create_worktree)
    assert callable(cleanup_worktree)
    assert callable(get_agent_status)
    assert callable(get_all_worktrees)
    assert callable(create_child_tasks)
    assert callable(attach_artifacts)
    assert callable(get_task_graph)


def test_spawn_agent_script_exists_and_executable():
    script_path = PACKAGE_DIR / "scripts" / "spawn-agent.sh"
    assert script_path.exists()
    assert os.access(script_path, os.X_OK)


def test_detect_hotspots_script_exists_and_executable():
    script_path = PACKAGE_DIR / "scripts" / "detect-hotspots.py"
    assert script_path.exists()
    assert os.access(script_path, os.X_OK)


def test_project_structure():
    expected_files = [
        "scripts/spawn-agent.sh",
        "scripts/detect-hotspots.py",
        "orchestration_tools/agent_workspace.py",
        "orchestration_tools/kanban_tools.py"
    ]
    for rel_path in expected_files:
        path = PACKAGE_DIR / rel_path
        assert path.exists(), f"Expected file {path} does not exist"


def test_spawn_agent_script_syntax():
    script_path = PACKAGE_DIR / "scripts" / "spawn-agent.sh"
    result = subprocess.run(
        ["bash", "-n", str(script_path)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Script has syntax errors: {result.stderr}"


def _py_compile(path):
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Python syntax error in {path}: {result.stderr}"


def test_scripts_and_modules_have_valid_syntax():
    _py_compile(PACKAGE_DIR / "scripts" / "detect-hotspots.py")
    _py_compile(PACKAGE_DIR / "orchestration_tools" / "agent_workspace.py")
    _py_compile(PACKAGE_DIR / "orchestration_tools" / "kanban_tools.py")


def test_module_imports():
    try:
        import orchestration_tools
        assert hasattr(orchestration_tools, "agent_workspace")
        assert hasattr(orchestration_tools, "kanban_tools")
        from orchestration_tools.agent_workspace import create_worktree
        from orchestration_tools.kanban_tools import create_child_tasks
    except ImportError as e:
        pytest.fail(f"Failed to import modules: {e}")


def test_kanban_tools_interface():
    from orchestration_tools import kanban_tools
    expected_functions = [
        "create_child_tasks",
        "attach_artifacts",
        "get_task_graph",
        "promote_to_ready",
        "create_task_with_parents",
        "get_kanaban_task_info"
    ]
    for func_name in expected_functions:
        assert hasattr(kanban_tools, func_name), f"Missing function: {func_name}"
        assert callable(getattr(kanban_tools, func_name)), f"Function not callable: {func_name}"


def test_agent_workspace_interface():
    from orchestration_tools import agent_workspace
    expected_functions = [
        "create_worktree",
        "cleanup_worktree",
        "get_agent_status",
        "scan_overlapping_modifications",
        "get_all_worktrees",
        "cleanup_all_worktrees"
    ]
    for func_name in expected_functions:
        assert hasattr(agent_workspace, func_name), f"Missing function: {func_name}"
        assert callable(getattr(agent_workspace, func_name)), f"Function not callable: {func_name}"


def test_scripts_documentation():
    with open(PACKAGE_DIR / "scripts" / "spawn-agent.sh") as f:
        content = f.read()
    assert content.startswith("#!/usr/bin/env bash"), "spawn-agent.sh should start with shebang"
    assert "# Agent spawn script" in content, "spawn-agent.sh should have documentation"

    with open(PACKAGE_DIR / "scripts" / "detect-hotspots.py") as f:
        content = f.read()
    assert DOCSTRING in content, "detect-hotspots.py should have docstring"
    assert "Hotspot detector" in content, "detect-hotspots.py should describe its purpose"


def test_module_documentation():
    with open(PACKAGE_DIR / "orchestration_tools" / "agent_workspace.py") as f:
        content = f.read()
    assert DOCSTRING in content, "agent_workspace.py should have docstring"
    assert "Agent Workspace Manager" in content, "agent_workspace.py should describe its purpose"

    with open(PACKAGE_DIR / "orchestration_tools" / "kanban_tools.py") as f:
        content = f.read()
    assert DOCSTRING in content, "kanban_tools.py should have docstring"
    assert "Kanban integration helpers" in content, "kanban_tools.py should describe its purpose"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])