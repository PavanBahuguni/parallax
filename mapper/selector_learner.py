"""Selector Learner - JIT Correction Tracking and Persistence.

This module handles:
1. Recording JIT selector resolutions during test execution
2. Updating mission files with corrected selectors
3. Updating semantic graph components with corrected selectors
4. Persisting corrections to PostgreSQL for future use
5. Retrieving known corrections to preemptively fix selectors
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import UUID

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class SelectorCorrection:
    """Represents a single selector correction."""
    
    def __init__(
        self,
        original_selector: str,
        corrected_selector: str,
        action_type: str = "",
        description: str = "",
        node_id: str = "",
        component_role: str = "",
        step_index: int = -1
    ):
        self.original_selector = original_selector
        self.corrected_selector = corrected_selector
        self.action_type = action_type
        self.description = description
        self.node_id = node_id
        self.component_role = component_role
        self.step_index = step_index
        self.timestamp = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_selector": self.original_selector,
            "corrected_selector": self.corrected_selector,
            "action_type": self.action_type,
            "description": self.description,
            "node_id": self.node_id,
            "component_role": self.component_role,
            "step_index": self.step_index,
            "timestamp": self.timestamp
        }


class SelectorLearner:
    """Manages JIT selector correction learning and persistence."""
    
    def __init__(
        self,
        project_id: Optional[str] = None,
        mapper_dir: Optional[Path] = None,
        db_url: Optional[str] = None
    ):
        """Initialize SelectorLearner.
        
        Args:
            project_id: UUID of the project (for DB operations)
            mapper_dir: Path to the mapper directory
            db_url: PostgreSQL connection URL (optional)
        """
        self.project_id = project_id
        self.mapper_dir = mapper_dir or Path(__file__).parent
        self.db_url = db_url or os.getenv("DATABASE_URL")
        
        # Load environment
        env_file = self.mapper_dir / ".env"
        if env_file.exists():
            load_dotenv(env_file)
        
        # Track corrections during execution
        self.corrections: List[SelectorCorrection] = []
    
    def record_correction(
        self,
        original_selector: str,
        corrected_selector: str,
        action_type: str = "",
        description: str = "",
        node_id: str = "",
        component_role: str = "",
        step_index: int = -1
    ) -> SelectorCorrection:
        """Record a JIT selector correction.
        
        Called by the executor when JIT resolution succeeds.
        
        Args:
            original_selector: The selector that failed
            corrected_selector: The selector that worked
            action_type: Type of action (click, fill, wait_visible)
            description: Step description
            node_id: Semantic graph node ID
            component_role: Component role from graph
            step_index: Index of the step in the mission
            
        Returns:
            The recorded correction
        """
        correction = SelectorCorrection(
            original_selector=original_selector,
            corrected_selector=corrected_selector,
            action_type=action_type,
            description=description,
            node_id=node_id,
            component_role=component_role,
            step_index=step_index
        )
        self.corrections.append(correction)
        
        logger.info(
            f"Recorded JIT correction: '{original_selector}' -> '{corrected_selector}' "
            f"(action: {action_type}, node: {node_id})"
        )
        
        return correction
    
    def get_corrections(self) -> List[Dict[str, Any]]:
        """Get all recorded corrections as dictionaries."""
        return [c.to_dict() for c in self.corrections]
    
    def clear_corrections(self):
        """Clear all recorded corrections."""
        self.corrections = []
    
    def apply_corrections_to_mission(
        self,
        mission_path: Path,
        corrections: Optional[List[SelectorCorrection]] = None
    ) -> bool:
        """Apply corrections to mission file.
        
        Updates the mission JSON with corrected selectors, marking them
        as JIT-corrected for transparency.
        
        Args:
            mission_path: Path to the mission JSON file
            corrections: Optional list of corrections (uses self.corrections if None)
            
        Returns:
            True if update succeeded
        """
        corrections = corrections or self.corrections
        if not corrections:
            logger.info("No corrections to apply to mission")
            return True
        
        if not mission_path.exists():
            logger.warning(f"Mission file not found: {mission_path}")
            return False
        
        try:
            mission_data = json.loads(mission_path.read_text())
            modified = False
            
            # Build correction lookup
            correction_map = {c.original_selector: c for c in corrections}
            
            # Update selectors in various parts of the mission
            
            # 1. Update gateway_plan steps
            for persona_test in mission_data.get("persona_tests", []):
                gateway_plan = persona_test.get("gateway_plan", {})
                for step in gateway_plan.get("steps", []):
                    selector = step.get("selector", "")
                    if selector in correction_map:
                        correction = correction_map[selector]
                        step["selector"] = correction.corrected_selector
                        step["original_selector"] = correction.original_selector
                        step["jit_corrected"] = True
                        step["jit_corrected_at"] = correction.timestamp
                        modified = True
                        logger.info(f"Updated gateway_plan step selector: {selector} -> {correction.corrected_selector}")
            
            # 2. Update navigation_path steps
            for nav_step in mission_data.get("navigation_path", []):
                selector = nav_step.get("selector", "")
                if selector in correction_map:
                    correction = correction_map[selector]
                    nav_step["selector"] = correction.corrected_selector
                    nav_step["original_selector"] = correction.original_selector
                    nav_step["jit_corrected"] = True
                    nav_step["jit_corrected_at"] = correction.timestamp
                    modified = True
                    logger.info(f"Updated navigation_path step selector: {selector} -> {correction.corrected_selector}")
            
            # 3. Update deterministic_steps
            for det_step_group in mission_data.get("deterministic_steps", []):
                for step in det_step_group.get("steps", []):
                    selector = step.get("selector", "")
                    if selector in correction_map:
                        correction = correction_map[selector]
                        step["selector"] = correction.corrected_selector
                        step["original_selector"] = correction.original_selector
                        step["jit_corrected"] = True
                        step["jit_corrected_at"] = correction.timestamp
                        modified = True
                        logger.info(f"Updated deterministic_steps selector: {selector} -> {correction.corrected_selector}")
            
            # 4. Update test_cases component_selector and field_selectors
            for persona_test in mission_data.get("persona_tests", []):
                for tc in persona_test.get("test_cases", []):
                    # Component selector
                    comp_selector = tc.get("component_selector", "")
                    if comp_selector in correction_map:
                        correction = correction_map[comp_selector]
                        tc["component_selector"] = correction.corrected_selector
                        tc["original_component_selector"] = correction.original_selector
                        tc["jit_corrected"] = True
                        modified = True
                    
                    # Field selectors
                    for field_name, field_info in tc.get("field_selectors", {}).items():
                        if isinstance(field_info, dict):
                            selector = field_info.get("selector", "")
                            if selector in correction_map:
                                correction = correction_map[selector]
                                field_info["selector"] = correction.corrected_selector
                                field_info["original_selector"] = correction.original_selector
                                field_info["jit_corrected"] = True
                                modified = True
            
            if modified:
                # Add correction metadata to mission
                if "jit_corrections" not in mission_data:
                    mission_data["jit_corrections"] = []
                
                for correction in corrections:
                    mission_data["jit_corrections"].append(correction.to_dict())
                
                mission_data["jit_corrections_applied_at"] = datetime.utcnow().isoformat()
                
                # Write updated mission
                mission_path.write_text(json.dumps(mission_data, indent=2))
                logger.info(f"Applied {len(corrections)} corrections to mission: {mission_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply corrections to mission: {e}")
            return False
    
    def update_graph_selectors(
        self,
        graph_path: Optional[Path] = None,
        corrections: Optional[List[SelectorCorrection]] = None
    ) -> bool:
        """Update semantic graph with corrected selectors.
        
        Updates component selectors in the semantic graph, maintaining
        a history of previous selectors.
        
        Args:
            graph_path: Path to semantic graph (defaults to semantic_graph.json)
            corrections: Optional list of corrections (uses self.corrections if None)
            
        Returns:
            True if update succeeded
        """
        corrections = corrections or self.corrections
        if not corrections:
            logger.info("No corrections to apply to graph")
            return True
        
        graph_path = graph_path or (self.mapper_dir / "semantic_graph.json")
        
        if not graph_path.exists():
            logger.warning(f"Semantic graph not found: {graph_path}")
            return False
        
        try:
            graph = json.loads(graph_path.read_text())
            modified = False
            
            # Group corrections by node_id
            corrections_by_node: Dict[str, List[SelectorCorrection]] = {}
            for correction in corrections:
                if correction.node_id:
                    if correction.node_id not in corrections_by_node:
                        corrections_by_node[correction.node_id] = []
                    corrections_by_node[correction.node_id].append(correction)
            
            # Build global correction lookup for selectors without node_id
            global_corrections = {c.original_selector: c for c in corrections if not c.node_id}
            
            # Update components in each node
            for node in graph.get("nodes", []):
                node_id = node.get("id", "")
                node_corrections = corrections_by_node.get(node_id, [])
                
                # Build node-specific correction lookup
                node_correction_map = {c.original_selector: c for c in node_corrections}
                # Merge with global corrections
                correction_lookup = {**global_corrections, **node_correction_map}
                
                if not correction_lookup:
                    continue
                
                for component in node.get("components", []):
                    selector = component.get("selector", "")
                    
                    if selector in correction_lookup:
                        correction = correction_lookup[selector]
                        
                        # Maintain history of previous selectors
                        if "previous_selectors" not in component:
                            component["previous_selectors"] = []
                        
                        if selector not in component["previous_selectors"]:
                            component["previous_selectors"].append(selector)
                        
                        # Update to new selector
                        component["selector"] = correction.corrected_selector
                        component["last_verified"] = datetime.utcnow().isoformat()
                        component["jit_corrected"] = True
                        
                        modified = True
                        logger.info(
                            f"Updated graph component '{component.get('role', '')}' on node '{node_id}': "
                            f"'{selector}' -> '{correction.corrected_selector}'"
                        )
            
            if modified:
                graph_path.write_text(json.dumps(graph, indent=2))
                logger.info(f"Updated semantic graph with {len(corrections)} corrections")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update graph selectors: {e}")
            return False
    
    def get_known_corrections_for_node(
        self,
        node_id: str,
        graph_path: Optional[Path] = None
    ) -> Dict[str, str]:
        """Get known selector corrections for a node from the semantic graph.
        
        This enables preemptive correction - using the corrected selector
        before the original even fails.
        
        Args:
            node_id: The semantic graph node ID
            graph_path: Path to semantic graph
            
        Returns:
            Dict mapping original selectors to corrected selectors
        """
        graph_path = graph_path or (self.mapper_dir / "semantic_graph.json")
        
        if not graph_path.exists():
            return {}
        
        try:
            graph = json.loads(graph_path.read_text())
            corrections = {}
            
            for node in graph.get("nodes", []):
                if node.get("id") == node_id or node.get("semantic_name") == node_id:
                    for component in node.get("components", []):
                        if component.get("jit_corrected") and component.get("previous_selectors"):
                            current_selector = component.get("selector", "")
                            for prev_selector in component.get("previous_selectors", []):
                                corrections[prev_selector] = current_selector
                    break
            
            return corrections
            
        except Exception as e:
            logger.warning(f"Failed to get known corrections: {e}")
            return {}
    
    def apply_all(
        self,
        mission_path: Path,
        graph_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """Apply all recorded corrections to mission and graph.
        
        This is the main entry point called after test execution.
        
        Args:
            mission_path: Path to the mission JSON file
            graph_path: Path to semantic graph (optional)
            
        Returns:
            Result summary
        """
        result = {
            "corrections_count": len(self.corrections),
            "mission_updated": False,
            "graph_updated": False,
            "errors": []
        }
        
        if not self.corrections:
            logger.info("No JIT corrections to apply")
            return result
        
        # Apply to mission
        try:
            result["mission_updated"] = self.apply_corrections_to_mission(mission_path)
        except Exception as e:
            result["errors"].append(f"Mission update failed: {e}")
        
        # Apply to graph
        try:
            result["graph_updated"] = self.update_graph_selectors(graph_path)
        except Exception as e:
            result["errors"].append(f"Graph update failed: {e}")
        
        # Log summary
        logger.info(
            f"Applied {len(self.corrections)} JIT corrections: "
            f"mission={result['mission_updated']}, graph={result['graph_updated']}"
        )
        
        return result


# CLI interface for testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python selector_learner.py <mission_file> <original_selector> <corrected_selector>")
        print("       python selector_learner.py apply <mission_file>")
        sys.exit(1)
    
    if sys.argv[1] == "apply":
        mission_file = Path(sys.argv[2])
        learner = SelectorLearner()
        
        # Load corrections from mission file if any
        if mission_file.exists():
            mission_data = json.loads(mission_file.read_text())
            for corr in mission_data.get("jit_corrections", []):
                learner.record_correction(
                    original_selector=corr.get("original_selector", ""),
                    corrected_selector=corr.get("corrected_selector", ""),
                    action_type=corr.get("action_type", ""),
                    node_id=corr.get("node_id", "")
                )
            
            result = learner.apply_all(mission_file)
            print(json.dumps(result, indent=2))
    else:
        mission_file = Path(sys.argv[1])
        original = sys.argv[2]
        corrected = sys.argv[3]
        
        learner = SelectorLearner()
        learner.record_correction(original, corrected)
        result = learner.apply_all(mission_file)
        print(json.dumps(result, indent=2))
