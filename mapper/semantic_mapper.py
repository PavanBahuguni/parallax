"""Semantic Discovery Mapper - Phase 1: UI Discovery

This mapper produces a **semantic navigation graph** for Phase 1 discovery:
1. Semantic identifiers (CSS selectors, not indices)
2. API anchoring (network interception)
3. Component roles (forms, buttons, lists)

NOTE: Database table linking (`impacts_db`) is intentionally set to `null`.
This will be implemented in Phase 2 via PR-Diff analysis, which provides
100% precision by analyzing actual code changes rather than heuristics.

Phase 1 (Current): Contextual Onboarding - Map the application
Phase 2 (Next): Intent Ingestion - Link to PR diffs for exact table changes

Output format enables autonomous testing when combined with PR-Diff analysis.
"""
import asyncio
import json
import os
import re
from typing import Dict, List, Any, Optional, Tuple
from playwright.async_api import async_playwright, Page, Request, Response
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.callbacks import CallbackManagerForLLMRun
from pydantic import Field
import httpx

# Import our fixed LLM
import sys
sys.path.append(os.path.dirname(__file__))


class FixedNutanixChatModel(BaseChatModel):
    """Custom ChatModel for Nutanix API."""
    
    api_url: str = Field(description="Nutanix API base URL")
    api_key: str = Field(description="Nutanix API key")
    model_name: str = Field(default="openai/gpt-oss-120b")
    temperature: float = Field(default=0)
    max_tokens: int = Field(default=4096)
    
    model_config = {"extra": "allow"}
    
    @property
    def _llm_type(self) -> str:
        return "nutanix-chat"
    
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
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
        
        with httpx.Client(verify=False, timeout=120.0) as client:
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
    
    def _generate(
        self,
        messages: List[Any],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate chat completion."""
        message_dicts = []
        for m in messages:
            if hasattr(m, 'content'):
                role = "user"
                if m.__class__.__name__ == "AIMessage":
                    role = "assistant"
                elif m.__class__.__name__ == "SystemMessage":
                    role = "system"
                message_dicts.append({"role": role, "content": m.content})
        
        response = self._call_api(message_dicts)
        content = self._fix_response(response)
        from langchain_core.messages import AIMessage
        ai_message = AIMessage(content=content)
        generation = ChatGeneration(message=ai_message)
        return ChatResult(generations=[generation])


# --- Configuration ---
CONFIG = {
    "BASE_URL": "http://localhost:5173",
    "API_BASE": "http://localhost:8000",
    "BACKEND_PATH": "../sample-app/backend",
    "GRAPH_FILE": "semantic_graph.json"
}


class SemanticMapper:
    """Enriched mapper that produces semantic navigation graph."""
    
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.graph = {
            "nodes": [],
            "edges": [],
            "api_endpoints": {},
            "db_tables": {}
        }
        self.network_log: List[Dict] = []
        self.visited_urls: set = set()
        self.route_templates: Dict[str, Dict] = {}  # Template URL -> merged node data
        self.discovered_templates: set = set()  # Track which templates we've already discovered
    
    async def analyze_with_llm(self, prompt: str) -> str:
        """Use LLM to analyze and extract semantic information."""
        try:
            result = self.llm.invoke([HumanMessage(content=prompt)])
            # Result is a ChatResult object, access message content directly
            if hasattr(result, 'generations') and result.generations:
                return result.generations[0].message.content
            elif hasattr(result, 'content'):
                return result.content
            else:
                return str(result)
        except Exception as e:
            print(f"   ⚠️ LLM analysis failed: {e}")
            return ""
    
    def _extract_primary_entity(self, url: str, active_apis: List[str], components: List[Dict]) -> Optional[str]:
        """Extract primary entity from URL, APIs, or components.
        
        This extracts the main entity (e.g., "Product", "Order") that this page/component manages.
        Priority: API endpoints > URL path > component roles
        
        Returns:
            Entity name (e.g., "Product") or None
        """
        import re
        
        # Strategy 1: Extract from API endpoints (most reliable)
        for api in active_apis:
            # Extract path from API: "GET /products" -> "/products"
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
                        return entity
        
        # Strategy 2: Extract from component API triggers
        for component in components:
            for api in component.get("triggers_api", []):
                api_path = api.split(' ', 1)[-1] if ' ' in api else api
                if api_path.startswith('/'):
                    path_segment = api_path.strip('/').split('/')[0]
                    if path_segment:
                        if path_segment.endswith('s') and len(path_segment) > 3:
                            entity = path_segment[:-1].title()
                        else:
                            entity = path_segment.title()
                        if len(entity) > 2:
                            return entity
        
        # Strategy 3: Extract from URL path
        if url:
            # Extract path from URL: http://localhost:5173/products -> /products
            url_path = url.split('://', 1)[-1].split('/', 1)[-1] if '://' in url else url
            if url_path and url_path != '/':
                path_segment = url_path.split('/')[0]
                if path_segment:
                    if path_segment.endswith('s') and len(path_segment) > 3:
                        entity = path_segment[:-1].title()
                    else:
                        entity = path_segment.title()
                    if len(entity) > 2:
                        return entity
        
        # Strategy 4: Extract from component database impacts
        for component in components:
            db_table = component.get("impacts_db")
            if db_table:
                # Handle plural: products -> Product
                if db_table.endswith('s') and len(db_table) > 3:
                    entity = db_table[:-1].title()
                else:
                    entity = db_table.title()
                if len(entity) > 2:
                    return entity
        
        return None
    
    async def extract_semantic_components(self, page: Page, url: str) -> List[Dict]:
        """Extract semantic components (forms, buttons, lists) with roles."""
        components = []
        
        # Extract forms
        forms = await page.query_selector_all('form')
        for i, form in enumerate(forms):
            form_id = await form.get_attribute('id') or f"form-{i}"
            action = await form.get_attribute('action') or ""
            
            # Get all inputs in this form
            inputs = await form.query_selector_all('input, textarea, select')
            fields = []
            for inp in inputs:
                field_name = await inp.get_attribute('name')
                field_placeholder = await inp.get_attribute('placeholder') or ""
                field_type = await inp.get_attribute('type') or "text"
                field_id = await inp.get_attribute('id') or ""
                tag_name = await inp.evaluate("el => el.tagName.toLowerCase()")
                
                # Build a stable selector based on tag type
                if field_name:
                    if tag_name == "select":
                        selector = f"select[name='{field_name}']"
                    elif tag_name == "textarea":
                        selector = f"textarea[name='{field_name}']"
                    else:
                        selector = f"input[name='{field_name}']"
                elif field_id:
                    selector = f"{tag_name}#{field_id}"
                elif field_placeholder:
                    selector = f"{tag_name}[placeholder='{field_placeholder}']"
                else:
                    if tag_name == "select":
                        selector = f"select"
                    elif tag_name == "textarea":
                        selector = f"textarea"
                    else:
                        selector = f"input[type='{field_type}']"
                
                # Use placeholder as display name if no name attribute
                display_name = field_name or field_placeholder or field_id or f"field_{len(fields)}"
                
                fields.append({
                    "name": display_name,
                    "type": field_type,
                    "selector": selector,
                    "tag": tag_name,  # Store tag name for executor
                    "has_name_attr": bool(field_name)
                })
            
            # Get submit button
            submit_btn = await form.query_selector('button[type="submit"], input[type="submit"], button')
            submit_text = ""
            if submit_btn:
                submit_text = await submit_btn.inner_text()
            
            # Use LLM to infer semantic role
            if fields:
                llm_prompt = f"""Analyze this form and assign a semantic role:
Form ID: {form_id}
Fields: {', '.join([f['name'] for f in fields])}
Submit button: {submit_text}

What is this form's purpose? Respond with ONLY a short role name (e.g., "create_item_form", "login_form", "search_form").
"""
                semantic_role = await self.analyze_with_llm(llm_prompt)
                semantic_role = semantic_role.strip().lower().replace(' ', '_')
            else:
                semantic_role = f"form_{form_id}"
            
            components.append({
                "type": "form",
                "role": semantic_role,
                "selector": f"form#{form_id}" if form_id != f"form-{i}" else f"form:nth-of-type({i+1})",
                "fields": fields,
                "triggers_api": [],  # Will be filled during interaction
                "impacts_db": None   # Will be filled via schema lookup
            })
        
        # Extract buttons (outside forms)
        buttons = await page.query_selector_all('button:not(form button)')
        for i, btn in enumerate(buttons):
            btn_text = (await btn.inner_text()).strip()
            btn_id = await btn.get_attribute('id')
            btn_class = await btn.get_attribute('class')
            btn_data_testid = await btn.get_attribute('data-testid')
            
            # Extract stable text (remove dynamic content like counts, prices)
            # Pattern: "Products (6)" -> "Products", "Cart (0) - $0.00" -> "Cart"
            stable_text = btn_text
            if btn_text:
                # Remove patterns like "(6)", "($0.00)", "- $0.00", etc.
                stable_text = re.sub(r'\s*\([^)]*\)', '', stable_text)  # Remove (count)
                stable_text = re.sub(r'\s*-\s*\$[\d.]+', '', stable_text)  # Remove - $price
                stable_text = re.sub(r'\s*\$[\d.]+', '', stable_text)  # Remove $price
                stable_text = stable_text.strip()
            
            # Build stable selector (prefer ID, then class, then partial text)
            selector = None
            if btn_id:
                selector = f"button#{btn_id}"
            elif btn_data_testid:
                selector = f"button[data-testid='{btn_data_testid}']"
            elif btn_class:
                # Use first meaningful class (skip generic ones)
                classes = btn_class.split()
                meaningful_classes = [c for c in classes if c not in ['btn', 'button', 'active']]
                if meaningful_classes:
                    selector = f"button.{meaningful_classes[0]}"
            
            # Fallback to partial text match (without dynamic content)
            # Use :has-text() with stable text, but prefer more specific patterns
            if not selector and stable_text:
                # For tabs, try to match by position in tabs container
                parent = await btn.evaluate_handle('el => el.parentElement')
                if parent:
                    parent_tag = await parent.evaluate('el => el.tagName')
                    parent_class = await parent.evaluate('el => el.className')
                    if 'tabs' in str(parent_class).lower():
                        # Tab buttons - use position-based selector within tabs
                        tab_index = i  # This might need adjustment
                        selector = f".tabs button:nth-child({tab_index + 1})"
                    else:
                        # Regular button - use stable text
                        selector = f"button:has-text('{stable_text}')"
                else:
                    selector = f"button:has-text('{stable_text}')"
            
            # Final fallback
            if not selector:
                selector = f"button:nth-of-type({i+1})"
            
            # Generate semantic role from stable text
            if stable_text:
                role_base = stable_text.lower().replace(' ', '_').replace('(', '').replace(')', '')
                # Clean up role (remove special chars)
                role_base = re.sub(r'[^a-z0-9_]', '', role_base)
                semantic_role = f"button_{role_base}"
            else:
                semantic_role = f"button_{i}"
            
            components.append({
                "type": "button",
                "role": semantic_role,
                "selector": selector,
                "text": btn_text,  # Keep original text for reference
                "stable_text": stable_text,  # Add stable text for matching
                "triggers_api": [],
                "impacts_db": None
            })
        
        # Extract lists/tables (data display)
        lists = await page.query_selector_all('ul, ol, table, [role="list"]')
        for i, lst in enumerate(lists):
            items = await lst.query_selector_all('li, tr, [role="listitem"]')
            if len(items) > 0:
                # Use LLM to understand what this list displays
                list_html = await lst.evaluate("el => el.outerHTML")
                list_preview = list_html[:300]
                
                llm_prompt = f"""What does this list display? HTML: {list_preview}
Respond with ONLY a short name (e.g., "items_list", "user_table", "navigation_menu").
"""
                semantic_role = await self.analyze_with_llm(llm_prompt)
                semantic_role = semantic_role.strip().lower().replace(' ', '_')
                
                # Get tag name properly (await the coroutine)
                tag_name = await lst.evaluate("el => el.tagName")
                selector = f"ul:nth-of-type({i+1})" if tag_name == "UL" else f"table:nth-of-type({i+1})"
                
                components.append({
                    "type": "list",
                    "role": semantic_role,
                    "selector": selector,
                    "item_count": len(items),
                    "triggers_api": [],  # List likely loads from GET API
                    "impacts_db": None
                })
        
        return components
    
    async def setup_network_interception(self, page: Page):
        """Setup network interception to capture API calls."""
        
        async def handle_request(request: Request):
            """Capture outgoing API requests."""
            if CONFIG["API_BASE"] in request.url or "localhost:8000" in request.url:
                self.network_log.append({
                    "type": "request",
                    "method": request.method,
                    "url": request.url,
                    "timestamp": asyncio.get_event_loop().time()
                })
                print(f"   📤 {request.method} {request.url}")
        
        async def handle_response(response: Response):
            """Capture API responses."""
            if CONFIG["API_BASE"] in response.url or "localhost:8000" in response.url:
                try:
                    status = response.status
                    # Try to get response body (may fail for some responses)
                    body = None
                    try:
                        body = await response.json()
                    except:
                        pass
                    
                    self.network_log.append({
                        "type": "response",
                        "method": response.request.method,
                        "url": response.url,
                        "status": status,
                        "body": body,
                        "timestamp": asyncio.get_event_loop().time()
                    })
                    print(f"   📥 {response.status} {response.request.method} {response.url}")
                except Exception as e:
                    print(f"   ⚠️ Error capturing response: {e}")
        
        page.on("request", handle_request)
        page.on("response", handle_response)
    
    async def enrich_components_with_apis(self, components: List[Dict], start_time: float, end_time: float):
        """Link captured API calls to the components that triggered them."""
        # Get API calls that happened during this page's interaction
        page_apis = [
            log for log in self.network_log 
            if start_time <= log["timestamp"] <= end_time
        ]
        
        for component in components:
            # Match APIs based on timing and type
            relevant_apis = []
            
            if component["type"] == "form":
                # Forms usually trigger POST/PUT requests
                relevant_apis = [
                    api for api in page_apis 
                    if api["type"] == "request" and api["method"] in ["POST", "PUT", "PATCH"]
                ]
            elif component["type"] == "list":
                # Lists usually load via GET requests
                relevant_apis = [
                    api for api in page_apis 
                    if api["type"] == "request" and api["method"] == "GET"
                ]
            elif component["type"] == "button":
                # Buttons could trigger any type of request
                relevant_apis = [api for api in page_apis if api["type"] == "request"]
            
            # Store unique API endpoints
            unique_endpoints = set()
            for api in relevant_apis:
                endpoint = api["url"].replace(CONFIG["API_BASE"], "")
                unique_endpoints.add(f"{api['method']} {endpoint}")
            
            component["triggers_api"] = list(unique_endpoints)
            
            # For each API, try to link to DB table
            if unique_endpoints:
                # Take the first API endpoint
                first_api = list(unique_endpoints)[0]
                method, endpoint = first_api.split(" ", 1)
                db_table = await self.link_api_to_db(endpoint, method)
                if db_table:
                    component["impacts_db"] = db_table
    
    async def discover_page(self, page: Page, url: str, parent_url: Optional[str] = None, action: str = "navigate") -> str:
        """Discover and analyze a single page."""
        if url in self.visited_urls:
            return url
        
        self.visited_urls.add(url)
        
        print(f"\n🔍 Discovering: {url}")
        
        # Record start time for API correlation
        start_time = asyncio.get_event_loop().time()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=10000)
            await asyncio.sleep(1)  # Let any dynamic content load
        except Exception as e:
            print(f"   ⚠️ Failed to load page: {e}")
            return url
        
        # Extract page title and semantic name
        title = await page.title()
        
        # Use LLM to generate semantic page name
        body_text = await page.inner_text('body')
        body_preview = body_text[:500]
        
        llm_prompt = f"""What is this page's purpose?
URL: {url}
Title: {title}
Content preview: {body_preview}

Respond with ONLY a short semantic name (e.g., "items_dashboard", "login_page", "user_profile").
"""
        semantic_name = await self.analyze_with_llm(llm_prompt)
        semantic_name = semantic_name.strip().lower().replace(' ', '_')
        
        # Generate a human-readable display title/header
        # Keep both semantic_name (for programmatic matching) and display_header (for UI display)
        header_prompt = f"""Generate a clean, human-readable page title/header for this page:
URL: {url}
Page Title: {title}
Semantic Name: {semantic_name}
Content preview: {body_preview[:300]}

Respond with ONLY a short, clean title (e.g., "Order Management Dashboard", "Orders Page", "Product Catalog", "Shopping Cart").
Do not include quotes or extra formatting, just the title text.
"""
        display_header = await self.analyze_with_llm(header_prompt)
        display_header = display_header.strip().strip('"').strip("'")
        
        # Fallback: generate from semantic_name if LLM fails
        # This ensures display_header always exists, but semantic_name is preserved for matching
        if not display_header or len(display_header) < 3:
            # Convert semantic_name to title case: "order_management_dashboard" -> "Order Management Dashboard"
            display_header = semantic_name.replace('_', ' ').title()
        
        # Extract semantic components
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
        
        # Create node
        # IMPORTANT: Keep both semantic_name (for programmatic matching) and display_header (for UI display)
        # - semantic_name: Used by context_processor for finding nodes, mission.json target_node, etc.
        # - display_header: Used by UI components for human-readable labels
        node_id = semantic_name or f"page_{len(self.graph['nodes'])}"
        node = {
            "id": node_id,
            "url": url,
            "semantic_name": semantic_name,  # e.g., "order_management_dashboard" - for programmatic matching
            "title": title,
            "display_header": display_header,  # e.g., "Order Management Dashboard" - for UI display
            "primary_entity": primary_entity,  # Store extracted entity
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
                "selector": None  # Would need to track which element was clicked
            })
        
        print(f"   ✅ Node: {node_id}")
        print(f"   📦 Components: {len(components)}")
        print(f"   📡 APIs: {len(active_apis)}")
        
        return url
    
    async def try_button_opens_form(self, page: Page, button_component: Dict, current_node: Dict) -> bool:
        """Try clicking a button that might open a form, then detect and interact with the form.
        
        This handles cases where forms appear dynamically (e.g., modals, collapsible forms).
        """
        print(f"\n🔧 Testing button that might open form: {button_component['role']}")
        
        try:
            # Click the button
            button_selector = button_component.get("selector")
            if not button_selector:
                return False
            
            # Record network activity before click
            start_time = asyncio.get_event_loop().time()
            network_before = len(self.network_log)
            
            # Click button
            await page.click(button_selector, timeout=3000)
            await asyncio.sleep(0.5)  # Wait for form to appear
            
            # Look for form that appeared (could be in modal or on page)
            form_selectors = [
                "form:visible",
                ".modal form",
                "[role='dialog'] form",
                "form[data-testid*='add']",
                "form[data-testid*='create']"
            ]
            
            form_element = None
            for selector in form_selectors:
                try:
                    form_element = await page.query_selector(selector)
                    if form_element:
                        break
                except:
                    continue
            
            if not form_element:
                print(f"   ⚠️ No form appeared after clicking button")
                return False
            
            # Extract form fields
            form_id = await form_element.get_attribute('id') or "dynamic-form"
            inputs = await form_element.query_selector_all('input, textarea, select')
            
            fields = []
            for inp in inputs:
                field_name = await inp.get_attribute('name')
                field_placeholder = await inp.get_attribute('placeholder') or ""
                field_type = await inp.get_attribute('type') or "text"
                field_id = await inp.get_attribute('id') or ""
                tag_name = await inp.evaluate("el => el.tagName.toLowerCase()")
                
                # Build selector
                if field_name:
                    if tag_name == "select":
                        selector = f"select[name='{field_name}']"
                    else:
                        selector = f"input[name='{field_name}']"
                elif field_id:
                    selector = f"{tag_name}#{field_id}"
                elif field_placeholder:
                    selector = f"{tag_name}[placeholder='{field_placeholder}']"
                else:
                    selector = f"{tag_name}[type='{field_type}']"
                
                display_name = field_name or field_placeholder or field_id or f"field_{len(fields)}"
                
                fields.append({
                    "name": display_name,
                    "type": field_type,
                    "selector": selector,
                    "tag": tag_name,
                    "has_name_attr": bool(field_name)
                })
            
            if not fields:
                print(f"   ⚠️ Form has no fields")
                return False
            
            print(f"   ✅ Found form with {len(fields)} field(s)")
            
            # Fill form with test data
            for field in fields:
                selector = field["selector"]
                tag = field.get("tag", "input")
                
                # Generate test value
                field_name_lower = field["name"].lower()
                if "name" in field_name_lower:
                    test_value = "Test Product"
                elif "description" in field_name_lower:
                    test_value = "Test description"
                elif "price" in field_name_lower or "cost" in field_name_lower:
                    test_value = "49.99"
                elif "stock" in field_name_lower or field["type"] == "number":
                    test_value = "100"
                elif "category" in field_name_lower:
                    test_value = "Electronics"
                else:
                    test_value = f"test_{field['name']}"
                
                try:
                    if tag == "select":
                        await page.select_option(selector, test_value, timeout=2000)
                    else:
                        await page.fill(selector, test_value, timeout=2000)
                    print(f"   ✏️ Filled {field['name']}: {test_value}")
                except Exception as e:
                    print(f"   ⚠️ Could not fill {field['name']}: {e}")
            
            # Find and click submit button
            submit_selectors = [
                "button[type='submit']",
                "button:has-text('Create')",
                "button:has-text('Add')",
                "button:has-text('Submit')",
                "button:has-text('Save')"
            ]
            
            submit_clicked = False
            for submit_selector in submit_selectors:
                try:
                    submit_btn = await form_element.query_selector(submit_selector)
                    if submit_btn:
                        await submit_btn.click()
                        submit_clicked = True
                        print(f"   ✅ Clicked submit button")
                        break
                except:
                    continue
            
            if not submit_clicked:
                print(f"   ⚠️ Could not find submit button")
                return False
            
            # Wait for network activity
            await page.wait_for_load_state("networkidle", timeout=5000)
            await asyncio.sleep(1)
            
            end_time = asyncio.get_event_loop().time()
            network_after = len(self.network_log)
            
            # Get APIs triggered during form submission
            triggered_apis = self.network_log[network_before:network_after]
            request_apis = [
                f"{log['method']} {log['url'].replace(CONFIG['API_BASE'], '').replace('http://localhost:8000', '')}"
                for log in triggered_apis
                if log["type"] == "request"
            ]
            
            # Create or update form component in the node
            form_component = None
            for comp in current_node["components"]:
                if comp.get("type") == "form" and comp.get("role") == "create_product_form":
                    form_component = comp
                    break
            
            if not form_component:
                # Create new form component
                form_component = {
                    "type": "form",
                    "role": "create_product_form",
                    "selector": "form:visible, .modal form",
                    "fields": fields,
                    "triggers_api": [],
                    "impacts_db": None
                }
                current_node["components"].append(form_component)
            
            # Update component with triggered APIs
            form_component["triggers_api"] = list(set(request_apis))
            form_component["fields"] = fields  # Update fields
            
            # Also update button component to reference the form
            button_component["opens_form"] = True
            button_component["form_role"] = form_component["role"]
            
            print(f"   📡 Triggered {len(request_apis)} API call(s)")
            for api in request_apis:
                print(f"      • {api}")
            
            return True
            
        except Exception as e:
            print(f"   ⚠️ Button/form interaction failed: {e}")
            return False
    
    async def try_form_interaction(self, page: Page, component: Dict, current_node: Dict) -> bool:
        """Try to interact with a form to discover API calls."""
        if component["type"] != "form":
            return False
        
        print(f"\n🔧 Testing form: {component['role']}")
        
        try:
            # Fill form fields with test data
            for field in component["fields"]:
                selector = field["selector"]
                test_value = f"test_{field['name']}"
                
                try:
                    await page.fill(selector, test_value, timeout=2000)
                    print(f"   ✏️ Filled {field['name']}: {test_value}")
                except Exception as e:
                    print(f"   ⚠️ Could not fill {field['name']}: {e}")
            
            # Find and click submit button
            form_selector = component["selector"]
            submit_btn = await page.query_selector(f"{form_selector} button[type='submit'], {form_selector} button")
            
            if submit_btn:
                # Record network activity before click
                start_time = asyncio.get_event_loop().time()
                network_before = len(self.network_log)
                
                await submit_btn.click()
                await page.wait_for_load_state("networkidle", timeout=5000)
                
                end_time = asyncio.get_event_loop().time()
                network_after = len(self.network_log)
                
                # Get APIs triggered during form submission
                triggered_apis = self.network_log[network_before:network_after]
                request_apis = [
                    f"{log['method']} {log['url'].replace(CONFIG['API_BASE'], '').replace('http://localhost:8000', '')}"
                    for log in triggered_apis
                    if log["type"] == "request"
                ]
                
                # Update component with triggered APIs
                component["triggers_api"] = list(set(request_apis))
                
                # Note: impacts_db will be determined from PR diff in Phase 2
                component["impacts_db"] = None  # TODO: Get from PR diff
                
                print(f"   📡 Triggered {len(request_apis)} API call(s)")
                for api in request_apis:
                    print(f"      • {api}")
                return True
        
        except Exception as e:
            print(f"   ⚠️ Form interaction failed: {e}")
            return False
        
        return False
    
    def normalize_parameterized_route(self, url: str) -> Tuple[str, Optional[str], Optional[str]]:
        """Normalize parameterized routes to templates.
        
        Examples:
            /products/1 -> /products/{productId}, productId, 1
            /orders/123 -> /orders/{orderId}, orderId, 123
            /products -> /products, None, None
        
        Returns:
            (template_url, param_name, param_value)
        """
        import re
        
        # Pattern: /products/123, /orders/456, etc.
        # Match numeric IDs at the end of URL path
        pattern = r'^(.+)/(\d+)$'
        match = re.match(pattern, url.replace(CONFIG['BASE_URL'], ''))
        
        if match:
            base_path = match.group(1)
            param_value = match.group(2)
            
            # Infer parameter name from base path
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
                # Generic: use last segment name
                segments = base_path.split('/')
                last_segment = segments[-1] if segments else 'id'
                param_name = f"{last_segment}Id"
                template = f"{base_path}/{{{param_name}}}"
            
            # Convert to full URL template
            full_template = f"{CONFIG['BASE_URL']}{template}"
            return full_template, param_name, param_value
        
        return url, None, None
    
    def normalize_api_endpoint(self, api: str) -> str:
        """Normalize API endpoints with IDs to templates.
        
        Examples:
            GET /products/1 -> GET /products/{productId}
            POST /orders/123 -> POST /orders/{orderId}
        """
        import re
        
        # Pattern: METHOD /path/123
        pattern = r'^(\w+)\s+(.+)/(\d+)$'
        match = re.match(pattern, api)
        
        if match:
            method = match.group(1)
            base_path = match.group(2)
            param_value = match.group(3)
            
            # Infer parameter name
            if '/products' in base_path:
                param_name = '{productId}'
            elif '/orders' in base_path:
                param_name = '{orderId}'
            elif '/users' in base_path:
                param_name = '{userId}'
            else:
                segments = base_path.split('/')
                last_segment = segments[-1] if segments else 'id'
                param_name = f"{{{last_segment}Id}}"
            
            return f"{method} {base_path}/{param_name}"
        
        return api
    
    def merge_parameterized_nodes(self):
        """Merge nodes with parameterized routes into template nodes."""
        print("\n🔄 Merging parameterized routes...")
        
        # Group nodes by template
        template_groups: Dict[str, List[Dict]] = {}
        nodes_to_remove = []
        
        for node in self.graph["nodes"]:
            url = node["url"]
            template_url, param_name, param_value = self.normalize_parameterized_route(url)
            
            if param_name:  # This is a parameterized route
                if template_url not in template_groups:
                    template_groups[template_url] = []
                template_groups[template_url].append(node)
                nodes_to_remove.append(node)
        
        # Create merged template nodes
        merged_count = 0
        for template_url, nodes in template_groups.items():
            if len(nodes) <= 1:
                # Only one instance, no need to merge
                continue
            
            # Get parameter name from first node
            _, param_name, _ = self.normalize_parameterized_route(nodes[0]["url"])
            
            # Use the first node as base, merge components and APIs
            base_node = nodes[0].copy()
            base_node["url"] = template_url
            base_node["url_template"] = template_url
            base_node["is_template"] = True
            base_node["parameter_name"] = param_name
            
            # Merge components (deduplicate by selector)
            seen_selectors = set()
            merged_components = []
            for node in nodes:
                for comp in node.get("components", []):
                    selector = comp.get("selector", "")
                    if selector and selector not in seen_selectors:
                        # Normalize API endpoints in component
                        if comp.get("triggers_api"):
                            comp["triggers_api"] = [
                                self.normalize_api_endpoint(api) 
                                for api in comp["triggers_api"]
                            ]
                        merged_components.append(comp)
                        seen_selectors.add(selector)
            
            # Merge active APIs (normalize and deduplicate)
            merged_apis = set()
            for node in nodes:
                for api in node.get("active_apis", []):
                    normalized = self.normalize_api_endpoint(api)
                    merged_apis.add(normalized)
            
            base_node["components"] = merged_components
            base_node["active_apis"] = list(merged_apis)
            
            # Re-extract primary entity for merged template (may have more APIs now)
            base_node["primary_entity"] = self._extract_primary_entity(
                template_url, 
                list(merged_apis), 
                merged_components
            )
            
            # Update semantic name to indicate it's a template
            if not base_node["semantic_name"].endswith("_template"):
                base_node["semantic_name"] = f"{base_node['semantic_name']}_template"
            
            # Update display header to indicate it's a template if not already updated
            if "display_header" not in base_node or not base_node.get("display_header"):
                # Generate from semantic name
                base_node["display_header"] = base_node["semantic_name"].replace('_', ' ').title()
            elif not base_node["display_header"].endswith(" (Template)"):
                base_node["display_header"] = f"{base_node['display_header']} (Template)"
            
            # Replace first node with merged template
            node_index = self.graph["nodes"].index(nodes[0])
            self.graph["nodes"][node_index] = base_node
            
            # Remove other duplicate nodes
            for node in nodes[1:]:
                if node in self.graph["nodes"]:
                    self.graph["nodes"].remove(node)
            
            merged_count += len(nodes) - 1
            print(f"   ✅ Merged {len(nodes)} nodes into template: {template_url}")
        
        # Normalize edges to use template URLs
        for edge in self.graph["edges"]:
            from_template, _, _ = self.normalize_parameterized_route(edge["from"])
            to_template, _, _ = self.normalize_parameterized_route(edge["to"])
            
            # Update edge to use template if it exists
            if from_template != edge["from"]:
                # Find the template node ID
                for node in self.graph["nodes"]:
                    if node.get("url") == from_template:
                        edge["from"] = node["id"]
                        break
            
            if to_template != edge["to"]:
                for node in self.graph["nodes"]:
                    if node.get("url") == to_template:
                        edge["to"] = node["id"]
                        break
        
        print(f"   ✅ Merged {merged_count} duplicate nodes into templates")
    
    async def discover_navigation_links(self, page: Page) -> List[Dict[str, str]]:
        """Discover navigation links (React Router Links, anchor tags, buttons that navigate)."""
        links = []
        
        try:
            # Find React Router Link components (they render as <a> tags)
            link_elements = await page.query_selector_all('a[href]')
            
            for link in link_elements:
                href = await link.get_attribute('href')
                text = (await link.inner_text()).strip()
                link_id = await link.get_attribute('id')
                data_testid = await link.get_attribute('data-testid')
                
                if href:
                    # Convert relative URLs to absolute
                    if href.startswith('/'):
                        full_url = f"{CONFIG['BASE_URL']}{href}"
                    elif href.startswith('http'):
                        # Only include links to our app
                        if CONFIG['BASE_URL'] in href:
                            full_url = href
                        else:
                            continue
                    else:
                        # Relative path, construct full URL
                        current_url = page.url
                        base = current_url.rsplit('/', 1)[0] if '/' in current_url else CONFIG['BASE_URL']
                        full_url = f"{base}/{href}"
                    
                    # Build selector
                    selector = None
                    if link_id:
                        selector = f"a#{link_id}"
                    elif data_testid:
                        selector = f"a[data-testid='{data_testid}']"
                    elif text:
                        # Use text content as fallback
                        selector = f"a:has-text('{text[:50]}')"  # Limit text length
                    
                    links.append({
                        "url": full_url,
                        "text": text,
                        "selector": selector or f"a[href='{href}']",
                        "href": href
                    })
            
            # Also check navigation buttons (like in our Navigation component)
            nav_buttons = await page.query_selector_all('nav a, .navigation a, [data-testid^="nav-"]')
            for btn in nav_buttons:
                href = await btn.get_attribute('href')
                if href and href not in [l['href'] for l in links]:
                    text = (await btn.inner_text()).strip()
                    data_testid = await btn.get_attribute('data-testid')
                    
                    if href.startswith('/'):
                        full_url = f"{CONFIG['BASE_URL']}{href}"
                    elif href.startswith('http') and CONFIG['BASE_URL'] in href:
                        full_url = href
                    else:
                        continue
                    
                    selector = None
                    if data_testid:
                        selector = f"a[data-testid='{data_testid}']"
                    elif text:
                        selector = f"a:has-text('{text[:50]}')"
                    
                    links.append({
                        "url": full_url,
                        "text": text,
                        "selector": selector or f"a[href='{href}']",
                        "href": href
                    })
            
        except Exception as e:
            print(f"   ⚠️ Error discovering links: {e}")
        
        return links
    
    async def discover_all_routes(self, page: Page, start_url: str, max_depth: int = 3, current_depth: int = 0):
        """Recursively discover all routes by following navigation links.
        
        For parameterized routes (e.g., /products/1, /products/2), we discover at least
        one instance to find components/links, but skip additional instances of the same template.
        """
        if current_depth >= max_depth:
            return
        
        # Check if this is a parameterized route we've already discovered
        template_url, param_name, param_value = self.normalize_parameterized_route(start_url)
        if param_name and template_url in self.discovered_templates:
            # We've already discovered this template, skip to avoid redundant discovery
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
        
        # Filter to only internal routes (same base URL)
        internal_links = [
            link for link in links 
            if link['url'].startswith(CONFIG['BASE_URL']) and link['url'] not in self.visited_urls
        ]
        
        # Smart filtering: Group links by template pattern and only visit one per template
        # This prevents visiting 100+ product detail pages when they're all the same template
        template_groups: Dict[str, List[Dict]] = {}
        non_template_links = []
        
        for link in internal_links:
            link_template, link_param, _ = self.normalize_parameterized_route(link['url'])
            
            if link_param:
                # This is a parameterized route - group by template
                if link_template in self.discovered_templates:
                    # Already discovered this template, skip
                    continue
                
                if link_template not in template_groups:
                    template_groups[link_template] = []
                template_groups[link_template].append(link)
            else:
                # Non-parameterized route - check if already visited
                if link['url'] not in self.visited_urls:
                    non_template_links.append(link)
        
        # For each template, only visit the first instance
        filtered_links = []
        for template_url, template_links in template_groups.items():
            if template_links:
                # Only add the first link from this template group
                # The template will be marked as discovered after visiting this first instance
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
                print(f"\n   🔗 Following: {link['text']} → {link['url']}")
                
                # Navigate to the link (actual navigation in Chromium)
                await page.goto(link['url'], wait_until="networkidle", timeout=10000)
                await asyncio.sleep(1)  # Let page load
                
                # Recursively discover this page (will add to visited_urls and create node)
                # This will also discover links from the new page
                await self.discover_all_routes(page, link['url'], max_depth, current_depth + 1)
                
                # After discovery, create edge from current page to linked page
                if current_node_id:
                    # Find the target node ID (should exist now after discovery)
                    # For templates, we need to find the template node
                    target_node_id = None
                    link_template, _, _ = self.normalize_parameterized_route(link['url'])
                    
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
                
                # Note: We don't navigate back because we're doing depth-first traversal
                # The navigation bar appears on every page, so we'll discover all routes
                # The visited_urls check prevents re-discovering pages
                
            except Exception as e:
                print(f"   ⚠️ Failed to follow link {link['url']}: {e}")
                continue


async def run_semantic_mapper():
    """Main function - runs the semantic discovery mapper."""
    
    print("=" * 70)
    print("🧬 SEMANTIC DISCOVERY MAPPER - Triple-Check Edition")
    print("=" * 70)
    print()
    
    # Load environment
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        load_dotenv(env_file)
        print("✅ Loaded .env configuration")
    
    api_url = os.getenv("NUTANIX_API_URL")
    api_key = os.getenv("NUTANIX_API_KEY")
    model = os.getenv("NUTANIX_MODEL", "openai/gpt-oss-120b")
    
    if not api_url or not api_key:
        print("❌ Missing NUTANIX_API_URL or NUTANIX_API_KEY")
        return
    
    print(f"🤖 LLM: {model}")
    print(f"🌐 Target: {CONFIG['BASE_URL']}")
    print()
    
    # Initialize LLM
    llm = FixedNutanixChatModel(
        api_url=api_url,
        api_key=api_key,
        model_name=model
    )
    
    # Initialize mapper
    mapper = SemanticMapper(llm)
    
    # Run discovery
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Setup network interception
        await mapper.setup_network_interception(page)
        
        try:
            # Discover all routes by following navigation links
            print("\n🚀 Starting route discovery...")
            await mapper.discover_all_routes(page, CONFIG["BASE_URL"], max_depth=3)
            
            # Try to interact with forms on each discovered page to discover more APIs
            print("\n🔧 Interacting with forms to discover APIs...")
            for node in mapper.graph["nodes"]:
                if node["components"]:
                    # Navigate to the page
                    try:
                        await page.goto(node["url"], wait_until="networkidle", timeout=10000)
                        await asyncio.sleep(1)
                        
                        # First, try buttons that might open forms (like "Add Product" button)
                        for component in node["components"]:
                            if component["type"] == "button":
                                # Check if button text suggests it opens a form
                                btn_text = component.get("text", "").lower()
                                btn_role = component.get("role", "").lower()
                                if any(keyword in btn_text or keyword in btn_role for keyword in ["add", "create", "new", "open"]):
                                    await mapper.try_button_opens_form(page, component, node)
                        
                        # Then, interact with existing forms
                        for component in node["components"]:
                            if component["type"] == "form":
                                await mapper.try_form_interaction(page, component, node)
                    except Exception as e:
                        print(f"   ⚠️ Could not interact with forms on {node['url']}: {e}")
                        continue
            
        finally:
            await browser.close()
    
    # Merge parameterized routes into templates
    mapper.merge_parameterized_nodes()
    
    # Save graph
    output_path = os.path.join(os.path.dirname(__file__), CONFIG["GRAPH_FILE"])
    with open(output_path, 'w') as f:
        json.dump(mapper.graph, f, indent=2)
    
    # Print summary
    print()
    print("=" * 70)
    print("✅ SEMANTIC MAPPING COMPLETE")
    print("=" * 70)
    print(f"📊 Output: {output_path}")
    print(f"   Nodes: {len(mapper.graph['nodes'])}")
    print(f"   Edges: {len(mapper.graph['edges'])}")
    print(f"   API calls captured: {len(mapper.network_log)}")
    print()
    
    # Print detailed node info
    for node in mapper.graph["nodes"]:
        print(f"📄 {node['semantic_name']} ({node['url']})")
        print(f"   Active APIs: {len(node['active_apis'])}")
        for api in node['active_apis']:
            print(f"      • {api}")
        print(f"   Components: {len(node['components'])}")
        for comp in node['components']:
            print(f"      • {comp['type']}: {comp['role']}")
            if comp.get('triggers_api'):
                print(f"         └─ API: {', '.join(comp['triggers_api'])}")
            if comp.get('impacts_db'):
                print(f"         └─ DB: {comp['impacts_db']}")
    
    print()
    print("🎯 Next Step: Use this graph with the Triple-Check Runner")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_semantic_mapper())
