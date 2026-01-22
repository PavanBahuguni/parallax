Run these commands in your project root to set up the environment and dependencies instantly.Bash# Initialize a new uv project
uv init --app
uv venv

# Install all necessary libraries in one go
uv add browser-use playwright networkx chromadb langchain-ollama pydantic-settings

# Install browser binaries
uv run playwright install chromium
📝 2. The Mapper Implementation (discovery_mapper.py)This script uses Playwright's request interception to map network calls and NetworkX to build the sitemap.Pythonimport asyncio
import json
import networkx as nx
from networkx.readwrite import json_graph
import chromadb
from browser_use import Agent, Browser, BrowserConfig
from langchain_ollama import ChatOllama
from pydantic import BaseModel

# --- Configuration ---
CONFIG = {
    "BASE_URL": "http://localhost:5173",
    "API_FILTER": "localhost:8000",
    "DB_PATH": "./agent_memory",
    "GRAPH_FILE": "sitemap_graph.json"
}

# --- State Management ---
site_graph = nx.DiGraph()
chroma_client = chromadb.PersistentClient(path=CONFIG["DB_PATH"])
collection = chroma_client.get_or_create_collection(name="ui_semantic_map")
network_log = []

async def request_sniffer(request):
    """Listens for backend API calls specifically."""
    if CONFIG["API_FILTER"] in request.url:
        network_log.append({
            "method": request.method,
            "url": request.url,
            "type": request.resource_type
        })
        print(f"📡 API Sniffed: {request.method} {request.url}")

async def run_mapper():
    # Use Local LLM (Ollama)
    llm = ChatOllama(model="llama3", num_ctx=32000)
    
    # Setup Browser with interception
    browser = Browser(config=BrowserConfig(headless=False))
    
    async with await browser.new_context() as context:
        page = await context.get_current_page()
        page.on("request", request_sniffer)

        # Exploration Mission
        agent = Agent(
            task=f"Starting at {CONFIG['BASE_URL']}, explore all clickable links and buttons. "
                 f"Identify what each page does and record all network activity.",
            llm=llm,
            browser=browser
        )
        
        history = await agent.run()

        # Build Graph from Agent Trace
        for i, step in enumerate(history.history):
            url = step.state.url if hasattr(step, 'state') else CONFIG["BASE_URL"]
            thought = step.model_output.thought if hasattr(step, 'model_output') else "Discovery step"
            
            # 1. Add to Navigation Graph
            site_graph.add_node(
                url, 
                label=thought[:50], 
                apis=list(network_log)
            )
            
            # 2. Store in Vector Memory (ChromaDB)
            collection.add(
                documents=[thought],
                metadatas=[{"url": url, "step": i}],
                ids=[f"node_{i}_{url}"]
            )

        # Save Final Mapping
        with open(CONFIG["GRAPH_FILE"], "w") as f:
            json.dump(json_graph.node_link_data(site_graph), f, indent=2)
            
    print(f"✅ Mapping Complete. Saved to {CONFIG['GRAPH_FILE']}")

if __name__ == "__main__":
    asyncio.run(run_mapper())
🧭 3. Where and How the Data is StoredData TypeStorage FormatPurposeSite Topologysitemap_graph.jsonA NetworkX JSON file. Stores the "how to get there" (nodes/edges).Semantic Contextagent_memory/ (ChromaDB)A Vector Database. Stores "what is here" (descriptions of UI components).API LinkagesNode AttributesInside the JSON, each URL node contains a list of apis it triggered.🚀 4. How to ExecuteTo run the mapper using uv, simply use:Bashuv run discovery_mapper.py
🧠 Cursor/Grok StrategyReference the Graph: Tell Cursor, "The sitemap_graph.json is the source of truth for navigation. Use Dijkstra's algorithm from networkx to find paths."Dynamic Routing: Since the URL is configurable in the CONFIG dict, you can change it to any staging URL without rewriting the code.Network Mapping: Explain to the LLM that the apis attribute in the JSON is how the agent knows which backend service to verify during the "Triple-Check" phase.