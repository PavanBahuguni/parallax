"""Agentic PR Context Gathering using LangGraph.

This module implements a LangGraph workflow for intelligently gathering
PR context beyond just diffs. It uses LLM reasoning to decide what
additional context is needed and fetches it via MCP tools.
"""
from typing import TypedDict, List, Dict, Any, Optional, Literal
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage
import json
import re

from github_mcp_client import GitHubMCPClient


class PRContextState(TypedDict):
    """State for PR context gathering workflow."""
    pr_link: str
    pr_diff: Dict[str, Any]  # Files and patches from PR diff
    task_description: Optional[str]
    pr_summary: Dict[str, Any]  # Initial summary from diff analysis
    context_gaps: Dict[str, Any]  # LLM-identified gaps
    fetched_context: Dict[str, Any]  # Accumulated context from MCP tools
    enriched_context: Dict[str, Any]  # Final merged context
    test_scope: Dict[str, bool]  # What needs testing: db, api, ui


class AgenticPRContextGatherer:
    """Agentic PR context gatherer using LangGraph."""
    
    def __init__(self, llm, github_mcp_client: Optional[GitHubMCPClient] = None):
        """Initialize agentic PR context gatherer.
        
        Args:
            llm: LLM instance for reasoning
            github_mcp_client: GitHub MCP client (optional, will create if not provided)
        """
        self.llm = llm
        self.github_mcp_client = github_mcp_client or GitHubMCPClient()
        self.workflow = self._build_workflow()
    
    def _build_workflow(self) -> StateGraph:
        """Build LangGraph workflow for PR context gathering."""
        workflow = StateGraph(PRContextState)
        
        # Add nodes
        workflow.add_node("analyze_pr_diff", self._analyze_pr_diff)
        workflow.add_node("identify_context_gaps", self._identify_context_gaps)
        workflow.add_node("fetch_pr_description", self._fetch_pr_description)
        workflow.add_node("fetch_full_files", self._fetch_full_files)
        workflow.add_node("merge_context", self._merge_context)
        workflow.add_node("decide_test_scope", self._decide_test_scope)
        
        # Set entry point
        workflow.set_entry_point("analyze_pr_diff")
        
        # Add edges
        workflow.add_edge("analyze_pr_diff", "identify_context_gaps")
        workflow.add_conditional_edges(
            "identify_context_gaps",
            self._route_to_tools,
            {
                "fetch_pr_description": "fetch_pr_description",
                "fetch_full_files": "fetch_full_files",
                "merge_context": "merge_context"
            }
        )
        workflow.add_edge("fetch_pr_description", "merge_context")
        workflow.add_edge("fetch_full_files", "merge_context")
        workflow.add_edge("merge_context", "decide_test_scope")
        workflow.add_edge("decide_test_scope", END)
        
        return workflow.compile()
    
    def _analyze_pr_diff(self, state: PRContextState) -> PRContextState:
        """Analyze PR diff to extract initial summary.
        
        This is similar to existing _extract_pr_summary_with_llm but returns
        structured summary for further processing.
        """
        files = state.get("pr_diff", {}).get("files", [])
        task_description = state.get("task_description")
        
        # Build context from PR diff patches (limit to avoid token bloat)
        patches = []
        for file_info in files[:15]:  # Limit to 15 files
            patch = file_info.get("patch", "")
            filename = file_info.get("filename", "")
            if patch:
                # Truncate each patch to first 800 chars
                patch_preview = patch[:800]
                patches.append(f"File: {filename}\n{patch_preview}")
        
        combined_diff = "\n\n---\n\n".join(patches)
        
        # Build prompt
        task_context = ""
        if task_description:
            task_preview = task_description[:500] if len(task_description) > 500 else task_description
            task_context = f"""

Task Context:
{task_preview}

Use this task context to focus on relevant changes.
"""
        
        prompt = f"""Analyze this PR diff and extract WHAT changed. Ignore file paths/names - focus on actual changes.
{task_context}
PR Diff:
{combined_diff}

Extract semantic changes:
1. Database changes: tables and columns added/modified
2. API changes: endpoints added/modified (format: METHOD /path)
3. UI changes: components/fields added/modified, routes/pages added/modified, buttons added/modified, form elements added/modified etc.

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
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                result = json.loads(json_match.group())
                return {
                    **state,
                    "pr_summary": {
                        "db_changes": result.get("db_changes", {"tables": [], "columns": []}),
                        "api_changes": result.get("api_changes", []),
                        "ui_changes": result.get("ui_changes", []),
                        "files_changed": len(files)
                    }
                }
        except Exception as e:
            print(f"   ⚠️  PR diff analysis failed: {e}")
        
        # Fallback
        return {
            **state,
            "pr_summary": {
                "db_changes": {"tables": [], "columns": []},
                "api_changes": [],
                "ui_changes": [],
                "files_changed": len(files)
            }
        }
    
    def _identify_context_gaps(self, state: PRContextState) -> PRContextState:
        """Use LLM to identify what additional context is needed."""
        pr_summary = state.get("pr_summary", {})
        pr_diff = state.get("pr_diff", {})
        task_description = state.get("task_description", "")
        
        # Build prompt
        prompt = f"""Analyze this PR diff summary and identify what additional context is needed to fully understand the changes.

