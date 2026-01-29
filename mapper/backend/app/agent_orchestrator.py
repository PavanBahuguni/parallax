"""AI Agent Orchestrator - Automates Map, Generate Mission, Execute Test workflow."""
import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Awaitable, Coroutine
from dotenv import load_dotenv

try:
    import httpx
except ImportError:
    httpx = None

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Orchestrates the automated QA workflow with intelligent decision making."""
    
    def __init__(
        self,
        update_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        project_id: Optional[str] = None,
        project_config: Optional[Dict[str, Any]] = None
    ):
        """Initialize orchestrator with optional callback for real-time updates.
        
        Args:
            update_callback: Async function to call with progress updates: {"step": "...", "status": "...", "message": "..."}
            project_id: Optional project ID for project-specific configuration
            project_config: Optional pre-loaded project configuration dict
        """
        self.update_callback = update_callback
        self.mapper_dir = Path(__file__).parent.parent.parent
        self.project_id = project_id
        self.project_config = project_config or {}
        
        # Load environment
        env_file = self.mapper_dir / ".env"
        if env_file.exists():
            load_dotenv(env_file)
    
    async def _send_update(self, step: str, status: str, message: str, data: Optional[Dict] = None):
        """Send progress update via callback."""
        if self.update_callback:
            await self.update_callback({
                "step": step,
                "status": status,  # "running", "completed", "failed", "skipped"
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "data": data or {}
            })
    
    def _fetch_pr_diff_direct(self, owner: str, repo: str, pr_number: str) -> Optional[Dict]:
        """Fetch PR diff directly from GitHub API without requiring context_processor.
        
        Returns:
            Dict with 'files' list containing diff data
        """
        if httpx is None:
            logger.warning("httpx not available, cannot fetch PR diff")
            return None
            
        try:
            github_token = os.getenv("GITHUB_TOKEN")
            
            headers = {}
            if github_token:
                headers["Authorization"] = f"token {github_token}"
            
            url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
            
            with httpx.Client(verify=True, timeout=30.0, headers=headers) as client:
                response = client.get(url)
                
                if response.status_code == 404:
                    logger.warning(f"PR not found (404). Is it public?")
                    return None
                
                response.raise_for_status()
                return {"files": response.json()}
                
        except Exception as e:
            logger.warning(f"GitHub API error: {e}")
            return None
    
    def _analyze_pr_diff_simple(self, pr_data: Dict) -> Dict[str, Any]:
        """Simple PR diff analysis without LLM - extracts basic changes.
        
        Returns:
            Dict with ui_changes, api_changes, file_types
        """
        files = pr_data.get("files", [])
        ui_changes = []
        api_changes = []
        file_types = {}
        
        for file_info in files:
            filename = file_info.get("filename", "")
            patch = file_info.get("patch", "") or ""
            status = file_info.get("status", "")
            
            # Track file types
            ext = Path(filename).suffix
            file_types[ext] = file_types.get(ext, 0) + 1
            
            # Check for UI changes
            if ext in [".tsx", ".ts", ".jsx", ".js"]:
                if "category" in patch.lower() or "dropdown" in patch.lower() or "select" in patch.lower():
                    ui_changes.append(f"category dropdown/select added")
                if "filter" in patch.lower():
                    ui_changes.append(f"category filter added")
                if "badge" in patch.lower():
                    ui_changes.append(f"category badge added")
            
            # Check for API changes
            if filename.endswith(".py") and ("main.py" in filename or "routes" in filename or "api" in filename):
                if re.search(r'@app\.(get|post|put|patch|delete)\(', patch, re.IGNORECASE):
                    # Extract endpoint
                    match = re.search(r'@app\.(get|post|put|patch|delete)\(["\']([^"\']+)["\']', patch, re.IGNORECASE)
                    if match:
                        method = match.group(1).upper()
                        path = match.group(2)
                        api_changes.append(f"{method} {path}")
        
        return {
            "ui_changes": list(set(ui_changes)),  # Deduplicate
            "api_changes": list(set(api_changes)),
            "file_types": file_types,
            "files_changed": len(files)
        }
    
    async def should_run_mapper(self, task_id: str, pr_link: Optional[str] = None) -> bool:
        """Determine if semantic mapper needs to run based on PR changes.
        
        Checks:
        1. If persona-specific semantic graphs exist and have content
        2. If semantic_graph.json exists and is recent
        3. If PR changes affect UI routes/components
        4. If PR changes affect API endpoints
        
        Returns:
            True if mapper should run, False if can skip
        """
        await self._send_update("analyze", "running", "Analyzing PR changes...")
        logger.info(f"Analyzing PR for task {task_id}, PR link: {pr_link}")
        
        # Check for persona-specific graphs first (these are the ones actually used)
        persona_graphs_found = []
        for persona_graph in self.mapper_dir.glob("semantic_graph_*.json"):
            try:
                graph_data = json.loads(persona_graph.read_text())
                node_count = len(graph_data.get("nodes", []))
                if node_count > 0:
                    persona_name = persona_graph.stem.replace("semantic_graph_", "")
                    persona_graphs_found.append((persona_name, node_count))
            except Exception:
                pass
        
        # If we have persona-specific graphs with content, skip mapping
        if persona_graphs_found:
            graph_summary = ", ".join([f"{name}: {count} nodes" for name, count in persona_graphs_found])
            await self._send_update("analyze", "completed", f"Using existing persona graphs ({graph_summary})")
            await self._send_update("map", "skipped", f"Found {len(persona_graphs_found)} persona graph(s)")
            return False
        
        semantic_graph_path = self.mapper_dir / "semantic_graph.json"
        
        # If no semantic graph exists, must run mapper
        if not semantic_graph_path.exists():
            await self._send_update("analyze", "completed", "No existing graph found")
            await self._send_update("map", "running", "Building semantic graph...")
            return True
        
        # Check if main graph has content
        try:
            graph_data = json.loads(semantic_graph_path.read_text())
            if len(graph_data.get("nodes", [])) == 0:
                await self._send_update("analyze", "completed", "Graph is empty")
                await self._send_update("map", "running", "Building semantic graph...")
                return True
        except Exception:
            pass
        
        # If no PR link, run mapper to be safe
        if not pr_link:
            await self._send_update("analyze", "completed", "No PR link provided")
            await self._send_update("map", "running", "Building semantic graph...")
            return True
        
        # Check PR changes to see if UI/API changed
        try:
            # Try to fetch PR diff directly without importing context_processor
            # (which requires langchain_core that may not be installed in backend)
            pr_match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr_link)
            if pr_match:
                owner, repo, pr_number = pr_match.groups()
                pr_data = self._fetch_pr_diff_direct(owner, repo, pr_number)
                
                if pr_data:
                    files = pr_data.get("files", [])
                    
                    # Check for specific UI changes that require remapping
                    needs_remap = False
                    remap_reasons = []
                    
                    for file_info in files:
                        filename = file_info.get("filename", "")
                        patch = file_info.get("patch", "") or ""
                        
                        # Check for new routes (React Router, Next.js, etc.)
                        if any(ext in filename for ext in [".tsx", ".tsx", ".jsx", ".js"]):
                            # Check for new route definitions
                            if re.search(r'path\s*[:=]\s*["\']([^"\']+)["\']', patch, re.IGNORECASE):
                                needs_remap = True
                                remap_reasons.append("New route detected")
                            
                            # Check for new Link components or navigation
                            if re.search(r'<Link\s+to\s*=\s*["\']([^"\']+)["\']', patch, re.IGNORECASE) or \
                               re.search(r'navigate\s*\(["\']([^"\']+)["\']', patch, re.IGNORECASE) or \
                               re.search(r'useNavigate|useRouter|Router', patch, re.IGNORECASE):
                                needs_remap = True
                                remap_reasons.append("New navigation/link detected")
                            
                            # Check for new buttons that might open forms/modals
                            if re.search(r'<button[^>]*onClick', patch, re.IGNORECASE) and \
                               ('form' in patch.lower() or 'modal' in patch.lower() or 'dialog' in patch.lower()):
                                needs_remap = True
                                remap_reasons.append("New interactive button detected")
                            
                            # Check for new form components (only if it's a new form, not adding fields to existing)
                            # Skip if it's just adding a field (like <select> or <input> to existing form)
                            if file_info.get("status") == "added" and \
                               (re.search(r'<form[^>]*>', patch, re.IGNORECASE) or \
                                re.search(r'export\s+(default\s+)?function\s+\w+Form', patch, re.IGNORECASE)):
                                needs_remap = True
                                remap_reasons.append("New form component detected")
                            
                            # Check for new pages/components (file additions)
                            if file_info.get("status") == "added" and \
                               any(ext in filename for ext in [".tsx", ".tsx", ".jsx"]):
                                # Only remap if it's a page component, not just a utility component
                                if "page" in filename.lower() or "route" in filename.lower() or \
                                   re.search(r'export\s+(default\s+)?function\s+\w+Page', patch, re.IGNORECASE):
                                    needs_remap = True
                                    remap_reasons.append("New page component added")
                    
                    if needs_remap:
                        reasons_str = ", ".join(set(remap_reasons))
                        await self._send_update("analyze", "completed", f"UI changes detected: {reasons_str}")
                        await self._send_update("map", "running", "Rebuilding semantic graph...")
                        return True
                
                # Analyze PR diff for simple changes (without LLM)
                pr_summary = self._analyze_pr_diff_simple(pr_data)
            else:
                # If we can't fetch PR diff, skip mapper (assume no structural changes)
                await self._send_update("analyze", "completed", "Could not fetch PR diff")
                await self._send_update("map", "skipped", "No structural changes detected")
                return False
            
            # Check if UI files changed (less specific)
            ui_changes = pr_summary.get("ui_changes", [])
            file_types = pr_summary.get("file_types", {})
            
            # Check UI changes - if they're only field-level, skip mapping
            # Field-level keywords that don't require remapping
            field_keywords = ["dropdown", "select", "input", "field", "category", "badge", "filter", "form field", "badge"]
            # Structural keywords that DO require remapping
            structural_ui_keywords = ["route", "link", "page", "navigation", "component", "button"]
            
            # Check if ALL ui_changes are field-level (no structural changes)
            all_field_changes = all(
                any(field_kw in change.lower() for field_kw in field_keywords) or
                not any(struct_kw in change.lower() for struct_kw in structural_ui_keywords)
                for change in ui_changes
            )
            
            # If we have UI changes but they're all field-level, skip mapping
            if ui_changes and all_field_changes:
                await self._send_update("analyze", "completed", f"Field-level changes only ({len(ui_changes)} files)")
                await self._send_update("map", "skipped", "No structural changes")
                return False
            
            # If we have structural UI changes, remap
            if ui_changes and not all_field_changes:
                structural_list = [c for c in ui_changes if any(struct_kw in c.lower() for struct_kw in structural_ui_keywords) and not any(field_kw in c.lower() for field_kw in field_keywords)]
                await self._send_update("analyze", "completed", f"Structural UI changes ({len(structural_list)} files)")
                await self._send_update("map", "running", "Rebuilding semantic graph...")
                return True
            
            # If frontend files changed but no UI changes detected, check file status
            frontend_extensions = [".tsx", ".ts", ".jsx", ".js", ".vue", ".html"]
            frontend_changed = any(
                any(ext in str(f) for ext in frontend_extensions)
                for f in pr_summary.get("sample_files", [])
            )
            
            # Only remap if new files were added (structural change)
            # Modifications to existing files (like adding a field) don't need remapping
            if frontend_changed:
                # If we can't determine file status, be conservative and skip
                # (Better to skip than waste time remapping when not needed)
                await self._send_update("analyze", "completed", "Frontend modified, no structural changes")
                await self._send_update("map", "skipped", "Using existing graph")
                return False
            
            # Check if API routes changed - only remap if NEW endpoints added, not modifications to existing ones
            api_changes = pr_summary.get("api_changes", [])
            if api_changes and pr_data:
                # Check PR diff to see if these are new endpoints or just modifications
                files = pr_data.get("files", [])
                # Check if any new route decorators were added (new endpoints)
                new_endpoints = False
                for file_info in files:
                    filename = file_info.get("filename", "")
                    patch = file_info.get("patch", "") or ""
                    status = file_info.get("status", "")
                    
                    # Only check backend files
                    if "main.py" in filename or "routes" in filename or "api" in filename or filename.endswith(".py"):
                        # Check for new route decorators (added lines with @app.post, @app.get, etc.)
                        if status == "added" and re.search(r'@app\.(get|post|put|patch|delete)\(', patch, re.IGNORECASE):
                            new_endpoints = True
                            break
                        # Check for new route definitions in added lines
                        if status == "added" and re.search(r'@(get|post|put|patch|delete)\(["\']([^"\']+)["\']', patch, re.IGNORECASE):
                            new_endpoints = True
                            break
                
                if new_endpoints:
                    await self._send_update("analyze", "completed", f"New API endpoints ({len(api_changes)} files)")
                    await self._send_update("map", "running", "Rebuilding semantic graph...")
                    return True
                else:
                    # Only modifications to existing endpoints, skip mapping
                    await self._send_update("analyze", "completed", "API modified, no new endpoints")
                    await self._send_update("map", "skipped", "Using existing graph")
                    # Don't return False here - continue to check other conditions
            elif api_changes:
                # Can't analyze PR, be conservative but log the reason
                await self._send_update("analyze", "completed", f"API changes detected ({len(api_changes)} files)")
                await self._send_update("map", "running", "Rebuilding semantic graph...")
                return True
            
            # Check graph age - if older than 7 days, remap
            graph_age = (datetime.now() - datetime.fromtimestamp(semantic_graph_path.stat().st_mtime)).days
            if graph_age > 7:
                await self._send_update("analyze", "completed", f"Graph is {graph_age} days old")
                await self._send_update("map", "running", "Refreshing semantic graph...")
                return True
            
            await self._send_update("analyze", "completed", "No structural changes detected")
            await self._send_update("map", "skipped", "Using existing graph")
            return False
            
        except Exception as e:
            logger.warning(f"Error analyzing PR for mapper decision: {e}")
            await self._send_update("analyze", "completed", f"Analysis error: {str(e)[:50]}")
            await self._send_update("map", "running", "Building semantic graph (fallback)...")
            return True
    
    async def run_semantic_mapper(self, task_id: str) -> Dict[str, Any]:
        """Run semantic mapper and return result."""
        # Update already sent in should_run_mapper, but send completion message
        pass
        
        try:
            script_path = self.mapper_dir / "semantic_mapper.py"
            
            # Prepare environment with project config
            env = os.environ.copy()
            if self.project_config:
                env["PROJECT_BASE_URL"] = self.project_config.get("BASE_URL", "")
                env["PROJECT_API_BASE"] = self.project_config.get("API_BASE", "")
                env["PROJECT_BACKEND_PATH"] = self.project_config.get("BACKEND_PATH", "")
                # Extract persona names from persona objects
                personas = self.project_config.get("PERSONAS", [])
                if personas:
                    persona_names = []
                    for p in personas:
                        if isinstance(p, dict):
                            persona_names.append(p.get("name", ""))
                        elif isinstance(p, str):
                            # Legacy format
                            persona_names.append(p)
                    if persona_names:
                        env["PROJECT_PERSONAS"] = ",".join(persona_names)
                        # Also store full persona objects as JSON for gateway instructions access
                        # Note: 'json' module is imported at module level
                        env["PROJECT_PERSONAS_FULL"] = json.dumps(personas)
            
            process = await asyncio.create_subprocess_exec(
                "uv", "run", "python", str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.mapper_dir),
                env=env
            )
            
            stdout, _ = await process.communicate()
            output = stdout.decode() if stdout else ""
            
            # Check for persona-specific graphs first (these are the primary output)
            total_nodes = 0
            total_edges = 0
            persona_count = 0
            for persona_graph in self.mapper_dir.glob("semantic_graph_*.json"):
                try:
                    graph_data = json.loads(persona_graph.read_text())
                    total_nodes += len(graph_data.get("nodes", []))
                    total_edges += len(graph_data.get("edges", []))
                    persona_count += 1
                except Exception:
                    pass
            
            if persona_count > 0 and total_nodes > 0:
                await self._send_update("map", "completed", 
                    f"Graph built: {total_nodes} nodes, {total_edges} edges ({persona_count} persona(s))")
                return {
                    "success": process.returncode == 0,
                    "output": output,
                    "nodes": total_nodes,
                    "edges": total_edges,
                    "personas": persona_count
                }
            
            # Fallback: Check main semantic graph
            semantic_graph_path = self.mapper_dir / "semantic_graph.json"
            if semantic_graph_path.exists():
                try:
                    graph_data = json.loads(semantic_graph_path.read_text())
                    node_count = len(graph_data.get("nodes", []))
                    edge_count = len(graph_data.get("edges", []))
                    await self._send_update("map", "completed", 
                        f"Graph built: {node_count} nodes, {edge_count} edges")
                    return {
                        "success": process.returncode == 0,
                        "output": output,
                        "nodes": node_count,
                        "edges": edge_count
                    }
                except Exception as e:
                    logger.warning(f"Could not parse semantic graph: {e}")
            
            if process.returncode == 0:
                await self._send_update("map", "completed", "Graph ready")
            else:
                await self._send_update("map", "failed", f"Mapping failed: {output[:100]}")
            
            return {
                "success": process.returncode == 0,
                "output": output
            }
            
        except Exception as e:
            error_msg = str(e)
            await self._send_update("map", "failed", f"Mapping error: {error_msg[:100]}")
            return {
                "success": False,
                "error": error_msg
            }
    
    async def run_context_processor(self, task_id: str, task_file_path: Path) -> Dict[str, Any]:
        """Run context processor to generate mission.json."""
        await self._send_update("generate-mission", "running", "Generating test plan...")
        
        # Clean up previous mission file to ensure we don't return stale results
        mission_file = self.mapper_dir / "temp" / f"{task_id}_mission.json"
        if mission_file.exists():
            try:
                mission_file.unlink()
                logger.info(f"Deleted stale mission file: {mission_file}")
            except Exception as e:
                logger.warning(f"Failed to delete stale mission file: {e}")
        
        try:
            script_path = self.mapper_dir / "context_processor.py"
            
            # Prepare environment with project config
            env = os.environ.copy()
            if self.project_config:
                env["PROJECT_BASE_URL"] = self.project_config.get("BASE_URL", "")
                env["PROJECT_API_BASE"] = self.project_config.get("API_BASE", "")
                env["PROJECT_DATABASE_URL"] = self.project_config.get("DATABASE_URL", "")
                env["PROJECT_OPENAPI_URL"] = self.project_config.get("OPENAPI_URL", "")
                env["PROJECT_BACKEND_PATH"] = self.project_config.get("BACKEND_PATH", "")
            
            process = await asyncio.create_subprocess_exec(
                "uv", "run", "python", str(script_path), str(task_file_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.mapper_dir),
                env=env
            )
            
            stdout, _ = await process.communicate()
            output = stdout.decode() if stdout else ""
            
            # Log the context_processor output for debugging
            if output:
                logger.info("=== Context Processor Output ===")
                for line in output.split('\n'):
                    if line.strip():
                        logger.info(f"[context_processor] {line}")
                logger.info("=== End Context Processor Output ===")
            
            # Check if mission.json was created
            mission_file = self.mapper_dir / "temp" / f"{task_id}_mission.json"
            if mission_file.exists():
                try:
                    mission_data = json.loads(mission_file.read_text())
                    action_count = len(mission_data.get("actions", []))
                    verification = mission_data.get("verification_points", {})
                    
                    # Send detailed info about what was generated
                    personas = mission_data.get("personas", [])
                    test_cases = mission_data.get("test_cases", [])
                    
                    details_msg = []
                    if personas:
                        details_msg.append(f"👤 Personas: {', '.join(personas)}")
                    
                    if test_cases:
                        details_msg.append(f"📋 Test Cases ({len(test_cases)}):")
                        for i, tc in enumerate(test_cases[:5]):
                            purpose = tc.get("purpose", "Unknown test case")
                            details_msg.append(f"  {i+1}. {purpose}")
                        if len(test_cases) > 5:
                            details_msg.append(f"  ... and {len(test_cases) - 5} more")
                    
                    if details_msg:
                        await self._send_update("generate-mission", "running", "\n".join(details_msg))

                    await self._send_update("generate-mission", "completed",
                        f"Test plan ready ({action_count} actions)")
                    return {
                        "success": True,
                        "output": output,
                        "mission_file": str(mission_file.relative_to(self.mapper_dir)),
                        "mission": mission_data
                    }
                except Exception as e:
                    logger.warning(f"Could not parse mission JSON: {e}")
            
            # If we reached here, either file doesn't exist or parsing failed
            if process.returncode == 0:
                # Script exited successfully but no output file - likely missing configuration or early return
                error_msg = "Generation completed but no mission file was created. Check logs for missing API keys or configuration."
                if "Missing NUTANIX_API_URL" in output:
                    error_msg = "Missing NUTANIX_API_URL or NUTANIX_API_KEY environment variables."
                
                await self._send_update("generate-mission", "failed", error_msg)
                return {
                    "success": False, 
                    "error": error_msg,
                    "output": output
                }
            else:
                await self._send_update("generate-mission", "failed", f"Generation failed: {output[:100]}")
            
            return {
                "success": False,
                "output": output,
                "mission_file": None
            }
            
        except Exception as e:
            error_msg = str(e)
            await self._send_update("generate-mission", "failed", f"Generation error: {error_msg[:100]}")
            return {
                "success": False,
                "error": error_msg
            }
    
    def _clean_log_line(self, line: str) -> str:
        """Clean log line by removing timestamps, log levels, and ANSI codes."""
        # Remove ANSI escape codes
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        line = ansi_escape.sub('', line)
        
        # Remove timestamps and log levels (e.g., "10:16:43 | INFO     | [executor] ")
        # Matches pattern: HH:MM:SS | LEVEL | [source]
        log_prefix = re.compile(r'^\d{2}:\d{2}:\d{2}\s+\|\s+[A-Z]+\s+\|\s+\[[^\]]+\]\s+')
        line = log_prefix.sub('', line)
        
        # Also handle simpler format: HH:MM:SS |
        simple_prefix = re.compile(r'^\d{2}:\d{2}:\d{2}\s+\|\s+')
        line = simple_prefix.sub('', line)
        
        return line.strip()
    
    async def _register_tests_in_cluster(self, task_id: str, mission_result: Dict[str, Any]) -> Dict[str, Any]:
        """Register test cases to the test repository with LLM-powered analysis.
        
        This integrates the ClusterManager with TestRepositoryManager to:
        1. Extract complete test definitions from the mission
        2. Use LLM to detect duplicates, conflicts, and merge candidates
        3. Save tests to file-based repository (source of truth)
        4. Sync to database for graph enrichment
        
        Args:
            task_id: The task ID
            mission_result: Result from run_context_processor
            
        Returns:
            Registration result with merge/conflict info
        """
        result = {
            "success": True,
            "tests_registered": 0,
            "tests_added": 0,
            "tests_duplicates": 0,
            "tests_conflicts": 0,
            "tests_merged": 0,
            "conflicts": [],
            "warnings": []
        }
        
        try:
            mission_data = mission_result.get("mission", {})
            if not mission_data:
                # Try to load from file
                mission_file_path = mission_result.get("mission_file")
                if mission_file_path:
                    mission_file = self.mapper_dir / mission_file_path
                    if mission_file.exists():
                        mission_data = json.loads(mission_file.read_text())
            
            if not mission_data:
                logger.warning("No mission data available for clustering")
                return result
            
            target_node = mission_data.get("target_node", "")
            if not target_node:
                logger.warning("No target_node in mission, skipping clustering")
                return result
            
            await self._send_update("cluster", "running", f"Analyzing tests for {target_node}...")
            
            # Import ClusterManager (lazy import to avoid circular dependencies)
            import sys
            sys.path.insert(0, str(self.mapper_dir))
            from cluster_manager import ClusterManager
            
            # Initialize ClusterManager
            manager = ClusterManager(
                project_id=self.project_id,
                mapper_dir=self.mapper_dir
            )
            
            # Use new repository-based registration with LLM analysis
            await self._send_update("cluster", "running", f"Merging tests into repository for {target_node}...")
            
            repo_result = manager.register_tests_to_repository(
                mission_data=mission_data,
                task_id=task_id,
                sync_to_db=True
            )
            
            # Map repository result to our result structure
            result["success"] = repo_result.get("success", False)
            result["tests_added"] = repo_result.get("tests_added", 0)
            result["tests_duplicates"] = repo_result.get("tests_duplicates", 0)
            result["tests_conflicts"] = repo_result.get("tests_conflicts", 0)
            result["tests_merged"] = repo_result.get("tests_merged", 0)
            result["tests_registered"] = result["tests_added"] + result["tests_merged"]
            result["warnings"] = repo_result.get("warnings", [])
            
            # Convert conflicts to old format for backward compatibility
            for decision in repo_result.get("decisions", []):
                if decision.get("action") == "conflict":
                    result["conflicts"].append({
                        "type": "conflict",
                        "new_test_id": decision.get("test_id"),
                        "reason": decision.get("reason", "")
                    })
            
            # Send appropriate update based on result
            if result["tests_conflicts"] > 0:
                await self._send_update(
                    "cluster", 
                    "completed", 
                    f"Added {result['tests_added']}, {result['tests_conflicts']} conflict(s) detected"
                )
            elif result["tests_duplicates"] > 0:
                await self._send_update(
                    "cluster", 
                    "completed", 
                    f"Added {result['tests_added']}, skipped {result['tests_duplicates']} duplicate(s)"
                )
            else:
                await self._send_update(
                    "cluster", 
                    "completed", 
                    f"Added {result['tests_added']} test(s) to repository '{target_node}'"
                )
            
            logger.info(f"Repository registration complete: {result}")
            
        except Exception as e:
            logger.warning(f"Cluster registration failed: {e}")
            import traceback
            traceback.print_exc()
            result["success"] = False
            result["warnings"].append(f"Clustering error: {str(e)[:100]}")
            await self._send_update("cluster", "skipped", f"Clustering skipped: {str(e)[:50]}")
        
        return result

    async def run_executor(self, task_id: str, mission_file_path: Path) -> Dict[str, Any]:
        """Run executor to execute tests."""
        # Load mission to extract test cases
        test_cases = []
        try:
            mission_data = json.loads(mission_file_path.read_text())
            
            # Extract test cases from mission
            test_cases_list = mission_data.get("test_cases", [])
            if test_cases_list:
                for test_case in test_cases_list:
                    purpose = test_case.get("purpose", "")
                    verification = test_case.get("verification", {})
                    
                    # Add purpose as main test case
                    if purpose:
                        test_cases.append(f"📋 {purpose}")
                    
                if test_cases:
                    await self._send_update("execute", "running", f"Running {len(test_cases)} test cases...")
                else:
                    await self._send_update("execute", "running", "Running tests...")
            else:
                # Fallback: Generate test cases from actions and verification_points (legacy approach)
                verification = mission_data.get("verification_points", {})
                actions = mission_data.get("actions", [])
                intent = mission_data.get("intent", {})
                changes = intent.get("changes", [])
                
                # Get primary entity for context
                primary_entity = intent.get("primary_entity", "").lower()
                
                # Extract only fields that are mentioned in changes (new/changed fields)
                # Get all possible field names from expected_values
                expected_field_names = set(verification.get("expected_values", {}).keys())
                changed_fields = set()
                
                import re
                for change in changes:
                    change_lower = change.lower()
                    
                    # Pattern 1: "added `category` column" or "added category column"
                    field_matches = re.findall(r'`?(\w+)`?\s+(?:column|field|dropdown|select|badge|filter)', change_lower)
                    for match in field_matches:
                        # Verify this field actually exists in expected_values
                        if any(match.lower() == field.lower() for field in expected_field_names):
                            changed_fields.add(match.lower())
                    
                    # Pattern 2: "added category" or "updated category" - extract field name after action verb
                    action_pattern = r'(?:added|updated|modified)\s+`?(\w+)`?'
                    action_matches = re.findall(action_pattern, change_lower)
                    for match in action_matches:
                        if any(match.lower() == field.lower() for field in expected_field_names):
                            changed_fields.add(match.lower())
                    
                    # Pattern 3: Direct field mentions in changes
                    for field_name in expected_field_names:
                        field_lower = field_name.lower()
                        # Check if this field is explicitly mentioned in the change
                        if (
                            field_lower in change_lower and
                            # Make sure it's not part of another word (e.g., "category" not "categories")
                            re.search(r'\b' + re.escape(field_lower) + r'\b', change_lower)
                        ):
                            changed_fields.add(field_lower)
                
                logger.info(f"Changed fields detected from PR/task: {changed_fields}")
                
                # UI Test Cases - Only for changed fields
                if actions:
                    for action in actions:
                        component_role = action.get("component_role", "")
                        field_selectors = action.get("field_selectors", {})
                        
                        # Only include fields that are in changed_fields (exact match or word boundary)
                        relevant_fields = {
                            name: info for name, info in field_selectors.items()
                            if any(
                                changed_field == name.lower() or 
                                re.search(r'\b' + re.escape(changed_field) + r'\b', name.lower())
                                for changed_field in changed_fields
                            )
                        }
                        
                        for field_name, field_info in relevant_fields.items():
                            # User-friendly description for changed fields
                            if field_info.get("tag") == "select":
                                test_cases.append(f"UI: Verify {field_name} dropdown exists and can select a value")
                            elif field_info.get("tag") == "input":
                                test_cases.append(f"UI: Verify {field_name} field exists and can enter a value")
                            elif field_info.get("tag") == "textarea":
                                test_cases.append(f"UI: Verify {field_name} text area exists and can enter text")
                            else:
                                test_cases.append(f"UI: Verify {field_name} field exists and is functional")
                        
                        # Add form submission test only if there are relevant fields
                        if relevant_fields and ("form" in component_role.lower() or "button" in component_role.lower()):
                            fields_list = ", ".join(relevant_fields.keys())
                            test_cases.append(f"UI: Submit form with {primary_entity} including {fields_list} field(s)")
                
                # API Test Cases - Only for changed fields
                api_endpoint = verification.get("api_endpoint", "")
                if api_endpoint:
                    expected_values = verification.get("expected_values", {})
                    # Only include fields that are in changed_fields (exact match)
                    changed_fields_in_api = [
                        field for field in expected_values.keys()
                        if any(changed_field == field.lower() for changed_field in changed_fields)
                    ]
                    
                    if changed_fields_in_api:
                        fields_str = ", ".join(changed_fields_in_api)
                        test_cases.append(f"API: Verify {api_endpoint} accepts and processes {fields_str} field(s)")
                        test_cases.append(f"API: Verify {api_endpoint} returns {fields_str} in response")
                
                # DB Test Cases - Only for changed fields
                db_table = verification.get("db_table", "")
                if db_table:
                    expected_values = verification.get("expected_values", {})
                    # Only include columns that are in changed_fields (exact match)
                    changed_columns = [
                        field for field in expected_values.keys()
                        if any(changed_field == field.lower() for changed_field in changed_fields)
                    ]
                    
                    if changed_columns:
                        columns_str = ", ".join(changed_columns)
                        test_cases.append(f"DB: Verify {columns_str} column(s) exist in {db_table} table")
                        test_cases.append(f"DB: Verify {columns_str} column(s) can store values correctly")
                
                if test_cases:
                    await self._send_update("execute", "running", f"Running {len(test_cases)} test cases...")
                else:
                    await self._send_update("execute", "running", "Running tests...")
        except Exception as e:
            logger.warning(f"Could not extract test cases: {e}")
            await self._send_update("execute", "running", "Running tests...")
        
        try:
            script_path = self.mapper_dir / "executor.py"
            
            # Prepare environment without VIRTUAL_ENV to avoid uv warnings
            import os
            env = os.environ.copy()
            env.pop("VIRTUAL_ENV", None)
            
            # Add project config to environment
            if self.project_config:
                env["PROJECT_BASE_URL"] = self.project_config.get("BASE_URL", "")
                env["PROJECT_API_BASE"] = self.project_config.get("API_BASE", "")
                env["PROJECT_DATABASE_URL"] = self.project_config.get("DATABASE_URL", "")
                # Keep existing DATABASE_URL if PROJECT_DATABASE_URL not set
                if not env.get("PROJECT_DATABASE_URL") and env.get("DATABASE_URL"):
                    pass  # Use existing DATABASE_URL
                elif env.get("PROJECT_DATABASE_URL"):
                    env["DATABASE_URL"] = env["PROJECT_DATABASE_URL"]
            
            process = await asyncio.create_subprocess_exec(
                "uv", "run", "python", str(script_path), str(mission_file_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.mapper_dir),
                env=env
            )
            
            # Stream output line by line so UI gets real-time updates
            output_lines = []
            last_update_time = asyncio.get_event_loop().time()
            
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                
                decoded_line = line.decode().rstrip()
                
                # Clean log line for UI display
                clean_line = self._clean_log_line(decoded_line)
                
                # Keep original line for output_lines to preserve full logs for files
                output_lines.append(decoded_line)
                logger.info(f"[executor] {decoded_line}")
                
                # Send periodic updates to UI (every 5 seconds or on very important lines only)
                current_time = asyncio.get_event_loop().time()
                # Check important markers in the CLEANED line to avoid missing them due to formatting
                is_important = any(marker in clean_line for marker in [
                    '❌', 'Test completed', 'OVERALL', 'TRIPLE-CHECK',
                    'Database Verification', 'API Verification', 'UI Verification',
                    'EXECUTION SUMMARY', 'FAILED', 'PASSED'
                ])

                if is_important or (current_time - last_update_time > 5.0):
                    # Send cleaned line as progress update
                    # For periodic updates, we might want to send the last few cleaned lines
                    # But the UI expects a single message string usually.
                    # Let's send just this line if important, or a batch if periodic.
                    
                    progress_msg = clean_line
                    
                    # Only send if it's different from the last sent message and not empty
                    if progress_msg and progress_msg != getattr(self, '_last_progress_msg', None):
                        await self._send_update("execute", "running", progress_msg)
                        self._last_progress_msg = progress_msg
                    last_update_time = current_time
            
            await process.wait()
            output = "\n".join(output_lines)
            
            # Check for report file
            report_file = self.mapper_dir / "temp" / f"{mission_file_path.stem}_report.json"
            logger.info(f"Looking for report file at: {report_file}")
            
            result = {
                "success": process.returncode == 0,
                "output": output,
                "report_file": str(report_file.relative_to(self.mapper_dir)) if report_file.exists() else None
            }
            
            # Try to read report file even if process failed
            if report_file.exists():
                logger.info(f"Report file found, size: {report_file.stat().st_size} bytes")
                try:
                    report_data = json.loads(report_file.read_text())
                    result["report"] = report_data
                    
                    triple_check = report_data.get("triple_check", {})
                    db_success = triple_check.get("database", {}).get("success", False)
                    api_success = triple_check.get("api", {}).get("success", False)
                    ui_success = triple_check.get("ui", {}).get("success", False)
                    overall_success = report_data.get("overall_success", False)
                    
                    # Count passed/failed checks
                    passed = sum([db_success, api_success, ui_success])
                    failed = 3 - passed
                    
                    # Build scenario-level results message
                    scenario_results = report_data.get("scenario_results", {})
                    scenario_summary_lines = []
                    
                    if scenario_results:
                        # Load mission to get scenario details
                        mission_data = json.loads(mission_file_path.read_text())
                        test_cases = mission_data.get("test_cases", [])
                        
                        # Create a map of scenario_id to scenario details
                        scenario_map = {s.get("id"): s for s in test_cases}
                        
                        for scenario_id, scenario_result in scenario_results.items():
                            # Handle error scenarios (browser_agent_error, critical_error, etc.)
                            if scenario_id in ["browser_agent_error", "critical_error"]:
                                error_msg = scenario_result.get("error", "Unknown error")
                                scenario_summary_lines.append(f"❌ {scenario_id.replace('_', ' ').title()}: {error_msg}")
                                # Show traceback if available (truncated)
                                traceback = scenario_result.get("traceback", "")
                                if traceback:
                                    traceback_lines = traceback.split('\n')
                                    # Show last 5 lines of traceback
                                    if len(traceback_lines) > 5:
                                        traceback_preview = '\n'.join(traceback_lines[-5:])
                                    else:
                                        traceback_preview = traceback
                                    scenario_summary_lines.append(f"    Error details: {traceback_preview}")
                                continue
                            
                            scenario_info = scenario_map.get(scenario_id, {})
                            purpose = scenario_result.get("purpose") or scenario_info.get("purpose", "")
                            verification = scenario_result.get("verification", {})
                            
                            # Handle scenarios with errors
                            if scenario_result.get("error"):
                                error_msg = scenario_result.get("error", "Unknown error")
                                scenario_summary_lines.append(f"❌ {purpose or scenario_id}: {error_msg}")
                                continue
                            
                            if not purpose:
                                continue
                            
                            # Determine overall scenario success
                            scenario_success = scenario_result.get("success", False)
                            ui_checked = verification.get("ui", {}).get("checked", False)
                            api_checked = verification.get("api", {}).get("checked", False)
                            db_checked = verification.get("db", {}).get("checked", False)
                            
                            ui_success_scenario = verification.get("ui", {}).get("success", False) if ui_checked else None
                            api_success_scenario = verification.get("api", {}).get("success", False) if api_checked else None
                            db_success_scenario = verification.get("db", {}).get("success", False) if db_checked else None
                            
                            # Scenario passes if action succeeded and all checked verifications passed
                            scenario_passed = scenario_success
                            if ui_checked:
                                scenario_passed = scenario_passed and ui_success_scenario
                            if api_checked:
                                scenario_passed = scenario_passed and api_success_scenario
                            if db_checked:
                                scenario_passed = scenario_passed and db_success_scenario
                            
                            status_icon = "✅" if scenario_passed else "❌"
                            scenario_summary_lines.append(f"{status_icon} {purpose}")
                            
                            # Add verification point details
                            if ui_checked:
                                ui_status = "✅" if ui_success_scenario else "❌"
                                ui_desc = scenario_info.get("verification", {}).get("ui", "")
                                if ui_desc:
                                    scenario_summary_lines.append(f"    {ui_status} UI: {ui_desc}")
                            
                            if api_checked:
                                api_status = "✅" if api_success_scenario else "❌"
                                api_desc = scenario_info.get("verification", {}).get("api", "")
                                if api_desc:
                                    scenario_summary_lines.append(f"    {api_status} API: {api_desc}")
                            
                            if db_checked:
                                db_status = "✅" if db_success_scenario else "❌"
                                db_desc = scenario_info.get("verification", {}).get("db", "")
                                if db_desc:
                                    scenario_summary_lines.append(f"    {db_status} DB: {db_desc}")
                    
                    # Build final message
                    if overall_success:
                        await self._send_update("execute", "completed", f"All tests passed ({passed}/3 checks)")
                    else:
                        await self._send_update("execute", "failed", f"{failed} check(s) failed, {passed} passed")
                    
                    result["triple_check"] = {
                        "database": db_success,
                        "api": api_success,
                        "ui": ui_success,
                        "overall": overall_success
                    }
                    result["scenario_results"] = scenario_results
                except Exception as e:
                    logger.warning(f"Could not parse report JSON: {e}")

            # If executor failed, extract and show the actual error
            if process.returncode != 0:
                # Try to extract the actual error from output
                error_lines = output.split('\n') if output else []
                error_msg = output
                
                # Look for error patterns in the output
                error_start_idx = None
                for i, line in enumerate(error_lines):
                    # Look for common error indicators
                    if any(keyword in line for keyword in ['Traceback', 'Error:', 'Exception:', '❌', 'FAIL', 'failed']):
                        error_start_idx = i
                        break
                
                if error_start_idx is not None:
                    # Extract error from that point onwards
                    error_section = '\n'.join(error_lines[error_start_idx:])
                    # Also include last 20 lines before error for context
                    context_start = max(0, error_start_idx - 20)
                    error_msg = '\n'.join(error_lines[context_start:])
                else:
                    # Fallback: show last 1000 chars (more likely to contain the error)
                    error_msg = output[-1000:] if len(output) > 1000 else output
                
                # Limit error message but show key parts
                if len(error_msg) > 2000:
                    error_msg = error_msg[:1000] + "\n... (truncated) ...\n" + error_msg[-1000:]
                
                # If we have a report, we don't need to show the raw error as prominently
                if "report" not in result:
                    await self._send_update("execute", "failed", f"Execution failed: {error_msg[:200]}")
                
                result["error"] = output
                return result
            
            if process.returncode == 0:
                if not result.get("triple_check", {}).get("overall", False):
                    await self._send_update("execute", "failed", "Some checks failed")
            else:
                await self._send_update("execute", "failed", "Execution error")
            
            return result
            
        except Exception as e:
            error_msg = str(e)[:100]
            await self._send_update("execute", "failed", f"Error: {error_msg}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def run_full_workflow(self, task_id: str, task_file_path: Path, 
                                pr_link: Optional[str] = None) -> Dict[str, Any]:
        """Run the complete automated workflow: Map → Generate Mission → Execute.
        
        Returns:
            Dict with results from each step and overall status
        """
        await self._send_update("workflow", "running", f"Starting workflow for {task_id}")
        
        results = {
            "task_id": task_id,
            "steps": {},
            "overall_success": False
        }
        
        try:
            # Step 1: Check if mapper needs to run
            should_map = await self.should_run_mapper(task_id, pr_link)
            
            if should_map:
                # Step 2: Run semantic mapper
                map_result = await self.run_semantic_mapper(task_id)
                results["steps"]["map"] = map_result
                
                if not map_result.get("success"):
                    await self._send_update("workflow", "failed", "Mapping failed")
                    results["overall_success"] = False
                    return results
            else:
                await self._send_update("map", "skipped", "Using existing graph")
                results["steps"]["map"] = {"success": True, "skipped": True}
            
            # Step 3: Generate mission
            mission_result = await self.run_context_processor(task_id, task_file_path)
            results["steps"]["generate-mission"] = mission_result
            
            if not mission_result.get("success"):
                await self._send_update("workflow", "failed", "Mission generation failed")
                results["overall_success"] = False
                return results
            
            # Step 3.5: Register tests in cluster and tag semantic graph
            await self._register_tests_in_cluster(task_id, mission_result)
            
            # Step 4: Execute tests
            # Handle None value explicitly (get() default only works if key is missing, not if value is None)
            mission_file_path = mission_result.get("mission_file") or f"temp/{task_id}_mission.json"
            mission_file = self.mapper_dir / mission_file_path
            
            if mission_file.exists():
                execute_result = await self.run_executor(task_id, mission_file)
                results["steps"]["execute"] = execute_result
                results["overall_success"] = execute_result.get("success", False) and \
                    execute_result.get("triple_check", {}).get("overall", False)
            else:
                await self._send_update("execute", "failed", "Mission file not found")
                results["steps"]["execute"] = {
                    "success": False,
                    "error": "Mission file not found"
                }
                results["overall_success"] = False
            
            # Final status
            if results["overall_success"]:
                await self._send_update("workflow", "completed", "All tests passed")
            else:
                await self._send_update("workflow", "failed", "Some tests failed")
            
            return results
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Workflow error: {e}", exc_info=True)
            await self._send_update("workflow", "failed", f"Error: {error_msg[:100]}")
            results["overall_success"] = False
            results["error"] = error_msg
            return results
