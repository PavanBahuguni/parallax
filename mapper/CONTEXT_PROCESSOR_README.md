# Context Processor - Phase 1: Intent Extraction

## Overview

The **Context Processor** is the "Intel Intelligence" unit that bridges Human Intent (Markdown) and Code Reality (PR) by anchoring both to your Semantic Graph. It transforms raw task descriptions into structured **Mission JSON** that Phase 2 executor can execute without guessing.

## What It Does

1. **Parses** `task.md` to extract description and PR link
2. **Extracts Intent** via LLM (entity, changes, test focus)
3. **Finds Target Node** in semantic graph
4. **Analyzes PR Diff** (mocked for now, real implementation in Phase 2)
5. **Generates Mission JSON** with complete test plan

## Usage

### 1. Create Task File

Create `task.md`:

```markdown
# Task: Test New Item Creation Feature

## Description

Verify that the new item creation form works correctly. Users should be able to add items with a name and description.

## PR Link

https://github.com/example/repo/pull/123
```

### 2. Run Context Processor

```bash
cd mapper
uv run python context_processor.py task.md
```

### 3. Output: Mission JSON

Generates `mission.json`:

```json
{
  "ticket_id": "TICKET-101",
  "target_node": "items_manager",
  "target_url": "http://localhost:5173",
  "navigation_steps": ["http://localhost:5173"],
  "actions": [
    {
      "component_role": "create_item_form",
      "component_selector": "form:nth-of-type(1)",
      "test_data": {
        "Item name": "AI Test Item",
        "Item description": "Testing automated QA"
      }
    }
  ],
  "verification_points": {
    "api_endpoint": "POST /items",
    "db_table": "items",
    "expected_values": {
      "item_name": "AI Test Item",
      "item_description": "Testing automated QA"
    }
  },
  "intent": {
    "primary_entity": "Item",
    "changes": ["added new item creation form"],
    "test_focus": "verify form accepts inputs and saves correctly"
  },
  "pr_link": "https://github.com/example/repo/pull/123"
}
```

## Mission JSON Structure

| Field | Description | Example |
|-------|-------------|---------|
| `ticket_id` | Extracted from description | `"TICKET-101"` |
| `target_node` | Node ID from semantic graph | `"items_manager"` |
| `target_url` | Page URL to navigate to | `"http://localhost:5173"` |
| `navigation_steps` | Path to target page | `["http://localhost:5173"]` |
| `actions` | Components to interact with | Form with test data |
| `verification_points` | What to verify | API endpoint, DB table, expected values |
| `intent` | Extracted intent | Entity, changes, test focus |
| `pr_link` | PR URL for reference | GitHub/GitLab link |

## How It Works

### Step 1: Markdown Parsing

```python
task_data = processor.parse_task_markdown("task.md")
# Extracts:
# - description: Full task text
# - pr_link: GitHub/GitLab URL
```

**Supported Formats**:
- `PR Link: https://github.com/...`
- `PR: https://gitlab.com/...`
- Direct GitHub/GitLab URLs in text

### Step 2: Intent Extraction (LLM)

Uses Nutanix LLM to extract:
- **Primary Entity**: `"Item"`, `"User"`, `"Order"`
- **Changes**: `["added Price field"]`, `["modified status"]`
- **Test Focus**: What should be verified

### Step 3: Graph Matching

Finds matching node in `semantic_graph.json`:
1. Search by semantic name (`items_manager`)
2. Search by API endpoint (`POST /items`)
3. Search by component role (`create_item_form`)

### Step 4: PR Diff Analysis (Mocked)

Currently simulates PR analysis. Phase 2 will:
- Fetch PR diff from GitHub/GitLab API
- Parse SQLAlchemy model changes
- Extract exact DB tables and columns
- Find modified API routes
- Identify changed UI files

### Step 5: Mission Synthesis

Combines all information:
- Generates test data based on component fields
- Maps API endpoints from component
- Links to DB table from PR analysis
- Creates verification plan

## Command Line Options

```bash
# Basic usage
uv run python context_processor.py task.md

# Custom output file
uv run python context_processor.py task.md --output custom_mission.json

# Custom graph file
uv run python context_processor.py task.md --graph custom_graph.json
```

## Integration with Phase 2

The `mission.json` is consumed by **Phase 2: Triple-Check Executor**:

```python
# Phase 2 executor reads mission.json
with open("mission.json") as f:
    mission = json.load(f)

# Navigate to target
navigate_to(mission["target_url"])

# Interact with component
component = mission["actions"][0]
fill_form(component["component_selector"], component["test_data"])

# Verify API
verify_api_called(mission["verification_points"]["api_endpoint"])

# Verify DB
verify_db_record(
    mission["verification_points"]["db_table"],
    mission["verification_points"]["expected_values"]
)
```

## Example Task Files

### Simple Task

```markdown
# Add Price Field to Items

Verify that items can now have a price field.

PR Link: https://github.com/example/repo/pull/456
```

### Complex Task

```markdown
# TICKET-789: User Authentication Flow

## Description

Test the new user authentication flow. Users should be able to:
- Register with email and password
- Login with credentials
- See their profile page

## PR Link

https://github.com/example/repo/pull/789

## Expected Behavior

- Registration creates user in database
- Login sets authentication cookie
- Profile page displays user information
```

## Troubleshooting

### "No matching node found"

**Problem**: Entity doesn't match any node in semantic graph.

**Solution**:
1. Run `semantic_mapper.py` first to generate graph
2. Check entity name matches semantic names
3. Verify API endpoints exist in graph

### "LLM extraction failed"

**Problem**: LLM couldn't parse intent.

**Solution**:
1. Check `.env` has valid API credentials
2. Verify task.md has clear description
3. Try simplifying the task description

### "PR link not found"

**Problem**: No PR link detected in task.md.

**Solution**:
- Add `PR Link: https://...` line
- Or include GitHub/GitLab URL in text

## Next Steps

### Phase 2: Real PR Diff Analysis

Replace `mock_pr_diff_analysis()` with:

```python
def analyze_pr_diff(self, pr_link: str) -> Dict[str, Any]:
    """Fetch and parse real PR diff from GitHub/GitLab."""
    # Fetch PR diff via API
    diff = fetch_pr_diff(pr_link)
    
    # Parse SQLAlchemy changes
    db_changes = parse_sqlalchemy_models(diff)
    
    # Parse FastAPI route changes
    api_changes = parse_fastapi_routes(diff)
    
    # Parse React component changes
    ui_changes = parse_react_components(diff)
    
    return {
        "db_table": db_changes["table"],
        "db_columns": db_changes["columns"],
        "api_endpoints": api_changes["routes"],
        "ui_files": ui_changes["components"]
    }
```

### Phase 2: Triple-Check Executor

Create `executor.py` that:
1. Reads `mission.json`
2. Navigates to target page
3. Interacts with components
4. Verifies DB → API → UI
5. Reports results

---

**Status**: ✅ Phase 1 Complete - Ready for Phase 2 Integration
