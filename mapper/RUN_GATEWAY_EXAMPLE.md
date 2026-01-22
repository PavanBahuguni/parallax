# Running Gateway Mapper with Login

## Quick Start

1. **Create `.env` file** (copy from `env.example`):
   ```bash
   cp env.example .env
   ```

2. **Verify credentials in `.env`**:
   ```env
   LOGIN_USERNAME=nx_partner@sizer.com
   LOGIN_PASSWORD=GsoBlr123!
   ```

3. **Run gateway mapper**:
   ```bash
   uv run python semantic_mapper_with_gateway.py \
     --persona reseller \
     --gateway-instructions gateway_reseller.txt \
     --storage-state temp/storage_reseller.json \
     --output semantic_graph_reseller.json \
     --base-url http://localhost:9000 \
     --llm-provider nutanix \
     --headless false \
     --max-depth 3
   ```

## What Happens

1. **Gateway Execution**: 
   - Opens http://localhost:9000
   - Logs in with credentials from `.env`
   - Waits for dashboard to load
   - Saves authenticated session to `temp/storage_reseller.json`

2. **Semantic Mapping**:
   - Uses the authenticated session
   - Discovers all routes starting from the dashboard
   - Generates semantic graph with persona context

## Skip Gateway (Reuse Session)

If you already have a saved session:

```bash
uv run python semantic_mapper_with_gateway.py \
  --persona reseller \
  --storage-state temp/storage_reseller.json \
  --output semantic_graph_reseller.json \
  --base-url http://localhost:9000 \
  --skip-gateway \
  --headless false
```
