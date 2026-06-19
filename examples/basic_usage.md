# Basic usage

This walkthrough uses the bundled `examples/sample_input.txt`, a messy status note with
duplicated paragraphs, a mobile signature, a page marker, a decorative rule, and excessive
blank lines.

## 1. Optimize a file

```bash
lcc optimize examples/sample_input.txt \
  --question "What are the key points and risks?" \
  --model gpt-4.1 \
  --max-input-tokens 6000 \
  --output optimized_prompt.md \
  --report report.json
```

The terminal shows a summary (printed to stderr):

```
    lcc -- optimization summary
Model               gpt-4.1
Token counting      exact (tiktoken)
Original tokens     236
Optimized tokens    128
Token savings       45.8%
Compression ratio   0.542
Full prompt tokens  267
Est. cost before    0.000472 USD
Est. cost after     0.000256 USD
Est. cost savings   0.000216 USD
```

- `optimized_prompt.md` contains the evidence-aware prompt (role, question, cleaned context,
  constraints, response requirements, length guidance).
- `report.json` contains the full machine-readable report (see the README for the schema).

## 2. Read from stdin

Use `-` as the input to read from stdin. The prompt goes to `--output` (or stdout); the
summary goes to stderr, so piping stays clean:

```bash
cat examples/sample_input.txt | lcc optimize - \
  --question "Summarize the relevant information." \
  --output optimized_prompt.md \
  --report report.json
```

## 3. Tune the behavior

```bash
# Editable defaults and pricing
lcc optimize examples/sample_input.txt -q "Summarize." \
  --config config/default.yaml --pricing config/pricing.yaml

# Keep all paragraphs / boilerplate (disable cleaning steps)
lcc optimize examples/sample_input.txt -q "Summarize." --no-near-dedup --no-boilerplate

# Add explicit constraints (repeatable) and a length target
lcc optimize examples/sample_input.txt -q "Summarize." \
  --constraint "Answer in English." \
  --constraint "Use at most five bullet points." \
  --max-output-tokens 300
```

## 4. Use the report programmatically

```bash
lcc optimize examples/sample_input.txt -q "Summarize." --report report.json -o /dev/null
python -c "import json; r=json.load(open('report.json')); print(r['token_savings_percent'], '% saved')"
```

## Notes

- If `tiktoken` is not installed, counts are **approximate** and the report's
  `token_count_method` will say so. Install with `pip install ".[tiktoken]"` for exact counts.
  `lcc` never downloads tokenizer assets at runtime, so exact counting also needs the
  encoding cached locally; if it is unavailable offline, counting falls back to approximate
  with a warning explaining why (see [ADR 0008](../docs/adr/0008-tokenizer-network-boundary.md)).
- Pricing values are **editable examples**, not guaranteed current prices. Edit
  `config/pricing.yaml` (or pass your own via `--pricing`) and verify against your provider.
