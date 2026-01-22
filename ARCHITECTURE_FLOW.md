# Agentic QA System - Architecture Flow Diagram

## Complete System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AGENTIC QA SYSTEM FLOW                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 0: SEMANTIC DISCOVERY (semantic_mapper.py)                           │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐
    │  Web App     │  (React + FastAPI + PostgreSQL)
    │  Running     │
    └──────┬───────┘
           │
           │ Playwright Browser Automation
           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  semantic_mapper.py                                          │
    │  ┌──────────────────────────────────────────────────────┐  │
    │  │ Libraries:                                            │  │
    │  │  • playwright (Browser automation)                   │  │
    │  │  • browser-use (AI-powered browser control)          │  │
    │  │  • networkx (Graph structure)                         │  │
    │  │  • chromadb (Semantic vector storage)                │  │
    │  │  • httpx (HTTP client for LLM API)                   │  │
    │  └──────────────────────────────────────────────────────┘  │
    │                                                              │
    │  ┌──────────────────────────────────────────────────────┐ │
    │  │ LLM: FixedNutanixChatModel                            │ │
    │  │  • API: Nutanix Hosted (openai/gpt-oss-120b)         │ │
    │  │  • Purpose: Semantic component naming                 │ │
    │  │  • Input: DOM structure, component descriptions       │ │
    │  │  • Output: Semantic names (e.g., "create_item_form")   │ │
    │  └──────────────────────────────────────────────────────┘ │
    │                                                              │
    │  Flow:                                                       │
    │  1. Navigate to URL                                         │
    │  2. Intercept network calls (API requests)                  │
    │  3. Extract DOM elements                                    │
    │  4. LLM assigns semantic names to components               │
    │  5. Link components → APIs → DB tables                     │
    │  6. Store in ChromaDB (vector embeddings)                │
    │  7. Generate semantic_graph.json                           │
    └──────┬───────────────────────────────────────────────────────┘
           │
           │ Output: semantic_graph.json
           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  semantic_graph.json                                         │
    │  {                                                            │
    │    "nodes": [{                                               │
    │      "id": "items_manager",                                  │
    │      "components": [{                                        │
    │        "role": "create_item_form",                           │
    │        "selector": "form:nth-of-type(1)",                   │
    │        "triggers_api": ["POST /items"],                     │
    │        "impacts_db": "items"                                 │
    │      }]                                                      │
    │    }]                                                        │
    │  }                                                           │
    └─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: CONTEXT PROCESSOR (context_processor.py)                           │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐         ┌──────────────┐
    │  task.md     │         │  PR Link     │
    │  (Human      │         │  (GitHub)    │
    │   Intent)    │         │              │
    └──────┬───────┘         └──────┬───────┘
           │                        │
           │                        │ GitHub API
           │                        │ (PyGithub/httpx)
           │                        ▼
           │              ┌─────────────────────┐
           │              │ PR Diff Analysis   │
           │              │  • Parse migrations│
           │              │  • Extract columns │
           │              │  • Parse models.py │
           │              │  • Parse API routes│
           │              │  • Parse frontend  │
           │              └─────────────────────┘
           │                        │
           │                        │
           ▼                        ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  context_processor.py                                        │
    │  ┌──────────────────────────────────────────────────────┐  │
    │  │ Libraries:                                            │  │
    │  │  • graph_queries (Query semantic_graph.json)         │  │
    │  │  • httpx (GitHub API, LLM API)                       │  │
    │  │  • pygithub (GitHub API wrapper)                     │  │
    │  │  • re (Regex parsing)                                │  │
    │  │  • json (JSON processing)                             │  │
    │  └──────────────────────────────────────────────────────┘  │
    │                                                              │
    │  ┌──────────────────────────────────────────────────────┐ │
    │  │ LLM: FixedNutanixChatModel                            │ │
    │  │  • API: Nutanix Hosted (openai/gpt-oss-120b)         │ │
    │  │  • Purpose: Intent extraction                         │ │
    │  │  • Input: Task description (Markdown)                 │ │
    │  │  • Output: Structured intent (entity, changes, focus)│ │
    │  └──────────────────────────────────────────────────────┘ │
    │                                                              │
    │  Flow:                                                       │
    │  1. Parse task.md → description + PR link                  │
    │  2. LLM extracts intent (entity, changes, test focus)       │
    │  3. Find target node in semantic_graph.json                │
    │  4. Fetch PR diff from GitHub API                          │
    │  5. Parse PR diff → extract DB columns, API endpoints      │
    │  6. Generate test_data based on component fields           │
    │  7. Synthesize mission.json                                │
    └──────┬───────────────────────────────────────────────────────┘
           │
           │ Output: temp/TASK-1_mission.json
           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  mission.json                                                │
    │  {                                                            │
    │    "ticket_id": "TASK-1",                                    │
    │    "target_node": "items_manager",                           │
    │    "actions": [{                                              │
    │      "component_role": "create_item_form",                   │
    │      "test_data": {                                          │
    │        "Item name": "AI Test Item",                          │
    │        "Item tag": "test-tag"                                │
    │      }                                                        │
    │    }],                                                        │
    │    "verification_points": {                                  │
    │      "api_endpoint": "POST /items",                          │
    │      "db_table": "items",                                    │
    │      "expected_values": {                                     │
    │        "tag": "test-tag"                                     │
    │      }                                                        │
    │    }                                                          │
    │  }                                                           │
    └─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: TRIPLE-CHECK EXECUTOR (executor.py)                                 │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────┐
    │  mission.json       │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  executor.py                                                  │
    │  ┌──────────────────────────────────────────────────────┐  │
    │  │ Libraries:                                            │  │
    │  │  • playwright (Browser automation)                   │  │
    │  │  • asyncpg (PostgreSQL async driver)                  │  │
    │  │  • httpx (HTTP client)                                │  │
    │  │  • rich (Terminal output formatting)                   │  │
    │  │  • asyncio (Async execution)                          │  │
    │  └──────────────────────────────────────────────────────┘  │
    │                                                              │
    │  ┌──────────────────────────────────────────────────────┐ │
    │  │ LLM: FixedNutanixChatModel (Optional - Healer Mode)  │ │
    │  │  • API: Nutanix Hosted (openai/gpt-oss-120b)         │ │
    │  │  • Purpose: Selector recovery when UI changes        │ │
    │  │  • Input: DOM snapshot + failed selector              │ │
    │  │  • Output: New selector + reasoning                   │ │
    │  └──────────────────────────────────────────────────────┘ │
    │                                                              │
    │  ┌──────────────────────────────────────────────────────┐ │
    │  │ HYBRID ARCHITECTURE                                    │ │
    │  │                                                          │ │
    │  │  ┌──────────────────────────────────────────────┐    │ │
    │  │  │ FAST PATH (Deterministic)                    │    │ │
    │  │  │  • Use mission.json selectors directly        │    │ │
    │  │  │  • Playwright locator.fill() / click()       │    │ │
    │  │  │  • 3-second timeout                           │    │ │
    │  │  │  • 90% success rate                           │    │ │
    │  │  └──────────────────┬───────────────────────────┘    │ │
    │  │                     │                                 │ │
    │  │                     │ ❌ Failure?                    │ │
    │  │                     ▼                                 │ │
    │  │  ┌──────────────────────────────────────────────┐    │ │
    │  │  │ HEALER MODE (Agentic)                        │    │ │
    │  │  │  • LLM analyzes DOM snapshot                 │    │ │
    │  │  │  • Finds broken selector                     │    │ │
    │  │  │  • Returns new selector + reasoning           │    │ │
    │  │  │  • Updates mission.json for next run          │    │ │
    │  │  │  • 80% recovery rate                         │    │ │
    │  │  └──────────────────────────────────────────────┘    │ │
    │  └──────────────────────────────────────────────────────┘ │
    │                                                              │
    │  Flow:                                                       │
    │  1. Read mission.json                                       │
    │  2. Connect to PostgreSQL                                    │
    │  3. Navigate to target_url                                   │
    │  4. Setup network interception                               │
    │  5. Execute actions (Fast Path → Healer if needed)          │
    │  6. Triple-Check Verification:                              │
    │     a) Database: Query PostgreSQL for expected values       │
    │     b) API: Verify endpoint was called                      │
    │     c) UI: Confirm item appears in list                    │
    │  7. Generate report.json                                    │
    └──────┬───────────────────────────────────────────────────────┘
           │
           │ Output: temp/TASK-1_mission_report.json
           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  report.json                                                  │
    │  {                                                            │
    │    "execution_path": "deterministic",                        │
    │    "healer_used": false,                                     │
    │    "triple_check": {                                          │
    │      "database": {"success": true},                          │
    │      "api": {"success": true},                               │
    │      "ui": {"success": true}                                 │
    │    },                                                         │
    │    "overall_success": true                                    │
    │  }                                                           │
    └─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ DATA FLOW & STORAGE                                                          │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────┐
    │  ChromaDB       │  Vector embeddings for semantic search
    │  (agent_memory/)│
    └─────────────────┘
           ▲
           │ Store semantic data
           │
    ┌──────┴──────────────────────────────────────────────┐
    │  semantic_mapper.py                                  │
    │  • Stores component descriptions as vectors          │
    │  • Enables semantic search ("forms that create")    │
    └──────────────────────────────────────────────────────┘

    ┌─────────────────┐
    │  PostgreSQL     │  Application database
    │  (items table)  │
    └─────────────────┘
           ▲
           │ Query for verification
           │
    ┌──────┴──────────────────────────────────────────────┐
    │  executor.py                                          │
    │  • Verifies data was saved correctly                  │
    │  • Uses asyncpg for async queries                     │
    └──────────────────────────────────────────────────────┘

    ┌─────────────────┐
    │  semantic_graph.json │  Structural graph data
    └─────────────────┘
           ▲
           │ Read for queries
           │
    ┌──────┴──────────────────────────────────────────────┐
    │  graph_queries.py                                    │
    │  • find_component_by_role()                          │
    │  • find_components_using_api()                      │
    │  • semantic_search()                                │
    └──────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ LLM USAGE SUMMARY                                                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. SEMANTIC MAPPER                                                          │
