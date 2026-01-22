"""View semantic data stored in ChromaDB.

This script helps inspect what was captured during discovery mapping.
"""
import os
import json
import chromadb
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

console = Console()

def view_chromadb():
    """Display all semantic data from ChromaDB."""
    
    db_path = os.path.join(os.path.dirname(__file__), "agent_memory")
    
    if not os.path.exists(db_path):
        console.print("[red]❌ No ChromaDB found at agent_memory/[/red]")
        console.print("[yellow]Run semantic_mapper.py first to generate data[/yellow]")
        return
    
    console.print(f"\n[bold cyan]🔍 ChromaDB Semantic Storage[/bold cyan]")
    console.print(f"[dim]Location: {db_path}[/dim]\n")
    
    # Connect to ChromaDB
    client = chromadb.PersistentClient(path=db_path)
    
    # Get collection
    try:
        collection = client.get_or_create_collection(name="ui_semantic_map")
    except Exception as e:
        console.print(f"[red]❌ Error accessing collection: {e}[/red]")
        return
    
    # Get all items
    try:
        results = collection.get(include=["documents", "metadatas"])
    except Exception as e:
        console.print(f"[red]❌ Error retrieving data: {e}[/red]")
        return
    
    if not results["ids"]:
        console.print("[yellow]⚠️  No semantic data found[/yellow]")
        console.print("[dim]The mapper hasn't stored any data yet[/dim]")
        return
    
    console.print(f"[green]✅ Found {len(results['ids'])} semantic entries[/green]\n")
    
    # Display as table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("URL", style="blue")
    table.add_column("Action", style="yellow")
    table.add_column("Description", style="green")
    
    for i, doc_id in enumerate(results["ids"]):
        metadata = results["metadatas"][i]
        document = results["documents"][i]
        
        # Truncate long descriptions
        desc_preview = document[:60] + "..." if len(document) > 60 else document
        
        table.add_row(
            doc_id,
            metadata.get("url", "N/A"),
            metadata.get("action_type", metadata.get("action", "N/A")),
            desc_preview
        )
    
    console.print(table)
    
    # Show detailed view of first few entries
    console.print("\n[bold cyan]📄 Detailed View (First 3 Entries)[/bold cyan]\n")
    
    for i in range(min(3, len(results["ids"]))):
        doc_id = results["ids"][i]
        metadata = results["metadatas"][i]
        document = results["documents"][i]
        
        panel_content = f"""[bold]URL:[/bold] {metadata.get('url', 'N/A')}
[bold]Step:[/bold] {metadata.get('step', 'N/A')}
[bold]Action:[/bold] {metadata.get('action_type', metadata.get('action', 'N/A'))}
[bold]APIs:[/bold] {metadata.get('apis', '[]')}

[bold]Description:[/bold]
{document}
"""
        
        console.print(Panel(panel_content, title=f"Entry {i+1}: {doc_id}", border_style="cyan"))
        console.print()
    
    # Summary stats
    console.print("[bold cyan]📊 Statistics[/bold cyan]")
    
    # Count unique URLs
    urls = set(m.get("url", "") for m in results["metadatas"])
    console.print(f"  • Unique URLs: {len(urls)}")
    
    # Count by action type
    actions = {}
    for m in results["metadatas"]:
        action = m.get("action_type", m.get("action", "unknown"))
        actions[action] = actions.get(action, 0) + 1
    
    console.print(f"  • Action types:")
    for action, count in sorted(actions.items()):
        console.print(f"    - {action}: {count}")
    
    console.print()


def search_semantic_data(query: str, n_results: int = 5):
    """Search semantic data using ChromaDB's vector search."""
    
    db_path = os.path.join(os.path.dirname(__file__), "agent_memory")
    
    if not os.path.exists(db_path):
        console.print("[red]❌ No ChromaDB found[/red]")
        return
    
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_or_create_collection(name="ui_semantic_map")
    
    console.print(f"\n[bold cyan]🔎 Searching for: '{query}'[/bold cyan]\n")
    
    try:
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        
        if not results["ids"][0]:
            console.print("[yellow]No results found[/yellow]")
            return
        
        for i, doc_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            metadata = results["metadatas"][0][i]
            document = results["documents"][0][i]
            
            similarity = 1 - distance  # Convert distance to similarity
            
            panel_content = f"""[bold]Similarity:[/bold] {similarity:.2%}
[bold]URL:[/bold] {metadata.get('url', 'N/A')}
[bold]Action:[/bold] {metadata.get('action_type', metadata.get('action', 'N/A'))}

[bold]Description:[/bold]
{document}
"""
            
            console.print(Panel(panel_content, title=f"Result {i+1}", border_style="green"))
            console.print()
    
    except Exception as e:
        console.print(f"[red]❌ Search failed: {e}[/red]")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        if len(sys.argv) < 3:
            console.print("[red]Usage: python view_chromadb.py search <query>[/red]")
            sys.exit(1)
        
        query = " ".join(sys.argv[2:])
        search_semantic_data(query)
    else:
        view_chromadb()
