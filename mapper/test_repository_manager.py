"""Test Repository Manager - Aggregated Test Storage with LLM Analysis.

This module manages a consolidated test repository where tests from multiple
task missions are aggregated, deduplicated, and managed. Files serve as the
source of truth for test definitions, while the database provides fast indexing.

Key features:
- File-based test storage (git-friendly, LLM-friendly)
- LLM-powered conflict and duplicate detection
- Database sync for graph enrichment
- Test lifecycle management (active, deprecated, conflicting)
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from uuid import UUID

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class SimpleLLM:
    """Simple LLM wrapper for test analysis."""
    
    def __init__(self, api_url: str, api_key: str, model_name: str = "openai/gpt-oss-120b"):
        self.api_url = api_url
        self.api_key = api_key
        self.model_name = model_name
    
    def invoke(self, prompt: str) -> str:
        """Invoke LLM with a prompt and return response."""
        url = f"{self.api_url}/chat/completions" if "/llm" in self.api_url else f"{self.api_url}/llm/chat/completions"
        
        headers = {
            "Authorization": f"Basic {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 4000,
            "response_format": {"type": "json_object"}
        }
        
        try:
            with httpx.Client(verify=False, timeout=60.0) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                choices = data.get("choices", [])
                if not choices:
                    return ""
                
                message = choices[0].get("message", {})
                content = message.get("content")
                if content and content != "null":
                    return content
                
                reasoning = message.get("reasoning") or message.get("reasoning_content")
                return reasoning or ""
        except Exception as e:
            logger.warning(f"LLM invocation failed: {e}")
            return ""


class TestRepositoryManager:
    """Manages the aggregated test repository with LLM-powered analysis."""
    
    def __init__(
        self,
        project_id: Optional[str] = None,
        mapper_dir: Optional[Path] = None,
        repository_dir: Optional[Path] = None
    ):
        """Initialize TestRepositoryManager.
        
        Args:
            project_id: UUID of the project
            mapper_dir: Path to the mapper directory
            repository_dir: Path to the test repository directory (default: mapper/test_repository)
        """
        self.project_id = project_id
        self.mapper_dir = mapper_dir or Path(__file__).parent
        self.repository_dir = repository_dir or (self.mapper_dir / "test_repository")
        
        # Ensure repository directory exists
        self.repository_dir.mkdir(parents=True, exist_ok=True)
        
        # Load environment
        env_file = self.mapper_dir / ".env"
        if env_file.exists():
            load_dotenv(env_file)
        
        # Initialize LLM for analysis
        self.llm = None
        api_url = os.getenv("NUTANIX_API_URL")
        api_key = os.getenv("NUTANIX_API_KEY")
        if api_url and api_key:
            self.llm = SimpleLLM(api_url, api_key)
    
    def get_repository_file(self, node_id: str) -> Path:
        """Get the repository file path for a node."""
        return self.repository_dir / f"{node_id}.json"
    
    def load_repository(self, node_id: str) -> Dict[str, Any]:
        """Load tests for a node from the repository file.
        
        Args:
            node_id: The semantic graph node ID
            
        Returns:
            Repository data with node_id, last_updated, and tests list
        """
        repo_file = self.get_repository_file(node_id)
        
        if repo_file.exists():
            try:
                data = json.loads(repo_file.read_text())
                logger.info(f"Loaded repository for node '{node_id}': {len(data.get('tests', []))} tests")
                return data
            except Exception as e:
                logger.warning(f"Failed to load repository for node '{node_id}': {e}")
        
        # Return empty repository structure
        return {
            "node_id": node_id,
            "last_updated": None,
            "tests": []
        }
    
    def save_repository(self, node_id: str, data: Dict[str, Any]) -> bool:
        """Save repository data to file.
        
        Args:
            node_id: The semantic graph node ID
            data: Repository data to save
            
        Returns:
            True if save succeeded
        """
        try:
            data["last_updated"] = datetime.utcnow().isoformat()
            repo_file = self.get_repository_file(node_id)
            repo_file.write_text(json.dumps(data, indent=2))
            logger.info(f"Saved repository for node '{node_id}': {len(data.get('tests', []))} tests")
            return True
        except Exception as e:
            logger.error(f"Failed to save repository for node '{node_id}': {e}")
            return False
    
    def list_repositories(self) -> List[Dict[str, Any]]:
        """List all repository files with summary info.
        
        Returns:
            List of repository summaries
        """
        repositories = []
        
        for repo_file in self.repository_dir.glob("*.json"):
            try:
                data = json.loads(repo_file.read_text())
                repositories.append({
                    "node_id": data.get("node_id", repo_file.stem),
                    "test_count": len(data.get("tests", [])),
                    "last_updated": data.get("last_updated"),
                    "file_path": str(repo_file.relative_to(self.mapper_dir))
                })
            except Exception as e:
                logger.warning(f"Failed to read repository file {repo_file}: {e}")
        
        return repositories
    
    def extract_test_from_mission(self, test_case: Dict[str, Any], mission_data: Dict[str, Any], 
                                   persona_test: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        """Extract a complete test definition from mission data.
        
        Args:
            test_case: The test case from persona_tests
            mission_data: The full mission data
            persona_test: The persona test block containing this test
            task_id: The task ID that generated this test
            
        Returns:
            Complete test definition for repository
        """
        now = datetime.utcnow().isoformat()
        
        return {
            "id": test_case.get("id", ""),
            "purpose": test_case.get("purpose", ""),
            "persona": test_case.get("persona", persona_test.get("persona", "")),
            "source_tasks": [task_id],
            "status": "active",
            "navigation_path": persona_test.get("navigation_path", []),
            "gateway_plan": persona_test.get("gateway_plan", {}),
            "verification": test_case.get("verification", {}),
            "execution_steps": test_case.get("steps", []),
            "action_type": test_case.get("action_type", "verify"),
            "component_selector": test_case.get("component_selector"),
            "component_role": test_case.get("component_role"),
            "field_selectors": test_case.get("field_selectors", {}),
            "test_data": test_case.get("test_data", {}),
            "created_at": now,
            "updated_at": now
        }
    
    def analyze_with_llm(self, new_tests: List[Dict[str, Any]], 
                          existing_tests: List[Dict[str, Any]],
                          task_id: str) -> Dict[str, Any]:
        """Use LLM to analyze new tests vs existing tests.
        
        Args:
            new_tests: List of new test definitions
            existing_tests: List of existing test definitions
            task_id: The task ID generating these tests
            
        Returns:
            Analysis result with decisions for each test
        """
        if not self.llm:
            # Without LLM, default to adding all tests
            logger.warning("LLM not available, defaulting to 'add' for all new tests")
            return {
                "decisions": [
                    {"test_id": t["id"], "action": "add", "reason": "LLM not available"}
                    for t in new_tests
                ]
            }
        
        if not existing_tests:
            # No existing tests, add all
            return {
                "decisions": [
                    {"test_id": t["id"], "action": "add", "reason": "No existing tests"}
                    for t in new_tests
                ]
            }
        
        # Build prompt for LLM analysis
        new_tests_summary = "\n".join([
            f"- {t['id']}: {t['purpose']} (persona: {t.get('persona', 'N/A')})"
            for t in new_tests
        ])
        
        existing_tests_summary = "\n".join([
            f"- {t['id']}: {t['purpose']} (persona: {t.get('persona', 'N/A')}, status: {t.get('status', 'active')})"
            for t in existing_tests
        ])
        
        prompt = f"""Analyze these test cases for a QA automation system.

