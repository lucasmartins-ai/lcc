# Cloud Provider Integration (Fireworks AI)

The cloud completion client is isolated in [`src/lcc/router/cloud_client.py`](file:///Users/Master/lcc-1/src/lcc/router/cloud_client.py). It uses the OpenAI-compatible chat completions standard and stdlib HTTP (`urllib.request`) with zero external dependencies.

## Environment Variables

```bash
FIREWORKS_API_KEY=fw-...
FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
FIREWORKS_MODEL_ID=accounts/fireworks/models/deepseek-v3p1
```

## Behavior & Fallback Guarantees

- **Mock Fallback**: If `FIREWORKS_API_KEY` is not set, `lcc.router` uses `MockRemoteSolver` for 100% offline, deterministic testing.
- **Security**: API keys are read from environment variables and never logged or serialized into reports.
- **Token Accounting**: Prompt, completion, and total tokens are parsed directly from provider `usage` objects when available; otherwise estimated conservatively.
- **Resilience**: Transient network glitches retry with exponential backoff; persistent errors return a controlled `[remote_error]` response without crashing the router pipeline.
- **Token-Efficient Prompting**: The remote prompt is built compactly with only the necessary cleaned context and instructions.
