# Semantic Discovery Mapper - Triple-Check Edition

## Overview

This mapper produces a **semantic navigation graph** that contains the "DNA" needed for autonomous full-stack testing. Unlike simple navigation logs, this graph links:

- **DOM elements** → **API endpoints** → **Database tables**
- **User actions** → **Backend code** → **Data persistence**

## Output Format: `semantic_graph.json`

### Structure

```json
{
  "nodes": [
    {
      "id": "items_manager",
      "url": "http://localhost:5173",
      "semantic_name": "items_manager",
      "title": "Vite + React + TS",
      "components": [
        {
          "type": "form",
          "role": "create_item_form",
          "selector": "form:nth-of-type(1)",
          "fields": [
            {
              "name": "Item name",
              "type": "text",
              "selector": "input[placeholder='Item name']",
              "has_name_attr": false
            }
          ],
          "triggers_api": ["POST /items", "GET /items"],
          "impacts_db": "items"
        }
      ],
      "active_apis": ["GET /items"]
    }
  ],
  "edges": [],
  "api_endpoints": {},
  "db_tables": {}
}
```

### Key Features

#### 1. **Semantic Identifiers** ✅
- **CSS selectors** instead of brittle indices
- **Stable references**: `input[placeholder='Item name']` not `index 33`
- **Multiple fallbacks**: name → id → placeholder → type

#### 2. **API Anchoring** ✅
- **Network interception** captures real API calls
- **`triggers_api`**: Which APIs fire when you interact with a component
- **`active_apis`**: Which APIs load when the page loads

#### 3. **Component Roles** ✅
- **Semantic naming** via LLM analysis
- **`create_item_form`** not just "form 1"
- **Types**: form, button, list, table

#### 4. **Database Linking** ✅
- **`impacts_db`**: Which Postgres table is modified
- **Automatic inference** from backend `models.py`
- **Schema lookup**: Parses SQLAlchemy models

#### 5. **Full-Stack Traceability**
For every user action, you know:
- **UI**: Which element to interact with (`selector`)
- **API**: Which endpoint gets called (`triggers_api`)
- **DB**: Which table gets modified (`impacts_db`)

## Usage

### Run the Mapper

```bash
cd mapper
uv run python semantic_mapper.py
```

### Output

```
🧬 SEMANTIC DISCOVERY MAPPER - Triple-Check Edition
======================================================================
✅ Node: items_manager
📦 Components: 1
   • form: create_item_form
      └─ API: POST /items, GET /items
      └─ DB: items
```

### Generated Files

- **`semantic_graph.json`**: The enriched navigation graph
- **Network log**: All API calls captured during exploration

## How It Enables Triple-Checking

### Example: Testing "Create Item" Feature

With the semantic graph, an autonomous test agent can:

1. **Find the component**:
   ```python
   component = graph["nodes"][0]["components"][0]
   # role: "create_item_form"
   ```

2. **Interact with UI**:
   ```python
   selector = component["selector"]  # "form:nth-of-type(1)"
   page.fill("input[placeholder='Item name']", "Test Item")
   ```

3. **Verify API call**:
   ```python
   expected_api = component["triggers_api"][0]  # "POST /items"
   assert network_log.contains(expected_api)
   ```

4. **Check database**:
   ```python
   table = component["impacts_db"]  # "items"
   result = db.execute(f"SELECT * FROM {table} WHERE name='Test Item'")
   assert result is not None
   ```

## Architecture

### Discovery Process

```
1. Navigate to page
   └─ Capture GET requests (active_apis)

2. Extract components
   ├─ Forms: inputs + submit buttons
   ├─ Buttons: standalone actions
   └─ Lists/Tables: data display elements

3. Interact with each component
   └─ Capture POST/PUT requests (triggers_api)

4. Link APIs to database tables
   └─ Parse backend/app/models.py
```

### LLM-Powered Semantic Analysis

