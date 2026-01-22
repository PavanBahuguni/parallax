"""
semantic_mapper_with_gateway.py

Step 1 only:
- Natural language gateway (login + persona selection) compiled to structured steps
- Execute steps deterministically with Playwright
- Save storage_state
- Run existing SemanticMapper to generate semantic_graph.json

NO changes to existing semantic_mapper.py
"""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, Response

# Reuse your existing mapper + LLM wrapper
from semantic_mapper import SemanticMapper, FixedNutanixChatModel, CONFIG


async def wait_for_active_requests_complete(page: Page, timeout: int = 30000) -> None:
    """
    Wait for active network requests to complete instead of using networkidle.
    This is more reliable than networkidle which waits for 500ms of silence.
    
    Strategy:
    1. Track requests that start after this function is called
    2. Wait for all tracked requests to receive responses
    3. Use a timeout to avoid waiting forever
    """
    # Track active requests (requests that haven't received responses yet)
    active_requests = {}
    
    def handle_request(request):
        # Store request with timestamp
        active_requests[request.url] = asyncio.get_event_loop().time()
    
    def handle_response(response):
        # Remove request when response is received
        active_requests.pop(response.url, None)
    
    # Set up listeners BEFORE checking active requests
    page.on("request", handle_request)
    page.on("response", handle_response)
    
    try:
        # Wait for all active requests to complete
        start_time = asyncio.get_event_loop().time()
        max_wait_seconds = timeout / 1000
        
        while active_requests:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= max_wait_seconds:
                remaining = len(active_requests)
                if remaining > 0:
                    print(f"      ⚠️  Timeout waiting for {remaining} request(s) to complete (continuing anyway)")
                break
            
            await asyncio.sleep(0.1)  # Check every 100ms
        
        # Give a small buffer for any final responses
        await asyncio.sleep(0.3)
    finally:
        # Clean up listeners
        try:
            page.remove_listener("request", handle_request)
            page.remove_listener("response", handle_response)
        except:
            pass  # Ignore if listeners were already removed


# -----------------------------
# Load Playwright scripts from files
# -----------------------------
def _load_playwright_script(script_name: str) -> str:
    """Load a JavaScript file from the scripts directory."""
    script_path = Path(__file__).parent / "scripts" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")
    return script_path.read_text()


# -----------------------------
# Gateway plan schema (minimal)
# -----------------------------
ALLOWED_ACTIONS = {
    "goto",
    "click",
    "fill",
    "select",
    "wait_visible",
    "assert_text",
    "assert_url_contains",
    "save_storage_state",
}

ENV_RE = re.compile(r"^env\(([^)]+)\)$")


def resolve_value(val: Optional[str]) -> Optional[str]:
    """Resolve env(NAME) strings."""
    if val is None:
        return None
    m = ENV_RE.match(val)
    if m:
        return os.getenv(m.group(1), "")
    return val


async def find_username_field_agentic(page: Page) -> Optional[str]:
    """
    Agentic discovery: Analyze page HTML to find username/email input field.
    Returns selector if found, None otherwise.
    """
    js = """
    () => {
        const inputs = Array.from(document.querySelectorAll('input[type="text"], input[type="email"], input:not([type])'));
        for (const inp of inputs) {
            const name = (inp.name || '').toLowerCase();
            const id = (inp.id || '').toLowerCase();
            const placeholder = (inp.placeholder || '').toLowerCase();
            const ariaLabel = (inp.getAttribute('aria-label') || '').toLowerCase();
            const type = inp.type.toLowerCase();
            
            // Check if this looks like a username/email field
            const isUsername = 
                name.includes('user') || name.includes('email') || name.includes('login') ||
                id.includes('user') || id.includes('email') || id.includes('login') ||
                placeholder.includes('user') || placeholder.includes('email') || placeholder.includes('login') ||
                ariaLabel.includes('user') || ariaLabel.includes('email') || ariaLabel.includes('login') ||
                type === 'email';
            
            if (isUsername && inp.offsetParent !== null) {  // Check if visible
                // Build best selector
                if (inp.id) return `#${inp.id}`;
                if (inp.name) return `input[name="${inp.name}"]`;
                if (inp.getAttribute('data-testid')) return `[data-testid="${inp.getAttribute('data-testid')}"]`;
                return `input[type="${inp.type || 'text'}"]`;
            }
        }
        return null;
    }
    """
    selector = await page.evaluate(js)
    return selector


async def find_password_field_agentic(page: Page) -> Optional[str]:
    """
    Agentic discovery: Analyze page HTML to find password input field.
    Returns selector if found, None otherwise.
    """
    js = """
    () => {
        const inputs = Array.from(document.querySelectorAll('input[type="password"]'));
        for (const inp of inputs) {
            if (inp.offsetParent !== null) {  // Check if visible
                // Build best selector
                if (inp.id) return `#${inp.id}`;
                if (inp.name) return `input[name="${inp.name}"]`;
                if (inp.getAttribute('data-testid')) return `[data-testid="${inp.getAttribute('data-testid')}"]`;
                return `input[type="password"]`;
            }
        }
        return null;
    }
    """
    selector = await page.evaluate(js)
    return selector


async def find_button_by_text_agentic(page: Page, text_keywords: List[str]) -> Optional[str]:
    """
    Agentic discovery: Find button by analyzing text content.
    text_keywords: List of keywords to match (e.g., ['continue', 'login', 'submit'])
    Returns selector if found, None otherwise.
    """
    keywords_lower = [kw.lower() for kw in text_keywords]
    
    js = f"""
    () => {{
        const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"], a[role="button"]'));
        for (const btn of buttons) {{
            if (btn.offsetParent === null) continue;  // Skip hidden
            
            const text = (btn.innerText || btn.textContent || btn.value || btn.getAttribute('aria-label') || '').toLowerCase().trim();
            const keywords = {keywords_lower};
            
            // Check if button text matches any keyword
            const matches = keywords.some(kw => text.includes(kw));
            
            if (matches) {{
                // Build best selector
                if (btn.id) return `#${{btn.id}}`;
                if (btn.getAttribute('data-testid')) return `[data-testid="${{btn.getAttribute('data-testid')}}"]`;
                if (btn.getAttribute('aria-label')) return `[aria-label="${{btn.getAttribute('aria-label')}}"]`;
                // Use text-based selector as fallback
                return `button:has-text("${{text}}"), [role="button"]:has-text("${{text}}")`;
            }}
        }}
        return null;
    }}
    """
    selector = await page.evaluate(js)
    return selector


async def find_button_smart(page: Page, button_text: str) -> Optional[str]:
    """
    Smart button finder: Tries multiple strategies to find a button by text.
    Priority: exact text match → aria-label → id → data-testid → partial text match
    
    Args:
        page: Playwright page object
        button_text: The button text to find (e.g., "Log In With My Nutanix")
    
    Returns:
        Best selector found, or None if not found
    """
    button_text_lower = button_text.lower().strip()
    
    js = f"""
    () => {{
        const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"], a[role="button"]'));
        
        // First pass: Try exact text match (case-insensitive)
        for (const btn of buttons) {{
            if (btn.offsetParent === null) continue;  // Skip hidden
            
            const btnText = (btn.innerText || btn.textContent || btn.value || '').trim();
            if (btnText.toLowerCase() === '{button_text_lower}') {{
                // Found exact match - return best selector
                if (btn.id) return `#${{btn.id}}`;
                if (btn.getAttribute('data-testid')) return `[data-testid="${{btn.getAttribute('data-testid')}}"]`;
                if (btn.getAttribute('aria-label')) return `[aria-label="${{btn.getAttribute('aria-label')}}"]`;
                // Use text selector
                return `button:has-text("${{btnText}}")`;
            }}
        }}
        
        // Second pass: Try partial text match (contains)
        for (const btn of buttons) {{
            if (btn.offsetParent === null) continue;
            
            const btnText = (btn.innerText || btn.textContent || btn.value || '').trim().toLowerCase();
            if (btnText.includes('{button_text_lower}') || '{button_text_lower}'.includes(btnText)) {{
                // Found partial match - return best selector
                if (btn.id) return `#${{btn.id}}`;
                if (btn.getAttribute('data-testid')) return `[data-testid="${{btn.getAttribute('data-testid')}}"]`;
                if (btn.getAttribute('aria-label')) return `[aria-label="${{btn.getAttribute('aria-label')}}"]`;
                // Use text selector
                const originalText = (btn.innerText || btn.textContent || btn.value || '').trim();
                return `button:has-text("${{originalText}}")`;
            }}
        }}
        
        // Third pass: Try aria-label match
        for (const btn of buttons) {{
            if (btn.offsetParent === null) continue;
            
            const ariaLabel = (btn.getAttribute('aria-label') || '').trim().toLowerCase();
            if (ariaLabel === '{button_text_lower}' || ariaLabel.includes('{button_text_lower}')) {{
                return `[aria-label="${{btn.getAttribute('aria-label')}}"]`;
            }}
        }}
        
        return null;
    }}
    """
    selector = await page.evaluate(js)
    return selector


async def collect_ui_snapshot(page: Page, max_elems: int = 60) -> Dict[str, Any]:
    """
    Compact snapshot for small LLM:
    - URL, title
    - visible body preview
    - key interactive elements (role/name/selector_hint)
    """
    title = await page.title()
    url = page.url
    body_text = await page.inner_text("body")
    body_preview = " ".join(body_text.split())[:800]

    # Simplified JavaScript to avoid syntax issues
    # Include both elements with explicit role attributes AND native HTML elements
    js = f"""
    () => {{
      const out = [];
      const seen = new Set(); // Track elements we've already added
      
      // First, collect elements with explicit role attributes
      // BUT exclude cookie/privacy consent elements
      const roles = ["button", "link", "textbox", "combobox", "menuitem", "tab"];
      for (const r of roles) {{
        const nodes = document.querySelectorAll(`[role="${{r}}"]`);
        for (const el of nodes) {{
          const rect = el.getBoundingClientRect();
          if (rect.width < 1 || rect.height < 1) continue;
          if (seen.has(el)) continue;
          
          // FILTER OUT: Cookie/privacy consent elements
          const elId = (el.id || "").toLowerCase();
          const elClass = (el.className || "").toLowerCase();
          const elAriaLabel = (el.getAttribute("aria-label") || "").toLowerCase();
          const parent = el.closest(".cookie-consent, .cookie-banner, .cookie-notice, .privacy-consent, .privacy-banner, .privacy-notice, [id*='cookie' i], [id*='consent' i], [id*='privacy' i], [id*='onetrust' i]");
          
          if (parent || 
              elId.includes("cookie") || elId.includes("consent") || elId.includes("privacy") || elId.includes("onetrust") ||
              elClass.includes("cookie") || elClass.includes("consent") || elClass.includes("privacy") ||
              elAriaLabel.includes("cookie") || elAriaLabel.includes("consent") || elAriaLabel.includes("privacy")) {{
            continue; // Skip cookie/privacy consent elements
          }}
          
          seen.add(el);
          
          const name = (el.getAttribute("aria-label") || el.innerText || el.value || "").trim();
          let selector_hint = null;
          if (el.id) {{
            selector_hint = "#" + el.id;
          }} else {{
            const dt = el.getAttribute("data-testid");
            if (dt) {{
              selector_hint = "[data-testid='" + dt + "']";
            }} else {{
              const aria = el.getAttribute("aria-label");
              if (aria) {{
                selector_hint = el.tagName.toLowerCase() + "[aria-label='" + aria + "']";
              }} else {{
                selector_hint = el.tagName.toLowerCase();
              }}
            }}
          }}
          out.push({{
            role: r,
            name: name.slice(0, 80),
            selector_hint: selector_hint
          }});
          if (out.length >= {max_elems}) return out;
        }}
      }}
      
      // Also collect native HTML interactive elements (buttons, links, inputs, etc.)
      // BUT exclude cookie/privacy consent elements
      const nativeSelectors = [
        "button:not([role])",  // Native buttons without explicit role
        "a:not([role])",  // Native links without explicit role
        "input[type='text']:not([role]), input[type='email']:not([role]), input[type='password']:not([role])",
        "textarea:not([role])",
        "select:not([role])"
      ];
      
      for (const selector of nativeSelectors) {{
        const nodes = document.querySelectorAll(selector);
        for (const el of nodes) {{
          if (seen.has(el)) continue;
          const rect = el.getBoundingClientRect();
          if (rect.width < 1 || rect.height < 1) continue;
          
          // FILTER OUT: Cookie/privacy consent elements
          const elId = (el.id || "").toLowerCase();
          const elClass = (el.className || "").toLowerCase();
          const elAriaLabel = (el.getAttribute("aria-label") || "").toLowerCase();
          const parent = el.closest(".cookie-consent, .cookie-banner, .cookie-notice, .privacy-consent, .privacy-banner, .privacy-notice, [id*='cookie' i], [id*='consent' i], [id*='privacy' i], [id*='onetrust' i]");
          
          if (parent || 
              elId.includes("cookie") || elId.includes("consent") || elId.includes("privacy") || elId.includes("onetrust") ||
              elClass.includes("cookie") || elClass.includes("consent") || elClass.includes("privacy") ||
              elAriaLabel.includes("cookie") || elAriaLabel.includes("consent") || elAriaLabel.includes("privacy")) {{
            continue; // Skip cookie/privacy consent elements
          }}
          
          seen.add(el);
          
          const tagName = el.tagName.toLowerCase();
          let role = tagName;
          if (tagName === "a") role = "link";
          else if (tagName === "input" || tagName === "textarea") role = "textbox";
          else if (tagName === "select") role = "combobox";
          
          const name = (el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.innerText || el.value || "").trim();
          let selector_hint = null;
          if (el.id) {{
            selector_hint = "#" + el.id;
          }} else {{
            const dt = el.getAttribute("data-testid");
            if (dt) {{
              selector_hint = "[data-testid='" + dt + "']";
            }} else {{
              const aria = el.getAttribute("aria-label");
              if (aria) {{
                selector_hint = tagName + "[aria-label='" + aria + "']";
              }} else {{
                selector_hint = tagName;
              }}
            }}
          }}
          out.push({{
            role: role,
            name: name.slice(0, 80),
            selector_hint: selector_hint
          }});
          if (out.length >= {max_elems}) return out;
        }}
      }}
      
      return out;
    }}
    """
    elements = await page.evaluate(js)

    return {
        "url": url,
        "title": title,
        "body_preview": body_preview,
        "elements": elements,
    }


