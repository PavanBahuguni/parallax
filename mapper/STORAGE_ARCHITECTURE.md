# Storage Architecture: Graph Store vs ChromaDB

## Current Architecture ✅

You asked: **"Should we use a graph store for this? or just chroma is fine?"**

**My recommendation: Keep the current hybrid approach, but enhance it slightly.**

## Why Not a Pure Graph Database?

### Current Approach (Hybrid)
```
JSON File (semantic_graph.json)
  └─ Stores: Structure, relationships, metadata
  └─ Purpose: Quick lookups, easy to version control, human-readable

ChromaDB (agent_memory/)
  └─ Stores: Semantic embeddings of descriptions
  └─ Purpose: Vector search, "find similar components"
```

### Problems with Pure Graph DB (Neo4j, ArangoDB)

| Issue | Impact |
|-------|--------|
| **Overkill** | Your graph is small (1-50 nodes typically) |
| **Infrastructure** | Requires separate database server |
| **Complexity** | Cypher/AQL query language learning curve |
| **Version Control** | Can't `git diff` a database |
| **Portability** | Harder to share/deploy |

### When You WOULD Need Graph DB

- **1000+ nodes**: Multi-page apps with complex navigation
- **Deep queries**: "Find all paths from login to checkout"
- **Real-time updates**: Multiple agents updating concurrently
- **Complex relationships**: Many edge types, constraints

## Enhanced Hybrid Architecture (Recommended)

### Structure

```
mapper/
├── semantic_graph.json       # 🎯 Source of truth (structure)
├── agent_memory/             # 🔍 ChromaDB (semantic search)
└── graph_queries.py          # 🛠️ Query helpers (new!)
```

### Why This Works

1. **JSON = Structure**: Fast lookups, easy to diff, version-controlled
2. **ChromaDB = Semantics**: Vector search for "find similar forms"
3. **Python = Queries**: NetworkX for graph algorithms when needed

### Example Queries

```python
# Load graph
graph = json.load(open("semantic_graph.json"))

# Find component by role
component = next(c for n in graph["nodes"] 
                 for c in n["components"] 
                 if c["role"] == "create_item_form")

# Find all forms that touch a specific API
forms_using_api = [
    c for n in graph["nodes"]
    for c in n["components"]
    if c["type"] == "form" and "POST /items" in c["triggers_api"]
]

# Use ChromaDB for semantic search
results = collection.query(
    query_texts=["forms that create items"],
    n_results=5
)
```

## Proposed Enhancement: Add Query Layer

Let me create `graph_queries.py` to make querying easier:

