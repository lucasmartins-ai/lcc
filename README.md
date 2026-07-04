# LCC-Router

**LCC-Router: Local Context Compiler for Hybrid Token-Efficient AI Routing** is the AMD
Developer Hackathon ACT II Track 1 submission repository.

This repo contains two clearly separated layers:

- `src/lcc/` is the pre-existing MIT-licensed Local Context Compiler baseline. It is a
  deterministic, local-first context compiler that cleans, deduplicates, inspects, prepares,
  structures, and measures text before an LLM call.
- `act2_router/` is the new hackathon-specific routing layer. It may use local model
  attempts, local verification, Fireworks AI fallback, routing policy, and evaluation glue.

The deterministic LCC core remains model-free. Do not put local LLM calls, remote LLM calls,
embeddings, vector databases, network clients, or response verification inside `src/lcc/`.
The existing LCC boundary remains documented in
[ADR 0010](docs/adr/0010-deterministic-first-preparation-model-assistance.md): optional model
assistance stays outside the deterministic core, inspection, and benchmarking boundaries.

## What Is Implemented

- LCC inspection and prepare wrappers in `act2_router/lcc_adapter.py`.
- Deterministic feature extraction in `act2_router/features.py`.
- Policy-driven routes: `LOCAL_THEN_VERIFY`, `COMPRESS_THEN_LOCAL`,
  `COMPRESS_THEN_REMOTE`, and `REMOTE_DIRECT`.
- Mock local solver and optional local HTTP adapters.
- Rule-based local verifier, plus an optional local-LLM verifier wrapper.
- Fireworks-compatible remote client with mock mode when `FIREWORKS_API_KEY` is missing.
- Local fixture evaluation runner with JSON and Markdown reports.
- Docker entrypoint for demo/eval.

## What Is Mocked

- Local solving defaults to `LOCAL_MODEL_BACKEND=mock`.
- Remote solving defaults to mock mode unless `FIREWORKS_API_KEY` is set.
- Current eval accuracy is a local development proxy, not official Track 1 accuracy.
- Official task/model adapters will be finalized after the Track 1 task format and model
  requirements are revealed.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run one task:

```bash
python -m act2_router.cli run --task examples/tasks/noisy_context.json
```

Inspect routing features:

```bash
python -m act2_router.cli inspect --task examples/tasks/noisy_context.json
```

Run local fixture eval:

```bash
python -m act2_router.cli eval --cases examples/tasks --output eval/reports/report.json
```

Show policy:

```bash
python -m act2_router.cli policy --show
```

## Tests

```bash
python -m pytest
ruff check .
ruff format --check .
mypy
```

Tests do not require Fireworks credentials or a real local model.

## Docker

```bash
docker build -t lcc-router .
docker run --rm --env-file .env lcc-router python -m act2_router.cli run --task examples/tasks/noisy_context.json
```

The default container command runs:

```bash
python -m act2_router.cli eval --cases examples/tasks --output eval/reports/docker_eval.json
```

## Real vs Mock

Real:

- deterministic LCC inspect/prepare/optimize calls;
- transparent route feature extraction;
- policy decision trace;
- rule-based local verification;
- remote token accounting from Fireworks usage when returned;
- conservative token estimates when usage is absent.

Mock by default:

- local model answer generation;
- Fireworks answer generation without credentials;
- local development accuracy proxy.

## Fireworks Configuration

Set these only when running real remote escalation:

```bash
FIREWORKS_API_KEY=fw-...
FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
FIREWORKS_MODEL_ID=accounts/fireworks/models/deepseek-v3p1
```

No API keys are committed. `.env.example` documents the expected variables.

## Baseline

See [HACKATHON_BASELINE.md](HACKATHON_BASELINE.md). It separates what existed before the
hackathon from what was added for AMD ACT II. This repo does not claim that the original LCC
core was built during the hackathon, does not claim official benchmark performance, and does
not claim local verification guarantees correctness.