PR Summary:
- DB Changes: {pr_summary.get('db_changes', {})}
- API Changes: {pr_summary.get('api_changes', [])}
- UI Changes: {pr_summary.get('ui_changes', [])}
- Files Changed: {pr_summary.get('files_changed', 0)}

Task Description: {task_description[:200] if task_description else 'N/A'}

What context is missing? Consider:
1. Do we need the PR description/comments for more context?
2. Do we need full file contents (not just diffs) to understand model structures, API routes, etc.?
3. Are there related files (imports, dependencies) that might be affected?

Respond with JSON:
{{
  "needs_pr_description": true/false,
  "needs_full_files": ["models.py", "main.py"] or [],
  "needs_commit_messages": true/false,
  "reasoning": "why these are needed"
}}

Examples:
- If DB changes detected but only see diff → need full models.py
- If API changes detected but only see diff → need full main.py/routes file
- If UI changes detected → might need PR description for context
- If unclear what changed → need PR description
"""
        
        try:
            response = self.llm.invoke(prompt)
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                gaps = json.loads(json_match.group())
                return {
                    **state,
                    "context_gaps": gaps
                }
        except Exception as e:
            print(f"   ⚠️  Context gap identification failed: {e}")
        
        # Default: fetch PR description only
        return {
            **state,
            "context_gaps": {
                "needs_pr_description": True,
                "needs_full_files": [],
                "needs_commit_messages": False,
                "reasoning": "Default: fetch PR description for context"
            }
        }
    
    def _route_to_tools(self, state: PRContextState) -> str:
        """Route to appropriate tools based on context gaps."""
        gaps = state.get("context_gaps", {})
        
        # Check what's needed
        needs_description = gaps.get("needs_pr_description", False)
        needs_full_files = gaps.get("needs_full_files", [])
        
        # Route to tools
        if needs_full_files:
            return "fetch_full_files"
        elif needs_description:
            return "fetch_pr_description"
        else:
            return "merge_context"
    
    def _fetch_pr_description(self, state: PRContextState) -> PRContextState:
        """Fetch PR description via MCP tool."""
        pr_link = state.get("pr_link", "")
        if not pr_link:
            return state
        
        print("   📥 Fetching PR description via MCP...")
        description_data = self.github_mcp_client.fetch_pr_description(pr_link)
        
        if "error" not in description_data:
            print("   ✅ PR description fetched")
        
        return {
            **state,
            "fetched_context": {
                **state.get("fetched_context", {}),
                "pr_description": description_data
            }
        }
    
    def _fetch_full_files(self, state: PRContextState) -> PRContextState:
        """Fetch full file contents via MCP tool."""
        pr_link = state.get("pr_link", "")
        gaps = state.get("context_gaps", {})
        files_to_fetch = gaps.get("needs_full_files", [])
        
        if not files_to_fetch or not pr_link:
            return state
        
        print(f"   📥 Fetching {len(files_to_fetch)} full file(s) via MCP...")
        full_files = {}
        
        for filename in files_to_fetch:
            print(f"      📄 Fetching {filename}...")
            file_data = self.github_mcp_client.fetch_file_contents(pr_link, filename)
            if "error" not in file_data:
                full_files[filename] = file_data.get("content", "")
                print(f"      ✅ {filename} fetched ({len(file_data.get('content', ''))} chars)")
            else:
                print(f"      ⚠️  Failed to fetch {filename}: {file_data.get('error')}")
        
        return {
            **state,
            "fetched_context": {
                **state.get("fetched_context", {}),
                "full_files": full_files
            }
        }
    
    def _merge_context(self, state: PRContextState) -> PRContextState:
        """Merge all context into enriched context."""
        pr_summary = state.get("pr_summary", {})
        fetched_context = state.get("fetched_context", {})
        
        enriched = {
            **pr_summary,
            "pr_description": fetched_context.get("pr_description", {}),
            "full_files": fetched_context.get("full_files", {}),
            "commit_messages": fetched_context.get("commit_messages", [])
        }
        
        print("   ✅ Context merged")
        
        return {
            **state,
            "enriched_context": enriched
        }
    
    def _decide_test_scope(self, state: PRContextState) -> PRContextState:
        """Decide what needs to be tested: DB, API, UI, or combinations.
        
        This is the key agentic decision: based on PR changes, determine
        which layers need verification.
        """
        enriched_context = state.get("enriched_context", {})
        pr_summary = state.get("pr_summary", {})
        task_description = state.get("task_description", "")
        
        db_changes = pr_summary.get("db_changes", {})
        api_changes = pr_summary.get("api_changes", [])
        ui_changes = pr_summary.get("ui_changes", [])
        
        prompt = f"""Analyze these PR changes and determine what needs to be tested.