Compare NEW tests from {task_id} with EXISTING tests in the repository.

NEW TESTS:
{new_tests_summary}

EXISTING TESTS:
{existing_tests_summary}

For each NEW test, determine the appropriate action:
- "add": Test is unique and should be added to the repository
- "duplicate": Test verifies the same thing as an existing test (skip it)
- "conflict": Test contradicts an existing test (flag for review)
- "merge": Test is similar but adds value to an existing test (combine them)

Consider:
1. Same persona + same verification = likely duplicate
2. Same persona + contradicting expectations = conflict
3. Different personas testing same feature = NOT duplicates (both needed)
4. Similar tests that could share navigation = merge candidates

Respond with JSON:
{{
  "decisions": [
    {{
      "test_id": "id of new test",
      "action": "add|duplicate|conflict|merge",
      "reason": "brief explanation",
      "merge_with": "existing_test_id (only if action is merge)"
    }}
  ]
}}
"""
        
        try:
            response = self.llm.invoke(prompt)
            if response:
                result = json.loads(response)
                logger.info(f"LLM analysis complete: {len(result.get('decisions', []))} decisions")
                return result
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
        
        # Fallback: add all tests
        return {
            "decisions": [
                {"test_id": t["id"], "action": "add", "reason": "LLM analysis failed, defaulting to add"}
                for t in new_tests
            ]
        }
    
    def merge_new_tests(self, node_id: str, new_tests: List[Dict[str, Any]], 
                         task_id: str) -> Dict[str, Any]:
        """Merge new tests from a task mission into the repository.
        
        Args:
            node_id: The target node ID
            new_tests: List of new test definitions
            task_id: The task ID generating these tests
            
        Returns:
            Merge result with counts and decisions
        """
        result = {
            "success": True,
            "added": 0,
            "duplicates": 0,
            "conflicts": 0,
            "merged": 0,
            "decisions": [],
            "warnings": []
        }
        
        if not new_tests:
            result["warnings"].append("No new tests to merge")
            return result
        
        # Load existing repository
        repo_data = self.load_repository(node_id)
        existing_tests = repo_data.get("tests", [])
        
        # Analyze with LLM
        analysis = self.analyze_with_llm(new_tests, existing_tests, task_id)
        decisions = {d["test_id"]: d for d in analysis.get("decisions", [])}
        
        # Process each new test based on LLM decision
        for test in new_tests:
            test_id = test["id"]
            decision = decisions.get(test_id, {"action": "add", "reason": "No decision from LLM"})
            action = decision.get("action", "add")
            
            result["decisions"].append({
                "test_id": test_id,
                "action": action,
                "reason": decision.get("reason", "")
            })
            
            if action == "add":
                # Add new test to repository
                existing_tests.append(test)
                result["added"] += 1
                logger.info(f"Added test '{test_id}' to repository for node '{node_id}'")
                
            elif action == "duplicate":
                # Skip duplicate, but update source_tasks of existing test
                result["duplicates"] += 1
                for existing in existing_tests:
                    if existing["id"] == test_id or (
                        existing.get("purpose") == test.get("purpose") and 
                        existing.get("persona") == test.get("persona")
                    ):
                        if task_id not in existing.get("source_tasks", []):
                            existing.setdefault("source_tasks", []).append(task_id)
                        existing["updated_at"] = datetime.utcnow().isoformat()
                        break
                logger.info(f"Skipped duplicate test '{test_id}'")
                
            elif action == "conflict":
                # Add with conflicting status for review
                test["status"] = "conflicting"
                existing_tests.append(test)
                result["conflicts"] += 1
                result["warnings"].append(f"Conflict detected: {test_id} - {decision.get('reason', '')}")
                logger.warning(f"Added conflicting test '{test_id}'")
                
            elif action == "merge":
                # Merge with existing test
                merge_with = decision.get("merge_with")
                merged = False
                for existing in existing_tests:
                    if existing["id"] == merge_with:
                        # Add source task
                        if task_id not in existing.get("source_tasks", []):
                            existing.setdefault("source_tasks", []).append(task_id)
                        # Merge verification points
                        existing_verification = existing.get("verification", {})
                        new_verification = test.get("verification", {})
                        for key, value in new_verification.items():
                            if key not in existing_verification:
                                existing_verification[key] = value
                            elif isinstance(value, list) and isinstance(existing_verification[key], list):
                                existing_verification[key] = list(set(existing_verification[key] + value))
                        existing["verification"] = existing_verification
                        existing["updated_at"] = datetime.utcnow().isoformat()
                        merged = True
                        break
                
                if merged:
                    result["merged"] += 1
                    logger.info(f"Merged test '{test_id}' with '{merge_with}'")
                else:
                    # Couldn't find merge target, add as new
                    existing_tests.append(test)
                    result["added"] += 1
                    result["warnings"].append(f"Merge target '{merge_with}' not found, added as new")
        
        # Save updated repository
        repo_data["tests"] = existing_tests
        if self.save_repository(node_id, repo_data):
            logger.info(f"Repository updated for node '{node_id}': "
                       f"added={result['added']}, duplicates={result['duplicates']}, "
                       f"conflicts={result['conflicts']}, merged={result['merged']}")
        else:
            result["success"] = False
            result["warnings"].append("Failed to save repository")
        
        return result
    
    def sync_to_database(self, node_id: str, api_base_url: str = "http://localhost:8001") -> Dict[str, Any]:
        """Sync repository tests to the database via API.
        
        Args:
            node_id: The node ID to sync
            api_base_url: Base URL for the API
            
        Returns:
            Sync result with counts
        """
        result = {
            "success": True,
            "synced": 0,
            "errors": []
        }
        
        repo_data = self.load_repository(node_id)
        tests = repo_data.get("tests", [])
        
        for test in tests:
            if test.get("status") == "deprecated":
                continue  # Skip deprecated tests
            
            try:
                cluster_data = {
                    "project_id": self.project_id,
                    "task_id": test.get("source_tasks", [None])[0],  # Use first source task
                    "cluster_name": node_id,
                    "test_case_id": test["id"],
                    "target_node": node_id,
                    "purpose": test.get("purpose", ""),
                    "mission_file": f"test_repository/{node_id}.json",
                    "persona": test.get("persona", ""),
                    "verification": test.get("verification", {}),
                    "status": test.get("status", "active")
                }
                
                with httpx.Client(timeout=10.0) as client:
                    response = client.post(
                        f"{api_base_url}/api/clusters",
                        json=cluster_data
                    )
                    if response.status_code == 200:
                        result["synced"] += 1
                    else:
                        result["errors"].append(f"Failed to sync test '{test['id']}': {response.text}")
                        
            except Exception as e:
                result["errors"].append(f"Error syncing test '{test['id']}': {e}")
        
        if result["errors"]:
            result["success"] = False
            
        logger.info(f"Database sync for node '{node_id}': synced={result['synced']}, errors={len(result['errors'])}")
        return result
    
    def update_test_status(self, node_id: str, test_id: str, status: str, 
                           reason: Optional[str] = None) -> bool:
        """Update the status of a test in the repository.
        
        Args:
            node_id: The node ID
            test_id: The test ID to update
            status: New status (active, deprecated, conflicting)
            reason: Optional reason for status change
            
        Returns:
            True if update succeeded
        """
        repo_data = self.load_repository(node_id)
        tests = repo_data.get("tests", [])
        
        for test in tests:
            if test["id"] == test_id:
                test["status"] = status
                test["updated_at"] = datetime.utcnow().isoformat()
                if reason:
                    test["status_reason"] = reason
                
                if self.save_repository(node_id, repo_data):
                    logger.info(f"Updated test '{test_id}' status to '{status}'")
                    return True
                return False
        
        logger.warning(f"Test '{test_id}' not found in node '{node_id}'")
        return False
    
    def get_test(self, node_id: str, test_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific test from the repository.
        
        Args:
            node_id: The node ID
            test_id: The test ID
            
        Returns:
            Test definition or None if not found
        """
        repo_data = self.load_repository(node_id)
        for test in repo_data.get("tests", []):
            if test["id"] == test_id:
                return test
        return None
    
    def get_tests_by_persona(self, node_id: str, persona: str) -> List[Dict[str, Any]]:
        """Get all tests for a specific persona.
        
        Args:
            node_id: The node ID
            persona: The persona name
            
        Returns:
            List of tests for the persona
        """
        repo_data = self.load_repository(node_id)
        return [
            test for test in repo_data.get("tests", [])
            if test.get("persona", "").lower() == persona.lower()
            and test.get("status") != "deprecated"
        ]


