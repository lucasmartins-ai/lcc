# Release process

This document is the checklist for cutting a public release of `lcc`. The next prepared
release is **v0.4.0**.

> **Scope reminder.** v0.4.0 is the deterministic core (clean, dedupe, token budget,
> prompt builder) plus `lcc bench`, `lcc inspect`, deterministic Phase 1.7 prepare
> (`lcc prepare`, recommendations, chunk inventory, lexical selection; see
> [ADR 0010](adr/0010-deterministic-first-preparation-model-assistance.md)), opt-in
> relevance compaction (`lcc compact` with mechanical/Jev/Laya providers, trim,
> sufficiency, cache alignment; see ADRs 0013–0016), `lcc explain`, `lcc intake`,
> local agents, and hybrid routing. All model judgment stays opt-in and outside the
> deterministic core. It does **not** include RAG, embeddings, vector databases, an API
> server, hosted product, or semantic retrieval execution. Those are roadmap items
> (see [docs/roadmap.md](roadmap.md)) and must never be described as implemented.

Do not create a tag, publish to PyPI, or push release refs unless the maintainer explicitly
decides to release.

## 1. Pre-release local checks

Run from a clean checkout with the dev extras installed:

```bash
python -m pip install -e ".[dev]"
```

All four required checks must pass:

```bash
python -m pytest
ruff check .
ruff format --check .
mypy
```

Then exercise the installed development CLI:

```bash
lcc --version

lcc optimize examples/sample_input.txt \
  -q "What are the key points?" \
  -m gpt-4.1 \
  -o /tmp/lcc_release_prompt.md \
  -r /tmp/lcc_release_report.json

lcc inspect examples/sample_input.txt \
  -m gpt-4.1 \
  -r /tmp/lcc_release_inspect.json

lcc prepare examples/sample_input.txt \
  -q "What are the key points?" \
  -m gpt-4.1 \
  -o /tmp/lcc_release_prepare_prompt.md \
  -r /tmp/lcc_release_prepare_report.json

lcc bench benchmarks/cases --output /tmp/lcc_release_bench_1.json
lcc bench benchmarks/cases --output /tmp/lcc_release_bench_2.json
```

Confirm the benchmark output is byte-identical across repeated runs:

```bash
cmp /tmp/lcc_release_bench_1.json /tmp/lcc_release_bench_2.json
```

Note in the JSON reports whether `token_count_method` is `exact` or `approximate`. Both are
valid; exact requires `tiktoken` plus locally cached encoding assets. Do not claim exact
counting if the report says approximate.

## 2. Build and package checks

Remove stale local artifacts, then build the source distribution and wheel:

```bash
rm -rf build dist *.egg-info src/*.egg-info
python -m build
python -m twine check dist/*
```

Audit package contents before publishing:

```bash
python -m tarfile -l dist/local_context_compiler-0.4.0.tar.gz
python -m zipfile -l dist/local_context_compiler-0.4.0-py3-none-any.whl
```

Expected shape:

- The sdist includes `src/lcc`, `README.md`, `CHANGELOG.md`, `LICENSE`, `docs/`,
  `examples/`, `benchmarks/`, `config/`, and `tests/`.
- The wheel includes the `lcc` package, `lcc/py.typed`, and distribution metadata. Docs,
  examples, benchmark fixtures, and tests do not need to be installed into site-packages.

## 3. Clean environment install smoke test

Install the built wheel in a virtual environment outside the repository:

```bash
python -m venv /tmp/lcc-wheel-smoke
/tmp/lcc-wheel-smoke/bin/python -m pip install --upgrade pip
/tmp/lcc-wheel-smoke/bin/python -m pip install dist/local_context_compiler-0.4.0-py3-none-any.whl
```

Smoke-test the installed console script, not the editable checkout:

```bash
/tmp/lcc-wheel-smoke/bin/lcc --version

printf 'Alpha point.\n\nAlpha point.\n\nRegards,\nTeam\n' > /tmp/lcc_smoke_input.txt

/tmp/lcc-wheel-smoke/bin/lcc optimize /tmp/lcc_smoke_input.txt \
  -q "What are the key points?" \
  -o /tmp/lcc_smoke_prompt.md \
  -r /tmp/lcc_smoke_report.json

/tmp/lcc-wheel-smoke/bin/lcc inspect /tmp/lcc_smoke_input.txt \
  -r /tmp/lcc_smoke_inspect.json

/tmp/lcc-wheel-smoke/bin/lcc prepare /tmp/lcc_smoke_input.txt \
  -q "What are the key points?" \
  -o /tmp/lcc_smoke_prepare_prompt.md \
  -r /tmp/lcc_smoke_prepare_report.json

/tmp/lcc-wheel-smoke/bin/lcc bench benchmarks/cases \
  --output /tmp/lcc_smoke_bench.json
```

