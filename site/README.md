# lcc site

Static site for lcc: landing, use cases, research log, downloads and an in-browser intake judge demo.
Astro + Tailwind, built to plain HTML; the only client script is the demo.

```sh
cd site
npm ci
npm run fetch-judge   # full-history clone of LCC-judge into .cache/ (or set LCC_JUDGE_DIR to a clone)
npm test              # TypeScript intake judge vs the Python output in test/intake-parity.json
npm run build         # -> dist/
npm run preview
```

Nothing is typed by hand twice:

- The landing and the docs sidebar read `docs/index.md`; every `docs/**/*.md` page keeps its old Jekyll path
  (`QUICKSTART.html`, `PRIVACY_POLICY.html`).
- The research log reads LCC-judge through git at one commit (`LCC_JUDGE_REF`, default `HEAD`): `STATUS.md`
  for state, each protocol's first commit for its date, each results file's "Bottom line" for the result.
  `src/lib/research.ts` only maps studies to files.
- Numbers quoted in prose go through `cite()`, which fails the build when the quoted text is no longer in its
  source file. Model sha256 values are computed and must match the pins in the Python loaders.
- After a change to the intake model, regenerate the fixture: `python tests/test_site_intake_fixture.py --write`.

Deploy is not wired. `SITE_BASE=/lcc` builds for `lucasmartins-ai.github.io/lcc`; the default `/` suits a
custom domain.
