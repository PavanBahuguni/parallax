# Agentic QA Discovery Mapper

**✅ Production-Ready Semantic Mapper with Full-Stack Traceability**

This mapper automatically explores your web application and generates a **semantic navigation graph** that links DOM elements → API endpoints → Database tables, enabling autonomous triple-check testing.

## Features

- 🧬 **Semantic Discovery**: LLM-powered component naming (`create_item_form` not `form_0`)
- 🔍 **Network Interception**: Captures API calls during interaction
- 📊 **Graph Output**: JSON format with full-stack traceability
- 🔎 **Vector Search**: ChromaDB for semantic queries
- 🛠️ **Query Tools**: CLI and Python API for exploring data
- 🧠 **Context Processor**: Phase 1 - Intent extraction from task.md → Mission JSON

## Output Format

```json
{
  "nodes": [{
    "id": "items_manager",
    "semantic_name": "items_manager",
    "components": [{
      "type": "form",
      "role": "create_item_form",
      "selector": "form:nth-of-type(1)",
      "fields": [
        {
          "name": "Item name",
          "selector": "input[placeholder='Item name']"
        }
      ],
      "triggers_api": ["POST /items", "GET /items"],
      "impacts_db": "items"
    }],
    "active_apis": ["GET /items"]
  }]
}
```

## Prerequisites