│    ┌────────────────────────────────────────────────────────────────────┐  │
│    │ Purpose: Assign semantic names to UI components                     │  │
│    │ Input: DOM structure, component descriptions                        │  │
│    │ Output: "create_item_form" (not "form_0")                          │  │
│    │ Frequency: Once per page discovery                                 │  │
│    │ Cost: ~$0.01 per page                                              │  │
│    └────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. CONTEXT PROCESSOR                                                        │
│    ┌────────────────────────────────────────────────────────────────────┐  │
│    │ Purpose: Extract intent from task description                      │  │
│    │ Input: Markdown task description                                  │  │
│    │ Output: Structured intent (entity, changes, test focus)            │  │
│    │ Frequency: Once per task                                           │  │
│    │ Cost: ~$0.01 per task                                              │  │
│    └────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. EXECUTOR HEALER (Optional)                                              │
│    ┌────────────────────────────────────────────────────────────────────┐  │
│    │ Purpose: Recover broken selectors when UI changes                 │  │
│    │ Input: DOM snapshot + failed selector                             │  │
│    │ Output: New selector + reasoning                                  │  │
│    │ Frequency: Only when fast path fails (~10% of runs)               │  │
│    │ Cost: ~$0.01 per recovery attempt                                 │  │
│    └────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ LIBRARY DEPENDENCIES                                                         │
└─────────────────────────────────────────────────────────────────────────────┘

