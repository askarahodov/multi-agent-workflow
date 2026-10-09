#!/usr/bin/env python3

"""
Hotspot detector for Harbor-Transfer-Portal multi-agent orchestration.

This script scans recent kanban completions for metadata.hotspot flags and
compares them with git diff --name-only across worktrees to detect collisions.
"""

import subprocess
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

# Configuration
PROJECT_ROOT = Path("/mnt/data/app/Harbor-Transfer-Portal")
WORKSPACES_ROOT = PROJECT_ROOT / ".worktrees"
KANBAN_BOARD_PATH = Path.home() / ".hermes" / "kanban" / "boards" / "me"
KANBAN_DB_PATH = KANBAN_BOARD_PATH / "kanban.db"
SCAN_WINDOW_DAYS = 7  # Look back at least 7 days for recent completions
OUTPUT_FORMAT = "json"  # Can be "json", "text", or "summary"


def load_recent_completions() -> List[Dict[str, Any]]:
    """Load recent kanban task completions from the database."""
    completions = []
    
    try:
        # Check if kanban.db exists
        if not KANBAN_DB_PATH.exists():
            print(f"Warning: Kanban database not found at {KANBAN_DB_PATH}")
            return completions
        
        # This would normally use SQLite to query the kanban database
        # For now, implement a simplified version that looks for recent
        # completed task metadata files
        
        workspace_path = KANBAN_BOARD_PATH / "attachments"
        if not workspace_path.exists():
            return completions
        
        # Scan for completion metadata files
        for file_path in workspace_path.glob("*/metadata.json"):
            try:
                with open(file_path, 'r') as f:
                    metadata = json.load(f)
                
                # Filter for completed tasks in scan window
                if _is_recent_completion(metadata):
                    completions.append(metadata)
                    
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not read metadata file {file_path}: {e}")
                continue
                
    except Exception as e:
        print(f"Warning: Error loading recent completions: {e}")
    
    return completions


def _is_recent_completion(metadata: Dict[str, Any]) -> bool:
    """Check if a completion is within the scan window."""
    try:
        # Look for timestamp in metadata
        timestamp_str = metadata.get("timestamp") or metadata.get("completed_at")
        if not timestamp_str:
            return False
        
        # Parse timestamp (try different formats)
        for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]:
            try:
                completion_time = datetime.strptime(timestamp_str, fmt)
                break
            except ValueError:
                continue
        else:
            return False
        
        # Check if within scan window
        cutoff_time = datetime.now() - timedelta(days=SCAN_WINDOW_DAYS)
        return completion_time >= cutoff_time
        
    except Exception:
        return False


def get_worktree_modified_files(worktree_path: Path) -> List[str]:
    """Get list of modified files in a worktree using git diff."""
    try:
        # Get modified files using git status --porcelain
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=True
        )
        
        modified_files = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                # Extract file path (remove status prefix)
                file_path = line[3:].strip()
                modified_files.append(file_path)
        
        return modified_files
        
    except subprocess.CalledProcessError as e:
        print(f"Warning: Could not get modified files for {worktree_path}: {e}")
        return []
    except Exception as e:
        print(f"Warning: Error processing {worktree_path}: {e}")
        return []


def scan_worktrees_for_changes() -> Dict[str, List[str]]:
    """Scan all worktrees for modified files."""
    worktree_changes = {}
    
    if not WORKSPACES_ROOT.exists():
        print(f"Warning: Workspaces root not found at {WORKSPACES_ROOT}")
        return worktree_changes
    
    # Find all worktree directories
    for worktree_dir in WORKSPACES_ROOT.iterdir():
        if worktree_dir.is_dir():
            task_id = worktree_dir.name
            try:
                modified_files = get_worktree_modified_files(worktree_dir)
                if modified_files:
                    worktree_changes[task_id] = modified_files
            except Exception as e:
                print(f"Warning: Error scanning worktree {task_id}: {e}")
                continue
    
    return worktree_changes


