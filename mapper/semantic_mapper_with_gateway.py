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
    storage_state_path: Optional[str] = None,
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
4. **MUST CONVERT EVERY NUMBERED STEP** - If instructions have 10 numbered steps, you MUST create 10 steps in the plan. Do NOT skip any steps. Count the numbered steps in the instructions and ensure your plan has the same number of steps.
5. **Follow instructions in order** - Convert each numbered instruction into exactly one step (or wait/assert step). The last step in instructions must be the last step in your plan.

CONTEXT:
- Target app base URL: {base_url}
- Target app domain: {base_domain}
- Persona identifier: {persona}
- Follow the instructions exactly as provided. Do not add steps or verifications not mentioned in the instructions.

OUTPUT REQUIREMENTS:
- Output ONLY valid JSON.
- Allowed actions: {sorted(list(ALLOWED_ACTIONS))}
- Every click/fill/select/wait_visible must include "selector".

SELECTOR PRIORITY (CRITICAL - for buttons/links mentioned in instructions):
1. **ALWAYS prefer ID if available** - If snapshot shows `id` attribute (e.g., `id="legend-link-Expansion"`), use: `#legend-link-Expansion`
   - This is especially important for elements with dynamic text content (e.g., "$24.88M (58)" which changes over time)
   - IDs are stable and don't change when content updates
2. **If snapshot shows data-testid**, use: `[data-testid='...']`
3. **If snapshot shows aria-label**, use: `[aria-label='...']`
4. **Only use text-based selectors as last resort** - If instructions mention button/link TEXT and no ID/data-testid/aria-label is available, use: `:has-text('Text')` or `button:has-text('Text')`
   - **WARNING**: Avoid text selectors for dynamic content like currency values, counts, percentages, etc.

EXACT TEXT MATCHING (CRITICAL):
- **If instructions say "exactly" or "exact match"** (e.g., "click on div exactly having CDW"), you MUST use exact text matching
- For exact matches in dropdowns/popups, use: `container-selector div:has-text('EXACT_TEXT')` BUT add `"exact_match": true` to the step
- Example: If instructions say "click on div exactly having CDW" and there are options like "CDW US", "CDW Canada", use:
  ```json
  {{"action": "click", "selector": ".view-as-partner-popup div:has-text('CDW')", "exact_match": true}}
  ```
- The `exact_match: true` flag ensures only elements with text content exactly equal to 'CDW' (not 'CDW US' or 'CDW Canada') are selected

IMPORTANT: When instructions mention button text in natural language (e.g., "Click on 'X' button"), ALWAYS check the snapshot for ID/data-testid/aria-label FIRST. Only use text-based selectors if no stable identifier is available. This is critical for elements with dynamic content (currency, counts, etc.).

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
{f"- Optionally include final step save_storage_state with path \"{storage_state_path}\" (for reference only, not required)." if storage_state_path else "- Do NOT include save_storage_state step (using gateway plan instead of storage state)."}

JSON format:
{{
  "persona": "{persona}",
  "goal": "short goal describing what the gateway accomplishes",
  {f'"storage_state_path": "{storage_state_path}",' if storage_state_path else ''}
  "steps": [
    {{ "action": "goto", "url": "{base_url}" }},
    {{ "action": "click", "selector": "..." }},
    {{ "action": "click", "selector": "...", "exact_match": true }},
    {{ "action": "fill", "selector": "...", "value": "..." }}
  ],
  "postconditions": [
    {{ "action": "assert_text", "text": "..." }}
  ]
}}

Note: Use "exact_match": true for click actions when instructions say "exactly" or "exact match" to ensure precise text matching in dropdowns/popups.

Note: "postconditions" array is optional. Only include it if the instructions mention verification steps.

REMINDER: 
- Convert ONLY the steps mentioned in USER INSTRUCTIONS below.
- **CRITICAL: Count the numbered steps in the instructions. Your plan MUST have the same number of steps.**
- **If instructions have step 10, your plan MUST include step 10. Do NOT stop at step 9.**
- Do NOT add cookie consent, privacy dialogs, or any other steps.
- Use the PAGE SNAPSHOT only to find selectors for elements mentioned in instructions.

