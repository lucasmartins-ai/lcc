# Release process

This document is the checklist for cutting a public release of `lcc`. The first public
release is **v0.1.0**.

> **Scope reminder.** v0.1.0 is the deterministic MVP plus the deterministic benchmark
> harness. It does **not** include RAG, embeddings, vector databases, local or remote LLM
> calls, an API server, voice/audio or ASR, transcript ingestion, semantic scoring, model
> routing, or response verification. Those are roadmap items
> (see [docs/roadmap.md](roadmap.md)) and must never be described as implemented.

## 0. Outstanding repository-URL placeholder (do this first)

The repository is **not yet wired to a GitHub remote**, so the canonical project URL is
unknown and must not be invented. The placeholder `your-org/local-context-compiler`
currently appears in:

- `pyproject.toml` — `[project.urls]` (`Homepage`, `Repository`, `Issues`)
- `CHANGELOG.md` — the `[Unreleased]` / `[0.1.0]` link references at the bottom
- `CONTRIBUTING.md` — the `git clone` URL in **Development setup**

**Maintainer action before publishing:**

1. Create the GitHub repository and add the remote
   (`git remote add origin https://github.com/<owner>/<repo>`).
2. Replace every `your-org/local-context-compiler` occurrence above with the real
   `<owner>/<repo>`. Find them with:

   ```bash
   grep -rn "your-org/local-context-compiler" --include='*.toml' --include='*.md' .
   ```

3. Add the CI status badge to `README.md` once the repo is known (see step 5).

`benchmarks/README.md` contains `<case_id>` / `<your_id>` — those are intentional
placeholders in user-facing instructions, **not** repository URLs. Leave them.

## 1. Pre-release local checks

Run from a clean checkout with the dev extras installed (`pip install -e ".[dev]"`). All
of these must pass — never fabricate results; if a check cannot run, say so.

```bash
python -m pytest
ruff check .
ruff format --check .
mypy
```

Then exercise both CLI commands end to end:

```bash
lcc optimize examples/sample_input.txt \
  -q "What are the key points?" \
  -m gpt-4.1 \
  -o /tmp/lcc_release_prompt.md \
  -r /tmp/lcc_release_report.json

lcc bench benchmarks/cases --output /tmp/lcc_release_bench_1.json
lcc bench benchmarks/cases --output /tmp/lcc_release_bench_2.json
```

Confirm the benchmark output is **byte-identical** across the two runs (determinism is a
release gate):

```bash
cmp /tmp/lcc_release_bench_1.json /tmp/lcc_release_bench_2.json \
  && echo "OK: benchmark reports are byte-identical" \
  || echo "FAIL: benchmark reports differ — determinism regression"
```

Note in `/tmp/lcc_release_report.json` whether `token_count_method` is `exact` or
`approximate`. Both are valid; exact requires `tiktoken` plus locally cached encoding
assets (lcc never downloads them — see
[ADR 0008](adr/0008-tokenizer-network-boundary.md)). Do not claim exact counting if the
report says approximate.

## 2. GitHub checks

- [ ] Push the release branch.
- [ ] Confirm the **CI workflow** (`.github/workflows/ci.yml`) passes on Python 3.11,
      3.12, and 3.13.
- [ ] Replace the repository-URL placeholders (step 0).
- [ ] Add the CI badge to `README.md` and confirm it renders and links correctly
      (step 5).

## 3. CHANGELOG process

- Keep `CHANGELOG.md` in [Keep a Changelog](https://keepachangelog.com/) format.
- Move everything under `[Unreleased]` into a dated, versioned section
  (`## [0.1.0] - YYYY-MM-DD`) at release time.
- Use the actual release date. If the date is genuinely undecided, leave the heading as
  `## [Unreleased]` and add re-dating it as a release checklist item — do not invent a
  date.
- Update the link references at the bottom once the repository URL is known.

## 4. Version bump process

- The version lives in `pyproject.toml` (`[project] version`). It is the single source of
  truth.
- Follow [SemVer](https://semver.org/): patch for fixes, minor for additive features,
  major for breaking changes. A JSON-report breaking change also bumps the report
  `schema_version` per [ADR 0004](adr/0004-report-schema-versioning.md).
- Bump the version and the CHANGELOG heading in the same commit.

## 5. README badge

Once the GitHub `<owner>/<repo>` is known, add the CI badge near the top of `README.md`:

```markdown
[![CI](https://github.com/<owner>/<repo>/actions/workflows/ci.yml/badge.svg)](https://github.com/<owner>/<repo>/actions/workflows/ci.yml)
```

- [ ] Badge URL uses the real `<owner>/<repo>`.
- [ ] Badge image renders and the link opens the Actions page.

Until the repository URL is known, **do not** insert a placeholder/fake badge — leave this
item open instead.

## 6. Tag process

After CI is green and the CHANGELOG is dated:

```bash
git tag -a v0.1.0 -m "lcc v0.1.0"
git push origin v0.1.0
```

Tag names are `vMAJOR.MINOR.PATCH`. Do not move or reuse a published tag.

## 7. GitHub release notes checklist

- [ ] Title: `v0.1.0`.
- [ ] Body: paste the `[0.1.0]` section from `CHANGELOG.md`.
- [ ] State the boundaries explicitly: deterministic, local-first, **no runtime network by
      default**, no API keys, no model/LLM/embedding calls in the core.
- [ ] State the tokenization honesty note: exact only with local `tiktoken` assets,
      otherwise a clearly labelled approximate count.
- [ ] List the two CLI commands: `lcc optimize` and `lcc bench`.
- [ ] Explicitly note what is **not** included (RAG, embeddings, LLM calls, API server,
      voice/audio, semantic evaluation).
- [ ] Link the ADRs (0001–0008) for the frozen design decisions.

## 8. PyPI publishing (future / manual)

PyPI publishing is **not configured** and is out of scope for v0.1.0. If/when it is set up:

- Build with `python -m build` and verify the sdist/wheel install in a clean venv.
- Upload with `twine upload` using a scoped API token, ideally via a trusted-publisher
  GitHub Action rather than a long-lived token.
- The distribution name is `local-context-compiler`; the installed console script is
  `lcc`.

Until then, install from source (`pip install -e ".[dev]"` for development, or
`pip install ".[tiktoken]"` for a minimal runtime install with exact token counting).
