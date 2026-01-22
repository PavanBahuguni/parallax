# Agentic QA System

A comprehensive system for automated web application testing using AI agents and semantic discovery.

## 🎯 What This Does

This system automatically explores your web application and generates a **semantic navigation graph** that links:
- **DOM elements** (buttons, forms, inputs)
- **API endpoints** (GET, POST, PUT, DELETE)
- **Database tables** (which data gets modified)

This enables **autonomous triple-checking**: DB → API → UI verification for any feature.

## Project Structure

```
agentic-qa/
├── sample-app/             # Full-stack demo application
│   ├── backend/           # FastAPI + PostgreSQL backend
│   └── frontend/          # React + TypeScript frontend
├── mapper/                # AI-powered semantic discovery
│   ├── semantic_mapper.py     # 🆕 Enriched mapper (use this!)
│   ├── browser_use_fixed.py   # Browser-use integration
│   ├── semantic_graph.json    # 🆕 Output: full-stack graph
│   ├── SEMANTIC_MAPPER_README.md  # 📖 Detailed documentation
│   └── pyproject.toml         # Dependencies
├── run_mapper.py         # Convenience script
└── implementation-plan-*.md  # Project documentation
```

## 🚀 Quick Start

### 1. Sample Application

**Backend:**
```bash
cd sample-app/backend
uv sync
# Create .env file with: DATABASE_URL=postgresql://postgres@localhost:5432/postgres
uv run uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd sample-app/frontend
npm install
npm run dev
```

Visit: http://localhost:5173

### 2. Semantic Discovery Mapper

**Setup:**
```bash
cd mapper
uv sync
uv run playwright install chromium

# Create .env file:
cat > .env << EOF
NUTANIX_API_URL=https://dev-nuchat-server.saas.nutanix.com/api/v1
NUTANIX_API_KEY=your_base64_key
NUTANIX_MODEL=openai/gpt-oss-120b
EOF
```

**Run:**
```bash
uv run python semantic_mapper.py
```

**Output:**
```json
{
  "nodes": [{
    "id": "items_manager",
    "components": [{
      "role": "create_item_form",
      "selector": "input[placeholder='Item name']",
      "triggers_api": ["POST /items"],
      "impacts_db": "items"
    }]
  }]
}
```

## 📊 What Makes This Different

### Old Approach (Simple Navigation Log)
```json
{
  "nodes": [
    {"id": "http://localhost:5173", "label": "Step 1"}
  ],
  "apis": []  // ❌ Empty!
}
```

### New Approach (Semantic Graph) ✨
```json
{
  "nodes": [{
    "semantic_name": "items_manager",
    "components": [{
      "role": "create_item_form",
      "selector": "input[placeholder='Item name']",  // ✅ Stable selector
      "triggers_api": ["POST /items", "GET /items"], // ✅ Captured APIs
      "impacts_db": "items"                          // ✅ DB table link
    }]
  }]
}
```

## 🧬 Semantic Graph Features

### 1. **Semantic Identifiers**
- CSS selectors instead of brittle indices
- `input[placeholder='Item name']` not `index 33`

### 2. **API Anchoring**
- Network interception captures real API calls
- Links user actions → backend endpoints

### 3. **Component Roles**
- LLM-powered semantic naming
- `create_item_form` not `form_0`

### 4. **Database Linking**
- Parses backend code to find DB tables
- Automatic inference from SQLAlchemy models

### 5. **Full-Stack Traceability**
For every UI component, you know:
- **Selector**: How to find it in the DOM
- **APIs**: Which endpoints it triggers
- **Database**: Which tables it modifies

## 🎓 Use Cases

### 1. Triple-Check Testing
```python
# Read semantic graph
component = graph["nodes"][0]["components"][0]

# ✅ DB check
db.insert("items", {"name": "Test"})

# ✅ API check
response = requests.post("/items", json={"name": "Test"})
assert response.status == 200

# ✅ UI check
page.fill(component["selector"], "Test")
page.click("button:has-text('Add')")
assert page.locator("text=Test").is_visible()
```

### 2. Jira Ticket → Test
```python
# Ticket: "Test create item feature"
# Agent finds "create_item_form" in graph
# Auto-generates and executes test
```

### 3. Regression Testing
```python
# Graph knows all API endpoints
# For each endpoint, verify:
# - Response schema unchanged
# - DB writes correct
# - UI updates properly
```

## 📦 Prerequisites

- **Python 3.11+**
- **[uv](https://github.com/astral-sh/uv)** (Python package manager)
- **Node.js 16+** (for frontend)
- **PostgreSQL** (for backend)
- **Nutanix LLM API** or **Ollama** (for semantic analysis)

## 📖 Documentation

- **`mapper/SEMANTIC_MAPPER_README.md`**: Detailed mapper documentation
- **`sample-app/README.md`**: Sample app setup guide
- **`implementation-plan-2.md`**: Original discovery mapper design

## 🔧 Configuration

### Mapper Config (`mapper/semantic_mapper.py`)
```python
CONFIG = {
    "BASE_URL": "http://localhost:5173",      # Frontend
    "API_BASE": "http://localhost:8000",      # Backend API
    "BACKEND_PATH": "../sample-app/backend",  # For DB linking
    "GRAPH_FILE": "semantic_graph.json"
}
```

### Environment Variables
```ini
# Nutanix Hosted LLM
NUTANIX_API_URL=https://dev-nuchat-server.saas.nutanix.com/api/v1
NUTANIX_API_KEY=your_base64_encoded_key
NUTANIX_MODEL=openai/gpt-oss-120b
```

## 🎯 Next Steps

### Immediate (You Can Use Now)
- ✅ Run `semantic_mapper.py` on your app
- ✅ Get enriched graph with API/DB links
- ✅ Use selectors for stable test automation

### Coming Soon
- [ ] **Triple-Check Runner**: Automated DB → API → UI verification
- [ ] **Jira Integration**: Ticket → Test generation
- [ ] **Multi-page crawling**: Discover entire app automatically
- [ ] **Edge pre-conditions**: Track "must login first" flows
- [ ] **Visual regression**: Screenshot comparison

## 🐛 Troubleshooting

### "No API calls captured"
```bash
# Check backend is running
curl http://localhost:8000/items

# Verify API_BASE in config matches
# semantic_mapper.py line 104
```

### "impacts_db is null"
```bash
# Check backend path is correct
ls ../sample-app/backend/app/models.py

# Verify models have __tablename__
grep "__tablename__" ../sample-app/backend/app/models.py
```

### "LLM analysis failed"
```bash
# Test LLM connection
cd mapper
uv run python -c "from semantic_mapper import FixedNutanixChatModel; ..."

# Check .env credentials
cat .env
```

## 🤝 Contributing

We use `uv` for dependency management:

```bash
# Add dependency
cd mapper
uv add package-name

# Update dependencies
uv sync

# Run tests (coming soon)
uv run pytest
```

## 📝 License

MIT

## 🙏 Acknowledgments

- **browser-use**: AI-powered browser automation
- **Playwright**: Reliable web automation
- **NetworkX**: Graph data structures
- **ChromaDB**: Vector storage for semantic data
- **Nutanix**: Hosted LLM API

---

**Status**: ✅ Semantic mapper production-ready

**Next**: Triple-Check Runner for autonomous testing
