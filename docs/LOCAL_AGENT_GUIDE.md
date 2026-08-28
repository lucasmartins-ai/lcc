# Local LLM Agent Guide: Gemma 4 e4b & Qwen3.5-4B

This guide provides practical instructions for deploying and running **Gemma 4 e4b** and **Qwen3.5-4B** as zero-remote-token local agents in `lcc`.

---

## 🚀 Overview & Target Models

| Model | Parameter Size | Quantization | Chat Format | Primary Strengths |
| :--- | :---: | :---: | :---: | :--- |
| **Gemma 4 e4b** | ~4B | 4-bit (`e4b` / `Q4_K_M`) | `<start_of_turn>user...` | Ultra-low memory footprint (<3GB RAM), fast summarization, triage. |
| **Qwen3.5-4B** | ~4B | 4-bit (`e4b` / `Q4_K_M`) | ChatML (`<\|im_start\|>...`) | Strict JSON schema generation, table output, complex reasoning. |

---

## 🛠️ Step 1: Install and Launch Local Backend

### Option A: Ollama (Recommended for Simplicity)

1. Install Ollama from [ollama.com](https://ollama.com).
2. Pull the model weights:
   ```bash
   # For Gemma 4 / Gemma 2 4-bit:
   ollama run gemma2:2b # or gemma3:4b / gemma:4b
   
   # For Qwen 3.5 / 2.5 4-bit:
   ollama run qwen2.5:3b # or qwen3.5:4b
   ```
3. Verify Ollama is listening at `http://127.0.0.1:11434`.

---

### Option B: llama.cpp / llama-server (Maximum Performance on Apple Silicon / CUDA)

1. Download or build `llama-server`.
2. Download the 4-bit GGUF model (`e4b` / `Q4_K_M`):
   ```bash
   # Start server with OpenAI-compatible endpoint
   ./llama-server \
     -m models/gemma-4b-e4b.gguf \
     --port 8080 \
     --ctx-size 8192 \
     -ngl 99
   ```

---

## ⚙️ Step 2: Configure LCC Environment

Set environment variables or edit `configs/models.yaml`:

```bash
# For Gemma 4 e4b on Ollama:
export LOCAL_MODEL_BACKEND=ollama
export LOCAL_MODEL_NAME=gemma-4-e4b
export LOCAL_MODEL_ENDPOINT=http://127.0.0.1:11434
export LOCAL_MODEL_QUANTIZATION=e4b
export LOCAL_VERIFIER_BACKEND=rule  # or local_llm

# For Qwen3.5-4B on llama.cpp:
export LOCAL_MODEL_BACKEND=llamacpp
export LOCAL_MODEL_NAME=qwen3.5-4b
export LOCAL_MODEL_ENDPOINT=http://127.0.0.1:8080/v1
export LOCAL_MODEL_QUANTIZATION=e4b
export LOCAL_VERIFIER_BACKEND=local_llm
```

---

## 🔍 Step 3: Health Check and Diagnostic Probing

Check whether the local agent is online and measure latency:

```bash
lcc agent health
```

Example output:
```json
{
  "healthy": true,
  "status": "ready",
  "model_name": "gemma-4-e4b",
  "backend": "ollama",
  "family": "gemma",
  "latency_ms": 14,
  "details": {
    "endpoint": "http://127.0.0.1:11434"
  }
}
```

---

## 💻 Step 4: CLI Direct Execution

Run tasks directly through the local agent:

```bash
# Text generation with Gemma 4 e4b
lcc agent run \
  --prompt "Summarize the key architectural boundaries of LCC" \
  --model gemma-4-e4b

# Strict JSON generation with Qwen3.5-4B
lcc agent run \
  --prompt "Extract status: ready, code: 200" \
  --model qwen3.5-4b \
  --format json
```

---

## 🐍 Programmatic Python API

```python
from lcc.agents import LocalAgent, LocalAgentConfig
from lcc.router import TaskInput

# Initialize Gemma 4 e4b Agent
agent = LocalAgent(LocalAgentConfig(
    backend="ollama",
    model_name="gemma-4-e4b",
    endpoint="http://127.0.0.1:11434",
    quantization="e4b"
))

# Solve task locally (0 remote tokens used)
task = TaskInput(
    task_id="intake-001",
    instruction="Extract missing requirements",
    context="Raw prompt context..."
)
answer = agent.solve(task)
print(answer.answer)
print(f"Latency: {answer.latency_ms} ms")
```

---

## 🛡️ Verifier & Hybrid Routing

When running `lcc route run`, the local agent solves eligible tasks. The router evaluates the answer against strict quality gates:
1. If the local answer meets requirements and confidence $\ge$ threshold $\to$ **accepted (0 remote tokens)**.
2. If the task is risky or formatting fails $\to$ **escalated to cloud provider (Fireworks AI)** with LCC-compressed prompt.
