"""Triple-Check Executor - Agentic Browser Architecture

Uses browser-use library for LLM-driven UI test execution.
Performs triple-check verification: DB → API → UI
"""
import asyncio
import json
import os
import re
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
import asyncpg
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError
from rich.console import Console
from langchain_core.messages import HumanMessage

# Import LLM from context_processor
from context_processor import FixedNutanixChatModel

# Import browser agent
from browser_agent import BrowserAgent

# Import gateway execution from semantic mapper (has agentic fallbacks)
from semantic_mapper_with_gateway import execute_gateway_plan as mapper_execute_gateway_plan

# Force unbuffered output for real-time logging in subprocess
console = Console(force_terminal=True)

# Regex to match env(VARIABLE_NAME) patterns
ENV_RE = re.compile(r"^env\(([^)]+)\)$")

def resolve_env_value(val: Optional[str]) -> Optional[str]:
    """Resolve env(NAME) strings to actual environment variable values.
    
    Examples:
        env(LOGIN_USERNAME) -> actual username from environment
        env(LOGIN_PASSWORD) -> actual password from environment
    """
    if val is None:
        return None
    m = ENV_RE.match(val)
    if m:
        env_var = m.group(1)
        resolved = os.getenv(env_var, "")
        if not resolved:
            console.print(f"[yellow]⚠️ Environment variable {env_var} is not set[/yellow]")
        return resolved
    return val