Core Libraries:
├── playwright (>=1.57.0)          Browser automation
├── browser-use (>=0.11.2)          AI-powered browser control
├── networkx (>=3.6.1)              Graph structure management
├── chromadb (>=1.4.0)              Vector database for semantic storage
├── asyncpg (>=0.29.0)              PostgreSQL async driver
├── httpx (>=0.27.0)                HTTP client (LLM API, GitHub API)
├── pygithub (>=2.1.1)              GitHub API wrapper
├── rich (>=14.2.0)                 Terminal output formatting
├── pydantic                        Data validation
└── python-dotenv (>=1.0.0)          Environment variable management

LLM Integration:
└── FixedNutanixChatModel           Custom wrapper for Nutanix API
    ├── API: Nutanix Hosted (openai/gpt-oss-120b)
    ├── Handles non-standard response format
    └── Used in: semantic_mapper, context_processor, executor

┌─────────────────────────────────────────────────────────────────────────────┐
│ EXECUTION FLOW SUMMARY                                                       │
└─────────────────────────────────────────────────────────────────────────────┘

1. DISCOVERY PHASE (One-time setup)
   └─> semantic_mapper.py explores app → generates semantic_graph.json

2. PLANNING PHASE (Per task)
   └─> context_processor.py reads task.md + PR → generates mission.json