def build_gateway_compile_prompt(
    persona: str,
    instructions: str,
    snapshot: Dict[str, Any],
    base_url: str,
    storage_state_path: str,
) -> str:
    """
    IMPORTANT: This is where we 'add this to prompt':
    - persona context
    - gateway goal
    - restrict output to strict JSON plan
    """
    # Check if instructions mention authentication/credentials
    mentions_auth = any(keyword in instructions.lower() for keyword in ['login', 'log in', 'sign in', 'auth', 'credential', 'password', 'user'])
    
    # Check if instructions mention verification/confirmation
    mentions_verification = any(keyword in instructions.lower() for keyword in ['verify', 'confirm', 'ensure', 'check', 'assert', 'validate', 'should see', 'must see', 'expect'])

    credential_instruction = ""
    if mentions_auth:
        credential_instruction = "- Use env(LOGIN_USERNAME), env(LOGIN_PASSWORD), env(TEST_USER), env(TEST_PASS), or env(MFA_SECRET) if credentials are needed. Match the env variable names used in the instructions."

    postcondition_instruction = ""
    if mentions_verification:
        postcondition_instruction = f"- Include postconditions based on verification steps mentioned in the instructions (e.g., if instructions say 'verify X is visible', add assert_text or assert_url_contains)."
    else:
        postcondition_instruction = "- Postconditions are optional. Only include them if the instructions explicitly mention verification or confirmation steps."

    # Extract domain from base_url for redirect checks
    from urllib.parse import urlparse
    base_parsed = urlparse(base_url)
    base_domain = base_parsed.netloc  # e.g., "localhost:9000"
    
    return f"""
You are an automation planner that converts NATURAL LANGUAGE instructions into a strict, executable JSON plan.

CRITICAL RULES - READ THIS FIRST:
1. **ONLY FOLLOW THE INSTRUCTIONS PROVIDED** - Do NOT add steps that are not in the instructions.
2. **DO NOT add cookie consent clicks, privacy dialogs, or any other steps not explicitly mentioned.**
3. **The page snapshot is ONLY for finding selectors** - Use it to locate elements mentioned in instructions, but do NOT add steps based on what you see in the snapshot.
4. **Follow instructions in order** - Convert each numbered instruction into exactly one step (or wait/assert step).

CONTEXT:
- Target app base URL: {base_url}
- Target app domain: {base_domain}
- Persona identifier: {persona}
- Follow the instructions exactly as provided. Do not add steps or verifications not mentioned in the instructions.

OUTPUT REQUIREMENTS:
- Output ONLY valid JSON.
- Allowed actions: {sorted(list(ALLOWED_ACTIONS))}
- Every click/fill/select/wait_visible must include "selector".

SELECTOR PRIORITY (for buttons/links mentioned in instructions):
1. **If instructions mention button/link TEXT** (e.g., "Click on 'Log In With My Nutanix' button"), use text-based selector: `:has-text('Log In With My Nutanix')` or `button:has-text('Log In With My Nutanix')`
2. **If snapshot shows aria-label** for the element, use: `[aria-label='...']`
3. **If snapshot shows id**, use: `#id`
4. **If snapshot shows data-testid**, use: `[data-testid='...']`

IMPORTANT: When instructions mention button text in natural language (e.g., "Click on 'X' button"), prefer text-based selectors over aria-label/id unless the snapshot clearly shows a better selector.

ACTION SELECTION RULES (CRITICAL - FOLLOW THESE EXACTLY):

STEP 1: Check if instruction mentions URL/domain pattern
- Look for phrases: "URL should contain", "URL contains", "wait for URL", or domain names like "stage-my.nutanix.com", "localhost:9000"
- If found → USE assert_url_contains with the domain/URL pattern
- Example: "Wait for SSO page to load (URL should contain stage-my.nutanix.com)" 
  → {{"action": "assert_url_contains", "text": "stage-my.nutanix.com"}}
- Example: "Wait for redirect back to original application (URL should contain localhost:9000)"
  → {{"action": "assert_url_contains", "text": "localhost:9000"}}

STEP 2: If no URL mentioned, check if instruction says "wait for text X to be visible"
- If found → USE wait_visible with text selector
- Example: "Wait for text 'Partner Central' to be visible"
  → {{"action": "wait_visible", "selector": ":has-text('Partner Central')"}}

STEP 3: If instruction says "wait for X to load" WITHOUT URL or text mention
- Use wait_visible with a text selector for a visible element
- Example: "Wait for password screen to load"
  → {{"action": "wait_visible", "selector": ":has-text('password')"}} (or find a visible element on password screen)

PATTERN MATCHING GUIDE:
- "(URL should contain X)" → assert_url_contains with X
- "(URL contains X)" → assert_url_contains with X  
- "wait for text X" → wait_visible with :has-text('X')
- "wait for X to load" + URL mentioned → assert_url_contains
- "wait for X to load" + NO URL → wait_visible

- IMPORTANT: Do not add HTML tag assumptions (h1, div, span, etc.) to selectors unless the instructions explicitly mention the tag name.
- IMPORTANT: When instructions mention BOTH a page name AND a URL pattern in parentheses, the URL pattern takes priority - use assert_url_contains.
{credential_instruction}
{postcondition_instruction}
- MUST include final step save_storage_state with path "{storage_state_path}".

JSON format:
{{
  "persona": "{persona}",
  "goal": "short goal describing what the gateway accomplishes",
  "storage_state_path": "{storage_state_path}",
  "steps": [
    {{ "action": "goto", "url": "{base_url}" }},
    {{ "action": "click", "selector": "..." }},
    {{ "action": "fill", "selector": "...", "value": "..." }}
  ],
  "postconditions": [
    {{ "action": "assert_text", "text": "..." }}
  ]
}}

Note: "postconditions" array is optional. Only include it if the instructions mention verification steps.

REMINDER: 
- Convert ONLY the steps mentioned in USER INSTRUCTIONS below.
- Do NOT add cookie consent, privacy dialogs, or any other steps.
- Use the PAGE SNAPSHOT only to find selectors for elements mentioned in instructions.

USER INSTRUCTIONS (follow these EXACTLY, in order):
{instructions}

PAGE SNAPSHOT (JSON) - Use this ONLY to find selectors for elements mentioned in instructions:
{json.dumps(snapshot, indent=2)}
""".strip()


async def compile_gateway_plan(llm, prompt: str) -> Dict[str, Any]:
    """Call LLM and parse JSON plan."""
    from langchain_core.messages import HumanMessage

    print("   ⏳ Waiting for LLM response (this may take 30-60 seconds)...")
    try:
        # Ollama (langchain_community.llms.Ollama) expects string, not messages
        # Nutanix (FixedNutanixChatModel) expects list of messages
        if hasattr(llm, '__class__') and 'Ollama' in llm.__class__.__name__:
            # Ollama LLM - pass string directly
            result = llm.invoke(prompt)
            response = result if isinstance(result, str) else str(result)
        else:
            # Nutanix ChatModel - pass messages
            result = llm.invoke([HumanMessage(content=prompt)])
            # Handle ChatResult format
            if hasattr(result, 'generations') and result.generations:
                response = result.generations[0].message.content
            elif hasattr(result, 'content'):
                response = result.content
            else:
                response = str(result)
        print("   ✅ LLM response received")
    except Exception as e:
        print(f"   ❌ LLM call failed: {e}")
        raise

    # Debug: Print first 500 chars of response to help diagnose issues
    print(f"   🔍 Response preview: {response[:500]}...")

    # Try to extract JSON - handle multiple formats:
    # 1. JSON wrapped in markdown code blocks (```json ... ```)
    # 2. JSON wrapped in code blocks (``` ... ```)
    # 3. Raw JSON object
    plan = None
    
    # Try markdown code block first
    json_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", response, re.IGNORECASE)
    if json_match:
        try:
            plan = json.loads(json_match.group(1))
            print("   ✅ Extracted JSON from markdown code block")
        except json.JSONDecodeError as e:
            print(f"   ⚠️  Failed to parse JSON from code block: {e}")
    
    # If that didn't work, try raw JSON object
    if not plan:
        json_match = re.search(r"(\{[\s\S]*\})", response)
        if json_match:
            try:
                plan = json.loads(json_match.group(1))
                print("   ✅ Extracted JSON from raw response")
            except json.JSONDecodeError as e:
                print(f"   ⚠️  Failed to parse JSON: {e}")
                print(f"   📄 Full response (first 2000 chars):\n{response[:2000]}")
                raise RuntimeError(f"LLM returned invalid JSON. Error: {e}\nResponse preview: {response[:500]}")
    
    if not plan:
        raise RuntimeError(f"LLM did not return JSON. Response:\n{response[:1000]}")

    # Validate basics
    if plan.get("persona") is None or plan.get("steps") is None:
        raise ValueError("Invalid plan: missing persona/steps")
    for s in plan.get("steps", []):
        if s.get("action") not in ALLOWED_ACTIONS:
            raise ValueError(f"Invalid action in plan: {s.get('action')}")
        if s["action"] in ("click", "fill", "select", "wait_visible") and not s.get("selector"):
            raise ValueError(f"Step missing selector: {s}")
        if s["action"] == "goto" and not s.get("url"):
            raise ValueError(f"Goto missing url: {s}")

    return plan


