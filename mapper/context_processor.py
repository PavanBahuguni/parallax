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
    
    def invoke(self, input: Any) -> Any:
        """Invoke LLM with a prompt or list of messages."""
        if isinstance(input, str):
            messages = [{"role": "user", "content": input}]
        elif isinstance(input, list):
            messages = []
            for m in input:
                content = m.content if hasattr(m, 'content') else str(m)
                role = "user"
                if hasattr(m, '__class__'):
                    if m.__class__.__name__ == "AIMessage":
                        role = "assistant"
                    elif m.__class__.__name__ == "SystemMessage":
                        role = "system"
                messages.append({"role": role, "content": content})
        else:
            messages = [{"role": "user", "content": str(input)}]
            
        response = self._call_api(messages)
        content = self._fix_response(response)
        
        # Return object with content attribute to match LangChain interface
        class Result:
            def __init__(self, content):
                self.content = content
        return Result(content)


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
    
    # UI file extensions for filtering PR diffs
    UI_FILE_EXTENSIONS = {
        '.tsx', '.jsx', '.ts', '.js',  # React/TypeScript
        '.vue', '.svelte',              # Vue/Svelte
        '.html', '.htm',                # HTML
        '.css', '.scss', '.less',       # Styles (for component context)
        '.hbs', '.handlebars',          # Handlebars
        '.ejs', '.pug', '.jade'         # Template engines
    }
    
    def _filter_ui_files(self, files: List[Dict]) -> List[Dict]:
        """Filter PR files to only include UI-relevant files.
        
        Args:
            files: List of file dicts from PR diff (each has 'filename', 'patch', etc.)
        
        Returns:
            Filtered list containing only UI files (.tsx, .jsx, .html, .vue, etc.)
        """
        ui_files = []
        for file_info in files:
            filename = file_info.get("filename", "")
            # Get file extension
            ext = Path(filename).suffix.lower()
            
            if ext in self.UI_FILE_EXTENSIONS:
                ui_files.append(file_info)
            # Also include files in common UI directories
            elif any(ui_dir in filename.lower() for ui_dir in [
                '/components/', '/pages/', '/views/', '/screens/',
                '/ui/', '/frontend/', '/client/', '/web/'
            ]):
                ui_files.append(file_info)
        
        return ui_files
    
    def _extract_ui_elements_from_pr(self, pr_files: List[Dict]) -> List[Dict]:
        """Extract only UI element lines from PR patches for JIT context.
        
        Strips JS logic and keeps only HTML/TSX element additions:
        - <th>, <td>, <div>, <span>, etc.
        - className, id, data-testid attributes
        - Text content within elements
        
        Args:
            pr_files: List of file dicts from PR diff
            
        Returns:
            List of dicts with 'filename' and 'elements' (list of UI element lines)
        """
        import re
        
        ui_files = self._filter_ui_files(pr_files)
        if not ui_files:
            return []
        
        result = []
        
        # Patterns for UI elements we want to extract
        element_pattern = re.compile(
            r'<(th|td|div|span|button|input|select|label|p|h[1-6]|a|table|tr|form|nav|header|section)'
            r'[^>]*',
            re.IGNORECASE
        )
        
        # Pattern for useful attributes
        attr_pattern = re.compile(
            r'(className|class|id|data-[\w-]+|aria-[\w-]+|name|placeholder|title|href)\s*=\s*["\'{][^"\'{}]+["\'}]',
            re.IGNORECASE
        )
        
        # Skip patterns - pure JS/logic lines
        skip_patterns = [
            r'^\s*(import|export|const|let|var|function|return;|if\s*\(|else\s*\{|switch|case|break)',
            r'^\s*//|\s*\*|console\.|\.map\(|\.filter\(|\.reduce\(',
            r'===|!==|&&|\|\||=>\s*\{',
        ]
        skip_regex = re.compile('|'.join(skip_patterns))
        
        for file_info in ui_files[:15]:  # Limit files
            filename = file_info.get("filename", "")
            patch = file_info.get("patch", "")
            if not patch:
                continue
            
            elements = []
            # Only look at added lines
            for line in patch.split('\n'):
                if not line.startswith('+') or line.startswith('+++'):
                    continue
                
                line_content = line[1:].strip()  # Remove the +
                
                # Skip empty lines and pure JS
                if not line_content or skip_regex.search(line_content):
                    continue
                
                # Check for UI elements or attributes
                has_element = element_pattern.search(line_content)
                has_attr = attr_pattern.search(line_content) and '<' in line_content
                
                if has_element or has_attr:
                    # Truncate long lines
                    if len(line_content) > 150:
                        line_content = line_content[:150] + "..."
                    elements.append(line_content)
            
            if elements:
                result.append({
                    "filename": filename,
                    "elements": elements[:15]  # Limit elements per file
                })
        
        return result[:10]  # Limit to 10 files max
    
    def _rerank_nodes_with_pr_context(
        self, 
        candidate_nodes: List[Dict], 
        task_description: str,
        pr_files: List[Dict]
    ) -> List[Dict]:
        """Re-rank candidate nodes using LLM based on PR UI file changes.
        
        Args:
            candidate_nodes: List of candidate nodes from vector search
            task_description: The task description for context
            pr_files: UI-filtered PR files (from _filter_ui_files)
        
        Returns:
            Re-ranked list of nodes (best match first)
        """
        if not candidate_nodes or len(candidate_nodes) <= 1:
            return candidate_nodes
        
        # Filter to UI files only
        ui_files = self._filter_ui_files(pr_files)
        
        if not ui_files:
            print("   ⚠️  No UI files in PR diff for re-ranking, using original order")
            return candidate_nodes
        
        # Build UI file context (file paths + brief patch snippets)
        ui_context_parts = []
        for file_info in ui_files[:10]:  # Limit to 10 files
            filename = file_info.get("filename", "")
            patch = file_info.get("patch", "")
            # Extract key identifiers from patch (component names, routes, etc.)
            patch_preview = patch[:300] if patch else ""
            ui_context_parts.append(f"- {filename}\n  {patch_preview}")
        
        ui_context = "\n".join(ui_context_parts)
        
        # Build node summaries for LLM
        node_summaries = []
        for i, node in enumerate(candidate_nodes):
            node_id = node.get("id", "unknown")
            node_url = node.get("url", "")
            node_path = node.get("path", "")
            display_header = node.get("display_header", "")
            semantic_name = node.get("semantic_name", "")
            
            # Get component info
            components = node.get("components", [])
            component_types = [c.get("type", "") for c in components[:5]]
            component_roles = [c.get("role", "") for c in components[:5] if c.get("role")]
            
            summary = (
                f"{i+1}. Node ID: {node_id}\n"
                f"   URL: {node_url}\n"
                f"   Path: {node_path}\n"
                f"   Header: {display_header}\n"
                f"   Semantic Name: {semantic_name}\n"
                f"   Components: {', '.join(component_types)}\n"
                f"   Roles: {', '.join(component_roles[:3])}"
            )
            node_summaries.append(summary)
        
        nodes_context = "\n\n".join(node_summaries)
        
        # LLM prompt for re-ranking
        prompt = f"""You are analyzing which semantic graph node best matches a task based on PR changes.

TASK DESCRIPTION:
{task_description}

PR UI FILE CHANGES:
{ui_context}

CANDIDATE NODES (from semantic graph):
{nodes_context}

INSTRUCTIONS:
1. Analyze the task description to understand WHAT page/feature is being modified
2. Look at the PR file paths and patches - they indicate which UI components are changed
3. Match the PR changes to the most relevant semantic graph node

Key matching hints:
- File paths like "SalesData/Opportunities.tsx" suggest a "sales_data" or "opportunities" node
- File paths like "Renewals/Bookings.tsx" suggest a "renewals" or "bookings" node
- Component names and routes in the code help identify the correct page

Respond ONLY with a JSON object containing the ranked node IDs (best match first):
{{
  "ranked_node_ids": ["best_node_id", "second_best_id", ...],
  "reasoning": "Brief explanation of why the top choice is best"
}}
"""
        
        try:
            response = self.llm.invoke(prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                result = json.loads(json_match.group())
                ranked_ids = result.get("ranked_node_ids", [])
                reasoning = result.get("reasoning", "")
                
                if ranked_ids:
                    print(f"   🔄 Re-ranked nodes: {ranked_ids[:3]}")
                    print(f"   💡 Reasoning: {reasoning[:100]}...")
                    
                    # Reorder nodes based on LLM ranking
                    node_by_id = {n.get("id"): n for n in candidate_nodes}
                    reranked = []
                    seen = set()
                    
                    # Add nodes in ranked order
                    for node_id in ranked_ids:
                        if node_id in node_by_id and node_id not in seen:
                            reranked.append(node_by_id[node_id])
                            seen.add(node_id)
                    
                    # Add any remaining nodes not in ranking
                    for node in candidate_nodes:
                        if node.get("id") not in seen:
                            reranked.append(node)
                    
                    return reranked
                    
        except Exception as e:
            print(f"   ⚠️  Re-ranking failed: {e}, using original order")
        
        return candidate_nodes
    
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
    
    def _extract_semantic_graph_context(
        self, 
        task_description: Optional[str] = None,
        pr_files: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """Extract relevant context from semantic graph to help intent extraction.
        
        Uses vector search (if available) to find relevant entities based on task description.
        Also includes text-matched nodes that might be missed by vector search.
        Then re-ranks candidates using PR UI file context for better accuracy.
        Otherwise falls back to extracting all entities.
        
        Args:
            task_description: Optional task description to use for semantic search
            pr_files: Optional list of PR file dicts for re-ranking (from _fetch_pr_diff)
        
        Returns:
            Dict with entities, APIs, component_types, and ranked_nodes
        """
        nodes = []
        found_node_ids = set()
        
        # Try semantic search first if task description is available
        if task_description and self.graph_queries.collection:
            try:
                print(f"   🔍 Using vector search for context (query: '{task_description[:30]}...')...")
                search_results = self.graph_queries.semantic_search(task_description, n_results=5)
                
                # Extract nodes from search results
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
        
        # Also do text-based matching to catch nodes vector search might miss
        if task_description:
            task_lower = task_description.lower()
            
            # Extract key terms from task description (e.g., "Sales Data" -> "sales", "data")
            key_terms = []
            # Look for quoted or capitalized terms
            for term in re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', task_description):
                key_terms.extend(term.lower().split())
            # Also add common terms that indicate page types
            if "sales" in task_lower:
                key_terms.append("sales")
            if "renewal" in task_lower:
                key_terms.append("renewal")
            if "opportunity" in task_lower or "opportunities" in task_lower:
                key_terms.append("opportunity")
                key_terms.append("bookings")  # opportunities are often shown in bookings pages
            
            key_terms = list(set(key_terms))  # Dedupe
            
            if key_terms:
                print(f"   🔤 Text matching for terms: {key_terms}")
                all_nodes = self.graph_queries.get_all_nodes()
                
                for node in all_nodes:
                    node_id = node.get("id", "")
                    if node_id in found_node_ids:
                        continue  # Already found by vector search
                    
                    # Check if node matches any key terms
                    node_text = " ".join([
                        node.get("id", ""),
                        node.get("url", ""),
                        node.get("display_header", ""),
                        node.get("description", "")
                    ]).lower()
                    
                    # Score by how many terms match
                    matches = sum(1 for term in key_terms if term in node_text)
                    if matches > 0:
                        nodes.append(node)
                        found_node_ids.add(node_id)
                        print(f"   📌 Text match: {node_id} (matched {matches} terms)")
        
        # Re-rank nodes using PR context if available and we have multiple candidates
        if pr_files and task_description and len(nodes) > 1:
            print(f"   🔄 Re-ranking {len(nodes)} nodes using PR UI file context...")
            nodes = self._rerank_nodes_with_pr_context(nodes, task_description, pr_files)
        
        # Fallback to all nodes when nothing found
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
            # Extract content from Result object
            response_text = response.content if hasattr(response, 'content') else str(response)
            print(f"Ollama response: {response_text}")
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
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

4. Applicable Personas: Which user roles/personas does this test apply to? Common personas include: Reseller, Distributor, Admin, User, etc. If specific roles are mentioned (e.g., "Resellers will see X, Distributors will see Y"), list them. If no personas mentioned, respond with ["default"].

Respond in JSON format:
{{
  "primary_entity": "Product",
  "changes": ["added category field to products", "updated POST /products endpoint"],
  "test_focus": "verify category field saves correctly in database and displays in UI",
  "personas": ["Reseller", "Distributor"]
}}
"""
        
        response = self.llm.invoke(prompt)
        # Extract content from Result object
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # Try to extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        
        # Fallback: parse manually
        entity_match = re.search(r'entity["\']?\s*:\s*["\']?(\w+)', response_text, re.IGNORECASE)
        changes_match = re.search(r'changes["\']?\s*:\s*\[(.*?)\]', response_text, re.IGNORECASE)
        
        return {
            "primary_entity": entity_match.group(1) if entity_match else "Unknown",
            "changes": [c.strip().strip('"') for c in changes_match.group(1).split(',')] if changes_match else [],
            "test_focus": response_text[:200]  # Fallback
        }
    
    def find_target_node(
        self, 
        entity: str, 
        api_endpoint: Optional[str] = None,
        task_description: Optional[str] = None,
        pr_files: Optional[List[Dict]] = None
    ) -> Optional[Dict[str, Any]]:
        """Find the target node in semantic graph matching the entity/API.
        
        Uses multi-strategy search with optional LLM re-ranking based on PR context.
        
        Args:
            entity: Primary entity name (e.g., "Item")
            api_endpoint: Optional API endpoint to match (e.g., "POST /items")
            task_description: Optional task description for re-ranking context
            pr_files: Optional PR file list for LLM re-ranking
        
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
        found_node_ids = set()
        if self.graph_queries.collection:
            query = f"create or add new {entity_lower}"
            print(f"   🔍 Using vector search to find target node for '{query}'...")
            search_results = self.graph_queries.semantic_search(query, n_results=5)  # Get more for re-ranking
            
            for result in search_results:
                node_id = result["metadata"].get("node_id") or result["metadata"].get("id")
                if node_id and node_id not in found_node_ids:
                    node = self.graph_queries.find_node_by_semantic_name(node_id)
                    if node:
                        candidate_nodes.append((node, 1.5)) # Good priority
                        found_node_ids.add(node_id)
        
        # Strategy 2a: Text-based matching from task description
        # This catches nodes vector search might miss (e.g., "Sales Data" -> "sales_bookings")
        if task_description:
            task_lower = task_description.lower()
            key_terms = []
            
            # Extract key terms indicating page type
            if "sales" in task_lower and "renewal" not in task_lower:
                key_terms.append("sales")
            if "renewal" in task_lower and "sales" not in task_lower:
                key_terms.append("renewal")
            if "opportunity" in task_lower or "opportunities" in task_lower:
                key_terms.append("opportunity")
            if "booking" in task_lower or "bookings" in task_lower:
                key_terms.append("booking")
            
            if key_terms:
                print(f"   🔤 Also matching nodes by task terms: {key_terms}")
                all_nodes = self.graph_queries.get_all_nodes()
                
                for node in all_nodes:
                    node_id = node.get("id", "")
                    if node_id in found_node_ids:
                        continue
                    
                    node_text = " ".join([
                        node.get("id", ""),
                        node.get("url", ""),
                        node.get("display_header", ""),
                        node.get("description", "")[:500]  # Limit description length
                    ]).lower()
                    
                    # Check if node matches key terms
                    matches = sum(1 for term in key_terms if term in node_text)
                    if matches > 0:
                        # Higher priority for more matches
                        priority = 1.0 if matches >= 2 else 1.3
                        candidate_nodes.append((node, priority))
                        found_node_ids.add(node_id)
                        print(f"   📌 Text match: {node_id} (matched {matches} terms, priority={priority})")
        
        # Strategy 2b (Legacy): Scan all nodes (fallback if vector search missing or insufficient)
        if not candidate_nodes:
            for node in self.graph_queries.get_all_nodes():
                components = node.get("components", [])
                has_create_form = False
                has_button_opens_form = False
                
                # Check if node matches entity name
                semantic_name = node.get("semantic_name", "").lower()
                node_id = node.get("id", "").lower()
                display_header = node.get("display_header", "").lower()
                
                # Strong match: exact entity name in node ID or header
                if entity_lower in node_id or entity_lower in display_header:
                    candidate_nodes.append((node, 1))  # High priority
                    continue
                
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
                    if entity_lower in semantic_name or entity_lower in node_id:
                        candidate_nodes.append((node, 2))  # Lower priority
        
        # Apply LLM re-ranking if we have PR context and multiple candidates
        if candidate_nodes and pr_files and task_description and len(candidate_nodes) > 1:
            print(f"   🔄 Re-ranking {len(candidate_nodes)} candidate nodes using PR context...")
            # Extract just the nodes for re-ranking
            nodes_only = [node for node, priority in candidate_nodes]
            reranked_nodes = self._rerank_nodes_with_pr_context(nodes_only, task_description, pr_files)
            
            if reranked_nodes:
                # Return the top re-ranked node
                return reranked_nodes[0]
                    
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
                
                # Include PR metadata needed for fetching full files
                return {
                    "files": files_data,
                    "url": pr.url,  # e.g., https://api.github.com/repos/owner/repo/pulls/123
                    "head": {
                        "ref": pr.head.ref,  # branch name
                        "sha": pr.head.sha   # commit SHA
                    },
                    "base": {
                        "ref": pr.base.ref   # target branch (e.g., main)
                    }
                }
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
                    
                    # Also fetch PR metadata for full file access
                    pr_url = f"{api_base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
                    pr_response = client.get(pr_url)
                    pr_info = pr_response.json() if pr_response.status_code == 200 else {}
                    
                    return {
                        "files": response.json(),
                        "url": pr_url,
                        "head": pr_info.get("head", {}),
                        "base": pr_info.get("base", {})
                    }
                
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
        
        print(f"\n   📂 Parsing PR diff ({len(files)} files) for DB/API/UI changes...")
        
        db_table = None
        db_schema = None
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
                print(f"      📊 Found migration file: {filename}")
                table, columns = self._parse_migration_file(patch, filename)
                if table:
                    db_table = table
                    db_columns.extend(columns)
                    changes.append(f"Migration: {filename}")
            
            # Detect database/entity/model files using common patterns
            # Works for any language: Java, Python, Go, TypeScript, etc.
            elif self._is_db_model_file(filename):
                print(f"      📊 Found DB model/entity file: {filename}")
                
                # Try to fetch full file content for accurate table/schema extraction
                full_file_content = self._fetch_file_content_from_pr(pr_data, filename)
                
                table, columns, schema = self._extract_db_info_with_llm(patch, filename, full_file_content)
                if table or columns or schema:
                    if table:
                        db_table = table
                    if schema:
                        db_schema = schema
                    if columns:
                        db_columns.extend(columns)
                    changes.append(f"DB Model: {filename}")
            
            # Parse API routes (main.py)
            elif "main.py" in filename or "app/main.py" in filename:
                print(f"      🔌 Found API routes file: {filename}")
                endpoints = self._parse_api_routes(patch)
                api_endpoints.extend(endpoints)
                if endpoints:
                    print(f"         Found endpoints: {endpoints}")
                    changes.append(f"API: {filename}")
            
            # Parse frontend files
            elif filename.endswith((".tsx", ".ts", ".jsx", ".js")):
                if "frontend" in filename or "src" in filename:
                    ui_files.append(filename)
                    fields = self._parse_frontend_fields(patch)
                    if fields:
                        print(f"      🖥️  Found UI file: {filename} (fields: {fields})")
                        changes.append(f"UI: {filename} - fields: {', '.join(fields)}")
        
        # Deduplicate columns
        db_columns = list(set(db_columns))
        
        # Summary
        print(f"\n   📋 PR Diff Parsing Summary:")
        print(f"      DB Table:    {db_table or 'None found'}")
        print(f"      DB Schema:   {db_schema or 'None found'}")
        print(f"      DB Columns:  {db_columns or 'None found'}")
        print(f"      API Endpoints: {len(api_endpoints)} found")
        print(f"      UI Files:    {len(ui_files)} found")
        
        # Don't create default/hallucinated table or endpoints - only return what was actually found
        return {
            "db_table": db_table if db_table else None,
            "db_schema": db_schema if db_schema else None,
            "db_columns": db_columns,
            "api_endpoints": api_endpoints,  # Empty list if none found, don't hallucinate
            "ui_files": ui_files,
            "changes": changes
        }
    
    def _fetch_file_content_from_pr(self, pr_data: Dict, filename: str) -> Optional[str]:
        """Fetch full file content from GitHub for accurate table/schema extraction.
        
        The diff may not contain @Table or schema annotations if they weren't modified,
        so we fetch the full file to get complete DB info.
        
        Args:
            pr_data: PR data with repo info
            filename: Path to the file in the repo
            
        Returns:
            Full file content or None if fetch fails
        """
        try:
            # Extract repo info from PR data
            pr_url = pr_data.get("url", "")
            # PR URL format: https://api.github.com/repos/owner/repo/pulls/123
            
            print(f"         🔗 PR URL: {pr_url}")
            
            if not pr_url:
                print(f"         ⚠️ No PR URL in pr_data")
                return None
            
            # Parse repo from URL
            match = re.search(r'repos/([^/]+/[^/]+)/pulls', pr_url)
            if not match:
                print(f"         ⚠️ Could not parse repo from PR URL")
                return None
            
            repo = match.group(1)
            print(f"         📦 Repo: {repo}")
            
            # Get the head ref (branch) from PR
            head_ref = pr_data.get("head", {}).get("ref", "main")
            print(f"         🌿 Branch: {head_ref}")
            
            # Fetch file content from GitHub
            import httpx
            github_token = os.getenv("GITHUB_TOKEN")
            if not github_token:
                print(f"         ⚠️ No GITHUB_TOKEN env var, cannot fetch full file")
                return None
            
            headers = {
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3.raw"
            }
            
            # GitHub API to get file content
            file_url = f"https://api.github.com/repos/{repo}/contents/{filename}?ref={head_ref}"
            print(f"         📥 Fetching: {file_url[:80]}...")
            
            response = httpx.get(file_url, headers=headers, timeout=10)
            if response.status_code == 200:
                print(f"         ✅ Fetched {len(response.text)} chars")
                return response.text
            else:
                print(f"         ⚠️ Could not fetch file: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"         ⚠️ Error fetching file: {e}")
            return None
    
    def _parse_migration_file(self, patch: str, filename: str) -> Tuple[Optional[str], List[str]]:
        """Parse Alembic migration file to extract table and column names.
        
        Returns:
            (table_name, [column_names])
        """
        print(f"\n      🔍 Parsing migration file: {filename}")
        table_name = None
        columns = []
        
        # Extract table name from ALTER TABLE statements
        # Handle schema-qualified names: order_management.products -> products
        table_match = re.search(r'ALTER\s+TABLE\s+([\w.]+)', patch, re.IGNORECASE)
        if table_match:
            full_name = table_match.group(1)
            # Extract table name (last part after dot, or full name if no dot)
            table_name = full_name.split('.')[-1] if '.' in full_name else full_name
            print(f"         📋 Found ALTER TABLE: {full_name} → table: {table_name}")
        
        # Extract column names from ADD COLUMN
        column_matches = re.findall(r'ADD\s+COLUMN\s+(\w+)', patch, re.IGNORECASE)
        if column_matches:
            print(f"         📝 Found ADD COLUMN: {column_matches}")
        columns.extend(column_matches)
        
        # Extract from Column definitions
        column_defs = re.findall(r'Column\([^)]*name=["\'](\w+)["\']', patch)
        if column_defs:
            print(f"         📝 Found Column(name=...): {column_defs}")
        columns.extend(column_defs)
        
        # Extract from sa.Column
        sa_columns = re.findall(r'sa\.Column\([^)]*["\'](\w+)["\']', patch)
        if sa_columns:
            print(f"         📝 Found sa.Column: {sa_columns}")
        columns.extend(sa_columns)
        
        unique_columns = list(set(columns))
        print(f"         ✅ Extracted: table={table_name}, columns={unique_columns}")
        
        return table_name, unique_columns
    
    def _is_db_model_file(self, filename: str) -> bool:
        """Check if a file is likely a database model/entity file.
        
        Uses common naming patterns across languages:
        - Java: *Entity.java, */entity/*, */entities/*, */model/*, */models/*
        - Python: models.py, *_model.py
        - Go: *_model.go, */models/*
        - TypeScript: *.entity.ts, */entities/*
        - GraphQL: *.graphqls, *.graphql
        - SQL: *.sql (migrations, schemas)
        """
        filename_lower = filename.lower()
        
        # File extension patterns
        if filename_lower.endswith(('.sql', '.graphqls', '.graphql')):
            return True
        
        # Directory patterns (entity, entities, model, models, domain)
        db_dirs = ['/entity/', '/entities/', '/model/', '/models/', '/domain/', '/schemas/']
        if any(d in filename_lower for d in db_dirs):
            return True
        
        # Filename patterns
        db_patterns = [
            'entity.', '.entity.', '_entity.',  # Java, TypeScript
            'model.', '.model.', '_model.',     # Various
            'models.py',                         # Python/Django/SQLAlchemy
            'schema.',                           # GraphQL, DB schemas
        ]
        basename = filename.split('/')[-1].lower()
        if any(p in basename for p in db_patterns):
            return True
        
        return False
    
    def _extract_db_info_with_llm(self, patch: str, filename: str, 
                                    full_file_content: Optional[str] = None) -> Tuple[Optional[str], List[str], Optional[str]]:
        """Use LLM to extract database table, schema, and column information.
        
        This is language-agnostic and works for any entity/model file format.
        
        Strategy:
        1. First analyze the diff to find columns that were ADDED
        2. If table/schema not in diff, use full file content to find @Table, __tablename__, etc.
        
        Args:
            patch: The git diff/patch content
            filename: The filename for context
            full_file_content: Optional full file content (for extracting table/schema if not in diff)
            
        Returns:
            (table_name, [column_names], schema_name) - columns that were added/modified
        """
        print(f"\n      🤖 Using LLM to extract DB info from: {filename}")
        print(f"         ════════════════════════════════════════════════════════")
        
        if not self.llm:
            print(f"         ⚠️ No LLM available, skipping DB extraction")
            return None, [], None
        
        # Prepare context: use full file if available, otherwise just diff
        if full_file_content:
            # Use full file for table/schema, but highlight the diff for columns
            file_context = full_file_content[:6000] if len(full_file_content) > 6000 else full_file_content
            context_type = "full file with diff highlighted"
            print(f"         📄 Context: FULL FILE ({len(full_file_content)} chars)")
        else:
            file_context = patch[:4000] if len(patch) > 4000 else patch
            context_type = "diff only"
            print(f"         📄 Context: DIFF ONLY ({len(patch)} chars)")
        
        # Log the content being sent
        print(f"         ────────────────────────────────────────────────────────")
        print(f"         📤 FILE CONTENT BEING SENT TO LLM:")
        print(f"         ────────────────────────────────────────────────────────")
        # Show first 1500 chars of content
        content_preview = file_context[:1500]
        for line in content_preview.split('\n')[:40]:  # Max 40 lines
            print(f"         │ {line[:100]}")  # Max 100 chars per line
        if len(file_context) > 1500:
            print(f"         │ ... ({len(file_context) - 1500} more chars)")
        print(f"         ────────────────────────────────────────────────────────")
        
        prompt = f"""Analyze this database entity/model file and extract:
1. The exact DATABASE TABLE NAME (from @Table annotation, __tablename__, or similar)
2. The DATABASE SCHEMA NAME if specified (from schema attribute in @Table, or schema prefix)
3. Any DATABASE COLUMN NAMES that were ADDED or MODIFIED

File: {filename}
Context type: {context_type}

```
{file_context}
```

{f"Diff (showing what was added/changed):{chr(10)}```{chr(10)}{patch[:2000]}{chr(10)}```" if full_file_content and patch else ""}

CRITICAL Instructions:
- Extract the EXACT table name as defined in code (e.g., @Table(name = "opportunity") means table is "opportunity", NOT "opportunities")
- Extract schema if present (e.g., @Table(name = "opportunity", schema = "partner_ssot") means schema is "partner_ssot")
- For columns, only include those that appear in ADDED lines (lines starting with +) in the diff
- Return column names exactly as they appear in the database (snake_case)
- Do NOT pluralize or modify the table name - use exactly what's in the code

Respond ONLY with valid JSON in this exact format:
{{"table_name": "exact_table_name_or_null", "schema": "schema_name_or_null", "columns_added": ["column1", "column2"]}}

Example: If code has @Table(name = "opportunity", schema = "partner_ssot"), respond with:
{{"table_name": "opportunity", "schema": "partner_ssot", "columns_added": [...]}}"""

        try:
            print(f"         📤 SENDING TO LLM...")
            print(f"         ────────────────────────────────────────────────────────")
            print(f"         📝 PROMPT INSTRUCTIONS (key parts):")
            print(f"         │ - Extract EXACT table name from @Table, __tablename__")
            print(f"         │ - Extract schema if present")  
            print(f"         │ - Do NOT pluralize table name")
            print(f"         ────────────────────────────────────────────────────────")
            
            response = self.llm.invoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            print(f"         📥 RAW LLM RESPONSE:")
            print(f"         ────────────────────────────────────────────────────────")
            for line in content.split('\n'):
                print(f"         │ {line}")
            print(f"         ────────────────────────────────────────────────────────")
            
            # Parse JSON response
            json_match = re.search(r'\{[^{}]*\}', content)
            if json_match:
                result = json.loads(json_match.group())
                table_name = result.get("table_name")
                schema = result.get("schema")
                columns = result.get("columns_added", [])
                
                print(f"         ✅ PARSED RESULT:")
                print(f"            Table: {table_name}")
                print(f"            Schema: {schema}")
                print(f"            Columns: {columns}")
                print(f"         ════════════════════════════════════════════════════════")
                
                return table_name, columns, schema
            else:
                print(f"         ⚠️ Could not parse JSON from LLM response")
                print(f"         ════════════════════════════════════════════════════════")
                return None, [], None
                
        except Exception as e:
            print(f"         ❌ LLM extraction failed: {e}")
            print(f"         ════════════════════════════════════════════════════════")
            return None, [], None
    
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
        """Fallback mock PR analysis when PR diff cannot be analyzed.
        
        Returns empty values instead of hallucinated endpoints/tables.
        """
        return {
            "db_table": None,  # Don't hallucinate table names
            "db_columns": [],
            "api_endpoints": [],  # Don't hallucinate API endpoints
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
            
        # Check if target page is a table/list view based on description
        target_description = target_node.get('description', '')
        is_list_view = any(keyword in target_description.lower() for keyword in [
            'table', 'list', 'tabular', 'rows', 'grid', 'booking', 'opportunities'
        ])
        page_type = "TABLE/LIST VIEW (columns are visible directly on this page)" if is_list_view else "Detail/Form page"
        
        context = f"""
Task: {task_description}
Entity: {intent.get('primary_entity')}
Changes: {', '.join(intent.get('changes', []))}
Test Focus: {intent.get('test_focus', '')}
Target Page: {target_node.get('url')}
Target Page Type: {page_type}
Target Page Description: {target_description[:300] if target_description else 'N/A'}
Components: {'; '.join(components_summary) if components_summary else 'None'}
DB Table: {pr_analysis.get('db_table')}
API Endpoints: {', '.join(pr_analysis.get('api_endpoints', []))}
"""

        # Build prompt based on operation type
        if is_read_only:
            # Read-only/verification tasks - focus on verification, not form submission
            prompt = f"""You are a QA Test Architect. Create a test plan for this VERIFICATION task.

{context}

CRITICAL GROUNDING RULES:
1. ONLY test what is EXPLICITLY stated in the task description
2. Do NOT invent new requirements or assumptions
3. Do NOT assume UI labels match backend field names (e.g., if backend has "tcvAmountUplifted", UI might just show "TCV")
4. The task description is the SOLE source of truth for what to verify
5. If the target page is a TABLE/LIST view, verify columns DIRECTLY on that page - do NOT add steps to "open a record" or "click on an item" unless the task EXPLICITLY requires viewing a detail page
6. Check if the target node description mentions "table", "list", or "tabular" - if so, columns are visible on the list page itself
7. HIDDEN FIELD VERIFICATION: Only add "Verify that [field] is NOT in the API response" if the task EXPLICITLY says that field should be hidden/not shown for that persona. Do NOT assume symmetric visibility rules - if task says "A is hidden from Persona1" it does NOT mean "B is hidden from Persona2" unless explicitly stated.

The task involves: {', '.join(intent.get('changes', []))}

For API-to-UI verification:
- If task says "show X in UI from backend field Y", verify the VALUE from API field Y appears in the UI column
- Do NOT verify column headers unless the task explicitly mentions header text
- Use "verify_api_value_in_ui" approach: capture API response, extract field value, verify it displays in UI

Generate a JSON object with:
1. "test_data": {{}} (empty - no form data needed for verification tasks)
2. "expected_values": {{}} (empty - no database verification needed unless explicitly mentioned)
3. "test_cases": A list of test scenarios (one per persona if task mentions personas). Each must have:
   - "id": unique_snake_case_id
   - "purpose": specific description GROUNDED to what the task says
   - "action_type": "verify" (NOT "form" or "filter")
   - "steps": List of SIMPLE, AUTOMATION-FRIENDLY steps using ONLY these patterns:
     * "Log in as a [Role] user." (login handled by gateway)
     * "Verify that the [Column] column is visible." (for column visibility)
     * "Capture the API response." (to intercept network calls)
     * "Verify that the [Column] column displays the value from [fieldName] in the API response." (for API-to-UI verification)
     * "Verify that [fieldName] is NOT in the API response." (for API security - ensures field is not exposed to this persona)
   - "verification": Object with:
     - "ui": MUST be an ARRAY of simple check strings, e.g., ["TCV column is visible", "TCV column displays API value", "API does not expose tcvAmount"]
     - "api_field_mapping": Map of UI column to API field (e.g., {{"TCV": "tcvAmountUplifted"}} for Reseller)
     - "hidden_api_fields": Array of fields that should NOT be in the API response for this persona (e.g., ["tcvAmount"] for Reseller)
     - IMPORTANT: "ui" MUST always be an array, never a string
     - "api" and "db" can be null

CRITICAL STEP GENERATION RULES:
- Do NOT generate steps like "Select a row", "Note the ID", "Call the API manually" - these are NOT automatable
- Do NOT generate "Confirm that..." steps - use "Verify that..." instead
- Do NOT include example text like "(e.g., the first row)" in steps
- Keep steps SHORT and SPECIFIC - each step should map to ONE action
- The test navigates to the page via navigation_path, so do NOT include navigation steps
- API responses are captured automatically via network interception, NOT by manual API calls
- HIDDEN FIELDS: Only add "Verify that [field] is NOT in the API response" if the task EXPLICITLY mentions that specific field should be hidden for that specific persona. Example: if task says "Resellers cannot see tcvAmount", add this check for Reseller only. Do NOT add hidden field checks for other personas unless explicitly stated.

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
   - "verification": Object with "ui" (MUST be array of strings), "api", "db" checks

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

CRITICAL GROUNDING RULES:
1. ONLY test what is EXPLICITLY stated in the task description
2. Do NOT invent new requirements or assumptions
3. The task description is the SOLE source of truth

Generate a JSON object with:
1. "test_data": Key-value pairs for form fields (only if forms are involved). Use realistic, generic values.
2. "expected_values": Key-value pairs to verify in Database (only if database verification is needed).
3. "test_cases": A list of test scenarios. Each must have:
   - "id": unique_snake_case_id
   - "purpose": specific description GROUNDED to what the task says
   - "action_type": "form", "filter", or "verify" (choose based on task requirements)
   - "steps": List of human-readable steps
   - "verification": Object with "ui" (MUST be array of strings), "api", "db" checks

IMPORTANT:
- ONLY test what the task explicitly asks for
- Do NOT invent new requirements not in the task
- Match test case types to the actual task requirements
- Do NOT generate form test cases if the task is about verification only

Respond with ONLY the JSON.
"""
        try:
            response = self.llm.invoke(prompt)
            # Extract content from Result object
            response_text = response.content if hasattr(response, 'content') else str(response)
            # Extract JSON
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            print(f"   ⚠️  LLM Test Plan Generation failed: {e}")
        
        # Fallback (empty plan)
        return {"test_data": {}, "expected_values": {}, "test_cases": []}
    
    def _build_navigation_path(self, target_node: Dict) -> List[Dict[str, Any]]:
        """Build navigation path from entrypoint to target node using semantic graph edges.
        
        Uses BFS to find shortest path from entrypoint to target node, extracting
        selectors from edges for deterministic navigation.
        
        Args:
            target_node: Target node to navigate to
            
        Returns:
            List of navigation steps with actions and selectors
        """
        if not target_node:
            print("   ⚠️ _build_navigation_path: No target node provided")
            return []
        
        target_node_id = target_node.get("id") or target_node.get("semantic_name")
        if not target_node_id:
            print("   ⚠️ _build_navigation_path: Target node has no ID")
            return []
        
        print(f"   🔍 Building navigation path to: {target_node_id}")
        
        # Get graph structure
        graph = self.graph_queries.graph
        nodes = {n.get("id") or n.get("semantic_name"): n for n in graph.get("nodes", [])}
        edges = graph.get("edges", [])
        
        # Filter out external edges - we only want internal navigation
        internal_edges = [e for e in edges if not e.get("is_external", False)]
        print(f"   📊 Graph has {len(nodes)} nodes and {len(internal_edges)} internal edges")
        
        # Find entrypoint node (usually the home/dashboard)
        entrypoints = graph.get("entrypoints", {})
        entrypoint_id = None
        entrypoint_url = None
        
        # Try to find entrypoint from entrypoints dict
        for persona, node_id in entrypoints.items():
            if node_id in nodes:
                entrypoint_id = node_id
                entrypoint_url = nodes[node_id].get("url")
                break
        
        # Fallback: use first node as entrypoint
        if not entrypoint_id and nodes:
            first_node = list(nodes.values())[0]
            entrypoint_id = first_node.get("id") or first_node.get("semantic_name")
            entrypoint_url = first_node.get("url")
        
        print(f"   🏠 Entrypoint: {entrypoint_id} ({entrypoint_url})")
        
        # Check if target_node_id exists in graph, if not try to find a matching node
        if target_node_id not in nodes:
            print(f"   ⚠️ Target node '{target_node_id}' not found in graph, searching for similar...")
            # Try to find a node with similar ID (partial match)
            for node_id in nodes:
                if target_node_id in node_id or node_id in target_node_id:
                    print(f"   ✅ Found similar node: {node_id}")
                    target_node_id = node_id
                    break
        
        if not entrypoint_id or entrypoint_id == target_node_id:
            # Target is the entrypoint, just go there directly
            target_url = target_node.get("url", "")
            if target_url:
                return [{"action": "goto", "url": target_url}]
            return []
        
        # Build adjacency list from internal edges only
        adjacency = {}
        edge_info = {}  # Store edge info for path reconstruction
        
        for edge in internal_edges:
            from_id = edge.get("from")
            to_id = edge.get("to")
            
            # Handle URL-based edge references (convert to node IDs)
            for node_id, node in nodes.items():
                if node.get("url") == from_id:
                    from_id = node_id
                if node.get("url") == to_id:
                    to_id = node_id
            
            if from_id not in adjacency:
                adjacency[from_id] = []
            adjacency[from_id].append(to_id)
            
            # Store edge info for selector extraction
            edge_key = f"{from_id}->{to_id}"
            edge_info[edge_key] = edge
        
        # BFS to find shortest path
        from collections import deque
        
        queue = deque([(entrypoint_id, [entrypoint_id])])
        visited = {entrypoint_id}
        path = None
        
        while queue:
            current, current_path = queue.popleft()
            
            if current == target_node_id:
                path = current_path
                break
            
            for neighbor in adjacency.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, current_path + [neighbor]))
        
        if not path:
            # No path found, log available edges for debugging
            print(f"   ⚠️ No path found from {entrypoint_id} to {target_node_id}")
            print(f"   📋 Available edges from entrypoint:")
            for edge in internal_edges:
                if edge.get("from") == entrypoint_id:
                    print(f"      → {edge.get('to')} via selector: {edge.get('selector')}")
            
            # Try to find any edge that leads to a page with similar name
            for edge in internal_edges:
                to_id = edge.get("to", "")
                if target_node_id in to_id or to_id in target_node_id or "booking" in to_id.lower():
                    print(f"   🔄 Found fallback edge to similar node: {to_id}")
                    path = [entrypoint_id, to_id]
                    break
            
            if not path:
                # No path found - just go to base URL and let gateway handle navigation
                # Don't use target_url directly as it might be an API endpoint
                print(f"   ⚠️ No navigation path available - using base URL only")
                print(f"   💡 Navigation to target page will be handled by gateway or browser-use")
                if entrypoint_url:
                    return [{"action": "goto", "url": entrypoint_url}]
                return [{"action": "goto", "url": "http://localhost:9000/"}]
        
        print(f"   ✅ Found path: {' → '.join(path)}")
        
        # Convert path to navigation steps
        nav_steps = []
        
        # First step: goto entrypoint
        if entrypoint_url:
            nav_steps.append({"action": "goto", "url": entrypoint_url})
        
        # Add click steps for each edge in the path
        for i in range(len(path) - 1):
            from_id = path[i]
            to_id = path[i + 1]
            edge_key = f"{from_id}->{to_id}"
            
            edge = edge_info.get(edge_key, {})
            selector = None
            
            # Priority: link_id > selector > link_text based selector
            link_id = edge.get("link_id")
            if link_id:
                selector = f"a#{link_id}"
            elif edge.get("selector"):
                selector = edge.get("selector")
            elif edge.get("link_text"):
                link_text = edge.get("link_text")
                selector = f":has-text('{link_text}')"
            
            # Check if this edge requires LLM-based navigation
            requires_llm = edge.get("requires_llm_navigation", False)
            to_node = nodes.get(to_id, {})
            
            # Prefer actual captured headers over semantic display_header
            # display_header is generated/inferred, headers[] contains real text from the page
            captured_headers = to_node.get("headers", [])
            # Filter to meaningful headers (not dates, dashes, short strings, copyright)
            meaningful_headers = [
                h for h in captured_headers 
                if h and len(h) > 3 
                and not h.startswith('-')
                and not h.startswith('©')
                and not any(c.isdigit() for c in h[:3])  # Skip dates like "11 Aug 2025"
                and h not in ['-', '|']
            ]
            # Use first meaningful captured header, fallback to display_header
            wait_header = meaningful_headers[0] if meaningful_headers else to_node.get("display_header", to_id)
            display_header = to_node.get("display_header", to_id)  # Keep for navigation instructions
            
            if selector:
                print(f"   📍 Step: click '{selector}' to reach {to_id}")
                nav_steps.append({
                    "action": "click",
                    "selector": selector,
                    "target_node": to_id,
                    "link_text": edge.get("link_text"),  # Include for reference
                    "href": edge.get("href")  # Include href if available
                })
                
                # Add wait for page load using actual captured header
                if wait_header:
                    nav_steps.append({
                        "action": "wait_visible",
                        "selector": f"text={wait_header}",
                        "description": f"Wait for page load (captured header: '{wait_header}')"
                    })
            elif requires_llm or edge.get("inferred_from") == "entrypoint_fallback":
                # No selector available - need LLM-based navigation
                print(f"   🤖 Step: navigate to '{display_header}' (LLM-assisted)")
                nav_steps.append({
                    "action": "navigate_to_page",
                    "target_node": to_id,
                    "target_text": display_header,
                    "link_text": edge.get("link_text", display_header),
                    "requires_llm": True,
                    "instruction": f"Navigate to the '{display_header}' page using the sidebar menu or navigation"
                })
                
                # Add wait for page load using actual captured header
                if wait_header:
                    nav_steps.append({
                        "action": "wait_visible",
                        "selector": f"text={wait_header}",
                        "description": f"Wait for page load (captured header: '{wait_header}')"
                    })
            else:
                print(f"   ⚠️ No selector found for edge {from_id} → {to_id}")
                print(f"      Edge data: {edge}")
        
        print(f"   📋 Navigation path has {len(nav_steps)} steps")
        return nav_steps
    
    def _convert_test_case_to_steps(self, test_case: Dict, target_node: Dict, 
                                     navigation_path: List[Dict]) -> List[Dict[str, Any]]:
        """Convert natural language test case steps to deterministic actions.
        
        Parses natural language steps and maps them to structured actions with
        selectors from the semantic graph.
        
        Args:
            test_case: Test case with natural language steps
            target_node: Target node containing component selectors
            navigation_path: Pre-computed navigation path to include
            
        Returns:
            List of deterministic steps with actions and selectors
        """
        deterministic_steps = []
        nl_steps = test_case.get("steps", [])
        verification = test_case.get("verification", {})
        
        # Check if this test case has a persona (gateway handles login)
        has_persona = bool(test_case.get("persona"))
        
        # Include navigation path as initial steps
        for nav_step in navigation_path:
            deterministic_steps.append(nav_step)
        
        # Get selectors from test case and target node
        component_selector = test_case.get("component_selector")
        field_selectors = test_case.get("field_selectors", {})
        
        # Get components from target node for selector lookup
        components = target_node.get("components", []) if target_node else []
        
        # Get target URL from navigation path to skip redundant navigation steps
        target_url = target_node.get("url", "") if target_node else ""
        
        # Pattern matchers for natural language step conversion
        patterns = [
            # Skip navigation to URL if already navigated via navigation_path
            # These will be handled separately below
            (r"navigate to (?:the )?(?:http[s]?://[^\s]+)\.?$", "skip_url_navigation"),
            (r"go to (?:the )?(?:http[s]?://[^\s]+)\.?$", "skip_url_navigation"),
            
            # Navigation patterns - these are handled by browser-use since we don't have selectors
            (r"navigate to (?:the )?(.+?)(?:\s+page|\s+url)?\s*(?:using .+)?$", "navigate"),
            (r"go to (?:the )?(.+?)(?:\s+page|\s+url)?$", "navigate"),
            
            # Click patterns
            (r"click (?:on )?(?:the )?(.+?)(?:button|link|row)?\.?$", "click"),
            (r"open (?:the )?(.+?)(?:record|item|row)?\.?$", "click"),
            (r"select (?:the )?(.+)\.?$", "click"),
            
            # Wait patterns
            (r"wait for (?:the )?(.+?) to (?:load|appear|be visible)\.?$", "wait_visible"),
            (r"wait (?:for )?(?:the )?(.+?) (?:to )?load(?:ing)?\s*(?:completely)?\.?$", "wait_visible"),
            
            # Verification patterns
            (r"verify (?:that )?(?:the )?(.+?) is visible\.?$", "assert_visible"),
            (r"verify (?:that )?(?:the )?(.+?) shows (.+)\.?$", "assert_text"),
            (r"verify (?:that )?(?:a )?column (?:header )?(?:labeled )?['\"]?(.+?)['\"]? is visible\.?$", "assert_column"),
            (r"confirm (?:that )?(?:there is )?no (?:separate )?(.+?)(?:column|field)?\s*(?:displaying .+)?\.?$", "assert_not_visible"),
            
            # Fill patterns
            (r"enter ['\"]?(.+?)['\"]? (?:in|into) (?:the )?(.+?)(?:field|input)?\.?$", "fill"),
            (r"type ['\"]?(.+?)['\"]? (?:in|into) (?:the )?(.+?)(?:field|input)?\.?$", "fill"),
            
            # API verification patterns
            (r"(?:using .+)?send a (?:GET|POST|PUT|DELETE) request to (?:the )?(.+?) endpoint\.?$", "verify_api"),
            (r"verify (?:that )?(?:the )?response (?:includes|contains) (?:the )?(?:fields? )?['\"]?(.+?)['\"]?\.?$", "verify_api_fields"),
            
            # API capture and extraction patterns
            (r"capture (?:the )?(?:graphql |graphql api |api |API )?response(?:s)?(?: (?:that |which )?(?:provides|contains|includes|for) .+)?\.?$", "capture_api"),
            (r"(?:open (?:the )?)?(?:network inspector|devtools)(?: and)? capture (?:the )?(?:graphql |api )?response(?:s)?(?: for .+)?\.?$", "capture_api"),
            (r"trigger (?:the )?(?:graphql |api )?query.+capture (?:the )?(?:graphql |api )?response(?:s)?\.?$", "capture_api"),
            (r"extract (?:the )?value of (?:the )?['\"]?(\w+)['\"]? (?:field )?from (?:the )?(?:api |API )?response\.?$", "extract_api_field"),
            (r"extract (?:the )?(\w+) (?:value )?(?:for .+)?from (?:the )?(?:api |API )?response\.?$", "extract_api_field"),
            # Pattern: "Extract the tcvAmountUplifted field value from the API response"
            (r"extract (?:the )?(\w+) field (?:value )?from (?:the )?(?:api |API |captured )?(?:api )?response\.?$", "extract_api_field"),
            
            # API value in UI patterns (verify API data displays correctly in UI)
            (r"verify (?:that )?(?:the )?(.+?) (?:column|field|cell) (?:displays|shows|contains) (?:the )?(?:value )?(?:returned by (?:the )?(?:api )?(?:field )?)?(\w+)(?: for .+)?\.?$", "verify_api_value_in_ui"),
            (r"verify (?:that )?(?:the )?(.+?) (?:column|field|cell) (?:displays|shows|contains) (?:the |a )?(?:value|values)? ?(?:from |that (?:corresponds|matches) (?:to )?(?:the )?)?(\w+)(?:\s+(?:field|data))?\.?$", "verify_api_value_in_ui"),
            (r"verify (?:that )?(?:the )?(.+?) (?:column|field|cell) (?:displays|shows|contains) (?:the )?(?:value )?(?:retrieved|returned|from) (?:from )?(?:the )?(\w+)(?: field)?(?: in (?:the )?(?:api |captured )?(?:api )?response)?\.?$", "verify_api_value_in_ui"),
            (r"(?:the )?(.+?) (?:column|field) (?:shows|displays|contains) (\w+) values?\.?$", "verify_api_value_in_ui"),
            (r"verify (?:that )?(?:the )?(.+?) (?:column|field) displays the extracted (\w+) value\.?$", "verify_api_value_in_ui"),
            # Pattern: "Verify that the TCV column displays the value from the tcvAmountUplifted field in the captured API response"
            (r"verify (?:that )?(?:the )?(.+?) (?:column|field) (?:displays|shows) (?:the )?value (?:from )?(?:the )?(\w+) field (?:in )?(?:the )?(?:captured )?(?:api )?response\.?$", "verify_api_value_in_ui"),
            
            # Column visibility patterns (various phrasings)
            (r"verify (?:that )?(?:the )?(?:TCV|tcv) column is visible(?:\s+(?:in the UI|on (?:the )?page))?\.?$", "assert_tcv_visible"),
            (r"verify (?:that )?(?:the )?(\w+) column is visible(?:\s+(?:in the UI|on (?:the )?page))?\.?$", "assert_column_visible"),
            (r"for each .+(?:row|record).+verify (?:that )?(?:the )?(\w+) column is visible\.?$", "assert_column_visible"),
            (r"(?:for each .+)?verify (?:that )?(?:the )?(\w+) column (?:is )?(?:visible|displayed|shown)(?:\s+(?:in|on) .+)?\.?$", "assert_column_visible"),
            
            # Simple "Capture the API response" pattern
            (r"capture (?:the )?api response\.?$", "capture_api"),
            
            # Locate/find column patterns
            (r"locate (?:the )?(.+?) column(?: (?:in )?(?:the )?.+)?\.?$", "assert_column_visible"),
            (r"find (?:the )?(.+?) column(?: (?:in )?(?:the )?.+)?\.?$", "assert_column_visible"),
            
            # "field is NOT in the API response" patterns - API security check
            (r"verify (?:that )?(?:the )?(\w+) (?:is not|is NOT|isn't) (?:in|present in|returned in|exposed in) (?:the )?api response\.?$", "assert_field_not_visible"),
            (r"confirm (?:that )?(?:the )?(\w+) (?:is not|is NOT|isn't) (?:in|present in|returned in|exposed in) (?:the )?api response\.?$", "assert_field_not_visible"),
            
            # Legacy "value is not displayed/rendered" patterns - still need to support for backward compatibility
            (r"confirm (?:that )?(?:the )?(\w+)(?: value)? (?:is not|isn't) (?:displayed|shown|visible)(?: (?:anywhere )?(?:in )?(?:the )?UI)?(?: for .+)?\.?$", "assert_field_not_visible"),
            (r"verify (?:that )?(?:the )?(\w+)(?:Amount|value)? (?:is not|isn't) (?:displayed|shown|visible)(?:\s+(?:anywhere )?in (?:the )?UI)?(?: for .+)?\.?$", "assert_field_not_visible"),
            (r"verify (?:that )?(?:the )?(\w+)(?: field)? (?:is not|isn't) (?:rendered|displayed|shown|visible)(?: (?:or visible )?)?(?:in (?:the )?UI)?\.?$", "assert_field_not_visible"),
            # Pattern: "Verify that the tcvAmount value is not rendered in the TCV column"
            (r"verify (?:that )?(?:the )?(\w+)(?: value)? (?:is not|isn't) (?:rendered|displayed|shown) (?:in )?(?:the )?(.+?) (?:column|field)(?:\s*\(.+\))?\.?$", "assert_field_not_visible"),
            
            # Log in patterns - various formats
            (r"log in (?:to )?(?:the )?application as (?:a )?(?:user with )?(?:the )?(.+?) role\.?$", "login"),
            (r"log in (?:to )?(?:the )?application as (?:a )?(.+?) user\.?$", "login"),
            (r"log in as (?:a )?(.+?) user\.?$", "login"),
            (r"sign in as (?:a )?(.+?) user\.?$", "login"),
            (r"authenticate as (?:a )?(.+?)\.?$", "login"),
        ]
        
        for step_text in nl_steps:
            step_text_lower = step_text.lower().strip()
            action_added = False
            
            for pattern, action_type in patterns:
                match = re.match(pattern, step_text_lower, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    
                    if action_type == "skip_url_navigation":
                        # Skip navigation to URL - already handled by navigation_path
                        # The navigation_path already takes us to the target URL
                        print(f"      ⏭️ Skipping redundant URL navigation: {step_text[:50]}...")
                        action_added = True
                        break
                    
                    elif action_type == "navigate":
                        # Navigation step - handled by browser-use agent
                        # This is for in-app navigation (e.g., clicking sidebar menus)
                        target = groups[0] if groups else ""
                        deterministic_steps.append({
                            "action": "navigate_to_page",
                            "target_text": target.strip(),
                            "instruction": f"Navigate to {target.strip()}",
                            "requires_llm": True,
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type == "click":
                        target = groups[0] if groups else ""
                        # Try to find selector from components
                        selector = None
                        for comp in components:
                            comp_text = (comp.get("text", "") or comp.get("role", "")).lower()
                            if target in comp_text or comp_text in target:
                                selector = comp.get("selector")
                                break
                        
                        if not selector:
                            # Use text-based selector
                            selector = f":has-text('{target.strip()}')"
                        
                        deterministic_steps.append({
                            "action": "click",
                            "selector": selector,
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type == "wait_visible":
                        target = groups[0] if groups else ""
                        # Try to find specific selector
                        selector = f":has-text('{target.strip()}')"
                        
                        # Check for table-specific patterns
                        if "table" in target or "list" in target:
                            selector = "table, [role='table'], .table, [class*='table']"
                        
                        deterministic_steps.append({
                            "action": "wait_visible",
                            "selector": selector,
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type in ["assert_visible", "assert_column"]:
                        target = groups[0] if groups else ""
                        # For column verification, look for th or header element
                        if action_type == "assert_column":
                            selector = f"th:has-text('{target.strip()}')"
                        else:
                            selector = f":has-text('{target.strip()}')"
                        
                        deterministic_steps.append({
                            "action": "assert_visible",
                            "selector": selector,
                            "expected": target.strip(),
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type == "assert_text":
                        target = groups[0] if groups else ""
                        expected = groups[1] if len(groups) > 1 else ""
                        
                        deterministic_steps.append({
                            "action": "assert_text",
                            "selector": f":has-text('{target.strip()}')",
                            "expected": expected.strip(),
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type == "assert_not_visible":
                        target = groups[0] if groups else ""
                        
                        deterministic_steps.append({
                            "action": "assert_not_visible",
                            "selector": f":has-text('{target.strip()}')",
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type == "fill":
                        value = groups[0] if groups else ""
                        field = groups[1] if len(groups) > 1 else ""
                        
                        # Try to find field selector
                        selector = field_selectors.get(field, {}).get("selector")
                        if not selector:
                            selector = f"input[placeholder*='{field}'], input[name*='{field}']"
                        
                        deterministic_steps.append({
                            "action": "fill",
                            "selector": selector,
                            "value": value,
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type in ["verify_api", "verify_api_fields"]:
                        target = groups[0] if groups else ""
                        
                        deterministic_steps.append({
                            "action": "verify_api",
                            "endpoint": target.strip(),
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type == "verify_api_value_in_ui":
                        # Extract UI element and API field from matched groups
                        ui_element = groups[0] if groups else ""  # e.g., "TCV column"
                        api_field_lower = groups[1] if len(groups) > 1 else ""  # lowercase from regex
                        
                        # Preserve original case for API field by finding it in original step_text
                        # The regex matched on lowercase, but we need the original case
                        api_field = api_field_lower
                        # Look for common camelCase patterns in original text
                        camel_match = re.search(r'\b(tcvAmountUplifted|tcvAmount|[a-z]+[A-Z][a-zA-Z]*)\b', step_text)
                        if camel_match:
                            api_field = camel_match.group(1)
                        
                        # Determine selector based on UI element description
                        selector = ""
                        ui_lower = ui_element.lower()
                        if "column" in ui_lower:
                            # Look for table cells in that column
                            column_name = ui_element.replace("column", "").strip()
                            selector = f"table td, table th:has-text('{column_name}') ~ td"
                        elif "field" in ui_lower:
                            field_name = ui_element.replace("field", "").strip()
                            selector = f"[data-field='{field_name}'], :has-text('{field_name}')"
                        else:
                            selector = f":has-text('{ui_element.strip()}')"
                        
                        deterministic_steps.append({
                            "action": "verify_api_value_in_ui",
                            "field": api_field.strip(),  # API field to extract (preserved case)
                            "selector": selector,  # Where to look in UI
                            "format": "currency",  # Assume currency for financial values
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type == "capture_api":
                        # Step to capture API responses - executor will intercept network calls
                        deterministic_steps.append({
                            "action": "capture_api",
                            "description": step_text,
                            "wait_for_network": True
                        })
                        action_added = True
                        break
                    
                    elif action_type == "extract_api_field":
                        field_lower = groups[0] if groups else ""
                        # Preserve original case for API field
                        field = field_lower
                        camel_match = re.search(r'\b(tcvAmountUplifted|tcvAmount|[a-z]+[A-Z][a-zA-Z]*)\b', step_text)
                        if camel_match:
                            field = camel_match.group(1)
                        deterministic_steps.append({
                            "action": "extract_api_field",
                            "field": field.strip(),
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type == "assert_tcv_visible":
                        # Specific handler for TCV column verification
                        deterministic_steps.append({
                            "action": "assert_visible",
                            "selector": "th:has-text('TCV'), span.title:has-text('TCV')",
                            "expected": "TCV",
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type == "assert_column_visible":
                        column_name_raw = groups[0] if groups else ""
                        # Look for the original case in step_text (since we matched on lowercase)
                        # Find the column name in original text to preserve case
                        column_match = re.search(r'(?:the\s+)?(\w+)\s+column', step_text, re.IGNORECASE)
                        if column_match:
                            column_name = column_match.group(1)
                        else:
                            column_name = column_name_raw.upper() if len(column_name_raw) <= 4 else column_name_raw.title()
                        
                        deterministic_steps.append({
                            "action": "assert_visible",
                            "selector": f"th:has-text('{column_name}'), span.title:has-text('{column_name}')",
                            "expected": column_name.strip(),
                            "description": step_text
                        })
                        action_added = True
                        break
                    
                    elif action_type == "assert_field_not_visible":
                        field_lower = groups[0] if groups else ""
                        # Preserve original case for API field
                        field_name = field_lower
                        camel_match = re.search(r'\b(tcvAmountUplifted|tcvAmount|[a-z]+[A-Z][a-zA-Z]*)\b', step_text)
                        if camel_match:
                            field_name = camel_match.group(1)
                        # For tcvAmount vs tcvAmountUplifted, we verify the raw field isn't in the API response
                        # This is an API security check - the field should not be returned to this persona
                        field_name_clean = field_name.strip()
                        deterministic_steps.append({
                            "action": "assert_api_field_not_shown",
                            "field": field_name_clean,
                            "description": f"API Security Check: Verify '{field_name_clean}' is not exposed in API response"
                        })
                        action_added = True
                        break
                    
                    elif action_type == "login":
                        # Skip login steps when persona is present (gateway handles login)
                        if has_persona:
                            # Skip this step - gateway already handles login
                            action_added = True
                            break
                        
                        role = groups[0] if groups else ""
                        
                        # Login step - will be handled by gateway execution
                        deterministic_steps.append({
                            "action": "login",
                            "role": role.strip(),
                            "description": step_text
                        })
                        action_added = True
                        break
            
            # If no pattern matched, check for login-related text and skip if persona present
            if not action_added:
                # Check if this is a login step that didn't match the pattern
                login_keywords = ["log in", "login", "sign in", "authenticate"]
                is_login_step = any(kw in step_text_lower for kw in login_keywords)
                
                if is_login_step and has_persona:
                    # Skip login steps - gateway handles this
                    continue
                
                deterministic_steps.append({
                    "action": "manual",
                    "description": step_text,
                    "requires_browser_use": True
                })
        
        # Add verification steps based on test case verification requirements
        ui_verification = verification.get("ui")
        if ui_verification:
            # Check if it's a structured verification with field mappings
            if isinstance(ui_verification, dict):
                # Look for field-specific verifications
                for key, value in ui_verification.items():
                    # Keys like "tcv_amount_uplifted_displayed" indicate API field verification
                    if "uplifted" in key.lower() or "amount" in key.lower():
                        # Extract field name from key
                        field_match = re.search(r'(tcv\w+|amount\w+)', key, re.IGNORECASE)
                        if field_match:
                            field_name = field_match.group(1)
                            # Convert snake_case to camelCase
                            parts = field_name.split('_')
                            camel_field = parts[0] + ''.join(p.title() for p in parts[1:])
                            
                            deterministic_steps.append({
                                "action": "verify_api_value_in_ui",
                                "field": camel_field,
                                "selector": "table tbody td",
                                "format": "currency",
                                "endpoint": "/api/v1/opportunity",
                                "description": f"Verify {camel_field} from API is displayed in UI"
                            })
                    else:
                        deterministic_steps.append({
                            "action": "verify_ui",
                            "expected": value,
                            "description": f"UI Verification: {value}"
                        })
            else:
                deterministic_steps.append({
                    "action": "verify_ui",
                    "expected": ui_verification,
                    "description": f"UI Verification: {ui_verification}"
                })
        
        if verification.get("api"):
            deterministic_steps.append({
                "action": "verify_api",
                "expected": verification.get("api"),
                "description": f"API Verification: {verification.get('api')}"
            })
        
        if verification.get("db"):
            deterministic_steps.append({
                "action": "verify_db",
                "expected": verification.get("db"),
                "description": f"DB Verification: {verification.get('db')}"
            })
        
        return deterministic_steps
    
    def _build_api_verification(self, target_node: Dict, test_cases: List[Dict], 
                                 pr_analysis: Dict, verification_points: Dict) -> Dict[str, Any]:
        """Build API verification configuration for inline verification during execution.
        
        Extracts API endpoints and expected fields from semantic graph, test cases,
        and PR analysis.
        
        Args:
            target_node: Target node with active_apis
            test_cases: Test cases with verification requirements
            pr_analysis: PR analysis with API changes
            verification_points: Existing verification points
            
        Returns:
            API verification configuration for inline checks
        """
        api_verification = {
            "inline": True,  # Verify during execution, not after
            "capture_during": True,  # Capture all API calls during execution
            "endpoints": []
        }
        
        # Extract expected fields from intent/PR analysis
        expected_fields = []
        if pr_analysis.get("db_changes"):
            for change in pr_analysis.get("db_changes", []):
                # Extract field names from changes like "added tcv_amount column"
                field_match = re.search(r"(?:added|modified|changed)\s+(\w+)", change, re.IGNORECASE)
                if field_match:
                    expected_fields.append(field_match.group(1))
        
        # Get active APIs from target node
        active_apis = target_node.get("active_apis", []) if target_node else []
        
        for api in active_apis:
            # Parse API string like "GET /api/v1/opportunity?..."
            parts = api.split(" ", 1)
            method = parts[0] if parts else "GET"
            url = parts[1] if len(parts) > 1 else api
            
            # Extract path without query params
            path = url.split("?")[0] if "?" in url else url
            
            endpoint_config = {
                "method": method,
                "url": path,
                "expected_fields": expected_fields if expected_fields else None,
                "verify_after_navigation": True  # Verify after navigating to page
            }
            
            api_verification["endpoints"].append(endpoint_config)
        
        # Add endpoints from verification_points
        if verification_points.get("api_endpoint"):
            api_ep = verification_points.get("api_endpoint")
            parts = api_ep.split(" ", 1)
            method = parts[0] if parts else "GET"
            url = parts[1] if len(parts) > 1 else api_ep
            
            # Check if not already added
            existing_urls = [ep.get("url") for ep in api_verification["endpoints"]]
            if url not in existing_urls:
                api_verification["endpoints"].append({
                    "method": method,
                    "url": url,
                    "expected_fields": expected_fields if expected_fields else None
                })
        
        # Extract API requirements from test cases
        for test_case in test_cases:
            verification = test_case.get("verification", {})
            if verification.get("api"):
                api_req = verification.get("api")
                
                # Handle different verification formats
                fields_match = []
                if isinstance(api_req, str):
                    # Parse expected fields from API verification string
                    fields_match = re.findall(r"['\"](\w+)['\"]", api_req)
                elif isinstance(api_req, dict):
                    # Extract fields from dict (e.g., api_field_mapping)
                    fields_match = list(api_req.values()) if api_req else []
                elif isinstance(api_req, list):
                    # List of field names
                    fields_match = [f for f in api_req if isinstance(f, str)]
                
                if fields_match:
                    # Add to first endpoint or create a general requirement
                    if api_verification["endpoints"]:
                        existing_fields = api_verification["endpoints"][0].get("expected_fields") or []
                        for field in fields_match:
                            if field not in existing_fields:
                                existing_fields.append(field)
                        api_verification["endpoints"][0]["expected_fields"] = existing_fields
                    else:
                        api_verification["endpoints"].append({
                            "method": "GET",
                            "url": "*",  # Any endpoint
                            "expected_fields": fields_match
                        })
            
            # Also extract from api_field_mapping if present
            api_field_mapping = verification.get("api_field_mapping", {})
            if api_field_mapping and isinstance(api_field_mapping, dict):
                fields_from_mapping = list(api_field_mapping.values())
                if fields_from_mapping:
                    if api_verification["endpoints"]:
                        existing_fields = api_verification["endpoints"][0].get("expected_fields") or []
                        for field in fields_from_mapping:
                            if field not in existing_fields:
                                existing_fields.append(field)
                        api_verification["endpoints"][0]["expected_fields"] = existing_fields
                    else:
                        api_verification["endpoints"].append({
                            "method": "GET",
                            "url": "*",
                            "expected_fields": fields_from_mapping
                        })
        
        return api_verification
    
    def _build_db_verification_config(self, pr_analysis: Dict, test_cases: List[Dict], 
                                       intent: Dict, task_data: Optional[Dict] = None) -> Dict[str, Any]:
        """Build database verification config for triple-check (DB -> API -> UI).
        
        This enables verifying that:
        1. The correct value exists in the database
        2. The API returns that value
        3. The UI displays that value
        
        Args:
            pr_analysis: Parsed PR diff with db_table, db_columns
            test_cases: List of test case definitions
            intent: Extracted intent with primary_entity, changes
            task_data: Optional task data with description that may contain DB hints
            
        Returns:
            Dict with db_verification config
        """
        print("\n   🗄️  Building DB Verification Config...")
        print(f"      📋 PR Analysis Input:")
        print(f"         - db_table: {pr_analysis.get('db_table')}")
        print(f"         - db_schema: {pr_analysis.get('db_schema')}")
        print(f"         - db_columns: {pr_analysis.get('db_columns', [])}")
        
        db_table = pr_analysis.get("db_table")
        db_schema = pr_analysis.get("db_schema")
        db_columns = pr_analysis.get("db_columns", [])
        
        # If no DB info from PR, try to infer from task description and intent
        if not db_table:
            print("      ⚠️  No database table found in PR diff")
            print("      🔍 Attempting to infer DB info from task description...")
            
            # Extract from task description
            task_desc = ""
            if task_data:
                task_desc = task_data.get("description", "")
            
            # Common patterns to find table/column info in task description
            # e.g., "tcvAmount and tcvAmountUplifted on opportunity in database"
            db_patterns = [
                r'(\w+)\s+(?:and\s+\w+\s+)?(?:on|in|from)\s+(\w+)\s+(?:table\s+)?(?:in\s+)?(?:the\s+)?database',
                r'(?:in|from)\s+(?:the\s+)?(\w+)\s+(?:table|entity)',
                r'database\s+(?:table|entity)\s+(\w+)',
            ]
            
            for pattern in db_patterns:
                match = re.search(pattern, task_desc, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    # Try to identify table name (usually entity name like "opportunity", "product")
                    for g in groups:
                        if g and g.lower() in ['opportunity', 'opportunities', 'product', 'products', 
                                                'order', 'orders', 'booking', 'bookings', 'customer', 'customers']:
                            # Pluralize if needed for table name
                            db_table = g.lower() if g.lower().endswith('s') else g.lower() + 's'
                            print(f"         ✅ Inferred table from task: {db_table}")
                            break
                if db_table:
                    break
            
            # Extract column hints from api_field_mapping in test cases
            if not db_columns:
                print("      🔍 Extracting column hints from test case api_field_mapping...")
                for tc in test_cases:
                    verification = tc.get("verification", {})
                    api_mapping = verification.get("api_field_mapping", {})
                    for ui_col, api_field in api_mapping.items():
                        # Convert camelCase to snake_case for DB column
                        snake_col = re.sub(r'([A-Z])', r'_\1', api_field).lower().lstrip('_')
                        if snake_col not in db_columns:
                            db_columns.append(snake_col)
                            print(f"         ✅ Inferred column: {api_field} → {snake_col}")
        
        if not db_table:
            print("      ⚠️  Could not infer database table - DB verification disabled")
            print("         💡 Tip: Add 'on <table_name> in database' to task description to enable")
            return {"enabled": False, "reason": "No database table found in PR diff or task description"}
        
        print(f"      ✅ Found DB table: {db_table}")
        print(f"      ✅ Found DB columns: {db_columns}")
        
        # Build column to API field mapping
        # Convention: db column snake_case -> API field camelCase
        column_to_api_field = {}
        print("\n      🔄 Building column → API field mapping (snake_case → camelCase):")
        for col in db_columns:
            # Convert snake_case to camelCase
            parts = col.split('_')
            camel = parts[0] + ''.join(p.title() for p in parts[1:])
            column_to_api_field[col] = camel
            print(f"         {col} → {camel}")
        
        # Extract ID field name from test cases or use default
        id_field = "id"  # Default primary key field
        
        # Try to find ID field from api_field_mapping in test cases
        api_fields_to_verify = []
        print("\n      🔍 Extracting API fields from test cases:")
        for tc in test_cases:
            verification = tc.get("verification", {})
            api_mapping = verification.get("api_field_mapping", {})
            if api_mapping:
                print(f"         Test case api_field_mapping: {api_mapping}")
            for ui_col, api_field in api_mapping.items():
                if api_field not in api_fields_to_verify:
                    api_fields_to_verify.append(api_field)
        
        print(f"      📝 API fields to verify: {api_fields_to_verify}")
        
        # Map API fields back to DB columns for verification
        api_to_db_column = {v: k for k, v in column_to_api_field.items()}
        
        # Build verification queries - use schema if available
        verification_queries = []
        table_ref = f"{db_schema}.{db_table}" if db_schema else db_table
        print(f"\n      📊 Building verification queries (table: {table_ref}):")
        
        for api_field in api_fields_to_verify:
            db_col = api_to_db_column.get(api_field, api_field)  # Fallback to same name
            query_template = f"SELECT {db_col} FROM {table_ref} WHERE {id_field} = $1"
            verification_queries.append({
                "api_field": api_field,
                "db_column": db_col,
                "db_table": db_table,
                "db_schema": db_schema,
                "id_field": id_field,
                "query_template": query_template,
                "description": f"Verify {api_field} from API matches {db_col} in DB"
            })
            print(f"         Query: {query_template}")
            print(f"         → API field: {api_field}, DB column: {db_col}")
        
        config = {
            "enabled": True,
            "db_table": db_table,
            "db_schema": db_schema,  # Schema from @Table annotation or similar
            "db_columns": db_columns,
            "column_to_api_field": column_to_api_field,
            "id_field": id_field,
            "verification_queries": verification_queries,
            "connection_env_var": "PROJECT_DATABASE_URL"  # Environment variable for DB connection
        }
        
        print(f"\n      ✅ DB Verification Config built successfully")
        print(f"         Enabled: {config['enabled']}")
        print(f"         Table: {config['db_table']}")
        print(f"         Queries: {len(verification_queries)}")
        
        return config
    
    def synthesize_mission(self, task_data: Dict, intent: Dict, target_node: Dict, 
                          pr_analysis: Dict, test_scope: Optional[Dict[str, bool]] = None,
                          pr_files: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Synthesize all information into Mission JSON.
        
        Args:
            task_data: Task description and metadata
            intent: Extracted intent from task
            target_node: Target semantic graph node
            pr_analysis: PR diff analysis
            test_scope: Test scope configuration
            pr_files: Optional PR files for extracting UI elements for JIT context
        
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
        
        # Validate target_url - detect if it's an API URL instead of a UI URL
        # API URLs typically have patterns like /api/, /graphql, /v1/, etc.
        api_url_patterns = ['/api/', '/graphql', '/v1/', '/v2/', '/rest/']
        target_url_is_api = any(pattern in target_url for pattern in api_url_patterns)
        
        if target_url_is_api:
            print(f"   ⚠️ Warning: target_url appears to be an API endpoint: {target_url}")
            print(f"   ⚠️ This may be a data issue in the semantic graph - node URLs should be UI paths, not API endpoints")
            # Try to extract base URL and use the dashboard/home as starting point
            # For now, use the base_url as the starting navigation point
            # The actual navigation should happen via gateway plan or click steps
            from urllib.parse import urlparse
            parsed = urlparse(target_url)
            corrected_base = f"{parsed.scheme}://{parsed.netloc}"
            print(f"   🔧 Using corrected base URL for navigation: {corrected_base}")
            # Keep target_url for reference but use base for navigation_steps
            navigation_url = corrected_base
        else:
            navigation_url = target_url
        
        # If it's a template URL, we can still use it - executor will resolve it
        navigation_steps = [navigation_url]
        
        # Build deterministic navigation path using semantic graph edges
        navigation_path = self._build_navigation_path(target_node) if target_node else []
        
        # If navigation path is empty or first step is an API URL, fix it
        if navigation_path:
            first_step = navigation_path[0] if navigation_path else {}
            if first_step.get("action") == "goto":
                first_url = first_step.get("url", "")
                if any(pattern in first_url for pattern in api_url_patterns):
                    print(f"   ⚠️ Navigation path starts with API URL, correcting to base URL")
                    navigation_path[0]["url"] = navigation_url
        
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
        
        # Build verification_points first (needed for api_verification)
        verification_points = {
            # Only include API endpoint if it was actually found and test_scope allows API testing
            "api_endpoint": api_endpoint if (api_endpoint and test_scope.get("test_api", True)) else None,
            # Only include DB table if it was actually found and test_scope allows DB testing
            "db_table": pr_analysis.get("db_table") if (pr_analysis.get("db_table") and test_scope.get("test_db", True)) else None,
            "expected_values": expected_values
        }
        
        # Build API verification configuration
        api_verification = self._build_api_verification(
            target_node, test_cases, pr_analysis, verification_points
        )
        
        # NOTE: deterministic_steps will be generated AFTER persona_tests 
        # to ensure we use test cases WITH persona info (for login skip logic)
        deterministic_steps = []
        
        # Extract personas from intent (LLM extracted from task description)
        personas = intent.get("personas", ["default"])
        if not personas or personas == ["default"]:
            # Fallback: try to detect personas from test cases
            detected_personas = set()
            for tc in test_cases:
                tc_text = (tc.get("id", "") + tc.get("purpose", "")).lower()
                if "reseller" in tc_text:
                    detected_personas.add("Reseller")
                if "distributor" in tc_text:
                    detected_personas.add("Distributor")
                if "admin" in tc_text:
                    detected_personas.add("Admin")
            
            if detected_personas:
                personas = list(detected_personas)
                print(f"   🔍 Detected personas from test cases: {personas}")
            else:
                # Use Reseller as default if available
                personas = ["Reseller"]
                print(f"   ℹ️ No personas detected, using default: {personas}")
        
        print(f"   👥 Building tests for personas: {personas}")
        
        # Check available gateway plans before building persona configs
        print("\n   🚪 Checking available gateway plans...")
        available_gateways = self.list_available_gateway_plans()
        if available_gateways:
            print(f"   📋 Found gateway plans for: {', '.join(available_gateways.keys())}")
            for persona_name, path in available_gateways.items():
                print(f"      - {persona_name}: {path.name}")
        else:
            print("   ⚠️ No gateway plans found!")
        
        # Filter personas to only those with valid gateway plans
        valid_personas = []
        for persona in personas:
            if persona in available_gateways or persona.lower() in [p.lower() for p in available_gateways]:
                valid_personas.append(persona)
            else:
                print(f"   ⚠️ Skipping persona '{persona}' - no gateway plan available")
        
        if not valid_personas and personas:
            print(f"   ⚠️ No valid personas with gateway plans. Using all personas: {personas}")
            valid_personas = personas
        
        # Build persona-specific test configurations
        persona_tests = []
        for persona in valid_personas:
            persona_config = self._build_persona_test_config(
                persona=persona,
                test_cases=test_cases,
                navigation_path=navigation_path,
                target_node=target_node if target_node else {},
                intent=intent
            )
            # Only add if gateway plan was loaded successfully
            if persona_config.get("gateway_plan"):
                persona_tests.append(persona_config)
            else:
                print(f"   ⚠️ Skipping persona '{persona}' - gateway plan failed to load")
        
        # Generate deterministic_steps from persona test cases (with persona info)
        # This ensures login steps are properly skipped since gateway handles them
        for persona_config in persona_tests:
            for test_case in persona_config.get("test_cases", []):
                test_case_id = test_case.get("id") or test_case.get("name", "").lower().replace(" ", "_")
                steps = self._convert_test_case_to_steps(test_case, target_node, navigation_path)
                
                deterministic_steps.append({
                    "test_case_id": test_case_id,
                    "name": test_case.get("name", ""),
                    "steps": steps
                })
        
        # Determine execution mode based on whether we have deterministic steps
        has_reliable_steps = len(deterministic_steps) > 0 and all(
            not any(s.get("requires_browser_use") for s in tc.get("steps", []))
            for tc in deterministic_steps
        )
        execution_mode = "deterministic" if has_reliable_steps else "hybrid"
        
        # Use only personas that have valid gateway plans in the final mission
        final_personas = [pt["persona"] for pt in persona_tests]
        if not final_personas:
            print("   ⚠️ No personas with valid gateway plans - test may require manual login")
            final_personas = personas  # Fall back to original personas
        
        # Extract UI elements from PR for JIT selector resolution context
        pr_ui_changes = []
        if pr_files:
            pr_ui_changes = self._extract_ui_elements_from_pr(pr_files)
        
        # Build DB verification config for triple-check (DB -> API -> UI)
        db_verification = self._build_db_verification_config(pr_analysis, test_cases, intent, task_data)
        
        mission = {
            "ticket_id": self._extract_ticket_id(task_data.get("description", "")),
            "target_node": target_node.get("id") or target_node.get("semantic_name") if target_node else "unknown",
            "target_url": target_node.get("url") if target_node else "",
            "execution_mode": execution_mode,  # deterministic, hybrid, or agentic
            "personas": final_personas,  # Only personas with valid gateway plans
            "persona_tests": persona_tests,  # Per-persona test configurations with gateway plans
            "navigation_path": navigation_path,  # structured navigation from entrypoint
            "navigation_steps": navigation_steps,  # Legacy: simple URL list for backward compat
            "deterministic_steps": deterministic_steps,  # structured test steps with selectors
            "test_cases": test_cases,  # Legacy: for browser-use fallback
            "api_verification": api_verification,  # inline API verification config
            "verification_points": verification_points,
            "intent": {
                "primary_entity": intent.get("primary_entity"),
                "changes": intent.get("changes"),
                "test_focus": intent.get("test_focus"),
                "personas": final_personas  # Only valid personas in intent
            },
            "pr_link": task_data.get("pr_link"),
            "test_scope": test_scope,  # Agentic decision on what to test
            "pr_ui_changes": pr_ui_changes,  # UI elements from PR for JIT context
            "db_verification": db_verification  # DB verification config for triple-check
        }
        
        return mission
    
    
    def _load_gateway_plan(self, persona: str) -> Optional[Dict[str, Any]]:
        """Load and validate the gateway plan for a specific persona.
        
        Gateway plans contain the steps to login/authenticate as a persona.
        
        Args:
            persona: Persona name (e.g., "Reseller", "Distributor")
            
        Returns:
            Gateway plan dict or None if not found/invalid
        """
        # Try to find gateway plan file
        # Check temp folder first (project-specific), then root mapper folder
        possible_paths = [
            Path(__file__).parent / "temp" / f"gateway_plan_{persona}.json",
            Path(__file__).parent / "temp" / f"gateway_plan_{persona.lower()}.json",
            Path(__file__).parent / f"gateway_plan_{persona}.json",
            Path(__file__).parent / f"gateway_plan_{persona.lower()}.json",
            # Also check for gateway_<persona>.json naming convention
            Path(__file__).parent / "temp" / f"gateway_{persona}.json",
            Path(__file__).parent / "temp" / f"gateway_{persona.lower()}.json",
        ]
        
        for path in possible_paths:
            if path.exists():
                try:
                    with open(path, 'r') as f:
                        gateway_plan = json.load(f)
                    
                    # Validate the gateway plan has required fields
                    if not self._validate_gateway_plan(gateway_plan, persona, path):
                        continue
                    
                    print(f"   ✅ Loaded gateway plan for {persona}: {path.name}")
                    print(f"      Goal: {gateway_plan.get('goal', 'N/A')}")
                    print(f"      Steps: {len(gateway_plan.get('steps', []))}")
                    return gateway_plan
                except json.JSONDecodeError as e:
                    print(f"   ⚠️ Invalid JSON in gateway plan {path}: {e}")
                except Exception as e:
                    print(f"   ⚠️ Error loading gateway plan {path}: {e}")
        
        print(f"   ⚠️ No gateway plan found for persona: {persona}")
        print(f"      Searched paths:")
        for path in possible_paths:
            print(f"        - {path}")
        return None
    
    def _validate_gateway_plan(self, gateway_plan: Dict, persona: str, path: Path) -> bool:
        """Validate a gateway plan has required structure.
        
        Args:
            gateway_plan: Gateway plan dict to validate
            persona: Expected persona name
            path: Path to the file (for error messages)
            
        Returns:
            True if valid, False otherwise
        """
        errors = []
        
        # Check required fields
        if not gateway_plan.get("steps"):
            errors.append("Missing 'steps' array")
        elif not isinstance(gateway_plan["steps"], list):
            errors.append("'steps' must be an array")
        elif len(gateway_plan["steps"]) == 0:
            errors.append("'steps' array is empty")
        
        if not gateway_plan.get("goal"):
            errors.append("Missing 'goal' field")
        
        # Validate each step has required fields
        steps = gateway_plan.get("steps", [])
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"Step {i+1} is not a dict")
                continue
            
            action = step.get("action")
            if not action:
                errors.append(f"Step {i+1} missing 'action'")
            elif action in ["click", "fill", "wait_visible"]:
                if not step.get("selector"):
                    errors.append(f"Step {i+1} ({action}) missing 'selector'")
            elif action == "fill":
                if not step.get("value"):
                    errors.append(f"Step {i+1} (fill) missing 'value'")
        
        if errors:
            print(f"   ⚠️ Gateway plan validation failed for {persona} ({path.name}):")
            for error in errors:
                print(f"      - {error}")
            return False
        
        return True
    
    def list_available_gateway_plans(self) -> Dict[str, Path]:
        """List all available gateway plans in the temp and root folders.
        
        Returns:
            Dict mapping persona names to their gateway plan paths
        """
        available = {}
        
        search_paths = [
            Path(__file__).parent / "temp",
            Path(__file__).parent,
        ]
        
        for search_path in search_paths:
            if not search_path.exists():
                continue
            
            # Look for gateway_plan_*.json and gateway_*.json files
            for pattern in ["gateway_plan_*.json", "gateway_*.json"]:
                for path in search_path.glob(pattern):
                    # Extract persona name from filename
                    name = path.stem
                    if name.startswith("gateway_plan_"):
                        persona = name.replace("gateway_plan_", "")
                    elif name.startswith("gateway_"):
                        persona = name.replace("gateway_", "")
                    else:
                        continue
                    
                    # Normalize persona name (capitalize first letter)
                    persona = persona.capitalize()
                    
                    if persona not in available:
                        available[persona] = path
        
        return available
    
    def _build_persona_test_config(self, persona: str, test_cases: List[Dict], 
                                    navigation_path: List[Dict], target_node: Dict,
                                    intent: Dict) -> Dict[str, Any]:
        """Build test configuration for a specific persona.
        
        Includes gateway plan, navigation path, and persona-specific test cases.
        
        Args:
            persona: Persona name
            test_cases: Test cases to filter/adapt for this persona
            navigation_path: Navigation path to target
            target_node: Target node
            intent: Intent dict with test focus
            
        Returns:
            Persona test configuration
        """
        # Load gateway plan for this persona
        gateway_plan = self._load_gateway_plan(persona)
        
        # Normalize persona name for comparison
        persona_lower = persona.lower()
        
        # Filter/adapt test cases for this persona
        persona_test_cases = []
        for tc in test_cases:
            # Check if test case is relevant to this persona
            tc_id = tc.get("id", "").lower()
            tc_purpose = tc.get("purpose", "").lower()
            
            # Include if:
            # 1. Test case mentions this persona
            # 2. Test case has no persona-specific filtering (applies to all)
            mentions_persona = persona_lower in tc_id or persona_lower in tc_purpose
            mentions_other_persona = any(
                other in tc_id or other in tc_purpose 
                for other in ["reseller", "distributor", "admin", "user"] 
                if other != persona_lower
            )
            
            if mentions_persona or not mentions_other_persona:
                # Clone the test case and add persona context
                persona_tc = tc.copy()
                persona_tc["persona"] = persona
                persona_test_cases.append(persona_tc)
        
        # Build expected results based on intent for this persona
        expected_results = {}
        test_focus = intent.get("test_focus", "")
        
        # Parse test focus for persona-specific expectations
        # e.g., "resellers see tcvAmountUplifted, distributors see tcvAmount"
        if persona_lower in test_focus.lower():
            # Extract what this persona should see
            expected_results["description"] = f"Expected behavior for {persona}"
        
        config = {
            "persona": persona,
            "gateway_plan": gateway_plan,
            "navigation_path": navigation_path,
            "test_cases": persona_test_cases,
            "expected_results": expected_results
        }
        
        return config
    
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
            if task_file_stem.upper().startswith("TASK-"):
                # Extract TASK-X from filename (e.g., TASK-1_task -> TASK-1, Task-3 -> TASK-3)
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
    
    # Fetch PR files early for re-ranking (if PR link available)
    pr_files = []
    pr_link = task_data.get("pr_link", "")
    if pr_link:
        try:
            # Parse PR URL to get owner/repo/pr_number
            pr_match = re.search(r'https?://([^/]+)/([^/]+)/([^/]+)/pull/(\d+)', pr_link)
            if pr_match:
                github_domain = pr_match.group(1)
                owner = pr_match.group(2)
                repo = pr_match.group(3)
                pr_number = pr_match.group(4)
                
                print(f"   📥 Fetching PR #{pr_number} files for re-ranking...")
                pr_data = processor._fetch_pr_diff(owner, repo, pr_number, github_domain=github_domain)
                if pr_data:
                    pr_files = pr_data.get("files", [])
                    # Filter to UI files only for re-ranking
                    ui_files = processor._filter_ui_files(pr_files)
                    print(f"   ✅ Found {len(pr_files)} total files, {len(ui_files)} UI files for re-ranking")
        except Exception as e:
            print(f"   ⚠️  Failed to fetch PR files for re-ranking: {e}")
    
    # Extract semantic graph context with PR-based re-ranking
    semantic_context = processor._extract_semantic_graph_context(
        task_data.get("description", ""),
        pr_files=pr_files
    )
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
        
        # Fallback: infer from changes (only if explicitly mentioned in change text)
        if not api_endpoint and intent.get("changes"):
            for change in intent["changes"]:
                change_lower = change.lower()
                if "post" in change_lower or "create" in change_lower:
                    # Extract API endpoint from change description
                    # e.g., "updated POST /products" -> "POST /products"
                    api_match = re.search(r'(POST|PUT|PATCH)\s+/(\w+)', change, re.IGNORECASE)
                    if api_match:
                        api_endpoint = f"{api_match.group(1)} /{api_match.group(2)}"
                        break
                    # Don't hallucinate - only use if explicitly found in change text
        
        if api_endpoint:
            print(f"   🔍 Using API endpoint: {api_endpoint}")
        else:
            print(f"   🔍 No API endpoint found in PR diff, will search semantic graph by entity only")
        
        # Pass PR files for LLM-based re-ranking
        target_node = processor.find_target_node(
            intent["primary_entity"], 
            api_endpoint,
            task_description=task_data.get("description", ""),
            pr_files=pr_files  # Use pr_files fetched earlier for re-ranking
        )
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
            task_data, intent, target_node, pr_analysis, test_scope=test_scope,
            pr_files=pr_files
        )
        
        # Save mission JSON (output_path already set in Step 1)
        with open(output_path, 'w') as f:
            json.dump(mission, f, indent=2)
        
        print(f"   ✅ Mission saved to: {output_path}")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
