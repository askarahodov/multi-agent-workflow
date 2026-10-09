"""
Agent Workspace Manager for Harbor-Transfer-Portal multi-agent orchestration.

This module provides functionality to manage git worktrees for agent tasks,
including creation, cleanup, status checking, and conflict detection.
"""

import json
import os
import subprocess
import sys
import time
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

# Configuration
PROJECT_ROOT = Path("/mnt/data/app/Harbor-Transfer-Portal")
WORKSPACES_ROOT = PROJECT_ROOT / ".worktrees"
KANBAN_DB_PATH = Path.home() / ".hermes" / "kanban" / "boards" / "me" / "kanban.db"

# Global registry to track active worktrees
ACTIVE_WORKTREES: Dict[str, Dict[str, Any]] = {}


def create_worktree(task_id: str, branch: str = None) -> str:
    """Create a git worktree for a given task ID and branch.
    
    Args:
        task_id: The kanban task ID
        branch: The branch name (defaults to "harbor-transfer-portal/{task_id}")
        
    Returns:
        The absolute path to the created worktree
        
    Raises:
        RuntimeError: If worktree creation fails
    """
    if branch is None:
        branch = f"harbor-transfer-portal/{task_id}"
    
    worktree_path = WORKSPACES_ROOT / task_id
    
    # Register the worktree creation attempt
    _log_worktree_operation(task_id, "create_attempt", {"branch": branch, "path": str(worktree_path)})
    
    try:
        # Ensure workspaces root exists
        worktree_path.mkdir(parents=True, exist_ok=True)
        
        # Check if branch exists locally
        branch_exists = _check_branch_exists(branch)
        
        if branch_exists:
            # Use existing branch
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), branch],
                cwd=str(PROJECT_ROOT),
                check=True,
                capture_output=True,
                text=True
            )
        else:
            # Create new branch from main
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), "main"],
                cwd=str(PROJECT_ROOT),
                check=True,
                capture_output=True,
                text=True
            )
            
            # Create and checkout the task branch
            subprocess.run(
                ["git", "checkout", "-b", branch],
                cwd=str(worktree_path),
                check=True,
                capture_output=True,
                text=True
            )
        
        # Update registry
        ACTIVE_WORKTREES[task_id] = {
            "path": str(worktree_path),
            "branch": branch,
            "created_at": datetime.datetime.now().isoformat(),
            "status": "active"
        }
        
        _log_worktree_operation(task_id, "created", {"path": str(worktree_path), "branch": branch})
        return str(worktree_path)
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to create worktree: {e.stderr or e.stdout or str(e)}"
        _log_worktree_operation(task_id, "create_failed", {"error": error_msg})
        raise RuntimeError(error_msg) from e


def cleanup_worktree(task_id: str) -> bool:
    """Clean up a worktree for a given task ID.
    
    Args:
        task_id: The kanban task ID
        
    Returns:
        True if cleanup was successful, False otherwise
    """
    if task_id not in ACTIVE_WORKTREES:
        # Try to find worktree in the filesystem
        worktree_path = WORKSPACES_ROOT / task_id
        if not worktree_path.exists():
            return False
    else:
        worktree_path = Path(ACTIVE_WORKTREES[task_id]["path"])
    
    try:
        # First, remove the worktree from git
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
            text=True
        )
        
        # Remove the directory if empty
        if worktree_path.exists():
            worktree_path.rmdir()
        
        # Update registry
        if task_id in ACTIVE_WORKTREES:
            del ACTIVE_WORKTREES[task_id]
        
        _log_worktree_operation(task_id, "cleaned_up", {"path": str(worktree_path)})
        return True
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to cleanup worktree: {e.stderr or e.stdout or str(e)}"
        _log_worktree_operation(task_id, "cleanup_failed", {"error": error_msg})
        return False


def get_agent_status(task_id: str) -> Dict[str, Any]:
    """Get the status of an agent worktree.
    
    Args:
        task_id: The kanban task ID
        
    Returns:
        Dictionary containing agent status information
        
    Raises:
        RuntimeError: If task_id is not found
    """
    if task_id not in ACTIVE_WORKTREES:
        raise RuntimeError(f"No active worktree found for task_id: {task_id}")
    
    worktree_info = ACTIVE_WORKTREES[task_id].copy()
    
    # Get tmux session info if available
    tmux_session = _get_tmux_session_for_task(task_id)
    worktree_info["tmux_session"] = tmux_session
    
    # Get last heartbeat time
    last_heartbeat = _get_last_heartbeat(task_id)
    worktree_info["last_heartbeat"] = last_heartbeat
    
    # Get git status
    git_status = _get_git_status(worktree_info["path"])
    worktree_info["git_status"] = git_status
    
    return worktree_info