PR Changes:
- DB Changes: Tables: {db_changes.get('tables', [])}, Columns: {db_changes.get('columns', [])}
- API Changes: {api_changes}
- UI Changes: {ui_changes}

Task Description: {task_description[:200] if task_description else 'N/A'}

What needs to be tested? Respond with JSON:
{{
  "test_db": true/false,
  "test_api": true/false,
  "test_ui": true/false,
  "reasoning": "why these layers need testing"
}}

Examples:
- CSS-only change → {{"test_db": false, "test_api": false, "test_ui": true}}
- New DB column → {{"test_db": true, "test_api": true, "test_ui": true}}
- API endpoint change → {{"test_db": false, "test_api": true, "test_ui": true}}
- Frontend component change → {{"test_db": false, "test_api": false, "test_ui": true}}
- Bug fix in existing feature → {{"test_db": true, "test_api": true, "test_ui": true}}
"""
        
        try:
            response = self.llm.invoke(prompt)
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                scope = json.loads(json_match.group())
                print(f"   ✅ Test scope decided: DB={scope.get('test_db')}, API={scope.get('test_api')}, UI={scope.get('test_ui')}")
                return {
                    **state,
                    "test_scope": {
                        "test_db": scope.get("test_db", True),
                        "test_api": scope.get("test_api", True),
                        "test_ui": scope.get("test_ui", True),
                        "reasoning": scope.get("reasoning", "")
                    }
                }
        except Exception as e:
            print(f"   ⚠️  Test scope decision failed: {e}")
        
        # Default: test everything
        return {
            **state,
            "test_scope": {
                "test_db": True,
                "test_api": True,
                "test_ui": True,
                "reasoning": "Default: test all layers"
            }
        }
    
    def gather_context(self, pr_link: str, pr_diff: Dict[str, Any], 
                      task_description: Optional[str] = None) -> Dict[str, Any]:
        """Gather PR context using agentic workflow.
        
        Args:
            pr_link: GitHub PR URL
            pr_diff: PR diff data (from _fetch_pr_diff)
            task_description: Optional task description
            
        Returns:
            Dict with enriched_context and test_scope
        """
        initial_state: PRContextState = {
            "pr_link": pr_link,
            "pr_diff": pr_diff,
            "task_description": task_description,
            "pr_summary": {},
            "context_gaps": {},
            "fetched_context": {},
            "enriched_context": {},
            "test_scope": {}
        }
        
        # Run workflow
        final_state = self.workflow.invoke(initial_state)
        
        return {
            "enriched_context": final_state.get("enriched_context", {}),
            "test_scope": final_state.get("test_scope", {})
        }
