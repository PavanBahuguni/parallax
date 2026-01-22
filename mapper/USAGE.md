# Mapper Folder - Clean Structure

## 📁 Production Files

```
mapper/
├── semantic_mapper.py          # 🎯 Main mapper (use this!)
├── semantic_graph.json         # 📊 Generated output
├── graph_queries.py            # 🔍 Query helper
├── view_chromadb.py           # 👁️ View semantic storage
├── agent_memory/              # 💾 ChromaDB storage
├── SEMANTIC_MAPPER_README.md  # 📖 Documentation
├── STORAGE_ARCHITECTURE.md    # 🏗️ Storage design decisions
├── README.md                  # 🚀 Quick start guide
├── pyproject.toml             # 📦 Dependencies
├── env.example                # ⚙️ Configuration template
└── uv.lock                    # 🔒 Dependency lock
```

## 🚀 Usage

### 1. Run Discovery Mapper
```bash
uv run python semantic_mapper.py
```

**Output**: `semantic_graph.json` with full-stack traceability

### 2. View Results

**Summary**:
```bash
uv run python graph_queries.py summary
```

**All APIs**:
```bash
uv run python graph_queries.py apis
```

**Database Tables**:
```bash
uv run python graph_queries.py tables
```

**Semantic Search**:
```bash
uv run python graph_queries.py search "forms that create items"
```

### 3. View ChromaDB Data

**All entries**:
```bash
uv run python view_chromadb.py
```

**Search**:
```bash
uv run python view_chromadb.py search "create item"
```

## 📊 What Each Tool Does

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `semantic_mapper.py` | Discover app structure | Initial mapping, after UI changes |
| `graph_queries.py` | Query discovered data | Find components, APIs, tables |
| `view_chromadb.py` | Inspect semantic storage | Debug, understand what was captured |

## 🎯 Query Examples

### Python API

```python
from graph_queries import GraphQueries

queries = GraphQueries()

# Find a specific component
form = queries.find_component_by_role("create_item_form")
print(form["selector"])  # "form:nth-of-type(1)"
print(form["triggers_api"])  # ["POST /items", "GET /items"]
print(form["impacts_db"])  # "items"

# Find all forms
forms = queries.find_components_by_type("form")

# Find components that use an API
components = queries.find_components_using_api("POST /items")

# Find components that modify a table
components = queries.find_components_impacting_table("items")

# Get all APIs
apis = queries.get_all_apis()
print(apis)  # ["GET /items", "POST /items"]

# Get statistics
stats = queries.get_stats()
print(f"Discovered {stats['components']} components")

# Semantic search
results = queries.semantic_search("forms that add data")
for result in results:
    print(f"Found: {result['metadata']['url']} (similarity: {result['similarity']:.2%})")
```

### CLI

```bash
# Quick summary
uv run python graph_queries.py summary

# List all API endpoints
uv run python graph_queries.py apis
# Output:
#   • GET /items
#   • POST /items

# Show database tables and dependencies
uv run python graph_queries.py tables
# Output:
#   items:
#     Components: create_item_form
#     APIs: POST /items, GET /items

# Semantic search
uv run python graph_queries.py search "create new items"
```

## 🏗️ Storage Architecture

### Hybrid Approach (Current)

We use **both** JSON and ChromaDB:

**JSON (`semantic_graph.json`)**:
- ✅ Structure and relationships
- ✅ Fast exact lookups
- ✅ Version control friendly
- ✅ Human-readable
- ✅ No database server needed

**ChromaDB (`agent_memory/`)**:
- ✅ Semantic embeddings
- ✅ Vector search ("find similar")
- ✅ Natural language queries
- ✅ Persistent storage

### Why Not Neo4j/ArangoDB?

- Your graph is small (1-50 nodes typically)
- No complex graph algorithms needed yet
- JSON + NetworkX handles current needs
- Avoid infrastructure overhead

### When to Upgrade

Consider a graph database if:
- **1000+ nodes** (large multi-page apps)
- **Complex queries** needed ("shortest path from A to B with constraint C")
- **Real-time collaborative mapping** (multiple agents)
- **Graph algorithms** (PageRank, community detection)

For now: **JSON + ChromaDB is perfect** ✅

## 📖 Documentation

- **`SEMANTIC_MAPPER_README.md`**: Detailed mapper documentation
- **`STORAGE_ARCHITECTURE.md`**: Storage design decisions
- **`README.md`**: Quick start guide
- **`../SEMANTIC_GRAPH_COMPARISON.md`**: Before/after comparison

## 🔄 Workflow

```
1. Run semantic_mapper.py
   └─ Generates semantic_graph.json
   └─ Stores embeddings in agent_memory/

2. Query with graph_queries.py
   └─ Find components by role/type
   └─ Discover API/DB relationships
   └─ Get statistics

3. View raw data with view_chromadb.py
   └─ Inspect semantic storage
   └─ Debug what was captured

4. Use in Triple-Check Runner (next step)
   └─ Read semantic_graph.json
   └─ Auto-generate tests
   └─ Execute DB → API → UI verification
```

## 🧹 Cleaned Up

**Removed files** (obsolete/test):
- ❌ `discovery_mapper.py` (old version)
- ❌ `discovery_mapper_working.py` (old version)
- ❌ `browser_use_fixed.py` (experimental)
- ❌ `browser_use_mapper.py` (incomplete)
- ❌ `debug_browser_use.py` (debug script)
- ❌ `test_browser_use.py` (test script)
- ❌ `test_mapper.py` (old test)
- ❌ `simple_mapper.py` (POC without LLM)
- ❌ `nutanix_llm.py` (integrated into semantic_mapper.py)
- ❌ `sitemap_graph.json` (old format)
- ❌ `NUTANIX_API_ISSUE.md` (resolved issue)

**Result**: Clean, production-ready folder with only necessary files.

## 🎓 Next Steps

1. **Triple-Check Runner**: Use semantic_graph.json to auto-generate tests
2. **Jira Integration**: Parse tickets → find components → execute tests
3. **Multi-page crawling**: Discover entire apps automatically
4. **CI/CD Integration**: Run mapper on every deployment

---

**Questions?** Check `SEMANTIC_MAPPER_README.md` for detailed documentation.