def detect_collisions(completions: List[Dict[str, Any]], worktree_changes: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """Detect collisions between completion metadata hotspots and worktree changes."""
    collisions = []
    
    # Build index of files mentioned in hotspots
    hotspot_files = {}
    for completion in completions:
        task_id = completion.get("task_id", "unknown")
        metadata = completion.get("metadata", {})
        hotspots = metadata.get("hotspot", []) or []
        
        for file_path in hotspots:
            if file_path not in hotspot_files:
                hotspot_files[file_path] = []
            hotspot_files[file_path].append(task_id)
    
    # Check for matches with worktree changes
    for task_id, modified_files in worktree_changes.items():
        for file_path in modified_files:
            if file_path in hotspot_files:
                # Collision detected
                hotspot_tasks = hotspot_files[file_path]
                
                # Check if any of the hotspot tasks are the current task (self-collision)
                if task_id in hotspot_tasks:
                    severity = "self-reference"
                elif len(hotspot_tasks) > 1:
                    severity = "multi-collision"
                else:
                    severity = "collision"
                
                collision = {
                    "file": file_path,
                    "current_task": task_id,
                    "hotspot_tasks": hotspot_tasks,
                    "severity": severity,
                    "type": "hotspot_match"
                }
                
                collisions.append(collision)
                
                # Remove from index to avoid duplicate reports for same file
                hotspot_files.pop(file_path, None)
    
    # Also check for conflicts between worktrees (different tasks modifying same file)
    file_to_tasks = {}
    for task_id, modified_files in worktree_changes.items():
        for file_path in modified_files:
            if file_path in file_to_tasks:
                # Cross-worktree collision
                collision = {
                    "file": file_path,
                    "current_task": task_id,
                    "hotspot_tasks": file_to_tasks[file_path],
                    "severity": "cross-worktree",
                    "type": "cross_worktree_collision"
                }
                
                collisions.append(collision)
            else:
                file_to_tasks[file_path] = [task_id]
    
    return collisions


def analyze_comments_for_hotspots(completions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyze recent task completions for hotspot comments."""
    hotspot_comments = []
    
    # This would normally parse kanban comment threads
    # For now, look for hotspot comments in task metadata
    
    for completion in completions:
        task_id = completion.get("task_id", "unknown")
        metadata = completion.get("metadata", {})
        
        # Check for hotspot comments in comments
        comments = metadata.get("comments", [])
        for comment in comments:
            if "hotspot:" in comment.lower():
                hotspot_comments.append({
                    "task_id": task_id,
                    "comment": comment,
                    "file": _extract_file_from_hotspot_comment(comment)
                })
    
    return hotspot_comments


def _extract_file_from_hotspot_comment(comment: str) -> Optional[str]:
    """Extract file path from a hotspot comment."""
    # Look for patterns like "hotspot: <path> — <reason>"
    import re
    
    # Pattern: hotspot: followed by file path, then optional separator
    hotspot_match = re.search(r'hotspot:\s*([^\s—]+)', comment, re.IGNORECASE)
    if hotspot_match:
        return hotspot_match.group(1)
    
    return None


def generate_report(completions: List[Dict[str, Any]], collisions: List[Dict[str, Any]], 
                   hotspot_comments: List[Dict[str, Any]], worktree_changes: Dict[str, List[str]]) -> Dict[str, Any]:
    """Generate a comprehensive hotspot detection report."""
    
    # Summary statistics
    summary = {
        "total_completions": len(completions),
        "total_worktrees_scanned": len(worktree_changes),
        "total_files_modified": sum(len(files) for files in worktree_changes.values()),
        "total_collisions_detected": len(collisions),
        "hotspot_comments_found": len(hotspot_comments)
    }
    
    # Categorize collisions
    collision_types = {}
    for collision in collisions:
        ctype = collision["type"]
        if ctype not in collision_types:
            collision_types[ctype] = []
        collision_types[ctype].append(collision)
    
    # Generate recommendations
    recommendations = []
    
    if collisions:
        recommendations.append("Investigate highlighted collisions and resolve conflicting changes")
    
    # Check for high-severity collisions
    high_severity = [c for c in collisions if c.get("severity") in ["multi-collision", "cross-worktree"]]
    if high_severity:
        recommendations.append(f"Immediate attention required: {len(high_severity)} high-severity collisions detected")
    
    # Check for self-references (task modifying files it was warned about)
    self_refs = [c for c in collisions if c.get("severity") == "self-reference"]
    if self_refs:
        recommendations.append(f"Tasks should respect previous hotspot warnings: {len(self_refs)} self-references found")
    
    return {
        "summary": summary,
        "collision_types": collision_types,
        "high_severity_collisions": high_severity,
        "self_references": self_refs,
        "hotspot_comments": hotspot_comments,
        "recommendations": recommendations,
        "timestamp": datetime.now().isoformat()
    }


def output_report(report: Dict[str, Any], format: str = "json") -> None:
    """Output the report in the specified format."""
    
    if format == "json":
        print(json.dumps(report, indent=2, default=str))
    elif format == "text":
        _output_text_report(report)
    elif format == "summary":
        _output_summary_report(report)
    else:
        print(json.dumps(report, indent=2, default=str))


def _output_text_report(report: Dict[str, Any]) -> None:
    """Output a human-readable text report."""
    summary = report["summary"]
    collisions = report.get("high_severity_collisions", [])
    recommendations = report.get("recommendations", [])
    
    print("=== HOTSPOT DETECTION REPORT ===")
    print(f"Generated: {report['timestamp']}")
    print()
    print(f"Summary:")
    print(f"  - Total completions scanned: {summary['total_completions']}")
    print(f"  - Worktrees scanned: {summary['total_worktrees_scanned']}")
    print(f"  - Total files modified: {summary['total_files_modified']}")
    print(f"  - Collisions detected: {summary['total_collisions_detected']}")
    print(f"  - Hotspot comments found: {summary['hotspot_comments_found']}")
    print()
    
    if collisions:
        print("HIGH-SEVERITY COLLISIONS:")
        for collision in collisions:
            print(f"  - {collision['file']} (Task: {collision['current_task']})")
            print(f"    Severity: {collision['severity']}")
        print()
    
    if recommendations:
        print("RECOMMENDATIONS:")
        for rec in recommendations:
            print(f"  - {rec}")
        print()


def _output_summary_report(report: Dict[str, Any]) -> None:
    """Output a concise summary report."""
    summary = report["summary"]
    print(f"HOTSPOT SCAN: {summary['total_collisions_detected']} collisions detected")
    print(f"  - Files modified: {summary['total_files_modified']}")
    print(f"  - Worktrees: {summary['total_worktrees_scanned']}")
    
    collisions = report.get("high_severity_collisions", [])
    if collisions:
        print(f"  - HIGH SEVERITY: {len(collisions)} requires attention")
    
    self_refs = report.get("self_references", [])
    if self_refs:
        print(f"  - SELF REFERENCES: {len(self_refs)} tasks ignoring hotspot warnings")


def main() -> None:
    """Main function."""
    print("Starting hotspot detector...")
    
    # Load recent completions
    print("Loading recent completions...")
    completions = load_recent_completions()
    print(f"Found {len(completions)} recent completions")
    
    # Scan worktrees for changes
    print("Scanning worktrees for modified files...")
    worktree_changes = scan_worktrees_for_changes()
    print(f"Found changes in {len(worktree_changes)} worktrees")
    
    # Detect collisions
    print("Detecting collisions...")
    collisions = detect_collisions(completions, worktree_changes)
    print(f"Detected {len(collisions)} collisions")
    
    # Analyze comments for hotspots
    print("Analyzing hotspot comments...")
    hotspot_comments = analyze_comments_for_hotspots(completions)
    print(f"Found {len(hotspot_comments)} hotspot comments")
    
    # Generate report
    print("Generating report...")
    report = generate_report(completions, collisions, hotspot_comments, worktree_changes)
    
    # Output report
    output_report(report, OUTPUT_FORMAT)
    
    # Exit with appropriate code
    if collisions:
        print(f"\nFound {len(collisions)} collisions that may require attention.")
        sys.exit(1) if OUTPUT_FORMAT == "strict" else None
    else:
        print("\nNo collisions detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()