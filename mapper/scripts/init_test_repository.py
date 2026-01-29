#!/usr/bin/env python3
"""Initialize test repository from existing mission files and test_clusters.

This script:
1. Reads existing mission files from temp/
2. Extracts complete test definitions
3. Creates repository files in test_repository/
4. Optionally syncs to database

Usage:
    python scripts/init_test_repository.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from test_repository_manager import TestRepositoryManager


def extract_tests_from_mission(mission_file: Path) -> tuple[str, list]:
    """Extract tests from a mission file.
    
    Returns:
        Tuple of (target_node, list of test definitions)
    """
    try:
        mission_data = json.loads(mission_file.read_text())
    except Exception as e:
        print(f"  Error reading {mission_file}: {e}")
        return None, []
    
    target_node = mission_data.get("target_node", "")
    if not target_node:
        print(f"  No target_node in {mission_file.name}")
        return None, []
    
    # Extract task ID from filename (e.g., TASK-3_mission.json -> TASK-3)
    task_id = mission_file.stem.replace("_mission", "")
    
    tests = []
    manager = TestRepositoryManager()
    
    # Extract from persona_tests
    for persona_test in mission_data.get("persona_tests", []):
        for tc in persona_test.get("test_cases", []):
            test_def = manager.extract_test_from_mission(
                test_case=tc,
                mission_data=mission_data,
                persona_test=persona_test,
                task_id=task_id
            )
            tests.append(test_def)
    
    # Handle legacy format
    for tc in mission_data.get("test_cases", []):
        if not any(t["id"] == tc.get("id") for t in tests):
            test_def = manager.extract_test_from_mission(
                test_case=tc,
                mission_data=mission_data,
                persona_test={"persona": tc.get("persona", "")},
                task_id=task_id
            )
            tests.append(test_def)
    
    return target_node, tests


def main():
    """Initialize test repository from mission files."""
    mapper_dir = Path(__file__).parent.parent
    temp_dir = mapper_dir / "temp"
    repo_dir = mapper_dir / "test_repository"
    
    print("\n=== Initializing Test Repository ===\n")
    
    # Ensure repository directory exists
    repo_dir.mkdir(parents=True, exist_ok=True)
    print(f"Repository directory: {repo_dir}")
    
    # Find all mission files
    mission_files = list(temp_dir.glob("*_mission.json"))
    print(f"Found {len(mission_files)} mission file(s) in {temp_dir}\n")
    
    if not mission_files:
        print("No mission files found. Nothing to initialize.")
        return
    
    # Group tests by node
    tests_by_node = {}
    
    for mission_file in mission_files:
        print(f"Processing: {mission_file.name}")
        target_node, tests = extract_tests_from_mission(mission_file)
        
        if target_node and tests:
            if target_node not in tests_by_node:
                tests_by_node[target_node] = []
            tests_by_node[target_node].extend(tests)
            print(f"  -> {len(tests)} test(s) for node '{target_node}'")
        else:
            print(f"  -> No tests extracted")
    
    print(f"\n=== Creating Repository Files ===\n")
    
    manager = TestRepositoryManager(mapper_dir=mapper_dir)
    
    for node_id, tests in tests_by_node.items():
        # Deduplicate tests by ID
        unique_tests = {}
        for test in tests:
            test_id = test["id"]
            if test_id in unique_tests:
                # Merge source_tasks
                existing = unique_tests[test_id]
                for task in test.get("source_tasks", []):
                    if task not in existing.get("source_tasks", []):
                        existing.setdefault("source_tasks", []).append(task)
                existing["updated_at"] = datetime.utcnow().isoformat()
            else:
                unique_tests[test_id] = test
        
        # Create repository data
        repo_data = {
            "node_id": node_id,
            "last_updated": datetime.utcnow().isoformat(),
            "tests": list(unique_tests.values())
        }
        
        # Save to file
        repo_file = repo_dir / f"{node_id}.json"
        repo_file.write_text(json.dumps(repo_data, indent=2))
        print(f"Created: {repo_file.name} ({len(unique_tests)} tests)")
    
    print(f"\n=== Repository Initialization Complete ===\n")
    print(f"Created {len(tests_by_node)} repository file(s)")
    print(f"Total tests: {sum(len(t) for t in tests_by_node.values())}")
    
    # List created files
    print("\nRepository files:")
    for repo_file in repo_dir.glob("*.json"):
        data = json.loads(repo_file.read_text())
        print(f"  - {repo_file.name}: {len(data.get('tests', []))} tests")


if __name__ == "__main__":
    main()