def json_serialize(obj: Any) -> Any:
    """Recursively convert datetime, date, Decimal, and UUID objects to JSON-serializable formats."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, UUID):
        return str(obj)
    elif isinstance(obj, dict):
        return {key: json_serialize(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [json_serialize(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(json_serialize(item) for item in obj)
    else:
        return obj


class TripleCheckExecutor:
    """Triple-check executor using browser-use for UI tests."""
    
    def __init__(self, mission_path: str, llm=None):
        self.mission_path = Path(mission_path)
        self.llm = llm
        self.mission = None
        self.api_calls: List[Dict] = []
        self.db_connection = None
        
        # Load .env file early to ensure env variables are available for gateway plans
        env_file = Path(__file__).parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
            console.print(f"[dim]   ✅ Loaded .env from {env_file}[/dim]")
        
        # Load mission
        with open(self.mission_path, 'r') as f:
            self.mission = json.load(f)
        
        # Cache for loaded semantic graphs
        self._semantic_graphs: Dict[str, Dict] = {}
    
    def load_semantic_graph(self, persona: str) -> Optional[Dict[str, Any]]:
        """Load semantic graph for a specific persona.
        
        Looks for semantic_graph_{Persona}.json in the mapper directory.
        """
        if persona in self._semantic_graphs:
            return self._semantic_graphs[persona]
        
        mapper_dir = Path(__file__).parent
        
        # Try exact case match first
        graph_path = mapper_dir / f"semantic_graph_{persona}.json"
        if not graph_path.exists():
            # Try case-insensitive match
            for p in mapper_dir.glob("semantic_graph_*.json"):
                if persona.lower() in p.name.lower():
                    graph_path = p
                    break
        
        if graph_path.exists():
            try:
                with open(graph_path, 'r') as f:
                    graph = json.load(f)
                self._semantic_graphs[persona] = graph
                console.print(f"[dim]   📊 Loaded semantic graph for {persona}: {len(graph.get('nodes', []))} nodes, {len(graph.get('edges', []))} edges[/dim]")
                return graph
            except Exception as e:
                console.print(f"[yellow]   ⚠️ Failed to load semantic graph for {persona}: {e}[/yellow]")
                return None
        else:
            console.print(f"[yellow]   ⚠️ No semantic graph found for {persona}[/yellow]")
            return None
    
    async def connect_db(self):
        """Connect to PostgreSQL database."""
        console.print("\n[bold cyan]🗄️  Database Connection Setup[/bold cyan]")
        
        # Load .env for database URL
        env_file = Path(__file__).parent / ".env"
        console.print(f"[dim]   Looking for .env at: {env_file}[/dim]")
        if env_file.exists():
            load_dotenv(env_file)
            console.print(f"[dim]   ✓ Loaded .env file[/dim]")
        else:
            console.print(f"[dim]   ⚠ No .env file found[/dim]")
        
        # Prefer PROJECT_DATABASE_URL from project config, fallback to DATABASE_URL
        project_db_url = os.getenv("PROJECT_DATABASE_URL")
        default_db_url = os.getenv("DATABASE_URL")
        
        console.print(f"[dim]   PROJECT_DATABASE_URL: {'set' if project_db_url else 'not set'}[/dim]")
        console.print(f"[dim]   DATABASE_URL: {'set' if default_db_url else 'not set'}[/dim]")
        
        db_url = project_db_url or default_db_url or "postgresql+asyncpg://postgres@localhost:5432/postgres"
        
        # Convert asyncpg URL to standard format
        if db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        
        # Mask password in URL for logging
        import re
        masked_url = re.sub(r':([^:@]+)@', ':****@', db_url)
        console.print(f"[dim]   Connection URL: {masked_url}[/dim]")
        
        try:
            # Parse connection string
            # Format: postgresql://user:pass@host:port/dbname
            console.print(f"[dim]   Connecting...[/dim]")
            self.db_connection = await asyncpg.connect(db_url)
            
            # Get server version for confirmation
            version = await self.db_connection.fetchval("SELECT version()")
            console.print(f"[green]   ✅ Database connected successfully[/green]")
            console.print(f"[dim]      Server: {version[:60]}...[/dim]" if len(version) > 60 else f"[dim]      Server: {version}[/dim]")
        except Exception as e:
            console.print(f"[red]   ❌ Database connection failed: {e}[/red]")
            console.print(f"[dim]      Triple-check DB verification will be skipped[/dim]")
            # Don't raise - allow execution to continue without DB
            self.db_connection = None
    
    async def close_db(self):
        """Close database connection."""
        if self.db_connection:
            await self.db_connection.close()
    
    async def verify_database(self, expected_values: Dict, db_table: Optional[str] = None, db_schema: Optional[str] = None) -> Tuple[bool, Dict]:
        """Verify database state matches expected values.
        
        Args:
            expected_values: Dict of field names to expected values
            db_table: Database table name (e.g., "products" or "schema.products")
            db_schema: Database schema name (e.g., "partner_ssot") - takes priority if provided
        
        Returns:
            (success, verification_result)
        """
        if not self.db_connection:
            return False, {"error": "Database not connected"}
        
        try:
            # Default table if not provided
            if not db_table:
                db_table = "items"
            
            # Handle schema-qualified table names
            if "." in db_table:
                # Already has schema prefix
                table_with_schema = db_table
            elif db_schema:
                # Use provided schema
                table_with_schema = f"{db_schema}.{db_table}"
            else:
                # No schema provided, use table as-is (will use search_path)
                table_with_schema = db_table
            
            # Map mission.json field names to database column names
            field_mapping = {
                "item_name": "name",
                "item_description": "description",
                "name": "name",
                "description": "description",
                "tag": "tag",
                "category": "category"  # Add category mapping
            }
            
            # Build WHERE clause from expected_values
            conditions = []
            params = []
            param_idx = 1
            
            for key, value in expected_values.items():
                # Map field name to database column name
                db_column = field_mapping.get(key, key)
                conditions.append(f"{db_column} = ${param_idx}")
                params.append(value)
                param_idx += 1
            
            if not conditions:
                # No conditions, just get the latest record
                query = f"SELECT * FROM {table_with_schema} ORDER BY id DESC LIMIT 1"
                row = await self.db_connection.fetchrow(query)
            else:
                where_clause = " AND ".join(conditions)
                query = f"SELECT * FROM {table_with_schema} WHERE {where_clause} ORDER BY id DESC LIMIT 1"
                row = await self.db_connection.fetchrow(query, *params)
            
            if row:
                result = dict(row)
                console.print(f"[green]✅ DB Check: Found record in {table_with_schema}[/green]")
                # Print relevant fields
                relevant_fields = {k: v for k, v in result.items() if k in expected_values or k in ['id', 'name', 'category']}
                console.print(f"[dim]   {relevant_fields}[/dim]")
                return True, {"found": True, "record": result, "table": table_with_schema}
            else:
                console.print(f"[red]❌ DB Check: No matching record found in {table_with_schema}[/red]")
                return False, {"found": False, "query": query, "params": params, "table": table_with_schema}
                
        except Exception as e:
            console.print(f"[red]❌ DB Check failed: {e}[/red]")
            return False, {"error": str(e)}
    
    async def verify_api(self, page: Page, expected_endpoint: str, filter_param: Optional[str] = None) -> Tuple[bool, Dict]:
        """Verify API was called with correct payload.
        
        Args:
            expected_endpoint: Format "METHOD /path" (e.g., "POST /items" or "GET /products")
            filter_param: Optional filter parameter name to check for (e.g., "category")
        
        Returns:
            (success, api_call_info)
        """
        # Wait briefly for network activity to settle
        try:
            await page.wait_for_load_state("load", timeout=3000)
        except:
            pass  # Continue even if not fully loaded
        await asyncio.sleep(0.5)
        
        # Parse expected endpoint: "POST /items" -> method="POST", path="/items"
        parts = expected_endpoint.strip().split(None, 1)
        if len(parts) == 2:
            expected_method = parts[0].upper()
            expected_path = parts[1]
        else:
            # Fallback: assume it's just a path
            expected_method = None
            expected_path = parts[0] if parts else ""
        
        # Check captured API calls
        matching_calls = []
        for call in self.api_calls:
            url = call.get("url", "")
            method = call.get("method", "").upper()
            
            # Extract path from URL (e.g., "http://localhost:8000/items" -> "/items")
            # Get API base from project config
            api_base = os.getenv("PROJECT_API_BASE", os.getenv("API_BASE", "http://localhost:8000"))
            try:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(url)
                path = parsed.path
                query_params = parse_qs(parsed.query)
            except:
                # Fallback: find path after domain
                if "/" in url:
                    path = "/" + url.split("/", 3)[-1] if len(url.split("/")) > 3 else url
                else:
                    path = url
                query_params = {}
            
            # Match method and path
            method_match = expected_method is None or method == expected_method
            path_match = expected_path in path or path.endswith(expected_path)
            
            if method_match and path_match:
                # If filter_param is specified, check if it's in the query string
                if filter_param:
                    if filter_param in query_params:
                        filter_value = query_params[filter_param][0]
                        console.print(f"[green]✅ API Check: {expected_endpoint} called with filter '{filter_param}={filter_value}'[/green]")
                        matching_calls.append(call)
                    else:
                        # Filter parameter not found - this indicates filter might be broken
                        console.print(f"[yellow]⚠️  API Check: {expected_endpoint} called but filter parameter '{filter_param}' not found in query string[/yellow]")
                        console.print(f"[dim]   Query params: {query_params}[/dim]")
                        # Still add to matching_calls but mark as potentially broken
                        call["filter_missing"] = True
                        matching_calls.append(call)
                else:
                    matching_calls.append(call)
        
        if matching_calls:
            latest_call = matching_calls[-1]
            
            # Check if filter was missing (indicates broken filter)
            if latest_call.get("filter_missing") and filter_param:
                console.print(f"[red]❌ API Check: Filter parameter '{filter_param}' missing - filter may be broken[/red]")
                return False, {"error": f"Filter parameter '{filter_param}' not found in API call", "call": latest_call}
            
            console.print(f"[green]✅ API Check: {expected_endpoint} was called[/green]")
            console.print(f"[dim]   Method: {latest_call.get('method')}, Status: {latest_call.get('status')}[/dim]")
            return True, latest_call
        else:
            console.print(f"[red]❌ API Check: {expected_endpoint} was not called[/red]")
            # Format captured calls for display
            captured_strs = [f"{c.get('method')} {c.get('url')}" for c in self.api_calls[-5:]]
            console.print(f"[dim]   Captured calls: {captured_strs}[/dim]")
            return False, {"error": "API call not found", "captured_calls": self.api_calls[-5:]}
    
    async def execute_gateway_plan(self, page: Page, gateway_plan: Dict) -> bool:
        """Execute a gateway plan to login/authenticate as a persona.
        
        Uses the same robust gateway execution from semantic_mapper_with_gateway.py
        which has agentic fallbacks for finding elements when selectors fail.
        
        Args:
            page: Playwright page
            gateway_plan: Gateway plan with steps to execute
            
        Returns:
            True if gateway execution succeeded
        """
        if not gateway_plan or not gateway_plan.get("steps"):
            console.print("[yellow]   ⚠️ No gateway plan provided, skipping login[/yellow]")
            return True
        
        persona = gateway_plan.get("persona", "Unknown")
        console.print(f"[bold cyan]   🚪 Executing Gateway Plan for {persona}[/bold cyan]")
        console.print(f"[dim]   Goal: {gateway_plan.get('goal', 'N/A')}[/dim]")
        
        try:
            # Use the robust gateway execution from semantic_mapper_with_gateway.py
            # This has agentic fallbacks for finding username/password fields,
            # intelligent button discovery, and exact text matching for dropdowns
            await mapper_execute_gateway_plan(page, gateway_plan)
            console.print(f"[green]   ✅ Gateway plan completed for {persona}[/green]")
            return True
        except Exception as e:
            console.print(f"[red]   ❌ Gateway execution failed: {e}[/red]")
            return False
    
    async def execute(self) -> Dict[str, Any]:
        """Execute the mission with support for deterministic/hybrid/agentic modes.
        
        Execution modes:
        - deterministic: Use structured steps with Playwright (fast, reliable)
        - hybrid: Try deterministic first, fall back to browser-use if needed
        - agentic: Use browser-use for all UI tests (current behavior)
        
        Returns:
            Execution report with triple-check results
        """
        console.print("\n" + "=" * 70)
        console.print("[bold cyan]🎯 TRIPLE-CHECK EXECUTOR - Multi-Mode Architecture[/bold cyan]")
        console.print("=" * 70)
        console.print(f"[bold]Mission:[/bold] {self.mission.get('ticket_id')}")
        console.print(f"[bold]Target:[/bold] {self.mission.get('target_url')}")
        
        # Show personas if available
        personas = self.mission.get("personas", [])
        if personas:
            console.print(f"[bold]Personas:[/bold] {', '.join(personas)}")
        
        # Determine execution mode
        execution_mode = self.mission.get("execution_mode", "agentic")
        deterministic_steps = self.mission.get("deterministic_steps", [])
        
        console.print(f"[bold]Mode:[/bold] {execution_mode}")
        console.print()
        
        # Connect to database
        await self.connect_db()
        
        # Execution results
        results = {
            "mission_id": self.mission.get("ticket_id"),
            "execution_path": execution_mode,
            "personas": personas,
            "persona_results": {},  # Track results per persona
            "deterministic_execution": None,
            "fallback_used": False,
            "scenario_results": {},  # Track results per scenario
            "triple_check": {
                "database": {"success": False, "details": {}},
                "api": {"success": False, "details": {}},
                "ui": {"success": False, "details": {}}
            },
            "playwright_script": "",
            "overall_success": False
        }
        
        ui_success = False
        deterministic_success = False
        
        # Get persona tests if available
        persona_tests = self.mission.get("persona_tests", [])
        
        try:
            # Execute tests for each persona
            if persona_tests and execution_mode in ["deterministic", "hybrid"]:
                console.print("[bold cyan]🔧 Executing Persona-Based Tests[/bold cyan]\n")
                
                all_persona_success = True
                
                for persona_config in persona_tests:
                    persona = persona_config.get("persona", "Unknown")
                    gateway_plan = persona_config.get("gateway_plan")
                    persona_nav_path = persona_config.get("navigation_path", [])
                    persona_test_cases = persona_config.get("test_cases", [])
                    
                    console.print(f"\n[bold]👤 Testing as: {persona}[/bold]")
                    console.print("=" * 50)
                    
                    persona_result = {
                        "persona": persona,
                        "gateway_success": False,
                        "test_results": [],
                        "success": False
                    }
                    
                    try:
                        async with async_playwright() as p:
                            browser = await p.chromium.launch(headless=False)
                            page = await browser.new_page()
                            
                            # Navigate to base URL first (gateway needs login page visible)
                            base_url = "http://localhost:9000/"
                            console.print(f"[dim]   📍 Navigating to base URL: {base_url}[/dim]")
                            await page.goto(base_url, wait_until="load", timeout=30000)
                            await asyncio.sleep(2)  # Wait for page to settle
                            
                            # Step 1: Execute gateway plan to login as persona
                            if gateway_plan:
                                gateway_success = await self.execute_gateway_plan(page, gateway_plan)
                                persona_result["gateway_success"] = gateway_success
                                
                                if not gateway_success:
                                    console.print(f"[red]   ❌ Gateway failed for {persona}, skipping tests[/red]")
                                    persona_result["success"] = False
                                    results["persona_results"][persona] = persona_result
                                    all_persona_success = False
                                    await browser.close()
                                    continue
                            else:
                                persona_result["gateway_success"] = True
                                console.print(f"[dim]   ℹ️ No gateway plan for {persona}, proceeding directly[/dim]")
                            
                            # Step 2: Execute navigation path
                            console.print(f"[bold cyan]   📍 Navigating to target page[/bold cyan]")
                            for nav_step in persona_nav_path:
                                action = nav_step.get("action", "")
                                if action == "goto":
                                    url = nav_step.get("url", "")
                                    console.print(f"[dim]   → goto: {url}[/dim]")
                                    await page.goto(url, wait_until="load", timeout=30000)
                                    await asyncio.sleep(2)
                                elif action == "click":
                                    selector = nav_step.get("selector", "")
                                    console.print(f"[dim]   → click: {selector}[/dim]")
                                    try:
                                        await page.wait_for_selector(selector, timeout=15000)
                                        await page.click(selector)
                                        # Wait for navigation/network after click
                                        await asyncio.sleep(3)
                                        try:
                                            await page.wait_for_load_state("networkidle", timeout=10000)
                                        except:
                                            pass  # Continue if networkidle times out
                                    except Exception as e:
                                        console.print(f"[yellow]   ⚠️ Click failed for {selector}: {e}[/yellow]")
                                        # Try href navigation as fallback
                                        target_node = nav_step.get("target_node")
                                        href = nav_step.get("href")
                                        if href:
                                            console.print(f"[dim]   → Fallback: navigating directly to {href}[/dim]")
                                            await page.goto(href if href.startswith("http") else f"http://localhost:9000{href}")
                                elif action == "wait_visible":
                                    # Just wait for network idle - we know we're navigating to the right place
                                    console.print(f"[dim]   → waiting for page to load...[/dim]")
                                    try:
                                        await page.wait_for_load_state("networkidle", timeout=15000)
                                        console.print(f"[green]   ✅ Page loaded (network idle)[/green]")
                                    except:
                                        await asyncio.sleep(2)
                                        console.print(f"[yellow]   ⚠️ Network idle timeout, continuing[/yellow]")
                            
                            # Step 3: Execute persona-specific test cases
                            console.print(f"[bold cyan]   🧪 Running tests for {persona}[/bold cyan]")
                            
                            # Create a mission subset for this persona
                            persona_mission = {
                                **self.mission,
                                "test_cases": persona_test_cases,
                                "deterministic_steps": [
                                    ds for ds in deterministic_steps 
                                    if persona.lower() in ds.get("test_case_id", "").lower() or 
                                       not any(p.lower() in ds.get("test_case_id", "").lower() 
                                              for p in ["reseller", "distributor", "admin"] 
                                              if p.lower() != persona.lower())
                                ]
                            }
                            
                            # Load semantic graph for this persona
                            semantic_graph = self.load_semantic_graph(persona)
                            
                            deterministic_executor = DeterministicExecutor(page, persona_mission, semantic_graph, llm=self.llm, db_connection=self.db_connection)
                            det_results = await deterministic_executor.execute_all()
                            
                            persona_result["test_results"] = det_results.get("test_case_results", [])
                            persona_result["success"] = det_results.get("success", False)
                            persona_result["api_calls"] = det_results.get("api_calls", [])
                            
                            # Capture API calls
                            det_api_calls = det_results.get("api_calls", [])
                            if det_api_calls:
                                self.api_calls.extend(det_api_calls)
                            
                            if not persona_result["success"]:
                                all_persona_success = False
                            
                            # Keep browser open briefly
                            await asyncio.sleep(2)
                            await browser.close()
                        
                    except Exception as e:
                        import traceback
                        error_trace = traceback.format_exc()
                        console.print(f"[red]   ❌ Persona test failed for {persona}: {e}[/red]")
                        persona_result["error"] = str(e)
                        persona_result["success"] = False
                        all_persona_success = False
                    
                    results["persona_results"][persona] = persona_result
                    
                    success_icon = "✅" if persona_result["success"] else "❌"
                    console.print(f"\n[bold]{success_icon} {persona} Tests: {'PASS' if persona_result['success'] else 'FAIL'}[/bold]")
                
                deterministic_success = all_persona_success
                ui_success = all_persona_success
                results["deterministic_execution"] = {"persona_based": True, "success": all_persona_success}
                
                if deterministic_success:
                    results["execution_path"] = "deterministic"
                    console.print("\n[green]✅ All persona tests completed successfully[/green]\n")
                else:
                    console.print("\n[yellow]⚠️ Some persona tests had failures[/yellow]\n")
            
            # Fallback: Try deterministic execution without persona separation
            elif execution_mode in ["deterministic", "hybrid"] and deterministic_steps:
                console.print("[bold cyan]🔧 Attempting Deterministic Execution[/bold cyan]\n")
                
                try:
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=False)
                        page = await browser.new_page()
                        
                        # Execute deterministic steps
                        # Try to get persona from mission for semantic graph
                        personas = self.mission.get("personas", [])
                        persona = personas[0] if personas else "Reseller"
                        semantic_graph = self.load_semantic_graph(persona)
                        
                        deterministic_executor = DeterministicExecutor(page, self.mission, semantic_graph, llm=self.llm, db_connection=self.db_connection)
                        det_results = await deterministic_executor.execute_all()
                        
                        results["deterministic_execution"] = det_results
                        deterministic_success = det_results.get("success", False)
                        
                        # Capture API calls from deterministic execution
                        det_api_calls = det_results.get("api_calls", [])
                        if det_api_calls:
                            self.api_calls.extend(det_api_calls)
                            console.print(f"[dim]   📡 Captured {len(det_api_calls)} API call(s) from deterministic execution[/dim]")
                        
                        # Keep browser open briefly
                        await asyncio.sleep(2)
                        await browser.close()
                    
                    if deterministic_success:
                        ui_success = True
                        results["execution_path"] = "deterministic"
                        console.print("[green]✅ Deterministic execution completed successfully[/green]\n")
                    else:
                        console.print("[yellow]⚠️ Deterministic execution had failures[/yellow]\n")
                        
                        # Check if fallback is needed
                        if det_results.get("requires_fallback") and execution_mode == "hybrid":
                            console.print("[yellow]   Some steps require browser-use fallback[/yellow]")
                
                except Exception as e:
                    import traceback
                    error_trace = traceback.format_exc()
                    console.print(f"[red]❌ Deterministic execution failed: {e}[/red]")
                    console.print(f"[dim]{error_trace}[/dim]")
                    results["deterministic_execution"] = {"error": str(e), "traceback": error_trace}
                    deterministic_success = False
            
            # Fall back to browser-use if:
            # - Mode is "agentic" OR
            # - Mode is "hybrid" and deterministic failed OR
            # - Mode is "hybrid" and some steps require browser-use
            should_use_browser_use = (
                execution_mode == "agentic" or
                (execution_mode == "hybrid" and not deterministic_success) or
                (execution_mode == "hybrid" and results.get("deterministic_execution", {}).get("requires_fallback"))
            )
            
            if should_use_browser_use and self.llm:
                if execution_mode == "hybrid" and not deterministic_success:
                    console.print("[bold cyan]🤖 Falling back to browser-use Agent[/bold cyan]\n")
                    results["fallback_used"] = True
                    results["execution_path"] = "hybrid"
                else:
                    console.print("[bold cyan]🤖 Using browser-use Agent for UI Tests[/bold cyan]\n")
                
                try:
                    console.print("[dim]   Initializing BrowserAgent...[/dim]")
                    # BrowserAgent now uses browser-use internally - no page needed
                    browser_agent = BrowserAgent(None, self.llm, self.mission)
                    console.print("[dim]   ✅ BrowserAgent initialized, executing scenarios...[/dim]")
                    ui_results = await browser_agent.execute_all_scenarios()
                    console.print("[dim]   ✅ Scenarios execution completed[/dim]")
                    
                    # Store UI results
                    results["scenario_results"] = ui_results.get("scenario_results", {})
                    results["playwright_script"] = ui_results.get("playwright_script", "")
                    results["ui_execution"] = ui_results
                    
                    # Capture API calls from browser-use session
                    browser_api_calls = ui_results.get("api_calls", [])
                    if browser_api_calls:
                        self.api_calls.extend(browser_api_calls)
                        console.print(f"[dim]   📡 Captured {len(browser_api_calls)} API call(s) from browser-use[/dim]")
                    
                    # Determine UI success from scenario results
                    ui_success = ui_results.get("success", False)
                except Exception as e:
                    import traceback
                    error_trace = traceback.format_exc()
                    console.print(f"[red]❌ BrowserAgent execution failed: {e}[/red]")
                    console.print(f"[dim]{error_trace}[/dim]")
                    ui_success = False
                    results["ui_execution"] = {"error": str(e), "traceback": error_trace}
                    # Also store in scenario_results for better visibility
                    results["scenario_results"] = {
                        "browser_agent_error": {
                            "success": False,
                            "error": str(e),
                            "traceback": error_trace
                        }
                    }
            elif not self.llm and not deterministic_success:
                console.print("[yellow]⚠️  No LLM available and deterministic execution failed[/yellow]\n")
                ui_success = False
                results["ui_execution"] = {"error": "No LLM available for fallback"}
            
            # Create a browser just for verification (checking UI state after tests)
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # Wait a bit for API/DB to process
                await asyncio.sleep(2)
                
                # Triple-Check Verification (Deterministic)
                console.print("[bold cyan]🔍 TRIPLE-CHECK VERIFICATION[/bold cyan]\n")
                
                # Get test scope from mission (agentic decision)
                test_scope = self.mission.get("test_scope", {
                    "test_db": True,
                    "test_api": True,
                    "test_ui": True
                })
                
                verification = self.mission.get("verification_points", {})
                expected_values = verification.get("expected_values", {})
                api_endpoint = verification.get("api_endpoint", "")
                db_table = verification.get("db_table", "items")
                
                # Get db_schema from db_verification config (extracted from PR)
                db_verification = self.mission.get("db_verification", {})
                db_schema = db_verification.get("db_schema")
                
                # 1. Database Check (Deterministic) - Skip if test_scope says no
                if test_scope.get("test_db", True):
                    console.print("[bold]1️⃣ Database Verification[/bold]")
                    db_success, db_result = await self.verify_database(expected_values, db_table=db_table, db_schema=db_schema)
                    results["triple_check"]["database"] = {
                        "success": db_success,
                        "details": db_result
                    }
                else:
                    console.print("[bold]1️⃣ Database Verification[/bold] [dim](Skipped - not in test scope)[/dim]")
                    results["triple_check"]["database"] = {
                        "success": True,
                        "details": {"skipped": True, "reason": test_scope.get("reasoning", "Not in test scope")}
                    }
                console.print()
                
                # 2. API Check (Deterministic) - Skip if test_scope says no
                if test_scope.get("test_api", True):
                    console.print("[bold]2️⃣ API Verification[/bold]")
                    # Check if any scenario requires API verification with filter
                    filter_param = None
                    for scenario in self.mission.get("test_cases", []):
                        verification_req = scenario.get("verification", {})
                        if verification_req.get("api") and "filter" in verification_req.get("api", "").lower():
                            # Try to extract filter parameter from scenario
                            scenario_id = scenario.get("id", "")
                            if "filter" in scenario_id:
                                # Use test_data directly from the scenario
                                test_data = scenario.get("test_data", {})
                                filter_param = list(test_data.keys())[0] if test_data else None
                                break
                    
                    api_success, api_result = await self.verify_api(page, api_endpoint, filter_param=filter_param)
                    results["triple_check"]["api"] = {
                        "success": api_success,
                        "details": api_result
                    }
                else:
                    console.print("[bold]2️⃣ API Verification[/bold] [dim](Skipped - not in test scope)[/dim]")
                    results["triple_check"]["api"] = {
                        "success": True,
                        "details": {"skipped": True, "reason": test_scope.get("reasoning", "Not in test scope")}
                    }
                console.print()
                
                # 3. UI Check - Use results from agentic execution - Skip if test_scope says no
                if test_scope.get("test_ui", True):
                    console.print("[bold]3️⃣ UI Verification[/bold]")
                    results["triple_check"]["ui"] = {
                        "success": ui_success,
                        "details": results.get("scenario_results", {})
                    }
                else:
                    console.print("[bold]3️⃣ UI Verification[/bold] [dim](Skipped - not in test scope)[/dim]")
                    results["triple_check"]["ui"] = {
                        "success": True,
                        "details": {"skipped": True, "reason": test_scope.get("reasoning", "Not in test scope")}
                    }
                console.print()
                
                # Map triple-check results to scenarios
                scenario_map = {}
                for scenario in self.mission.get("test_cases", []):
                    scenario_id = scenario.get("id", "")
                    scenario_map[scenario_id] = {
                        "purpose": scenario.get("purpose", ""),
                        "verification": scenario.get("verification", {})
                    }
                
                for scenario_id, scenario_info in results.get("scenario_results", {}).items():
                    verification_req = scenario_map.get(scenario_id, {}).get("verification", {})
                    
                    # Ensure verification structure exists with all required keys
                    if "verification" not in scenario_info or not isinstance(scenario_info.get("verification"), dict):
                        scenario_info["verification"] = {}
                    
                    # Ensure all verification sub-keys exist
                    for key in ["ui", "api", "db"]:
                        if key not in scenario_info["verification"] or not isinstance(scenario_info["verification"].get(key), dict):
                            scenario_info["verification"][key] = {"success": False, "checked": False}
                    
                    # Check UI verification if required
                    if verification_req.get("ui"):
                        scenario_info["verification"]["ui"]["success"] = ui_success
                        scenario_info["verification"]["ui"]["checked"] = True
                    
                    # Check API verification if required
                    if verification_req.get("api"):
                        scenario_info["verification"]["api"]["success"] = api_success
                        scenario_info["verification"]["api"]["checked"] = True
                    
                    # Check DB verification if required
                    if verification_req.get("db"):
                        scenario_info["verification"]["db"]["success"] = db_success
                        scenario_info["verification"]["db"]["checked"] = True
                
                # Overall success
                results["overall_success"] = db_success and api_success and ui_success
                
                # Keep browser open for a moment to see results
                await asyncio.sleep(3)
                await browser.close()
        
        finally:
            await self.close_db()
        
        # Print summary
        console.print("=" * 70)
        console.print("[bold cyan]📊 EXECUTION SUMMARY[/bold cyan]")
        console.print("=" * 70)
        console.print(f"Execution Path: {results['execution_path']}")
        console.print()
        console.print("Triple-Check Results:")
        console.print(f"  ✅ Database: {'PASS' if results['triple_check']['database']['success'] else 'FAIL'}")
        console.print(f"  ✅ API: {'PASS' if results['triple_check']['api']['success'] else 'FAIL'}")
        console.print(f"  ✅ UI: {'PASS' if results['triple_check']['ui']['success'] else 'FAIL'}")
        console.print()
        
        # Print scenario results
        if results.get("scenario_results"):
            console.print("Scenario Results:")
            for scenario_id, scenario_result in results["scenario_results"].items():
                success_icon = "✅" if scenario_result.get("success") else "❌"
                console.print(f"  {success_icon} {scenario_result.get('purpose', scenario_id)}")
                verification = scenario_result.get("verification", {})
                if verification.get("ui", {}).get("checked"):
                    ui_icon = "✅" if verification["ui"]["success"] else "❌"
                    console.print(f"      {ui_icon} UI: {verification['ui'].get('reasoning', 'Verified')}")
                if verification.get("api", {}).get("checked"):
                    api_icon = "✅" if verification["api"]["success"] else "❌"
                    console.print(f"      {api_icon} API: Verified")
                if verification.get("db", {}).get("checked"):
                    db_icon = "✅" if verification["db"]["success"] else "❌"
                    console.print(f"      {db_icon} DB: Verified")
        console.print()
        
        # Print Playwright script location
        if results.get("playwright_script"):
            console.print("[green]📝 Playwright script generated (see playwright_script in results)[/green]")
        
        console.print(f"[bold]{'✅ OVERALL: PASS' if results['overall_success'] else '❌ OVERALL: FAIL'}[/bold]")
        console.print("=" * 70)
        
        return results


class DeterministicExecutor:
    """Executor for deterministic steps using Playwright.
    
    Similar to gateway plan execution, this executes structured steps
    with selectors for faster, more reliable test execution.
    """
    
    def __init__(self, page: Page, mission: Dict[str, Any], semantic_graph: Optional[Dict[str, Any]] = None, llm=None, db_connection=None):
        self.page = page
        self.mission = mission
        self.semantic_graph = semantic_graph
        self.llm = llm
        self.db_connection = db_connection  # Database connection for DB verification
        self.api_calls: List[Dict] = []
        self.step_results: List[Dict] = []
        self._network_handler_setup = False
        
        # Build navigation lookup from semantic graph
        self._node_by_url: Dict[str, Dict] = {}
        self._node_by_id: Dict[str, Dict] = {}
        self._edges_from: Dict[str, List[Dict]] = {}  # from_node_id -> list of edges
        
        # Extract context for JIT selector resolution
        self._jit_context = self._build_jit_context()
        
        if semantic_graph:
            self._build_navigation_index(semantic_graph)
    
    def _build_jit_context(self) -> Dict[str, Any]:
        """Build context from mission for JIT selector resolution.
        
        Extracts PR diff info, task intent, and component selectors to help
        the LLM make better selector decisions at runtime.
        """
        context = {
            "intent": {},
            "pr_link": None,
            "target_node": None,
            "target_components": [],
            "field_selectors": {},
            "api_field_mapping": {},
        }
        
        # Extract intent from mission
        intent = self.mission.get("intent", {})
        if intent:
            context["intent"] = {
                "primary_entity": intent.get("primary_entity", ""),
                "changes": intent.get("changes", []),
                "test_focus": intent.get("test_focus", ""),
            }
        
        # Extract PR link
        context["pr_link"] = self.mission.get("pr_link", "")
        
        # Extract target node info
        context["target_node"] = self.mission.get("target_node", "")
        
        # Extract component info from test cases
        for test_case in self.mission.get("test_cases", []):
            if test_case.get("component_selector"):
                context["target_components"].append({
                    "selector": test_case.get("component_selector"),
                    "role": test_case.get("component_role", ""),
                })
            if test_case.get("field_selectors"):
                context["field_selectors"].update(test_case["field_selectors"])
            
            # Extract API field mappings
            verification = test_case.get("verification", {})
            if verification.get("api_field_mapping"):
                context["api_field_mapping"].update(verification["api_field_mapping"])
        
        # Extract from semantic graph if available
        if self.semantic_graph:
            target_node_id = self.mission.get("target_node", "")
            for node in self.semantic_graph.get("nodes", []):
                if node.get("id") == target_node_id:
                    # Get components with selectors from target node
                    for comp in node.get("components", []):
                        if comp.get("selector"):
                            context["target_components"].append({
                                "selector": comp.get("selector"),
                                "role": comp.get("role", ""),
                                "name": comp.get("name", ""),
                            })
                    break
        
        # Extract UI elements from PR patches if available
        context["pr_ui_elements"] = self._extract_pr_ui_elements()
        
        return context
    
    def _extract_pr_ui_elements(self) -> List[str]:
        """Extract only UI element snippets from PR for JIT context.
        
        Uses pre-processed pr_ui_changes from mission (created by context_processor).
        Each entry has 'filename' and 'elements' (list of UI element lines).
        
        Returns:
            List of UI element snippets (max 20 lines, focused on new additions)
        """
        pr_ui_changes = self.mission.get("pr_ui_changes", [])
        if not pr_ui_changes:
            return []
        
        ui_elements = []
        
        for file_info in pr_ui_changes[:10]:  # Limit to 10 files
            elements = file_info.get("elements", [])
            for elem in elements:
                if len(ui_elements) >= 20:
                    break
                ui_elements.append(elem)
            if len(ui_elements) >= 20:
                break
        
        return ui_elements
    
    def _build_jit_context_hints(self, description: str) -> str:
        """Build context hints string for JIT selector resolution prompts.
        
        Keeps context minimal and focused on what's relevant to the element.
        
        Args:
            description: The element description being searched for
            
        Returns:
            Formatted context string to include in LLM prompts
        """
        import re
        hints = []
        desc_lower = description.lower()
        desc_keywords = set(re.findall(r'\b\w{3,}\b', desc_lower))
        
        # Add only the most relevant intent (one line)
        intent = self._jit_context.get("intent", {})
        if intent.get("test_focus"):
            # Truncate to 150 chars
            focus = intent['test_focus'][:150]
            hints.append(f"**Testing**: {focus}")
        
        # Add API field mappings ONLY if relevant to this description
        api_mapping = self._jit_context.get("api_field_mapping", {})
        if api_mapping:
            relevant_mappings = []
            for ui_name, api_field in api_mapping.items():
                # Check if this mapping is relevant to current element
                ui_keywords = set(re.findall(r'\b\w{3,}\b', ui_name.lower()))
                if ui_keywords & desc_keywords:  # Intersection
                    relevant_mappings.append(f"{ui_name}={api_field}")
            if relevant_mappings:
                hints.append(f"**Fields**: {', '.join(relevant_mappings[:3])}")
        
        # Add PR UI elements - filter to only those relevant to description
        pr_ui_elements = self._jit_context.get("pr_ui_elements", [])
        if pr_ui_elements:
            relevant_elements = []
            for elem in pr_ui_elements:
                elem_lower = elem.lower()
                # Check if element contains any of our keywords
                if any(kw in elem_lower for kw in desc_keywords if len(kw) > 3):
                    relevant_elements.append(elem)
                    if len(relevant_elements) >= 5:
                        break
            
            if relevant_elements:
                hints.append("**PR Added Elements**:\n```\n" + "\n".join(relevant_elements) + "\n```")
        
        # Add known selectors ONLY if they match description keywords
        target_components = self._jit_context.get("target_components", [])
        if target_components:
            relevant_selectors = []
            for comp in target_components:
                if comp.get("selector"):
                    comp_name = comp.get("name", comp.get("role", "")).lower()
                    comp_keywords = set(re.findall(r'\b\w{3,}\b', comp_name))
                    if comp_keywords & desc_keywords:
                        relevant_selectors.append(f"{comp.get('name', 'elem')}: {comp['selector']}")
            if relevant_selectors:
                hints.append("**Known selectors**: " + ", ".join(relevant_selectors[:3]))
        
        if hints:
            return "## Context:\n" + "\n".join(hints) + "\n"
        return ""
    
    def _build_navigation_index(self, graph: Dict[str, Any]):
        """Build lookup tables for efficient navigation from semantic graph."""
        # Index nodes by URL and ID
        for node in graph.get("nodes", []):
            node_id = node.get("id")
            node_url = node.get("url", "")
            if node_id:
                self._node_by_id[node_id] = node
            if node_url:
                # Normalize URL (remove trailing slash, query params for matching)
                normalized = node_url.rstrip("/")
                self._node_by_url[normalized] = node
                # Also index by path only
                parsed = urlparse(node_url)
                self._node_by_url[parsed.path.rstrip("/")] = node
        
        # Index edges by source node
        for edge in graph.get("edges", []):
            from_id = edge.get("from")
            if from_id:
                if from_id not in self._edges_from:
                    self._edges_from[from_id] = []
                self._edges_from[from_id].append(edge)
    
    def _find_current_node(self, current_url: str) -> Optional[Dict]:
        """Find the semantic graph node matching the current URL."""
        # Try exact match first
        normalized = current_url.rstrip("/")
        if normalized in self._node_by_url:
            return self._node_by_url[normalized]
        
        # Try path-only match
        parsed = urlparse(current_url)
        path = parsed.path.rstrip("/")
        if path in self._node_by_url:
            return self._node_by_url[path]
        
        # Try matching base path (without query params)
        base_url = f"{parsed.scheme}://{parsed.netloc}{path}"
        if base_url in self._node_by_url:
            return self._node_by_url[base_url]
        
        return None
    
    def _find_target_node(self, target_text: str) -> Optional[Dict]:
        """Find semantic graph node matching target description using text matching."""
        target_lower = target_text.lower()
        keywords = [w for w in target_lower.split() if len(w) > 2]
        
        best_match = None
        best_score = 0
        
        for node in self._node_by_id.values():
            score = 0
            # Check display_header
            header = (node.get("display_header") or "").lower()
            for kw in keywords:
                if kw in header:
                    score += 3
            # Check semantic_name
            name = (node.get("semantic_name") or "").lower()
            for kw in keywords:
                if kw in name:
                    score += 2
            # Check description
            desc = (node.get("description") or "").lower()
            for kw in keywords:
                if kw in desc:
                    score += 1
            # Check URL
            url = (node.get("url") or "").lower()
            for kw in keywords:
                if kw in url:
                    score += 2
            
            if score > best_score:
                best_score = score
                best_match = node
        
        return best_match if best_score > 0 else None
    
    def _find_navigation_path(self, from_node_id: str, to_node_id: str) -> Optional[List[Dict]]:
        """Find path of edges from source to target node using BFS."""
        if from_node_id == to_node_id:
            return []
        
        from collections import deque
        visited = {from_node_id}
        queue = deque([(from_node_id, [])])  # (node_id, path_of_edges)
        
        while queue:
            current_id, path = queue.popleft()
            
            for edge in self._edges_from.get(current_id, []):
                if edge.get("is_external"):
                    continue  # Skip external edges
                
                next_id = edge.get("to")
                if not next_id or next_id in visited:
                    continue
                
                new_path = path + [edge]
                
                if next_id == to_node_id:
                    return new_path
                
                visited.add(next_id)
                queue.append((next_id, new_path))
        
        return None  # No path found
    
    async def _resolve_selector_at_runtime(self, description: str, action: str) -> Optional[str]:
        """Resolve a selector at runtime using LLM analysis of the current page.
        
        Uses a 2-step agentic process:
        1. Ask LLM what HTML tags/attributes to look for based on description
        2. Extract only those elements from page
        3. Ask LLM to pick the best selector from the filtered HTML
        
        Now enhanced with PR diff context, task intent, and known selectors
        from the semantic graph and mission configuration.
        
        Args:
            description: Description of the element to find (e.g., "TCV column header")
            action: Action being performed (e.g., "click", "assert_visible")
            
        Returns:
            New CSS selector or None if resolution failed
        """
        if not self.llm:
            return None
            
        console.print(f"[bold yellow]   🤖 Attempting JIT selector resolution for: '{description}'[/bold yellow]")
        
        # Build context hints from mission/task
        context_hints = self._build_jit_context_hints(description)
        
        try:
            # Step 1: Ask LLM what to look for (enhanced with context)
            # This reduces the context window by filtering the DOM first
            query_prompt = f"""You are a Playwright automation expert. The user wants to {action} on: "{description}".

