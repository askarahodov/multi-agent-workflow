"""
Kanban integration helpers for multi-agent orchestration.

This module provides functions to integrate with the Hermes Kanban board,
including task creation, artifact attachment, and graph visualization.
"""

import subprocess
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# Configuration
KANBAN_BOARD_PATH = Path.home() / ".hermes" / "kanban" / "boards" / "me"
KANBAN_DB_PATH = KANBAN_BOARD_PATH / "kanban.db"
WORKSPACES_PATH = KANBAN_BOARD_PATH / "workspaces"


def _default_project_root() -> Path:
    """Return the repository root that contains this module (tools/agent-orchestration/orchestration_tools/)."""
    return Path(__file__).resolve().parents[3]


PROJECT_ROOT = Path(os.environ.get("ORCHESTRATION_PROJECT_ROOT") or _default_project_root())
PROJECT_SLUG = os.environ.get("ORCHESTRATION_PROJECT") or PROJECT_ROOT.name
TENANT = os.environ.get("ORCHESTRATION_TENANT")

# Global kanban client configuration
KANBAN_CONFIG = {
    "board_path": str(KANBAN_BOARD_PATH),
    "workspace_kind": "worktree",
    "workspace_path": str(WORKSPACES_PATH),
    "project": PROJECT_SLUG,
    "tenant": TENANT
}


def create_child_tasks(parent_id: str, task_specs: List[Dict[str, Any]]) -> List[str]:
    """Create child tasks for a parent kanban task.
    
    Args:
        parent_id: The parent task ID
        task_specs: List of task specifications (each must contain at least 'title' and 'assignee')
        
    Returns:
        List of created child task IDs
        
    Raises:
        RuntimeError: If task creation fails
    """
    created_task_ids = []
    
    for spec in task_specs:
        try:
            # Build kanban create command
            cmd = [
                "hermes", "kanban", "create",
                "--board", "me",
                "--workspace", "worktree",
                "--parent", parent_id,
                "--priority", str(spec.get("priority", 5)),
                "--project", PROJECT_SLUG
            ]
            if TENANT:
                cmd.extend(["--tenant", TENANT])
            
            # Add title
            title = spec.get("title", "Untitled Task")
            cmd.extend(["--title", title])
            
            # Add assignee
            assignee = spec.get("assignee")
            if assignee:
                cmd.extend(["--assignee", assignee])
            
            # Add skills if specified
            skills = spec.get("skills", [])
            if skills:
                for skill in skills:
                    cmd.extend(["--skill", skill])
            
            # Add max runtime if specified
            max_runtime = spec.get("max_runtime")
            if max_runtime:
                cmd.extend(["--max-runtime", str(max_runtime)])
            
            # Add model/provider if specified
            model = spec.get("model")
            if model:
                cmd.extend(["--model", model])
                provider = spec.get("provider")
                if provider:
                    cmd.extend(["--provider", provider])
            
            # Execute kanban create
            print(f"Creating task: {title} (parent: {parent_id})")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Extract task ID from output (assuming JSON output)
            try:
                output = json.loads(result.stdout)
                task_id = output.get("id")
                if task_id:
                    created_task_ids.append(task_id)
                    print(f"Created child task: {task_id}")
            except json.JSONDecodeError:
                # Parse output as text to extract task ID
                output = result.stdout.strip()
                if output:
                    # Try to find task ID in output (common format might be "Created task with ID: t_xxx")
                    import re
                    match = re.search(r't_[a-zA-Z0-9]+', output)
                    if match:
                        created_task_ids.append(match.group(0))
                        print(f"Created child task (extracted): {match.group(0)}")
                    else:
                        print(f"Warning: Could not extract task ID from output: {output}")
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to create child task '{spec.get('title', 'unknown')}': {e.stderr or e.stdout or str(e)}"
            print(f"[KANBAN_TOOLS] {error_msg}")
            raise RuntimeError(error_msg) from e
        except Exception as e:
            error_msg = f"Unexpected error creating child task '{spec.get('title', 'unknown')}': {str(e)}"
            print(f"[KANBAN_TOOLS] {error_msg}")
            raise RuntimeError(error_msg) from e
    
    return created_task_ids


