# Local Model

Local model work is outside the deterministic LCC core. Local tokens are treated as zero-cost
for Track 1 scoring, but local inference still uses local compute.

Environment:

```bash
LOCAL_MODEL_BACKEND=mock|ollama|llamacpp|vllm|transformers
LOCAL_MODEL_NAME=<model name>
LOCAL_MODEL_ENDPOINT=http://127.0.0.1:11434
LOCAL_VERIFIER_BACKEND=rule|local_llm
```

Default behavior:

- `mock` backend is deterministic and used for tests/demo without setup;
- `ollama` uses `/api/generate`;
- `llamacpp`, `vllm`, and `transformers` expect an OpenAI-compatible local
  `/chat/completions` endpoint;
- unsupported or partially configured backends fall back to labelled mock mode.

The verifier defaults to rules. `local_llm` verification is optional and falls back to the
rule verifier if the local model returns malformed JSON.