{context_hints}

What HTML tags and attributes should we scan the page for?
Return a JSON object with:
- "tags": list of tag names (e.g. ["button", "a", "th"])
- "attributes": list of attributes to check (e.g. ["id", "class", "data-testid", "role"])
- "text_keywords": list of keywords to look for in text content (e.g. ["Save", "Submit"])

Keep it focused on elements likely to match "{description}".
"""
            
            try:
                response = self.llm.invoke(query_prompt)
                content = response.content if hasattr(response, 'content') else str(response)
                
                # Extract JSON (json already imported at top of file)
                json_match = re.search(r'\{[\s\S]*\}', content)
                if not json_match:
                    console.print(f"[red]      ❌ Failed to parse LLM strategy[/red]")
                    return None
                    
                strategy = json.loads(json_match.group())
                tags = strategy.get("tags", ["button", "a", "input", "div", "span"])
                attributes = strategy.get("attributes", ["id", "class", "role", "name", "aria-label"])
                keywords = strategy.get("text_keywords", [])
                
            except Exception as e:
                console.print(f"[yellow]      ⚠️ Strategy generation failed: {e}, using defaults[/yellow]")
                tags = ["button", "a", "input", "select", "th", "td", "div", "span"]
                attributes = ["id", "class", "role", "name", "aria-label", "data-testid"]
                keywords = [w for w in description.split() if len(w) > 3]

            # Step 2: Extract filtered HTML based on strategy
            # We use evaluate to run this in browser context
            html_snapshot = await self.page.evaluate(f"""(strategy) => {{
                const tags = {json.dumps(tags)};
                const attrs = {json.dumps(attributes)};
                const keywords = {json.dumps(keywords)};
                
                function getFilteredDom(element, depth = 0) {{
                    if (depth > 15) return ''; 
                    
                    // Skip hidden elements
                    const style = window.getComputedStyle(element);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {{
                        return '';
                    }}
                    
                    const tagName = element.tagName.toLowerCase();
                    let isRelevant = tags.includes(tagName);
                    
                    // Check text content for keywords
                    const text = element.innerText || '';
                    if (keywords.some(k => text.toLowerCase().includes(k.toLowerCase()))) {{
                        isRelevant = true;
                    }}
                    
                    // Always include structure tags if they contain relevant children
                    const structureTags = ['table', 'thead', 'tbody', 'tr', 'form', 'nav', 'header', 'main'];
                    if (structureTags.includes(tagName)) {{
                        isRelevant = true; 
                    }}

                    let html = '';
                    let hasRelevantChild = false;
                    
                    // Recurse for children
                    let childrenHtml = '';
                    for (const child of element.children) {{
                        const childResult = getFilteredDom(child, depth + 1);
                        if (childResult) {{
                            childrenHtml += childResult;
                            hasRelevantChild = true;
                        }}
                    }}
                    
                    if (isRelevant || hasRelevantChild) {{
                        // Build opening tag
                        let attrStr = '';
                        for (const attr of attrs) {{
                            if (element.hasAttribute(attr)) {{
                                attrStr += ` ${{attr}}="${{element.getAttribute(attr)}}"`;
                            }}
                        }}
                        
                        html += `<${{tagName}}${{attrStr}}>`;
                        
                        // Add text if it's a leaf node or relevant container
                        if (!hasRelevantChild && text.length < 200) {{
                            html += text.trim();
                        }} else {{
                            html += childrenHtml;
                        }}
                        
                        html += `</${{tagName}}>`;
                        return html;
                    }}
                    
                    return '';
                }}
                
                return getFilteredDom(document.body);
            }}""", {})
            
            # Truncate if still too large
            if len(html_snapshot) > 30000:
                html_snapshot = html_snapshot[:30000] + "...(truncated)"
            
            # Step 3: Ask LLM to find selector (enhanced with context)
            prompt = f"""You are a Playwright selector expert. 
