"""Phase 1: Context Processor - Intent Extraction & Mission Synthesis

The Context Processor bridges Human Intent (Markdown) and Code Reality (PR)
by anchoring both to the Semantic Graph. It generates a structured "Mission JSON"
that Phase 2 executor can execute without guessing.

Flow:
1. Parse task.md (description + PR link)
2. Extract intent via LLM (entity, changes)
3. Find matching node in semantic graph
4. Analyze PR diff (mocked for now)
5. Generate mission.json with test plan
"""
import os
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
import httpx

# Import graph queries
from graph_queries import GraphQueries

# Try importing PyGithub, fallback to httpx if not available
try:
    from github import Github
    HAS_PYGITHUB = True
except ImportError:
    HAS_PYGITHUB = False

# Import agentic PR context gatherer (optional)
try:
    from agentic_pr_context import AgenticPRContextGatherer
    from github_mcp_client import GitHubMCPClient
    HAS_AGENTIC_CONTEXT = True
except ImportError:
    HAS_AGENTIC_CONTEXT = False

# Import LLM from semantic_mapper
import sys
sys.path.append(os.path.dirname(__file__))


class FixedNutanixChatModel:
    """Simple LLM wrapper for intent extraction."""
    
    def __init__(self, api_url: str, api_key: str, model_name: str = "openai/gpt-oss-120b"):
        self.api_url = api_url
        self.api_key = api_key
        self.model_name = model_name
    
    def _call_api(self, messages: List[dict]) -> dict:
        """Make API call to Nutanix."""
        url = f"{self.api_url}/chat/completions" if "/llm" in self.api_url else f"{self.api_url}/llm/chat/completions"
        
        headers = {
            "Authorization": f"Basic {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"}  # Force JSON output
        }
        
        with httpx.Client(verify=False, timeout=60.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    
    def _fix_response(self, response: dict) -> str:
        """Extract content from Nutanix's non-standard response."""
        choices = response.get("choices", [])
        if not choices:
            return ""
        
        message = choices[0].get("message", {})
        content = message.get("content")
        if content and content != "null":
            return content
        
        reasoning = message.get("reasoning") or message.get("reasoning_content")
        return reasoning or ""
    
    def invoke(self, prompt: str) -> str:
        """Invoke LLM with a prompt."""
        messages = [{"role": "user", "content": prompt}]
        response = self._call_api(messages)
        return self._fix_response(response)


class OllamaChatModel:
    """Simple LLM wrapper for Ollama (local, fast, free)."""
    
    def __init__(self, model_name: str = "llama3.1:8b", base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url
    
    def invoke(self, prompt: str) -> str:
        """Invoke Ollama LLM with a prompt."""
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,  # Deterministic for structured extraction
                "num_predict": 2000  # Limit tokens
            }
        }
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                return result.get("response", "")
        except Exception as e:
            print(f"   ⚠️  Ollama API error: {e}")
            return ""