async def execute_gateway_plan(page: Page, plan: Dict[str, Any]) -> None:
    """
    Agentic Playwright execution of compiled gateway plan.
    
    This function executes the gateway plan with intelligent fallbacks:
    - If a selector fails, it analyzes the page HTML to find the correct element
    - For username/email fields: Scans all text inputs to identify which is username/email
    - For password fields: Finds password input by analyzing HTML attributes
    - For buttons: Finds buttons by analyzing text content and matching keywords
    
    This makes the gateway execution robust and adaptive - it doesn't just fail
    if the LLM-generated selector is wrong, it intelligently discovers the right element.
    """
    print(f"\n🚀 Executing gateway plan ({len(plan.get('steps', []))} steps)...")
    
    for i, step in enumerate(plan.get("steps", []), 1):
        action = step["action"]
        print(f"   [{i}/{len(plan.get('steps', []))}] {action.upper()}", end="")
        
        try:
            if action == "goto":
                url = resolve_value(step["url"])
                print(f": {url}")
                # Check if we're already on this URL
                current_url = page.url
                if current_url == url or current_url.rstrip('/') == url.rstrip('/'):
                    print(f"      ℹ️  Already on target URL, skipping navigation")
                else:
                    # Use "load" instead of "networkidle" for more lenient waiting
                    # Some pages never reach networkidle due to polling/websockets
                    try:
                        await page.goto(url, wait_until="load", timeout=60000)
                        # Give it a moment for any dynamic content
                        await asyncio.sleep(1)
                    except Exception as e:
                        # If load fails, try domcontentloaded as fallback
                        print(f"      ⚠️  Load timeout, trying domcontentloaded...")
                        try:
                            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(2)  # Give more time for dynamic content
                        except Exception as e2:
                            print(f"      ⚠️  Navigation warning: {e2}")
                            # Continue anyway - page might be partially loaded
            elif action == "click":
                selector = step["selector"]
                print(f": {selector}")
                
                # Try to click with the provided selector
                try:
                    # IMPROVEMENT: Try case-insensitive text matching first (faster than agentic fallback)
                    # If selector uses text='...', try case-insensitive alternatives first
                    clicked = False
                    if "text=" in selector:
                        text_match = re.search(r"text=['\"]([^'\"]+)['\"]", selector)
                        if text_match:
                            original_text = text_match.group(1)
                            # Try case-insensitive alternatives before failing
                            # :has-text() is more flexible and often case-insensitive
                            case_insensitive_selectors = [
                                f":has-text('{original_text}')",  # Most flexible, often case-insensitive
                                f"text='{original_text.lower()}'",  # Lowercase version
                                f"text='{original_text.capitalize()}'",  # Capitalized version
                                selector,  # Original as last resort
                            ]
                            for alt_selector in case_insensitive_selectors:
                                try:
                                    # For login/submit buttons, wait for them to be enabled first
                                    selector_lower = alt_selector.lower()
                                    if any(keyword in selector_lower for keyword in ["login", "log in", "submit", "sign in"]):
                                        try:
                                            await page.wait_for_selector(f"{alt_selector}:not([disabled])", state="visible", timeout=5000)
                                            print(f"      ✅ Button is enabled and ready")
                                        except:
                                            pass  # Continue to click attempt
                                    
                                    await page.click(alt_selector, timeout=3000)
                                    print(f"      ✅ Clicked with case-insensitive selector: {alt_selector}")
                                    selector = alt_selector  # Update selector for logging
                                    clicked = True
                                    break
                                except:
                                    continue
                    
                    if not clicked:
                        # Not a text selector or case-insensitive alternatives failed, use original
                        # For login/submit buttons, wait for them to be enabled first
                        selector_lower = selector.lower()
                        if any(keyword in selector_lower for keyword in ["login", "log in", "submit", "sign in"]):
                            try:
                                await page.wait_for_selector(f"{selector}:not([disabled])", state="visible", timeout=10000)
                                print(f"      ✅ Button is enabled and ready")
                            except:
                                print(f"      ⚠️  Button might be disabled, attempting click anyway")
                        
                        await page.click(selector, timeout=int(step.get("timeout_ms", 15000)))
                except Exception as e:
                    # AGENTIC MODE: If selector fails, try to find button by text/aria-label/id/data-testid
                    print(f"      🤖 Selector failed, trying smart button discovery...")
                    
                    # Extract button text from selector
                    button_text = None
                    
                    # Try to extract text from aria-label selector
                    aria_match = re.search(r"\[aria-label=['\"]([^'\"]+)['\"]", selector)
                    if aria_match:
                        button_text = aria_match.group(1)
                        print(f"      🔍 Extracted text from aria-label selector: '{button_text}'")
                    
                    # Try to extract text from text selector
                    if not button_text:
                        text_match = re.search(r"text=['\"]([^'\"]+)['\"]|has-text\(['\"]([^'\"]+)['\"]\)", selector)
                        if text_match:
                            button_text = text_match.group(1) or text_match.group(2)
                            print(f"      🔍 Extracted text from text selector: '{button_text}'")
                    
                    # If we have button text, use smart finder
                    if button_text:
                        discovered_selector = await find_button_smart(page, button_text)
                        if discovered_selector:
                            selector = discovered_selector
                            print(f"      ✅ Smart discovery found button: {discovered_selector}")
                            await page.click(selector, timeout=int(step.get("timeout_ms", 15000)))
                        else:
                            # Fallback to keyword-based search
                            print(f"      🔍 Smart finder failed, trying keyword-based search...")
                            text_lower = button_text.lower()
                            keywords = []
                            if "continue" in text_lower:
                                keywords = ["continue", "next", "proceed"]
                            elif "login" in text_lower or "log in" in text_lower:
                                keywords = ["login", "log in", "sign in", "submit"]
                            elif "submit" in text_lower:
                                keywords = ["submit", "login", "save", "ok"]
                            else:
                                # Extract first few words as keywords
                                words = button_text.split()[:3]
                                keywords = [w.lower() for w in words if len(w) > 2]
                            
                            if keywords:
                                discovered_selector = await find_button_by_text_agentic(page, keywords)
                                if discovered_selector:
                                    selector = discovered_selector
                                    print(f"      ✅ Keyword-based discovery found button: {discovered_selector}")
                                    await page.click(selector, timeout=int(step.get("timeout_ms", 15000)))
                                else:
                                    raise RuntimeError(f"Could not find button with text '{button_text}'. Tried smart finder and keyword search.")
                            else:
                                raise RuntimeError(f"Could not find button with text '{button_text}'. No keywords extracted.")
                    else:
                        # No text extracted, try original selector one more time with longer timeout
                        print(f"      ⚠️  Could not extract button text from selector, retrying with longer timeout...")
                        try:
                            await page.click(selector, timeout=int(step.get("timeout_ms", 30000)))
                        except:
                            raise RuntimeError(f"Could not click button with selector: {selector}. Original error: {e}")
                
                # Longer wait for login/submit buttons that trigger redirects
                selector_lower = selector.lower()
                if any(keyword in selector_lower for keyword in ["login", "log in", "submit", "sign in", "continue"]):
                    print(f"      ⏳ Waiting for redirect/navigation...")
                    try:
                        # Wait for navigation to start and complete
                        # SSO flows can take time, so use longer timeout
                        await page.wait_for_load_state("load", timeout=30000)
                        
                        # Wait for URL to stabilize (SSO redirects can be multi-step)
                        initial_url = page.url
                        await asyncio.sleep(2)  # Give time for redirects
                        
                        # Check if URL changed (indicates redirect happened)
                        final_url = page.url
                        if initial_url != final_url:
                            print(f"      🔄 Redirect detected: {initial_url} → {final_url}")
                            # Wait a bit more for the final page to fully load
                            await page.wait_for_load_state("domcontentloaded", timeout=15000)
                            await asyncio.sleep(1)
                        
                        # Handle popup windows if SSO opened one
                        # Get context from page to check for popups
                        try:
                            page_context = page.context
                            pages = page_context.pages
                            if len(pages) > 1:
                                print(f"      ⚠️  Multiple pages detected ({len(pages)}), checking for SSO popup...")
                                # Find the page that's not the original
                                for p in pages:
                                    if p != page and not p.is_closed():
                                        popup_url = p.url
                                        print(f"      🔍 Found popup window: {popup_url}")
                                        # If popup is SSO/auth related, wait for it to close or redirect
                                        if any(domain in popup_url for domain in ['sso', 'auth', 'login', 'oauth', 'saml', 'nutanix']):
                                            print(f"      ⏳ Waiting for SSO popup to complete...")
                                            try:
                                                # Wait for popup to navigate to final destination or close
                                                await p.wait_for_load_state("load", timeout=20000)
                                                await asyncio.sleep(2)
                                                # Check if popup closed or redirected
                                                if p.is_closed():
                                                    print(f"      ✅ SSO popup closed")
                                                else:
                                                    final_popup_url = p.url
                                                    print(f"      🔄 SSO popup URL: {final_popup_url}")
                                            except Exception as popup_err:
                                                print(f"      ⚠️  Popup handling warning: {popup_err}")
                        except AttributeError:
                            # Context not available, skip popup handling
                            pass
                        
                        # Verify page is still valid after SSO redirects
                        try:
                            # Try to access page properties to verify it's still valid
                            _ = page.url
                            _ = page.context
                        except Exception as page_err:
                            print(f"      ❌ Page became invalid after SSO redirect: {page_err}")
                            raise RuntimeError(f"Page/context was closed during SSO redirect. This may indicate SSO opened a new window that needs to be handled.")
                    except Exception as e:
                        print(f"      ⚠️  Navigation wait warning: {e}")
                        # Verify page is still valid
                        try:
                            _ = page.url
                        except:
                            print(f"      ❌ Page is no longer valid - may have been closed during redirect")
                            raise RuntimeError(f"Page became invalid during navigation: {e}")
                        # If load times out, wait a bit anyway for redirects
                        await asyncio.sleep(3)
                else:
                    # Small delay after other clicks
                    await asyncio.sleep(0.5)
            elif action == "fill":
                selector = step["selector"]
                value = resolve_value(step["value"])
                print(f": {selector} = {value[:50] if value else 'empty'}")
                
                # Wait for element to be visible before filling
                try:
                    await page.wait_for_selector(selector, state="visible", timeout=int(step.get("timeout_ms", 15000)))
                except Exception as e:
                    # AGENTIC MODE: If primary selector fails, analyze page HTML to find the field
                    selector_lower = selector.lower()
                    
                    if "password" in selector_lower or "passwd" in selector_lower:
                        print(f"      🤖 Primary selector failed, analyzing page to find password field...")
                        # Try hardcoded alternatives first (faster)
                        alt_selectors = [
                            "input[type='password']",
                            "input[type='password']:visible",
                            "[type='password']",
                            "input.password",
                            "#password",
                            "input[name='password']"
                        ]
                        found = False
                        for alt_selector in alt_selectors:
                            try:
                                await page.wait_for_selector(alt_selector, state="visible", timeout=2000)
                                selector = alt_selector
                                print(f"      ✅ Found password field with: {alt_selector}")
                                found = True
                                break
                            except:
                                continue
                        
                        # If hardcoded alternatives fail, use agentic discovery
                        if not found:
                            print(f"      🔍 Using agentic discovery to find password field...")
                            discovered_selector = await find_password_field_agentic(page)
                            if discovered_selector:
                                selector = discovered_selector
                                print(f"      ✅ Agentic discovery found password field: {discovered_selector}")
                                found = True
                        
                        if not found:
                            raise RuntimeError(f"Could not find password field. Analyzed page HTML but found no password input.")
                    
                    elif "username" in selector_lower or "email" in selector_lower or "user" in selector_lower:
                        print(f"      🤖 Primary selector failed, analyzing page to find username/email field...")
                        # Try hardcoded alternatives first (faster)
                        alt_selectors = [
                            "input[name='username']",
                            "#email",
                            "input#email",
                            "input[name='email']",
                            "input[type='email']",
                            "input[type='text'][name='username']",
                            "input[type='text']:visible",
                            "#username",
                            "input[placeholder*='username' i]",
                            "input[placeholder*='email' i]",
                            "input[placeholder*='user' i]"
                        ]
                        found = False
                        for alt_selector in alt_selectors:
                            try:
                                await page.wait_for_selector(alt_selector, state="visible", timeout=2000)
                                selector = alt_selector
                                print(f"      ✅ Found username field with: {alt_selector}")
                                found = True
                                break
                            except:
                                continue
                        
                        # If hardcoded alternatives fail, use agentic discovery
                        if not found:
                            print(f"      🔍 Using agentic discovery to find username/email field...")
                            discovered_selector = await find_username_field_agentic(page)
                            if discovered_selector:
                                selector = discovered_selector
                                print(f"      ✅ Agentic discovery found username field: {discovered_selector}")
                                found = True
                        
                        if not found:
                            raise RuntimeError(f"Could not find username/email field. Analyzed page HTML but found no matching input.")
                    else:
                        # For other fields, just raise the original error
                        raise
                
                # Fill the field - use type() for password fields to trigger keyboard events
                is_password = "password" in selector.lower() or "passwd" in selector.lower()
                
                if is_password:
                    # For password fields, use type() to simulate real typing
                    # This triggers input/keyup events that many forms need for validation
                    print(f"      🔐 Typing password (simulating keyboard input)...")
                    
                    # Clear field first using page.fill()
                    await page.fill(selector, "", timeout=int(step.get("timeout_ms", 15000)))
                    await asyncio.sleep(0.1)
                    
                    # Type the password to trigger keyboard events (simulates real typing)
                    # delay=50ms between keystrokes mimics human typing
                    await page.type(selector, value, delay=50, timeout=int(step.get("timeout_ms", 15000)))
                    
                    # Verify password was filled (check length, not actual value for security)
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            filled_length = await element.evaluate("el => el.value.length")
                            if filled_length != len(value):
                                print(f"      ⚠️  Warning: Password field length mismatch (expected {len(value)}, got {filled_length})")
                            else:
                                print(f"      ✅ Password entered ({filled_length} characters)")
                    except:
                        print(f"      ✅ Password typed (verification skipped)")
                    
                    # Trigger blur event (some forms validate on blur)
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            await element.evaluate("el => el.blur()")
                    except:
                        pass  # Ignore if blur fails
                    
                    # Give form time to validate password
                    await asyncio.sleep(1)
                    
                    # Check for validation errors (some forms show error messages)
                    try:
                        error_elements = await page.query_selector_all(".error, .invalid, [role='alert'], .field-error")
                        if error_elements:
                            error_texts = []
                            for err in error_elements[:3]:  # Check first 3 errors
                                text = await err.inner_text()
                                if text.strip():
                                    error_texts.append(text.strip())
                            if error_texts:
                                print(f"      ⚠️  Form validation errors detected: {', '.join(error_texts)}")
                    except:
                        pass  # Ignore errors checking for validation messages
                else:
                    # For other fields, use page.fill() for reliability
                    await page.fill(selector, value, timeout=int(step.get("timeout_ms", 15000)))
                    
                    # Trigger input and change events (some forms need these)
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            await element.evaluate("""
                                el => {
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                }
                            """)
                    except:
                        pass  # Ignore if we can't trigger events
                    
                    # Small delays for form interactions
                    if "username" in selector.lower() or "email" in selector.lower() or "user" in selector.lower():
                        # Some forms show password field after username is filled
                        await asyncio.sleep(0.5)
            elif action == "select":
                selector = step["selector"]
                value = resolve_value(step["value"])
                print(f": {selector} = {value}")
                await page.select_option(selector, value, timeout=int(step.get("timeout_ms", 15000)))
            elif action == "wait_visible":
                selector = step["selector"]
                print(f": {selector}")
                
                # FALLBACK: If selector contains a domain/URL pattern, this should be assert_url_contains instead
                # This handles cases where LLM incorrectly generates wait_visible for URL checks
                domain_patterns = [
                    r'stage-my\.nutanix\.com',
                    r'localhost:\d+',
                    r'partner-dev\.saas\.nutanix\.com',
                    r'\.nutanix\.com',
                    r'\.com',
                    r'\.net',
                    r'\.org',
                    r'http',
                    r'https',
                ]
                selector_lower = selector.lower()
                is_domain_pattern = any(re.search(pattern, selector_lower) for pattern in domain_patterns)
                
                if is_domain_pattern:
                    # Extract domain from selector
                    domain_match = re.search(r'([a-z0-9.-]+\.(com|net|org|io|dev)|localhost:\d+)', selector_lower)
                    if domain_match:
                        domain = domain_match.group(1)
                        print(f"      ⚠️  Detected domain pattern in wait_visible, converting to assert_url_contains: {domain}")
                        # Convert to assert_url_contains
                        await asyncio.sleep(1)  # Initial wait
                        waited = 1
                        max_wait = 30  # Longer wait for redirects
                        while domain not in page.url.lower() and waited < max_wait:
                            await asyncio.sleep(0.5)
                            waited += 0.5
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=1000)
                            except:
                                pass
                        
                        current_url = page.url
                        if domain in current_url.lower():
                            print(f"      ✅ URL contains '{domain}'")
                            await asyncio.sleep(1)  # Additional wait for page to be ready
                        else:
                            print(f"      ⚠️  URL doesn't contain '{domain}' yet (current: {current_url[:100]}...)")
                            print(f"      ℹ️  Continuing - may need more time for redirect")
                        continue  # Skip the wait_visible logic below
                
                # SMART FALLBACK: For common page types, use specific element selectors
                # Extract text from selector to understand intent
                text_match = re.search(r":has-text\(['\"]([^'\"]+)['\"]\)|text=['\"]([^'\"]+)['\"]", selector)
                text_to_find = None
                if text_match:
                    text_to_find = (text_match.group(1) or text_match.group(2)).lower()
                
                # If waiting for "password screen", wait for password INPUT field instead
                if text_to_find and "password" in text_to_find:
                    print(f"      🤖 Detected 'password screen' wait - using password input field selector")
                    password_selectors = [
                        "input[type='password']:visible",
                        "input[type='password']",
                        "input[name='password']:visible",
                        "#password:visible",
                        "input.password:visible",
                    ]
                    found = False
                    for pwd_selector in password_selectors:
                        try:
                            await page.wait_for_selector(pwd_selector, state="visible", timeout=5000)
                            print(f"      ✅ Password field found with: {pwd_selector}")
                            found = True
                            break
                        except:
                            continue
                    if found:
                        continue  # Success, skip rest of wait_visible logic
                    else:
                        print(f"      ⚠️  Password field not found, falling back to text matching...")
                
                # If waiting for "username" or "email" screen, wait for username/email INPUT field
                if text_to_find and ("username" in text_to_find or "email" in text_to_find or "user" in text_to_find):
                    print(f"      🤖 Detected 'username/email screen' wait - using input field selector")
                    username_selectors = [
                        "input[type='email']:visible",
                        "input[type='text'][name*='user' i]:visible",
                        "input[type='text'][name*='email' i]:visible",
                        "input[name='username']:visible",
                        "#email:visible",
                        "#username:visible",
                    ]
                    found = False
                    for user_selector in username_selectors:
                        try:
                            await page.wait_for_selector(user_selector, state="visible", timeout=5000)
                            print(f"      ✅ Username/email field found with: {user_selector}")
                            found = True
                            break
                        except:
                            continue
                    if found:
                        continue  # Success, skip rest of wait_visible logic
                
                try:
                    # IMPROVEMENT: Try case-insensitive text matching first
                    if "text=" in selector:
                        text_match = re.search(r"text=['\"]([^'\"]+)['\"]", selector)
                        if text_match:
                            original_text = text_match.group(1)
                            # Try case-insensitive alternatives first
                            case_insensitive_selectors = [
                                f":has-text('{original_text}')",  # Case-insensitive
                                f"text='{original_text.lower()}'",  # Lowercase
                                f"text='{original_text.upper()}'",  # Uppercase
                                f"text='{original_text.capitalize()}'",  # Capitalized
                                selector,  # Original as fallback
                            ]
                            found = False
                            for alt_selector in case_insensitive_selectors:
                                try:
                                    # Check if selector matches too many elements (common issue)
                                    elements = await page.query_selector_all(alt_selector)
                                    if len(elements) > 10:
                                        print(f"      ⚠️  Selector matches {len(elements)} elements, trying more specific alternatives...")
                                        # For password/username screens, try input fields instead
                                        if "password" in original_text.lower():
                                            try:
                                                await page.wait_for_selector("input[type='password']:visible", state="visible", timeout=5000)
                                                print(f"      ✅ Found password input field instead")
                                                found = True
                                                break
                                            except:
                                                pass
                                        continue  # Skip this selector, try next
                                    
                                    await page.wait_for_selector(alt_selector, state="visible", timeout=3000)
                                    print(f"      ✅ Found with case-insensitive selector: {alt_selector}")
                                    found = True
                                    break
                                except:
                                    continue
                            if not found:
                                raise Exception("Case-insensitive alternatives failed")
                        else:
                            await page.wait_for_selector(selector, state="visible", timeout=int(step.get("timeout_ms", 15000)))
                    else:
                        await page.wait_for_selector(selector, state="visible", timeout=int(step.get("timeout_ms", 15000)))
                except Exception as e:
                    # If selector contains tag assumptions (h1, div, etc.) and fails,
                    # try text-based alternatives without tag restrictions
                    # Extract text from selectors like "h1:has-text('X')" or "text='X'"
                    text_match = re.search(r":has-text\(['\"]([^'\"]+)['\"]\)|text=['\"]([^'\"]+)['\"]", selector)
                    if text_match:
                        text_to_find = text_match.group(1) or text_match.group(2)
                        print(f"      ⚠️  Primary selector failed, trying text-based alternatives...")
                        
                        # SMART FALLBACK: For password/username, try input fields first
                        if "password" in text_to_find.lower():
                            print(f"      🤖 Trying password input field as fallback...")
                            try:
                                await page.wait_for_selector("input[type='password']:visible", state="visible", timeout=5000)
                                print(f"      ✅ Found password input field")
                                continue  # Success!
                            except:
                                pass
                        
                        if "username" in text_to_find.lower() or "email" in text_to_find.lower() or "user" in text_to_find.lower():
                            print(f"      🤖 Trying username/email input field as fallback...")
                            try:
                                await page.wait_for_selector("input[type='email']:visible, input[type='text'][name*='user' i]:visible", state="visible", timeout=5000)
                                print(f"      ✅ Found username/email input field")
                                continue  # Success!
                            except:
                                pass
                        
                        # Try simpler text-based selectors without tag assumptions (case-insensitive)
                        alt_selectors = [
                            f":has-text('{text_to_find}')",  # Case-insensitive
                            f"text='{text_to_find.lower()}'",  # Lowercase
                            f"text='{text_to_find}'",  # Original
                            f"*:has-text('{text_to_find}')"  # Any element
                        ]
                        found = False
                        for alt_selector in alt_selectors:
                            try:
                                # Check if this selector matches too many elements
                                elements = await page.query_selector_all(alt_selector)
                                if len(elements) > 10:
                                    print(f"      ⚠️  Selector '{alt_selector}' matches {len(elements)} elements, skipping...")
                                    continue
                                
                                await page.wait_for_selector(alt_selector, state="visible", timeout=5000)
                                print(f"      ✅ Found text '{text_to_find}' with selector: {alt_selector}")
                                found = True
                                break
                            except:
                                continue
                        if not found:
                            # If all text selectors fail, raise original error
                            raise e
                    else:
                        # No text found in selector, raise original error
                        raise e
            elif action == "assert_text":
                # Try different possible field names
                text = step.get("text") or step.get("value") or step.get("contains")
                if not text:
                    raise ValueError(f"assert_text step missing 'text' field: {step}")
                print(f": checking for '{text}'")
                body = await page.inner_text("body")
                if text not in body:
                    raise RuntimeError(f"assert_text failed: expected '{text}' not found in page body")
                print(f"      ✅ Found text '{text}'")
            elif action == "assert_url_contains":
                # Try different possible field names (LLM might use 'url', 'text', 'value', etc.)
                text = step.get("text") or step.get("url") or step.get("value") or step.get("contains") or step.get("url_contains")
                if not text:
                    raise ValueError(f"assert_url_contains step missing 'text'/'url' field: {step}")
                print(f": checking URL contains '{text}'")
                
                # Wait for navigation - longer timeout for post-login redirects
                # Check if this might be a post-login assert (after clicking login/submit)
                is_post_login = i > 5  # Rough heuristic: if it's later in the steps
                max_wait = 30 if is_post_login else 10  # Longer wait for post-login redirects
                
                await asyncio.sleep(1)  # Initial wait
                waited = 1
                while text not in page.url and waited < max_wait:
                    await asyncio.sleep(0.5)
                    waited += 0.5
                    # Check if page is still loading
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=1000)
                    except:
                        pass
                
                current_url = page.url
                if text not in current_url:
                    # For post-login asserts, make it a warning instead of error
                    # Postconditions will verify the final state
                    if is_post_login:
                        print(f"      ⚠️  URL doesn't contain '{text}' yet (current: {current_url[:100]}...)")
                        print(f"      ℹ️  Continuing - postconditions will verify final state")
                    else:
                        raise RuntimeError(f"assert_url_contains failed: expected '{text}' in URL, but got '{current_url}'")
                else:
                    print(f"      ✅ URL contains '{text}'")
                    # After URL assertion succeeds, wait for page to be ready
                    # Especially important for SSO pages that load dynamically
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                        await asyncio.sleep(1)  # Additional wait for dynamic content
                    except:
                        await asyncio.sleep(2)  # Fallback wait if load state times out
            elif action == "save_storage_state":
                path = step.get("path", "storage_state.json")
                print(f": {path} (will be saved after gateway completes)")
                # no-op here; storage_state is saved at context level outside
                pass
            else:
                raise ValueError(f"Unknown action: {action}")
            
            print(f"      ✅ Step {i} completed")
        except Exception as e:
            print(f"      ❌ Step {i} failed: {e}")
            raise

    # postconditions (optional - only executed if present)
    postconditions = plan.get("postconditions", [])
    if postconditions:
        print(f"\n   🔍 Verifying {len(postconditions)} postcondition(s)...")
        for step in postconditions:
            action = step["action"]
            try:
                if action == "assert_text":
                    body = await page.inner_text("body")
                    if step["text"] not in body:
                        print(f"   ⚠️ Postcondition warning: text '{step['text']}' not found (continuing anyway)")
                        # Don't fail - postconditions are optional verification
                        continue
                    print(f"   ✅ Postcondition passed: found text '{step['text']}'")
                elif action == "wait_visible":
                    await page.wait_for_selector(step["selector"], state="visible", timeout=int(step.get("timeout_ms", 15000)))
                    print(f"   ✅ Postcondition passed: selector '{step['selector']}' is visible")
                elif action == "assert_url_contains":
                    if step["text"] not in page.url:
                        print(f"   ⚠️ Postcondition warning: URL doesn't contain '{step['text']}' (current: {page.url})")
                        continue
                    print(f"   ✅ Postcondition passed: URL contains '{step['text']}'")
                else:
                    print(f"   ⚠️ Unsupported postcondition action: {action} (skipping)")
            except Exception as e:
                print(f"   ⚠️ Postcondition check failed (non-fatal): {e}")
                # Continue execution - postconditions are optional verification


