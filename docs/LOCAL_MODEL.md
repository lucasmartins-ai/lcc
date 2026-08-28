# Local Model & Local Agents

Local model execution is handled by `lcc.agents` outside the deterministic LCC core. Local tokens are 100% free of cloud costs (zero remote tokens used), executing on local hardware via edge-optimized models.

## Environment Variables

```bash
LOCAL_MODEL_BACKEND=mock|ollama|llamacpp|vllm|mlx|transformers
LOCAL_MODEL_NAME=gemma-4-e4b|qwen3.5-4b|<custom model>
LOCAL_MODEL_ENDPOINT=http://127.0.0.1:11434
LOCAL_MODEL_QUANTIZATION=e4b
LOCAL_MODEL_FAMILY=auto|gemma|qwen|generic
LOCAL_VERIFIER_BACKEND=rule|local_llm
```

## Supported Local Models & Features

- **Gemma 4 e4b**: Native Google Gemma turn formatting (`<start_of_turn>user...`), 4-bit edge quantization, fast context comprehension.
- **Qwen3.5-4B**: Native ChatML format (`<|im_start|>system...`), superior structured JSON generation and code reasoning.
- **Health Check**: `lcc agent health`
- **Direct Run**: `lcc agent run --prompt "..." --model gemma-4-e4b`
- **Hybrid Routing**: `lcc route run --task examples/tasks/noisy_context.json`

For complete setup and serving instructions with Ollama and llama.cpp, see [LOCAL_AGENT_GUIDE.md](LOCAL_AGENT_GUIDE.md).
