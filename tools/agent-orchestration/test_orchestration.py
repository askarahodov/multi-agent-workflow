"""
Basic tests for Harbor-Transfer-Portal multi-agent orchestration tooling.
"""

import os
import sys
import json
import tempfile
import subprocess
from pathlib import Path
import pytest

# Add the module to the path
sys.path.insert(0, str(Path(__file__).parent / "harbor_transfer_portal"))

# Import the modules we're testing
from agent_workspace import create_worktree, cleanup_worktree, get_agent_status, get_all_worktrees
from kanban_tools import create_child_tasks, attach_artifacts, get_task_graph


def test_agent_workspace_module_exists():
    """Test that the agent_workspace module can be imported."""
    from harbor_transfer_portal import agent_workspace
    assert agent_workspace is not None


def test_kanban_tools_module_exists():
    """Test that the kanban_tools module can be imported."""
    from harbor_transfer_portal import kanban_tools
    assert kanban_tools is not None


def test_create_worktree_directory_exists():
    """Test that worktree directory creation logic exists."""
    # This test validates the module structure
    assert callable(create_worktree)
    assert callable(cleanup_worktree)
    assert callable(get_agent_status)
    assert callable(get_all_worktrees)


def test_kanban_tools_functions_exist():
    """Test that kanban tools functions exist."""
    assert callable(create_child_tasks)
    assert callable(attach_artifacts)
    assert callable(get_task_graph)


def test_spawn_agent_script_exists():
    """Test that the spawn-agent.sh script exists and is executable."""
    script_path = Path("scripts/spawn-agent.sh")
    assert script_path.exists()
    assert os.access(script_path, os.X_OK)


def test_detect_hotspots_script_exists():
    """Test that the detect-hotspots.py script exists and is executable."""
    script_path = Path("scripts/detect-hotspots.py")
    assert script_path.exists()
    assert os.access(script_path, os.X_OK)


def test_project_structure():
    """Test that expected project structure exists."""
    expected_files = [
        "scripts/spawn-agent.sh",
        "scripts/detect-hotspots.py",
        "harbor_transfer_portal/agent_workspace.py",
        "harbor_transfer_portal/kanban_tools.py"
    ]
    
    for file_path in expected_files:
        assert Path(file_path).exists(), f"Expected file {file_path} does not exist"


def test_spawn_agent_help():
    """Test that spawn-agent.sh script accepts help/usage arguments."""
    # Test that the script exists and is executable
    script_path = Path("scripts/spawn-agent.sh")
    
    # Try to run with --help if supported, or at least check it's a valid script
    result = subprocess.run(
        ["bash", "-n", str(script_path)],
        capture_output=True,
        text=True
    )
    
    # bash -n should return 0 for syntactically valid scripts
    assert result.returncode == 0, f"Script has syntax errors: {result.stderr}"


def test_detect_hotspots_syntax():
    """Test that detect-hotspots.py has valid Python syntax."""
    script_path = Path("scripts/detect-hotspots.py")
    
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(script_path)],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, f"Python syntax error in detect-hotspots.py: {result.stderr}"


def test_agent_workspace_python_syntax():
    """Test that agent_workspace.py has valid Python syntax."""
    script_path = Path("harbor_transfer_portal/agent_workspace.py")
    
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(script_path)],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, f"Python syntax error in agent_workspace.py: {result.stderr}"


def test_kanban_tools_python_syntax():
    """Test that kanban_tools.py has valid Python syntax."""
    script_path = Path("harbor_transfer_portal/kanban_tools.py")
    
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(script_path)],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, f"Python syntax error in kanban_tools.py: {result.stderr}"


def test_scripts_are_executable():
    """Test that all expected scripts are executable."""
    scripts = [
        "scripts/spawn-agent.sh",
        "scripts/detect-hotspots.py"
    ]
    
    for script_path in scripts:
        path = Path(script_path)
        assert path.exists(), f"Script {script_path} does not exist"
        assert os.access(path, os.X_OK), f"Script {script_path} is not executable"


def test_module_imports():
    """Test that all expected modules can be imported."""
    try:
        # Test importing the modules directly
        import harbor_transfer_portal
        assert hasattr(harbor_transfer_portal, 'agent_workspace')
        assert hasattr(harbor_transfer_portal, 'kanban_tools')
        
        # Test importing specific functions
        from harbor_transfer_portal.agent_workspace import create_worktree, cleanup_worktree
        from harbor_transfer_portal.kanban_tools import create_child_tasks, attach_artifacts
        
    except ImportError as e:
        pytest.fail(f"Failed to import modules: {e}")


def test_kanaban_integration_structure():
    """Test the overall kanban integration structure."""
    # Check that the kanban_tools module has the expected interface
    from harbor_transfer_portal import kanban_tools
    
    # These functions should exist
    expected_functions = [
        'create_child_tasks',
        'attach_artifacts', 
        'get_task_graph',
        'promote_to_ready',
        'create_task_with_parents',
        'get_kanaban_task_info'
    ]
    
    for func_name in expected_functions:
        assert hasattr(kanban_tools, func_name), f"Missing function: {func_name}"
        assert callable(getattr(kanban_tools, func_name)), f"Function not callable: {func_name}"


def test_agent_workspace_functions():
    """Test the agent_workspace module interface."""
    from harbor_transfer_portal import agent_workspace
    
    # These functions should exist
    expected_functions = [
        'create_worktree',
        'cleanup_worktree',
        'get_agent_status',
        'scan_overlapping_modifications',
        'get_all_worktrees',
        'cleanup_all_worktrees'
    ]
    
    for func_name in expected_functions:
        assert hasattr(agent_workspace, func_name), f"Missing function: {func_name}"
        assert callable(getattr(agent_workspace, func_name)), f"Function not callable: {func_name}"


def test_scripts_documentation():
    """Test that scripts have basic documentation."""
    # Check spawn-agent.sh has shebang and comments
    with open("scripts/spawn-agent.sh", "r") as f:
        content = f.read()
        assert content.startswith("#!/usr/bin/env bash"), "spawn-agent.sh should start with shebang"
        assert "# Agent spawn script" in content, "spawn-agent.sh should have documentation"
    
    # Check detect-hotspots.py has module docstring
    with open("scripts/detect-hotspots.py", "r") as f:
        content = f.read()
        assert '"""' in content, "detect-hotspots.py should have docstring"
        assert "Hotspot detector" in content, "detect-hotspots.py should describe its purpose"


def test_module_documentation():
    """Test that modules have proper documentation."""
    # Check agent_workspace.py has module docstring
    with open("harbor_transfer_portal/agent_workspace.py", "r") as f:
        content = f.read()
        assert '"""' in content, "agent_workspace.py should have docstring"
        assert "Agent Workspace Manager" in content, "agent_workspace.py should describe its purpose"
    
    # Check kanban_tools.py has module docstring  
    with open("harbor_transfer_portal/kanban_tools.py", "r") as f:
        content = f.read()
        assert '"""' in content, "kanban_tools.py should have docstring"
        assert "Kanban integration helpers" in content, "kanban_tools.py should describe its purpose"


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])