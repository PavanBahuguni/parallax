# Graph Queries - Persona-Based Querying

The `graph_queries.py` module now supports querying persona-specific semantic graphs.

## Basic Usage

### 1. Load a Persona-Specific Graph

```python
from graph_queries import GraphQueries

# Load Reseller persona graph
queries = GraphQueries(persona="Reseller")

# Load Distributor persona graph
queries = GraphQueries(persona="Distributor")

# Load default graph (no persona)
queries = GraphQueries()
```

### 2. List Available Personas

```python
queries = GraphQueries()
personas = queries.get_personas_in_graph()
print(personas)  # ['Reseller', 'Distributor']
```

### 3. Filter Nodes by Persona

```python
queries = GraphQueries()

# Get all nodes for Reseller persona
reseller_nodes = queries.filter_by_persona("Reseller")
print(f"Reseller has {len(reseller_nodes)} nodes")

# Get all nodes (optionally filtered)
all_nodes = queries.get_all_nodes()
reseller_only = queries.get_all_nodes(persona="Reseller")
```

### 4. Find Components by Persona

```python
queries = GraphQueries(persona="Reseller")

# Find component (automatically filtered to Reseller persona)
component = queries.find_component_by_role("create_deal_form")
```

### 5. Semantic Search with Persona Filter

```python
queries = GraphQueries(persona="Reseller")

# Index the graph first
queries.index_graph_to_chromadb()

# Search within Reseller persona only
results = queries.semantic_search("dashboard with opportunities", persona="Reseller")
for result in results:
    print(f"{result['metadata']['display_header']}: {result['similarity']:.2%}")
```

## Command Line Usage

### List all personas in graph:
```bash
python graph_queries.py personas
```

### Query Reseller persona graph:
```bash
# Summary
python graph_queries.py --persona Reseller summary

# Search
python graph_queries.py --persona Reseller search "dashboard"

# List APIs
python graph_queries.py --persona Reseller apis
```

### Query Distributor persona graph:
```bash
python graph_queries.py --persona Distributor summary
```

## Example: Compare Personas

```python
from graph_queries import GraphQueries

# Load both graphs
reseller = GraphQueries(persona="Reseller")
distributor = GraphQueries(persona="Distributor")

# Compare node counts
print(f"Reseller nodes: {len(reseller.get_all_nodes())}")
print(f"Distributor nodes: {len(distributor.get_all_nodes())}")

# Compare APIs
reseller_apis = set(reseller.get_all_apis())
distributor_apis = set(distributor.get_all_apis())
print(f"Common APIs: {len(reseller_apis & distributor_apis)}")
print(f"Reseller-only APIs: {len(reseller_apis - distributor_apis)}")
print(f"Distributor-only APIs: {len(distributor_apis - reseller_apis)}")
```

## API Reference

### GraphQueries Class

#### Constructor
- `GraphQueries(graph_path=None, chromadb_path="agent_memory", persona=None)`
  - `persona`: Optional persona name (e.g., "Reseller", "Distributor")

#### Persona Methods
- `filter_by_persona(persona: str) -> List[Dict]`: Get all nodes for a persona
- `get_personas_in_graph() -> List[str]`: List all personas in the graph

#### Query Methods (with persona parameter)
- `get_all_nodes(persona=None) -> List[Dict]`: Get nodes (optionally filtered)
- `find_component_by_role(role: str, persona=None) -> Optional[Dict]`
- `semantic_search(query: str, n_results=5, persona=None) -> List[Dict]`

## Notes

- Persona graphs are stored as `semantic_graph_{PersonaName}.json`
- Case-insensitive matching is used when loading persona graphs
- Nodes are tagged with persona in `node.context.persona`
- ChromaDB indexing includes persona metadata for filtering