def attach_artifacts(task_id: str, paths: List[str]) -> Dict[str, Any]:
    """Attach artifacts to a kanban task.
    
    Args:
        task_id: The target task ID
        paths: List of file paths to attach
        
    Returns:
        Dictionary containing attachment results
        
    Raises:
        RuntimeError: If artifact attachment fails
    """
    results = {
        "task_id": task_id,
        "attached": [],
        "failed": [],
        "total": len(paths)
    }
    
    for path in paths:
        if not Path(path).exists():
            error_msg = f"Path does not exist: {path}"
            print(f"[KANBAN_TOOLS] Warning: {error_msg}")
            results["failed"].append({"path": path, "error": error_msg})
            continue
        
        try:
            # Build kanban attach command
            cmd = [
                "hermes", "kanban", "attach",
                "--board", "me",
                task_id,
                path
            ]
            
            print(f"Attaching artifact: {path} to task {task_id}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            results["attached"].append({"path": path, "status": "success"})
            print(f"Successfully attached: {path}")
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to attach {path}: {e.stderr or e.stdout or str(e)}"
            print(f"[KANBAN_TOOLS] {error_msg}")
            results["failed"].append({"path": path, "error": error_msg})
    
    if results["failed"]:
        error_summary = "; ".join([f"{f['path']}: {f['error']}" for f in results["failed"]])
        raise RuntimeError(f"Failed to attach {len(results['failed'])} artifacts: {error_summary}")
    
    return results


def get_task_graph(task_id: str) -> Dict[str, Any]:
    """Get task dependency graph for visualization.
    
    Args:
        task_id: The target task ID
        
    Returns:
        Dictionary containing task graph information
        
    Raises:
        RuntimeError: If graph retrieval fails
    """
    try:
        # Get task details
        cmd = [
            "hermes", "kanban", "show",
            "--board", "me",
            task_id
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse task details (would normally use JSON output)
        # For now, return a structured representation
        task_info = {
            "task_id": task_id,
            "children": [],
            "parents": [],
            "dependencies": [],
            "siblings": []
        }
        
        # Try to get children
        try:
            children_cmd = [
                "hermes", "kanban", "list",
                "--board", "me",
                "--filter", f"parents:{task_id}"
            ]
            
            children_result = subprocess.run(
                children_cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Parse children (simplified)
            output_lines = children_result.stdout.strip().split('\n')
            for line in output_lines:
                if line.startswith("t_") and "|" in line:
                    child_id = line.split("|")[0].strip()
                    if child_id != task_id:
                        task_info["children"].append(child_id)
        except Exception as e:
            print(f"[KANBAN_TOOLS] Could not get children for {task_id}: {e}")
        
        # Try to get parents
        try:
            # This would normally use kanban show to get parents
            # For now, placeholder implementation
            task_info["parents"] = []
        except Exception as e:
            print(f"[KANBAN_TOOLS] Could not get parents for {task_id}: {e}")
        
        return task_info
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to get task graph for {task_id}: {e.stderr or e.stdout or str(e)}"
        print(f"[KANBAN_TOOLS] {error_msg}")
        raise RuntimeError(error_msg) from e


def promote_to_ready(task_id: str, reason: str = "Parent completed") -> bool:
    """Promote a task from todo to ready.
    
    Args:
        task_id: The target task ID
        reason: Reason for promotion
        
    Returns:
        True if promotion was successful, False otherwise
        
    Raises:
        RuntimeError: If promotion fails
    """
    try:
        # Use kanban promote command
        cmd = [
            "hermes", "kanban", "promote",
            "--board", "me",
            task_id,
            "--reason", reason
        ]
        
        print(f"Promoting task {task_id} to ready: {reason}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        print(f"Successfully promoted task {task_id} to ready")
        return True
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to promote task {task_id}: {e.stderr or e.stdout or str(e)}"
        print(f"[KANBAN_TOOLS] {error_msg}")
        return False


def create_task_with_parents(title: str, assignee: str, parent_ids: List[str], 
                             workspace: str = "worktree", branch: str = None) -> Dict[str, Any]:
    """Create a new task with multiple parent dependencies.
    
    Args:
        title: Task title
        assignee: Task assignee
        parent_ids: List of parent task IDs
        workspace: Workspace type (worktree, scratch, dir)
        branch: Branch name (optional)
        
    Returns:
        Dictionary containing task creation result
        
    Raises:
        RuntimeError: If task creation fails
    """
    try:
        # Build kanban create command
        cmd = [
            "hermes", "kanban", "create",
            "--board", "me",
            "--workspace", workspace,
            "--title", title,
            "--assignee", assignee
        ]
        
        # Add parents if specified
        if parent_ids:
            for parent_id in parent_ids:
                cmd.extend(["--parent", parent_id])
        
        # Add project and tenant
        cmd.extend(["--project", PROJECT_SLUG])
        if TENANT:
            cmd.extend(["--tenant", TENANT])
        
        # Add branch if specified
        if branch:
            cmd.extend(["--branch", branch])
        
        print(f"Creating task: {title} (parents: {parent_ids}, assignee: {assignee})")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse result to extract task info
        task_info = {
            "success": True,
            "title": title,
            "assignee": assignee,
            "parent_ids": parent_ids,
            "workspace": workspace,
            "branch": branch,
            "output": result.stdout,
            "error": None
        }
        
        # Try to extract task ID
        import re
        match = re.search(r't_[a-zA-Z0-9]+', result.stdout)
        if match:
            task_info["task_id"] = match.group(0)
        
        print(f"Successfully created task: {task_info.get('task_id', 'unknown')}")
        return task_info
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to create task '{title}': {e.stderr or e.stdout or str(e)}"
        print(f"[KANBAN_TOOLS] {error_msg}")
        
        return {
            "success": False,
            "title": title,
            "assignee": assignee,
            "parent_ids": parent_ids,
            "workspace": workspace,
            "branch": branch,
            "output": None,
            "error": error_msg
        }


def get_kanaban_task_info(task_id: str) -> Dict[str, Any]:
    """Get detailed information about a kanban task.
    
    Args:
        task_id: The target task ID
        
    Returns:
        Dictionary containing task information
        
    Raises:
        RuntimeError: If task info retrieval fails
    """
    try:
        # Use kanban show command
        cmd = [
            "hermes", "kanban", "show",
            "--board", "me",
            task_id
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse output (simplified - would need proper JSON parsing in real implementation)
        task_info = {
            "task_id": task_id,
            "raw_output": result.stdout,
            "success": True
        }
        
        return task_info
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to get task info for {task_id}: {e.stderr or e.stdout or str(e)}"
        print(f"[KANBAN_TOOLS] {error_msg}")
        raise RuntimeError(error_msg) from e