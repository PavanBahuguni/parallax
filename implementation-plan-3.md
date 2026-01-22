🏗️ Phase 1: The Context Processor (context_processor.py)The Context Processor is the "Intel Intelligence" unit of your system. Its job is to take raw, messy inputs (a Markdown file and a PR link) and transform them into a Structured Test Mission that the agent can execute without guessing.1. Core ObjectiveTo bridge the gap between Human Intent (Markdown) and Code Reality (PR) by anchoring both to your Semantic Graph. It answers: "What is being changed, where does it live in the UI, and which DB tables should I witness changing?"2. Key FunctionalitiesFunctionDescriptionIntent ExtractionParses the Markdown to find "What" needs to be tested (e.g., "Add a new item").PR Diff AnalysisScans the PR (simulated or real) to identify modified Models, API routes, or UI components.Entity MappingMaps code entities (like Item class) to the db_tables in your sitemap_graph.json.Navigation PlanningUses the GraphNavigator to find the shortest path to the target feature.Mission SynthesisPackages all the above into a single JSON "Briefing" for the Executor.3. Step-by-Step FlowIngestion: The script reads task.md and fetches the PR diff from the provided link.Semantic Analysis (LLM):Task Side: "User wants to verify the new 'Price' field."PR Side: "Developer added price: float to Item model and POST /items now accepts price."Graph Discovery:The script queries the GraphNavigator: "Find the node where POST /items is triggered."Result: It returns the items_dashboard node ID.Requirement Synthesis:It identifies the new field is price.It identifies the table is items.It determines that a "Success" is defined by:UI success message.API returning 201 with the new price.Database record containing the exact price.4. The "Briefing" Output (The JSON Mission)The final result of context_processor.py is a Mission JSON. This is what the executor.py (Phase 2) will consume.JSON{
  "ticket_id": "TICKET-101",
  "target_node": "items_dashboard",
  "navigation_steps": ["http://localhost:5173"],
  "actions": [
    {
      "component_role": "create_item_form",
      "test_data": {
        "Item name": "AI Test Kit",
        "Item description": "Testing the price field",
        "Item price": "49.99"
      }
    }
  ],
  "verification_points": {
    "api_endpoint": "POST /items",
    "db_table": "items",
    "expected_values": {"name": "AI Test Kit", "price": 49.99}
  }
}
5. Logic for Cursor (The Prompt)To build this, use the following prompt in Cursor. It is optimized for Grok-code-fast-1 by emphasizing structured parsing over complex abstraction."Create context_processor.py.Markdown Parser: Use mistune or simple regex to extract the 'Description' and 'PR Link' from task.md.Intent Engine: Use a small LLM call to identify the 'Primary Entity' (e.g., Item) and 'Specific Changes' (e.g., added Price) from the text.Graph Matcher: Import GraphNavigator. Find the node in sitemap_graph.json that matches the 'Primary Entity'.Diff Analyzer: (Mocked for now) Create a function that 'simulates' reading a PR and returns a list of changed DB columns.Output Generator: Combine everything into a mission.json file. This file must contain the target_node, test_data, and db_table needed for verification."🚀 What's Next?Once you have the mission.json, you are ready for Phase 2: The Triple-Check Executor. This script will take the mission, open the browser, and start the "Comparison Check" we discussed.Would you like me to show you how to structure the "PR Mock" function so you can test this without a live GitHub connection?