class SemanticMapperWithPersona(SemanticMapper):
    """
    Subclass existing SemanticMapper without modifying it.
    Inject persona context into nodes after discovery.
    Also prepend persona info into LLM prompts for better naming.
    """
    def __init__(self, llm, persona: str, base_url: Optional[str] = None):
        super().__init__(llm)
        self.persona = persona
        self.base_url = base_url or CONFIG['BASE_URL']  # Store base_url for filtering links

    async def analyze_with_llm(self, prompt: str) -> str:
        persona_prefix = f"[Persona Context] You are mapping the app while logged in as persona='{self.persona}'.\n"
        return await super().analyze_with_llm(persona_prefix + prompt)

    def _tag_last_node(self):
        if not self.graph.get("nodes"):
            return
        self.graph["nodes"][-1].setdefault("context", {})
        self.graph["nodes"][-1]["context"]["persona"] = self.persona

    async def link_api_to_db(self, endpoint: str, method: str) -> Optional[str]:
        """
        Stub implementation for Phase 1.
        Database table linking will be implemented in Phase 2 via PR-Diff analysis.
        """
        return None
    
    async def _dismiss_cookie_consent(self, page: Page) -> bool:
        """
        Attempt to automatically dismiss cookie/privacy consent dialogs.
        Returns True if a consent dialog was found and dismissed, False otherwise.
        """
        try:
            # Common selectors for cookie consent buttons
            consent_selectors = [
                'button:has-text("Accept")',
                'button:has-text("Accept All")',
                'button:has-text("Accept Cookies")',
                'button:has-text("I Accept")',
                'button:has-text("Agree")',
                'button:has-text("OK")',
                'button:has-text("Got it")',
                '[id*="accept" i]',
                '[id*="cookie-accept" i]',
                '[class*="accept" i]',
                '[class*="cookie-accept" i]',
                '.cookie-consent button:not([class*="reject"]):not([class*="decline"])',
                '.cookie-banner button:not([class*="reject"]):not([class*="decline"])',
                '[role="dialog"] button:has-text("Accept")',
                '[role="dialog"] button:has-text("OK")',
            ]
            
            for selector in consent_selectors:
                try:
                    # Check if element exists and is visible
                    element = await page.query_selector(selector)
                    if element:
                        is_visible = await element.is_visible()
                        if is_visible:
                            await element.click(timeout=2000)
                            await asyncio.sleep(0.5)  # Wait for dialog to close
                            print(f"   ✅ Dismissed cookie consent dialog")
                            return True
                except:
                    continue
            
            return False
        except Exception as e:
            # Silently fail - cookie consent dismissal is optional
            return False
    
    async def _extract_structured_page_info(self, page: Page) -> Dict[str, Any]:
        """
        Extract structured page information focusing on semantic content:
        - Headers (h1-h6) - page structure/hierarchy
        - Table columns - what data is displayed
        - Form fields - what can be input
        - Key paragraphs - main content (1-2 sentences each)
        
        This avoids noise from navigation, footers, and dynamic data.
        """
        info = {
            "headers": [],
            "tables": [],
            "forms": [],
            "key_content": ""
        }
        
        try:
            # Extract headers (h1-h6) - shows page structure
            headers_script = _load_playwright_script("extract_headers.js")
            info["headers"] = await page.evaluate(headers_script)
            
            # Extract table information (columns)
            tables_script = _load_playwright_script("extract_tables.js")
            info["tables"] = await page.evaluate(tables_script)
            
            # Extract form information (field names)
            forms_script = _load_playwright_script("extract_forms.js")
            info["forms"] = await page.evaluate(forms_script)
            
            # Extract key paragraphs (main content, not nav/footer)
            key_content_script = _load_playwright_script("extract_key_content.js")
            info["key_content"] = await page.evaluate(key_content_script)
            
        except Exception as e:
            print(f"   ⚠️ Error extracting structured page info: {e}")
        
        return info
    
    async def discover_page(self, page: Page, url: str, parent_url: Optional[str] = None, action: str = "navigate") -> str:
        """
        Override to add page summarization (description field).
        Improvement 2: Add description field that captures what the page represents without dynamic data.
        """
        # Check visited URLs (normalized comparison to prevent duplicate visits)
        # Normalize URL for comparison (remove trailing slashes, lowercase)
        normalized_url = url.rstrip('/').lower()
        visited_normalized = {u.rstrip('/').lower() for u in self.visited_urls}
        if normalized_url in visited_normalized:
            print(f"   ⏭️  Skipping already visited page: {url}")
            return url
        
        self.visited_urls.add(url)
        
        print(f"\n🔍 Discovering: {url}")
        
        # Record start time for API correlation
        start_time = asyncio.get_event_loop().time()
        
        # Check if we're already on this URL (maintains session state)
        current_url = page.url
        if current_url == url or current_url.rstrip('/') == url.rstrip('/'):
            print(f"   ℹ️  Already on target URL, waiting briefly for dynamic content...")
            # Don't wait for networkidle if already on URL - just wait briefly
            await asyncio.sleep(2)
        else:
            try:
                print(f"   ⏳ Waiting for page load and active requests to complete...")
                await page.goto(url, wait_until="load", timeout=60000)
                # Wait for active requests to complete (more reliable than networkidle)
                await wait_for_active_requests_complete(page, timeout=30000)
                print(f"   ✅ Page loaded and active requests completed")
            except Exception as e:
                # If load fails, try domcontentloaded
                print(f"   ⚠️  Load timeout, trying domcontentloaded...")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await wait_for_active_requests_complete(page, timeout=20000)
                    print(f"   ✅ Page loaded (domcontentloaded) and active requests completed")
                except Exception as e2:
                    print(f"   ⚠️ Failed to load page: {e2}")
                    return url
        
        # Dismiss cookie/privacy consent dialogs if present (before extracting page info)
        await self._dismiss_cookie_consent(page)
        
        # Extract page title
        title = await page.title()
        
        # IMPROVEMENT: Extract structured page information instead of raw body text
        # This focuses on semantic content and avoids navigation/footer noise
        structured_info = await self._extract_structured_page_info(page)
        
        # Use LLM to generate semantic page name from structured info
        llm_prompt = f"""What is this page's purpose?
URL: {url}
Title: {title}
Page Headers: {', '.join(structured_info['headers'][:5]) if structured_info['headers'] else 'N/A'}
Tables: {', '.join(structured_info['tables']) if structured_info['tables'] else 'None'}
Forms: {', '.join(structured_info['forms']) if structured_info['forms'] else 'None'}
Key Content: {structured_info['key_content']}

Respond with ONLY a short semantic name (e.g., "items_dashboard", "login_page", "user_profile").
"""
        semantic_name = await self.analyze_with_llm(llm_prompt)
        semantic_name = semantic_name.strip().lower().replace(' ', '_')
        
        # Generate a human-readable display title/header
        header_prompt = f"""Generate a clean, human-readable page title/header for this page:
URL: {url}
Page Title: {title}
Semantic Name: {semantic_name}
Main Header: {structured_info['headers'][0] if structured_info['headers'] else 'N/A'}

Respond with ONLY a short, clean title (e.g., "Order Management Dashboard", "Orders Page", "Product Catalog", "Shopping Cart").
Do not include quotes or extra formatting, just the title text.
"""
        display_header = await self.analyze_with_llm(header_prompt)
        display_header = display_header.strip().strip('"').strip("'")
        
        # Fallback: generate from semantic_name if LLM fails
        if not display_header or len(display_header) < 3:
            display_header = semantic_name.replace('_', ' ').title()
        
        # IMPROVEMENT 2: Generate page description/summary from structured info
        summary_prompt = f"""Summarize what this page represents, focusing on structure and purpose, not specific data values.

URL: {url}
Title: {title}
Page Headers: {', '.join(structured_info['headers'][:5]) if structured_info['headers'] else 'N/A'}
Tables: {', '.join(structured_info['tables']) if structured_info['tables'] else 'None'}
Forms: {', '.join(structured_info['forms']) if structured_info['forms'] else 'None'}
Key Content: {structured_info['key_content']}

Respond with a 2-3 sentence description of:
1. What this page shows/displays
2. Its main purpose or functionality
3. Key sections or features visible

IMPORTANT: Avoid mentioning specific numbers, amounts, counts, dates, or dynamic data values.
Focus on the structure, purpose, and type of information displayed.
"""
        page_description = await self.analyze_with_llm(summary_prompt)
        page_description = page_description.strip()
        
        # Extract semantic components (already extracts forms, buttons, lists)
        components = await self.extract_semantic_components(page, url)
        
        # Record end time
        end_time = asyncio.get_event_loop().time()
        
        # Enrich components with API data
        await self.enrich_components_with_apis(components, start_time, end_time)
        
        # Get active APIs (APIs called during page load)
        active_apis = [
            f"{log['method']} {log['url'].replace(CONFIG['API_BASE'], '')}"
            for log in self.network_log
            if log["type"] == "request" and start_time <= log["timestamp"] <= end_time
        ]
        active_apis = list(set(active_apis))  # Remove duplicates
        
        # Extract primary entity from APIs, URL, or components
        primary_entity = self._extract_primary_entity(url, active_apis, components)
        
        # Create node with description field and headers
        node_id = semantic_name or f"page_{len(self.graph['nodes'])}"
        node = {
            "id": node_id,
            "url": url,
            "semantic_name": semantic_name,
            "title": title,
            "display_header": display_header,
            "description": page_description,  # IMPROVEMENT 2: Add description for semantic search
            "headers": structured_info.get("headers", []),  # Store page headers for semantic search
            "primary_entity": primary_entity,
            "components": components,
            "active_apis": active_apis
        }
        
        self.graph["nodes"].append(node)
        
        # Create edge if there's a parent
        if parent_url:
            self.graph["edges"].append({
                "from": parent_url,
                "to": url,
                "action": action,
                "selector": None
            })
        
        print(f"   ✅ Node: {node_id}")
        print(f"   📝 Description: {page_description}")
        print(f"   📦 Components: {len(components)}")
        print(f"   📡 APIs: {len(active_apis)}")
        
        return url
    
    async def _build_stable_selector(self, link_element, text: str, href: str, link_id: str, data_testid: str) -> str:
        """
        Build a stable selector for a link, avoiding dynamic text content.
        Priority: id > data-testid > href > stable text > parent selectors
        """
        # Priority 1: Use id or data-testid if available (most stable)
        if link_id:
            return f"a#{link_id}"
        if data_testid:
            return f"a[data-testid='{data_testid}']"
        
        # Priority 2: Use href attribute (usually stable)
        if href:
            # Clean href for selector (escape special chars)
            href_clean = href.replace("'", "\\'").replace('"', '\\"')
            return f"a[href='{href_clean}']"
        
        # Priority 3: Check if text is dynamic
        dynamic_patterns = [
            r'\$[\d.,]+[KM]?',  # Currency like $1.05M, $78.91K
            r'\(\d+\)',  # Counts like (1), (3)
            r'\d{4}-\d{2}-\d{2}',  # Dates
            r'\d+%',  # Percentages
            r'\d+\.\d+[KM]?',  # Numbers with K/M suffix
        ]
        
        is_dynamic = any(re.search(pattern, text) for pattern in dynamic_patterns)
        
        if is_dynamic:
            # Try to find stable text by removing dynamic parts
            stable_text = text
            for pattern in dynamic_patterns:
                stable_text = re.sub(pattern, '', stable_text)
            stable_text = stable_text.strip()
            
            # If we have stable text remaining, use it
            if len(stable_text) > 3:
                stable_clean = stable_text.replace("'", "\\'").replace('"', '\\"')
                return f"a:has-text('{stable_clean[:50]}')"
            
            # Otherwise, try parent element's stable attributes
            try:
                parent_handle = await link_element.evaluate_handle('el => el.parentElement')
                if parent_handle:
                    parent_id = await parent_handle.get_attribute('id')
                    parent_testid = await parent_handle.get_attribute('data-testid')
                    parent_class = await parent_handle.get_attribute('class')
                    
                    if parent_id:
                        # Use parent id + structural position
                        return f"#{parent_id} a"
                    if parent_testid:
                        return f"[data-testid='{parent_testid}'] a"
                    if parent_class:
                        # Use first meaningful class
                        classes = parent_class.split()
                        meaningful = [c for c in classes if c and c not in ['', ' ']]
                        if meaningful:
                            return f".{meaningful[0]} a"
            except:
                pass
            
            # Last resort: use href if available
            if href:
                href_clean = href.replace("'", "\\'")
                return f"a[href='{href_clean}']"
        
        # Priority 4: Use text if it's stable (not dynamic)
        if text and len(text) > 0:
            text_clean = text.replace("'", "\\'").replace('"', '\\"')
            return f"a:has-text('{text_clean[:50]}')"
        
        # Fallback: use href
        if href:
            href_clean = href.replace("'", "\\'")
            return f"a[href='{href_clean}']"
        
        return "a[href]"  # Generic fallback
    
    async def discover_navigation_links(self, page: Page) -> List[Dict[str, str]]:
        """
        Override to use custom base_url and add domain filtering + stable selectors.
        Improvements:
        1. Domain filtering - only follow links with same domain
        2. Stable selector building - avoid dynamic text in selectors
        3. Filter out form controls (date filters, checkboxes) - only navigation links
        4. Filter out query-parameter-only links (filters, not navigation)
        
        NOTE: This method expects the page to already be loaded and network idle.
        It's called after discover_page() which waits for network completion.
        """
        links = []
        
        # Ensure page is ready before scanning (safety check)
        # This should already be done by discover_page(), but double-check
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except:
            pass  # If it times out, page might already be loaded, continue anyway
        
        # Extract domain from base_url for filtering
        base_parsed = urlparse(self.base_url)
        base_domain = base_parsed.netloc.split(':')[0]  # Remove port, get just domain
        
        try:
            # Find React Router Link components (they render as <a> tags)
            # BUT exclude links that are inside form controls or filter components
            link_elements = await page.query_selector_all('a[href]')
            
            for link in link_elements:
                # FILTER OUT: Links inside form controls, date pickers, checkboxes, filters
                try:
                    # Check if link is inside a form control or filter component
                    is_in_form_control = await link.evaluate("""
                        el => {
                            // Check if link is inside input, select, or form control
                            const parent = el.closest('form, .filter, .date-picker, .datepicker, [role="combobox"], [role="listbox"]');
                            if (parent) return true;
                            
                            // Check if link is a date/checkbox/select element itself
                            const tagName = el.tagName.toLowerCase();
                            if (tagName === 'input' || tagName === 'select') return true;
                            
                            // Check if link text suggests it's a filter/control (dates, quarters, etc.)
                            const text = (el.innerText || el.textContent || '').toLowerCase();
                            const filterKeywords = ['q1', 'q2', 'q3', 'q4', 'quarter', 'date', 'filter', 'select', 'choose'];
                            if (filterKeywords.some(kw => text.includes(kw))) {
                                // But allow if it's clearly a navigation link (has meaningful href path)
                                const href = el.getAttribute('href') || '';
                                // If href is just query params or hash, it's likely a filter
                                if (href.startsWith('?') || href.startsWith('#')) return true;
                                // If href is just a fragment with no path, skip
                                if (href === '#' || href === '') return true;
                            }
                            
                            return false;
                        }
                    """)
                    if is_in_form_control:
                        continue  # Skip form controls and filters
                except:
                    pass  # If evaluation fails, continue with link
                
                href = await link.get_attribute('href')
                text = (await link.inner_text()).strip()
                link_id = await link.get_attribute('id')
                data_testid = await link.get_attribute('data-testid')
                
                if href:
                    # FILTER OUT: Non-HTTP links (mailto, tel, javascript, etc.) - note but don't visit
                    non_http_protocols = ['mailto:', 'tel:', 'javascript:', 'sms:', 'ftp:', 'file:']
                    if any(href.lower().startswith(proto) for proto in non_http_protocols):
                        # Note the link but don't add it to navigation links (can't visit it)
                        print(f"   📎 Found non-HTTP link (not visiting): {href}")
                        continue
                    
                    # FILTER OUT: Query-parameter-only links (filters, not navigation)
                    # Links like "?date=2024-01-01" or "#filter" are filters, not navigation
                    href_clean = href.split('?')[0].split('#')[0]  # Remove query params and hash
                    if not href_clean or href_clean == '' or href_clean == '/':
                        # Skip links that are just query parameters or empty
                        if href.startswith('?') or href.startswith('#'):
                            continue
                    
                    # FILTER OUT: Links with filter-related text (dates, quarters, etc.)
                    text_lower = text.lower()
                    filter_indicators = ['q1', 'q2', 'q3', 'q4', 'quarter', 'jan', 'feb', 'mar', 'apr', 'may', 'jun', 
                                       'jul', 'aug', 'sep', 'oct', 'nov', 'dec', '2024', '2025', 'filter', 'select date']
                    # Only skip if text is ONLY filter-related (not a navigation link with filter text in it)
                    if any(indicator in text_lower for indicator in filter_indicators):
                        # Check if href suggests it's a filter (query params, hash, or very short)
                        if href.startswith('?') or href.startswith('#') or len(href.split('/')) <= 2:
                            continue  # Skip filter links
                    
                    # Convert relative URLs to absolute using custom base_url
                    if href.startswith('/'):
                        full_url = f"{self.base_url}{href}"
                    elif href.startswith('http'):
                        full_url = href
                        # IMPROVEMENT 1: Domain filtering - only include same domain
                        link_parsed = urlparse(full_url)
                        link_domain = link_parsed.netloc.split(':')[0]
                        if link_domain != base_domain:
                            continue  # Skip different domains
                    else:
                        # Relative path, construct full URL
                        current_url = page.url
                        base = current_url.rsplit('/', 1)[0] if '/' in current_url else self.base_url
                        full_url = f"{base}/{href}"
                    
                    # FILTER OUT: Already visited URLs (prevent duplicate visits)
                    # Normalize URL for comparison (remove trailing slashes, lowercase)
                    normalized_url = full_url.rstrip('/').lower()
                    visited_normalized = {u.rstrip('/').lower() for u in self.visited_urls}
                    if normalized_url in visited_normalized:
                        print(f"   ⏭️  Skipping already visited URL: {full_url}")
                        continue  # Skip already visited links
                    
                    # IMPROVEMENT 3: Build stable selector (avoids dynamic text)
                    selector = await self._build_stable_selector(link, text, href, link_id, data_testid)
                    
                    links.append({
                        "url": full_url,
                        "text": text,  # Keep original text for display/logging
                        "selector": selector,  # Use stable selector
                        "href": href
                    })
            
            # Also discover JavaScript-based navigation links (no href, uses role="link" or click handlers)
            # These are common in React Router and other SPA frameworks
            # Find ALL elements with role="link" or <a> tags that don't have href
            js_nav_elements_all = await page.query_selector_all('[role="link"]:not([href]), a:not([href])')
            print(f"   🔍 Found {len(js_nav_elements_all)} potential JS nav elements (no href)")
            
            # Separate into nav/header elements (priority) and others
            js_nav_elements_nav = []
            js_nav_elements_other = []
            
            for elem in js_nav_elements_all:
                # Check if element is in nav/header area
                try:
                    is_in_nav = await elem.evaluate("""
                        el => {
                            const parent = el.closest('nav, header, [role="navigation"], [data-testid*="nav"], [class*="nav"], [class*="header"]');
                            return parent !== null;
                        }
                    """)
                    if is_in_nav:
                        js_nav_elements_nav.append(elem)
                    else:
                        js_nav_elements_other.append(elem)
                except:
                    # If evaluation fails, add to others
                    js_nav_elements_other.append(elem)
            
            print(f"   📍 Nav/header JS links: {len(js_nav_elements_nav)}, Other JS links: {len(js_nav_elements_other)}")
            
            # Combine: nav elements first (higher priority), then others
            js_nav_elements = js_nav_elements_nav + js_nav_elements_other
            
            # CRITICAL: Collect all metadata BEFORE clicking any elements
            # Once we click and navigate, ElementHandle objects become invalid
            js_nav_metadata = []
            
            for js_link in js_nav_elements:
                try:
                    # FILTER OUT: Elements inside form controls or filters
                    is_in_form_control = await js_link.evaluate("""
                        el => {
                            const parent = el.closest('form, .filter, .date-picker, .datepicker, [role="combobox"], [role="listbox"], [role="menu"], [role="menuitem"]');
                            if (parent && !parent.closest('nav, header')) return true;  // Allow nav menus
                            const tagName = el.tagName.toLowerCase();
                            if (tagName === 'input' || tagName === 'select') return true;
                            return false;
                        }
                    """)
                    if is_in_form_control:
                        continue
                    
                    # Check if element is disabled
                    is_disabled = await js_link.get_attribute('aria-disabled')
                    if is_disabled == 'true':
                        continue  # Skip disabled links
                    
                    text = (await js_link.inner_text()).strip()
                    link_id = await js_link.get_attribute('id')
                    data_testid = await js_link.get_attribute('data-testid')
                    class_name = await js_link.get_attribute('class') or ''
                    
                    # Skip if no meaningful text (likely not a navigation link)
                    if not text or len(text.strip()) < 2:
                        continue
                    
                    # Skip filter-related text (but allow common nav items like "Home", "Sales", etc.)
                    text_lower = text.lower()
                    filter_indicators = ['q1', 'q2', 'q3', 'q4', 'quarter', 'date', 'filter', 'select date']
                    # Only skip if it's clearly a filter AND not a common nav item
                    common_nav_items = ['home', 'sales', 'renewals', 'programs', 'learn', 'marketing', 'tools', 'settings', 'profile', 'dashboard']
                    if any(indicator in text_lower for indicator in filter_indicators) and text_lower not in common_nav_items:
                        continue
                    
                    # Build selector for this element (for re-querying after navigation)
                    selector = None
                    if link_id:
                        selector = f"[id='{link_id}']"
                    elif data_testid:
                        selector = f"[data-testid='{data_testid}']"
                    elif text:
                        text_clean = text.replace("'", "\\'").replace('"', '\\"')
                        selector = f"[role='link']:has-text('{text_clean[:50]}')"
                    elif class_name:
                        classes = class_name.split()
                        meaningful_classes = [c for c in classes if c and len(c) > 3 and not c.startswith('data-')]
                        if meaningful_classes:
                            selector = f".{meaningful_classes[0]}"
                    
                    if not selector:
                        # Last resort: use text with role
                        text_clean = text.replace("'", "\\'").replace('"', '\\"')
                        selector = f"[role='link']:has-text('{text_clean[:30]}')"
                    
                    # Store metadata for later processing
                    js_nav_metadata.append({
                        'text': text,
                        'text_normalized': text.strip().lower(),
                        'link_id': link_id,
                        'data_testid': data_testid,
                        'class_name': class_name,
                        'selector': selector
                    })
                except Exception as e:
                    # If we can't get metadata, skip this element
                    print(f"   ⚠️  Error collecting JS nav metadata: {e}")
                    continue
            
            print(f"   📋 Collected metadata for {len(js_nav_metadata)} JS nav elements")
            
            # Track which links we've already discovered (by text) to avoid duplicates
            discovered_js_links = set()
            
            # Now process each element by re-querying it (ElementHandles are invalid after navigation)
            for metadata in js_nav_metadata:
                text = metadata['text']
                text_normalized = metadata['text_normalized']
                selector = metadata['selector']
                
                # Skip if we've already discovered a link with this text (avoid duplicates)
                if text_normalized in discovered_js_links:
                    continue
                
                # Try to discover the target URL by clicking and observing navigation
                # Store current URL before click
                current_url_before = page.url
                
                try:
                    # Re-query the element using selector (ElementHandle is invalid after navigation)
                    js_link = await page.query_selector(selector)
                    if not js_link:
                        # Try alternative selectors if primary fails
                        if metadata['link_id']:
                            js_link = await page.query_selector(f"#{metadata['link_id']}")
                        elif metadata['data_testid']:
                            js_link = await page.query_selector(f"[data-testid='{metadata['data_testid']}']")
                        elif text:
                            text_clean = text.replace("'", "\\'").replace('"', '\\"')
                            js_link = await page.query_selector(f":has-text('{text_clean}')")
                    
                    if not js_link:
                        print(f"   ⚠️  Could not find JS nav element: {text}")
                        continue
                    
                    # Click the element to trigger navigation
                    await js_link.click(timeout=5000)
                    
                    # Wait for URL change (React Router can take time)
                    # Poll for URL change up to 3 seconds
                    url_changed = False
                    target_url = None
                    for wait_attempt in range(6):  # 6 attempts * 0.5s = 3s max wait
                        await asyncio.sleep(0.5)
                        current_url_after = page.url
                        if current_url_after != current_url_before:
                            url_changed = True
                            target_url = current_url_after
                            break
                    
                    if url_changed and target_url:
                        # URL changed - this is a navigation link
                        
                        # Check if it's same domain
                        target_parsed = urlparse(target_url)
                        target_domain = target_parsed.netloc.split(':')[0]
                        if target_domain != base_domain:
                            # Different domain - skip
                            # Navigate back to original page
                            try:
                                await page.goto(current_url_before, wait_until="load", timeout=10000)
                            except:
                                pass
                            continue
                        
                        # Check if already visited
                        normalized_url = target_url.rstrip('/').lower()
                        visited_normalized = {u.rstrip('/').lower() for u in self.visited_urls}
                        if normalized_url in visited_normalized:
                            print(f"   ⏭️  Skipping already visited JS nav link: {text} → {target_url}")
                            # Navigate back to original page
                            try:
                                await page.goto(current_url_before, wait_until="load", timeout=10000)
                            except:
                                pass
                            discovered_js_links.add(text_normalized)  # Mark as discovered
                            continue
                        
                        # Use selector from metadata (already built)
                        links.append({
                            "url": target_url,
                            "text": text,
                            "selector": selector,
                            "href": None,  # No href - JS-based navigation
                            "js_navigation": True  # Mark as JS-based navigation
                        })
                        
                        print(f"   🔗 Discovered JS nav link: {text} → {target_url}")
                        discovered_js_links.add(text_normalized)  # Mark as discovered
                        
                        # Navigate back to original page to continue discovery
                        try:
                            await page.goto(current_url_before, wait_until="load", timeout=10000)
                            await wait_for_active_requests_complete(page, timeout=5000)
                            await asyncio.sleep(0.5)
                        except:
                            # If navigation back fails, we're on a new page - that's okay
                            # But we should continue from here
                            pass
                    else:
                        # URL didn't change - might be a button that opens modal/form, not navigation
                        # Or it might be the current page (active link)
                        # Navigate back if we're not on the original page (shouldn't happen, but safety check)
                        if page.url != current_url_before:
                            try:
                                await page.goto(current_url_before, wait_until="load", timeout=10000)
                            except:
                                pass
                        # Don't add to discovered_js_links - might be a different type of element
                except Exception as e:
                    # Click failed or navigation failed - skip this element
                    # Try to navigate back if we're not on original page
                    try:
                        if page.url != current_url_before:
                            await page.goto(current_url_before, wait_until="load", timeout=10000)
                    except:
                        pass
                    # Don't mark as discovered - might retry later
                    continue
            
            # Also check navigation buttons (like in our Navigation component)
            # BUT exclude form controls and filters
            nav_buttons = await page.query_selector_all('nav a, .navigation a, [data-testid^="nav-"]')
            for btn in nav_buttons:
                # FILTER OUT: Form controls and filters (same logic as above)
                try:
                    is_in_form_control = await btn.evaluate("""
                        el => {
                            const parent = el.closest('form, .filter, .date-picker, .datepicker, [role="combobox"], [role="listbox"]');
                            if (parent) return true;
                            const tagName = el.tagName.toLowerCase();
                            if (tagName === 'input' || tagName === 'select') return true;
                            return false;
                        }
                    """)
                    if is_in_form_control:
                        continue
                except:
                    pass
                
                href = await btn.get_attribute('href')
                if href and href not in [l['href'] for l in links]:
                    # FILTER OUT: Non-HTTP links (mailto, tel, javascript, etc.) - note but don't visit
                    non_http_protocols = ['mailto:', 'tel:', 'javascript:', 'sms:', 'ftp:', 'file:']
                    if any(href.lower().startswith(proto) for proto in non_http_protocols):
                        # Note the link but don't add it to navigation links (can't visit it)
                        print(f"   📎 Found non-HTTP link (not visiting): {href}")
                        continue
                    
                    # FILTER OUT: Query-parameter-only links
                    href_clean = href.split('?')[0].split('#')[0]
                    if not href_clean or href_clean == '' or href_clean == '/':
                        if href.startswith('?') or href.startswith('#'):
                            continue
                    
                    text = (await btn.inner_text()).strip()
                    text_lower = text.lower()
                    
                    # FILTER OUT: Filter-related text
                    filter_indicators = ['q1', 'q2', 'q3', 'q4', 'quarter', 'date', 'filter', 'select date']
                    if any(indicator in text_lower for indicator in filter_indicators):
                        if href.startswith('?') or href.startswith('#') or len(href.split('/')) <= 2:
                            continue
                    
                    data_testid = await btn.get_attribute('data-testid')
                    btn_id = await btn.get_attribute('id')
                    
                    if href.startswith('/'):
                        full_url = f"{self.base_url}{href}"
                    elif href.startswith('http'):
                        full_url = href
                        # IMPROVEMENT 1: Domain filtering
                        link_parsed = urlparse(full_url)
                        link_domain = link_parsed.netloc.split(':')[0]
                        if link_domain != base_domain:
                            continue  # Skip different domains
                    else:
                        continue
                    
                    # FILTER OUT: Already visited URLs (prevent duplicate visits)
                    # Normalize URL for comparison (remove trailing slashes, lowercase)
                    normalized_url = full_url.rstrip('/').lower()
                    visited_normalized = {u.rstrip('/').lower() for u in self.visited_urls}
                    if normalized_url in visited_normalized:
                        print(f"   ⏭️  Skipping already visited URL: {full_url}")
                        continue  # Skip already visited links
                    
                    # IMPROVEMENT 3: Build stable selector
                    selector = await self._build_stable_selector(btn, text, href, btn_id, data_testid)
                    
                    links.append({
                        "url": full_url,
                        "text": text,
                        "selector": selector,
                        "href": href
                    })
            
        except Exception as e:
            print(f"   ⚠️ Error discovering links: {e}")
        
        return links
    
    async def discover_all_routes(self, page: Page, start_url: str, max_depth: int = 3, current_depth: int = 0):
        """Override to filter links using custom base_url."""
        if current_depth >= max_depth:
            return
        
        # Check if this is a parameterized route we've already discovered
        # Use parent's normalize_parameterized_route but with custom base_url
        url_path = start_url.replace(self.base_url, '')
        pattern = r'^(.+)/(\d+)$'
        match = re.match(pattern, url_path)
        
        template_url = start_url
        param_name = None
        if match:
            base_path = match.group(1)
            param_value = match.group(2)
            if '/products' in base_path:
                param_name = 'productId'
                template = f"{base_path}/{{productId}}"
            elif '/orders' in base_path:
                param_name = 'orderId'
                template = f"{base_path}/{{orderId}}"
            elif '/users' in base_path:
                param_name = 'userId'
                template = f"{base_path}/{{userId}}"
            else:
                segments = base_path.split('/')
                last_segment = segments[-1] if segments else 'id'
                param_name = f"{last_segment}Id"
                template = f"{base_path}/{{{param_name}}}"
            template_url = f"{self.base_url}{template}"
        
        if param_name and template_url in self.discovered_templates:
            print(f"\n   ⏭️  Skipping {start_url} (template {template_url} already discovered)")
            return
        
        # Discover current page (this navigates to the actual URL in Chromium)
        await self.discover_page(page, start_url)
        
        # Mark template as discovered if this is a parameterized route
        if param_name:
            self.discovered_templates.add(template_url)
            print(f"   📌 Marked template as discovered: {template_url}")
        
        # Get navigation links (from the actual page we just navigated to)
        links = await self.discover_navigation_links(page)
        
        print(f"\n🔗 Found {len(links)} navigation link(s)")
        
        # Filter to only internal routes (same base URL) - use custom base_url
        # Also check for already visited URLs (normalized comparison to prevent duplicates)
        visited_normalized = {u.rstrip('/').lower() for u in self.visited_urls}
        internal_links = []
        for link in links:
            link_url = link['url']
            if link_url.startswith(self.base_url):
                # Normalize URL for comparison
                normalized_link_url = link_url.rstrip('/').lower()
                if normalized_link_url not in visited_normalized:
                    internal_links.append(link)
                else:
                    print(f"   ⏭️  Skipping already visited URL: {link_url}")
        
        # Smart filtering: Group links by template pattern and only visit one per template
        template_groups: Dict[str, List[Dict]] = {}
        non_template_links = []
        
        for link in internal_links:
            # Normalize link URL to check for templates
            link_path = link['url'].replace(self.base_url, '')
            link_match = re.match(pattern, link_path)
            
            link_template = link['url']
            link_param = None
            if link_match:
                base_path = link_match.group(1)
                if '/products' in base_path:
                    link_template = f"{self.base_url}{base_path}/{{productId}}"
                    link_param = 'productId'
                elif '/orders' in base_path:
                    link_template = f"{self.base_url}{base_path}/{{orderId}}"
                    link_param = 'orderId'
                elif '/users' in base_path:
                    link_template = f"{self.base_url}{base_path}/{{userId}}"
                    link_param = 'userId'
                else:
                    segments = base_path.split('/')
                    last_segment = segments[-1] if segments else 'id'
                    link_param = f"{last_segment}Id"
                    link_template = f"{self.base_url}{base_path}/{{{link_param}}}"
            
            if link_param:
                # This is a parameterized route - group by template
                if link_template in self.discovered_templates:
                    # Already discovered this template, skip
                    continue
                
                if link_template not in template_groups:
                    template_groups[link_template] = []
                template_groups[link_template].append(link)
            else:
                # Non-parameterized route - check if already visited (normalized comparison)
                normalized_link_url = link['url'].rstrip('/').lower()
                visited_normalized = {u.rstrip('/').lower() for u in self.visited_urls}
                if normalized_link_url not in visited_normalized:
                    non_template_links.append(link)
                else:
                    print(f"   ⏭️  Skipping already visited URL: {link['url']}")
        
        # For each template, only visit the first instance
        filtered_links = []
        for template_url, template_links in template_groups.items():
            if template_links:
                # Only add the first link from this template group
                filtered_links.append(template_links[0])
                skipped_count = len(template_links) - 1
                if skipped_count > 0:
                    print(f"   ⏭️  Skipping {skipped_count} duplicate instance(s) of template {template_url}")
        
        # Add non-template links
        filtered_links.extend(non_template_links)
        
        # Remove duplicates
        seen_urls = set()
        unique_links = []
        for link in filtered_links:
            if link['url'] not in seen_urls:
                seen_urls.add(link['url'])
                unique_links.append(link)
        
        print(f"   📍 {len(unique_links)} new route(s) to discover (after template deduplication)")
        
        # Get current node ID for edge creation
        current_node_id = None
        current_url = page.url
        for node in self.graph['nodes']:
            if node['url'] == current_url:
                current_node_id = node['id']
                break
        
        # Follow each link (depth-first traversal)
        for link in unique_links:
            try:
                # Verify page is still valid before navigation
                try:
                    _ = page.url
                    _ = page.context
                except Exception as page_err:
                    print(f"   ❌ Page is no longer valid: {page_err}")
                    raise RuntimeError(f"Cannot navigate - page/context was closed. This may indicate a session issue.")
                
                print(f"\n   🔗 Following: {link['text']} → {link['url']}")
                
                # Check if this is a JavaScript-based navigation link (no href)
                is_js_nav = link.get('js_navigation', False) or link.get('href') is None
                
                if is_js_nav:
                    # For JS navigation links, click the element instead of using page.goto()
                    selector = link.get('selector')
                    if selector:
                        try:
                            print(f"      🖱️  Clicking JS nav link: {selector}")
                            await page.click(selector, timeout=5000)
                            # Wait for navigation/redirect to complete
                            await asyncio.sleep(1)
                            # Wait for active requests to complete
                            await wait_for_active_requests_complete(page, timeout=30000)
                            
                            # Verify we navigated to the expected URL
                            current_url = page.url.rstrip('/').lower()
                            expected_url = link['url'].rstrip('/').lower()
                            if current_url != expected_url:
                                print(f"      ⚠️  Navigation mismatch: expected {link['url']}, got {page.url}")
                                # Continue anyway - might have redirected
                            
                            print(f"      ✅ JS nav link clicked, page loaded: {page.url}")
                        except Exception as click_err:
                            print(f"      ⚠️  Failed to click JS nav link: {click_err}")
                            continue  # Skip this link and continue
                    else:
                        print(f"      ⚠️  No selector for JS nav link, skipping")
                        continue
                else:
                    # Regular link with href - use page.goto()
                    try:
                        print(f"      ⏳ Waiting for page load and active requests to complete...")
                        await page.goto(link['url'], wait_until="load", timeout=60000)
                        # Wait for active requests to complete (more reliable than networkidle)
                        await wait_for_active_requests_complete(page, timeout=30000)
                        print(f"      ✅ Page loaded and active requests completed")
                    except Exception as nav_err:
                        # If load fails, try domcontentloaded
                        print(f"      ⚠️  Load timeout, trying domcontentloaded...")
                        try:
                            await page.goto(link['url'], wait_until="domcontentloaded", timeout=30000)
                            await wait_for_active_requests_complete(page, timeout=20000)
                            print(f"      ✅ Page loaded (domcontentloaded) and active requests completed")
                        except Exception as nav_err2:
                            print(f"      ⚠️ Failed to navigate to {link['url']}: {nav_err2}")
                            # Verify page is still valid
                            try:
                                _ = page.url
                            except:
                                print(f"      ❌ Page became invalid after navigation failure")
                                raise RuntimeError(f"Page/context was closed during navigation to {link['url']}")
                            continue  # Skip this link and continue
                
                # Recursively discover this page (will add to visited_urls and create node)
                await self.discover_all_routes(page, link['url'], max_depth, current_depth + 1)
                
                # After discovery, create edge from current page to linked page
                if current_node_id:
                    # Find the target node ID (should exist now after discovery)
                    target_node_id = None
                    link_path = link['url'].replace(self.base_url, '')
                    link_match = re.match(pattern, link_path)
                    link_template = link['url']
                    if link_match:
                        base_path = link_match.group(1)
                        if '/products' in base_path:
                            link_template = f"{self.base_url}{base_path}/{{productId}}"
                        elif '/orders' in base_path:
                            link_template = f"{self.base_url}{base_path}/{{orderId}}"
                        elif '/users' in base_path:
                            link_template = f"{self.base_url}{base_path}/{{userId}}"
                        else:
                            segments = base_path.split('/')
                            last_segment = segments[-1] if segments else 'id'
                            link_template = f"{self.base_url}{base_path}/{{{last_segment}Id}}"
                    
                    # First try to find exact match
                    for node in self.graph['nodes']:
                        if node.get('url') == link['url']:
                            target_node_id = node['id']
                            break
                    
                    # If not found and it's a template, find template node
                    if not target_node_id and link_template != link['url']:
                        for node in self.graph['nodes']:
                            if node.get('url') == link_template or node.get('url_template') == link_template:
                                target_node_id = node['id']
                                break
                    
                    if target_node_id and current_node_id != target_node_id:
                        # Check if edge already exists
                        edge_exists = any(
                            (e.get('from') == current_node_id or e.get('from') == current_url) and 
                            (e.get('to') == target_node_id or e.get('to') == link['url'])
                            for e in self.graph['edges']
                        )
                        if not edge_exists:
                            self.graph['edges'].append({
                                "from": current_node_id,
                                "to": target_node_id,
                                "action": "navigate",
                                "selector": link['selector']
                            })
                            print(f"      ✅ Created edge: {current_node_id} → {target_node_id}")
                
            except Exception as e:
                print(f"   ⚠️ Failed to follow link {link['url']}: {e}")
                continue


