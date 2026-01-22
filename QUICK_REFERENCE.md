# Agentic QA System - Quick Reference

## 🎯 Three-Phase Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ PHASE 0: DISCOVERY → semantic_graph.json                     │
│ PHASE 1: PLANNING → mission.json                             │
│ PHASE 2: EXECUTION → report.json                             │
└─────────────────────────────────────────────────────────────┘
```

## 📚 Key Libraries

| Library | Purpose | Used In |
|---------|---------|---------|
| **playwright** | Browser automation | semantic_mapper, executor |
| **browser-use** | AI-powered browser control | semantic_mapper |
| **networkx** | Graph structure | semantic_mapper, graph_queries |
| **chromadb** | Vector storage | semantic_mapper |
| **asyncpg** | PostgreSQL async driver | executor |
| **httpx** | HTTP client | All (LLM API, GitHub API) |
| **pygithub** | GitHub API wrapper | context_processor |
| **rich** | Terminal formatting | executor, view_chromadb |

## 🤖 LLM Usage (Nutanix GPT-120B)

| Phase | Purpose | Input | Output | Frequency |
|-------|---------|-------|--------|-----------|
| **Semantic Mapper** | Component naming | DOM structure | "create_item_form" | Once per page |
| **Context Processor** | Intent extraction | Task description | Entity, changes, focus | Once per task |
| **Executor Healer** | Selector recovery | DOM + failed selector | New selector | ~10% of runs |

## 🔄 Execution Flow

```
1. DISCOVERY (One-time)
   semantic_mapper.py
   └─> Explores app → semantic_graph.json

2. PLANNING (Per task)
   context_processor.py
   └─> task.md + PR → mission.json

3. EXECUTION (Per mission)
   executor.py
   └─> mission.json → report.json
```

## ✅ Triple-Check Verification

```
Action Execution
    │
    ├─> 1️⃣ Database: Query PostgreSQL
    ├─> 2️⃣ API: Verify endpoint called
    └─> 3️⃣ UI: Confirm item displayed
```

## 💰 Cost Breakdown

- **Discovery**: ~$0.01 (one-time)
- **Planning**: ~$0.01 (per task)
- **Execution (fast path)**: $0.00 (deterministic)
- **Execution (healer)**: ~$0.01 (only if needed)

**Total per mission**: ~$0.02-0.03

## ⚡ Performance

- **Fast Path**: 2-5 seconds (90% of runs)
- **Healer Mode**: 8-15 seconds (10% of runs)
- **Success Rate**: ~98%

## 📁 Key Files

```
mapper/
├── semantic_mapper.py       # Phase 0: Discovery
├── context_processor.py      # Phase 1: Planning
├── executor.py              # Phase 2: Execution
├── graph_queries.py         # Query helper
├── semantic_graph.json      # Generated graph
└── temp/
    ├── TASK-1_mission.json  # Generated mission
    └── TASK-1_report.json   # Execution report
```

## 🚀 Quick Commands

```bash
# Discovery
cd mapper && uv run python semantic_mapper.py

# Planning
cd mapper && uv run python context_processor.py task.md

# Execution
cd mapper && uv run python executor.py temp/TASK-1_mission.json

# Query Graph
cd mapper && uv run python graph_queries.py summary
```

## 🔍 What Each Phase Does

**Phase 0 (Discovery)**:
- Explores web app with Playwright
- Uses LLM to assign semantic names
- Captures API calls
- Links components → APIs → DB tables
- Stores in ChromaDB + JSON

**Phase 1 (Planning)**:
- Parses task.md (human intent)
- Uses LLM to extract structured intent
- Fetches PR diff from GitHub
- Parses PR to extract DB columns, APIs
- Generates mission.json with test plan

**Phase 2 (Execution)**:
- Reads mission.json
- Fast path: Deterministic execution (90%)
- Healer: LLM recovery if needed (10%)
- Triple-check: DB → API → UI verification
- Generates report.json

## 🎨 Hybrid Architecture

```
Fast Path (Deterministic)
    │
    ├─> 90% success rate
    ├─> 2-5 seconds
    └─> $0 cost

    │ ❌ Failure?
    ▼

Healer Mode (Agentic)
    │
    ├─> 80% recovery rate
    ├─> 8-15 seconds
    └─> ~$0.01 cost
```

## 📊 Data Flow

```
Web App → semantic_mapper → semantic_graph.json
                                    ↓
task.md + PR → context_processor → mission.json
                                    ↓
mission.json → executor → report.json
```

## 🔗 External Services

- **Nutanix LLM API**: Semantic naming, intent extraction, selector recovery
- **GitHub API**: PR diff analysis
- **PostgreSQL**: Database verification
- **Web App**: Target application (React + FastAPI)
