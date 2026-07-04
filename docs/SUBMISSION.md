# Submission Notes

## Project Title

LCC-Router: Local Context Compiler for Hybrid Token-Efficient AI Routing

## Short Description

LCC-Router is a local-first routing agent that uses deterministic LCC inspection and
compression, attempts local answers when risk is low, gates local acceptance through a
verifier, and escalates to Fireworks AI only when justified.

## Track 1 Fit

Track 1 rewards preserving output quality while reducing remote token use. LCC-Router treats
remote tokens as scarce and local work as zero-cost for scoring.

## Token Efficiency

- LCC identifies duplicate/noisy context before routing.
- The policy compresses before remote escalation when projected savings are material.
- Local attempts use zero remote tokens.
- Local verification prevents automatic acceptance of weak local answers.
- Fireworks is used for high-risk or rejected cases.

## Baseline Split

Pre-existing LCC baseline:

- deterministic cleaning;
- deduplication;
- token counting;
- cost estimation;
- inspect/prepare;
- lexical selection;
- deterministic benchmark harness;
- ADRs and baseline docs.

Built for AMD ACT II:

- `act2_router` package;
- local solver adapter;
- local verifier;
- Fireworks client;
- routing policy;
- task fixtures and eval runner;
- Docker submission path;
- hackathon docs.

## Demo

```bash
python -m act2_router.cli run --task examples/tasks/noisy_context.json
```

## Eval

```bash
python -m act2_router.cli eval --cases examples/tasks --output eval/reports/report.json
```

## Docker

```bash
docker build -t lcc-router .
docker run --rm --env-file .env lcc-router python -m act2_router.cli run --task examples/tasks/noisy_context.json
```

## Limitations

- Mock local and remote solvers are default until configured.
- Fixture accuracy is a local proxy, not official accuracy.
- Rule verification checks format/risk signals; it does not guarantee correctness.
- Official task adapters and model IDs will be finalized after kickoff.

## Future Improvements

- Calibrate thresholds on official tasks.
- Add official answer parser/scorer.
- Add local model-specific adapters once Track 1 models are known.
- Add richer evidence checks while keeping them outside `src/lcc`.
