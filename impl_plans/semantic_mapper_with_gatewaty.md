Great — step-by-step is the right way to do this.

## ✅ Step 1 Goal (only)

Create a **new script** `semantic_mapper_with_gateway.py` that:

1.  Runs a **Natural-Language Gateway** (optional - driven by gateway instruction files) using Playwright and LLM to compile instructions into executable steps.
2.  Saves `storage_state.json` (so you can reuse sessions later).
3.  Runs your existing `SemanticMapper` to generate the `semantic_graph.json` with persona context.

✅ **No changes to existing files**.  
✅ Everything self-contained in the new file.

***

# 1) Command to run (semantic map only)

### Basic run (gateway + mapping)

```bash
uv run python semantic_mapper_with_gateway.py \
  --persona <persona_name> \
  --gateway-instructions gateway_<persona_name>.txt \
  --storage-state temp/storage_<persona_name>.json \
  --output semantic_graph_<persona_name>.json \
  --headless false \
  --max-depth 3
```

### If you already have a session saved (skip gateway, just map)

```bash
uv run python semantic_mapper_with_gateway.py \
  --persona <persona_name> \
  --storage-state temp/storage_<persona_name>.json \
  --output semantic_graph_<persona_name>.json \
  --headless false \
  --max-depth 3 \
  --skip-gateway
```

> **Prereqs (same as your existing mapper):**

*   `.env` with `NUTANIX_API_URL`, `NUTANIX_API_KEY`, optional `NUTANIX_MODEL` (or Ollama configured)
*   your target application running and accessible
*   Playwright installed (`uv run playwright install chromium`)

***

# 2) What “add this to prompt” will mean (in this step)

We'll embed **persona context** into the LLM prompts used for semantic naming so the mapper tags things correctly for each persona. Example prompt prefix:

> "You are mapping the app while logged in as persona = [persona_name]. Use this context when naming pages and components to capture persona-specific functionality."

This helps the semantic graph capture persona-specific pages/components and enables testing different user roles within the same application.

***

# 3) Implementation plan for `semantic_mapper_with_gateway.py`

### ✅ Structure (all in one file)

**Key Principle**: The gateway instruction file (`gateway_<persona>.txt`) drives the entire flow. The framework orchestrates execution but does not hardcode any application-specific logic.

1.  **Parse args** (persona, gateway instructions file path, etc.)
2.  **Load env + init LLM** (reuse `FixedNutanixChatModel` from your existing `semantic_mapper.py` or use Ollama)
3.  **Launch Playwright**
4.  **Create context**:
    *   if `--skip-gateway`: load storage state and proceed
    *   else if gateway instructions file exists and has content:
        *   open base URL (you can pass `--base-url`)
        *   collect UI snapshot
        *   ask LLM to compile gateway instructions → structured steps (JSON)
        *   execute steps deterministically
        *   save storage state
    *   else: skip gateway, proceed directly to mapping
5.  **Run SemanticMapper** (your existing logic) using the context/page
6.  **Tag graph with persona context** + save to output JSON

***

# 4) Create the new file: `semantic_mapper_with_gateway.py`

> This is a working starting version that a small coding model can extend.  
> It imports your existing mapper classes **without modifying them**.

