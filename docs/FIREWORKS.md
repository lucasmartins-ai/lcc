# Fireworks AI

The real Fireworks call is isolated in `act2_router/fireworks_client.py`. It uses the
OpenAI-compatible chat completions shape and stdlib HTTP.

Environment:

```bash
FIREWORKS_API_KEY=fw-...
FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
FIREWORKS_MODEL_ID=accounts/fireworks/models/deepseek-v3p1
```

Behavior:

- missing `FIREWORKS_API_KEY` uses `MockRemoteSolver`;
- API keys are never hardcoded;
- prompt/completion/total tokens are read from provider `usage` when present;
- missing usage is estimated conservatively and labelled;
- transient HTTP failures retry briefly;
- persistent failures return a controlled `[remote_error]` answer.

The remote prompt is intentionally compact: instruction, expected format, necessary context,
and no debug trace.