- **Python 3.11+**
- **[uv](https://github.com/astral-sh/uv)** - Python package manager
- **Nutanix LLM API** - Hosted 120B model (or OpenAI-compatible endpoint)
- **Running application** - Frontend + Backend to explore

## Quick Start

### 1. Install Dependencies

```bash
cd mapper
uv sync
uv run playwright install chromium
```

### 2. Configure API Credentials

Create `.env` file:

```bash
cp env.example .env
```

Edit `.env`:

```ini
NUTANIX_API_URL=https://dev-nuchat-server.saas.nutanix.com/api/v1
NUTANIX_API_KEY=your_base64_encoded_key
NUTANIX_MODEL=openai/gpt-oss-120b
```

### 3. Start Your Application

```bash
# Backend (Terminal 1)
cd ../sample-app/backend
uv run uvicorn app.main:app --reload

# Frontend (Terminal 2)
cd ../sample-app/frontend
npm run dev
```

### 4. Run the Mapper

```bash
cd mapper
uv run python semantic_mapper.py
```

## Output

```
🧬 SEMANTIC DISCOVERY MAPPER - Triple-Check Edition
======================================================================
✅ Node: items_manager
📦 Components: 1
   • form: create_item_form
      └─ API: POST /items, GET /items
      └─ DB: items
======================================================================
✅ MAPPING COMPLETE!
   Graph: semantic_graph.json
   Nodes: 1
   API calls captured: 8
```

**Generated Files**:
- `semantic_graph.json` - Full-stack semantic graph
- `agent_memory/` - ChromaDB vector storage

## Phase 1: Context Processor

Transform task descriptions into structured test missions:

```bash
# Create task.md with description and PR link
cat > task.md << EOF
# Test New Item Creation

Verify that the form works correctly.

PR Link: https://github.com/example/repo/pull/123
EOF

# Generate mission.json
uv run python context_processor.py task.md
```

**Output**: `temp/TASK-1_mission.json` with complete test plan (target node, test data, verification points)

See `CONTEXT_PROCESSOR_README.md` for details.

## Phase 2: Triple-Check Executor (Hybrid Architecture)

Execute missions with **deterministic fast path** + **agentic recovery**:

```bash
# Execute mission (with healer enabled)
uv run python executor.py temp/TASK-1_mission.json

# Execute in deterministic-only mode (no LLM)
uv run python executor.py temp/TASK-1_mission.json --no-healer
```

**Features**:
- ⚡ **Fast Path**: Deterministic execution using mission.json selectors (3s timeout)
- 🔧 **Healer Mode**: LLM-powered recovery when selectors break
- 🔍 **Triple-Check**: Verifies DB → API → UI consistency
- 📊 **Auto-Healing**: Updates mission.json with recovered selectors

**Output**: `temp/TASK-1_mission_report.json` with execution results

See `EXECUTOR_README.md` for details.

## Query Tools

### View Summary

```bash
uv run python graph_queries.py summary
```

### View All APIs

```bash
uv run python graph_queries.py apis
```

### View Database Tables

```bash
uv run python graph_queries.py tables
```

### Semantic Search

```bash
uv run python graph_queries.py search "forms that create items"
```

### View ChromaDB Data

```bash
# All entries
uv run python view_chromadb.py

# Search
uv run python view_chromadb.py search "create item"
```

## Python API

```python
from graph_queries import GraphQueries

q = GraphQueries()

# Find component by role
form = q.find_component_by_role("create_item_form")
print(form["selector"])        # "form:nth-of-type(1)"
print(form["triggers_api"])    # ["POST /items", "GET /items"]
print(form["impacts_db"])      # "items"

# Find all forms
forms = q.find_components_by_type("form")

# Find components using an API
components = q.find_components_using_api("POST /items")

# Find components impacting a table
components = q.find_components_impacting_table("items")

# Get all APIs
apis = q.get_all_apis()
print(apis)  # ["GET /items", "POST /items"]

# Get statistics
stats = q.get_stats()
print(f"Components: {stats['components']}, APIs: {stats['apis']}")

# Semantic search
results = q.semantic_search("forms that add data", n_results=5)
for result in results:
    print(f"Similarity: {result['similarity']:.2%}")
    print(f"URL: {result['metadata']['url']}")
```

## Configuration

Edit `semantic_mapper.py`:

```python
CONFIG = {
    "BASE_URL": "http://localhost:5173",      # Frontend URL
    "API_BASE": "http://localhost:8000",      # Backend API
    "BACKEND_PATH": "../sample-app/backend",  # For DB linking
    "GRAPH_FILE": "semantic_graph.json"
}
```

## What It Discovers

### 1. Semantic Identifiers
- CSS selectors: `input[placeholder='Item name']`
- Not brittle indices: ~~`index 33`~~
- Multiple fallbacks: name → id → placeholder → type

### 2. Component Roles
- LLM-inferred: `create_item_form`
- Types: form, button, list, table
- Semantic naming throughout

### 3. API Anchoring
- Network interception via Playwright
- Captures: `GET /items`, `POST /items`
- Links to components that trigger them

### 4. Database Linking
- Parses `backend/app/models.py`
- Finds SQLAlchemy `__tablename__`
- Maps APIs → DB tables: `/items` → `items` table

### 5. Full-Stack Traceability
- **UI**: Which element (`selector`)
- **API**: Which endpoint (`triggers_api`)
- **DB**: Which table (`impacts_db`)

## Troubleshooting

### "No API calls captured"

```bash
# Check backend is running
curl http://localhost:8000/items

# Verify API_BASE in semantic_mapper.py matches
grep "API_BASE" semantic_mapper.py
```

### "impacts_db is null"

```bash
# Check backend path exists
ls ../sample-app/backend/app/models.py

# Verify models have __tablename__
grep "__tablename__" ../sample-app/backend/app/models.py
```

### "LLM analysis failed"

```bash
# Check .env credentials
cat .env

# Test API directly
curl -X POST "YOUR_API_URL/chat/completions" \
  -H "Authorization: Basic YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"openai/gpt-oss-120b","messages":[{"role":"user","content":"test"}],"max_tokens":5}'
```

### Frontend/Backend not running

```bash
# Verify services are accessible
curl http://localhost:5173
curl http://localhost:8000/health
```

## Documentation

- **`SEMANTIC_MAPPER_README.md`** - Detailed mapper documentation
- **`STORAGE_ARCHITECTURE.md`** - Why JSON + ChromaDB is optimal
- **`USAGE.md`** - Complete usage guide for all tools
- **`../SEMANTIC_GRAPH_COMPARISON.md`** - Before/after comparison

## Use Cases

### 1. Triple-Check Testing
```python
# Read semantic graph
component = graph["nodes"][0]["components"][0]

# ✅ DB check
db.insert(component["impacts_db"], test_data)

# ✅ API check
response = requests.post(component["triggers_api"][0], json=test_data)

# ✅ UI check
page.fill(component["selector"], test_data)
```

### 2. Jira Ticket → Test
- Ticket: "Test create item feature"
- Agent finds `create_item_form` in graph
- Auto-generates DB/API/UI test
- Executes and reports results

### 3. Regression Testing
- Graph knows all API endpoints
- For each endpoint: verify schema, DB writes, UI updates
- Run on every deployment

## Next Steps

- **Triple-Check Runner**: Auto-generate tests from graph
- **Jira Integration**: Ticket → test generation
- **Multi-page crawling**: Discover entire apps
- **CI/CD Integration**: Run mapper on every deployment

## Storage Architecture

**Current**: Hybrid JSON + ChromaDB

- **JSON** (`semantic_graph.json`): Structure, fast lookups, version control
- **ChromaDB** (`agent_memory/`): Semantic search, vector embeddings

**Why not Neo4j/ArangoDB?**: Your graph is small (1-50 nodes). JSON + NetworkX handles current needs without infrastructure overhead. See `STORAGE_ARCHITECTURE.md` for details.

## Files

```
mapper/
├── semantic_mapper.py          # 🎯 Main mapper (use this!)
├── semantic_graph.json         # 📊 Generated output
├── graph_queries.py            # 🔍 Query helper
├── view_chromadb.py           # 👁️ View semantic storage
├── agent_memory/              # 💾 ChromaDB storage
├── README.md                  # 📖 This file
├── SEMANTIC_MAPPER_README.md  # 📖 Detailed docs
├── STORAGE_ARCHITECTURE.md    # 🏗️ Storage design
├── USAGE.md                   # 🚀 Usage guide
└── pyproject.toml             # 📦 Dependencies
```

## Contributing

```bash
# Add dependency
uv add package-name

# Update dependencies
uv sync

# Run mapper
uv run python semantic_mapper.py

# Query results
uv run python graph_queries.py summary
```

---

**Status**: ✅ Production-ready

**Next**: Triple-Check Runner for autonomous testing
