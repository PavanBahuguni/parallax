# Semantic Mapper with Gateway

This tool extends the existing `semantic_mapper.py` to include natural-language driven authentication and persona selection before running semantic discovery.

## Overview

The gateway mapper allows you to:
1. **Optional Natural Language Gateway**: Describe login/persona selection in plain English (or skip entirely)
2. **LLM Compilation**: Convert natural language to executable Playwright steps when gateway is needed
3. **Session Persistence**: Save authenticated browser state for reuse
4. **Persona-Aware Mapping**: Tag semantic graphs with persona context

## Features

- **No modifications to existing code**: Imports and extends existing mapper classes
- **Configurable LLM providers**: Support for both Nutanix API and local Ollama
- **Deterministic execution**: LLM-generated plans are executed reliably with Playwright
- **Session reuse**: Save and restore authenticated browser sessions

## Prerequisites

- Python 3.11+
- Playwright installed: `uv run playwright install chromium`
- Environment variables in `.env`:
  - For Nutanix: `NUTANIX_API_URL`, `NUTANIX_API_KEY`
  - For Ollama: Local Ollama instance running
- Test application running (default: http://localhost:5173)

## Usage

### With Gateway (Authentication/Persona Selection)

```bash
# Using Nutanix LLM
uv run python semantic_mapper_with_gateway.py \
  --persona reseller \
  --gateway-instructions gateway_reseller.txt \
  --storage-state temp/storage_reseller.json \
  --output semantic_graph_reseller.json \
  --headless false \
  --max-depth 3

# Using Ollama
uv run python semantic_mapper_with_gateway.py \
  --persona reseller \
  --gateway-instructions gateway_reseller.txt \
  --storage-state temp/storage_reseller.json \
  --output semantic_graph_reseller.json \
  --llm-provider ollama \
  --ollama-model llama3.2:3b \
  --headless false \
  --max-depth 3
```

### Without Gateway (Direct Access - No Authentication Needed)

```bash
# Skip gateway entirely - go straight to semantic mapping
uv run python semantic_mapper_with_gateway.py \
  --persona internal \
  --storage-state temp/storage_internal.json \
  --output semantic_graph_internal.json \
  --llm-provider nutanix \
  --headless false \
  --max-depth 3
```

### Skip Gateway (Reuse Existing Session)

```bash
uv run python semantic_mapper_with_gateway.py \
  --persona reseller \
  --storage-state temp/storage_reseller.json \
  --output semantic_graph_reseller.json \
  --skip-gateway \
  --headless false \
  --max-depth 3
```

## Command Line Arguments

- `--persona`: Required. Persona to establish (internal|reseller|distributor)
- `--gateway-instructions`: Path to natural language gateway instructions (optional - skip if not needed)
- `--storage-state`: Path to save/load browser storage state JSON
- `--output`: Output semantic graph JSON file (default: semantic_graph.json)
- `--base-url`: Base URL to open (default: http://localhost:5173)
- `--headless`: Run browser in headless mode (default: false)
- `--max-depth`: Maximum navigation depth for discovery (default: 3)
- `--skip-gateway`: Skip gateway execution, reuse existing storage state
- `--llm-provider`: LLM provider (nutanix|ollama, default: nutanix)
- `--ollama-model`: Ollama model name (default: llama3.2:3b)

## Gateway Instruction Files

Create natural language instruction files for each persona:

### gateway_reseller.txt
```
1. Login using env(TEST_USER) and env(TEST_PASS).
2. After login, open the "View as" control.
3. Select "Reseller".
4. Search for partner account "Acme Corp" and select it.
5. Search for user "reseller_user_1" and select it.
6. Ensure the dashboard loads and confirms we are viewing as reseller.
```

### gateway_distributor.txt
```
1. Login using env(TEST_USER) and env(TEST_PASS).
2. After login, open the "View as" control.
3. Select "Distributor".
4. Search for partner account "Global Distributors Inc" and select it.
5. Search for user "distributor_user_1" and select it.
6. Ensure the dashboard loads and confirms we are viewing as distributor.
```

### gateway_internal.txt
```
1. Login using env(TEST_USER) and env(TEST_PASS).
2. After login, ensure we are viewing as internal/admin user.
3. Verify we have access to all internal features and dashboards.
4. Ensure the main admin dashboard loads properly.
```

## Environment Variables

Create a `.env` file with credentials:

```env
# For authentication
TEST_USER=your_test_user
TEST_PASS=your_test_password
MFA_SECRET=your_mfa_secret

# For Nutanix LLM
NUTANIX_API_URL=https://your-nutanix-instance.com/api/v1
NUTANIX_API_KEY=your_api_key
NUTANIX_MODEL=openai/gpt-oss-120b

# For Ollama (if using local)
OLLAMA_BASE_URL=http://localhost:11434
```

## Output

The tool generates:
1. **Storage State**: `temp/storage_*.json` - Browser session state for reuse
2. **Semantic Graph**: `semantic_graph_*.json` - Persona-tagged navigation graph

### Graph Structure
```json
{
  "nodes": [
    {
      "id": "dashboard",
      "url": "http://localhost:5173/",
      "semantic_name": "dashboard",
      "display_header": "Dashboard",
      "primary_entity": "Product",
      "components": [...],
      "active_apis": [...],
      "context": {
        "persona": "reseller"
      }
    }
  ],
  "edges": [...],
  "api_endpoints": {...},
  "entrypoints": {
    "reseller": "dashboard"
  }
}
```

## Architecture

The gateway mapper works in these phases:

1. **UI Snapshot**: Capture current page state (URL, title, interactive elements)
2. **LLM Compilation**: Convert natural language instructions to structured JSON plan
3. **Deterministic Execution**: Execute plan steps with Playwright
4. **Session Persistence**: Save authenticated browser state
5. **Semantic Mapping**: Run existing mapper with persona context
6. **Graph Enhancement**: Tag all nodes with persona information

## LLM Providers

### Nutanix API
- Requires API URL and key
- Supports various models (default: openai/gpt-oss-120b)
- Handles authentication and retries automatically

### Ollama (Local)
- Requires local Ollama instance running
- Faster response times, no API costs
- Supports any Ollama-compatible model
- Good for development and testing

## Validation

After running, verify:

1. Storage state exists: `temp/storage_reseller.json`
2. Graph file exists: `semantic_graph_reseller.json`
3. Graph contains persona context: `"context": {"persona": "reseller"}`
4. Entrypoint defined: `"entrypoints": {"reseller": "node_id"}`

## Troubleshooting

### Common Issues

**LLM doesn't return valid JSON**
- Check LLM provider configuration
- Verify API keys/URLs in `.env`
- Try a different model

**Gateway steps fail**
- Update selectors in gateway instructions
- Check if UI has changed
- Use more specific selectors (#id, [data-testid])

**Session not saved**
- Ensure storage state path is writable
- Check for permission issues

**Mapping incomplete**
- Increase `--max-depth`
- Check if authentication actually succeeded
- Verify app is accessible

## Next Steps

After generating persona-specific graphs, you can:
1. Run mapper for multiple personas
2. Merge graphs for multi-persona testing
3. Use graphs with context processor for test execution
4. Link to PR diffs for database impact analysis