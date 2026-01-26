"""Agentic Browser Agent - Using browser-use library for LLM-driven UI testing.

This module uses the browser-use library to execute test cases from mission.json.
The LLM reads natural language test descriptions and autonomously interacts with the UI.

Note: browser-use uses CDP directly, not Playwright's event system.
API verification is done separately by the executor's verification phase.
"""
import asyncio
import json
import os
import logging
import sys


# 1. SET THESE FIRST - Before any other imports
os.environ["ANONYMIZED_TELEMETRY"] = "false"
os.environ["BROWSER_USE_LOGGING_LEVEL"] = "error" # "result" is also a valid quiet option

# Suppress browser-use logging completely
logging.getLogger("browser_use").setLevel(logging.CRITICAL)
logging.getLogger("browser_use.agent").setLevel(logging.CRITICAL)
logging.getLogger("browser_use.browser").setLevel(logging.CRITICAL)
logging.getLogger("browser_use.browser.session").setLevel(logging.CRITICAL)
logging.getLogger("browser_use.controller").setLevel(logging.CRITICAL)
logging.getLogger("browser_use.dom").setLevel(logging.CRITICAL)

# Also disable all handlers
for name in ["browser_use", "browser_use.agent", "browser_use.browser", "browser_use.browser.session"]:
    logger = logging.getLogger(name)
    logger.handlers = []  # Remove all handlers
    logger.addHandler(logging.NullHandler())

# 2. Silence ALL loggers completely - redirect stdout/stderr during browser operations
def silence_all_loggers():
    # List of ALL noisy loggers - make them completely silent
    noisy_loggers = [
        "browser_use",
        "browser_use.agent",
        "browser_use.browser",
        "browser_use.browser.session",
        "browser_use.controller",
        "browser_use.dom",
        "browser_use.utils",
        "urllib3",
        "playwright",
        "langchain",
        "langchain_core",
        "openai",
        "httpcore",
        "httpx",
        "asyncio",
        "aiohttp"
    ]
    for name in noisy_loggers:
        logger = logging.getLogger(name)
        logger.setLevel(logging.CRITICAL)
        logger.propagate = False
        # Remove existing handlers to prevent duplicate printing
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        # Add a null handler to prevent any output
        logger.addHandler(logging.NullHandler())

silence_all_loggers()

from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path
from rich.console import Console

# Force unbuffered output for real-time logging
console = Console(force_terminal=True)

def log(msg: str):
    """Print and flush immediately for real-time output."""
    print(msg, flush=True)