class ContextProcessor:
    """Processes task markdown and PR diff into structured mission."""
    
    def __init__(self, graph_queries: GraphQueries, llm, ollama_llm=None, use_agentic_context: bool = True):
        self.graph_queries = graph_queries
        self.llm = llm  # Main LLM for intent extraction
        self.ollama_llm = ollama_llm  # Optional Ollama for PR summary (faster, cheaper)
        self.use_agentic_context = use_agentic_context and HAS_AGENTIC_CONTEXT
        
        # Initialize agentic context gatherer if enabled
        self.agentic_gatherer = None
        if self.use_agentic_context:
            try:
                github_client = GitHubMCPClient()
                self.agentic_gatherer = AgenticPRContextGatherer(self.llm, github_client)
                print("   ✅ Agentic PR context gathering enabled")
            except Exception as e:
                print(f"   ⚠️  Failed to initialize agentic context gatherer: {e}")
                self.use_agentic_context = False
    
    def parse_task_markdown(self, task_file: str) -> Dict[str, str]:
        """Parse task.md to extract description and PR link.
        
        Expected format:
        # Task Description
        Description text here...
        
        PR Link: https://github.com/...
        
        Returns:
            Dict with 'description' and 'pr_link' keys
        """
        task_path = Path(task_file)
        if not task_path.exists():
            raise FileNotFoundError(f"Task file not found: {task_file}")
        
        content = task_path.read_text()
        
        # Extract PR link (look for "PR Link:" or "PR:" or GitHub URL)
        pr_link = None
        pr_patterns = [
            r'PR\s*Link:\s*(https?://[^\s]+)',
            r'PR:\s*(https?://[^\s]+)',
            r'(https?://github\.com/[^\s]+)',
            r'(https?://gitlab\.com/[^\s]+)'
        ]
        
        for pattern in pr_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                pr_link = match.group(1)
                break
        
        # Extract description (everything before PR link, or entire content)
        if pr_link:
            description = content.split(pr_link)[0].strip()
        else:
            description = content.strip()
        
        # Remove markdown headers
        description = re.sub(r'^#+\s+', '', description, flags=re.MULTILINE)
        
        return {
            "description": description.strip(),
            "pr_link": pr_link
        }
    
    def _extract_semantic_graph_context(self, task_description: Optional[str] = None) -> Dict[str, Any]:
        """Extract relevant context from semantic graph to help intent extraction.
        
        Uses vector search (if available) to find relevant entities based on task description.
        Otherwise falls back to extracting all entities.
        
        Args:
            task_description: Optional task description to use for semantic search
        
        Returns:
            Dict with entities, APIs, component_types
        """
        nodes = []
        
        # Try semantic search first if task description is available
        if task_description and self.graph_queries.collection:
            try:
                print(f"   🔍 Using vector search for context (query: '{task_description[:30]}...')...")
                search_results = self.graph_queries.semantic_search(task_description, n_results=5)
                
                # Extract nodes from search results
                found_node_ids = set()
                for result in search_results:
                    node_id = result["metadata"].get("node_id") or result["metadata"].get("id")
                    if node_id and node_id not in found_node_ids:
                        # Find full node data
                        node = self.graph_queries.find_node_by_semantic_name(node_id)
                        if node:
                            nodes.append(node)
                            found_node_ids.add(node_id)
                
                print(f"   ✅ Vector search found {len(nodes)} relevant nodes")
            except Exception as e:
                print(f"   ⚠️  Vector search failed: {e}, falling back to full graph scan")
        else:
            # Fallback to all nodes when task_description or collection is not available
            nodes = self.graph_queries.get_all_nodes()
        
        # If vector search returned nothing (or wasn't used), ensure we have some nodes
        if not nodes:
            nodes = self.graph_queries.get_all_nodes()

        apis = self.graph_queries.get_all_apis()
        
        # Extract entities directly from nodes (stored by semantic_mapper)
        entities = set()
        component_types = set()
        
        for node in nodes:
            # Primary source: Use stored primary_entity from semantic_mapper
            primary_entity = node.get("primary_entity")
            if primary_entity:
                entities.add(primary_entity)
            
            # Fallback: Extract from API endpoints if primary_entity not available
            if not primary_entity:
                for api in node.get("active_apis", []):
                    # Extract path from API: "GET /products" -> "Product"
                    api_path = api.split(' ', 1)[-1] if ' ' in api else api
                    if api_path.startswith('/'):
                        path_segment = api_path.strip('/').split('/')[0]
                        if path_segment:
                            # Handle plural: products -> Product
                            if path_segment.endswith('s') and len(path_segment) > 3:
                                entity = path_segment[:-1].title()
                            else:
                                entity = path_segment.title()
                            if len(entity) > 2:
                                entities.add(entity)
                                break  # Found one, move to next node
            
            # Collect component types
            for component in node.get("components", []):
                comp_type = component.get("type", "")
                if comp_type:
                    component_types.add(comp_type)
        
        return {
            "entities": sorted(list(entities)),
            "apis": apis[:20],  # Limit to first 20 to avoid token bloat
            "component_types": sorted(list(component_types)),
            "node_count": len(nodes)
        }
    
    def _extract_pr_summary(self, pr_link: str, task_description: Optional[str] = None) -> Dict[str, Any]:
        """Extract semantic changes from PR diff using LLM.
        
        Focuses on WHAT changed (tables, columns, APIs, UI), not WHERE (file paths).
        Uses Ollama if available (faster, cheaper), falls back to regex if not.
        
        Args:
            pr_link: GitHub PR URL (supports github.com and GitHub Enterprise)
            task_description: Optional task description to help LLM focus on relevant changes
        
        Returns:
            Dict with db_changes, api_changes, ui_changes
        """
        if not pr_link:
            return {}
        
        try:
            # Parse PR URL - support both github.com and GitHub Enterprise (e.g., github.enterprise.com)
            # Pattern: https://[domain]/owner/repo/pull/123
            pr_match = re.search(r'https?://([^/]+)/([^/]+)/([^/]+)/pull/(\d+)', pr_link)
            if not pr_match:
                # Fallback to old pattern for github.com
                pr_match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr_link)
                if not pr_match:
                    return {}
                github_domain = "github.com"
                owner, repo, pr_number = pr_match.groups()
            else:
                github_domain = pr_match.group(1)  # e.g., github.com or github.enterprise.com
                owner = pr_match.group(2)
                repo = pr_match.group(3)
                pr_number = pr_match.group(4)
            
            # Fetch PR diff (pass domain for GitHub Enterprise support)
            pr_data = self._fetch_pr_diff(owner, repo, pr_number, github_domain=github_domain)
            if not pr_data:
                return {}
            
            files = pr_data.get("files", [])
            if not files:
                return {}
            
            # Use agentic context gathering if enabled
            if self.use_agentic_context and self.agentic_gatherer:
                print("   🤖 Using agentic PR context gathering...")
                try:
                    result = self.agentic_gatherer.gather_context(
                        pr_link=pr_link,
                        pr_diff=pr_data,
                        task_description=task_description
                    )
                    # Merge enriched context with test scope
                    enriched = result.get("enriched_context", {})
                    test_scope = result.get("test_scope", {})
                    
                    # Return in format compatible with existing code
                    return {
                        "db_changes": enriched.get("db_changes", {"tables": [], "columns": []}),
                        "api_changes": enriched.get("api_changes", []),
                        "ui_changes": enriched.get("ui_changes", []),
                        "files_changed": enriched.get("files_changed", len(files)),
                        "pr_description": enriched.get("pr_description", {}),
                        "full_files": enriched.get("full_files", {}),
                        "test_scope": test_scope  # NEW: Include test scope decision
                    }
                except Exception as e:
                    print(f"   ⚠️  Agentic context gathering failed: {e}, falling back to standard extraction")
                    # Fall through to standard extraction
            
            # Use LLM if available (Ollama preferred for speed/cost)
            if self.ollama_llm or self.llm:
                return self._extract_pr_summary_with_llm(files, task_description)
            else:
                # Fallback to simple file counting (non-semantic)
                return self._extract_pr_summary_simple(files)
                
        except Exception as e:
            # Silently fail - this is just for context, not critical
            print(f"   ⚠️  PR summary extraction failed: {e}")
            return {}
    
    def _extract_pr_summary_with_llm(self, files: List[Dict], task_description: Optional[str] = None) -> Dict[str, Any]:
        """Extract semantic changes using LLM (Ollama).
        
        Args:
            files: List of file changes from PR diff
            task_description: Optional task description to help focus on relevant changes
        """
        # Build context from PR diff patches (limit to avoid token bloat)
        patches = []
        for file_info in files[:15]:  # Limit to 15 files
            patch = file_info.get("patch", "")
            filename = file_info.get("filename", "")
            if patch:
                # Truncate each patch to first 800 chars (enough for structured changes)
                patch_preview = patch[:800]
                patches.append(f"File: {filename}\n{patch_preview}")
        
        combined_diff = "\n\n---\n\n".join(patches)
        
        # Build prompt with task context if available
        task_context = ""
        if task_description:
            # Truncate task description to avoid token bloat
            task_preview = task_description[:500] if len(task_description) > 500 else task_description
            task_context = f"""

Task Context:
{task_preview}

Use this task context to focus on relevant changes. Extract changes that align with the task requirements.
"""
        
        prompt = f"""Analyze this PR diff and extract WHAT changed. Ignore file paths/names - focus on actual changes.
{task_context}
PR Diff:
{combined_diff}

Extract semantic changes:
1. Database changes: tables and columns added/modified
2. API changes: endpoints added/modified (format: METHOD /path)
3. UI changes: components/fields added/modified, routes/pages added/modified, buttons added/modified, form elements added/modified etc.

{("Focus on changes that relate to the task context above." if task_context else "")}

Respond ONLY in valid JSON format:
{{
  "db_changes": {{
    "tables": ["products"],
    "columns": ["category"]
  }},
  "api_changes": ["POST /products", "GET /products"],
  "ui_changes": ["new category dropdown added", "category filter added", "button removed"]
}}

If no changes found in a category, use empty arrays.
"""
        
        try:
            response = self.llm.invoke(prompt)
            print(f"Ollama response: {response}")
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    # Normalize structure
                    return {
                        "db_changes": result.get("db_changes", {"tables": [], "columns": []}),
                        "api_changes": result.get("api_changes", []),
                        "ui_changes": result.get("ui_changes", []),
                        "files_changed": len(files)
                    }
                except json.JSONDecodeError:
                    pass
            
            # If JSON parsing failed, return empty
            return {"db_changes": {"tables": [], "columns": []}, "api_changes": [], "ui_changes": [], "files_changed": len(files)}
            
        except Exception as e:
            print(f"   ⚠️  LLM extraction failed: {e}, falling back to simple extraction")
            return self._extract_pr_summary_simple(files)
    
    def _extract_pr_summary_simple(self, files: List[Dict]) -> Dict[str, Any]:
        """Fallback: Simple file counting when LLM not available."""
        file_types = {
            "migrations": [],
            "models": [],
            "api_routes": [],
            "frontend": []
        }
        
        for file_info in files:
            filename = file_info.get("filename", "")
            if "alembic/versions" in filename:
                file_types["migrations"].append(filename)
            elif "models.py" in filename:
                file_types["models"].append(filename)
            elif "main.py" in filename or "routes" in filename:
                file_types["api_routes"].append(filename)
            elif filename.endswith((".tsx", ".ts", ".jsx", ".js")):
                file_types["frontend"].append(filename)
        
        return {
            "files_changed": len(files),
            "file_types": {k: len(v) for k, v in file_types.items()},
            "sample_files": [f.get("filename", "") for f in files[:5]]
        }
    
    def extract_intent(self, description: str, 
                      semantic_context: Optional[Dict[str, Any]] = None,
                      pr_summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Use LLM to extract intent: entity, changes, test focus.
        
        Args:
            description: Task description from task.md
            semantic_context: Optional context from semantic graph (entities, APIs, components)
            pr_summary: Optional PR diff summary (files changed, types)
        
        Returns:
            Dict with 'primary_entity', 'changes', 'test_focus'
        """
        # Build context sections
        context_sections = []
        
        if semantic_context:
            entities_str = ", ".join(semantic_context.get("entities", []))
            apis_str = ", ".join(semantic_context.get("apis", [])[:10])  # Limit APIs
            context_sections.append(f"""Available Entities in Application: {entities_str}
Available API Endpoints: {apis_str}
Component Types: {', '.join(semantic_context.get("component_types", []))}""")
        
        if pr_summary:
            # Format PR summary based on extraction method
            if "db_changes" in pr_summary:
                # LLM-extracted semantic changes
                db_changes = pr_summary.get("db_changes", {})
                api_changes = pr_summary.get("api_changes", [])
                ui_changes = pr_summary.get("ui_changes", [])
                
                context_sections.append(f"""PR Changes Summary:
- Database: Tables: {', '.join(db_changes.get('tables', []))}, Columns: {', '.join(db_changes.get('columns', []))}
- API Endpoints: {', '.join(api_changes[:5])}
- UI Changes: {', '.join(ui_changes[:5])}""")
            else:
                # Fallback: file-based summary
                file_types = pr_summary.get("file_types", {})
                files_info = ", ".join([f"{k}: {v}" for k, v in file_types.items() if v > 0])
                sample_files = pr_summary.get("sample_files", [])
                context_sections.append(f"""PR Changes Summary:
- Files Changed: {pr_summary.get('files_changed', 0)}
- File Types: {files_info}
- Sample Files: {', '.join(sample_files[:3])}""")
        
        context_text = "\n\n".join(context_sections) if context_sections else ""
        
        prompt = f"""Analyze this testing task description and extract structured information.

Task Description:
{description}

{f"Context from Application:{chr(10)}{context_text}" if context_text else ""}

Extract:
1. Primary Entity: What is the main thing being tested? Choose from available entities if possible, or infer from description.
2. Specific Changes: What was added/modified? Be specific about fields, endpoints, or components.
3. Test Focus: What should be verified? Focus on the actual changes mentioned.

{f"IMPORTANT: Align entity names with available entities: {', '.join(semantic_context.get('entities', [])) if semantic_context else 'N/A'}" if semantic_context and semantic_context.get('entities') else ""}

Respond in JSON format:
{{
  "primary_entity": "Product",
  "changes": ["added category field to products", "updated POST /products endpoint"],
  "test_focus": "verify category field saves correctly in database and displays in UI"
}}
"""
        
        response = self.llm.invoke(prompt)
        
        # Try to extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        
        # Fallback: parse manually
        entity_match = re.search(r'entity["\']?\s*:\s*["\']?(\w+)', response, re.IGNORECASE)
        changes_match = re.search(r'changes["\']?\s*:\s*\[(.*?)\]', response, re.IGNORECASE)
        
        return {
            "primary_entity": entity_match.group(1) if entity_match else "Unknown",
            "changes": [c.strip().strip('"') for c in changes_match.group(1).split(',')] if changes_match else [],
            "test_focus": response[:200]  # Fallback
        }
    
    def find_target_node(self, entity: str, api_endpoint: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Find the target node in semantic graph matching the entity/API.
        
        Args:
            entity: Primary entity name (e.g., "Item")
            api_endpoint: Optional API endpoint to match (e.g., "POST /items")
        
        Returns:
            Node dict or None
        """
        entity_lower = entity.lower()
        candidate_nodes = []
        
        # Strategy 1: Search by API endpoint (highest priority - most specific)
        if api_endpoint:
            components = self.graph_queries.find_components_using_api(api_endpoint)
            if components:
                node = components[0].get("_node")
                if node:
                    return node
        
        # Strategy 2: Vector search for "create {entity}" pages (if ChromaDB available)
        if self.graph_queries.collection:
            query = f"create or add new {entity_lower}"
            print(f"   🔍 Using vector search to find target node for '{query}'...")
            search_results = self.graph_queries.semantic_search(query, n_results=3)
            
            for result in search_results:
                node_id = result["metadata"].get("node_id") or result["metadata"].get("id")
                if node_id:
                    node = self.graph_queries.find_node_by_semantic_name(node_id)
                    if node:
                        candidate_nodes.append((node, 1.5)) # Good priority
        
        # Strategy 2b (Legacy): Scan all nodes (fallback if vector search missing or insufficient)
        if not candidate_nodes:
                    for node in self.graph_queries.get_all_nodes():
                        components = node.get("components", [])
                        has_create_form = False
                        has_button_opens_form = False
                        
                        for comp in components:
                            # Check for form components
                            if comp.get("type") == "form":
                                role = comp.get("role", "").lower()
                                if "create" in role or entity_lower in role:
                                    has_create_form = True
                                    break
                            
                            # Check for buttons that open forms
                            if comp.get("type") == "button":
                                if comp.get("opens_form") or comp.get("form_role"):
                                    btn_role = comp.get("role", "").lower()
                                    btn_text = comp.get("text", "").lower()
                                    if any(keyword in btn_role or keyword in btn_text for keyword in ["add", "create", "new"]):
                                        has_button_opens_form = True
                                        break
                        
                        if has_create_form or has_button_opens_form:
                            candidate_nodes.append((node, 1))  # High priority
                        else:
                            # Check if node matches entity but doesn't have create capability
                            semantic_name = node.get("semantic_name", "").lower()
                            node_id = node.get("id", "").lower()
                            if entity_lower in semantic_name or entity_lower in node_id:
                                candidate_nodes.append((node, 2))  # Lower priority
                    
        # Return highest priority candidate (lowest number = higher priority)
        if candidate_nodes:
            # Sort by priority (asc)
            candidate_nodes.sort(key=lambda x: x[1])
            return candidate_nodes[0][0]
        
        # Strategy 3: Search by component role patterns
        role_patterns = [
            f"create_{entity_lower}_form",
            f"{entity_lower}_form",
            f"{entity_lower}_catalog",  # Add catalog pattern
            f"{entity_lower}_manager",
            f"{entity_lower}_dashboard"
        ]
        
        for pattern in role_patterns:
            component = self.graph_queries.find_component_by_role(pattern)
            if component:
                return component.get("_node")
        
        return None
    
    def analyze_pr_diff(self, pr_link: str, entity: str) -> Dict[str, Any]:
        """Real PR diff analyzer - fetches and parses GitHub PR diff.
        
        Args:
            pr_link: GitHub PR URL (supports github.com and GitHub Enterprise)
            entity: Primary entity name (e.g., "Item")
        
        Returns:
            Dict with 'db_table', 'db_columns', 'api_endpoints', 'ui_files', 'changes'
        """
        if not pr_link:
            # Fallback to mock if no PR link
            return self._mock_pr_analysis(entity)
        
        try:
            # Parse PR URL - support both github.com and GitHub Enterprise
            # Pattern: https://[domain]/owner/repo/pull/123
            pr_match = re.search(r'https?://([^/]+)/([^/]+)/([^/]+)/pull/(\d+)', pr_link)
            if not pr_match:
                # Fallback to old pattern for github.com
                pr_match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr_link)
                if not pr_match:
                    print(f"   ⚠️  Invalid PR URL format: {pr_link}, using mock")
                    return self._mock_pr_analysis(entity)
                github_domain = "github.com"
                owner, repo, pr_number = pr_match.groups()
            else:
                github_domain = pr_match.group(1)  # e.g., github.com or github.enterprise.com
                owner = pr_match.group(2)
                repo = pr_match.group(3)
                pr_number = pr_match.group(4)
            
            # Fetch PR diff using GitHub API
            print(f"   📥 Fetching PR #{pr_number} from {github_domain}/{owner}/{repo}...")
            pr_data = self._fetch_pr_diff(owner, repo, pr_number, github_domain=github_domain)
            
            if not pr_data:
                print(f"   ⚠️  Could not fetch PR, using mock")
                return self._mock_pr_analysis(entity)
            
            # Parse diff to extract changes
            analysis = self._parse_pr_diff(pr_data, entity)
            print(f"   ✅ Extracted: {len(analysis.get('db_columns', []))} DB columns, "
                  f"{len(analysis.get('api_endpoints', []))} API endpoints")
            
            return analysis
            
        except Exception as e:
            print(f"   ⚠️  PR analysis failed: {e}, using mock")
            import traceback
            traceback.print_exc()
            return self._mock_pr_analysis(entity)
    
    def _fetch_pr_diff(self, owner: str, repo: str, pr_number: str, github_domain: str = "github.com") -> Optional[Dict]:
        """Fetch PR diff from GitHub API (supports GitHub Enterprise).
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
            github_domain: GitHub domain (default: github.com, or e.g., github.enterprise.com)
        
        Returns:
            Dict with 'files' list containing diff data
        """
        try:
            github_token = os.getenv("GITHUB_TOKEN")
            
            # Determine API base URL
            if github_domain == "github.com":
                api_base_url = "https://api.github.com"
            else:
                # GitHub Enterprise: https://github.enterprise.com -> https://github.enterprise.com/api/v3
                api_base_url = f"https://{github_domain}/api/v3"
            
            if HAS_PYGITHUB and github_token:
                # Use PyGithub for cleaner API access
                # PyGithub supports custom base_url for GitHub Enterprise
                if github_domain == "github.com":
                    g = Github(github_token)
                else:
                    # GitHub Enterprise requires base_url
                    g = Github(base_url=api_base_url, login_or_token=github_token)
                
                repo_obj = g.get_repo(f"{owner}/{repo}")
                pr = repo_obj.get_pull(int(pr_number))
                
                files_data = []
                for file in pr.get_files():
                    files_data.append({
                        "filename": file.filename,
                        "status": file.status,
                        "patch": file.patch or "",
                        "additions": file.additions,
                        "deletions": file.deletions
                    })
                
                return {"files": files_data}
            else:
                # Fallback to httpx
                headers = {}
                if github_token:
                    # GitHub Enterprise may need different auth format
                    if github_domain == "github.com":
                        headers["Authorization"] = f"token {github_token}"
                    else:
                        # Some Enterprise instances use Bearer token
                        headers["Authorization"] = f"Bearer {github_token}"
                
                url = f"{api_base_url}/repos/{owner}/{repo}/pulls/{pr_number}/files"
                
                # For GitHub Enterprise, we might need to disable SSL verification
                # (some internal instances use self-signed certs)
                verify_ssl = os.getenv("GITHUB_VERIFY_SSL", "true").lower() == "true"
                
                with httpx.Client(verify=verify_ssl, timeout=30.0, headers=headers) as client:
                    response = client.get(url)
                    
                    if response.status_code == 404:
                        print(f"   ⚠️  PR not found (404). Check authentication and URL.")
                        print(f"   🔍 API URL: {url}")
                        return None
                    
                    if response.status_code == 401:
                        print(f"   ⚠️  Authentication failed (401). Check GITHUB_TOKEN.")
                        return None
                    
                    response.raise_for_status()
                    return {"files": response.json()}
                
        except Exception as e:
            print(f"   ⚠️  GitHub API error: {e}")
            print(f"   🔍 Domain: {github_domain}, API Base: {api_base_url if 'api_base_url' in locals() else 'N/A'}")
            return None
    
    def _parse_pr_diff(self, pr_data: Dict, entity: str) -> Dict[str, Any]:
        """Parse PR diff to extract database, API, and UI changes.
        
        Returns:
            Dict with extracted changes
        """
        files = pr_data.get("files", [])
        
        db_table = None
        db_columns = []
        api_endpoints = []
        ui_files = []
        changes = []
        
        entity_lower = entity.lower()
        
        for file_info in files:
            filename = file_info.get("filename", "")
            patch = file_info.get("patch", "")
            status = file_info.get("status", "")
            
            # Parse migration files
            if "alembic/versions" in filename and filename.endswith(".py"):
                table, columns = self._parse_migration_file(patch, filename)
                if table:
                    db_table = table
                    db_columns.extend(columns)
                    changes.append(f"Migration: {filename}")
            
            # Parse models.py
            elif "models.py" in filename or "app/models.py" in filename:
                table, columns = self._parse_models_file(patch)
                if table:
                    db_table = table or db_table
                    db_columns.extend(columns)
                    changes.append(f"Model: {filename}")
            
            # Parse API routes (main.py)
            elif "main.py" in filename or "app/main.py" in filename:
                endpoints = self._parse_api_routes(patch)
                api_endpoints.extend(endpoints)
                if endpoints:
                    changes.append(f"API: {filename}")
            
            # Parse frontend files
            elif filename.endswith((".tsx", ".ts", ".jsx", ".js")):
                if "frontend" in filename or "src" in filename:
                    ui_files.append(filename)
                    fields = self._parse_frontend_fields(patch)
                    if fields:
                        changes.append(f"UI: {filename} - fields: {', '.join(fields)}")
        
        # Deduplicate columns
        db_columns = list(set(db_columns))
        
        # Default table name if not found
        if not db_table:
            db_table = f"{entity_lower}s"
        
        return {
            "db_table": db_table,
            "db_columns": db_columns,
            "api_endpoints": api_endpoints or [f"POST /{entity_lower}s", f"GET /{entity_lower}s"],
            "ui_files": ui_files,
            "changes": changes
        }
    
    def _parse_migration_file(self, patch: str, filename: str) -> Tuple[Optional[str], List[str]]:
        """Parse Alembic migration file to extract table and column names.
        
        Returns:
            (table_name, [column_names])
        """
        table_name = None
        columns = []
        
        # Extract table name from ALTER TABLE statements
        # Handle schema-qualified names: order_management.products -> products
        table_match = re.search(r'ALTER\s+TABLE\s+([\w.]+)', patch, re.IGNORECASE)
        if table_match:
            full_name = table_match.group(1)
            # Extract table name (last part after dot, or full name if no dot)
            table_name = full_name.split('.')[-1] if '.' in full_name else full_name
        
        # Extract column names from ADD COLUMN
        column_matches = re.findall(r'ADD\s+COLUMN\s+(\w+)', patch, re.IGNORECASE)
        columns.extend(column_matches)
        
        # Extract from Column definitions
        column_defs = re.findall(r'Column\([^)]*name=["\'](\w+)["\']', patch)
        columns.extend(column_defs)
        
        # Extract from sa.Column
        sa_columns = re.findall(r'sa\.Column\([^)]*["\'](\w+)["\']', patch)
        columns.extend(sa_columns)
        
        return table_name, list(set(columns))
    
    def _parse_models_file(self, patch: str) -> Tuple[Optional[str], List[str]]:
        """Parse SQLAlchemy models.py to extract table and column names.
        
        Returns:
            (table_name, [column_names])
        """
        table_name = None
        columns = []
        
        # Extract __tablename__
        table_match = re.search(r'__tablename__\s*=\s*["\'](\w+)["\']', patch)
        if table_match:
            table_name = table_match.group(1)
        
        # Extract Column definitions
        column_matches = re.findall(r'Column\([^)]*name=["\'](\w+)["\']', patch)
        columns.extend(column_matches)
        
        # Extract Column(..., name=...) pattern
        column_name_matches = re.findall(r'name\s*=\s*["\'](\w+)["\']', patch)
        columns.extend(column_name_matches)
        
        # Extract from class attributes (e.g., tag = Column(String))
        attr_matches = re.findall(r'(\w+)\s*=\s*Column\(', patch)
        columns.extend(attr_matches)
        
        return table_name, list(set(columns))
    
    def _parse_api_routes(self, patch: str) -> List[str]:
        """Parse FastAPI routes to extract API endpoints.
        
        Returns:
            List of endpoints (e.g., ["POST /items", "GET /items"])
        """
        endpoints = []
        
        # Extract @app.post("/items") or @app.get("/items")
        route_matches = re.findall(r'@app\.(get|post|put|patch|delete)\(["\']([^"\']+)["\']', patch, re.IGNORECASE)
        for method, path in route_matches:
            endpoints.append(f"{method.upper()} {path}")
        
        # Extract from decorators
        decorator_matches = re.findall(r'@(get|post|put|patch|delete)\(["\']([^"\']+)["\']', patch, re.IGNORECASE)
        for method, path in decorator_matches:
            endpoints.append(f"{method.upper()} {path}")
        
        return list(set(endpoints))
    
    def _parse_frontend_fields(self, patch: str) -> List[str]:
        """Parse frontend files to extract form field names.
        
        Returns:
            List of field names
        """
        fields = []
        
        # Extract placeholder text (e.g., placeholder="Item name")
        placeholder_matches = re.findall(r'placeholder=["\']([^"\']+)["\']', patch, re.IGNORECASE)
        fields.extend(placeholder_matches)
        
        # Extract name attributes
        name_matches = re.findall(r'name=["\']([^"\']+)["\']', patch, re.IGNORECASE)
        fields.extend(name_matches)
        
        # Extract useState hooks (e.g., const [tag, setTag] = useState(''))
        state_matches = re.findall(r'const\s+\[(\w+),\s*set\w+\]\s*=\s*useState', patch, re.IGNORECASE)
        fields.extend(state_matches)
        
        # Extract from select/dropdown elements (e.g., <select name="category">)
        select_matches = re.findall(r'<select[^>]*name=["\']([^"\']+)["\']', patch, re.IGNORECASE)
        fields.extend(select_matches)
        
        # Extract from select id attributes (e.g., <select id="category">)
        select_id_matches = re.findall(r'<select[^>]*id=["\']([^"\']+)["\']', patch, re.IGNORECASE)
        fields.extend(select_id_matches)
        
        return list(set(fields))
    
    def _mock_pr_analysis(self, entity: str) -> Dict[str, Any]:
        """Fallback mock PR analysis."""
        entity_lower = entity.lower()
        
        return {
            "db_table": f"{entity_lower}s",
            "db_columns": ["id", "name", "description"],
            "api_endpoints": [f"POST /{entity_lower}s", f"GET /{entity_lower}s"],
            "ui_files": [],
            "changes": []
        }
    
    def _generate_test_plan_with_llm(self, task_description: str, intent: Dict, 
                                    target_node: Dict, component: Dict, 
                                    form_component: Optional[Dict], 
                                    pr_analysis: Dict) -> Dict[str, Any]:
        """Generate a generic test plan using LLM to avoid hardcoding."""
        
        # Analyze task intent to determine if it's read-only or write operation
        task_lower = task_description.lower()
        changes_text = ' '.join(intent.get('changes', [])).lower()
        test_focus = intent.get('test_focus', '').lower()
        
        # Determine operation type
        is_read_only = any(keyword in task_lower + changes_text + test_focus for keyword in [
            'verify', 'check', 'confirm', 'validate', 'ensure', 'should see', 'should not see',
            'removed', 'removal', 'deleted', 'no longer', 'display', 'shows', 'visible',
            'updated text', 'changed text', 'modified text', 'date changed', 'deadline changed'
        ])
        
        is_write_operation = any(keyword in task_lower + changes_text + test_focus for keyword in [
            'create', 'add', 'new', 'insert', 'save', 'submit', 'post', 'put', 'patch'
        ])
        
        # Determine if form test cases are needed
        needs_form_test = is_write_operation and form_component is not None
        
        # Prepare context for LLM
        components_summary = []
        if form_component:
            fields = [f"{f.get('name')} ({f.get('tag')})" for f in form_component.get('fields', [])]
            components_summary.append(f"Form: {form_component.get('role')} with fields: {', '.join(fields)}")
        if component:
            components_summary.append(f"Interaction Component: {component.get('role')} ({component.get('type')})")
            
        context = f"""
Task: {task_description}
Entity: {intent.get('primary_entity')}
Changes: {', '.join(intent.get('changes', []))}
Test Focus: {intent.get('test_focus', '')}
Target Page: {target_node.get('url')}
Components: {'; '.join(components_summary) if components_summary else 'None'}
DB Table: {pr_analysis.get('db_table')}
API Endpoints: {', '.join(pr_analysis.get('api_endpoints', []))}
"""

        # Build prompt based on operation type
        if is_read_only:
            # Read-only/verification tasks - focus on verification, not form submission
            prompt = f"""You are a QA Test Architect. Create a test plan for this VERIFICATION task.

{context}

CRITICAL: This task is about VERIFYING/CHECKING existing UI elements or content, NOT creating new records.
The task involves: {', '.join(intent.get('changes', []))}

Generate a JSON object with:
1. "test_data": {{}} (empty - no form data needed for verification tasks)
2. "expected_values": {{}} (empty - no database verification needed unless explicitly mentioned)
3. "test_cases": A list of 1-3 VERIFICATION test scenarios. Each must have:
   - "id": unique_snake_case_id
   - "purpose": specific description of what this case verifies
   - "action_type": "verify" (NOT "form" or "filter")
   - "steps": List of human-readable steps focusing on navigation and verification (e.g., "Navigate to page", "Wait for page to load", "Verify element X is visible/not visible", "Verify text contains Y")
   - "verification": Object with "ui" checks (text descriptions of what to verify), "api" and "db" can be null

IMPORTANT:
- Do NOT generate form submission test cases
- Do NOT generate test data for creating records
- Focus ONLY on verifying the changes mentioned in the task
- If the task mentions removing an element, verify it's NOT visible
- If the task mentions updating text, verify the NEW text is displayed

Respond with ONLY the JSON.
"""
        elif needs_form_test:
            # Write operation with form - generate form test cases
            prompt = f"""You are a QA Test Architect. Create a test plan for this FORM SUBMISSION task.

{context}

CRITICAL: This task involves CREATING or UPDATING records via a form.

Generate a JSON object with:
1. "test_data": Key-value pairs for form fields. Use realistic, generic values based on field names and types. Do NOT use hardcoded category values unless the task explicitly mentions them.
2. "expected_values": Key-value pairs to verify in Database (should match test_data).
3. "test_cases": A list of 1-3 test scenarios. Each must have:
   - "id": unique_snake_case_id
   - "purpose": specific description of what this case tests
   - "action_type": "form" or "filter" (as appropriate)
   - "steps": List of human-readable steps. For dropdowns/selects, use instructions like "Select the first available option from [Field Name] dropdown" if specific values aren't known.
   - "verification": Object with "ui", "api", "db" checks (text descriptions)

IMPORTANT:
- Use generic, realistic test data appropriate for the entity type
- For category/dropdown fields, instruct to "Select the first available option" rather than hardcoding values
- Do NOT use application-specific values like 'Electronics' unless the task explicitly mentions them
- Base test data on the actual field names and types from the form component

Respond with ONLY the JSON.
"""
        else:
            # Fallback: generic test plan
            prompt = f"""You are a QA Test Architect. Create a test plan for this task.

{context}

Generate a JSON object with:
1. "test_data": Key-value pairs for form fields (only if forms are involved). Use realistic, generic values.
2. "expected_values": Key-value pairs to verify in Database (only if database verification is needed).
3. "test_cases": A list of 1-3 test scenarios. Each must have:
   - "id": unique_snake_case_id
   - "purpose": specific description of what this case tests
   - "action_type": "form", "filter", or "verify" (choose based on task requirements)
   - "steps": List of human-readable steps
   - "verification": Object with "ui", "api", "db" checks (text descriptions)

IMPORTANT:
- Match test case types to the actual task requirements
- Do NOT generate form test cases if the task is about verification only
- Use generic, realistic test data appropriate for the application domain
- Do NOT hardcode application-specific values

Respond with ONLY the JSON.
"""
        try:
            response = self.llm.invoke(prompt)
            # Extract JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            print(f"   ⚠️  LLM Test Plan Generation failed: {e}")
        
        # Fallback (empty plan)
        return {"test_data": {}, "expected_values": {}, "test_cases": []}
    
    def synthesize_mission(self, task_data: Dict, intent: Dict, target_node: Dict, 
                          pr_analysis: Dict, test_scope: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
        """Synthesize all information into Mission JSON.
        
        Returns:
            Mission JSON ready for Phase 2 executor
        """
        # Find the component to interact with
        component = None
        form_component = None
        print(f"Target node: {target_node}")
        if target_node:
            components = target_node.get("components", [])
            
            # Priority 1: Look for button that opens a form (forms may not be visible initially)
            for comp in components:
                print(f"Component: {comp}")
                if comp.get("type") == "button":
                    # Check if button opens a form
                    if comp.get("opens_form") or comp.get("form_role"):
                        component = comp
                        # Try to find the form component it opens
                        form_role = comp.get("form_role")
                        if form_role:
                            for c in components:
                                if c.get("type") == "form" and c.get("role") == form_role:
                                    form_component = c
                                    break
                            # Fallback: if form_role didn't match, try to find any form with "create" or "add" in role
                            if not form_component:
                                for c in components:
                                    if c.get("type") == "form":
                                        form_role_check = c.get("role", "").lower()
                                        if "create" in form_role_check or "add" in form_role_check or form_role.lower() in form_role_check:
                                            form_component = c
                                            break
                        # If still no form found, try to find any form component
                        if not form_component:
                            for c in components:
                                if c.get("type") == "form":
                                    form_component = c
                                    break
                        break
                    # Fallback: check if button text suggests it opens a form
                    elif not component:
                        btn_text = comp.get("text", "").lower()
                        btn_role = comp.get("role", "").lower()
                        if any(keyword in btn_text or keyword in btn_role for keyword in ["add", "create", "new"]):
                            component = comp
                            # Try to find associated form component
                            for c in components:
                                if c.get("type") == "form":
                                    form_role_check = c.get("role", "").lower()
                                    if "create" in form_role_check or "add" in form_role_check:
                                        form_component = c
                                        break
                            break
            
            # Priority 2: If no button found, try to find a visible form component
            if not component:
                for comp in components:
                    if comp.get("type") == "form":
                        # Check if form selector suggests it's always visible (not in modal)
                        selector = comp.get("selector", "")
                        # If selector doesn't include modal/dialog, assume it's visible
                        if "modal" not in selector.lower() and "dialog" not in selector.lower():
                            form_component = comp
                    component = comp
                    break
                
                # If still no component, use any form as fallback
                if not component:
                    for comp in components:
                        if comp.get("type") == "form":
                            form_component = comp
                            component = comp
                            break
            
            # Final fallback: use first component
            if not component and components:
                component = components[0]
        
        if not component:
            # Fallback if logic above didn't find it
            component = {"role": "unknown", "selector": "body", "type": "unknown"}
            if target_node:
                 components = target_node.get("components", [])
                 if components:
                     component = components[0]
        
        # Final check: If component is a button but we didn't find form_component, try to find it now
        if component.get("type") == "button" and not form_component:
            if target_node:
                components = target_node.get("components", [])
                # Try to find form component by form_role
                form_role = component.get("form_role")
                if form_role:
                    for c in components:
                        if c.get("type") == "form" and c.get("role") == form_role:
                            form_component = c
                            break
                # Fallback: find any form component
                if not form_component:
                    for c in components:
                        if c.get("type") == "form":
                            form_component = c
                            break
        
        # Extract field selectors from form component (for exact selectors in mission)
        field_selectors = {}
        if form_component and form_component.get("fields"):
            for field in form_component["fields"]:
                field_name = field.get("name", "")
                field_selector = field.get("selector", "")
                field_tag = field.get("tag", "input")
                if field_name and field_selector:
                    field_selectors[field_name] = {
                        "selector": field_selector,
                        "tag": field_tag,
                        "type": field.get("type", "text")
                    }
        
        # Extract API endpoint - prefer from PR analysis, then component
        api_endpoint = None
        # First, try to get POST/PUT/PATCH endpoint from PR analysis
        if pr_analysis.get("api_endpoints"):
            for api in pr_analysis["api_endpoints"]:
                if any(method in api for method in ["POST", "PUT", "PATCH"]):
                    api_endpoint = api
                    break
        # Fallback to component's triggers_api
        triggers_api = []
        if not api_endpoint:
            triggers_api = component.get("triggers_api", [])
        if triggers_api:
            # Prefer POST/PUT over GET
            for api in triggers_api:
                if any(method in api for method in ["POST", "PUT", "PATCH"]):
                    api_endpoint = api
                    break
            if not api_endpoint:
                api_endpoint = triggers_api[0]
        
        # Build navigation steps
        # Get base URL from project config or use default
        base_url = os.getenv("PROJECT_BASE_URL", os.getenv("BASE_URL", "http://localhost:5173"))
        target_url = target_node.get("url", base_url) if target_node else base_url
        # If it's a template URL, we can still use it - executor will resolve it
        navigation_steps = [target_url]
        
        # Generate generic test plan using LLM
        test_plan = self._generate_test_plan_with_llm(
            task_data.get("description", ""),
            intent,
            target_node if target_node else {},
            component,
            form_component,
            pr_analysis
        )
        
        test_data = test_plan.get("test_data", {})
        expected_values = test_plan.get("expected_values", {})
        test_cases = test_plan.get("test_cases", [])
        
        # Populate missing details in test cases
        for case in test_cases:
            if not case.get("component_selector"):
                case["component_selector"] = component.get("selector")
            if not case.get("component_role"):
                case["component_role"] = component.get("role")
            case["field_selectors"] = field_selectors
            # Ensure test_data is present if not in case
            if not case.get("test_data"):
                case["test_data"] = test_data
        
        # Default test scope: test everything if not provided
        if test_scope is None:
            test_scope = {
                "test_db": True,
                "test_api": True,
                "test_ui": True,
                "reasoning": "Default: test all layers"
            }
        
        mission = {
            "ticket_id": self._extract_ticket_id(task_data.get("description", "")),
            "target_node": target_node.get("id") or target_node.get("semantic_name") if target_node else "unknown",
            "target_url": target_node.get("url") if target_node else "",
            "navigation_steps": navigation_steps,
            "test_cases": test_cases,  # Unified: each action IS a test case
            "verification_points": {
                "api_endpoint": api_endpoint,
                "db_table": pr_analysis.get("db_table"),
                "expected_values": expected_values
            },
            "intent": {
                "primary_entity": intent.get("primary_entity"),
                "changes": intent.get("changes"),
                "test_focus": intent.get("test_focus")
            },
            "pr_link": task_data.get("pr_link"),
            "test_scope": test_scope  # NEW: Agentic decision on what to test
        }
        
        return mission
    
    
    def _extract_ticket_id(self, description: str) -> str:
        """Extract ticket ID from description (e.g., TICKET-101, JIRA-123)."""
        patterns = [
            r'([A-Z]+-\d+)',  # JIRA-123, TICKET-101
            r'Ticket\s+#?(\d+)',
            r'Issue\s+#?(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(1) if match.lastindex else match.group(0)
        
        return "TICKET-UNKNOWN"


def main():
    """Main entry point for context processor."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Process task markdown into mission JSON")
    parser.add_argument("task_file", nargs="?", default="tasks/task.md", 
                       help="Path to task.md file (default: tasks/task.md)")
    parser.add_argument("--output", "-o", default=None,
                       help="Output mission JSON file (default: temp/<task_name>_mission.json)")
    parser.add_argument("--graph", default="semantic_graph.json",
                       help="Path to semantic graph JSON")
    parser.add_argument("--temp-dir", default="temp",
                       help="Directory for generated files (default: temp)")
    
    args = parser.parse_args()
    
    # Load environment
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    
    api_url = os.getenv("NUTANIX_API_URL")
    api_key = os.getenv("NUTANIX_API_KEY")
    model = os.getenv("NUTANIX_MODEL", "openai/gpt-oss-120b")
    
    if not api_url or not api_key:
        print("❌ Missing NUTANIX_API_URL or NUTANIX_API_KEY in .env file")
        return
    
    print("=" * 70)
    print("🧠 CONTEXT PROCESSOR - Phase 1: Intent Extraction")
    print("=" * 70)
    print()
    
    # Initialize components
    graph_queries = GraphQueries(graph_path=args.graph)
    llm = FixedNutanixChatModel(api_url=api_url, api_key=api_key, model_name=model)
    
    # Initialize Ollama for PR summary extraction (optional, faster/cheaper)
    ollama_llm = None
    try:
        ollama_llm = OllamaChatModel(model_name="llama3.1:8b")
        # Test connection
        test_response = ollama_llm.invoke("test")
        if test_response:
            print("   ✅ Ollama connected (llama3.1:8b)")
        else:
            print("   ⚠️  Ollama not responding, will use fallback")
            ollama_llm = None
    except Exception as e:
        print(f"   ⚠️  Ollama not available: {e}, will use fallback")
        ollama_llm = None
    
    processor = ContextProcessor(graph_queries, llm, ollama_llm=ollama_llm)
    
    # Step 1: Parse task markdown
    print(f"📄 Step 1: Parsing {args.task_file}...")
    try:
        task_data = processor.parse_task_markdown(args.task_file)
        print(f"   ✅ Description: {task_data['description'][:100]}...")
        print(f"   ✅ PR Link: {task_data.get('pr_link', 'Not found')}")
        
        # Extract task name from ticket_id or description
        task_name = processor._extract_ticket_id(task_data.get("description", ""))
        if task_name == "TICKET-UNKNOWN":
            # Try to extract from task file name (e.g., TASK-1_task.md -> TASK-1)
            task_file_stem = Path(args.task_file).stem
            if task_file_stem.startswith("TASK-"):
                # Extract TASK-X from filename (e.g., TASK-1_task -> TASK-1)
                task_name = task_file_stem.split("_")[0].upper()
            elif task_file_stem == "task":
                task_name = "TASK-1"  # task.md -> TASK-1
            else:
                # Try to extract from first line of description
                first_line = task_data.get("description", "").split("\n")[0]
                task_name = re.sub(r'[^\w-]', '_', first_line[:50]).lower()
            if not task_name:
                task_name = "task"
        
        # Create temp directory
        temp_dir = Path(__file__).parent / args.temp_dir
        temp_dir.mkdir(exist_ok=True)
        
        # Generate output filename with task name
        if args.output:
            output_filename = args.output
        else:
            output_filename = f"{task_name}_mission.json"
        
        output_path = temp_dir / output_filename
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return
    
    # Step 2: Gather context for intent extraction
    print()
    print("🧠 Step 2: Gathering context for intent extraction...")
    semantic_context = processor._extract_semantic_graph_context(task_data.get("description", ""))
    print(f"   ✅ Found {len(semantic_context.get('entities', []))} entities, "
          f"{len(semantic_context.get('apis', []))} APIs in semantic graph")
    
    pr_summary = processor._extract_pr_summary(
        task_data.get("pr_link", ""),
        task_description=task_data.get("description", "")
    )
    print(f"   ✅ PR Summary: {pr_summary}")
    if pr_summary:
        print(f"   ✅ PR Summary: {pr_summary.get('files_changed', 0)} files changed")
    
    # Step 2b: Extract intent with context
    print()
    print("🧠 Step 2b: Extracting intent via LLM (with context)...")
    print(f"   ✅ Semantic Context: {semantic_context}")
    print(f"   ✅ PR Summary: {pr_summary}")
    try:
        intent = processor.extract_intent(
            task_data["description"],
            semantic_context=semantic_context,
            pr_summary=pr_summary
        )
        print(f"   ✅ Entity: {intent['primary_entity']}")
        print(f"   ✅ Changes: {intent.get('changes', [])}")
        print(f"   ✅ Focus: {intent.get('test_focus', 'N/A')[:100]}...")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return
    
    # Step 3: Analyze PR diff (needed for finding target node)
    print()
    print("📊 Step 3: Analyzing PR diff...")
    pr_analysis = processor.analyze_pr_diff(
        task_data.get("pr_link", ""),
        intent["primary_entity"]
    )
    print(f"   ✅ DB Table: {pr_analysis['db_table']}")
    print(f"   ✅ DB Columns: {pr_analysis.get('db_columns', [])}")
    print(f"   ✅ API Endpoints: {pr_analysis['api_endpoints']}")
    if pr_analysis.get('changes'):
        print(f"   ✅ Changes: {len(pr_analysis['changes'])} files modified")
    
    # Step 4: Find target node
    print()
    print("🔍 Step 4: Finding target node in semantic graph...")
    try:
        # Try to get POST/PUT/PATCH API endpoint from PR analysis or intent
        api_endpoint = None
        
        # First, try to get from PR analysis (most reliable)
        if pr_analysis.get("api_endpoints"):
            for api in pr_analysis["api_endpoints"]:
                if any(method in api for method in ["POST", "PUT", "PATCH"]):
                    api_endpoint = api
                    break
        
        # Fallback: infer from changes
        if not api_endpoint and intent.get("changes"):
            entity_lower = intent["primary_entity"].lower()
            for change in intent["changes"]:
                change_lower = change.lower()
                if "post" in change_lower or "create" in change_lower:
                    # Extract API endpoint from change description
                    # e.g., "updated POST /products" -> "POST /products"
                    import re
                    api_match = re.search(r'(POST|PUT|PATCH)\s+/(\w+)', change, re.IGNORECASE)
                    if api_match:
                        api_endpoint = f"{api_match.group(1)} /{api_match.group(2)}"
                        break
                    # Fallback: construct from entity
                    api_endpoint = f"POST /{entity_lower}s"
                    break
        
        print(f"   🔍 Using API endpoint: {api_endpoint}")
        target_node = processor.find_target_node(intent["primary_entity"], api_endpoint)
        if target_node:
            print(f"   ✅ Found: {target_node.get('id')} ({target_node.get('url')})")
        else:
            print(f"   ⚠️  No matching node found, using first node")
            nodes = graph_queries.get_all_nodes()
            target_node = nodes[0] if nodes else None
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return
    
    if not target_node:
        print("   ❌ No nodes found in graph. Run semantic_mapper.py first.")
        return
    
    # Step 5: Synthesize mission
    print()
    print("🎯 Step 5: Synthesizing mission...")
    try:
        # Extract test_scope from pr_summary if available (from agentic context gathering)
        test_scope = pr_summary.get("test_scope") if pr_summary else None
        if test_scope:
            print(f"   ✅ Test scope: DB={test_scope.get('test_db')}, API={test_scope.get('test_api')}, UI={test_scope.get('test_ui')}")
        
        mission = processor.synthesize_mission(
            task_data, intent, target_node, pr_analysis, test_scope=test_scope
        )
        
        # Save mission JSON (output_path already set in Step 1)
        with open(output_path, 'w') as f:
            json.dump(mission, f, indent=2)
        
        print(f"   ✅ Mission saved to: {output_path}")
        print()
        print("=" * 70)
        print("✅ MISSION GENERATED")
        print("=" * 70)
        print(json.dumps(mission, indent=2))
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