The mapper uses your Nutanix hosted LLM to:
- **Name pages**: "items_manager" not "page_0"
- **Name components**: "create_item_form" not "form_1"
- **Understand purpose**: Infers what a form/button does from context

### Network Interception

Uses Playwright's request/response listeners:
```python
page.on("request", handle_request)
page.on("response", handle_response)
```

Captures:
- Method (GET, POST, PUT, DELETE)
- URL (full endpoint path)
- Status code (200, 404, 500)
- Response body (for validation)

### Database Schema Linking

Parses `backend/app/models.py`:
```python
pattern = r'class\s+\w+.*?__tablename__\s*=\s*["\'](\w+)["\']'
```

Matches:
- `/items` → `items` table
- `/users` → `users` table
- `/orders` → `orders` table

## Comparison

| Feature | Old Format | New Format |
|---------|-----------|------------|
| Element reference | `index 33` | `input[placeholder='Item name']` |
| Component name | `form_0` | `create_item_form` |
| API capture | Empty `[]` | `["POST /items", "GET /items"]` |
| DB linking | Missing | `"impacts_db": "items"` |
| Semantic meaning | None | LLM-inferred roles |

## Next Steps

### Triple-Check Runner (Coming Next)

This script will:
1. **Read a Jira ticket**: "Test create item feature"
2. **Find the component** in `semantic_graph.json`
3. **Execute the triple-check**:
   - ✅ DB: Insert test data directly
   - ✅ API: Call `POST /items` and verify response
   - ✅ UI: Fill form and verify item appears
4. **Report results**: Pass/fail with detailed logs

### Enhancements

- [ ] **Multi-page crawling**: Follow `<a>` tags to discover more nodes
- [ ] **Edge pre-conditions**: Track "must login first" requirements
- [ ] **Response validation**: Store expected response schemas
- [ ] **Error scenarios**: Test 404, 500, validation errors
- [ ] **State transitions**: Track page → action → new page flows

## Configuration

Edit `semantic_mapper.py`:

```python
CONFIG = {
    "BASE_URL": "http://localhost:5173",      # Frontend URL
    "API_BASE": "http://localhost:8000",      # Backend API
    "BACKEND_PATH": "../sample-app/backend",  # Path to backend code
    "GRAPH_FILE": "semantic_graph.json"       # Output file
}
```

## Requirements

```toml
[project.dependencies]
browser-use = ">=0.11.2"
playwright = ">=1.57.0"
langchain-ollama = ">=1.0.1"
httpx = "*"
python-dotenv = "*"
```

## Environment Variables

Create `.env`:

```ini
NUTANIX_API_URL=https://dev-nuchat-server.saas.nutanix.com/api/v1
NUTANIX_API_KEY=your_base64_encoded_key
NUTANIX_MODEL=openai/gpt-oss-120b
```

## Troubleshooting

### "No API calls captured"

- ✅ Check `API_BASE` in config matches your backend
- ✅ Ensure backend is running (`localhost:8000`)
- ✅ Verify CORS allows frontend → backend calls

### "impacts_db is null"

- ✅ Check `BACKEND_PATH` points to correct directory
- ✅ Verify `app/models.py` exists with `__tablename__` definitions
- ✅ Ensure SQLAlchemy models follow standard pattern

### "LLM analysis failed"

- ✅ Verify `.env` has correct API credentials
- ✅ Test LLM directly: `llm.invoke([HumanMessage(content="test")])`
- ✅ Check Nutanix API quota/rate limits

## Contributing

To extend the mapper:

1. **Add new component types**: Edit `extract_semantic_components()`
2. **Improve DB linking**: Enhance `link_api_to_db()` with more patterns
3. **Add edge pre-conditions**: Track authentication/authorization requirements
4. **Support more frameworks**: Adapt selectors for Vue, Angular, etc.

---

**Status**: ✅ Production-ready for single-page applications

**Next**: Triple-Check Runner implementation