# CLI interface for testing
if __name__ == "__main__":
    import sys
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    
    manager = TestRepositoryManager()
    
    if len(sys.argv) < 2:
        console.print("\n[bold cyan]Test Repository Manager[/bold cyan]\n")
        console.print("Usage:")
        console.print("  python test_repository_manager.py list                    # List all repositories")
        console.print("  python test_repository_manager.py show <node_id>          # Show tests for a node")
        console.print("  python test_repository_manager.py sync <node_id>          # Sync node to database")
        console.print("  python test_repository_manager.py deprecate <node_id> <test_id>  # Deprecate a test")
        sys.exit(0)
    
    command = sys.argv[1]
    
    if command == "list":
        repos = manager.list_repositories()
        if not repos:
            console.print("[yellow]No repositories found[/yellow]")
        else:
            table = Table(title="Test Repositories")
            table.add_column("Node ID", style="cyan")
            table.add_column("Tests", style="green")
            table.add_column("Last Updated", style="yellow")
            
            for repo in repos:
                table.add_row(
                    repo["node_id"],
                    str(repo["test_count"]),
                    repo.get("last_updated", "N/A")
                )
            console.print(table)
    
    elif command == "show" and len(sys.argv) > 2:
        node_id = sys.argv[2]
        repo_data = manager.load_repository(node_id)
        tests = repo_data.get("tests", [])
        
        if not tests:
            console.print(f"[yellow]No tests found for node '{node_id}'[/yellow]")
        else:
            console.print(f"\n[bold cyan]Tests for node '{node_id}'[/bold cyan]\n")
            for test in tests:
                status_color = "green" if test.get("status") == "active" else "red"
                console.print(f"[{status_color}]{test['id']}[/{status_color}]")
                console.print(f"  Purpose: {test.get('purpose', 'N/A')[:80]}...")
                console.print(f"  Persona: {test.get('persona', 'N/A')}")
                console.print(f"  Status: {test.get('status', 'active')}")
                console.print(f"  Source Tasks: {', '.join(test.get('source_tasks', []))}")
                console.print()
    
    elif command == "sync" and len(sys.argv) > 2:
        node_id = sys.argv[2]
        result = manager.sync_to_database(node_id)
        if result["success"]:
            console.print(f"[green]Synced {result['synced']} tests to database[/green]")
        else:
            console.print(f"[red]Sync failed with {len(result['errors'])} errors[/red]")
            for error in result["errors"]:
                console.print(f"  - {error}")
    
    elif command == "deprecate" and len(sys.argv) > 3:
        node_id = sys.argv[2]
        test_id = sys.argv[3]
        if manager.update_test_status(node_id, test_id, "deprecated"):
            console.print(f"[green]Deprecated test '{test_id}'[/green]")
        else:
            console.print(f"[red]Failed to deprecate test '{test_id}'[/red]")
    
    else:
        console.print(f"[red]Unknown command: {command}[/red]")
