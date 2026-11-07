# lcc site

Static site for lcc at `lookadev.com/lcc/`: landing, use cases, research log, downloads and an in-browser intake
judge demo. Astro + Tailwind, built to plain HTML; the only client script is the demo.

```sh
cd site
npm ci
npm run fetch-judge   # full-history clone of LCC-judge into .cache/ (or set LCC_JUDGE_DIR to a clone)
npm test              # TypeScript intake judge vs the Python output in test/intake-parity.json
npm run build         # -> dist/lcc/
npm run preview       # http://localhost:4321/lcc/
```

Nothing is typed by hand twice:

- The landing and the docs sidebar read `docs/index.md`; every `docs/**/*.md` page keeps its file name
  (`/lcc/QUICKSTART`, `/lcc/PRIVACY_POLICY`).
- The research log reads LCC-judge through git at one commit (`LCC_JUDGE_REF`, default `HEAD`): `STATUS.md`
  for state, each protocol's first commit for its date, each results file's "Bottom line" for the result.
  `src/lib/research.ts` only maps studies to files.
- Numbers quoted in prose go through `cite()`, which fails the build when the quoted text is no longer in its
  source file. Model sha256 values are computed and must match the pins in the Python loaders.
- After a change to the intake model, regenerate the fixture: `python tests/test_site_intake_fixture.py --write`.

Deploy: `wrangler.jsonc` defines the `lcc-site` Worker (static assets only) on the route `lookadev.com/lcc/*`;
`lookadev.com/lcc` itself stays the pt-BR page of the lookadev Worker. `.github/workflows/site.yml` builds and runs
`wrangler deploy` on pushes that touch the site's sources, daily (new LCC-judge results) and on demand, only when
the repository variable `SITE_DEPLOY` is `true` and the `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` secrets
exist (put them in a GitHub Environment named `lcc-site` limited to `main`). `npx wrangler deploy --dry-run` checks
the config without publishing.