The `benchmarks/cases` path is a repository fixture path. A user installed only from PyPI can
run `lcc bench` against their own case directory using the format in
[benchmarks/README.md](../benchmarks/README.md).

## 4. CHANGELOG and versioning

- Keep `CHANGELOG.md` in [Keep a Changelog](https://keepachangelog.com/) format.
- Keep `[Unreleased]` for post-release work only.
- Move release entries into `## [MAJOR.MINOR.PATCH] - YYYY-MM-DD` at release time.
- The version lives in `pyproject.toml` (`[project] version`) and is mirrored by the source
  tree fallback in `src/lcc/__init__.py`.
- Follow [SemVer](https://semver.org/): patch for fixes, minor for additive features, major
  for breaking changes. A JSON-report breaking change also bumps the report
  `schema_version` per [ADR 0004](adr/0004-report-schema-versioning.md).

`lcc inspect`, `lcc bench`, and deterministic `lcc prepare` are additive CLI surfaces, so the
prepared release is `0.2.0` rather than a retroactive change to `0.1.0`.

## 5. GitHub checks

- Push the release branch and open a PR.
- Confirm CI passes on every configured Python version.
- Confirm the README CI badge renders and links to the Actions page.
- Confirm the publish workflow has not run; it should only run after a `v*.*.*` tag push.

## 6. PyPI Trusted Publishing setup

PyPI publishing uses GitHub Actions plus PyPI Trusted Publishing. Do **not** add PyPI tokens
or passwords to the repository.

Before the first PyPI release, configure a trusted publisher on PyPI:

- PyPI project name: `local-context-compiler`
- Owner: `vetlucasmartins`
- Repository: `lcc`
- Workflow name: `publish.yml`
- Environment name: `pypi`

The workflow is `.github/workflows/publish.yml`. It builds distributions, runs
`twine check`, uploads the distributions as a GitHub artifact, then publishes with
`pypa/gh-action-pypi-publish@release/v1` using `id-token: write`. The publish job uses the
GitHub environment `pypi`; configure that environment with reviewer protection if desired.

Trusted Publishing details:

- PyPI docs: <https://docs.pypi.org/trusted-publishers/using-a-publisher/>
- PyPA action docs: <https://github.com/pypa/gh-action-pypi-publish>

## 7. Tag and publish

Only after CI, local checks, package checks, and the clean-venv smoke test pass:

```bash
git tag -a v0.4.0 -m "lcc v0.4.0"
git push origin v0.4.0
```

The tag push triggers `.github/workflows/publish.yml`. Watch the workflow. If PyPI rejects
the upload with a trusted-publisher error, fix the PyPI publisher configuration instead of
adding a token.

Tag names are `vMAJOR.MINOR.PATCH`. Do not move or reuse a published tag.

## 8. GitHub release notes checklist

- [ ] Title: `v0.4.0`.
- [ ] Body: paste the `[Unreleased]` section from `CHANGELOG.md` (renamed to `[0.4.0]` with the release date when tagging).
- [ ] State the boundaries explicitly: deterministic, local-first, no runtime network by
      default, no API keys, no model/LLM/embedding calls in the core, and no model assistance
      inside the deterministic Phase 1.7 prepare boundary from
      [ADR 0010](adr/0010-deterministic-first-preparation-model-assistance.md).
- [ ] State that `lcc prepare` uses deterministic lexical selection only and does not summarize,
      rewrite, paraphrase, embed, or semantically rank source content.
- [ ] State the tokenization honesty note: exact only with local `tiktoken` assets,
      otherwise a clearly labelled approximate count.
- [ ] List the CLI commands: `lcc optimize`, `lcc inspect`, `lcc prepare`, `lcc bench`,
      `lcc intake`, `lcc compact` (opt-in; providers mechanical/jev/laya), `lcc explain`,
      `lcc agent`, `lcc route`, and, when including the Unreleased Phase 2 scaffold,
      `lcc semantic-retrieval`.
- [ ] Explicitly note what is not included: RAG, embeddings, vector databases, API server,
      hosted product, and semantic retrieval execution. Model judgment (`compact` providers,
      agents, routing, verifier) is opt-in only and outside the deterministic core.
- [ ] Link ADRs 0001-0016 for the frozen design decisions.