def scan_overlapping_modifications(worktree_paths: List[str]) -> List[Dict[str, Any]]:
    """Scan for overlapping file modifications across multiple worktrees.
    
    Args:
        worktree_paths: List of worktree paths to scan
        
    Returns:
        List of detected conflicts with file paths and task IDs
    """
    conflicts = []
    
    # Get modified files for each worktree
    modified_files = {}
    for path in worktree_paths:
        task_id = Path(path).name
        try:
            modified = _get_modified_files(path)
            modified_files[task_id] = modified
        except Exception as e:
            _log_worktree_operation(task_id, "scan_error", {"error": str(e)})
            modified_files[task_id] = []
    
    # Check for overlapping files
    file_to_tasks = {}
    for task_id, files in modified_files.items():
        for file_path in files:
            if file_path in file_to_tasks:
                # Conflict detected
                conflicts.append({
                    "file": file_path,
                    "tasks": file_to_tasks[file_path] + [task_id],
                    "severity": "high"
                })
            else:
                file_to_tasks[file_path] = [task_id]
    
    return conflicts


def _check_branch_exists(branch_name: str) -> bool:
    """Check if a branch exists in the git repository."""
    try:
        result = subprocess.run(
            ["git", "branch", "--list", branch_name],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True
        )
        return result.returncode == 0 and branch_name in result.stdout
    except subprocess.CalledProcessError:
        return False


def _get_tmux_session_for_task(task_id: str) -> Optional[str]:
    """Get tmux session name for a given task ID."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            check=True
        )
        
        for session in result.stdout.strip().split('\n'):
            if f"agent-{task_id}-" in session:
                return session
        return None
        
    except subprocess.CalledProcessError:
        return None


def _get_last_heartbeat(task_id: str) -> Optional[str]:
    """Get the last heartbeat time for a task (placeholder implementation)."""
    # This would normally query the kanban database or monitoring system
    # For now, return the creation time from registry
    if task_id in ACTIVE_WORKTREES:
        return ACTIVE_WORKTREES[task_id]["created_at"]
    return None


def _get_git_status(worktree_path: str) -> Dict[str, Any]:
    """Get git status for a worktree."""
    try:
        # Get current branch
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )
        current_branch = branch_result.stdout.strip()
        
        # Get modified files
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )
        
        modified_files = []
        for line in status_result.stdout.strip().split('\n'):
            if line:
                # Extract file path (remove status prefix)
                file_path = line[3:].strip()
                modified_files.append(file_path)
        
        return {
            "current_branch": current_branch,
            "modified_files": modified_files,
            "modified_count": len(modified_files)
        }
        
    except subprocess.CalledProcessError as e:
        return {
            "current_branch": "unknown",
            "modified_files": [],
            "modified_count": 0,
            "error": str(e)
        }


def _get_modified_files(worktree_path: str) -> List[str]:
    """Get list of modified files in a worktree."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )
        
        modified_files = []
        for line in result.stdout.strip().split('\n'):
            if line:
                file_path = line[3:].strip()
                modified_files.append(file_path)
        
        return modified_files
        
    except subprocess.CalledProcessError:
        return []


def _log_worktree_operation(task_id: str, operation: str, details: Dict[str, Any]) -> None:
    """Log worktree operations for debugging and auditing."""
    timestamp = datetime.datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "task_id": task_id,
        "operation": operation,
        "details": details
    }
    
    # Log to stderr for visibility
    print(f"[AGENT_WORKSPACE] {timestamp} - {task_id} - {operation}: {details}")


def get_all_worktrees() -> List[Dict[str, Any]]:
    """Get information about all active worktrees."""
    return list(ACTIVE_WORKTREES.values())


def cleanup_all_worktrees() -> Dict[str, bool]:
    """Clean up all active worktrees."""
    results = {}
    for task_id in list(ACTIVE_WORKTREES.keys()):
        try:
            success = cleanup_worktree(task_id)
            results[task_id] = success
        except Exception as e:
            results[task_id] = False
            print(f"[AGENT_WORKSPACE] Error cleaning up worktree {task_id}: {e}")
    
    return results