class BrowserUseAgent:
    """Wrapper around browser-use Agent for test execution."""
    
    def __init__(self, mission: Dict[str, Any], headless: bool = True):
        self.mission = mission
        self.headless = headless
        self.scenario_results = {}
        self.api_calls = []  # For compatibility, but won't be populated by browser-use
        
    def _build_task_prompt(self, test_case: Dict[str, Any]) -> str:
        """Build a natural language task prompt from a test case."""
        purpose = test_case.get("purpose", "")
        steps = test_case.get("steps", [])
        test_data = test_case.get("test_data", {})
        verification = test_case.get("verification", {})
        field_selectors = test_case.get("field_selectors", {})
        target_url = self.mission.get("target_url", "http://localhost:5173")
        
        # Build a clear task description
        task_parts = [f"TASK: {purpose}"]
        
        # Add strict instructions for test execution
        task_parts.append("\nINSTRUCTIONS:")
        task_parts.append("1. You are a STRICT QA Test Agent. Your job is to verify functionality, not to make it work.")
        task_parts.append("2. If a step fails (e.g., element not found, click has no effect), DO NOT RETRY. FAIL IMMEDIATELY.")
        task_parts.append("3. If verification fails (e.g., expected text not visible), FAIL IMMEDIATELY.")
        task_parts.append("4. Do not scroll up/down searching for things that should be visible.")
        task_parts.append("5. To fail, just stop and state 'TEST FAILED: [reason]'.")
        
        # Add step-by-step instructions
        if steps:
            task_parts.append("\nSTEPS TO PERFORM:")
            for i, step in enumerate(steps, 1):
                task_parts.append(f"  {i}. {step}")
        
        # Add test data to use
        if test_data:
            task_parts.append("\nDATA TO USE:")
            for field, value in test_data.items():
                selector_info = field_selectors.get(field, {})
                selector = selector_info.get("selector", "")
                tag = selector_info.get("tag", "input")
                if selector:
                    task_parts.append(f"  - {field}: '{value}' (element: {tag} with selector: {selector})")
            else:
                    task_parts.append(f"  - {field}: '{value}'")
        
        # Add verification requirements
        if verification:
            task_parts.append("\nVERIFICATION:")
            if verification.get("ui"):
                task_parts.append(f"  - UI Check: {verification['ui']}")
            if verification.get("api"):
                task_parts.append(f"  - API Check: {verification['api']}")
        
        return "\n".join(task_parts)
    
    async def _create_llm(self):
        """Create the LLM instance for browser-use."""
        from browser_use.llm.openai.chat import ChatOpenAI
        
        api_url = os.getenv("NUTANIX_API_URL", "")
        api_key = os.getenv("NUTANIX_API_KEY", "")
        model = os.getenv("NUTANIX_MODEL", "openai/gpt-oss-120b")
        
        if not api_url or not api_key:
            raise ValueError("NUTANIX_API_URL and NUTANIX_API_KEY must be set")
        
        os.environ["ANONYMIZED_TELEMETRY"] = "false" 
        os.environ["BROWSER_USE_LOGGING_LEVEL"] = "false" # Disable telemetry to reduce noise
        
        # Build base URL for OpenAI-compatible client
        base_url = api_url
        if "/llm" not in base_url:
            base_url = f"{api_url}/llm"
        base_url = base_url.replace("/chat/completions", "").replace("/completions", "")
        if base_url.endswith("/"):
            base_url = base_url[:-1]
        
        # Silent: LLM connection details
        
        return ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=0,
            max_completion_tokens=4096,
            default_headers={
                "Authorization": f"Basic {api_key}"
            }
        )
    
    async def execute_test_case(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single test case using browser-use Agent."""
        from browser_use import Agent
        from browser_use.browser.session import BrowserSession
        
        test_id = test_case.get("id", "unknown")
        purpose = test_case.get("purpose", "")
        target_url = self.mission.get("target_url", "http://localhost:5173")
        
        # Detect and correct API URLs - we need UI URLs for browser testing
        if target_url and ("/api/" in target_url or "/graphql" in target_url):
            # Extract base URL from API endpoint
            from urllib.parse import urlparse
            parsed = urlparse(target_url)
            target_url = f"{parsed.scheme}://{parsed.netloc}/"
            console.print(f"[yellow]⚠️ Target URL was an API endpoint, using base URL: {target_url}[/yellow]")
        
        console.print(f"[bold cyan]🤖 Executing: {purpose}[/bold cyan]")

        # Build the task prompt
        task = self._build_task_prompt(test_case)
        full_task = f"Go to {target_url} and then:\n\n{task}"

        browser_session = None
        agent = None

        try:
            # Create LLM and browser silently
            llm = await self._create_llm()
            browser_session = BrowserSession(
                headless=self.headless,
                disable_security=True,  # Allow cross-origin for local testing
            )
            await browser_session.start()

            # Create agent with browser session
            agent = Agent(
                task=full_task,
                llm=llm,
                browser_session=browser_session,
                use_vision=True,
                max_failures=2,  # Fail fast on errors (allow 1 retry for transient issues)
                max_actions_per_step=3,
                use_thinking=False
            )
            
            # Run the agent (fewer steps for filter/verify actions to fail faster if broken)
            action_type = test_case.get("action_type", "")
            max_steps = 10 if action_type in ["filter", "verify"] else 20
            
            # Run agent with suppressed output
            import sys
            from contextlib import redirect_stdout, redirect_stderr
            with redirect_stdout(open(os.devnull, 'w')), redirect_stderr(open(os.devnull, 'w')):
                history = await agent.run(max_steps=max_steps)
            
            # Check results
            final_result = history.final_result() if hasattr(history, 'final_result') else None
            steps_executed = len(history.history) if history and hasattr(history, 'history') else 0

            # Determine success based on final result - fail if agent explicitly reports TEST FAILED
            success = history.is_done() and (not final_result or "TEST FAILED" not in str(final_result))
            
            result = {
                "scenario_id": test_id,
                "purpose": purpose,
                "success": success,
                "steps_executed": steps_executed,
                "final_result": str(final_result) if final_result else None,
                "verification": {}
            }
            
            self.scenario_results[test_id] = result
            
            console.print(f"[{'green' if success else 'red'}]{'✅' if success else '❌'} Test completed ({steps_executed} steps)[/{'green' if success else 'red'}]\n")
            
            return result
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            console.print(f"[red]❌ Error executing test '{purpose}': {error_msg}[/red]")
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            
            result = {
                "scenario_id": test_id,
                "purpose": purpose,
                "success": False,
                "error": error_msg,
                "traceback": traceback.format_exc(),
                "verification": {}
            }
            self.scenario_results[test_id] = result
            return result
            
        finally:
            # Clean up browser session
            if browser_session:
                try:
                    console.print("[dim]   🔒 Closing browser...[/dim]")
                    await browser_session.stop()
                    console.print("[dim]   ✅ Browser closed[/dim]")
                except Exception as e:
                    console.print(f"[dim]   ⚠️ Error closing browser: {e}[/dim]")
    
    async def execute_all_scenarios(self) -> Dict[str, Any]:
        """Execute all test cases from the mission."""
        console.print("[bold cyan]📋 Loading test cases from mission...[/bold cyan]")
        
        test_cases = self.mission.get("test_cases", [])
        
        if not test_cases:
            console.print("[yellow]⚠️ No test cases found in mission[/yellow]")
            return {
                "success": False,
                "error": "No test cases found",
                "scenario_results": {},
                "api_calls": []
            }
        
        console.print(f"[green]✅ Found {len(test_cases)} test case(s)[/green]\n")
        
        target_url = self.mission.get("target_url", "http://localhost:5173")
        # Detect and correct API URLs - we need UI URLs for browser testing
        if target_url and ("/api/" in target_url or "/graphql" in target_url):
            from urllib.parse import urlparse
            parsed = urlparse(target_url)
            target_url = f"{parsed.scheme}://{parsed.netloc}/"
            console.print(f"[yellow]⚠️ Target URL was an API endpoint, using base URL: {target_url}[/yellow]")
        console.print(f"[dim]🌐 Target URL: {target_url}[/dim]\n")
        
        # Execute each test case
        all_success = True
        for i, test_case in enumerate(test_cases, 1):
            console.print(f"[bold]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold]")
            console.print(f"[bold]📝 Test {i}/{len(test_cases)}: {test_case.get('purpose', 'Unknown')}[/bold]")
            console.print(f"[dim]   Action type: {test_case.get('action_type', 'unknown')}[/dim]")
            
            result = await self.execute_test_case(test_case)
            if not result.get("success"):
                all_success = False
        
        console.print(f"[bold]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold]")
        
        return {
            "success": all_success,
            "scenario_results": self.scenario_results,
            "api_calls": self.api_calls,  # Empty for now, verification done by executor
            "playwright_script": ""
        }


# Keep the old BrowserAgent class for backward compatibility
class BrowserAgent:
    """Legacy wrapper - now delegates to BrowserUseAgent."""
    
    def __init__(self, page, llm, mission: Dict[str, Any]):
        """
        Initialize BrowserAgent.
        
        Note: page and llm parameters are kept for backward compatibility
        but are no longer used. browser-use manages its own browser and LLM.
        """
        self.page = page  # Not used anymore
        self.llm = llm    # Not used anymore
        self.mission = mission
        self.scenario_results = {}
        self.api_calls = []
        self._browser_use_agent = BrowserUseAgent(mission, headless=True)
    
    async def execute_all_scenarios(self) -> Dict[str, Any]:
        """Execute all scenarios using browser-use."""
        # Close the page we were passed since browser-use will create its own
        if self.page:
            try:
                await self.page.close()
            except:
                pass
        
        result = await self._browser_use_agent.execute_all_scenarios()
        self.scenario_results = self._browser_use_agent.scenario_results
        self.api_calls = self._browser_use_agent.api_calls
        return result
    
    def generate_playwright_script(self) -> str:
        """Generate Playwright script - not supported with browser-use."""
        return "// Playwright script generation not supported with browser-use\n"
