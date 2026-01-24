# Agentic PR Context Gathering - Implementation Summary

## Overview

This implementation adds **agentic reasoning** to the PR context gathering process, enabling the system to:
1. **Intelligently fetch additional context** beyond PR diffs (PR descriptions, full files, etc.)
2. **Decide what needs testing** (DB, API, UI, or combinations) based on PR changes
3. **Skip unnecessary verification** when changes don't affect certain layers

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│         Agentic PR Context Gathering (LangGraph)           │
└─────────────────────────────────────────────────────────────┘

1. Analyze PR Diff
   ↓
2. Identify Context Gaps (LLM decides what's missing)
   ↓
3. Route to MCP Tools (conditional)
   ├─→ Fetch PR Description
   ├─→ Fetch Full Files
   └─→ Skip if no gaps
   ↓
4. Merge Context
   ↓
5. Decide Test Scope (LLM decides what to test)
   ├─→ test_db: true/false
   ├─→ test_api: true/false
   └─→ test_ui: true/false
   ↓
6. Return Enriched Context + Test Scope
```

## Files Created/Modified

### New Files

1. **`mapper/github_mcp_client.py`**
   - MCP-style client for GitHub API operations
   - Tools: `fetch_pr_description()`, `fetch_file_contents()`, `fetch_commit_messages()`
   - Supports GitHub.com and GitHub Enterprise

2. **`mapper/agentic_pr_context.py`**
   - LangGraph workflow for agentic context gathering
   - Implements the workflow described above
   - Uses LLM to make decisions about context gaps and test scope

### Modified Files

1. **`mapper/pyproject.toml`**
   - Added `langgraph>=0.2.0` dependency

2. **`mapper/context_processor.py`**
   - Added `use_agentic_context` parameter (default: True)
   - Modified `_extract_pr_summary()` to use agentic workflow when enabled
   - Updated `synthesize_mission()` to accept and include `test_scope`
   - Mission JSON now includes `test_scope` field

3. **`mapper/executor.py`**
   - Updated to respect `test_scope` from mission.json
   - Skips DB/API/UI verification if not in test scope
   - Shows "(Skipped - not in test scope)" messages

## How It Works

### 1. Context Gathering

When processing a PR, the system:

1. **Fetches PR diff** (as before)
2. **Analyzes diff** to extract semantic changes (DB, API, UI)
3. **LLM identifies gaps**: "Do I need more context?"
   - Example: "I see a model change but only see the diff - need full models.py"
4. **Routes to MCP tools** based on gaps:
   - Fetches PR description if needed
   - Fetches full file contents if needed
5. **Merges all context** for final analysis

### 2. Test Scope Decision

After gathering context, the system:

1. **LLM analyzes PR changes** and decides what needs testing
2. **Returns test scope**:
   ```json
   {
     "test_db": true/false,
     "test_api": true/false,
     "test_ui": true/false,
     "reasoning": "why these layers need testing"
   }
   ```

3. **Examples**:
   - CSS-only change → `{"test_db": false, "test_api": false, "test_ui": true}`
   - New DB column → `{"test_db": true, "test_api": true, "test_ui": true}`
   - API endpoint change → `{"test_db": false, "test_api": true, "test_ui": true}`

### 3. Mission Execution

The executor respects `test_scope`:

- If `test_db: false` → Skips database verification
- If `test_api: false` → Skips API verification
- If `test_ui: false` → Skips UI verification (though UI execution still happens)

## Usage

### Enable/Disable Agentic Context

```python
# Enable (default)
processor = ContextProcessor(graph_queries, llm, use_agentic_context=True)

# Disable (fallback to standard extraction)
processor = ContextProcessor(graph_queries, llm, use_agentic_context=False)
```

### Mission JSON Structure

```json
{
  "ticket_id": "TICKET-101",
  "target_node": "items_manager",
  "test_cases": [...],
  "verification_points": {...},
  "test_scope": {
    "test_db": true,
    "test_api": true,
    "test_ui": true,
    "reasoning": "New DB column added, requires full stack verification"
  }
}
```

## Benefits

1. **Efficient**: Only fetches context when needed
2. **Intelligent**: Understands what's missing and what needs testing
3. **Flexible**: Adapts to different PR types
4. **Faster**: Skips unnecessary verification layers

## Example Flow

### Scenario: CSS-only change

1. PR diff shows: `styles.css` modified
2. LLM analyzes: "This is a CSS change, no DB/API impact"
3. Test scope: `{"test_db": false, "test_api": false, "test_ui": true}`
4. Executor: Skips DB and API checks, only tests UI

### Scenario: New DB column

1. PR diff shows: `models.py` modified, migration file added
2. LLM identifies gap: "Need full models.py to understand structure"
3. MCP tool fetches: Full `models.py` content
4. LLM analyzes: "New column affects DB, API, and UI"
5. Test scope: `{"test_db": true, "test_api": true, "test_ui": true}`
6. Executor: Tests all three layers

## Configuration

### Environment Variables

- `GITHUB_TOKEN`: GitHub API token (required for fetching PR context)
- `GITHUB_VERIFY_SSL`: Set to "false" for GitHub Enterprise with self-signed certs

### Dependencies

- `langgraph>=0.2.0`: For workflow orchestration
- `pygithub>=2.1.1`: For GitHub API access (or falls back to httpx)

## Backward Compatibility

- **Default behavior**: Agentic context gathering is **enabled by default**
- **Fallback**: If agentic gathering fails, falls back to standard extraction
- **Mission format**: `test_scope` is optional - executor defaults to testing all layers if missing

## Future Enhancements

1. **Related files detection**: Automatically find and fetch related files (imports, dependencies)
2. **Commit message analysis**: Use commit messages for additional context
3. **PR comments analysis**: Extract insights from PR review comments
4. **Caching**: Cache fetched context to avoid redundant API calls