3. EXECUTION PHASE (Per mission)
   └─> executor.py reads mission.json → executes → generates report.json

┌─────────────────────────────────────────────────────────────────────────────┐
│ TRIPLE-CHECK VERIFICATION FLOW                                              │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────┐
    │  Execute Action │  Fill form, click submit
    └────────┬────────┘
             │
             ├─────────────────────────────────────┐
             │                                     │
             ▼                                     ▼
    ┌─────────────────┐              ┌─────────────────┐
    │  1️⃣ DATABASE     │              │  2️⃣ API         │
    │  Verification    │              │  Verification   │
    │                  │              │                 │
    │  Query:          │              │  Check:        │
    │  SELECT * FROM   │              │  POST /items   │
    │  items WHERE    │              │  was called?   │
    │  tag = 'test-tag'│              │                 │
    │                  │              │  Status: 200?  │
    │  Result: ✅      │              │  Result: ✅    │
    └─────────────────┘              └─────────────────┘
             │                                     │
             └──────────────┬──────────────────────┘
                            │
                            ▼
                 ┌─────────────────┐
                 │  3️⃣ UI          │
                 │  Verification   │
                 │                 │
                 │  Check:         │
                 │  Item visible? │
                 │  Tag displayed?│
                 │                 │
                 │  Result: ✅     │
                 └─────────────────┘
                            │
                            ▼
                 ┌─────────────────┐
                 │  Overall: ✅    │
                 │  All checks pass│
                 └─────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ COST & PERFORMANCE                                                           │
└─────────────────────────────────────────────────────────────────────────────┘

Typical Execution Costs (per mission):
├── Discovery (one-time):        ~$0.01 (semantic mapping)
├── Planning:                    ~$0.01 (intent extraction)
├── Execution (fast path):      $0.00 (deterministic, no LLM)
└── Execution (healer mode):    ~$0.01 (only if fast path fails)

Total per mission: ~$0.02 (if healer not needed) to ~$0.03 (if healer needed)

Performance:
├── Fast Path:                  2-5 seconds
├── Healer Mode:                8-15 seconds
└── Overall Success Rate:       ~98% (fast path + healer combined)

┌─────────────────────────────────────────────────────────────────────────────┐
│ FILE STRUCTURE                                                               │
└─────────────────────────────────────────────────────────────────────────────┘

mapper/
├── semantic_mapper.py          Phase 0: Discovery
├── context_processor.py         Phase 1: Intent extraction + PR analysis
├── executor.py                  Phase 2: Triple-check execution
├── graph_queries.py             Query helper for semantic_graph.json
├── view_chromadb.py            View ChromaDB contents
├── semantic_graph.json         Generated semantic graph
├── agent_memory/               ChromaDB storage
│   └── chroma.sqlite3
└── temp/                       Generated files
    ├── TASK-1_mission.json     Generated mission
    └── TASK-1_mission_report.json  Execution report
