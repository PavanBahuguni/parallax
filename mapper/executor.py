"""Triple-Check Executor - Agentic Browser Architecture

Uses browser-use library for LLM-driven UI test execution.
Performs triple-check verification: DB → API → UI
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
import asyncpg
from playwright.async_api import async_playwright, Page
from rich.console import Console

# Import LLM from context_processor
from context_processor import FixedNutanixChatModel

# Import browser agent
from browser_agent import BrowserAgent

# Force unbuffered output for real-time logging in subprocess
console = Console(force_terminal=True)

def json_serialize(obj: Any) -> Any:
    """Recursively convert datetime objects to strings for JSON serialization."""
    if isinstance(obj, datetime):
        return obj.isoformat()
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
        
        # Load mission
        with open(self.mission_path, 'r') as f:
            self.mission = json.load(f)
    
    async def connect_db(self):
        """Connect to PostgreSQL database."""
        # Load .env for database URL
        env_file = Path(__file__).parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
        
        # Prefer PROJECT_DATABASE_URL from project config, fallback to DATABASE_URL
        db_url = os.getenv("PROJECT_DATABASE_URL") or os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5432/postgres")
        # Convert asyncpg URL to standard format
        if db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        
        try:
            # Parse connection string
            # Format: postgresql://user:pass@host:port/dbname
            self.db_connection = await asyncpg.connect(db_url)
            console.print("[green]✅ Database connected[/green]")
        except Exception as e:
            console.print(f"[red]❌ Database connection failed: {e}[/red]")
            raise
    
    async def close_db(self):
        """Close database connection."""
        if self.db_connection:
            await self.db_connection.close()
    
    async def verify_database(self, expected_values: Dict, db_table: Optional[str] = None) -> Tuple[bool, Dict]:
        """Verify database state matches expected values.
        
        Args:
            expected_values: Dict of field names to expected values
            db_table: Database table name (e.g., "products" or "order_management.products")
        
        Returns:
            (success, verification_result)
        """
        if not self.db_connection:
            return False, {"error": "Database not connected"}
        
        try:
            # Default table if not provided
            if not db_table:
                db_table = "items"
            
            # Handle schema-qualified table names (e.g., "order_management.products")
            # If table doesn't have schema, try common schemas
            if "." not in db_table:
                # Try order_management schema first (common in this app)
                table_with_schema = f"order_management.{db_table}"
            else:
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
        # Wait for network to settle
        await page.wait_for_load_state("networkidle", timeout=5000)
        
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
    
    async def execute(self) -> Dict[str, Any]:
        """Execute the mission with agentic browser + deterministic API/DB checks.
        
        Returns:
            Execution report with triple-check results
        """
        console.print("\n" + "=" * 70)
        console.print("[bold cyan]🎯 TRIPLE-CHECK EXECUTOR - Agentic Browser Architecture[/bold cyan]")
        console.print("=" * 70)
        console.print(f"[bold]Mission:[/bold] {self.mission.get('ticket_id')}")
        console.print(f"[bold]Target:[/bold] {self.mission.get('target_url')}")
        console.print()
        
        # Connect to database
        await self.connect_db()
        
        # Execution results
        results = {
            "mission_id": self.mission.get("ticket_id"),
            "execution_path": "agentic",
            "scenario_results": {},  # Track results per scenario
            "triple_check": {
                "database": {"success": False, "details": {}},
                "api": {"success": False, "details": {}},
                "ui": {"success": False, "details": {}}
            },
            "playwright_script": "",
            "overall_success": False
        }
        
        try:
            # Use browser-use for UI tests (it manages its own browser)
            if self.llm:
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
            else:
                console.print("[yellow]⚠️  No LLM available, skipping UI tests[/yellow]\n")
                ui_success = False
                results["ui_execution"] = {"error": "No LLM available"}
            
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
                
                # 1. Database Check (Deterministic) - Skip if test_scope says no
                if test_scope.get("test_db", True):
                    console.print("[bold]1️⃣ Database Verification[/bold]")
                    db_success, db_result = await self.verify_database(expected_values, db_table=db_table)
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
