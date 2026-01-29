"""Cluster Manager - Test Clustering, Conflict Detection, and Graph Tagging.

This module handles:
1. Clustering test cases by feature/page (target_node)
2. Detecting conflicts between new and existing tests
3. Tagging semantic_graph.json nodes with related tests
4. Persisting test metadata to PostgreSQL for impact analysis
5. Integration with TestRepositoryManager for aggregated test storage
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

# Import TestRepositoryManager (lazy import to avoid circular dependencies at module load)
_test_repository_manager = None

def get_test_repository_manager(project_id: Optional[str] = None, mapper_dir: Optional[Path] = None):
    """Get or create a TestRepositoryManager instance."""
    global _test_repository_manager
    if _test_repository_manager is None:
        from test_repository_manager import TestRepositoryManager
        _test_repository_manager = TestRepositoryManager(project_id=project_id, mapper_dir=mapper_dir)
    return _test_repository_manager


class SimpleLLM:
    """Simple LLM wrapper for conflict detection."""
    
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
            "max_tokens": 2000,
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


class ClusterManager:
    """Manages test clustering, conflict detection, and graph tagging."""
    
    def __init__(
        self,
        project_id: Optional[str] = None,
        mapper_dir: Optional[Path] = None,
        db_url: Optional[str] = None
    ):
        """Initialize ClusterManager.
        
        Args:
            project_id: UUID of the project (for DB operations)
            mapper_dir: Path to the mapper directory
            db_url: PostgreSQL connection URL (optional, for direct DB access)
        """
        self.project_id = project_id
        self.mapper_dir = mapper_dir or Path(__file__).parent
        self.db_url = db_url or os.getenv("DATABASE_URL")
        
        # Load environment
        env_file = self.mapper_dir / ".env"
        if env_file.exists():
            load_dotenv(env_file)
        
        # Initialize LLM for conflict detection
        self.llm = None
        api_url = os.getenv("NUTANIX_API_URL")
        api_key = os.getenv("NUTANIX_API_KEY")
        if api_url and api_key:
            self.llm = SimpleLLM(api_url, api_key)
    
    def load_semantic_graph(self, graph_file: str = "semantic_graph.json") -> Dict[str, Any]:
        """Load semantic graph from file."""
        graph_path = self.mapper_dir / graph_file
        if graph_path.exists():
            try:
                return json.loads(graph_path.read_text())
            except Exception as e:
                logger.warning(f"Failed to load semantic graph: {e}")
        return {"nodes": [], "edges": []}
    
    def save_semantic_graph(self, graph: Dict[str, Any], graph_file: str = "semantic_graph.json"):
        """Save semantic graph to file."""
        graph_path = self.mapper_dir / graph_file
        try:
            graph_path.write_text(json.dumps(graph, indent=2))
            logger.info(f"Saved semantic graph to {graph_path}")
        except Exception as e:
            logger.error(f"Failed to save semantic graph: {e}")
    
    def find_cluster_name(self, target_node: str) -> str:
        """Determine cluster name from target node.
        
        The cluster name is derived from the target node, which corresponds
        to a page/feature in the semantic graph.
        
        Args:
            target_node: The semantic graph node ID (e.g., "sales_bookings")
            
        Returns:
            Cluster name (same as target_node for now, could be hierarchical later)
        """
        # For now, use the target_node as the cluster name
        # In the future, we could group related nodes into clusters
        # e.g., "sales_bookings" and "sales_pipeline" -> "sales"
        return target_node
    
    def extract_test_cases_from_mission(self, mission_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract all test cases from a mission file.
        
        Args:
            mission_data: Parsed mission JSON
            
        Returns:
            List of test case metadata
        """
        test_cases = []
        target_node = mission_data.get("target_node", "")
        ticket_id = mission_data.get("ticket_id", "")
        mission_file = f"temp/{ticket_id}_mission.json" if ticket_id else None
        
        # Extract from persona_tests
        persona_tests = mission_data.get("persona_tests", [])
        for persona_test in persona_tests:
            persona = persona_test.get("persona", "")
            for tc in persona_test.get("test_cases", []):
                test_cases.append({
                    "test_case_id": tc.get("id", ""),
                    "purpose": tc.get("purpose", ""),
                    "target_node": target_node,
                    "cluster_name": self.find_cluster_name(target_node),
                    "mission_file": mission_file,
                    "persona": persona,
                    "verification": tc.get("verification", {}),
                    "action_type": tc.get("action_type", ""),
                    "component_role": tc.get("component_role", ""),
                })
        
        # Also extract from top-level test_cases (legacy format)
        for tc in mission_data.get("test_cases", []):
            if not any(t["test_case_id"] == tc.get("id") for t in test_cases):
                test_cases.append({
                    "test_case_id": tc.get("id", ""),
                    "purpose": tc.get("purpose", ""),
                    "target_node": target_node,
                    "cluster_name": self.find_cluster_name(target_node),
                    "mission_file": mission_file,
                    "persona": tc.get("persona", ""),
                    "verification": tc.get("verification", {}),
                    "action_type": tc.get("action_type", ""),
                    "component_role": tc.get("component_role", ""),
                })
        
        return test_cases
    
    def get_existing_tests_for_cluster(self, cluster_name: str, graph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get existing tests from semantic graph for a cluster.
        
        Args:
            cluster_name: The cluster/node name
            graph: The semantic graph data
            
        Returns:
            List of existing test metadata
        """
        for node in graph.get("nodes", []):
            if node.get("id") == cluster_name or node.get("semantic_name") == cluster_name:
                return node.get("related_tests", [])
        return []
    
    def check_conflicts(
        self,
        new_tests: List[Dict[str, Any]],
        existing_tests: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Check for conflicts between new and existing tests.
        
        Uses LLM to detect contradictions in test purposes/verifications.
        
        Args:
            new_tests: List of new test case metadata
            existing_tests: List of existing test metadata
            
        Returns:
            List of conflict reports
        """
        conflicts = []
        
        if not self.llm or not existing_tests or not new_tests:
            return conflicts
        
        # Build prompt for conflict detection
        new_tests_summary = "\n".join([
            f"- {t['test_case_id']}: {t['purpose']}" for t in new_tests
        ])
        
        existing_tests_summary = "\n".join([
            f"- {t.get('test_id', t.get('test_case_id', 'unknown'))}: {t.get('description', t.get('purpose', ''))}"
            for t in existing_tests
        ])
        
        prompt = f"""Analyze these test cases for conflicts or contradictions.

NEW TESTS:
{new_tests_summary}

EXISTING TESTS:
{existing_tests_summary}

Check if any NEW test contradicts or duplicates an EXISTING test.
A contradiction means: one test expects a behavior that another test expects to NOT happen.
A duplicate means: both tests verify the exact same thing.

Respond with JSON:
{{
  "conflicts": [
    {{
      "new_test_id": "id of new test",
      "existing_test_id": "id of existing test",
      "type": "contradiction" or "duplicate",
      "reason": "brief explanation"
    }}
  ]
}}

If no conflicts, return: {{"conflicts": []}}
"""
        
        try:
            response = self.llm.invoke(prompt)
            if response:
                result = json.loads(response)
                conflicts = result.get("conflicts", [])
                
                for conflict in conflicts:
                    logger.warning(
                        f"Conflict detected: {conflict['type']} between "
                        f"{conflict['new_test_id']} and {conflict['existing_test_id']}: "
                        f"{conflict['reason']}"
                    )
        except Exception as e:
            logger.warning(f"Conflict detection failed: {e}")
        
        return conflicts
    
    def tag_semantic_graph(
        self,
        mission_data: Dict[str, Any],
        task_id: Optional[str] = None,
        graph_file: str = "semantic_graph.json"
    ) -> bool:
        """Register test cases in memory for the cluster.
        
        Note: We no longer modify the semantic_graph.json file as it's generated.
        Instead, test-to-node relationships are stored in memory and should be
        persisted to the database via the API.
        
        Args:
            mission_data: Parsed mission JSON
            task_id: Optional task ID
            graph_file: Path to semantic graph file (unused, kept for compatibility)
            
        Returns:
            True if registration succeeded
        """
        target_node = mission_data.get("target_node", "")
        if not target_node:
            logger.warning("No target_node in mission data, skipping graph tagging")
            return False
        
        # Extract test cases
        test_cases = self.extract_test_cases_from_mission(mission_data)
        
        if not test_cases:
            logger.warning("No test cases found in mission data")
            return False
        
        # Log the registrations (actual DB persistence happens via API)
        for tc in test_cases:
            logger.info(
                f"Registered test '{tc['test_case_id']}' for node '{target_node}' "
                f"(persona: {tc.get('persona', 'N/A')}, task: {task_id})"
            )
        
        return True
    
    def register_tests(
        self,
        mission_data: Dict[str, Any],
        task_id: Optional[str] = None,
        graph_file: str = "semantic_graph.json"
    ) -> Dict[str, Any]:
        """Register test cases from a mission - full workflow.
        
        This is the main entry point that:
        1. Extracts test cases from mission
        2. Checks for conflicts with existing tests
        3. Tags the semantic graph
        4. Returns registration result
        
        Args:
            mission_data: Parsed mission JSON
            task_id: Optional task ID
            graph_file: Path to semantic graph file
            
        Returns:
            Registration result with conflicts and status
        """
        result = {
            "success": True,
            "tests_registered": 0,
            "conflicts": [],
            "warnings": []
        }
        
        target_node = mission_data.get("target_node", "")
        if not target_node:
            result["success"] = False
            result["warnings"].append("No target_node in mission data")
            return result
        
        # Extract test cases
        test_cases = self.extract_test_cases_from_mission(mission_data)
        if not test_cases:
            result["warnings"].append("No test cases found in mission")
            return result
        
        # Load graph and get existing tests
        graph = self.load_semantic_graph(graph_file)
        cluster_name = self.find_cluster_name(target_node)
        existing_tests = self.get_existing_tests_for_cluster(cluster_name, graph)
        
        # Check for conflicts
        conflicts = self.check_conflicts(test_cases, existing_tests)
        result["conflicts"] = conflicts
        
        if conflicts:
            for conflict in conflicts:
                result["warnings"].append(
                    f"Conflict: {conflict['type']} - {conflict['new_test_id']} vs {conflict['existing_test_id']}: {conflict['reason']}"
                )
        
        # Tag the graph (proceed even with conflicts - just warn)
        tagged = self.tag_semantic_graph(mission_data, task_id, graph_file)
        if tagged:
            result["tests_registered"] = len(test_cases)
        else:
            result["success"] = False
            result["warnings"].append("Failed to tag semantic graph")
        
        return result
    
    def register_tests_to_repository(
        self,
        mission_data: Dict[str, Any],
        task_id: str,
        sync_to_db: bool = True
    ) -> Dict[str, Any]:
        """Register test cases from a mission to the test repository.
        
        This is the new workflow that uses TestRepositoryManager for:
        1. Extracting complete test definitions from mission
        2. LLM-powered analysis for duplicates/conflicts/merges
        3. Saving to file-based repository
        4. Optionally syncing to database for graph enrichment
        
        Args:
            mission_data: Parsed mission JSON
            task_id: The task ID that generated this mission
            sync_to_db: Whether to sync to database after repository update
            
        Returns:
            Registration result with detailed merge info
        """
        result = {
            "success": True,
            "tests_added": 0,
            "tests_duplicates": 0,
            "tests_conflicts": 0,
            "tests_merged": 0,
            "decisions": [],
            "warnings": [],
            "db_synced": False
        }
        
        target_node = mission_data.get("target_node", "")
        if not target_node:
            result["success"] = False
            result["warnings"].append("No target_node in mission data")
            return result
        
        # Get TestRepositoryManager
        try:
            repo_manager = get_test_repository_manager(
                project_id=self.project_id,
                mapper_dir=self.mapper_dir
            )
        except Exception as e:
            logger.error(f"Failed to initialize TestRepositoryManager: {e}")
            result["success"] = False
            result["warnings"].append(f"Repository manager error: {e}")
            return result
        
        # Extract complete test definitions from mission
        new_tests = []
        persona_tests = mission_data.get("persona_tests", [])
        
        for persona_test in persona_tests:
            for tc in persona_test.get("test_cases", []):
                test_def = repo_manager.extract_test_from_mission(
                    test_case=tc,
                    mission_data=mission_data,
                    persona_test=persona_test,
                    task_id=task_id
                )
                new_tests.append(test_def)
        
        # Also handle legacy format
        for tc in mission_data.get("test_cases", []):
            if not any(t["id"] == tc.get("id") for t in new_tests):
                test_def = repo_manager.extract_test_from_mission(
                    test_case=tc,
                    mission_data=mission_data,
                    persona_test={"persona": tc.get("persona", "")},
                    task_id=task_id
                )
                new_tests.append(test_def)
        
        if not new_tests:
            result["warnings"].append("No test cases found in mission")
            return result
        
        logger.info(f"Extracted {len(new_tests)} tests from mission for node '{target_node}'")
        
        # Merge into repository with LLM analysis
        merge_result = repo_manager.merge_new_tests(
            node_id=target_node,
            new_tests=new_tests,
            task_id=task_id
        )
        
        # Update result with merge info
        result["success"] = merge_result.get("success", False)
        result["tests_added"] = merge_result.get("added", 0)
        result["tests_duplicates"] = merge_result.get("duplicates", 0)
        result["tests_conflicts"] = merge_result.get("conflicts", 0)
        result["tests_merged"] = merge_result.get("merged", 0)
        result["decisions"] = merge_result.get("decisions", [])
        result["warnings"].extend(merge_result.get("warnings", []))
        
        # Sync to database if requested
        if sync_to_db and result["success"]:
            try:
                sync_result = repo_manager.sync_to_database(target_node)
                result["db_synced"] = sync_result.get("success", False)
                if not sync_result.get("success"):
                    result["warnings"].extend(sync_result.get("errors", []))
            except Exception as e:
                result["warnings"].append(f"Database sync failed: {e}")
        
        logger.info(
            f"Repository registration complete for node '{target_node}': "
            f"added={result['tests_added']}, duplicates={result['tests_duplicates']}, "
            f"conflicts={result['tests_conflicts']}, merged={result['tests_merged']}"
        )
        
        return result
    
    def get_affected_tests(
        self,
        node_id: str,
        graph_file: str = "semantic_graph.json"
    ) -> List[Dict[str, Any]]:
        """Get all tests affected by a change to a graph node.
        
        This is used for impact analysis when a developer modifies a component.
        
        Args:
            node_id: The semantic graph node ID
            graph_file: Path to semantic graph file
            
        Returns:
            List of affected test metadata
        """
        graph = self.load_semantic_graph(graph_file)
        
        for node in graph.get("nodes", []):
            if node.get("id") == node_id or node.get("semantic_name") == node_id:
                return node.get("related_tests", [])
        
        return []
    
    def deprecate_test(
        self,
        test_id: str,
        node_id: str,
        reason: str = "Deprecated",
        graph_file: str = "semantic_graph.json"
    ) -> bool:
        """Mark a test as deprecated in the semantic graph.
        
        Args:
            test_id: The test case ID to deprecate
            node_id: The node containing the test
            reason: Reason for deprecation
            graph_file: Path to semantic graph file
            
        Returns:
            True if deprecation succeeded
        """
        graph = self.load_semantic_graph(graph_file)
        
        for node in graph.get("nodes", []):
            if node.get("id") == node_id or node.get("semantic_name") == node_id:
                for test in node.get("related_tests", []):
                    if test.get("test_id") == test_id:
                        test["status"] = "deprecated"
                        test["deprecated_at"] = datetime.utcnow().isoformat()
                        test["deprecation_reason"] = reason
                        self.save_semantic_graph(graph, graph_file)
                        logger.info(f"Deprecated test '{test_id}' on node '{node_id}': {reason}")
                        return True
        
        return False


# CLI interface for testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python cluster_manager.py <mission_file> [task_id]")
        sys.exit(1)
    
    mission_file = Path(sys.argv[1])
    task_id = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not mission_file.exists():
        print(f"Mission file not found: {mission_file}")
        sys.exit(1)
    
    mission_data = json.loads(mission_file.read_text())
    
    manager = ClusterManager()
    result = manager.register_tests(mission_data, task_id)
    
    print(json.dumps(result, indent=2))