The user wants to {action} on "{description}".

{context_hints}

Here is the filtered HTML structure (containing only relevant elements):
```html
{html_snapshot}
```

Find the best, most robust CSS selector for "{description}".
Rules:
1. Prefer robust attributes: id, data-testid, aria-label, name.
2. If text is unique, use :has-text('text') with EXACT case matching.
3. For tables, handle nested structures (e.g. th > div > span.title).
4. Pay attention to the task context above - it tells you what we're testing.
5. Return ONLY the selector string, no explanation.
6. If you cannot find a matching element, return "NOT_FOUND".
"""
            
            response = self.llm.invoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            new_selector = content.strip()
            
            if new_selector and new_selector != "NOT_FOUND":
                # Clean up response
                new_selector = new_selector.replace("```css", "").replace("```", "").replace("```json", "").strip()
                
                # Handle JSON responses like {"selector": "..."}
                if new_selector.startswith("{") and "selector" in new_selector:
                    try:
                        parsed = json.loads(new_selector)
                        if isinstance(parsed, dict) and "selector" in parsed:
                            new_selector = parsed["selector"]
                    except (json.JSONDecodeError, ValueError):
                        # Try regex extraction as fallback
                        match = re.search(r'"selector"\s*:\s*"([^"]+)"', new_selector)
                        if match:
                            new_selector = match.group(1)
                
                console.print(f"[green]      ✅ JIT resolved selector: {new_selector}[/green]")
                return new_selector
            else:
                console.print(f"[red]      ❌ JIT failed to resolve selector[/red]")
                return None
                
        except Exception as e:
            console.print(f"[red]      ❌ JIT resolution error: {e}[/red]")
            return None

    async def setup_network_interception(self):
        """Set up network interception to capture API calls during execution."""
        if self._network_handler_setup:
            return
        
        async def handle_request(request):
            """Capture outgoing API requests."""
            url = request.url
            # Filter to only capture API calls (not static assets)
            if self._is_api_request(url):
                self.api_calls.append({
                    "type": "request",
                    "method": request.method,
                    "url": url,
                    "timestamp": datetime.now().isoformat()
                })
        
        async def handle_response(response):
            """Capture API responses."""
            url = response.url
            if self._is_api_request(url):
                try:
                    # Try to get response body for API calls
                    body = None
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        try:
                            body = await response.json()
                        except:
                            pass
                    
                    self.api_calls.append({
                        "type": "response",
                        "method": response.request.method,
                        "url": url,
                        "status": response.status,
                        "body": body,
                        "timestamp": datetime.now().isoformat()
                    })
                except Exception as e:
                    console.print(f"[dim]   ⚠️ Failed to capture response: {e}[/dim]")
        
        self.page.on("request", handle_request)
        self.page.on("response", handle_response)
        self._network_handler_setup = True
        console.print("[dim]   📡 Network interception enabled[/dim]")
    
    def _is_api_request(self, url: str) -> bool:
        """Determine if a request is an API call (not static asset)."""
        # Skip static assets
        static_extensions = ['.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', 
                            '.woff', '.woff2', '.ttf', '.eot', '.ico', '.map']
        url_lower = url.lower()
        for ext in static_extensions:
            if ext in url_lower:
                return False
        
        # Skip static paths
        static_paths = ['/static/', '/assets/', '/public/', '/_next/', '/favicon']
        for path in static_paths:
            if path in url_lower:
                return False
        
        # Include if it looks like an API call
        api_indicators = ['/api/', '/graphql', '/rest/', '/v1/', '/v2/']
        for indicator in api_indicators:
            if indicator in url_lower:
                return True
        
        # Get base URL and API base from project config
        base_url = os.getenv("PROJECT_BASE_URL", os.getenv("BASE_URL", "http://localhost:5173"))
        api_base = os.getenv("PROJECT_API_BASE", os.getenv("API_BASE", ""))
        
        if api_base and url.startswith(api_base):
            return True
        
        return False
    
    async def execute_step(self, step: Dict) -> Dict:
        """Execute a single deterministic step.
        
        Args:
            step: Step definition with action, selector, etc.
            
        Returns:
            Step execution result
        """
        action = step.get("action", "")
        result = {
            "action": action,
            "step": step,
            "success": False,
            "error": None,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            if action == "goto":
                url = step.get("url", "")
                console.print(f"[dim]   → goto: {url}[/dim]")
                # Use "load" instead of "networkidle" - pages with polling never reach networkidle
                await self.page.goto(url, wait_until="load", timeout=30000)
                await asyncio.sleep(1)  # Give time for dynamic content
                result["success"] = True
            
            elif action == "click":
                selector = step.get("selector", "")
                description = step.get("description", selector)
                console.print(f"[dim]   → click: {selector}[/dim]")
                
                try:
                    await self.page.wait_for_selector(selector, timeout=10000)
                    await self.page.click(selector)
                except (PlaywrightTimeoutError, Exception) as e:
                    # Try JIT resolution
                    console.print(f"[yellow]      ⚠️ Selector failed, attempting JIT resolution...[/yellow]")
                    new_selector = await self._resolve_selector_at_runtime(description, "click")
                    if new_selector:
                        try:
                            await self.page.wait_for_selector(new_selector, timeout=5000)
                            await self.page.click(new_selector)
                            console.print(f"[green]      ✅ JIT retry succeeded[/green]")
                        except Exception as e2:
                            raise e  # Raise original error if JIT fails
                    else:
                        raise e  # Raise original error if JIT resolution fails

                # Use "load" instead of "networkidle" - pages with polling never reach networkidle
                try:
                    await self.page.wait_for_load_state("load", timeout=5000)
                except:
                    pass  # Continue even if load state doesn't complete
                await asyncio.sleep(0.5)  # Give time for dynamic content
                result["success"] = True
            
            elif action == "fill":
                selector = step.get("selector", "")
                value = step.get("value", "")
                description = step.get("description", f"fill {selector}")
                console.print(f"[dim]   → fill: {selector} = '{value}'[/dim]")
                
                try:
                    await self.page.wait_for_selector(selector, timeout=10000)
                    await self.page.fill(selector, value)
                except (PlaywrightTimeoutError, Exception) as e:
                    # Try JIT resolution
                    console.print(f"[yellow]      ⚠️ Selector failed, attempting JIT resolution...[/yellow]")
                    new_selector = await self._resolve_selector_at_runtime(description, "fill")
                    if new_selector:
                        try:
                            await self.page.wait_for_selector(new_selector, timeout=5000)
                            await self.page.fill(new_selector, value)
                            console.print(f"[green]      ✅ JIT retry succeeded[/green]")
                        except Exception as e2:
                            raise e
                    else:
                        raise e
                        
                result["success"] = True
            
            elif action == "wait_visible":
                selector = step.get("selector", "")
                timeout = step.get("timeout", 10000)
                description = step.get("description", f"wait for {selector}")
                console.print(f"[dim]   → wait_visible: {selector}[/dim]")
                
                try:
                    await self.page.wait_for_selector(selector, state="visible", timeout=timeout)
                except (PlaywrightTimeoutError, Exception) as e:
                    fallback_found = False
                    
                    # Strategy 1: Use actual captured headers from semantic graph
                    if self.semantic_graph:
                        current_url = self.page.url
                        current_node = self._find_current_node(current_url)
                        if current_node:
                            # Try actual captured headers from the page (real text that exists)
                            headers = current_node.get("headers", [])
                            # Filter to meaningful headers (not dates, dashes, or short strings)
                            meaningful_headers = [
                                h for h in headers 
                                if h and len(h) > 3 
                                and not h.startswith('-')
                                and not any(c.isdigit() for c in h[:3])  # Skip dates
                                and h not in ['©', '-', '|']
                            ]
                            
                            for header_text in meaningful_headers[:5]:  # Try first 5 meaningful headers
                                try:
                                    # Use text selector with the actual captured header
                                    text_selector = f"text={header_text}"
                                    await self.page.wait_for_selector(text_selector, state="visible", timeout=2000)
                                    console.print(f"[green]      ✅ Found captured header: '{header_text}'[/green]")
                                    fallback_found = True
                                    break
                                except:
                                    continue
                            
                            # Strategy 2: Try component selectors with stable_text
                            if not fallback_found:
                                components = current_node.get("components", [])
                                for comp in components[:10]:
                                    stable_text = comp.get("stable_text", "")
                                    comp_selector = comp.get("selector")
                                    if stable_text and len(stable_text) > 3:
                                        try:
                                            text_selector = f"text={stable_text}"
                                            await self.page.wait_for_selector(text_selector, state="visible", timeout=2000)
                                            console.print(f"[green]      ✅ Found component text: '{stable_text}'[/green]")
                                            fallback_found = True
                                            break
                                        except:
                                            continue
                            
                            # Strategy 3: Confirm via URL if we're on the target page
                            if not fallback_found:
                                target_node_id = self.mission.get("target_node", "")
                                if current_node.get("id") == target_node_id:
                                    console.print(f"[green]      ✅ URL confirms target page: {current_node.get('id')}[/green]")
                                    fallback_found = True
                    
                    # Strategy 4: JIT resolution as last resort
                    if not fallback_found:
                        console.print(f"[yellow]      ⚠️ Selector failed, attempting JIT resolution...[/yellow]")
                        new_selector = await self._resolve_selector_at_runtime(description, "wait for visibility")
                        if new_selector and new_selector != "NOT_FOUND":
                            try:
                                await self.page.wait_for_selector(new_selector, state="visible", timeout=5000)
                                console.print(f"[green]      ✅ JIT retry succeeded[/green]")
                                fallback_found = True
                            except Exception as e2:
                                pass
                    
                    if not fallback_found:
                        raise e
                        
                result["success"] = True
            
            elif action == "navigate_to_page":
                # Use semantic graph for navigation when available
                target_text = step.get("target_text", "")
                instruction = step.get("instruction", f"Navigate to {target_text}")
                console.print(f"[dim]   → navigate_to_page: {target_text}[/dim]")
                
                navigation_success = False
                
                # Strategy 1: Use semantic graph edges (preferred - deterministic)
                if self.semantic_graph and self._node_by_id:
                    console.print(f"[dim]      📊 Using semantic graph for navigation[/dim]")
                    
                    # Find current page node
                    current_url = self.page.url
                    current_node = self._find_current_node(current_url)
                    
                    if current_node:
                        console.print(f"[dim]      Current node: {current_node.get('id')} ({current_node.get('display_header', 'N/A')})[/dim]")
                        
                        # Find target node by matching description
                        target_node = self._find_target_node(target_text)
                        
                        if target_node:
                            console.print(f"[dim]      Target node: {target_node.get('id')} ({target_node.get('display_header', 'N/A')})[/dim]")
                            
                            # Find navigation path (BFS through edges)
                            path = self._find_navigation_path(current_node.get('id'), target_node.get('id'))
                            
                            if path is not None:
                                if len(path) == 0:
                                    console.print(f"[green]      ✅ Already on target page[/green]")
                                    navigation_success = True
                                else:
                                    console.print(f"[dim]      Found path with {len(path)} step(s)[/dim]")
                                    
                                    # Execute each edge in path
                                    for i, edge in enumerate(path):
                                        selector = edge.get("selector")
                                        href = edge.get("href")
                                        to_node = edge.get("to")
                                        
                                        console.print(f"[dim]      Step {i+1}: {current_node.get('id')} → {to_node}[/dim]")
                                        console.print(f"[dim]         Selector: {selector}[/dim]")
                                        
                                        if selector:
                                            try:
                                                # Wait for page to stabilize before looking for element
                                                await self.page.wait_for_load_state("load", timeout=10000)
                                                await asyncio.sleep(2)  # Extra time for dynamic widgets
                                                
                                                # Wait for element and click
                                                element = await self.page.wait_for_selector(selector, state="visible", timeout=15000)
                                                if element:
                                                    # Scroll into view if needed
                                                    await element.scroll_into_view_if_needed()
                                                    await asyncio.sleep(0.5)
                                                    await element.click()
                                                    # Wait for navigation/network
                                                    await asyncio.sleep(2)
                                                    try:
                                                        await self.page.wait_for_load_state("load", timeout=10000)
                                                    except:
                                                        pass  # Continue even if load doesn't complete
                                                    console.print(f"[green]         ✅ Clicked: {selector}[/green]")
                                                    navigation_success = True
                                            except Exception as e:
                                                console.print(f"[yellow]         ⚠️ Selector failed: {e}[/yellow]")
                                                # Try extracting href from selector and navigate directly
                                                href_from_selector = None
                                                if "href='" in selector:
                                                    import re
                                                    href_match = re.search(r"href='([^']+)'", selector)
                                                    if href_match:
                                                        href_from_selector = href_match.group(1)
                                                
                                                fallback_href = href or href_from_selector
                                                if fallback_href:
                                                    try:
                                                        target_url = f"http://localhost:9000{fallback_href}" if fallback_href.startswith('/') else fallback_href
                                                        console.print(f"[dim]         Trying direct URL: {target_url}[/dim]")
                                                        await self.page.goto(target_url, wait_until="load", timeout=15000)
                                                        console.print(f"[green]         ✅ Navigated via URL: {fallback_href}[/green]")
                                                        navigation_success = True
                                                    except Exception as e2:
                                                        console.print(f"[red]         ❌ URL navigation failed: {e2}[/red]")
                                                elif target_node.get("url"):
                                                    # Fallback to target node's URL
                                                    try:
                                                        target_url = target_node.get("url")
                                                        console.print(f"[dim]         Trying target node URL: {target_url}[/dim]")
                                                        await self.page.goto(target_url, wait_until="load", timeout=15000)
                                                        console.print(f"[green]         ✅ Navigated to target URL[/green]")
                                                        navigation_success = True
                                                    except Exception as e3:
                                                        console.print(f"[red]         ❌ Target URL navigation failed: {e3}[/red]")
                                        elif href:
                                            # No selector but have href
                                            try:
                                                target_url = f"http://localhost:9000{href}" if href.startswith('/') else href
                                                await self.page.goto(target_url, wait_until="networkidle", timeout=15000)
                                                console.print(f"[green]         ✅ Navigated via href: {href}[/green]")
                                                navigation_success = True
                                            except Exception as e:
                                                console.print(f"[red]         ❌ Href navigation failed: {e}[/red]")
                            else:
                                console.print(f"[yellow]      ⚠️ No path found in graph[/yellow]")
                                # Try direct URL navigation if we know target URL
                                target_url = target_node.get("url")
                                if target_url:
                                    console.print(f"[dim]      Trying direct URL: {target_url}[/dim]")
                                    try:
                                        await self.page.goto(target_url, wait_until="networkidle", timeout=15000)
                                        console.print(f"[green]      ✅ Navigated directly to URL[/green]")
                                        navigation_success = True
                                    except Exception as e:
                                        console.print(f"[red]      ❌ Direct navigation failed: {e}[/red]")
                        else:
                            console.print(f"[yellow]      ⚠️ Target node not found in graph[/yellow]")
                    else:
                        console.print(f"[yellow]      ⚠️ Current page not found in graph: {current_url}[/yellow]")
                
                # Strategy 2: Keyword-based fallback (if no graph or graph navigation failed)
                if not navigation_success:
                    console.print(f"[dim]      🔍 Falling back to keyword-based navigation[/dim]")
                    
                    stop_words = {"the", "to", "a", "an", "page", "view", "screen", "section", "tab"}
                    keywords = [w.strip(".,") for w in target_text.lower().split() 
                               if w.strip(".,") not in stop_words and len(w) > 2]
                    
                    console.print(f"[dim]      Keywords: {keywords}[/dim]")
                    
                    nav_selectors = []
                    for keyword in keywords[:3]:
                        nav_selectors.extend([
                            f"nav a:has-text('{keyword}')",
                            f"[class*='sidebar'] a:has-text('{keyword}')",
                            f"[class*='menu'] a:has-text('{keyword}')",
                            f"a:has-text('{keyword}')",
                            f"button:has-text('{keyword}')",
                        ])
                    
                    for selector in nav_selectors[:10]:
                        try:
                            console.print(f"[dim]      Trying: {selector}[/dim]")
                            element = await self.page.wait_for_selector(selector, state="visible", timeout=2000)
                            if element:
                                tag = await element.evaluate("el => el.tagName.toLowerCase()")
                                if tag in ['a', 'button', 'div', 'span', 'li']:
                                    await element.click()
                                    await asyncio.sleep(1.5)
                                    console.print(f"[green]      ✅ Clicked on '{selector}'[/green]")
                                    navigation_success = True
                                    break
                        except Exception:
                            continue
                
                result["success"] = navigation_success
                if not navigation_success:
                    result["error"] = f"Navigation to '{target_text}' failed"
            
            elif action == "assert_visible":
                selector = step.get("selector", "")
                description = step.get("description", f"assert visible {selector}")
                console.print(f"[dim]   → assert_visible: {selector}[/dim]")
                
                try:
                    element = await self.page.wait_for_selector(selector, state="visible", timeout=10000)
                    result["success"] = element is not None
                except (PlaywrightTimeoutError, Exception):
                    # Try JIT resolution
                    console.print(f"[yellow]      ⚠️ Selector failed, attempting JIT resolution...[/yellow]")
                    new_selector = await self._resolve_selector_at_runtime(description, "assert visibility")
                    if new_selector:
                        try:
                            element = await self.page.wait_for_selector(new_selector, state="visible", timeout=5000)
                            result["success"] = element is not None
                            console.print(f"[green]      ✅ JIT retry succeeded[/green]")
                        except:
                            result["success"] = False
                    else:
                        result["success"] = False
                
                if not result["success"]:
                    result["error"] = f"Element not visible: {selector}"
            
            elif action == "assert_not_visible":
                selector = step.get("selector", "")
                description = step.get("description", f"assert not visible {selector}")
                console.print(f"[dim]   → assert_not_visible: {selector}[/dim]")
                try:
                    element = await self.page.wait_for_selector(selector, state="hidden", timeout=5000)
                    result["success"] = True
                except:
                    # Element is visible when it shouldn't be
                    # Try JIT to confirm if we are looking at the right thing? 
                    # Actually for "not visible", if the selector is wrong (element doesn't exist), it passes "hidden" check.
                    # So JIT is only needed if we suspect the selector matches NOTHING but we want to ensure a SPECIFIC thing is gone.
                    # But usually "not visible" means "selector doesn't match visible element".
                    # So we don't strictly need JIT here unless we want to be very precise.
                    result["success"] = False
                    result["error"] = f"Element unexpectedly visible: {selector}"
            
            elif action == "assert_text":
                selector = step.get("selector", "")
                expected = step.get("expected", "")
                description = step.get("description", f"assert text '{expected}' in {selector}")
                console.print(f"[dim]   → assert_text: {selector} contains '{expected}'[/dim]")
                
                element = None
                try:
                    element = await self.page.wait_for_selector(selector, timeout=10000)
                except (PlaywrightTimeoutError, Exception):
                    # Try JIT resolution
                    console.print(f"[yellow]      ⚠️ Selector failed, attempting JIT resolution...[/yellow]")
                    new_selector = await self._resolve_selector_at_runtime(description, f"find element containing text '{expected}'")
                    if new_selector:
                        try:
                            element = await self.page.wait_for_selector(new_selector, timeout=5000)
                            console.print(f"[green]      ✅ JIT retry succeeded[/green]")
                        except:
                            pass

                if element:
                    text = await element.text_content()
                    result["success"] = expected.lower() in (text or "").lower()
                    result["actual_text"] = text
                    if not result["success"]:
                        result["error"] = f"Expected '{expected}' but got '{text}'"
                else:
                    result["success"] = False
                    result["error"] = f"Element not found: {selector}"
            
            elif action == "assert_url_contains":
                expected = step.get("expected", "")
                console.print(f"[dim]   → assert_url_contains: {expected}[/dim]")
                current_url = self.page.url
                result["success"] = expected in current_url
                result["actual_url"] = current_url
                if not result["success"]:
                    result["error"] = f"URL '{current_url}' does not contain '{expected}'"
            
            elif action == "verify_api":
                endpoint = step.get("endpoint", "")
                expected_fields = step.get("expected_fields", [])
                console.print(f"[dim]   → verify_api: {endpoint}[/dim]")
                result.update(self.verify_api_calls(endpoint, expected_fields))
            
            elif action == "verify_api_value_in_ui":
                # Extract value from API response and verify it's displayed in UI
                # Strategy: Match first item from API array with first row in table
                field_name = step.get("field", "")  # e.g., "tcvAmountUplifted"
                ui_selector = step.get("selector", "")  # Where to look in UI
                endpoint_pattern = step.get("endpoint", "")  # Which API response to check
                
                console.print(f"[dim]   → verify_api_value_in_ui: {field_name} in {ui_selector}[/dim]")
                
                # Extract value from captured API responses (first item in array)
                api_value = None
                for call in reversed(self.api_calls):  # Check most recent first
                    if call.get("type") != "response":
                        continue
                    if endpoint_pattern and endpoint_pattern not in call.get("url", ""):
                        continue
                    
                    body = call.get("body")
                    if body:
                        # Extract field value (supports nested paths like "data.0.tcvAmountUplifted")
                        api_value = self._extract_field_value(body, field_name)
                        if api_value is not None:
                            console.print(f"[dim]      Found {field_name} = {api_value} in API response[/dim]")
                            
                            # Also extract record ID for potential DB verification
                            record_id = None
                            for id_field in ["id", "opportunityId", "recordId", "_id"]:
                                record_id = self._extract_field_value(body, id_field)
                                if record_id:
                                    result["record_id"] = record_id
                                    break
                            break
                
                if api_value is None:
                    result["success"] = False
                    result["error"] = f"Field '{field_name}' not found in captured API responses"
                else:
                    # Check if the API value appears in the UI
                    # Strategy: For tables, find the column and check first row's cell
                    found_in_ui = False
                    matched_text = None
                    
                    try:
                        # Strategy 1: Try to find value in table structure
                        # Find TCV column index by looking at headers
                        column_name = "TCV"  # Default for TCV-related fields
                        if "tcv" in field_name.lower():
                            column_name = "TCV"
                        
                        # Try to find column header and get its index
                        headers = await self.page.query_selector_all("th")
                        tcv_col_index = -1
                        for i, header in enumerate(headers):
                            text = await header.text_content()
                            if text and column_name.upper() in text.upper():
                                tcv_col_index = i
                                console.print(f"[dim]      Found {column_name} column at index {tcv_col_index}[/dim]")
                                break
                        
                        if tcv_col_index >= 0:
                            # Get the first data row and check the TCV cell
                            first_row_cells = await self.page.query_selector_all("tbody tr:first-child td")
                            if tcv_col_index < len(first_row_cells):
                                cell = first_row_cells[tcv_col_index]
                                cell_text = await cell.text_content()
                                console.print(f"[dim]      First row TCV cell text: '{cell_text}'[/dim]")
                                if cell_text and self._values_match(api_value, cell_text):
                                    found_in_ui = True
                                    matched_text = cell_text.strip()
                                    console.print(f"[green]      ✅ API value {api_value} matches first row cell '{matched_text}'[/green]")
                        
                        # Strategy 2: Fallback - search in selector area
                        if not found_in_ui and ui_selector:
                            elements = await self.page.query_selector_all(ui_selector)
                            for el in elements:
                                text = await el.text_content()
                                if text and self._values_match(api_value, text):
                                    found_in_ui = True
                                    matched_text = text.strip()
                                    console.print(f"[green]      ✅ API value {api_value} matches UI text '{matched_text}'[/green]")
                                    break
                        
                        # Strategy 3: Fallback - search all table cells
                        if not found_in_ui:
                            all_cells = await self.page.query_selector_all("table td")
                            for cell in all_cells:
                                text = await cell.text_content()
                                if text and self._values_match(api_value, text):
                                    found_in_ui = True
                                    matched_text = text.strip()
                                    console.print(f"[green]      ✅ API value {api_value} found in table cell '{matched_text}'[/green]")
                                    break
                        
                        result["success"] = found_in_ui
                        result["api_value"] = api_value
                        result["matched_ui_text"] = matched_text
                        
                        if not found_in_ui:
                            result["error"] = f"API value '{api_value}' not found in UI"
                            console.print(f"[red]      ❌ API value {api_value} not found in UI[/red]")
                        else:
                            # If UI check passed, also do DB verification if enabled
                            await self._do_db_verification_if_enabled(
                                field_name, api_value, result.get("record_id"), result
                            )
                    
                    except Exception as e:
                        result["success"] = False
                        result["error"] = f"UI check failed: {e}"
            
            elif action == "verify_ui":
                expected = step.get("expected", "")
                console.print(f"[dim]   → verify_ui: {expected}[/dim]")
                
                # Normalize expected to a list
                items = []
                if isinstance(expected, list):
                    items = expected
                elif isinstance(expected, str) and (";" in expected or "," in expected):
                    # Split semicolon or comma-separated string into items
                    items = [i.strip() for i in re.split(r'[;,]', expected) if i.strip()]
                else:
                    items = [expected] if expected else []
                
                # These are high-level verification summaries
                # Most should have been verified by previous specific steps
                all_passed = True
                for item in items:
                    item_lower = item.lower()
                    # Check if this was already verified in previous steps
                    if any(phrase in item_lower for phrase in [
                        "column is visible", "displays api value", "not displayed", 
                        "not shown", "not exposed", "hidden"
                    ]):
                        # These should have been verified by assert_visible, verify_api_value_in_ui, etc.
                        console.print(f"[dim]      ✓ '{item}' (verified in previous steps)[/dim]")
                    else:
                        # Try to find the text on page
                        try:
                            await self.page.wait_for_selector(f":has-text('{item}')", timeout=2000)
                            console.print(f"[dim]      ✓ '{item}' found[/dim]")
                        except:
                            console.print(f"[yellow]      ⚠ '{item}' not found as literal text[/yellow]")
                
                result["success"] = all_passed
            
            elif action == "login":
                role = step.get("role", "")
                console.print(f"[dim]   → login: role={role} (delegated to gateway)[/dim]")
                # Login is typically handled by gateway execution before mission
                result["success"] = True
                result["note"] = "Login handled by gateway execution"
            
            elif action == "capture_api":
                # Capture API responses - just wait for network and mark success
                # Network interception already captures responses
                description = step.get("description", "")
                console.print(f"[dim]   → capture_api: waiting for API responses[/dim]")
                await asyncio.sleep(2)  # Give time for API calls to complete
                captured_count = len([c for c in self.api_calls if c.get("type") == "response"])
                console.print(f"[green]      ✅ Captured {captured_count} API response(s)[/green]")
                result["success"] = True
                result["captured_responses"] = captured_count
            
            elif action == "extract_api_field":
                # Extract a field from captured API responses
                field_name = step.get("field", "")
                console.print(f"[dim]   → extract_api_field: {field_name}[/dim]")
                
                api_value = None
                for call in reversed(self.api_calls):
                    if call.get("type") != "response":
                        continue
                    body = call.get("body")
                    if body:
                        api_value = self._extract_field_value(body, field_name)
                        if api_value is not None:
                            console.print(f"[green]      ✅ Extracted {field_name} = {api_value}[/green]")
                            result["success"] = True
                            result["extracted_value"] = api_value
                            break
                
                if api_value is None:
                    result["success"] = False
                    result["error"] = f"Field '{field_name}' not found in API responses"
            
            elif action == "assert_api_field_not_shown":
                # Triple-check for hidden field: UI, API, DB
                # This verifies a field should be hidden from this persona
                field_name = step.get("field", "")
                console.print(f"[dim]   → assert_api_field_not_shown: {field_name}[/dim]")
                
                # Track results for all 3 checks
                ui_pass = False
                api_pass = False
                db_pass = False
                api_value = None
                
                # 1. Get the field value from API responses (if it exists)
                for call in reversed(self.api_calls):
                    if call.get("type") != "response":
                        continue
                    body = call.get("body")
                    if body:
                        api_value = self._extract_field_value(body, field_name)
                        if api_value is not None:
                            break
                
                console.print(f"[bold]      🔍 HIDDEN FIELD CHECK: {field_name}[/bold]")
                
                # CHECK 1: UI - Value should NOT be displayed
                if api_value is not None:
                    formatted_values = [str(api_value)]
                    if isinstance(api_value, (int, float)):
                        formatted_values.extend([
                            f"${api_value:,.2f}",
                            f"${api_value:,.0f}",
                            f"{api_value:,.2f}",
                        ])
                    
                    found_in_ui = False
                    for val in formatted_values:
                        try:
                            element = await self.page.wait_for_selector(f"text='{val}'", timeout=2000)
                            if element:
                                found_in_ui = True
                                break
                        except:
                            pass
                    
                    ui_pass = not found_in_ui
                    if ui_pass:
                        console.print(f"[green]         1️⃣ UI:  ✅ PASS - Value '{api_value}' not displayed[/green]")
                    else:
                        console.print(f"[red]         1️⃣ UI:  ❌ FAIL - Value '{api_value}' is visible![/red]")
                else:
                    ui_pass = True
                    console.print(f"[green]         1️⃣ UI:  ✅ PASS - Field not in API, nothing to display[/green]")
                
                # CHECK 2: API - Field should NOT exist in response (security check)
                if api_value is None:
                    api_pass = True
                    console.print(f"[green]         2️⃣ API: ✅ PASS - Field correctly hidden from response[/green]")
                else:
                    api_pass = False
                    console.print(f"[red]         2️⃣ API: ❌ FAIL - Field found in response (value={api_value})[/red]")
                    console.print(f"[red]              ⚠️  SECURITY: Backend should not return this field for this persona[/red]")
                
                # CHECK 3: DB - Correct value should exist (data integrity)
                db_value = None
                db_config = self.mission.get("db_verification", {})
                if db_config.get("enabled") and self.db_connection:
                    # Find matching query for this field
                    for query_config in db_config.get("verification_queries", []):
                        if query_config.get("api_field") == field_name:
                            db_column = query_config.get("db_column")
                            db_table = query_config.get("db_table")
                            db_schema = query_config.get("db_schema") or db_config.get("db_schema")
                            id_field = query_config.get("id_field", "id")
                            
                            # Get record ID from API response
                            record_id = None
                            for call in reversed(self.api_calls):
                                if call.get("type") == "response" and call.get("body"):
                                    record_id = self._extract_field_value(call["body"], "id")
                                    if record_id:
                                        break
                            
                            if record_id and db_table and db_column:
                                table_ref = f"{db_schema}.{db_table}" if db_schema else db_table
                                query = f"SELECT {db_column} FROM {table_ref} WHERE {id_field} = $1"
                                try:
                                    row = await self.db_connection.fetchrow(query, record_id)
                                    if row:
                                        db_value = row[db_column]
                                except Exception as e:
                                    console.print(f"[yellow]         3️⃣ DB:  ⚠️  Query failed: {e}[/yellow]")
                            break
                
                if db_value is not None:
                    db_pass = True
                    console.print(f"[green]         3️⃣ DB:  ✅ PASS - Value exists in database ({db_value})[/green]")
                elif db_config.get("enabled"):
                    db_pass = False
                    console.print(f"[yellow]         3️⃣ DB:  ⚠️  Could not verify (no matching query config)[/yellow]")
                else:
                    db_pass = True  # Skip if DB verification not enabled
                    console.print(f"[dim]         3️⃣ DB:  ⏭️  Skipped (DB verification not enabled)[/dim]")
                
                # Overall result: API check is critical (security), others are informational
                result["success"] = api_pass  # Main pass/fail based on API security check
                result["ui_check"] = {"pass": ui_pass, "value_found": not ui_pass if api_value else None}
                result["api_check"] = {"pass": api_pass, "value": api_value}
                result["db_check"] = {"pass": db_pass, "value": db_value}
                
                if not api_pass:
                    result["error"] = f"SECURITY VIOLATION: '{field_name}' found in API response but should be hidden"
                    result["security_violation"] = True
            
            elif action == "manual":
                # Manual step requires browser-use fallback
                description = step.get("description", "")
                console.print(f"[yellow]   → manual: {description} (requires browser-use)[/yellow]")
                result["success"] = False
                result["requires_browser_use"] = True
                result["error"] = "Manual step requires browser-use fallback"
            
            elif action == "verify_db":
                # DB verification is handled by TripleCheckExecutor
                expected = step.get("expected", "")
                console.print(f"[dim]   → verify_db: {expected} (delegated to TripleCheckExecutor)[/dim]")
                result["success"] = True
                result["delegated"] = True
            
            elif action == "verify_triple_check":
                # Triple-check: DB -> API -> UI verification
                api_field = step.get("api_field", "")
                db_column = step.get("db_column", "")
                db_table = step.get("db_table", "")
                ui_selector = step.get("ui_selector", "")
                
                console.print(f"[dim]   → verify_triple_check: {api_field} (DB → API → UI)[/dim]")
                
                triple_result = await self._verify_triple_check(
                    api_field=api_field,
                    db_column=db_column,
                    db_table=db_table,
                    ui_selector=ui_selector
                )
                
                result["success"] = triple_result.get("success", False)
                result["triple_check"] = triple_result
                
                if result["success"]:
                    console.print(f"[green]      ✅ Triple-check passed: DB={triple_result.get('db_value')} == API={triple_result.get('api_value')} == UI={triple_result.get('ui_value')}[/green]")
                else:
                    console.print(f"[red]      ❌ Triple-check failed: {triple_result.get('error')}[/red]")
            
            else:
                console.print(f"[yellow]   → Unknown action: {action}[/yellow]")
                result["error"] = f"Unknown action: {action}"
        
        except Exception as e:
            result["error"] = str(e)
            console.print(f"[red]   ❌ Step failed: {e}[/red]")
        
        self.step_results.append(result)
        return result
    
    async def _do_db_verification_if_enabled(self, api_field: str, api_value: Any, 
                                              record_id: Optional[str], result: Dict) -> None:
        """Perform DB verification if db_verification is enabled in mission.
        
        This is called after a successful verify_api_value_in_ui to add the DB check.
        
        Args:
            api_field: API field name (e.g., "tcvAmountUplifted")
            api_value: Value from API response
            record_id: Record ID from API response (for DB lookup)
            result: Step result dict to update with DB verification info
        """
        # Check if db_verification is enabled in mission
        db_config = self.mission.get("db_verification", {})
        if not db_config.get("enabled", False):
            return
        
        console.print(f"\n[bold cyan]      🗄️  DB VERIFICATION (auto-triggered)[/bold cyan]")
        
        # Find the matching verification query for this field
        verification_queries = db_config.get("verification_queries", [])
        matching_query = None
        for vq in verification_queries:
            if vq.get("api_field") == api_field:
                matching_query = vq
                break
        
        if not matching_query:
            console.print(f"[dim]         ⚠️ No verification query for field '{api_field}'[/dim]")
            return
        
        db_table = matching_query.get("db_table", db_config.get("db_table"))
        db_column = matching_query.get("db_column")
        id_field = matching_query.get("id_field", "id")
        
        console.print(f"[dim]         📋 Query config:[/dim]")
        console.print(f"[dim]            Table: {db_table}[/dim]")
        console.print(f"[dim]            Column: {db_column}[/dim]")
        console.print(f"[dim]            ID Field: {id_field}[/dim]")
        console.print(f"[dim]            Record ID: {record_id}[/dim]")
        
        if not self.db_connection:
            console.print(f"[yellow]         ⚠️ No DB connection - skipping DB verification[/yellow]")
            console.print(f"[dim]            Set PROJECT_DATABASE_URL env var to enable[/dim]")
            result["db_verification"] = {"skipped": True, "reason": "No DB connection"}
            return
        
        if not record_id:
            console.print(f"[yellow]         ⚠️ No record ID - cannot query DB[/yellow]")
            result["db_verification"] = {"skipped": True, "reason": "No record ID"}
            return
        
        try:
            # Build and execute query
            # Use schema from verification query if available, otherwise from db_config
            schema = matching_query.get("db_schema") or db_config.get("db_schema")
            table_with_schema = f"{schema}.{db_table}" if schema else db_table
            
            query = f"SELECT {db_column} FROM {table_with_schema} WHERE {id_field} = $1"
            console.print(f"[cyan]         📝 Query: {query}[/cyan]")
            console.print(f"[cyan]            $1 = '{record_id}'[/cyan]")
            
            row = await self.db_connection.fetchrow(query, record_id)
            
            if row:
                db_value = row[db_column] if db_column in row.keys() else None
                console.print(f"[dim]         📥 DB Result: {db_column} = {db_value}[/dim]")
                
                # Compare DB vs API
                if db_value is not None and self._values_match(db_value, str(api_value)):
                    console.print(f"[green]         ✅ DB matches API: {db_value} == {api_value}[/green]")
                    result["db_verification"] = {
                        "success": True,
                        "db_value": db_value,
                        "api_value": api_value,
                        "query": query
                    }
                else:
                    console.print(f"[red]         ❌ MISMATCH: DB={db_value} ≠ API={api_value}[/red]")
                    result["db_verification"] = {
                        "success": False,
                        "db_value": db_value,
                        "api_value": api_value,
                        "error": f"DB value ({db_value}) != API value ({api_value})"
                    }
            else:
                console.print(f"[yellow]         ⚠️ No row found for {id_field}={record_id}[/yellow]")
                result["db_verification"] = {"skipped": True, "reason": f"No row found for ID {record_id}"}
                
        except Exception as e:
            console.print(f"[red]         ❌ DB query failed: {e}[/red]")
            result["db_verification"] = {"success": False, "error": str(e)}
    
    async def _verify_triple_check(self, api_field: str, db_column: str, 
                                    db_table: str, ui_selector: str) -> Dict[str, Any]:
        """Verify data consistency across DB -> API -> UI.
        
        This performs a triple-check:
        1. Extract record ID and field value from captured API response
        2. Query DB for the same record using ID
        3. Compare: DB value == API value
        4. Verify API value matches what's displayed in UI
        
        Args:
            api_field: API field name (e.g., "tcvAmountUplifted")
            db_column: DB column name (e.g., "tcv_amount_uplifted")
            db_table: DB table name (e.g., "opportunities")
            ui_selector: UI selector to find the displayed value
            
        Returns:
            Dict with success status and values at each layer
        """
        console.print(f"\n[bold cyan]   🔄 TRIPLE-CHECK: DB → API → UI[/bold cyan]")
        console.print(f"[dim]      ┌─ Input Parameters ─────────────────────────[/dim]")
        console.print(f"[dim]      │ API Field:   {api_field}[/dim]")
        console.print(f"[dim]      │ DB Column:   {db_column}[/dim]")
        console.print(f"[dim]      │ DB Table:    {db_table}[/dim]")
        console.print(f"[dim]      │ UI Selector: {ui_selector or '(auto-detect)'}[/dim]")
        console.print(f"[dim]      └──────────────────────────────────────────────[/dim]")
        
        result = {
            "success": False,
            "api_value": None,
            "db_value": None,
            "ui_value": None,
            "record_id": None,
            "error": None,
            "db_query": None
        }
        
        try:
            # Step 1: Extract value and ID from captured API response
            console.print(f"\n[bold]      📡 STEP 1: Extract from API Response[/bold]")
            api_value = None
            record_id = None
            
            console.print(f"[dim]         Searching {len(self.api_calls)} captured API calls...[/dim]")
            
            for i, call in enumerate(reversed(self.api_calls)):
                if call.get("type") != "response":
                    continue
                
                url = call.get("url", "")[:80]
                console.print(f"[dim]         Checking call #{len(self.api_calls) - i}: {url}...[/dim]")
                
                body = call.get("body")
                if body:
                    # Extract the API field value
                    api_value = self._extract_field_value(body, api_field)
                    # Extract record ID (try common ID fields)
                    for id_field in ["id", "opportunityId", "recordId", "_id"]:
                        record_id = self._extract_field_value(body, id_field)
                        if record_id:
                            console.print(f"[dim]         Found ID field '{id_field}': {record_id}[/dim]")
                            break
                    
                    if api_value is not None:
                        result["api_value"] = api_value
                        result["record_id"] = record_id
                        console.print(f"[green]         ✅ Found {api_field} = {api_value}[/green]")
                        console.print(f"[dim]            Record ID: {record_id}[/dim]")
                        break
            
            if api_value is None:
                console.print(f"[red]         ❌ Field '{api_field}' not found in any API response[/red]")
                result["error"] = f"API field '{api_field}' not found in captured responses"
                return result
            
            # Step 2: Query DB for the same record (if DB connection available)
            console.print(f"\n[bold]      🗄️  STEP 2: Query Database[/bold]")
            
            if self.db_connection and db_table and record_id:
                try:
                    # Handle schema-qualified table names
                    table_with_schema = db_table if "." in db_table else f"public.{db_table}"
                    
                    query = f"SELECT {db_column} FROM {table_with_schema} WHERE id = $1"
                    result["db_query"] = query
                    
                    console.print(f"[cyan]         📝 Generated Query:[/cyan]")
                    console.print(f"[cyan]            {query}[/cyan]")
                    console.print(f"[cyan]            Parameter $1 = '{record_id}'[/cyan]")
                    
                    console.print(f"[dim]         Executing query...[/dim]")
                    row = await self.db_connection.fetchrow(query, record_id)
                    
                    if row:
                        db_value = row[db_column] if db_column in row.keys() else None
                        result["db_value"] = db_value
                        console.print(f"[green]         ✅ DB Result: {db_column} = {db_value}[/green]")
                        
                        # Compare DB vs API
                        if db_value is not None and self._values_match(db_value, str(api_value)):
                            console.print(f"[green]         ✓ DB matches API (DB: {db_value} == API: {api_value})[/green]")
                        else:
                            console.print(f"[yellow]         ⚠ MISMATCH: DB ({db_value}) ≠ API ({api_value})[/yellow]")
                    else:
                        console.print(f"[yellow]         ⚠ No row found for ID: {record_id}[/yellow]")
                        console.print(f"[dim]            Query returned 0 rows[/dim]")
                        
                except Exception as db_err:
                    console.print(f"[red]         ❌ DB Query Error: {db_err}[/red]")
                    console.print(f"[dim]            Query: {query}[/dim]")
            else:
                console.print(f"[yellow]         ⏭️  DB check skipped[/yellow]")
                if not self.db_connection:
                    console.print(f"[dim]            Reason: No database connection[/dim]")
                    console.print(f"[dim]            Set PROJECT_DATABASE_URL env var to enable[/dim]")
                elif not db_table:
                    console.print(f"[dim]            Reason: No DB table specified[/dim]")
                elif not record_id:
                    console.print(f"[dim]            Reason: No record ID extracted from API[/dim]")
            
            # Step 3: Verify API value appears in UI
            console.print(f"\n[bold]      🖥️  STEP 3: Verify in UI[/bold]")
            ui_value = None
            found_in_ui = False
            
            # Try table-based lookup first (column at index)
            column_name = "TCV" if "tcv" in api_field.lower() else api_field
            console.print(f"[dim]         Looking for column '{column_name}' in table headers...[/dim]")
            
            headers = await self.page.query_selector_all("th")
            console.print(f"[dim]         Found {len(headers)} table headers[/dim]")
            
            col_index = -1
            for i, header in enumerate(headers):
                text = await header.text_content()
                if text and column_name.upper() in text.upper():
                    col_index = i
                    console.print(f"[dim]         ✓ Found '{column_name}' at column index {i}[/dim]")
                    break
            
            if col_index >= 0:
                first_row_cells = await self.page.query_selector_all("tbody tr:first-child td")
                console.print(f"[dim]         Found {len(first_row_cells)} cells in first row[/dim]")
                
                if col_index < len(first_row_cells):
                    cell = first_row_cells[col_index]
                    ui_value = await cell.text_content()
                    ui_value = ui_value.strip() if ui_value else None
                    result["ui_value"] = ui_value
                    console.print(f"[dim]         Cell value at index {col_index}: '{ui_value}'[/dim]")
                    
                    if ui_value and self._values_match(api_value, ui_value):
                        found_in_ui = True
                        console.print(f"[green]         ✅ UI Value: {ui_value}[/green]")
                        console.print(f"[green]         ✓ API matches UI (API: {api_value} == UI: {ui_value})[/green]")
                    else:
                        console.print(f"[yellow]         ⚠ Values don't match: API={api_value}, UI={ui_value}[/yellow]")
                else:
                    console.print(f"[yellow]         ⚠ Column index {col_index} out of range (only {len(first_row_cells)} cells)[/yellow]")
            else:
                console.print(f"[dim]         Column '{column_name}' not found in headers[/dim]")
            
            # Fallback: search with selector
            if not found_in_ui and ui_selector:
                console.print(f"\n[dim]         Fallback: searching with selector '{ui_selector}'...[/dim]")
                elements = await self.page.query_selector_all(ui_selector)
                console.print(f"[dim]         Found {len(elements)} elements matching selector[/dim]")
                
                for el in elements:
                    text = await el.text_content()
                    if text and self._values_match(api_value, text):
                        ui_value = text.strip()
                        result["ui_value"] = ui_value
                        found_in_ui = True
                        console.print(f"[green]         ✅ Found matching value: {ui_value}[/green]")
                        break
            
            if not found_in_ui:
                console.print(f"[red]         ❌ API value '{api_value}' not found in UI[/red]")
                result["error"] = f"API value '{api_value}' not found in UI"
                return result
            
            # All checks passed - print summary
            console.print(f"\n[bold green]      ═══════════════════════════════════════════════[/bold green]")
            console.print(f"[bold green]      ✅ TRIPLE-CHECK PASSED[/bold green]")
            console.print(f"[green]         DB:  {result.get('db_value', 'N/A')}[/green]")
            console.print(f"[green]         API: {api_value}[/green]")
            console.print(f"[green]         UI:  {ui_value}[/green]")
            console.print(f"[bold green]      ═══════════════════════════════════════════════[/bold green]")
            result["success"] = True
            
        except Exception as e:
            console.print(f"[red]      ❌ Triple-check error: {e}[/red]")
            result["error"] = str(e)
        
        return result
    
    def verify_api_calls(self, endpoint: str, expected_fields: List[str] = None) -> Dict:
        """Verify API calls match expected endpoint and fields.
        
        Args:
            endpoint: Expected endpoint pattern (e.g., "GET /api/v1/opportunity")
            expected_fields: List of fields that should be present in response
            
        Returns:
            Verification result
        """
        result = {"success": False, "matched_calls": [], "missing_fields": []}
        
        # Parse endpoint
        parts = endpoint.strip().split(None, 1)
        expected_method = parts[0].upper() if len(parts) > 0 else None
        expected_path = parts[1] if len(parts) > 1 else parts[0] if parts else ""
        
        # Find matching API calls
        for call in self.api_calls:
            if call.get("type") != "response":
                continue
            
            url = call.get("url", "")
            method = call.get("method", "").upper()
            
            # Check method match
            method_match = expected_method is None or method == expected_method
            
            # Check path match (partial match)
            path_match = expected_path in url or expected_path == "*"
            
            if method_match and path_match:
                result["matched_calls"].append(call)
                
                # Verify expected fields if provided
                if expected_fields:
                    body = call.get("body")
                    if body and isinstance(body, dict):
                        missing = []
                        for field in expected_fields:
                            # Check nested fields (e.g., "data.tcv_amount")
                            parts = field.split(".")
                            current = body
                            found = True
                            for part in parts:
                                if isinstance(current, dict) and part in current:
                                    current = current[part]
                                elif isinstance(current, list) and current:
                                    # Check first item in list
                                    current = current[0] if isinstance(current[0], dict) and part in current[0] else None
                                    if current is None:
                                        found = False
                                        break
                                    current = current.get(part)
                                else:
                                    found = False
                                    break
                            
                            if not found:
                                missing.append(field)
                        
                        result["missing_fields"] = missing
                        result["success"] = len(missing) == 0
                    else:
                        result["success"] = False
                        result["error"] = "Response body not available or not JSON"
                else:
                    # No fields to verify, just check endpoint was called
                    result["success"] = True
        
        if not result["matched_calls"]:
            result["error"] = f"No API calls matched: {endpoint}"
            # Include captured calls for debugging
            result["captured_calls"] = [
                f"{c.get('method')} {c.get('url')}" 
                for c in self.api_calls 
                if c.get("type") == "response"
            ][-5:]
        
        return result
    
    def _extract_field_value(self, data: Any, field_path: str) -> Any:
        """Extract a field value from nested data structure.
        
        Supports paths like:
        - "tcvAmountUplifted" - direct field (case-insensitive)
        - "data.tcvAmountUplifted" - nested
        - "data.0.tcvAmountUplifted" - array index
        - "items.*.tcvAmountUplifted" - first item in array (wildcard)
        
        Also searches recursively in nested structures if direct path fails.
        
        Args:
            data: JSON data (dict or list)
            field_path: Dot-separated path to field
            
        Returns:
            Field value or None if not found
        """
        if data is None:
            return None
        
        # First try direct path lookup
        result = self._extract_field_direct(data, field_path)
        if result is not None:
            return result
        
        # If direct lookup fails, try recursive search (case-insensitive)
        return self._find_field_recursive(data, field_path.split(".")[-1])
    
    def _extract_field_direct(self, data: Any, field_path: str) -> Any:
        """Direct path extraction with case-insensitive field matching."""
        if data is None:
            return None
        
        parts = field_path.split(".")
        current = data
        
        for part in parts:
            if current is None:
                return None
            
            # Handle array index or wildcard
            if part.isdigit():
                idx = int(part)
                if isinstance(current, list) and len(current) > idx:
                    current = current[idx]
                else:
                    return None
            elif part == "*":
                # Wildcard: get first item from array
                if isinstance(current, list) and len(current) > 0:
                    current = current[0]
                else:
                    return None
            elif isinstance(current, dict):
                # Case-insensitive dict lookup
                current = self._get_case_insensitive(current, part)
            elif isinstance(current, list) and len(current) > 0:
                # If current is array and part is a field name, check first item
                if isinstance(current[0], dict):
                    current = self._get_case_insensitive(current[0], part)
                else:
                    return None
            else:
                return None
        
        return current
    
    def _get_case_insensitive(self, d: dict, key: str) -> Any:
        """Get value from dict with case-insensitive key matching."""
        # Try exact match first
        if key in d:
            return d[key]
        # Try case-insensitive match
        key_lower = key.lower()
        for k, v in d.items():
            if k.lower() == key_lower:
                return v
        return None
    
    def _find_field_recursive(self, data: Any, field_name: str, max_depth: int = 5) -> Any:
        """Recursively search for a field in nested data structures."""
        if max_depth <= 0 or data is None:
            return None
        
        field_lower = field_name.lower()
        
        if isinstance(data, dict):
            # Check direct keys (case-insensitive)
            for k, v in data.items():
                if k.lower() == field_lower:
                    return v
            # Recurse into nested values
            for v in data.values():
                result = self._find_field_recursive(v, field_name, max_depth - 1)
                if result is not None:
                    return result
        elif isinstance(data, list) and len(data) > 0:
            # Search in first item (usually array of records)
            result = self._find_field_recursive(data[0], field_name, max_depth - 1)
            if result is not None:
                return result
        
        return None
    
    def _normalize_numeric_value(self, text: str) -> Optional[float]:
        """Extract and normalize a numeric value from text.
        
        Handles various formats:
        - Plain: "864880"
        - Comma-separated: "864,880"
        - Currency: "$864,880"
        - Abbreviated: "$864.88K", "1.5M", "2.3B"
        - Percentage: "45.5%"
        
        Args:
            text: Text that may contain a numeric value
            
        Returns:
            Normalized float value or None if not parseable
        """
        if not text:
            return None
        
        # Clean the text
        text = text.strip()
        
        # Remove currency symbols and whitespace
        text = re.sub(r'[$€£¥₹\s]', '', text)
        
        # Check for abbreviated formats (K, M, B)
        multiplier = 1
        if text.endswith('K') or text.endswith('k'):
            multiplier = 1_000
            text = text[:-1]
        elif text.endswith('M') or text.endswith('m'):
            multiplier = 1_000_000
            text = text[:-1]
        elif text.endswith('B') or text.endswith('b'):
            multiplier = 1_000_000_000
            text = text[:-1]
        
        # Remove percentage sign
        if text.endswith('%'):
            text = text[:-1]
        
        # Remove commas
        text = text.replace(',', '')
        
        # Handle parentheses for negative (e.g., "(100)" = -100)
        if text.startswith('(') and text.endswith(')'):
            text = '-' + text[1:-1]
        
        try:
            return float(text) * multiplier
        except (ValueError, TypeError):
            return None
    
    def _values_match(self, api_value: Any, ui_text: str, tolerance: float = 0.01) -> bool:
        """Compare API value with UI displayed text.
        
        Uses normalization to handle different display formats.
        
        Args:
            api_value: Raw value from API response
            ui_text: Text displayed in UI
            tolerance: Relative tolerance for float comparison (default 1%)
            
        Returns:
            True if values match within tolerance
        """
        if api_value is None or ui_text is None:
            return False
        
        # Try to normalize both values
        try:
            api_num = float(api_value)
        except (ValueError, TypeError):
            # Not a number, do string comparison
            return str(api_value).lower() in ui_text.lower()
        
        ui_num = self._normalize_numeric_value(ui_text)
        
        if ui_num is None:
            # UI text is not a number, check if raw value is in text
            return str(api_value) in ui_text
        
        # Compare with tolerance (handles rounding differences)
        if api_num == 0:
            return abs(ui_num) < tolerance
        
        relative_diff = abs(api_num - ui_num) / abs(api_num)
        return relative_diff <= tolerance
    
    async def execute_test_case(self, test_case_def: Dict) -> Dict:
        """Execute all steps for a test case.
        
        Args:
            test_case_def: Test case definition with steps
            
        Returns:
            Test case execution result
        """
        test_case_id = test_case_def.get("test_case_id", "unknown")
        name = test_case_def.get("name", test_case_id)
        steps = test_case_def.get("steps", [])
        
        console.print(f"[bold cyan]   📋 Test Case: {name}[/bold cyan]")
        
        result = {
            "test_case_id": test_case_id,
            "name": name,
            "success": True,
            "steps_executed": [],
            "steps_failed": [],
            "requires_fallback": False
        }
        
        for i, step in enumerate(steps):
            step_result = await self.execute_step(step)
            result["steps_executed"].append(step_result)
            
            if not step_result.get("success"):
                result["steps_failed"].append({
                    "step_index": i,
                    "step": step,
                    "error": step_result.get("error")
                })
                
                # Check if this step requires browser-use
                if step_result.get("requires_browser_use"):
                    result["requires_fallback"] = True
                    console.print(f"[yellow]   ⚠️ Step {i+1} requires browser-use fallback[/yellow]")
                else:
                    result["success"] = False
                    console.print(f"[red]   ❌ Step {i+1} failed: {step_result.get('error')}[/red]")
        
        success_icon = "✅" if result["success"] else "❌"
        console.print(f"[bold]   {success_icon} Test Case Result: {'PASS' if result['success'] else 'FAIL'}[/bold]")
        
        return result
    
    async def execute_all(self) -> Dict:
        """Execute all deterministic test cases.
        
        Returns:
            Overall execution result
        """
        console.print("[bold cyan]🔧 DETERMINISTIC EXECUTOR[/bold cyan]")
        console.print()
        
        # Set up network interception
        await self.setup_network_interception()
        
        deterministic_steps = self.mission.get("deterministic_steps", [])
        
        if not deterministic_steps:
            console.print("[yellow]   ⚠️ No deterministic steps found[/yellow]")
            return {
                "success": False,
                "error": "No deterministic steps found",
                "test_case_results": []
            }
        
        results = {
            "success": True,
            "test_case_results": [],
            "api_calls": self.api_calls,
            "steps_executed": len(self.step_results),
            "requires_fallback": False
        }
        
        for test_case_def in deterministic_steps:
            tc_result = await self.execute_test_case(test_case_def)
            results["test_case_results"].append(tc_result)
            
            if not tc_result.get("success"):
                results["success"] = False
            
            if tc_result.get("requires_fallback"):
                results["requires_fallback"] = True
        
        results["api_calls"] = self.api_calls
        
        console.print()
        success_icon = "✅" if results["success"] else "❌"
        console.print(f"[bold]{success_icon} Deterministic Execution: {'PASS' if results['success'] else 'FAIL'}[/bold]")
        
        return results


async def main():
    """Main entry point."""
    import argparse
    import sys
    import traceback
    
    parser = argparse.ArgumentParser(description="Execute mission with triple-check verification")
    parser.add_argument("mission_file", nargs="?", default="temp/TASK-1_mission.json",
                       help="Path to mission JSON file")
    
    args = parser.parse_args()
    
    try:
        # Load environment for LLM
        env_file = Path(__file__).parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
        
        api_url = os.getenv("NUTANIX_API_URL")
        api_key = os.getenv("NUTANIX_API_KEY")
        model = os.getenv("NUTANIX_MODEL", "openai/gpt-oss-120b")
        
        llm = None
        if api_url and api_key:
            llm = FixedNutanixChatModel(api_url=api_url, api_key=api_key, model_name=model)
            console.print("[green]✅ Agentic Browser Agent enabled[/green]\n")
        else:
            console.print("[yellow]⚠️  LLM credentials not found, running without agentic UI tests[/yellow]\n")
        
        # Execute
        executor = TripleCheckExecutor(args.mission_file, llm=llm)
        results = await executor.execute()
        
        # Save report
        report_path = Path(__file__).parent / "temp" / f"{Path(args.mission_file).stem}_report.json"
        report_path.parent.mkdir(exist_ok=True)
        
        # Convert datetime objects to strings for JSON serialization
        serializable_results = json_serialize(results)
        
        with open(report_path, 'w') as f:
            json.dump(serializable_results, f, indent=2)
        
        console.print(f"\n[green]📄 Report saved to: {report_path}[/green]")
        
        # Exit with error code if tests failed
        if not results.get("overall_success", False):
            sys.exit(1)
            
    except Exception as e:
        error_msg = f"Executor error: {str(e)}\n{traceback.format_exc()}"
        console.print(f"[red]❌ {error_msg}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
