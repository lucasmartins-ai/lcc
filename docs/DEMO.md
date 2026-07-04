# Demo

Run the default mock demo:

```bash
python -m act2_router.cli run --task examples/tasks/noisy_context.json
```

Expected behavior:

- LCC inspects the noisy context;
- policy sees projected cleanup value;
- router uses local-first behavior when risk is low;
- verifier gates acceptance;
- remote tokens stay at zero if local is accepted.

Force a remote-like path with the ambiguous fixture:

```bash
python -m act2_router.cli run --task examples/tasks/ambiguous_task.json
```

Without `FIREWORKS_API_KEY`, this uses the mock remote solver and labels the route through
the final metadata.