async def main():
    print("=" * 70)
    print("🚀 SEMANTIC MAPPER WITH GATEWAY")
    print("=" * 70)
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", required=True, help="internal|reseller|distributor")
    parser.add_argument("--gateway-instructions", default=None, help="Path to NL gateway instructions txt (optional - skip if not needed)")
    parser.add_argument("--storage-state", required=True, help="Path to write/read storage state JSON")
    parser.add_argument("--output", default="semantic_graph.json", help="Output graph json")
    parser.add_argument("--base-url", default=CONFIG["BASE_URL"], help="Base URL to open")
    parser.add_argument("--headless", default="false", help="true|false")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--skip-gateway", action="store_true")
    parser.add_argument("--llm-provider", default="nutanix", choices=["nutanix", "ollama"], help="LLM provider to use for page analysis (many calls)")
    parser.add_argument("--gateway-llm-provider", default="nutanix", choices=["nutanix", "ollama"], help="LLM provider to use for gateway compilation (1 call, critical - recommend nutanix)")
    parser.add_argument("--ollama-model", default="llama3.1:8b", help="Ollama model name (when using ollama provider)")
    args = parser.parse_args()

    print(f"📋 Configuration:")
    print(f"   Persona: {args.persona}")
    print(f"   Base URL: {args.base_url}")
    print(f"   Page Analysis LLM: {args.llm_provider}")
    print(f"   Gateway Compilation LLM: {args.gateway_llm_provider}")
    print(f"   Gateway Instructions: {args.gateway_instructions or 'None'}")
    print()

    headless = args.headless.lower() == "true"

    # Load env for LLM
    print("🔧 Loading environment configuration...")
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"✅ Loaded .env from {env_file}")
    else:
        print(f"⚠️  No .env file found at {env_file}")

    # Initialize LLM for page analysis (many calls)
    print(f"\n🤖 Initializing Page Analysis LLM ({args.llm_provider})...")
    if args.llm_provider == "nutanix":
        api_url = os.getenv("NUTANIX_API_URL")
        api_key = os.getenv("NUTANIX_API_KEY")
        model = os.getenv("NUTANIX_MODEL", "openai/gpt-oss-120b")

        if not api_url or not api_key:
            raise RuntimeError("Missing NUTANIX_API_URL or NUTANIX_API_KEY in .env")

        print(f"   API URL: {api_url}")
        print(f"   Model: {model}")
        llm = FixedNutanixChatModel(api_url=api_url, api_key=api_key, model_name=model)
        print("✅ Nutanix LLM initialized")
    elif args.llm_provider == "ollama":
        from langchain_community.llms import Ollama
        print(f"   Model: {args.ollama_model}")
        llm = Ollama(model=args.ollama_model)
        print("✅ Ollama LLM initialized")
    else:
        raise ValueError(f"Unsupported LLM provider: {args.llm_provider}")

    # Initialize LLM for gateway compilation (1 call, critical - recommend GPT-OSS)
    print(f"\n🤖 Initializing Gateway Compilation LLM ({args.gateway_llm_provider})...")
    if args.gateway_llm_provider == "nutanix":
        api_url = os.getenv("NUTANIX_API_URL")
        api_key = os.getenv("NUTANIX_API_KEY")
        model = os.getenv("NUTANIX_MODEL", "openai/gpt-oss-120b")

        if not api_url or not api_key:
            raise RuntimeError("Missing NUTANIX_API_URL or NUTANIX_API_KEY in .env")

        gateway_llm = FixedNutanixChatModel(api_url=api_url, api_key=api_key, model_name=model)
        print("✅ Gateway LLM (Nutanix GPT-OSS) initialized")
    elif args.gateway_llm_provider == "ollama":
        from langchain_community.llms import Ollama
        print(f"   Model: {args.ollama_model}")
        print(f"   ⚠️  Warning: Ollama may struggle with complex gateway instructions")
        gateway_llm = Ollama(model=args.ollama_model)
        print("✅ Gateway LLM (Ollama) initialized")
    else:
        raise ValueError(f"Unsupported gateway LLM provider: {args.gateway_llm_provider}")

    storage_state_path = Path(args.storage_state)
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n🌐 Launching browser (headless={headless})...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        print("✅ Browser launched")

        # Check if storage_state exists and is valid - if so, skip gateway automatically
        storage_state_exists = storage_state_path.exists() and storage_state_path.stat().st_size > 0
        
        if args.skip_gateway:
            if not storage_state_exists:
                raise RuntimeError(f"--skip-gateway set but storage state not found: {storage_state_path}")
            print(f"\n📄 Loading existing storage state from: {storage_state_path}")
            context = await browser.new_context(storage_state=str(storage_state_path))
            page = await context.new_page()
            print("✅ Context created with saved storage state")
            
            # Navigate to base URL to verify session is still valid
            print(f"\n🌐 Navigating to base URL: {args.base_url}")
            try:
                print(f"   ⏳ Waiting for page load and active requests to complete...")
                await page.goto(args.base_url, wait_until="load", timeout=60000)
                await wait_for_active_requests_complete(page, timeout=30000)
                print(f"   ✅ Page loaded and active requests completed: {page.url}")
            except Exception as e:
                print(f"   ⚠️  Navigation warning: {e}")
                print(f"   Current URL: {page.url}")
        elif storage_state_exists:
            # Storage state exists - load it and skip gateway (no LLM call needed!)
            print(f"\n📄 Found existing storage state: {storage_state_path}")
            print(f"   ✅ Loading saved authentication session (skipping gateway LLM compilation)")
            context = await browser.new_context(storage_state=str(storage_state_path))
            page = await context.new_page()
            print("✅ Context created with saved storage state")
            
            # Navigate to base URL
            print(f"\n🌐 Navigating to base URL: {args.base_url}")
            try:
                print(f"   ⏳ Waiting for page load and active requests to complete...")
                await page.goto(args.base_url, wait_until="load", timeout=60000)
                await wait_for_active_requests_complete(page, timeout=30000)
                print(f"   ✅ Page loaded and active requests completed: {page.url}")
            except Exception as e:
                print(f"   ⚠️  Navigation warning: {e}")
                print(f"   Current URL: {page.url}")
            
            # Skip gateway execution - we already have authenticated session
            print("\n" + "=" * 70)
            print("⏭️  SKIPPING GATEWAY (using existing storage state)")
            print("=" * 70)
            print(f"📋 Persona: {args.persona}")
            print(f"💾 Loaded storage state from: {storage_state_path}")
            print(f"🌐 Starting from: {page.url}")
        else:
            # No storage state exists - create fresh context and run gateway
            print(f"\n📄 Creating fresh browser context (no existing storage state found)...")
            context = await browser.new_context()
            page = await context.new_page()
            print("✅ Context created")

            # Start at base URL
            print(f"\n🌐 Navigating to base URL: {args.base_url}")
            try:
                print(f"   ⏳ Waiting for page load and active requests to complete...")
                await page.goto(args.base_url, wait_until="load", timeout=60000)
                # Wait for active requests to complete (more reliable than networkidle)
                await wait_for_active_requests_complete(page, timeout=30000)
                print(f"   ✅ Page loaded and active requests completed: {page.url}")
            except Exception as e:
                # If load fails, try domcontentloaded
                print(f"   ⚠️  Load timeout, trying domcontentloaded...")
                try:
                    await page.goto(args.base_url, wait_until="domcontentloaded", timeout=30000)
                    await wait_for_active_requests_complete(page, timeout=20000)
                    print(f"   ✅ Page loaded (domcontentloaded) and active requests completed: {page.url}")
                except Exception as e2:
                    print(f"   ⚠️  Navigation warning: {e2}")
                    print(f"   Current URL: {page.url}")
                    # Continue anyway - page might be partially loaded

            # Check if we should run gateway
            should_run_gateway = False
            instructions = ""

            if args.gateway_instructions:
                gateway_file = Path(args.gateway_instructions)
                if gateway_file.exists():
                    instructions = gateway_file.read_text().strip()
                    if instructions:  # Only run gateway if file has content
                        should_run_gateway = True

            if should_run_gateway:
                print("\n" + "=" * 70)
                print("🚪 GATEWAY EXECUTION")
                print("=" * 70)
                print(f"📋 Persona: {args.persona}")
                print(f"📄 Instructions: {args.gateway_instructions}")
                print(f"🎯 Goal: Navigate to starting point for semantic mapping")
                print(f"🌐 Current URL: {page.url}")
                
                print("\n📸 Collecting UI snapshot...")
                snapshot = await collect_ui_snapshot(page)
                print(f"✅ Snapshot collected: {len(snapshot.get('elements', []))} interactive elements found")
                
                print("\n🤖 Compiling gateway plan with LLM...")
                prompt = build_gateway_compile_prompt(
                    persona=args.persona,
                    instructions=instructions,
                    snapshot=snapshot,
                    base_url=args.base_url,
                    storage_state_path=str(storage_state_path),
                )

                plan = await compile_gateway_plan(gateway_llm, prompt)
                print("✅ Gateway plan compiled successfully")
                print("\n=== COMPILED GATEWAY PLAN ===")
                print(json.dumps(plan, indent=2))

                await execute_gateway_plan(page, plan)
                print(f"\n✅ Gateway execution completed")
                
                # Save storage state after gateway execution
                print(f"\n💾 Saving storage state to: {storage_state_path} (for future reuse)")
                await context.storage_state(path=str(storage_state_path))
                print(f"✅ Storage state saved")
            else:
                print("\n" + "=" * 70)
                print("⏭️  SKIPPING GATEWAY")
                print("=" * 70)
                print(f"📋 Persona: {args.persona}")
                if not args.gateway_instructions:
                    print("ℹ️  No gateway instructions provided - starting directly from base URL")
                else:
                    gateway_file = Path(args.gateway_instructions)
                    if not gateway_file.exists():
                        print(f"⚠️  Gateway file not found: {args.gateway_instructions}")
                    elif not instructions:
                        print(f"ℹ️  Gateway file is empty - starting directly from base URL")
                print(f"🌐 Starting from: {page.url}")
                
                # Save storage state even if no gateway was run (for future reuse)
                print(f"\n💾 Saving storage state to: {storage_state_path} (for future reuse)")
                await context.storage_state(path=str(storage_state_path))
                print(f"✅ Storage state saved")
            
            print(f"ℹ️  Continuing with same browser session (no context restart needed)")
            
            # Keep using the same context and page - don't close/reopen!
            # The storage_state is saved for future runs, but we maintain the current session

        # ----------------------------
        # Run semantic mapping
        # ----------------------------
        print("\n" + "=" * 70)
        print("🧬 Starting Semantic Mapping")
        print("=" * 70)
        
        mapper = SemanticMapperWithPersona(llm, persona=args.persona, base_url=args.base_url)

        # Setup network interception (existing mapper method)
        await mapper.setup_network_interception(page)

        # Start discovery from current page URL (after gateway) or base_url (if no gateway)
        # This maintains the authenticated session state
        start_url = page.url if page.url != args.base_url else args.base_url
        print(f"🌐 Starting discovery from: {start_url}")
        await mapper.discover_all_routes(page, start_url, max_depth=args.max_depth)

        # Interact with forms/buttons to discover APIs (reuse your existing loop)
        # Track which buttons/forms we've already tested to avoid duplicate testing
        # Use button role + selector as unique identifier (same button on different pages = same button)
        tested_buttons = set()  # Track by (role, selector) tuple
        tested_forms = set()  # Track by (role, selector) tuple
        tested_pages = set()  # Track pages we've navigated to
        
        for node in mapper.graph.get("nodes", []):
            try:
                node_url = node["url"]
                # Normalize URL for comparison
                normalized_node_url = node_url.rstrip('/').lower()
                
                # Check if we're already on this page (avoid unnecessary navigation)
                current_url = page.url.rstrip('/').lower()
                needs_navigation = current_url != normalized_node_url
                
                # Only navigate if we need to AND haven't tested this page's buttons/forms yet
                # But we still need to check if buttons/forms on this page have been tested
                has_untested_components = False
                
                # Check if this page has any untested buttons/forms
                for component in node.get("components", []):
                    if component.get("type") == "button":
                        btn_role = component.get("role", "")
                        btn_selector = component.get("selector", "")
                        btn_text = (component.get("text") or "").lower()
                        btn_role_lower = btn_role.lower()
                        if any(k in btn_text or k in btn_role_lower for k in ["add", "create", "new", "open"]):
                            button_key = (btn_role, btn_selector)
                            if button_key not in tested_buttons:
                                has_untested_components = True
                                break
                    elif component.get("type") == "form":
                        form_role = component.get("role", "")
                        form_selector = component.get("selector", "")
                        form_key = (form_role, form_selector)
                        if form_key not in tested_forms:
                            has_untested_components = True
                            break
                
                # Skip this page if all its buttons/forms have already been tested
                if not has_untested_components:
                    print(f"   ⏭️  Skipping {node_url} - all buttons/forms already tested")
                    continue
                
                # Check if this page was already visited during discovery phase
                # Normalize visited_urls for comparison
                visited_during_discovery = {u.rstrip('/').lower() for u in mapper.visited_urls}
                was_visited_during_discovery = normalized_node_url in visited_during_discovery
                
                # CRITICAL: If page was already visited during discovery, don't navigate to it again
                # Only test buttons/forms if we're already on that page
                if was_visited_during_discovery:
                    if needs_navigation:
                        # Page was visited during discovery but we're not on it now - skip it
                        # (We don't want to revisit pages that were already visited)
                        print(f"   ⏭️  Skipping {node_url} - already visited during discovery, won't navigate again")
                        continue
                    else:
                        # We're already on this page (from discovery), test buttons/forms without navigation
                        print(f"   ℹ️  Already on page {node_url} (visited during discovery), testing buttons/forms")
                        await asyncio.sleep(0.5)
                elif needs_navigation:
                    # Page was NOT visited during discovery, navigate to it for button/form testing
                    if normalized_node_url not in tested_pages:
                        print(f"   🔄 Navigating to {node_url} for button/form testing")
                        try:
                            await page.goto(node_url, wait_until="load", timeout=60000)
                            # Wait for active requests to complete (more reliable than networkidle)
                            await wait_for_active_requests_complete(page, timeout=30000)
                        except:
                            # If load fails, try domcontentloaded
                            try:
                                await page.goto(node_url, wait_until="domcontentloaded", timeout=30000)
                                await wait_for_active_requests_complete(page, timeout=20000)
                            except:
                                print(f"   ⚠️  Failed to navigate to {node_url}, skipping button/form testing")
                                tested_pages.add(normalized_node_url)  # Mark as tested to avoid retry
                                continue
                        await asyncio.sleep(1)
                        tested_pages.add(normalized_node_url)
                    else:
                        # Already tested this page in button/form testing phase
                        print(f"   ⏭️  Skipping {node_url} - already tested in button/form phase")
                        continue
                else:
                    # Already on this page (not visited during discovery)
                    print(f"   ℹ️  Already on page {node_url}, testing buttons/forms without navigation")
                    await asyncio.sleep(0.5)

                # Test buttons (only if not already tested)
                for component in node.get("components", []):
                    if component.get("type") == "button":
                        btn_text = (component.get("text") or "").lower()
                        btn_role = component.get("role", "")
                        btn_role_lower = btn_role.lower()
                        btn_selector = component.get("selector", "")
                        
                        if any(k in btn_text or k in btn_role_lower for k in ["add", "create", "new", "open"]):
                            button_key = (btn_role, btn_selector)
                            if button_key not in tested_buttons:
                                await mapper.try_button_opens_form(page, component, node)
                                tested_buttons.add(button_key)  # Mark as tested
                            else:
                                print(f"   ⏭️  Skipping already tested button: {btn_role}")

                # Test forms (only if not already tested)
                for component in node.get("components", []):
                    if component.get("type") == "form":
                        form_role = component.get("role", "")
                        form_selector = component.get("selector", "")
                        form_key = (form_role, form_selector)
                        
                        if form_key not in tested_forms:
                            await mapper.try_form_interaction(page, component, node)
                            tested_forms.add(form_key)  # Mark as tested
                        else:
                            print(f"   ⏭️  Skipping already tested form: {form_role}")
            except Exception:
                continue

        # Merge parameterized nodes (existing method)
        mapper.merge_parameterized_nodes()

        # Tag all nodes with persona context if missing
        for n in mapper.graph.get("nodes", []):
            n.setdefault("context", {})
            n["context"]["persona"] = args.persona

        # Add entrypoint for this persona if missing
        mapper.graph.setdefault("entrypoints", {})
        if args.persona not in mapper.graph["entrypoints"]:
            # crude: first node is the entrypoint
            if mapper.graph.get("nodes"):
                mapper.graph["entrypoints"][args.persona] = mapper.graph["nodes"][0]["id"]

        # Save graph
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(mapper.graph, indent=2))
        print(f"\n✅ Semantic graph saved to: {out_path}")
        
        # Automatically index graph to ChromaDB for semantic search
        print("\n" + "=" * 70)
        print("📚 Indexing graph to ChromaDB for semantic search")
        print("=" * 70)
        try:
            from graph_queries import GraphQueries
            graph_queries = GraphQueries(graph_path=str(out_path))
            graph_queries.index_graph_to_chromadb(force_reindex=True)
            print(f"✅ Graph indexed successfully to ChromaDB")
        except Exception as e:
            print(f"⚠️  ChromaDB indexing failed (will use text-based search): {e}")
            import traceback
            traceback.print_exc()

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())