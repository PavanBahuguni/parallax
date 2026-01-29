"""Query helpers for semantic graph and ChromaDB.

Provides convenient methods to search and analyze the discovered UI structure.
"""
import json
import os
import re
from typing import List, Dict, Optional, Any
from pathlib import Path

try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False


class GraphQueries:
    """Helper class for querying semantic graph and ChromaDB."""
    
    def __init__(self, graph_path: str = None, 
                 chromadb_path: str = "agent_memory",
                 persona: Optional[str] = None):
        """Initialize query interface.
        
        Args:
            graph_path: Path to semantic_graph.json (if None, auto-detects based on persona)
            chromadb_path: Path to ChromaDB storage
            persona: Optional persona name (e.g., 'Reseller', 'Distributor') to load persona-specific graph
        """
        self.persona = persona
        self.chromadb_path = Path(__file__).parent / chromadb_path
        
        # Determine graph file path
        mapper_dir = Path(__file__).parent
        
        if graph_path:
            # Explicit path provided
            self.graph_path = Path(__file__).parent / graph_path
        elif persona:
            # Load persona-specific graph (case-insensitive)
            self.graph_path = self._find_persona_graph(mapper_dir, persona)
            if not self.graph_path:
                raise FileNotFoundError(
                    f"Persona graph not found for '{persona}'. "
                    f"Expected: semantic_graph_{persona}.json"
                )
        else:
            # Default to semantic_graph.json
            self.graph_path = mapper_dir / "semantic_graph.json"
        
        # Load graph
        if not self.graph_path.exists():
            raise FileNotFoundError(f"Graph not found: {self.graph_path}")
        
        with open(self.graph_path, 'r') as f:
            self.graph = json.load(f)
        
        # If main graph is empty, try to use persona-specific graphs
        if len(self.graph.get("nodes", [])) == 0 and not persona:
            print(f"   ⚠️  Main graph is empty, looking for persona-specific graphs...")
            for persona_graph in mapper_dir.glob("semantic_graph_*.json"):
                if persona_graph.name == "semantic_graph.json":
                    continue
                try:
                    with open(persona_graph, 'r') as f:
                        pg_data = json.load(f)
                    if len(pg_data.get("nodes", [])) > 0:
                        self.graph = pg_data
                        self.graph_path = persona_graph
                        persona_name = persona_graph.stem.replace("semantic_graph_", "")
                        print(f"   ✅ Using persona graph: {persona_graph.name} ({len(pg_data['nodes'])} nodes)")
                        break
                except Exception:
                    pass
        
        print(f"✅ Loaded graph from: {self.graph_path.name}")
        if persona:
            print(f"   Persona: {persona}")
        
        # Connect to ChromaDB (optional)
        if CHROMADB_AVAILABLE and self.chromadb_path.exists():
            try:
                self.chroma_client = chromadb.PersistentClient(path=str(self.chromadb_path))
                self.collection = self.chroma_client.get_or_create_collection(
                    name="ui_semantic_map"
                )
            except Exception as e:
                print(f"⚠️  ChromaDB connection failed: {e}")
                self.chroma_client = None
                self.collection = None
        else:
            self.chroma_client = None
            self.collection = None
    
    def _find_persona_graph(self, mapper_dir: Path, persona_name: str) -> Optional[Path]:
        """Find persona graph file case-insensitively."""
        # Try exact match first
        exact_file = mapper_dir / f"semantic_graph_{persona_name}.json"
        if exact_file.exists():
            return exact_file
        
        # Try case-insensitive search
        target_name_lower = f"semantic_graph_{persona_name.lower()}.json"
        available_files = list(mapper_dir.glob("semantic_graph_*.json"))
        
        for file_path in available_files:
            if file_path.name.lower() == target_name_lower:
                return file_path
        
        return None
    
    # --- Persona Queries ---
    
    def filter_by_persona(self, persona: str) -> List[Dict[str, Any]]:
        """Filter nodes by persona.
        
        Args:
            persona: Persona name to filter by
        
        Returns:
            List of nodes belonging to this persona
        """
        results = []
        for node in self.graph.get("nodes", []):
            node_persona = node.get("context", {}).get("persona")
            if node_persona and node_persona.lower() == persona.lower():
                results.append(node)
        return results
    
    def get_personas_in_graph(self) -> List[str]:
        """Get list of all personas present in the graph.
        
        Returns:
            List of unique persona names
        """
        personas = set()
        for node in self.graph.get("nodes", []):
            node_persona = node.get("context", {}).get("persona")
            if node_persona:
                personas.add(node_persona)
        return sorted(list(personas))
    
    # --- Component Queries ---
    
    def find_component_by_role(self, role: str, persona: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Find a component by its semantic role.
        
        Args:
            role: Component role (e.g., "create_item_form")
            persona: Optional persona name to filter by
        
        Returns:
            Component dict or None
        """
        for node in self.graph["nodes"]:
            # Filter by persona if specified
            if persona:
                node_persona = node.get("context", {}).get("persona")
                if not node_persona or node_persona.lower() != persona.lower():
                    continue
            
            for component in node.get("components", []):
                if component.get("role") == role:
                    return {**component, "_node": node}
        return None
    
    def find_components_by_type(self, component_type: str) -> List[Dict[str, Any]]:
        """Find all components of a given type.
        
        Args:
            component_type: Type like "form", "button", "list"
        
        Returns:
            List of matching components
        """
        results = []
        for node in self.graph["nodes"]:
            for component in node.get("components", []):
                if component.get("type") == component_type:
                    results.append({**component, "_node": node})
        return results
    
    def find_components_using_api(self, api_endpoint: str) -> List[Dict[str, Any]]:
        """Find components that trigger a specific API.
        
        Args:
            api_endpoint: API like "POST /items" or "GET /products/{productId}"
        
        Returns:
            List of components that trigger this API
        """
        results = []
        import re
        
        # Normalize API endpoint (handle both concrete and template)
        normalized_api = api_endpoint
        # Pattern: METHOD /path/123 -> METHOD /path/{param}
        pattern = r'^(\w+)\s+(.+)/(\d+)$'
        match = re.match(pattern, api_endpoint)
        if match:
            method = match.group(1)
            base_path = match.group(2)
            if '/products' in base_path:
                normalized_api = f"{method} {base_path}/{{productId}}"
            elif '/orders' in base_path:
                normalized_api = f"{method} {base_path}/{{orderId}}"
        
        for node in self.graph["nodes"]:
            for component in node.get("components", []):
                triggers = component.get("triggers_api", [])
                # Check both exact match and normalized match
                if any(api_endpoint in api or normalized_api in api or api in api_endpoint or api in normalized_api 
                       for api in triggers):
                    results.append({**component, "_node": node})
        return results
    
    def find_components_impacting_table(self, table_name: str) -> List[Dict[str, Any]]:
        """Find components that modify a specific database table.
        
        Args:
            table_name: Table name like "items", "users"
        
        Returns:
            List of components that modify this table
        """
        results = []
        for node in self.graph["nodes"]:
            for component in node.get("components", []):
                if component.get("impacts_db") == table_name:
                    results.append({**component, "_node": node})
        return results
    
    # --- Node Queries ---
    
    def find_node_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Find a node by its URL. Handles both concrete URLs and templates.
        
        Args:
            url: Page URL (can be concrete like /products/1 or template like /products/{productId})
        
        Returns:
            Node dict or None
        """
        # First try exact match
        for node in self.graph["nodes"]:
            if node.get("url") == url:
                return node
        
        # If not found, check if it's a parameterized route that matches a template
        import re
        # Pattern: /products/123, /orders/456, etc.
        pattern = r'^(.+)/(\d+)$'
        match = re.match(pattern, url.replace('http://localhost:5173', ''))
        
        if match:
            base_path = match.group(1)
            # Try to find template node
            if '/products' in base_path:
                template_url = f"http://localhost:5173{base_path}/{{productId}}"
            elif '/orders' in base_path:
                template_url = f"http://localhost:5173{base_path}/{{orderId}}"
            else:
                segments = base_path.split('/')
                last_segment = segments[-1] if segments else 'id'
                param_name = f"{{{last_segment}Id}}"
                template_url = f"http://localhost:5173{base_path}/{param_name}"
            
            for node in self.graph["nodes"]:
                if node.get("url") == template_url or node.get("url_template") == template_url:
                    return node
        
        return None
    
    def find_node_by_semantic_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find a node by its semantic name.
        
        Args:
            name: Semantic name like "items_dashboard"
        
        Returns:
            Node dict or None
        """
        for node in self.graph["nodes"]:
            if node.get("semantic_name") == name or node.get("id") == name:
                return node
        return None
    
    def get_all_nodes(self, persona: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all nodes in the graph.
        
        Args:
            persona: Optional persona name to filter by
        
        Returns:
            List of nodes (filtered by persona if specified)
        """
        nodes = self.graph.get("nodes", [])
        if persona:
            return [node for node in nodes 
                   if node.get("context", {}).get("persona", "").lower() == persona.lower()]
        return nodes
    
    # --- API Queries ---
    
    def get_all_apis(self) -> List[str]:
        """Get all API endpoints discovered across all components."""
        apis = set()
        for node in self.graph["nodes"]:
            # Add active APIs (page load)
            apis.update(node.get("active_apis", []))
            
            # Add triggered APIs (component interactions)
            for component in node.get("components", []):
                apis.update(component.get("triggers_api", []))
        
        return sorted(list(apis))
    
    def get_api_coverage(self) -> Dict[str, List[str]]:
        """Get which components use which APIs.
        
        Returns:
            Dict mapping API endpoint -> list of component roles
        """
        coverage = {}
        for node in self.graph["nodes"]:
            for component in node.get("components", []):
                for api in component.get("triggers_api", []):
                    if api not in coverage:
                        coverage[api] = []
                    coverage[api].append(component.get("role", "unknown"))
        return coverage
    
    # --- Database Queries ---
    
    def get_all_tables(self) -> List[str]:
        """Get all database tables that are modified."""
        tables = set()
        for node in self.graph["nodes"]:
            for component in node.get("components", []):
                table = component.get("impacts_db")
                if table:
                    tables.add(table)
        return sorted(list(tables))
    
    def get_table_dependencies(self) -> Dict[str, Dict[str, List[str]]]:
        """Get which components and APIs affect which tables.
        
        Returns:
            Dict mapping table -> {components: [...], apis: [...]}
        """
        deps = {}
        for node in self.graph["nodes"]:
            for component in node.get("components", []):
                table = component.get("impacts_db")
                if not table:
                    continue
                
                if table not in deps:
                    deps[table] = {"components": [], "apis": []}
                
                deps[table]["components"].append(component.get("role", "unknown"))
                deps[table]["apis"].extend(component.get("triggers_api", []))
        
        # Deduplicate
        for table in deps:
            deps[table]["apis"] = list(set(deps[table]["apis"]))
        
        return deps
    
    # --- Semantic Search (ChromaDB) ---
    
    def index_graph_to_chromadb(self, force_reindex: bool = False):
        """Index the semantic graph into ChromaDB for vector search.
        
        Args:
            force_reindex: If True, clear existing data and reindex
        """
        if not CHROMADB_AVAILABLE:
            raise RuntimeError("ChromaDB not available. Install with: pip install chromadb")
        
        if not self.chromadb_path.exists():
            self.chromadb_path.mkdir(parents=True, exist_ok=True)
        
        if not self.chroma_client:
            self.chroma_client = chromadb.PersistentClient(path=str(self.chromadb_path))
            self.collection = self.chroma_client.get_or_create_collection(
                name="ui_semantic_map"
            )
        
        # Check if already indexed
        existing_count = self.collection.count()
        if existing_count > 0 and not force_reindex:
            print(f"✅ ChromaDB already indexed with {existing_count} entries. Use force_reindex=True to reindex.")
            return
        
        if force_reindex and existing_count > 0:
            print(f"🔄 Clearing existing {existing_count} entries...")
            # Delete and recreate collection
            self.chroma_client.delete_collection(name="ui_semantic_map")
            self.collection = self.chroma_client.create_collection(name="ui_semantic_map")
        
        print(f"📝 Indexing semantic graph into ChromaDB...")
        
        documents = []
        metadatas = []
        ids = []
        
        for node in self.graph.get("nodes", []):
            # Build rich description for each node
            desc_parts = []
            
            # Add display header
            if node.get("display_header"):
                desc_parts.append(f"Page: {node['display_header']}")
            
            # Add semantic name
            if node.get("semantic_name"):
                desc_parts.append(f"Semantic name: {node['semantic_name']}")
            
            # Add description
            if node.get("description"):
                desc_parts.append(node["description"])
            
            # Add headers (important for semantic search)
            headers = node.get("headers", [])
            if headers:
                # Include all headers as they provide rich semantic context
                headers_text = ", ".join(headers[:10])  # Limit to first 10 headers
                desc_parts.append(f"Page headers: {headers_text}")
            
            # Add primary entity
            if node.get("primary_entity"):
                desc_parts.append(f"Primary entity: {node['primary_entity']}")
            
            # Add component types
            components = node.get("components", [])
            if components:
                comp_types = {}
                for comp in components:
                    comp_type = comp.get("type", "unknown")
                    comp_types[comp_type] = comp_types.get(comp_type, 0) + 1
                comp_summary = ", ".join([f"{count} {ctype}(s)" for ctype, count in comp_types.items()])
                desc_parts.append(f"Components: {comp_summary}")
            
            # Add component roles
            roles = [comp.get("role") for comp in components if comp.get("role")]
            if roles:
                desc_parts.append(f"Component roles: {', '.join(roles[:5])}")
            
            # Add active APIs
            apis = node.get("active_apis", [])
            if apis:
                desc_parts.append(f"APIs: {', '.join(apis[:5])}")
            
            # Combine into full document
            document = " | ".join(desc_parts)
            
            # Build metadata (ChromaDB doesn't accept None values)
            metadata = {}
            
            # Only add non-None values
            node_id = node.get("id") or node.get("semantic_name")
            if node_id:
                metadata["node_id"] = str(node_id)
            
            # Add headers to metadata (for filtering/search)
            headers = node.get("headers", [])
            if headers:
                # Store first 5 headers as comma-separated string for metadata filtering
                metadata["headers"] = ", ".join(headers[:5])
            
            url = node.get("url")
            if url:
                metadata["url"] = str(url)
            
            semantic_name = node.get("semantic_name")
            if semantic_name:
                metadata["semantic_name"] = str(semantic_name)
            
            display_header = node.get("display_header")
            if display_header:
                metadata["display_header"] = str(display_header)
            
            primary_entity = node.get("primary_entity")
            if primary_entity:
                metadata["primary_entity"] = str(primary_entity)
            
            # Always include counts (they're integers, never None)
            metadata["component_count"] = len(components)
            metadata["api_count"] = len(apis)
            
            persona = node.get("context", {}).get("persona")
            if persona:
                metadata["persona"] = str(persona)
            
            # Generate unique ID: use URL hash or index to ensure uniqueness
            node_id = node.get("id") or node.get("semantic_name", f"node_{len(ids)}")
            node_url = node.get("url", "")
            
            # Create unique ID by combining semantic name with URL hash
            # This ensures uniqueness even if semantic names are duplicated
            import hashlib
            url_hash = hashlib.md5(node_url.encode()).hexdigest()[:8] if node_url else str(len(ids))
            doc_id = f"node_{node_id}_{url_hash}"
            
            # Ensure no duplicates (shouldn't happen with hash, but double-check)
            if doc_id in ids:
                doc_id = f"{doc_id}_{len(ids)}"
            
            documents.append(document)
            metadatas.append(metadata)
            ids.append(doc_id)
        
        # Add to ChromaDB in batches
        batch_size = 100
        total = len(ids)
        print(f"   Indexing {total} nodes...")
        
        for i in range(0, total, batch_size):
            batch_ids = ids[i:i+batch_size]
            batch_docs = documents[i:i+batch_size]
            batch_metas = metadatas[i:i+batch_size]
            
            self.collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_metas
            )
            print(f"   ✅ Indexed {min(i+batch_size, total)}/{total} nodes")
        
        print(f"✅ Successfully indexed {total} nodes into ChromaDB")
    
    def semantic_search(self, query: str, n_results: int = 5, persona: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search for nodes using semantic vector search (ChromaDB).
        
        Args:
            query: Natural language query like "dashboard with opportunities"
            n_results: Number of results to return
            persona: Optional persona name to filter results by (defaults to self.persona if set)
        
        Returns:
            List of matching entries with metadata
        """
        if not self.collection:
            raise RuntimeError(
                "ChromaDB not available or not indexed. "
                "Run: queries.index_graph_to_chromadb() to index the graph first."
            )
        
        # Use instance persona if not provided
        filter_persona = persona or self.persona
        
        try:
            # Check if collection has any data
            try:
                count = self.collection.count()
                if count == 0:
                    raise RuntimeError(
                        "ChromaDB collection is empty. "
                        "Run: queries.index_graph_to_chromadb() to index the graph first."
                    )
            except Exception:
                pass  # count() might fail, continue anyway
            
            # Build where clause for persona filtering
            where_clause = None
            if filter_persona:
                where_clause = {"persona": {"$eq": filter_persona}}
            
            # Get more results if filtering, then filter down
            query_n_results = n_results * 3 if filter_persona else n_results
            
            results = self.collection.query(
                query_texts=[query],
                n_results=query_n_results,
                where=where_clause,
                include=["documents", "metadatas", "distances"]
            )
            
            if not results["ids"][0]:
                return []
            
            formatted = []
            for i, doc_id in enumerate(results["ids"][0]):
                formatted.append({
                    "id": doc_id,
                    "similarity": 1 - results["distances"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "description": results["documents"][0][i]
                })
            
            # Filter by persona if specified (in case where clause didn't work or persona not in metadata)
            if filter_persona:
                formatted = [r for r in formatted 
                           if r["metadata"].get("persona", "").lower() == filter_persona.lower()]
            
            # Return top n_results
            return formatted[:n_results]
        except Exception as e:
            raise RuntimeError(f"ChromaDB search failed: {e}")
    
    def _text_search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Text-based search fallback when ChromaDB is not available.
        
        Searches through node descriptions, semantic names, component roles, and URLs.
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        results = []
        
        for node in self.graph.get("nodes", []):
            score = 0.0
            matched_fields = []
            
            # Search in semantic name
            semantic_name = (node.get("semantic_name") or "").lower()
            if query_lower in semantic_name:
                score += 2.0
                matched_fields.append("semantic_name")
            
            # Search in display header
            display_header = (node.get("display_header") or "").lower()
            if query_lower in display_header:
                score += 2.0
                matched_fields.append("display_header")
            
            # Search in description
            description = (node.get("description") or "").lower()
            if query_lower in description:
                score += 1.5
                matched_fields.append("description")
            elif any(word in description for word in query_words if len(word) > 3):
                score += 0.5
                matched_fields.append("description (partial)")
            
            # Search in URL
            url = (node.get("url") or "").lower()
            if query_lower in url:
                score += 1.0
                matched_fields.append("url")
            
            # Search in component roles
            for component in node.get("components", []):
                role = (component.get("role") or "").lower()
                if query_lower in role:
                    score += 1.0
                    matched_fields.append(f"component: {component.get('role')}")
            
            # Search in active APIs
            for api in node.get("active_apis", []):
                if query_lower in api.lower():
                    score += 0.5
                    matched_fields.append(f"api: {api}")
            
            if score > 0:
                # Build description from node data
                desc_parts = []
                if node.get("display_header"):
                    desc_parts.append(node["display_header"])
                if node.get("description"):
                    desc_parts.append(node["description"][:200])
                description_text = " | ".join(desc_parts) or node.get("semantic_name", "No description")
                
                results.append({
                    "id": node.get("id") or node.get("semantic_name"),
                    "similarity": min(score / 5.0, 1.0),  # Normalize to 0-1
                    "metadata": {
                        "url": node.get("url"),
                        "node_id": node.get("id"),
                        "semantic_name": node.get("semantic_name"),
                        "matched_fields": matched_fields
                    },
                    "description": description_text
                })
        
        # Sort by score (highest first) and return top n_results
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:n_results]
    
    # --- Statistics ---
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics about the discovered application."""
        stats = {
            "nodes": len(self.graph.get("nodes", [])),
            "edges": len(self.graph.get("edges", [])),
            "components": 0,
            "components_by_type": {},
            "apis": len(self.get_all_apis()),
            "tables": len(self.get_all_tables())
        }
        
        for node in self.graph["nodes"]:
            components = node.get("components", [])
            stats["components"] += len(components)
            
            for component in components:
                comp_type = component.get("type", "unknown")
                stats["components_by_type"][comp_type] = \
                    stats["components_by_type"].get(comp_type, 0) + 1
        
        return stats
    
    # --- Display Helpers ---
    
    def print_summary(self):
        """Print a human-readable summary of the graph."""
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        
        console = Console()
        
        console.print("\n[bold cyan]📊 Semantic Graph Summary[/bold cyan]\n")
        
        # Stats
        stats = self.get_stats()
        console.print(f"[green]✅ Nodes (pages):[/green] {stats['nodes']}")
        console.print(f"[green]✅ Components:[/green] {stats['components']}")
        console.print(f"[green]✅ API endpoints:[/green] {stats['apis']}")
        console.print(f"[green]✅ Database tables:[/green] {stats['tables']}")
        console.print()
        
        # Components by type
        if stats["components_by_type"]:
            console.print("[bold]Components by Type:[/bold]")
            for comp_type, count in stats["components_by_type"].items():
                console.print(f"  • {comp_type}: {count}")
            console.print()
        
        # All nodes
        console.print("[bold cyan]📄 Discovered Pages:[/bold cyan]\n")
        for node in self.graph["nodes"]:
            console.print(Panel(
                f"[bold]URL:[/bold] {node['url']}\n"
                f"[bold]Components:[/bold] {len(node.get('components', []))}\n"
                f"[bold]APIs:[/bold] {', '.join(node.get('active_apis', []))}",
                title=node.get("semantic_name", node.get("id", "unknown")),
                border_style="cyan"
            ))
        
        # All components
        console.print("\n[bold cyan]🔧 Discovered Components:[/bold cyan]\n")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Role", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("APIs", style="green")
        table.add_column("DB Table", style="blue")
        
        for node in self.graph["nodes"]:
            for comp in node.get("components", []):
                table.add_row(
                    comp.get("role", "unknown"),
                    comp.get("type", "unknown"),
                    ", ".join(comp.get("triggers_api", [])),
                    comp.get("impacts_db", "N/A")
                )
        
        console.print(table)
        console.print()


# --- CLI Interface ---

if __name__ == "__main__":
    import sys
    from rich.console import Console
    
    console = Console()
    
    # Parse persona argument if provided
    persona = None
    args = sys.argv[1:]  # Copy args to avoid modifying sys.argv during iteration
    
    # Handle --persona flag
    if "--persona" in args:
        persona_idx = args.index("--persona")
        if persona_idx + 1 < len(args):
            persona = args[persona_idx + 1]
            # Remove --persona and its value from args
            args = args[:persona_idx] + args[persona_idx + 2:]
    
    # Handle --search as alias for search command
    if "--search" in args:
        search_idx = args.index("--search")
        # Replace --search with search
        args[search_idx] = "search"
    
    try:
        queries = GraphQueries(persona=persona)
        
        # Show persona info if loaded
        if persona:
            console.print(f"[green]✅ Loaded graph for persona: {persona}[/green]\n")
        else:
            personas = queries.get_personas_in_graph()
            if personas:
                console.print(f"[cyan]ℹ️  Available personas in graph: {', '.join(personas)}[/cyan]")
                console.print(f"[dim]   Use --persona <name> to filter queries[/dim]\n")
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/red]")
        console.print("[yellow]Run semantic_mapper.py first to generate the graph[/yellow]")
        sys.exit(1)
    
    if len(args) > 0:
        command = args[0]
        
        if command == "summary":
            queries.print_summary()
        
        elif command == "apis":
            console.print("\n[bold cyan]📡 All API Endpoints:[/bold cyan]\n")
            for api in queries.get_all_apis():
                console.print(f"  • {api}")
            console.print()
        
        elif command == "tables":
            console.print("\n[bold cyan]💾 All Database Tables:[/bold cyan]\n")
            for table in queries.get_all_tables():
                console.print(f"  • {table}")
            
            console.print("\n[bold]Dependencies:[/bold]\n")
            for table, deps in queries.get_table_dependencies().items():
                console.print(f"[cyan]{table}[/cyan]:")
                console.print(f"  Components: {', '.join(deps['components'])}")
                console.print(f"  APIs: {', '.join(deps['apis'])}")
                console.print()
        
        elif command == "index":
            console.print("\n[bold cyan]📝 Indexing semantic graph to ChromaDB...[/bold cyan]\n")
            try:
                queries.index_graph_to_chromadb(force_reindex=True)
                console.print("[green]✅ Indexing complete![/green]\n")
            except Exception as e:
                console.print(f"[red]❌ Indexing failed: {e}[/red]\n")
        
        elif command == "search" and len(args) > 1:
            query = " ".join(args[1:])
            try:
                # Pass persona to search if it was set
                results = queries.semantic_search(query, persona=persona)
                
                console.print(f"\n[bold cyan]🔎 Semantic Search: '{query}'[/bold cyan]\n")
                if not results:
                    console.print("[yellow]No results found[/yellow]")
                    console.print("[dim]Try running: python graph_queries.py index[/dim]\n")
                else:
                    for i, result in enumerate(results, 1):
                        similarity = result['similarity']
                        color = "green" if similarity > 0.7 else "yellow" if similarity > 0.4 else "white"
                        console.print(f"[{color}]Result {i} - Similarity: {similarity:.2%}[/{color}]")
                        console.print(f"  URL: {result['metadata'].get('url', 'N/A')}")
                        console.print(f"  Node: {result['metadata'].get('semantic_name', result['metadata'].get('node_id', 'N/A'))}")
                        console.print(f"  Display: {result['metadata'].get('display_header', 'N/A')}")
                        if result['metadata'].get('primary_entity'):
                            console.print(f"  Entity: {result['metadata']['primary_entity']}")
                        console.print(f"  Description: {result['description'][:200]}...")
                        console.print()
            except RuntimeError as e:
                console.print(f"[red]❌ {e}[/red]")
                console.print("[dim]Run: python graph_queries.py index[/dim]\n")
            except Exception as e:
                console.print(f"[red]❌ Search failed: {e}[/red]\n")
        
        elif command == "personas":
            personas = queries.get_personas_in_graph()
            console.print("\n[bold cyan]👥 Personas in Graph:[/bold cyan]\n")
            if personas:
                for p in personas:
                    node_count = len(queries.filter_by_persona(p))
                    console.print(f"  • {p}: {node_count} nodes")
            else:
                console.print("[yellow]No personas found in graph[/yellow]")
            console.print()
        
        else:
            # Check if user might have used --search instead of search
            if args and args[0] == "--search":
                console.print("[yellow]⚠️  Use 'search' (not '--search') as the command[/yellow]")
                console.print("[dim]   Example: python graph_queries.py --persona Reseller search 'query'[/dim]\n")
            else:
                console.print(f"[red]Unknown command: {args[0] if args else 'none'}[/red]")
            
            console.print("\nUsage:")
            console.print("  python graph_queries.py [--persona <name>] <command> [arguments]")
            console.print("\nCommands:")
            console.print("  summary                    # Print graph summary")
            console.print("  personas                   # List all personas in graph")
            console.print("  apis                       # List all API endpoints")
            console.print("  tables                     # List all database tables")
            console.print("  index                      # Index graph to ChromaDB for semantic search")
            console.print("  search <query>             # Semantic search (requires indexing first)")
            console.print("\nExamples:")
            console.print("  python graph_queries.py --persona Reseller summary")
            console.print("  python graph_queries.py --persona Distributor search 'dashboard'")
            console.print("  python graph_queries.py search 'Demand Activation'")
    
    else:
        queries.print_summary()