```python
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

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page

# Reuse your existing mapper + LLM wrapper
from semantic_mapper import SemanticMapper, FixedNutanixChatModel, CONFIG


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

    js = f"""
    () => {{
      const roles = ["button","link","textbox","combobox","menuitem","tab"];
      const out = [];
      function selectorHint(el) {{
        if (!el) return null;
        if (el.id) return `#{el.id}`;
        const dt = el.getAttribute("data-testid");
        if (dt) return `[data-testid="${dt}"]`;
        const aria = el.getAttribute("aria-label");
        if (aria) return `${el.tagName.toLowerCase()}[aria-label="${aria}"]`;
        return el.tagName.toLowerCase();
      }}
      for (const r of roles) {{
        const nodes = document.querySelectorAll(`[role="${r}"]`);
        for (const el of nodes) {{
          const rect = el.getBoundingClientRect();
          if (rect.width < 1 || rect.height < 1) continue;
          const name = (el.getAttribute("aria-label") || el.innerText || el.value || "").trim();
          out.push({{
            role: r,
            name: name.slice(0, 80),
            selector_hint: selectorHint(el)
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
    return f"""
You are an automation planner that converts NATURAL LANGUAGE login/persona instructions into a strict, executable JSON plan.

CONTEXT:
- Target app base URL: {base_url}
- Persona to establish: {persona}
- You must plan steps that end in the app being ready to run tests AS THIS PERSONA.

OUTPUT REQUIREMENTS:
- Output ONLY valid JSON.
- Allowed actions: {sorted(list(ALLOWED_ACTIONS))}
- Every click/fill/select/wait_visible must include "selector".
- Use stable selectors in priority: #id, [data-testid=...], [aria-label=...], then role/text selectors.
- Use env(TEST_USER), env(TEST_PASS), env(MFA_SECRET) if credentials are needed.
- MUST include at least 2 postconditions verifying persona "{persona}" is active (e.g. assert_text "Viewing as [Persona]", assert_url_contains "/[persona]").
- MUST include final step save_storage_state with path "{storage_state_path}".

JSON format:
{{
  "persona": "{persona}",
  "goal": "short goal",
  "storage_state_path": "{storage_state_path}",
  "steps": [
    {{ "action": "goto", "url": "{base_url}" }}
  ],
  "postconditions": [
    {{ "action": "assert_text", "text": "..." }}
  ]
}}

USER INSTRUCTIONS:
{instructions}

PAGE SNAPSHOT (JSON):
{json.dumps(snapshot, indent=2)}
""".strip()


async def compile_gateway_plan(llm, prompt: str) -> Dict[str, Any]:
    """Call LLM and parse JSON plan."""
    response = llm.invoke(prompt)
    # Extract JSON object
    m = re.search(r"\{[\s\S]*\}", response)
    if not m:
        raise RuntimeError(f"LLM did not return JSON. Response:\n{response}")
    plan = json.loads(m.group(0))

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
    """Deterministic Playwright execution of compiled gateway plan."""
    for step in plan.get("steps", []):
        action = step["action"]
        if action == "goto":
            await page.goto(resolve_value(step["url"]), wait_until="networkidle")
        elif action == "click":
            await page.click(step["selector"], timeout=int(step.get("timeout_ms", 15000)))
        elif action == "fill":
            await page.fill(step["selector"], resolve_value(step["value"]), timeout=int(step.get("timeout_ms", 15000)))
        elif action == "select":
            await page.select_option(step["selector"], resolve_value(step["value"]), timeout=int(step.get("timeout_ms", 15000)))
        elif action == "wait_visible":
            await page.wait_for_selector(step["selector"], state="visible", timeout=int(step.get("timeout_ms", 15000)))
        elif action == "assert_text":
            body = await page.inner_text("body")
            if step["text"] not in body:
                raise RuntimeError(f"assert_text failed: {step['text']}")
        elif action == "assert_url_contains":
            if step["text"] not in page.url:
                raise RuntimeError(f"assert_url_contains failed: {step['text']}, url={page.url}")
        elif action == "save_storage_state":
            # no-op here; storage_state is saved at context level outside
            pass
        else:
            raise ValueError(f"Unknown action: {action}")

    # postconditions
    for step in plan.get("postconditions", []):
        action = step["action"]
        if action == "assert_text":
            body = await page.inner_text("body")
            if step["text"] not in body:
                raise RuntimeError(f"postcondition assert_text failed: {step['text']}")
        elif action == "wait_visible":
            await page.wait_for_selector(step["selector"], state="visible", timeout=int(step.get("timeout_ms", 15000)))
        elif action == "assert_url_contains":
            if step["text"] not in page.url:
                raise RuntimeError(f"postcondition assert_url_contains failed: {step['text']}, url={page.url}")
        else:
            # keep postconditions limited
            raise ValueError(f"Unsupported postcondition action: {action}")


class SemanticMapperWithPersona(SemanticMapper):
    """
    Subclass existing SemanticMapper without modifying it.
    Inject persona context into nodes after discovery.
    Also prepend persona info into LLM prompts for better naming.
    """
    def __init__(self, llm, persona: str):
        super().__init__(llm)
        self.persona = persona

    async def analyze_with_llm(self, prompt: str) -> str:
        persona_prefix = f"[Persona Context] You are mapping the app while logged in as persona='{self.persona}'.\n"
        return await super().analyze_with_llm(persona_prefix + prompt)

    def _tag_last_node(self):
        if not self.graph.get("nodes"):
            return
        self.graph["nodes"][-1].setdefault("context", {})
        self.graph["nodes"][-1]["context"]["persona"] = self.persona


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", required=True, help="Persona/role identifier (e.g., admin, user, guest)")
    parser.add_argument("--gateway-instructions", default=None, help="Path to NL gateway instructions txt")
    parser.add_argument("--storage-state", required=True, help="Path to write/read storage state JSON")
    parser.add_argument("--output", default="semantic_graph.json", help="Output graph json")
    parser.add_argument("--base-url", default=CONFIG["BASE_URL"], help="Base URL to open")
    parser.add_argument("--headless", default="false", help="true|false")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--skip-gateway", action="store_true")
    args = parser.parse_args()

    headless = args.headless.lower() == "true"

    # Load env for LLM
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    api_url = os.getenv("NUTANIX_API_URL")
    api_key = os.getenv("NUTANIX_API_KEY")
    model = os.getenv("NUTANIX_MODEL", "openai/gpt-oss-120b")

    if not api_url or not api_key:
        raise RuntimeError("Missing NUTANIX_API_URL or NUTANIX_API_KEY in .env")

    llm = FixedNutanixChatModel(api_url=api_url, api_key=api_key, model_name=model)

    storage_state_path = Path(args.storage_state)
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)

        # If we skip gateway, we must have storage state already
        if args.skip_gateway:
            if not storage_state_path.exists():
                raise RuntimeError(f"--skip-gateway set but storage state not found: {storage_state_path}")
            context = await browser.new_context(storage_state=str(storage_state_path))
            page = await context.new_page()
        else:
            # Create fresh context, run gateway, then save storage state, then recreate context with it
            context = await browser.new_context()
            page = await context.new_page()

            # Start at base URL
            await page.goto(args.base_url, wait_until="networkidle")

            if not args.gateway_instructions:
                raise RuntimeError("Provide --gateway-instructions unless using --skip-gateway")

            instructions = Path(args.gateway_instructions).read_text()

            snapshot = await collect_ui_snapshot(page)
            prompt = build_gateway_compile_prompt(
                persona=args.persona,
                instructions=instructions,
                snapshot=snapshot,
                base_url=args.base_url,
                storage_state_path=str(storage_state_path),
            )

            plan = await compile_gateway_plan(llm, prompt)
            print("\n=== COMPILED GATEWAY PLAN ===")
            print(json.dumps(plan, indent=2))

            await execute_gateway_plan(page, plan)

            # Save storage state
            await context.storage_state(path=str(storage_state_path))
            await context.close()

            # Reopen context using storage state for mapping
            context = await browser.new_context(storage_state=str(storage_state_path))
            page = await context.new_page()

        # ----------------------------
        # Run semantic mapping
        # ----------------------------
        mapper = SemanticMapperWithPersona(llm, persona=args.persona)

        # Setup network interception (existing mapper method)
        await mapper.setup_network_interception(page)

        # Discover all routes starting from base url (use your existing recursion)
        await mapper.discover_all_routes(page, args.base_url, max_depth=args.max_depth)

        # Interact with forms/buttons to discover APIs (reuse your existing loop)
        for node in mapper.graph.get("nodes", []):
            try:
                await page.goto(node["url"], wait_until="networkidle", timeout=10000)
                await asyncio.sleep(1)

                for component in node.get("components", []):
                    if component.get("type") == "button":
                        btn_text = (component.get("text") or "").lower()
                        btn_role = (component.get("role") or "").lower()
                        if any(k in btn_text or k in btn_role for k in ["add", "create", "new", "open"]):
                            await mapper.try_button_opens_form(page, component, node)

                for component in node.get("components", []):
                    if component.get("type") == "form":
                        await mapper.try_form_interaction(page, component, node)
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

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
```

***

# 5) Gateway Instruction Files

**Critical**: This framework is completely application-agnostic. The gateway instruction files (`gateway_<persona>.txt`) are the **single source of truth** for how to reach the starting point for semantic mapping. 

The framework:
- Reads your gateway instruction file
- Compiles it to executable steps using LLM
- Executes those steps deterministically
- Does NOT hardcode any application-specific logic

Your gateway instruction file should describe:
- How to authenticate (if needed)
- How to navigate to the starting point
- How to select/activate the desired persona/role (if applicable)
- How to verify you've reached the correct state

The examples below are generic templates - customize them to match your application's actual UI and flow.

Example (customize to your application's authentication flow):

```text
1. Login using env(TEST_USER) and env(TEST_PASS).
2. Navigate to user/role selection interface.
3. Select the desired persona/role.
4. Verify the interface loads with persona-specific features.
```

Create application-specific gateway instruction files for each persona/role you want to test:

*   `gateway_<persona_name>.txt` - Instructions for each persona/role
*   Example: `gateway_admin.txt`, `gateway_user.txt`, `gateway_guest.txt`

***

# 6) What you’ll validate after running Step 1

After the command runs, check:

1.  `temp/storage_<persona_name>.json` exists (browser session state)
2.  `semantic_graph_<persona_name>.json` exists (semantic navigation graph)
3.  In that graph, nodes include persona context:

```json
"context": {"persona": "<persona_name>"}
```

4.  Graph includes entrypoint for the persona:

```json
"entrypoints": {"<persona_name>": "...node_id..."}
```

***

# 7) Persona Postcondition Markers

For reliable persona verification, include postconditions in your gateway instructions that check for persona-specific UI markers.

Examples of postcondition markers you can use in gateway instructions:

*   Visible text like `"Viewing as [Persona]"`
*   UI badges or labels `"[Persona] Mode"`
*   Page headers `"[Persona] Dashboard"`
*   URL segments containing the persona name
*   Specific UI elements only visible to that persona

The LLM will automatically generate these postconditions based on your gateway instructions to ensure the persona context is properly established.

Once the gateway mapper works with your application, you can run it for different personas and compare the resulting semantic graphs to understand persona-specific functionality.