USER INSTRUCTIONS (follow these EXACTLY, in order - convert EVERY numbered step):
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
                
                # Check if this is an exact text match request
                exact_match = step.get("exact_match", False)
                clicked_exact = False
                
                # Try to click with the provided selector
                try:
                    # Handle exact text matching for dropdowns/popups
                    if exact_match and ":has-text(" in selector:
                        # Extract the text to match exactly and the container selector
                        text_match = re.search(r":has-text\(['\"]([^'\"]+)['\"]\)", selector)
                        if text_match:
                            exact_text = text_match.group(1)
                            # Extract container selector (the main container, not intermediate elements)
                            # For ".view-as-partner-popup div:has-text('CDW')", we want ".view-as-partner-popup"
                            # For ".popup-class:has-text('text')", we want ".popup-class"
                            before_has_text = selector.split(":has-text")[0].strip()
                            
                            # If there's a space, take just the first part (the container class)
                            # e.g., ".view-as-partner-popup div" -> ".view-as-partner-popup"
                            if " " in before_has_text:
                                container_selector = before_has_text.split()[0]
                            else:
                                container_selector = before_has_text
                            
                            if not container_selector:
                                container_selector = ".view-as-partner-popup"  # Default fallback
                            
                            print(f"      🔍 Using container: '{container_selector}' to find exact text: '{exact_text}'")
                            
                            # Wait for dropdown to populate with options containing the search text
                            # This is critical because typing in an input triggers async filtering
                            print(f"      ⏳ Waiting for dropdown to populate with '{exact_text}' options...")
                            max_wait_seconds = 5
                            wait_interval = 0.3
                            waited = 0
                            found_options = False
                            
                            while waited < max_wait_seconds:
                                check_js = f"""
                                () => {{
                                    const spans = Array.from(document.querySelectorAll('span'));
                                    for (const span of spans) {{
                                        const text = (span.innerText || span.textContent || '').trim();
                                        const rect = span.getBoundingClientRect();
                                        if (text.toLowerCase().includes('{exact_text}'.toLowerCase()) && rect.width > 0 && rect.height > 0) {{
                                            return true;
                                        }}
                                    }}
                                    return false;
                                }}
                                """
                                found_options = await page.evaluate(check_js)
                                if found_options:
                                    print(f"      ✅ Dropdown populated after {waited:.1f}s")
                                    break
                                await asyncio.sleep(wait_interval)
                                waited += wait_interval
                            
                            if not found_options:
                                print(f"      ⚠️  Dropdown didn't populate within {max_wait_seconds}s, proceeding anyway...")
                            
                            # Find element with exact text content (not containing additional text)
                            # IMPORTANT: We need strict exact matching to avoid "CDW Canada" matching "CDW"
                            # Strategy: Look for span elements first (where labels typically are), then other elements
                            # Only match if the element's text is EXACTLY the target, with no additional text
                            exact_selector_js = f"""
                            () => {{
                                const container = document.querySelector('{container_selector}') || document;
                                const exactText = '{exact_text}';
                                const candidates = [];
                                
                                // First, try to find span elements (labels are often in spans)
                                const spans = Array.from(container.querySelectorAll('span'));
                                for (const span of spans) {{
                                    const text = (span.innerText || span.textContent || '').trim();
                                    if (text === exactText) {{
                                        const rect = span.getBoundingClientRect();
                                        const isVisible = rect.width > 0 && rect.height > 0 && 
                                                         window.getComputedStyle(span).display !== 'none' &&
                                                         window.getComputedStyle(span).visibility !== 'hidden';
                                        if (isVisible) {{
                                            candidates.push({{element: span, text: text, priority: 1}});
                                        }}
                                    }}
                                }}
                                
                                // If no span found, check other elements, but be more careful
                                if (candidates.length === 0) {{
                                    const elements = Array.from(container.querySelectorAll('div, li, option, a, button'));
                                    for (const el of elements) {{
                                        const fullText = (el.innerText || el.textContent || '').trim();
                                        
                                        // STRICT EXACT MATCH: text must be exactly equal
                                        if (fullText === exactText) {{
                                            // Check if this element directly contains the text (not via children)
                                            // Count direct text nodes
                                            let directText = '';
                                            let hasChildElements = false;
                                            for (const child of el.childNodes) {{
                                                if (child.nodeType === 3) {{ // Text node
                                                    directText += child.textContent;
                                                }} else if (child.nodeType === 1) {{ // Element node
                                                    hasChildElements = true;
                                                }}
                                            }}
                                            directText = directText.trim();
                                            
                                            // If element has child elements AND the direct text doesn't match,
                                            // it means the text comes from children, so skip this parent
                                            if (hasChildElements && directText !== exactText) {{
                                                continue;
                                            }}
                                            
                                            const rect = el.getBoundingClientRect();
                                            const isVisible = rect.width > 0 && rect.height > 0 && 
                                                             window.getComputedStyle(el).display !== 'none' &&
                                                             window.getComputedStyle(el).visibility !== 'hidden';
                                            if (isVisible) {{
                                                candidates.push({{element: el, text: fullText, priority: 2}});
                                            }}
                                        }}
                                    }}
                                }}
                                
                                // Return first candidate (spans have priority 1, others have priority 2)
                                if (candidates.length > 0) {{
                                    // Sort by priority (lower is better)
                                    candidates.sort((a, b) => a.priority - b.priority);
                                    return candidates[0].element;
                                }}
                                
                                return null;
                            }}
                            """
                            try:
                                # Check if container exists and get DETAILED debug info
                                debug_js = f"""
                                () => {{
                                    const exactText = '{exact_text}';
                                    const primarySelector = '{container_selector}';
                                    
                                    // Try to find the container
                                    const containerEl = document.querySelector(primarySelector);
                                    
                                    // Also check common dropdown selectors
                                    const dropdownEl = document.querySelector('.ntnx-select-dropdown') || 
                                                       document.querySelector('[role="listbox"]');
                                    
                                    const container = containerEl || dropdownEl || document;
                                    const containerExists = !!containerEl;
                                    const dropdownExists = !!dropdownEl;
                                    
                                    // Get ALL spans in the document that contain the search text
                                    const allSpans = Array.from(document.querySelectorAll('span'));
                                    const matchingSpans = [];
                                    const exactSpans = [];
                                    
                                    for (const span of allSpans) {{
                                        const text = (span.innerText || span.textContent || '').trim();
                                        const rect = span.getBoundingClientRect();
                                        const isVisible = rect.width > 0 && rect.height > 0;
                                        
                                        if (text.toLowerCase().includes(exactText.toLowerCase())) {{
                                            matchingSpans.push({{
                                                text: text,
                                                visible: isVisible,
                                                width: rect.width,
                                                height: rect.height
                                            }});
                                            
                                            if (text === exactText) {{
                                                exactSpans.push({{
                                                    text: text,
                                                    visible: isVisible,
                                                    width: rect.width,
                                                    height: rect.height,
                                                    parent: span.parentElement?.className || 'unknown'
                                                }});
                                            }}
                                        }}
                                    }}
                                    
                                    return {{ 
                                        primaryContainerExists: containerExists,
                                        dropdownExists: dropdownExists,
                                        containerSelector: primarySelector,
                                        totalSpansInDoc: allSpans.length,
                                        matchingSpans: matchingSpans.slice(0, 20),
                                        exactSpans: exactSpans
                                    }};
                                }}
                                """
                                debug_info = await page.evaluate(debug_js)
                                if debug_info:
                                    print(f"      🔍 Container '{debug_info.get('containerSelector')}' exists: {debug_info.get('primaryContainerExists')}")
                                    print(f"      🔍 Dropdown (.ntnx-select-dropdown or [role=listbox]) exists: {debug_info.get('dropdownExists')}")
                                    print(f"      🔍 Total spans in document: {debug_info.get('totalSpansInDoc')}")
                                    matching = debug_info.get('matchingSpans', [])
                                    print(f"      🔍 Spans containing '{exact_text}': {len(matching)}")
                                    for m in matching[:10]:
                                        print(f"         - '{m.get('text')}' visible={m.get('visible')} ({m.get('width')}x{m.get('height')})")
                                    exact = debug_info.get('exactSpans', [])
                                    if exact:
                                        print(f"      ✅ EXACT MATCHES FOUND: {len(exact)}")
                                        for e in exact:
                                            print(f"         - '{e.get('text')}' visible={e.get('visible')} parent={e.get('parent')}")
                                    else:
                                        print(f"      ❌ NO EXACT MATCHES (text === '{exact_text}')")
                                
                                # Find exact match element and get its coordinates for Playwright click
                                # JavaScript .click() doesn't trigger proper events, so we need Playwright's click
                                find_exact_js = f"""
                                () => {{
                                    const exactText = '{exact_text}';
                                    
                                    // Search all spans in document for exact text match
                                    const spans = Array.from(document.querySelectorAll('span'));
                                    for (const span of spans) {{
                                        const text = (span.innerText || span.textContent || '').trim();
                                        if (text === exactText) {{
                                            const rect = span.getBoundingClientRect();
                                            const isVisible = rect.width > 0 && rect.height > 0 && 
                                                             window.getComputedStyle(span).display !== 'none' &&
                                                             window.getComputedStyle(span).visibility !== 'hidden';
                                            if (isVisible) {{
                                                // Get the clickable target (parent row)
                                                const clickTarget = span.closest('[role="option"]') || span.closest('.select-row') || span;
                                                const targetRect = clickTarget.getBoundingClientRect();
                                                
                                                // Generate a unique selector for the option
                                                let optionSelector = null;
                                                if (clickTarget.id) {{
                                                    optionSelector = '#' + clickTarget.id;
                                                }} else if (clickTarget.getAttribute('role') === 'option') {{
                                                    // Use text-based selector for the option
                                                    optionSelector = `[role="option"]:has(span:text-is("${{exactText}}"))`;
                                                }}
                                                
                                                return {{ 
                                                    success: true, 
                                                    text: text,
                                                    x: targetRect.x + targetRect.width / 2,
                                                    y: targetRect.y + targetRect.height / 2,
                                                    id: clickTarget.id || null,
                                                    optionSelector: optionSelector
                                                }};
                                            }}
                                        }}
                                    }}
                                    
                                    return {{ success: false, reason: 'No exact match found' }};
                                }}
                                """
                                find_result = await page.evaluate(find_exact_js)
                                
                                click_result = None
                                if find_result and find_result.get('success'):
                                    x = find_result.get('x')
                                    y = find_result.get('y')
                                    option_id = find_result.get('id')
                                    
                                    # Try clicking by ID first (most reliable)
                                    if option_id:
                                        try:
                                            await page.click(f'#{option_id}', timeout=3000)
                                            click_result = {'success': True, 'text': find_result.get('text'), 'clicked': 'id-selector'}
                                        except Exception as id_click_err:
                                            print(f"      ⚠️  ID click failed: {id_click_err}")
                                    
                                    # Fall back to coordinate click
                                    if not click_result or not click_result.get('success'):
                                        try:
                                            await page.mouse.click(x, y)
                                            click_result = {'success': True, 'text': find_result.get('text'), 'clicked': 'coordinates'}
                                        except Exception as coord_err:
                                            print(f"      ⚠️  Coordinate click failed: {coord_err}")
                                            click_result = {'success': False, 'reason': str(coord_err)}
                                else:
                                    click_result = find_result or {'success': False, 'reason': 'No exact match found in any container'}
                                if click_result and click_result.get('success'):
                                    print(f"      ✅ Clicked element with exact text match: '{exact_text}' (via {click_result.get('clicked', 'unknown')})")
                                    await asyncio.sleep(0.5)
                                    clicked_exact = True
                                else:
                                    reason = click_result.get('reason', 'unknown') if click_result else 'no result'
                                    print(f"      ⚠️  Exact text match not found: {reason}, trying regular selector...")
                            except Exception as exact_e:
                                print(f"      ⚠️  Exact text match failed: {exact_e}, trying regular selector...")
                    
                    if not clicked_exact:
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
                        # For other fields, try common fallback patterns
                        print(f"      🤖 Primary selector failed, trying fallback patterns...")
                        
                        # If selector is a class, try with input tag prefix
                        if selector.startswith("."):
                            class_name = selector[1:]  # Remove the dot
                            fallback_selectors = [
                                f"input{selector}",  # input.view-as-partner-input
                                f"input[name='{class_name}']",  # input[name='view-as-partner-input']
                                f"[name='{class_name}']",  # [name='view-as-partner-input']
                                selector,  # Original as last resort
                            ]
                        elif "name=" in selector:
                            # Extract name attribute value
                            name_match = re.search(r"name=['\"]([^'\"]+)['\"]", selector)
                            if name_match:
                                name_value = name_match.group(1)
                                fallback_selectors = [
                                    f"input[name='{name_value}']",  # input[name='...']
                                    f".{name_value}",  # .view-as-partner-input
                                    f"input.{name_value}",  # input.view-as-partner-input
                                    selector,  # Original
                                ]
                            else:
                                fallback_selectors = [selector]
                        else:
                            fallback_selectors = [selector]
                        
                        found = False
                        for fallback_selector in fallback_selectors:
                            try:
                                await page.wait_for_selector(fallback_selector, state="visible", timeout=2000)
                                selector = fallback_selector
                                print(f"      ✅ Found field with fallback selector: {fallback_selector}")
                                found = True
                                break
                            except:
                                continue
                        
                        if not found:
                            # Last resort: try to find any input field that might match
                            print(f"      🔍 Trying agentic discovery for input field...")
                            # Extract key terms from selector for search
                            search_terms = []
                            if "view-as" in selector.lower() or "partner" in selector.lower():
                                search_terms = ["view", "partner", "input"]
                            
                            if search_terms:
                                # Try to find input by analyzing page
                                try:
                                    input_js = f"""
                                    () => {{
                                        const inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type]), input[class*="view"], input[name*="view"], input[name*="partner"]'));
                                        for (const inp of inputs) {{
                                            if (inp.offsetParent !== null) {{  // Visible
                                                const name = inp.name || '';
                                                const className = inp.className || '';
                                                if (name.includes('view') || name.includes('partner') || className.includes('view') || className.includes('partner')) {{
                                                    return inp;
                                                }}
                                            }}
                                        }}
                                        return null;
                                    }}
                                    """
                                    element_handle = await page.evaluate_handle(input_js)
                                    if element_handle:
                                        # Get selector for this element
                                        selector_js = """
                                        (el) => {
                                            if (el.id) return `#${el.id}`;
                                            if (el.name) return `input[name='${el.name}']`;
                                            if (el.className) {
                                                const classes = el.className.split(' ').filter(c => c).join('.');
                                                return `input.${classes}`;
                                            }
                                            return null;
                                        }
                                        """
                                        discovered_selector = await page.evaluate(selector_js, element_handle)
                                        if discovered_selector:
                                            selector = discovered_selector
                                            print(f"      ✅ Agentic discovery found input field: {discovered_selector}")
                                            found = True
                                except Exception as agentic_e:
                                    print(f"      ⚠️  Agentic discovery failed: {agentic_e}")
                            
                            if not found:
                                raise RuntimeError(f"Could not find input field with selector '{step['selector']}'. Tried fallbacks: {fallback_selectors}")
                
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
        raw_base_url = base_url or CONFIG['BASE_URL']
        # Normalize base_url to always have a scheme for proper URL parsing
        if raw_base_url and not raw_base_url.startswith(('http://', 'https://')):
            self.base_url = f"http://{raw_base_url}"
        else:
            self.base_url = raw_base_url

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
    
    async def _open_dropdown_menus(self, page: Page):
        """
        Open dropdown menus to discover links inside them.
        Finds buttons with aria-haspopup="true" or dropdown triggers and clicks them.
        """
        try:
            # Find all dropdown trigger buttons
            # Include various patterns: aria-haspopup, dropdown-trigger class, etc.
            dropdown_selectors = [
                'button[aria-haspopup="true"]',
                'button[aria-expanded="false"]',
                '.dropdown-trigger',
                '[role="button"][aria-haspopup="true"]',
                'button.dropdown-trigger',
                '.ntnx-dropdown-trigger',  # Nutanix-specific dropdown trigger
                'button.ntnx-dropdown-trigger'
            ]
            
            opened_dropdowns = []
            
            for selector in dropdown_selectors:
                try:
                    buttons = await page.query_selector_all(selector)
                    for button in buttons:
                        try:
                            # Check if dropdown is already open
                            aria_expanded = await button.get_attribute('aria-expanded')
                            if aria_expanded == 'true':
                                continue  # Already open
                            
                            # Get button text for logging
                            button_text = (await button.inner_text()).strip() or await button.get_attribute('aria-label') or 'Unknown'
                            
                            # Click to open dropdown
                            await button.click(timeout=3000)
                            await asyncio.sleep(0.5)  # Wait for dropdown to appear
                            
                            # Verify dropdown opened
                            aria_expanded_after = await button.get_attribute('aria-expanded')
                            if aria_expanded_after == 'true':
                                opened_dropdowns.append(button_text)
                                print(f"   📂 Opened dropdown menu: {button_text}")
                            else:
                                # Check if dropdown appeared in DOM (some don't use aria-expanded)
                                dropdown_visible = await page.evaluate("""
                                    () => {
                                        const menus = document.querySelectorAll('[role="menu"], .dropdown-menu, [class*="dropdown"], [class*="menu"]');
                                        for (const menu of menus) {
                                            const rect = menu.getBoundingClientRect();
                                            if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(menu).display !== 'none') {
                                                return true;
                                            }
                                        }
                                        return false;
                                    }
                                """)
                                if dropdown_visible:
                                    opened_dropdowns.append(button_text)
                                    print(f"   📂 Opened dropdown menu: {button_text}")
                        except Exception as e:
                            # If clicking fails, continue with next button
                            continue
                except Exception as e:
                    # If selector fails, continue with next selector
                    continue
            
            if opened_dropdowns:
                print(f"   ✅ Opened {len(opened_dropdowns)} dropdown menu(s)")
                # Wait a bit more for all dropdowns to fully render
                await asyncio.sleep(0.3)
        except Exception as e:
            print(f"   ⚠️  Error opening dropdown menus: {e}")
    
    def _add_external_link(self, source_url: str, external_url: str, link_text: str, action: str = "navigate"):
        """
        Add an external link to the graph as a node and edge.
        External links are captured but not explored.
        """
        from urllib.parse import urlparse
        import hashlib
        
        parsed_url = urlparse(external_url)
        domain = parsed_url.netloc.split(':')[0]  # Remove port
        
        # Create a unique node ID based on the full external URL (to handle multiple links to same domain)
        # Use a hash of the URL to create a stable but unique ID
        url_hash = hashlib.md5(external_url.encode()).hexdigest()[:8]
        external_node_id = f"external_{domain.replace('.', '_').replace(':', '_')}_{url_hash}"
        
        # Check if external node already exists (by URL, not just ID)
        existing_external_node = None
        for node in self.graph.get("nodes", []):
            if node.get("url") == external_url:
                existing_external_node = node
                external_node_id = node.get("id")  # Use existing ID
                break
        
        # Create or update external node
        if not existing_external_node:
            # Use domain as display name, or full URL if domain is not available
            display_name = domain or external_url
            if link_text and link_text.strip():
                display_name = f"{link_text} ({domain})"
            
            external_node = {
                "id": external_node_id,
                "url": external_url,
                "semantic_name": external_node_id,
                "title": display_name,
                "display_header": display_name,
                "description": f"External link to {external_url}",
                "is_external": True,
                "domain": domain,
                "headers": [],
                "components": [],
                "active_apis": []
            }
            self.graph["nodes"].append(external_node)
            print(f"   🌐 Created external link node: {display_name} → {external_url}")
        
        # Find source node ID
        source_node_id = None
        for node in self.graph.get("nodes", []):
            if node.get("url") == source_url:
                source_node_id = node.get("id")
                break
        
        if not source_node_id:
            print(f"   ⚠️  Could not find source node for URL: {source_url}")
            return
        
        # Create edge from source to external node
        edge_data = {
            "from": source_node_id,
            "to": external_node_id,
            "action": action,
            "link_text": link_text,
            "href": external_url,
            "is_external": True,
            "description": f"External link: {link_text or external_url}"
        }
        
        # Check if edge already exists
        edge_exists = any(
            e.get("from") == source_node_id and 
            e.get("to") == external_node_id and
            e.get("href") == external_url
            for e in self.graph.get("edges", [])
        )
        
        if not edge_exists:
            self.graph["edges"].append(edge_data)
            print(f"   🌐 Created external link edge: {source_node_id} → {external_node_id} ({link_text or external_url})")
    
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
    
    async def discover_page(self, page: Page, url: str, parent_url: Optional[str] = None, action: str = "navigate", link_text: Optional[str] = None) -> str:
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
        
        # Validate URL - detect if it's an API URL instead of a UI URL
        # API URLs should not be stored as node URLs - they should be captured as active_apis
        api_url_patterns = ['/api/', '/graphql', '/v1/', '/v2/', '/rest/', '/query']
        url_is_api = any(pattern in url for pattern in api_url_patterns)
        
        if url_is_api:
            print(f"   ⚠️ Warning: URL appears to be an API endpoint: {url}")
            print(f"   ⚠️ This may cause issues - node URLs should be UI paths, not API endpoints")
            # Try to use the actual browser URL which might be the correct UI URL
            actual_browser_url = page.url
            if actual_browser_url != url and not any(pattern in actual_browser_url for pattern in api_url_patterns):
                print(f"   🔧 Using actual browser URL instead: {actual_browser_url}")
                url = actual_browser_url
                self.visited_urls.add(url)  # Also mark corrected URL as visited
        
        # Record start time for API correlation
        start_time = asyncio.get_event_loop().time()
        
        # Check if we're already on this URL (maintains session state)
        current_url = page.url
        if current_url == url or current_url.rstrip('/') == url.rstrip('/'):
            print(f"   ℹ️  Already on target URL, waiting for dynamic content to load...")
            # Wait for active requests to complete even if already on URL
            # This ensures dynamic content (like headers, links) is fully loaded
            await wait_for_active_requests_complete(page, timeout=30000)
            await asyncio.sleep(1)  # Small delay for final rendering
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
        # For home page, use the page title (app name) instead of inferring from headers
        display_header = None
        
        # Check if this is the home page (URL path is / or empty)
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        is_home_page = parsed_url.path == '/' or parsed_url.path == ''
        
        if is_home_page:
            # For home page, use the page title (app name) directly
            display_header = title
            print(f"   🏠 Home page detected, using app name as display_header: {display_header}")
        else:
            # For other pages, try to find h1 tag, then first header, then use LLM
            # Try to find h1 tag specifically (most likely to be the page title)
            try:
                h1_elements = await page.query_selector_all('h1')
                for h1 in h1_elements:
                    # Skip h1 in nav/footer
                    is_in_nav = await h1.evaluate('''(el) => {
                        const parent = el.closest('nav, footer, header, .nav, .footer, .header');
                        return parent !== null;
                    }''')
                    if is_in_nav:
                        continue
                    
                    h1_text = (await h1.inner_text()).strip()
                    if h1_text and len(h1_text) >= 3 and len(h1_text) <= 100:
                        # Check if it's not just navigation noise
                        skip_patterns = ['copyright', '©', 'all rights reserved', 'navigation', 'menu']
                        h1_lower = h1_text.lower()
                        if not any(pattern in h1_lower for pattern in skip_patterns):
                            display_header = h1_text
                            print(f"   📋 Using h1 tag as display_header: {display_header}")
                            break
            except Exception as e:
                print(f"   ⚠️  Error extracting h1: {e}")
            
            # If no h1 found, try the first header from structured_info
            if not display_header and structured_info.get('headers') and len(structured_info['headers']) > 0:
                first_header = structured_info['headers'][0].strip()
                # Filter out headers that are likely navigation/footer noise or content (not page titles)
                skip_patterns = [
                    'copyright', '©', 'all rights reserved', 
                    'navigation', 'menu', 'skip to', 'view as',
                ]
                first_header_lower = first_header.lower()
                
                # Use first header if it's suitable (not too long, not nav noise, not content-like)
                # Content-like headers are usually very long or contain colons (like "Cisco, Pure Storage, and Nutanix: Stronger Together")
                is_content_like = (
                    len(first_header) > 60 or  # Very long headers are usually content
                    ':' in first_header or  # Headers with colons are often content announcements
                    first_header.count(',') > 2  # Multiple commas suggest content, not title
                )
                
                if (len(first_header) >= 3 and 
                    len(first_header) <= 60 and  # Not too long for a page title
                    not any(pattern in first_header_lower for pattern in skip_patterns) and
                    not is_content_like):  # Not content-like
                    display_header = first_header
                    print(f"   📋 Using first header as display_header: {display_header}")
            
            # If no suitable header found (and not home page), use LLM to generate one
            if not display_header:
                header_prompt = f"""Generate a clean, human-readable page title/header for this page:
URL: {url}
Page Title: {title}
Semantic Name: {semantic_name}
Available Headers: {', '.join(structured_info['headers'][:5]) if structured_info['headers'] else 'N/A'}

Respond with ONLY a short, clean title (e.g., "Order Management Dashboard", "Orders Page", "Product Catalog", "Shopping Cart").
Do not include quotes or extra formatting, just the title text.
"""
                display_header = await self.analyze_with_llm(header_prompt)
                display_header = display_header.strip().strip('"').strip("'")
                print(f"   🤖 Generated display_header via LLM: {display_header}")
            
            # Final fallback: generate from semantic_name if LLM fails
            if not display_header or len(display_header) < 3:
                display_header = semantic_name.replace('_', ' ').title()
                print(f"   ⚠️  Using fallback display_header from semantic_name: {display_header}")
        
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
        # Normalize API URLs to extract meaningful endpoint paths
        active_apis = []
        for log in self.network_log:
            if log["type"] == "request" and start_time <= log["timestamp"] <= end_time:
                log_url = log['url']  # Use different variable name to not overwrite page url
                method = log['method']
                
                # Extract endpoint path from URL
                try:
                    from urllib.parse import urlparse, parse_qs, urlencode
                    parsed = urlparse(log_url)
                    endpoint_path = parsed.path
                    
                    # Remove API_BASE if present
                    api_base = CONFIG.get('API_BASE', '')
                    if api_base and endpoint_path.startswith(api_base):
                        endpoint_path = endpoint_path.replace(api_base, '')
                    
                    # If endpoint_path is empty or just '/', use the full path
                    if not endpoint_path or endpoint_path == '/':
                        endpoint_path = parsed.path
                    
                    # Add query params if present, but FILTER OUT pagination/sorting params
                    # These change frequently and shouldn't be part of the API signature
                    if parsed.query:
                        query_params = parse_qs(parsed.query, keep_blank_values=True)
                        # Remove pagination and sorting params
                        pagination_params = ['page', 'limit', 'offset', 'size', 'pageSize', 'per_page',
                                           'sortBy', 'sortOrder', 'sort', 'order', 'orderBy', 'direction',
                                           'skip', 'take', 'cursor', 'after', 'before']
                        filtered_params = {k: v for k, v in query_params.items() 
                                         if k.lower() not in [p.lower() for p in pagination_params]}
                        if filtered_params:
                            # Flatten single-value lists for cleaner output
                            clean_params = {k: v[0] if len(v) == 1 else v for k, v in filtered_params.items()}
                            endpoint_path = f"{endpoint_path}?{urlencode(clean_params, doseq=True)}"
                    
                    api_endpoint = f"{method} {endpoint_path}"
                    active_apis.append(api_endpoint)
                except Exception as e:
                    # Fallback: use full URL if parsing fails
                    api_endpoint = f"{method} {log_url}"
                    active_apis.append(api_endpoint)
        
        active_apis = list(set(active_apis))  # Remove duplicates
        
        # Extract primary entity from APIs, URL, or components
        primary_entity = self._extract_primary_entity(url, active_apis, components)
        
        # Create node with description field and headers
        node_id = semantic_name or f"page_{len(self.graph['nodes'])}"
        
        # Also aggregate into graph-level api_endpoints
        for api in active_apis:
            if api not in self.graph['api_endpoints']:
                self.graph['api_endpoints'][api] = {
                    "method": api.split(' ', 1)[0] if ' ' in api else 'GET',
                    "endpoint": api.split(' ', 1)[1] if ' ' in api else api,
                    "nodes": []
                }
            if node_id not in self.graph['api_endpoints'][api]["nodes"]:
                self.graph['api_endpoints'][api]["nodes"].append(node_id)
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
        
        # Log what was extracted
        print(f"   ✅ Node: {node_id}")
        print(f"   📝 Description: {page_description[:200]}..." if len(page_description) > 200 else f"   📝 Description: {page_description}")
        print(f"   📋 Headers: {len(structured_info.get('headers', []))} header(s)")
        if structured_info.get('headers'):
            print(f"      → {', '.join(structured_info['headers'][:10])}")
        print(f"   📦 Components: {len(components)}")
        print(f"   📡 APIs: {len(active_apis)}")
        
        # Create edge if there's a parent
        if parent_url:
            edge_data = {
                "from": parent_url,
                "to": url,
                "action": action,
                "selector": None,
                "link_text": link_text  # Link text passed as parameter (e.g., "Marketing", "Sales")
            }
            # Note: link_id will be added when edge is updated from discovered links
            self.graph["edges"].append(edge_data)
            if link_text:
                print(f"   🔗 Created edge with link text: '{link_text}' ({parent_url} → {url})")
        
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
        # ALWAYS prefer id/data-testid over text, especially when text contains dynamic values
        # This is critical for links with dynamic content like "$24.88M (58)"
        # IDs are stable identifiers that don't change when content updates
        if link_id:
            # Use ID selector - most stable, works even when text/href changes
            return f"a#{link_id}"
        if data_testid:
            return f"a[data-testid='{data_testid}']"
        
        # Priority 2: Use href attribute (usually stable, but less preferred than ID)
        # NOTE: If href has query parameters and we have an ID, ID should have been used above
        # This is a fallback when no ID/data-testid is available
        if href:
            # Clean href for selector (escape special chars)
            href_clean = href.replace("'", "\\'").replace('"', '\\"')
            # For hrefs with query params, prefer ID if available (but we're here because no ID)
            return f"a[href='{href_clean}']"
        
        # Priority 3: Check if text is dynamic
        # If id is available, ALWAYS use it - don't even check for dynamic text
        # This ensures we use stable identifiers when available
        dynamic_patterns = [
            r'\$[\d.,]+[KMkm]?',  # Currency like $1.05M, $78.91K, $24.88M
            r'\(\d+\)',  # Counts like (1), (3), (58)
            r'\d{4}-\d{2}-\d{2}',  # Dates
            r'\d+%',  # Percentages
            r'\d+\.\d+[KMkm]?',  # Numbers with K/M suffix
            r'\$[\d.,]+[KMkm]?\s*\(\d+\)',  # Combined: $24.88M (58)
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
    
    async def _wait_for_dynamic_widgets(self, page: Page, timeout: int = 10000) -> None:
        """
        Wait for dynamic widget content to render before extracting links.
        
        Many React/Vue apps load data asynchronously and render widgets after the initial page load.
        This method waits for common widget patterns (charts, dashboards, data tables) to appear.
        
        The goal is to capture links inside dynamically rendered components like:
        - Donut/pie chart legends with navigation links
        - Dashboard widgets with data-driven links
        - Tables with action links
        """
        widget_selectors = [
            # Donut/pie chart legends with links
            '[class*="DonutChart"] a[href]',
            '[class*="legend"] a[href]',
            '[class*="Legend"] a[href]',
            '[id*="legend"] a[href]',
            
            # Dashboard widgets
            '[class*="dashboard"] a[href]',
            '[class*="Dashboard"] a[href]',
            '[class*="widget"] a[href]',
            '[class*="Widget"] a[href]',
            
            # Data tables with links
            '[class*="table"] a[href]',
            'table a[href]',
            
            # Charts/graphs
            '[class*="chart"] a[href]',
            '[class*="Chart"] a[href]',
            
            # Recharts (common React charting library)
            '.recharts-wrapper a[href]',
            '.recharts-legend a[href]',
            
            # Nivo (another React charting library)
            '[class*="nivo"] a[href]',
            
            # General data-driven content
            '[class*="card"] a[href]',
            '[class*="Card"] a[href]',
        ]
        
        print(f"   ⏳ Waiting for dynamic widgets to render...")
        
        # Strategy: Wait until at least one widget selector finds links, or timeout
        start_time = asyncio.get_event_loop().time()
        max_wait_seconds = timeout / 1000
        found_widgets = False
        
        while not found_widgets:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= max_wait_seconds:
                print(f"   ⚠️  Timeout waiting for dynamic widgets (continuing anyway)")
                break
            
            # Check if any widget selectors find links
            for selector in widget_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    if elements and len(elements) > 0:
                        # Verify at least one element is visible
                        for el in elements[:3]:  # Check first 3
                            try:
                                is_visible = await el.is_visible()
                                if is_visible:
                                    href = await el.get_attribute('href')
                                    if href and href.startswith('/'):
                                        print(f"   ✅ Found dynamic widget link: {selector} ({len(elements)} links)")
                                        found_widgets = True
                                        break
                            except:
                                continue
                        if found_widgets:
                            break
                except:
                    continue
            
            if not found_widgets:
                await asyncio.sleep(0.5)  # Wait 500ms before checking again
        
        # Give a bit more time for any final rendering
        if found_widgets:
            await asyncio.sleep(0.5)
        else:
            # Even if we didn't find widgets, wait a bit for potential late-loading content
            await asyncio.sleep(1)
    
    async def discover_navigation_links(self, page: Page) -> List[Dict[str, str]]:
        """
        Override to use custom base_url and add domain filtering + stable selectors.
        Improvements:
        1. Domain filtering - only follow links with same domain
        2. Stable selector building - avoid dynamic text in selectors
        3. Filter out form controls (date filters, checkboxes) - only navigation links
        4. Filter out query-parameter-only links (filters, not navigation)
        5. Open dropdown menus to discover links inside them
        
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
        
        # STEP 0.5: Wait for dynamic widget content (charts, dashboards) to render
        # React components that fetch data asynchronously may not have rendered yet
        # Wait for common widget/chart selectors that indicate content has loaded
        await self._wait_for_dynamic_widgets(page)
        
        # STEP 1: Open dropdown menus to discover links inside them
        await self._open_dropdown_menus(page)
        
        # Extract domain from base_url for filtering
        # Normalize base_url to ensure it has a scheme for proper parsing
        normalized_base_url = self.base_url
        if not normalized_base_url.startswith(('http://', 'https://')):
            normalized_base_url = f"http://{normalized_base_url}"
        base_parsed = urlparse(normalized_base_url)
        base_domain = base_parsed.netloc.split(':')[0]  # Remove port, get just domain
        
        try:
            # Find React Router Link components (they render as <a> tags)
            # BUT exclude links that are inside form controls or filter components
            link_elements = await page.query_selector_all('a[href]')
            
            for link in link_elements:
                # FILTER OUT: Links inside form controls, date pickers, checkboxes, filters
                try:
                    # Check if link is inside a form control or filter component
                    # BUT allow links in dropdown menus (which we just opened)
                    is_in_form_control = await link.evaluate("""
                        el => {
                            // Check if link is inside input, select, or form control
                            const parent = el.closest('form, .filter, .date-picker, .datepicker, [role="combobox"], [role="listbox"]');
                            if (parent) return true;
                            
                            // Allow links in dropdown menus (role="menu" or dropdown containers)
                            const menuParent = el.closest('[role="menu"], .dropdown-menu, [class*="dropdown"], [class*="menu"]');
                            if (menuParent) {
                                // Check if menu is visible (opened)
                                const rect = menuParent.getBoundingClientRect();
                                const style = window.getComputedStyle(menuParent);
                                if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden') {
                                    return false; // Allow links in visible dropdown menus
                                }
                            }
                            
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
                        # Check if it's external domain
                        link_parsed = urlparse(full_url)
                        link_domain = link_parsed.netloc.split(':')[0]
                        if link_domain != base_domain:
                            # External link - capture it but don't explore
                            current_url = page.url
                            self._add_external_link(current_url, full_url, text, "navigate")
                            print(f"   🌐 Captured external link: {text} → {full_url}")
                            continue  # Don't explore external links
                    else:
                        # Relative path, construct full URL
                        current_url = page.url
                        base = current_url.rsplit('/', 1)[0] if '/' in current_url else self.base_url
                        full_url = f"{base}/{href}"
                    
                    # IMPROVEMENT 3: Build stable selector (avoids dynamic text)
                    # Always prefer id/data-testid over text, especially for dynamic values
                    # Do this BEFORE checking visited URLs so we have the selector ready
                    selector = await self._build_stable_selector(link, text, href, link_id, data_testid)
                    
                    # FILTER OUT: Already visited URLs (prevent duplicate visits)
                    # BUT: If link has an ID, we should still capture it as an edge even if URL was visited
                    # This is important for category links (e.g., Expansion, New Logo) that point to same base URL
                    normalized_url = full_url.rstrip('/').lower()
                    visited_normalized = {u.rstrip('/').lower() for u in self.visited_urls}
                    url_already_visited = normalized_url in visited_normalized
                    
                    if url_already_visited:
                        # If link has an ID, we should still add it to links list for edge creation
                        # (even though we won't visit the page again)
                        if link_id:
                            print(f"   📌 URL already visited but link has ID '{link_id}' - will create edge with ID selector")
                            # Continue to add link below (don't skip) - we'll create edge but not visit
                        else:
                            print(f"   ⏭️  Skipping already visited URL: {full_url}")
                            continue  # Skip already visited links without ID
                    
                    # Log selector choice for debugging
                    if link_id and selector.startswith(f"a#{link_id}"):
                        print(f"   ✅ Using ID selector for link: #{link_id} (text: '{text[:30]}...', href: '{href[:50]}...')")
                    elif data_testid and f"[data-testid='{data_testid}']" in selector:
                        print(f"   ✅ Using data-testid selector: [data-testid='{data_testid}'] (text: '{text[:30]}...')")
                    elif any(re.search(pattern, text) for pattern in [
                        r'\$[\d.,]+[KMkm]?', r'\(\d+\)', r'\$[\d.,]+[KMkm]?\s*\(\d+\)'
                    ]):
                        if link_id or data_testid:
                            print(f"   ✅ Link has ID/data-testid, using stable selector (text has dynamic content: '{text[:50]}')")
                        else:
                            print(f"   ⚠️  Link has dynamic text but no ID: '{text[:50]}' (href: '{href[:50]}...') - using text/href selector")
                    
                    links.append({
                        "url": full_url,
                        "text": text,  # Keep original text for display/logging
                        "selector": selector,  # Use stable selector (prioritizes id)
                        "href": href,
                        "link_id": link_id,  # Store ID for edge metadata
                        "data_testid": data_testid,  # Store data-testid for edge metadata
                        "skip_visit": url_already_visited and link_id  # Mark to skip visit but create edge
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
                    # BUT allow links in opened dropdown menus
                    is_in_form_control = await js_link.evaluate("""
                        el => {
                            const parent = el.closest('form, .filter, .date-picker, .datepicker, [role="combobox"], [role="listbox"]');
                            if (parent) return true;
                            
                            // Check if element is in a dropdown menu
                            const menuParent = el.closest('[role="menu"], [role="menuitem"], .dropdown-menu, [class*="dropdown"], [class*="menu"]');
                            if (menuParent) {
                                // Allow if menu is visible (opened dropdown)
                                const rect = menuParent.getBoundingClientRect();
                                const style = window.getComputedStyle(menuParent);
                                if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden') {
                                    return false; // Allow links in visible dropdown menus
                                }
                                // Also allow if parent is in nav/header (persistent nav menus)
                                if (menuParent.closest('nav, header')) {
                                    return false;
                                }
                            }
                            
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
                    # Use multiple fallback strategies for better reliability
                    selector = None
                    selector_fallbacks = []
                    
                    # Priority 1: Use id if available (most stable, especially for dynamic content)
                    if link_id:
                        selector = f"#{link_id}"
                        selector_fallbacks.append(f"[id='{link_id}']")
                        # Don't use text if id is available - id is always more stable
                    
                    # Priority 2: Use data-testid if available
                    if data_testid:
                        if not selector:
                            selector = f"[data-testid='{data_testid}']"
                        selector_fallbacks.append(f"[data-testid='{data_testid}']")
                    
                    # Priority 3: Use text only if no id/data-testid available
                    # Check if text contains dynamic values (currency, counts, etc.)
                    if text:
                        text_clean = text.replace("'", "\\'").replace('"', '\\"')
                        
                        # Check if text is dynamic - if so, prefer other selectors
                        dynamic_patterns = [
                            r'\$[\d.,]+[KMkm]?',  # Currency like $24.88M
                            r'\(\d+\)',  # Counts like (58)
                            r'\$[\d.,]+[KMkm]?\s*\(\d+\)',  # Combined: $24.88M (58)
                        ]
                        is_dynamic = any(re.search(pattern, text) for pattern in dynamic_patterns)
                        
                        if is_dynamic and not selector:
                            print(f"   ⚠️  JS nav link has dynamic text but no ID: '{text[:50]}' - will try class/parent selectors")
                        
                        # Try multiple text-based selectors (only if no id/data-testid)
                        text_selectors = [
                            f"a[role='link']:has-text('{text_clean}')",  # Most specific
                            f"[role='link']:has-text('{text_clean}')",  # More general
                            f"a:has-text('{text_clean}')",  # Even more general
                            f":has-text('{text_clean}')"  # Most general
                        ]
                        if not selector:
                            selector = text_selectors[0]
                        selector_fallbacks.extend(text_selectors)
                    
                    if class_name:
                        classes = class_name.split()
                        meaningful_classes = [c for c in classes if c and len(c) > 3 and not c.startswith('data-')]
                        if meaningful_classes:
                            class_selector = f"a.{meaningful_classes[0]}"
                            if not selector:
                                selector = class_selector
                            selector_fallbacks.append(class_selector)
                            # Also try with text
                            if text:
                                text_clean = text.replace("'", "\\'").replace('"', '\\"')
                                selector_fallbacks.append(f"a.{meaningful_classes[0]}:has-text('{text_clean}')")
                    
                    if not selector:
                        # Last resort: use text with role
                        if text:
                            text_clean = text.replace("'", "\\'").replace('"', '\\"')
                            selector = f"[role='link']:has-text('{text_clean[:30]}')"
                    
                    # Store metadata for later processing
                    js_nav_metadata.append({
                        'text': text,
                        'text_normalized': text.strip().lower(),
                        'link_id': link_id,
                        'data_testid': data_testid,
                        'class_name': class_name,
                        'selector': selector,
                        'selector_fallbacks': selector_fallbacks
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
                selector_fallbacks = metadata.get('selector_fallbacks', [])
                
                # Skip if we've already discovered a link with this text (avoid duplicates)
                if text_normalized in discovered_js_links:
                    continue
                
                # Try to discover the target URL by clicking and observing navigation
                # Store current URL before click
                current_url_before = page.url
                
                try:
                    # Re-query the element using selector (ElementHandle is invalid after navigation)
                    js_link = None
                    
                    # Try multiple selector strategies (use stored fallbacks if available)
                    selector_strategies = []
                    
                    # Strategy 1: Use provided selector
                    if selector:
                        selector_strategies.append(selector)
                    
                    # Strategy 2: Use stored fallback selectors
                    if selector_fallbacks:
                        selector_strategies.extend(selector_fallbacks)
                    
                    # Strategy 3: Try ID if available
                    if metadata['link_id']:
                        selector_strategies.append(f"#{metadata['link_id']}")
                        selector_strategies.append(f"[id='{metadata['link_id']}']")
                    
                    # Strategy 4: Try data-testid if available
                    if metadata['data_testid']:
                        selector_strategies.append(f"[data-testid='{metadata['data_testid']}']")
                    
                    # Strategy 5: Try role="link" with exact text match
                    if text:
                        text_clean = text.replace("'", "\\'").replace('"', '\\"')
                        selector_strategies.extend([
                            f"a[role='link']:has-text('{text_clean}')",
                            f"[role='link']:has-text('{text_clean}')",
                            f"a:has-text('{text_clean}')",
                            f":has-text('{text_clean}')"
                        ])
                    
                    # Strategy 6: Try class-based selector if available
                    if metadata['class_name']:
                        classes = metadata['class_name'].split()
                        meaningful_classes = [c for c in classes if c and len(c) > 3 and not c.startswith('data-')]
                        if meaningful_classes:
                            selector_strategies.append(f"a.{meaningful_classes[0]}")
                            if text:
                                text_clean = text.replace("'", "\\'").replace('"', '\\"')
                                selector_strategies.append(f"a.{meaningful_classes[0]}:has-text('{text_clean}')")
                    
                    # Try each selector strategy
                    for sel_strategy in selector_strategies:
                        try:
                            js_link = await page.query_selector(sel_strategy)
                            if js_link:
                                # Verify it's visible and has the correct text
                                is_visible = await js_link.is_visible()
                                link_text = (await js_link.inner_text()).strip()
                                if is_visible and text.lower() in link_text.lower():
                                    break  # Found valid element
                                else:
                                    js_link = None  # Reset if not visible or wrong text
                        except:
                            continue
                    
                    # If still not found, try JavaScript-based search and click directly
                    if not js_link:
                        # Use JavaScript to find and click the element directly
                        click_result = await page.evaluate(f"""
                            () => {{
                                const links = Array.from(document.querySelectorAll('a[role="link"], a:not([href])'));
                                for (const link of links) {{
                                    const linkText = (link.innerText || link.textContent || '').trim();
                                    if (linkText === '{text}' || linkText.toLowerCase() === '{text.lower()}') {{
                                        const rect = link.getBoundingClientRect();
                                        if (rect.width > 0 && rect.height > 0) {{
                                            // Click directly in JavaScript
                                            link.click();
                                            return {{ success: true, text: linkText }};
                                        }}
                                    }}
                                }}
                                return {{ success: false, reason: 'Element not found' }};
                            }}
                        """)
                        
                        if click_result and click_result.get('success'):
                            # Element was clicked, wait for navigation
                            print(f"   ✅ Clicked JS nav element via JavaScript: {text}")
                            js_link = True  # Mark as found so we proceed to URL checking
                        else:
                            js_link = None
                    
                    # Track if element was clicked via JavaScript fallback
                    clicked_via_js = False
                    
                    if not js_link:
                        print(f"   ⚠️  Could not find JS nav element: {text} (tried {len(selector_strategies)} selector strategies)")
                        continue
                    
                    # Click the element to trigger navigation
                    if js_link is True:
                        # Already clicked via JavaScript fallback
                        clicked_via_js = True
                    else:
                        # Click using Playwright ElementHandle
                        try:
                            # Scroll into view first to ensure element is clickable
                            await js_link.scroll_into_view_if_needed()
                            await asyncio.sleep(0.2)  # Small delay after scroll
                            await js_link.click(timeout=5000)
                        except Exception as click_err:
                            print(f"   ⚠️  Failed to click JS nav element '{text}': {click_err}")
                            continue
                    
                    # Wait for URL change (React Router can take time)
                    # Poll for URL change up to 5 seconds (increased from 3s)
                    url_changed = False
                    target_url = None
                    for wait_attempt in range(10):  # 10 attempts * 0.5s = 5s max wait
                        await asyncio.sleep(0.5)
                        current_url_after = page.url
                        if current_url_after != current_url_before:
                            url_changed = True
                            target_url = current_url_after
                            print(f"   ✅ URL changed detected (attempt {wait_attempt + 1}): {current_url_before} → {target_url}")
                            break
                    if not url_changed:
                        print(f"   ⚠️  URL did not change after clicking '{text}' (waited 5s), still on: {current_url_before}")
                    
                    if url_changed and target_url:
                        print(f"   🔍 URL changed after clicking '{text}': {current_url_before} → {target_url}")
                        # Wait for page to fully load after navigation
                        try:
                            await page.wait_for_load_state("networkidle", timeout=10000)
                            await asyncio.sleep(0.5)  # Additional small delay for any final rendering
                            print(f"   ✅ Page loaded after clicking: {text}")
                        except Exception as load_err:
                            # If networkidle times out, try domcontentloaded as fallback
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=5000)
                                await asyncio.sleep(0.5)
                                print(f"   ⚠️  Page loaded (domcontentloaded) after clicking: {text}")
                            except:
                                print(f"   ⚠️  Page load wait timed out for: {text}, continuing anyway")
                        # URL changed - this is a navigation link
                        
                        # Check if it's same domain
                        target_parsed = urlparse(target_url)
                        target_domain = target_parsed.netloc.split(':')[0]
                        # Normalize base_url for comparison
                        normalized_base_url = self.base_url
                        if not normalized_base_url.startswith(('http://', 'https://')):
                            normalized_base_url = f"http://{normalized_base_url}"
                        base_parsed_compare = urlparse(normalized_base_url)
                        base_domain_compare = base_parsed_compare.netloc.split(':')[0]
                        if target_domain != base_domain_compare:
                            # Different domain - capture as external link
                            print(f"   🌐 Captured external JS nav link: {text} → {target_url} (target_domain: {target_domain}, base_domain: {base_domain_compare})")
                            self._add_external_link(current_url_before, target_url, text, "click_js_nav")
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
                        # Include fallback selectors for better reliability
                        link_data = {
                            "url": target_url,
                            "text": text,
                            "selector": selector,
                            "href": None,  # No href - JS-based navigation
                            "js_navigation": True  # Mark as JS-based navigation
                        }
                        # Add fallback selectors if available (from metadata)
                        metadata_fallbacks = metadata.get('selector_fallbacks', [])
                        if metadata_fallbacks:
                            link_data["selector_fallbacks"] = metadata_fallbacks
                        links.append(link_data)
                        
                        print(f"   🔗 Discovered JS nav link: {text} → {target_url}")
                        print(f"      Selector: {selector}")
                        if metadata_fallbacks:
                            print(f"      Fallback selectors: {len(metadata_fallbacks)} available")
                        discovered_js_links.add(text_normalized)  # Mark as discovered
                        
                        # IMPORTANT: Discover the page immediately while we're on it
                        # This ensures headers, components, and links from the new page are captured
                        print(f"   🔍 Immediately discovering page: {target_url}")
                        try:
                            # Pass link text so edge can be labeled correctly
                            await self.discover_page(page, target_url, parent_url=current_url_before, action="click_js_nav", link_text=text)
                            print(f"   ✅ Discovered page: {target_url}")
                        except Exception as discover_err:
                            print(f"   ⚠️  Error discovering page {target_url}: {discover_err}")
                        
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
                        print(f"   ⚠️  URL did not change after clicking '{text}': {current_url_before} (still on same page)")
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
                # If link has an ID, we should still process it for edge creation (even if URL visited)
                if normalized_link_url not in visited_normalized:
                    internal_links.append(link)
                elif link.get('link_id'):
                    # URL was visited but link has ID - still add for edge creation (won't visit again)
                    print(f"   📌 URL already visited but link has ID '{link.get('link_id')}' - will create edge")
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
                # If link has an ID, we should still process it for edge creation (even if URL visited)
                if normalized_link_url not in visited_normalized:
                    non_template_links.append(link)
                elif link.get('link_id'):
                    # URL was visited but link has ID - still add for edge creation (won't visit again)
                    print(f"   📌 URL already visited but link has ID '{link.get('link_id')}' - will create edge")
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
                
                # Check if URL was already visited - if so, skip navigation but still create edge if link has ID
                normalized_link_url = link['url'].rstrip('/').lower()
                visited_normalized = {u.rstrip('/').lower() for u in self.visited_urls}
                url_already_visited = normalized_link_url in visited_normalized
                skip_navigation = url_already_visited and link.get('link_id')
                
                if skip_navigation:
                    print(f"   📌 URL already visited but link has ID '{link.get('link_id')}' - skipping navigation, will create edge")
                    # Skip navigation but continue to edge creation below
                else:
                    # Check if this is a JavaScript-based navigation link (no href)
                    is_js_nav = link.get('js_navigation', False) or link.get('href') is None
                
                if skip_navigation:
                    # Skip navigation - URL already visited, but we'll still create edge
                    pass
                elif is_js_nav:
                    # For JS navigation links, click the element instead of using page.goto()
                    selector = link.get('selector')
                    link_text = link.get('text', '')
                    
                    if selector or link_text:
                        try:
                            print(f"      🖱️  Clicking JS nav link: {link_text or selector}")
                            
                            # Try multiple strategies to click the JS nav link
                            clicked = False
                            
                            # Strategy 1: Use selector if available
                            if selector:
                                try:
                                    await page.click(selector, timeout=5000)
                                    clicked = True
                                except Exception as sel_err:
                                    print(f"      ⚠️  Selector click failed: {sel_err}")
                            
                            # Strategy 1b: Try fallback selectors if primary failed
                            if not clicked:
                                selector_fallbacks = link.get('selector_fallbacks', [])
                                for fallback_sel in selector_fallbacks:
                                    try:
                                        await page.click(fallback_sel, timeout=3000)
                                        clicked = True
                                        print(f"      ✅ Clicked using fallback selector: {fallback_sel}")
                                        break
                                    except:
                                        continue
                            
                            # Strategy 2: Use JavaScript to find and click by text
                            if not clicked and link_text:
                                click_result = await page.evaluate(f"""
                                    () => {{
                                        const links = Array.from(document.querySelectorAll('a[role="link"], a:not([href])'));
                                        for (const linkEl of links) {{
                                            const linkText = (linkEl.innerText || linkEl.textContent || '').trim();
                                            if (linkText === '{link_text}' || linkText.toLowerCase() === '{link_text.lower()}') {{
                                                const rect = linkEl.getBoundingClientRect();
                                                if (rect.width > 0 && rect.height > 0) {{
                                                    linkEl.click();
                                                    return {{ success: true, text: linkText }};
                                                }}
                                            }}
                                        }}
                                        return {{ success: false, reason: 'Element not found' }};
                                    }}
                                """)
                                
                                if click_result and click_result.get('success'):
                                    clicked = True
                                    print(f"      ✅ Clicked via JavaScript text search")
                            
                            if not clicked:
                                print(f"      ⚠️  Could not click JS nav link: {link_text or selector}")
                                continue
                            
                            # Wait for navigation/redirect to complete
                            await asyncio.sleep(1)
                            
                            # Wait for URL change (React Router can take time)
                            initial_url = page.url
                            for wait_attempt in range(10):  # 10 attempts * 0.5s = 5s max wait
                                await asyncio.sleep(0.5)
                                if page.url != initial_url:
                                    break
                            
                            # Wait for active requests to complete
                            await wait_for_active_requests_complete(page, timeout=30000)
                            
                            # Wait for page load
                            try:
                                await page.wait_for_load_state("networkidle", timeout=10000)
                            except:
                                await page.wait_for_load_state("domcontentloaded", timeout=5000)
                            
                            await asyncio.sleep(0.5)  # Small delay for final rendering
                            
                            # Verify we navigated to the expected URL
                            current_url = page.url.rstrip('/').lower()
                            expected_url = link['url'].rstrip('/').lower()
                            if current_url != expected_url:
                                print(f"      ⚠️  Navigation mismatch: expected {link['url']}, got {page.url}")
                                # Update link URL to actual URL if different
                                link['url'] = page.url
                            
                            print(f"      ✅ JS nav link clicked, page loaded: {page.url}")
                        except Exception as click_err:
                            print(f"      ⚠️  Failed to click JS nav link: {click_err}")
                            import traceback
                            print(f"      Traceback: {traceback.format_exc()}")
                            continue  # Skip this link and continue
                    else:
                        print(f"      ⚠️  No selector or text for JS nav link, skipping")
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
                # Skip discovery if we're just creating an edge for an already-visited URL with ID
                if not skip_navigation:
                    await self.discover_all_routes(page, link['url'], max_depth, current_depth + 1)
                else:
                    # URL was already visited - just ensure node exists for edge creation
                    print(f"   📌 Skipping discovery (already visited), ensuring node exists for edge with ID '{link.get('link_id')}'")
                
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
                            # Get link text for better edge labels
                            link_text = link.get('text', '')
                            action_type = "navigate"
                            if link.get('js_navigation'):
                                action_type = "click_js_nav"
                            
                            # Update existing edge if it was created during discover_page
                            existing_edge = None
                            for e in self.graph['edges']:
                                if (e.get('from') == current_node_id or e.get('from') == current_url) and \
                                   (e.get('to') == target_node_id or e.get('to') == link['url']):
                                    existing_edge = e
                                    break
                            
                            if existing_edge:
                                # Update existing edge with link text and metadata
                                existing_edge['link_text'] = link_text
                                existing_edge['action'] = action_type
                                existing_edge['selector'] = link.get('selector')
                                # Store ID and data-testid if available (for stable selectors)
                                if link.get('link_id'):
                                    existing_edge['link_id'] = link.get('link_id')
                                if link.get('data_testid'):
                                    existing_edge['data_testid'] = link.get('data_testid')
                                print(f"      ✅ Updated edge with link text: '{link_text}' ({current_node_id} → {target_node_id})")
                            else:
                                # Create new edge with metadata
                                edge_data = {
                                    "from": current_node_id,
                                    "to": target_node_id,
                                    "action": action_type,
                                    "selector": link.get('selector'),
                                    "link_text": link_text
                                }
                                # Store ID and data-testid if available (for stable selectors)
                                if link.get('link_id'):
                                    edge_data['link_id'] = link.get('link_id')
                                if link.get('data_testid'):
                                    edge_data['data_testid'] = link.get('data_testid')
                                self.graph['edges'].append(edge_data)
                                print(f"      ✅ Created edge: '{link_text}' ({current_node_id} → {target_node_id})")
                
            except Exception as e:
                print(f"   ⚠️ Failed to follow link {link['url']}: {e}")
                continue
    
    def deduplicate_nodes(self):
        """
        Remove duplicate nodes by ID, keeping the most complete version.
        
        When multiple nodes share the same ID, we keep the one with:
        1. Most components
        2. Most active_apis
        3. Longest description
        """
        print("\n🔄 Deduplicating nodes by ID...")
        
        nodes = self.graph.get("nodes", [])
        if not nodes:
            return
        
        # Group nodes by ID
        nodes_by_id: Dict[str, List[Dict]] = {}
        for node in nodes:
            node_id = node.get("id")
            if node_id not in nodes_by_id:
                nodes_by_id[node_id] = []
            nodes_by_id[node_id].append(node)
        
        # Find duplicates
        duplicate_ids = [nid for nid, group in nodes_by_id.items() if len(group) > 1]
        
        if not duplicate_ids:
            print("   ✅ No duplicate nodes found")
            return
        
        print(f"   ⚠️ Found {len(duplicate_ids)} duplicate node IDs:")
        for dup_id in duplicate_ids:
            print(f"      - {dup_id} ({len(nodes_by_id[dup_id])} instances)")
        
        # Build deduplicated node list
        deduplicated_nodes = []
        for node_id, group in nodes_by_id.items():
            if len(group) == 1:
                deduplicated_nodes.append(group[0])
            else:
                # Pick the "best" node - most components, then most APIs, then longest description
                def node_score(n):
                    return (
                        len(n.get("components", [])),
                        len(n.get("active_apis", [])),
                        len(n.get("description", ""))
                    )
                best_node = max(group, key=node_score)
                deduplicated_nodes.append(best_node)
                print(f"   ✅ Kept best version of '{node_id}' ({len(best_node.get('components', []))} components)")
        
        original_count = len(nodes)
        self.graph["nodes"] = deduplicated_nodes
        print(f"   📊 Nodes: {original_count} → {len(deduplicated_nodes)} (removed {original_count - len(deduplicated_nodes)} duplicates)")
    
    def deduplicate_edges(self):
        """
        Remove duplicate edges based on (from, to, action) tuple.
        """
        print("\n🔄 Deduplicating edges...")
        
        edges = self.graph.get("edges", [])
        if not edges:
            return
        
        seen = set()
        deduplicated_edges = []
        duplicates_removed = 0
        
        for edge in edges:
            # Create a key from the edge's essential properties
            edge_key = (
                edge.get("from"),
                edge.get("to"),
                edge.get("action"),
                edge.get("selector"),
                edge.get("link_text")
            )
            
            if edge_key not in seen:
                seen.add(edge_key)
                deduplicated_edges.append(edge)
            else:
                duplicates_removed += 1
        
        if duplicates_removed > 0:
            print(f"   ⚠️ Removed {duplicates_removed} duplicate edges")
        else:
            print("   ✅ No duplicate edges found")
        
        self.graph["edges"] = deduplicated_edges
        print(f"   📊 Edges: {len(edges)} → {len(deduplicated_edges)}")
    
    def create_internal_edges_from_components(self):
        """
        Post-process the graph to create internal navigation edges from component data.
        
        This method scans each node's components to find navigation buttons/links that
        trigger API calls. By matching these API calls to other nodes, we can infer
        navigation paths and create edges with selectors.
        
        The logic:
        1. Build a mapping from API endpoints to the nodes that use them
        2. For each node, look at components with triggers_api
        3. If a component's triggers_api matches another node's defining API, create an edge
        4. Use the component's selector for deterministic navigation
        """
        print("\n" + "=" * 70)
        print("🔗 Creating Internal Navigation Edges from Components")
        print("=" * 70)
        
        nodes = self.graph.get("nodes", [])
        api_endpoints = self.graph.get("api_endpoints", {})
        existing_edges = self.graph.get("edges", [])
        
        # Build reverse mapping: API endpoint -> list of node IDs that use it
        # This tells us which nodes are associated with which API calls
        api_to_nodes = {}
        for api_key, api_info in api_endpoints.items():
            for node_id in api_info.get("nodes", []):
                if api_key not in api_to_nodes:
                    api_to_nodes[api_key] = []
                api_to_nodes[api_key].append(node_id)
        
        # Also map URLs to nodes for matching
        url_to_node = {}
        for node in nodes:
            node_id = node.get("id")
            node_url = node.get("url", "")
            if node_url:
                url_to_node[node_url] = node_id
                # Also map without query params for partial matching
                if "?" in node_url:
                    base_url = node_url.split("?")[0]
                    if base_url not in url_to_node:
                        url_to_node[base_url] = node_id
        
        print(f"   📊 Analyzing {len(nodes)} nodes for navigation components")
        print(f"   📡 Tracking {len(api_endpoints)} API endpoints")
        
        edges_created = 0
        
        for source_node in nodes:
            source_id = source_node.get("id")
            components = source_node.get("components", [])
            
            # Skip external nodes
            if source_node.get("is_external"):
                continue
            
            for component in components:
                triggers_api = component.get("triggers_api", [])
                if not triggers_api:
                    continue
                
                selector = component.get("selector")
                text = component.get("text", "")
                stable_text = component.get("stable_text", "")
                role = component.get("role", "")
                
                # Skip components without meaningful text (likely utility buttons)
                if not stable_text and not text:
                    continue
                
                # Skip common non-navigation buttons
                skip_roles = ["button_export", "button_feedback", "button_allow_all", "button_back_button"]
                if role in skip_roles:
                    continue
                
                # Find target nodes by matching API calls
                target_candidates = set()
                
                for api_call in triggers_api:
                    # Normalize API call to match api_endpoints keys
                    # triggers_api format: "GET http://localhost:9000/api/v1/..."
                    # api_endpoints key format: "GET /api/v1/..."
                    
                    # Extract method and path
                    parts = api_call.split(" ", 1)
                    if len(parts) != 2:
                        continue
                    method, full_url = parts
                    
                    # Extract path from full URL
                    from urllib.parse import urlparse
                    parsed = urlparse(full_url)
                    path = parsed.path
                    if parsed.query:
                        path = f"{path}?{parsed.query}"
                    
                    api_key = f"{method} {path}"
                    
                    # Check if this API maps to any nodes
                    if api_key in api_to_nodes:
                        for node_id in api_to_nodes[api_key]:
                            # Don't create self-loops
                            if node_id != source_id:
                                target_candidates.add(node_id)
                    
                    # Also try matching by URL directly
                    if full_url in url_to_node:
                        target_id = url_to_node[full_url]
                        if target_id != source_id:
                            target_candidates.add(target_id)
                
                # Create edges to target nodes
                for target_id in target_candidates:
                    # Check if edge already exists
                    edge_exists = any(
                        e.get("from") == source_id and e.get("to") == target_id
                        for e in existing_edges
                    )
                    
                    if not edge_exists:
                        edge_data = {
                            "from": source_id,
                            "to": target_id,
                            "action": "click",
                            "selector": selector,
                            "link_text": stable_text or text,
                            "is_external": False,
                            "component_role": role,
                            "inferred_from": "component_triggers_api"
                        }
                        self.graph["edges"].append(edge_data)
                        existing_edges.append(edge_data)  # Track to avoid duplicates
                        edges_created += 1
                        print(f"   ✅ Created edge: {source_id} --[{stable_text or text[:30]}]--> {target_id}")
                        print(f"      Selector: {selector}")
        
        print(f"\n   📊 Created {edges_created} internal navigation edges from components")
        
        # NOTE: We do NOT create fallback edges for unreachable nodes because:
        # 1. If we don't have a valid selector from the entrypoint, we can't create a deterministic navigation path
        # 2. Using the destination page's display_header as link_text is wrong - that's not a navigation element
        # 3. The navigation to those pages should be captured during the actual crawl when the mapper clicks menu items
        #
        # If pages are unreachable, it means the semantic mapper didn't capture the navigation path during crawling.
        # The solution is to improve the crawling to capture sidebar/menu navigation, not to infer wrong edges.
        
        # Report unreachable nodes for debugging
        entrypoints = self.graph.get("entrypoints", {})
        entrypoint_ids = set(entrypoints.values())
        
        # Build adjacency list for reachability check
        adjacency = {}
        for edge in self.graph.get("edges", []):
            if not edge.get("is_external", False):
                from_id = edge.get("from")
                to_id = edge.get("to")
                if from_id not in adjacency:
                    adjacency[from_id] = set()
                adjacency[from_id].add(to_id)
        
        # BFS to find all nodes reachable from any entrypoint
        reachable_from_entrypoint = set()
        for entrypoint_id in entrypoint_ids:
            queue = [entrypoint_id]
            reachable_from_entrypoint.add(entrypoint_id)
            while queue:
                current = queue.pop(0)
                for neighbor in adjacency.get(current, []):
                    if neighbor not in reachable_from_entrypoint:
                        reachable_from_entrypoint.add(neighbor)
                        queue.append(neighbor)
        
        # Find internal nodes not reachable from entrypoint
        unreachable_internal_nodes = []
        for node in nodes:
            node_id = node.get("id")
            if (node_id not in reachable_from_entrypoint and 
                not node.get("is_external")):
                unreachable_internal_nodes.append(node)
        
        if unreachable_internal_nodes:
            print(f"\n   ⚠️ Warning: {len(unreachable_internal_nodes)} internal nodes are not reachable from entrypoint:")
            for node in unreachable_internal_nodes:
                print(f"      - {node.get('id')} ({node.get('display_header', 'N/A')})")
            print(f"   💡 These pages need navigation edges captured during crawling")
        
        print(f"\n   📊 Total internal edges created: {edges_created}")
        return edges_created


async def incremental_update(
    persona: str,
    pr_diff: Dict[str, Any],
    base_url: str,
    existing_graph_path: str,
    output_path: str,
    gateway_plan_path: Optional[str] = None,
    headless: bool = False,
    llm: Any = None
) -> Dict[str, Any]:
    """
    Incrementally update semantic graph based on PR changes.
    
    1. Load existing graph
    2. Identify affected nodes from PR diff (e.g., SalesDataOpportunities -> sales_bookings)
    3. Navigate to those pages using existing edges
    4. Re-capture only those nodes
    5. Merge back into graph
    
    Args:
        persona: Persona to use (Reseller, Distributor, etc.)
        pr_diff: PR analysis with ui_changes, affected_pages, etc.
        base_url: Base URL of the application
        existing_graph_path: Path to existing semantic graph
        output_path: Path to save updated graph
        gateway_plan_path: Path to gateway plan JSON
        headless: Whether to run browser in headless mode
        llm: LLM instance for page analysis
    
    Returns:
        Updated semantic graph
    """
    print("=" * 70)
    print("🔄 INCREMENTAL SEMANTIC GRAPH UPDATE")
    print("=" * 70)
    
    # Load existing graph
    print(f"\n📂 Loading existing graph: {existing_graph_path}")
    with open(existing_graph_path, 'r') as f:
        graph = json.load(f)
    
    print(f"   Nodes: {len(graph.get('nodes', []))}")
    print(f"   Edges: {len(graph.get('edges', []))}")
    
    # Identify affected nodes from PR diff
    affected_node_ids = set()
    ui_changes = pr_diff.get('ui_changes', [])
    
    # Common mappings from PR file/component names to node IDs
    page_mappings = {
        'salesdata': 'sales_bookings',
        'sales': 'sales_bookings', 
        'opportunity': 'sales_bookings',
        'opportunities': 'sales_bookings',
        'renewals': 'renewals_bookings',
        'booking': 'sales_bookings',
        'dashboard': 'partner_dashboard',
    }
    
    print(f"\n🔍 Analyzing PR changes to find affected nodes...")
    for change in ui_changes:
        change_lower = change.lower()
        for keyword, node_id in page_mappings.items():
            if keyword in change_lower:
                affected_node_ids.add(node_id)
                print(f"   Found: '{keyword}' in '{change[:50]}...' -> {node_id}")
    
    # Also check pr_diff for explicit page references
    for key in ['affected_pages', 'pages', 'components']:
        pages = pr_diff.get(key, [])
        if isinstance(pages, list):
            for page in pages:
                page_lower = page.lower() if isinstance(page, str) else ''
                for keyword, node_id in page_mappings.items():
                    if keyword in page_lower:
                        affected_node_ids.add(node_id)
    
    if not affected_node_ids:
        print("   ⚠️ No affected nodes identified, will update first internal node")
        # Default to first internal node
        for node in graph.get('nodes', []):
            if not node.get('id', '').startswith('external_'):
                affected_node_ids.add(node.get('id'))
                break
    
    print(f"\n📋 Nodes to update: {list(affected_node_ids)}")
    
    # Find nodes and their URLs
    nodes_to_update = []
    node_by_id = {n['id']: n for n in graph.get('nodes', [])}
    
    for node_id in affected_node_ids:
        if node_id in node_by_id:
            nodes_to_update.append(node_by_id[node_id])
        else:
            print(f"   ⚠️ Node '{node_id}' not found in graph")
    
    if not nodes_to_update:
        print("   ❌ No valid nodes to update")
        return graph
    
    # Launch browser and navigate
    print(f"\n🌐 Launching browser (headless={headless})...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Execute gateway plan if provided
        if gateway_plan_path and Path(gateway_plan_path).exists():
            print(f"\n🔐 Executing gateway plan: {gateway_plan_path}")
            with open(gateway_plan_path, 'r') as f:
                gateway_plan = json.load(f)
            
            # Navigate to base URL first
            await page.goto(base_url, wait_until="load", timeout=30000)
            await asyncio.sleep(2)
            
            # Execute gateway steps
            steps = gateway_plan.get('steps', [])
            for i, step in enumerate(steps):
                action = step.get('action', '')
                selector = step.get('selector', '')
                value = step.get('value', '')
                text = step.get('text', '')
                
                # Resolve env() values
                if value and value.startswith('env('):
                    env_var = value[4:-1]
                    value = os.getenv(env_var, '')
                
                try:
                    if action == 'click':
                        await page.wait_for_selector(selector, timeout=15000)
                        await page.click(selector)
                        await asyncio.sleep(1)
                    elif action == 'fill':
                        await page.wait_for_selector(selector, timeout=15000)
                        await page.fill(selector, value)
                    elif action == 'wait_visible':
                        await page.wait_for_selector(selector, state='visible', timeout=15000)
                    elif action == 'assert_url_contains':
                        await asyncio.sleep(2)  # Wait for navigation
                    
                    print(f"   ✅ Step {i+1}: {action}")
                except Exception as e:
                    print(f"   ⚠️ Step {i+1} ({action}): {e}")
            
            print("   ✅ Gateway completed")
        else:
            # Just navigate to base URL
            await page.goto(base_url, wait_until="load", timeout=30000)
        
        await asyncio.sleep(2)
        
        # Create mapper for component extraction
        mapper = SemanticMapper(llm=llm, config=CONFIG)
        
        # Update each affected node
        for node in nodes_to_update:
            node_id = node.get('id')
            node_url = node.get('url', '')
            
            print(f"\n🔄 Updating node: {node_id}")
            print(f"   URL: {node_url}")
            
            # Navigate to the node's URL
            try:
                await page.goto(node_url, wait_until="load", timeout=30000)
                await asyncio.sleep(3)  # Let dynamic content load
                
                # Wait for network idle
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except:
                    pass
                
                print(f"   ✅ Navigated to page")
                
                # Re-extract components
                print(f"   📊 Extracting components...")
                components = await mapper.extract_semantic_components(page, node_url)
                
                print(f"   Found {len(components)} components")
                
                # Look for TCV or other new columns
                tcv_found = False
                for comp in components:
                    comp_str = json.dumps(comp).lower()
                    if 'tcv' in comp_str:
                        tcv_found = True
                        print(f"   ✅ Found TCV in component: {comp.get('role', 'unknown')}")
                
                if not tcv_found:
                    print(f"   ⚠️ TCV not found in extracted components")
                
                # Update node in graph
                for i, n in enumerate(graph['nodes']):
                    if n['id'] == node_id:
                        graph['nodes'][i]['components'] = components
                        print(f"   ✅ Updated components for {node_id}")
                        break
                
            except Exception as e:
                print(f"   ❌ Failed to update {node_id}: {e}")
        
        await context.close()
        await browser.close()
    
    # Save updated graph
    print(f"\n💾 Saving updated graph to: {output_path}")
    with open(output_path, 'w') as f:
        json.dump(graph, f, indent=2)
    
    print(f"✅ Incremental update complete")
    
    return graph


async def main():
    print("=" * 70)
    print("🚀 SEMANTIC MAPPER WITH GATEWAY")
    print("=" * 70)
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", required=True, help="internal|reseller|distributor")
    parser.add_argument("--gateway-instructions", default=None, help="Path to NL gateway instructions txt (optional - skip if not needed)")
    parser.add_argument("--gateway-plan", default=None, help="Path to save/load compiled gateway plan JSON (optional - if provided, will load plan instead of compiling)")
    parser.add_argument("--storage-state", default=None, help="Path to write/read storage state JSON (optional - deprecated, gateway plan is preferred)")
    parser.add_argument("--output", default="semantic_graph.json", help="Output graph json")
    parser.add_argument("--base-url", default=CONFIG["BASE_URL"], help="Base URL to open")
    parser.add_argument("--headless", default="false", help="true|false")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--incremental", action="store_true", help="Incremental update mode - only update nodes affected by PR")
    parser.add_argument("--existing-graph", default=None, help="Path to existing graph for incremental update")
    parser.add_argument("--affected-pages", default=None, help="Comma-separated list of affected page keywords (e.g., 'sales,opportunity')")
    parser.add_argument("--skip-gateway", action="store_true")
    parser.add_argument("--force-recompile-gateway", action="store_true", help="Force recompilation of gateway plan even if cached plan exists")
    parser.add_argument("--llm-provider", default="nutanix", choices=["nutanix", "ollama"], help="LLM provider to use for page analysis (many calls)")
    parser.add_argument("--gateway-llm-provider", default="nutanix", choices=["nutanix", "ollama"], help="LLM provider to use for gateway compilation (1 call, critical - recommend nutanix)")
    parser.add_argument("--ollama-model", default="llama3.1:8b", help="Ollama model name (when using ollama provider)")
    args = parser.parse_args()

    print(f"📋 Configuration:")
    print(f"   Persona: {args.persona}")
    print(f"   Base URL: {args.base_url}")
    print(f"   Incremental Mode: {args.incremental}")
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
    
    # Handle incremental update mode
    if args.incremental:
        print("\n" + "=" * 70)
        print("🔄 INCREMENTAL UPDATE MODE")
        print("=" * 70)
        
        # Determine existing graph path
        existing_graph = args.existing_graph
        if not existing_graph:
            # Try to find existing graph for this persona
            persona_graph = Path(__file__).parent / f"semantic_graph_{args.persona}.json"
            default_graph = Path(__file__).parent / "semantic_graph.json"
            if persona_graph.exists():
                existing_graph = str(persona_graph)
            elif default_graph.exists():
                existing_graph = str(default_graph)
            else:
                print("❌ No existing graph found. Run full mapping first.")
                return
        
        print(f"   Existing graph: {existing_graph}")
        
        # Build PR diff from affected-pages argument
        pr_diff = {'ui_changes': []}
        if args.affected_pages:
            pages = args.affected_pages.split(',')
            pr_diff['ui_changes'] = [f"Changes to {p.strip()}" for p in pages]
            print(f"   Affected pages: {pages}")
        
        # Initialize LLM
        if args.llm_provider == "nutanix":
            api_url = os.getenv("NUTANIX_API_URL")
            api_key = os.getenv("NUTANIX_API_KEY")
            model = os.getenv("NUTANIX_MODEL", "openai/gpt-oss-120b")
            llm = FixedNutanixChatModel(api_url=api_url, api_key=api_key, model_name=model)
        else:
            from langchain_community.llms import Ollama
            llm = Ollama(model=args.ollama_model)
        
        # Determine gateway plan path
        gateway_plan = args.gateway_plan
        if not gateway_plan:
            gateway_plan = Path(__file__).parent / "temp" / f"gateway_plan_{args.persona}.json"
            if not gateway_plan.exists():
                gateway_plan = None
        
        # Run incremental update
        await incremental_update(
            persona=args.persona,
            pr_diff=pr_diff,
            base_url=args.base_url,
            existing_graph_path=existing_graph,
            output_path=args.output,
            gateway_plan_path=str(gateway_plan) if gateway_plan else None,
            headless=headless,
            llm=llm
        )
        return

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

    # Determine gateway plan path (preferred over storage state)
    gateway_plan_path = None
    if args.gateway_plan:
        gateway_plan_path = Path(args.gateway_plan)
        gateway_plan_path.parent.mkdir(parents=True, exist_ok=True)
    elif args.gateway_instructions:
        # Auto-generate plan path from instructions file
        instructions_path = Path(args.gateway_instructions)
        plan_name = f"gateway_plan_{args.persona}.json"
        gateway_plan_path = instructions_path.parent / plan_name
        gateway_plan_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Storage state path (optional, deprecated)
    storage_state_path = None
    if args.storage_state:
        storage_state_path = Path(args.storage_state)
        storage_state_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n🌐 Launching browser (headless={headless})...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        print("✅ Browser launched")

        # Always create fresh context - we'll run gateway plan each time
        print(f"\n📄 Creating fresh browser context...")
        context = await browser.new_context()
        page = await context.new_page()
        print("✅ Context created")
        
        if args.skip_gateway:
            # Skip gateway but still navigate to base URL
            print("\n" + "=" * 70)
            print("⏭️  SKIPPING GATEWAY (--skip-gateway flag set)")
            print("=" * 70)
            print(f"📋 Persona: {args.persona}")
        
        # Start at base URL (always navigate, even if skipping gateway)
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
        instructions = ""  # Will be set when reading instructions file
        gateway_plan = None

        # Try to load existing gateway plan first, but check if instructions have changed
        if args.force_recompile_gateway and gateway_plan_path and gateway_plan_path.exists():
            print(f"\n🔄 Force recompile flag set - removing existing gateway plan")
            gateway_plan_path.unlink()
            gateway_plan = None
        
        if gateway_plan_path and gateway_plan_path.exists():
            # Check if instructions file exists and compare content hash
            instructions_changed = False
            if args.gateway_instructions:
                instructions_file = Path(args.gateway_instructions)
                if instructions_file.exists():
                    import hashlib
                    # Read current instructions and normalize for consistent hashing
                    current_instructions = instructions_file.read_text()
                    normalized_instructions = "\n".join(line.strip() for line in current_instructions.strip().split("\n") if line.strip())
                    current_hash = hashlib.md5(normalized_instructions.encode()).hexdigest()
                    
                    # Check if plan has stored hash
                    try:
                        plan_data = json.loads(gateway_plan_path.read_text())
                        stored_hash = plan_data.get("instructions_hash")
                        
                        if stored_hash != current_hash:
                            instructions_changed = True
                            print(f"\n🔄 Gateway instructions have changed - will recompile")
                            print(f"   Old hash: {stored_hash[:8] if stored_hash else 'none'}...")
                            print(f"   New hash: {current_hash[:8]}...")
                            print(f"   ⚠️  Hashes don't match - plan will be regenerated")
                        else:
                            # Double-check: count steps in instructions vs plan (more reliable than hash)
                            import re
                            numbered_steps = [line for line in current_instructions.split("\n") if re.match(r'^\s*\d+\.', line.strip())]
                            expected_steps = len(numbered_steps)
                            plan_steps = len(plan_data.get("steps", []))
                            
                            if expected_steps != plan_steps:
                                print(f"\n🔄 Step count mismatch detected - forcing recompile")
                                print(f"   Instructions have {expected_steps} numbered steps")
                                print(f"   Plan has {plan_steps} steps")
                                print(f"   Missing {expected_steps - plan_steps} step(s)")
                                instructions_changed = True
                            else:
                                print(f"\n✅ Gateway plan matches current instructions")
                                print(f"   Hash: {current_hash[:8]}...")
                                print(f"   Steps: {expected_steps} (verified)")
                    except Exception as e:
                        # Plan doesn't have hash or is invalid - check modification time as fallback
                        if instructions_file.stat().st_mtime > gateway_plan_path.stat().st_mtime:
                            instructions_changed = True
                            print(f"\n📄 Gateway instructions file is newer than plan - will recompile")
            
            if not instructions_changed:
                try:
                    print(f"\n📄 Loading existing gateway plan from: {gateway_plan_path}")
                    gateway_plan = json.loads(gateway_plan_path.read_text())
                    # Remove hash from plan before using (it's metadata)
                    if "instructions_hash" in gateway_plan:
                        del gateway_plan["instructions_hash"]
                    print(f"✅ Gateway plan loaded successfully ({len(gateway_plan.get('steps', []))} steps)")
                    should_run_gateway = True
                except Exception as e:
                    print(f"⚠️  Failed to load gateway plan: {e}")
                    print("   Will compile new plan from instructions")
            else:
                # Instructions changed - delete old plan and recompile
                print(f"\n🔄 Removing old plan and recompiling from updated instructions")
                gateway_plan_path.unlink()
                gateway_plan = None

        # If no plan loaded, check for instructions to compile
        # Always read instructions if provided (needed for compilation and hash checking)
        if args.gateway_instructions:
            gateway_file = Path(args.gateway_instructions)
            if gateway_file.exists():
                instructions = gateway_file.read_text().strip()
                if instructions:  # Only run gateway if file has content
                    should_run_gateway = True
                else:
                    print(f"⚠️  Gateway instructions file is empty: {gateway_file}")
            else:
                print(f"⚠️  Gateway instructions file not found: {gateway_file}")
        elif not gateway_plan:
            # No instructions and no plan - can't run gateway
            print("ℹ️  No gateway instructions provided and no existing plan found")

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
                
                if gateway_plan:
                    # Use loaded plan
                    plan = gateway_plan
                    print(f"\n✅ Using loaded gateway plan ({len(plan.get('steps', []))} steps)")
                else:
                    # Compile new plan from instructions
                    # Re-read instructions to ensure we have the latest version
                    if args.gateway_instructions:
                        gateway_file = Path(args.gateway_instructions)
                        if gateway_file.exists():
                            instructions = gateway_file.read_text().strip()
                            print(f"\n📄 Reading instructions from: {gateway_file}")
                            print(f"   Instructions length: {len(instructions)} characters")
                            print(f"   Number of lines: {len(instructions.split(chr(10)))}")
                            # Show last few lines to verify step 10 is included
                            lines = instructions.split('\n')
                            if len(lines) >= 2:
                                print(f"   Last 2 lines: {lines[-2:]}")
                    
                    print("\n🤖 Compiling gateway plan with LLM...")
                    prompt = build_gateway_compile_prompt(
                        persona=args.persona,
                        instructions=instructions,
                        snapshot=snapshot,
                        base_url=args.base_url,
                        storage_state_path=str(storage_state_path) if storage_state_path else "",
                    )

                    plan = await compile_gateway_plan(gateway_llm, prompt)
                    print("✅ Gateway plan compiled successfully")
                    
                    # Validate that all steps were included
                    instruction_lines = [line.strip() for line in instructions.strip().split("\n") if line.strip() and (line.strip()[0].isdigit() or line.strip().startswith("1.") or line.strip().startswith("2.") or line.strip().startswith("3.") or line.strip().startswith("4.") or line.strip().startswith("5.") or line.strip().startswith("6.") or line.strip().startswith("7.") or line.strip().startswith("8.") or line.strip().startswith("9.") or line.strip().startswith("10."))]
                    # Count numbered steps (lines starting with number followed by period)
                    import re
                    numbered_steps = [line for line in instructions.split("\n") if re.match(r'^\s*\d+\.', line.strip())]
                    expected_steps = len(numbered_steps)
                    actual_steps = len(plan.get("steps", []))
                    
                    if expected_steps != actual_steps:
                        print(f"\n⚠️  WARNING: Plan has {actual_steps} steps but instructions have {expected_steps} numbered steps!")
                        print(f"   Expected steps: {expected_steps}")
                        print(f"   Actual steps in plan: {actual_steps}")
                        if expected_steps > actual_steps:
                            print(f"   ⚠️  Missing {expected_steps - actual_steps} step(s) - the LLM may have skipped some steps")
                            print(f"   Last instruction: {numbered_steps[-1] if numbered_steps else 'N/A'}")
                    
                    # Save compiled plan for future use with instructions hash
                    if gateway_plan_path:
                        # Store hash of instructions in plan for change detection
                        import hashlib
                        # Normalize instructions (strip whitespace, normalize line endings) for consistent hashing
                        normalized_instructions = "\n".join(line.strip() for line in instructions.strip().split("\n") if line.strip())
                        instructions_hash = hashlib.md5(normalized_instructions.encode()).hexdigest()
                        plan["instructions_hash"] = instructions_hash
                        
                        print(f"\n💾 Saving gateway plan to: {gateway_plan_path}")
                        gateway_plan_path.write_text(json.dumps(plan, indent=2))
                        print(f"✅ Gateway plan saved (hash: {instructions_hash[:8]}...) - will auto-recompile if instructions change")
                    
                    print("\n=== COMPILED GATEWAY PLAN ===")
                    print(json.dumps(plan, indent=2))

                await execute_gateway_plan(page, plan)
                print(f"\n✅ Gateway execution completed (fresh authentication)")
                
                # Optionally save storage state (but don't rely on it)
                if storage_state_path:
                    print(f"\n💾 Saving storage state to: {storage_state_path} (optional, for reference only)")
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
        
        # Deduplicate nodes by ID (keep the most complete version)
        mapper.deduplicate_nodes()
        
        # Deduplicate edges 
        mapper.deduplicate_edges()
        
        # Create internal navigation edges from component data
        # This infers navigation paths by matching component triggers_api to node APIs
        mapper.create_internal_edges_from_components()

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