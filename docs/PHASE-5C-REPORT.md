# Phase 5c report

Implemented release-free seed submissions and owner updates. Sprouting seeds retain their catalog content and social features, show a muted Sprouting chip and share-card label, and omit install/release details. The installer reports sprouting state and refuses installation; CI keeps schema and owner gates while skipping archive work.

Verified owners can PUT updates through the existing PR, label, and status flow. New releases require a strictly higher numeric semver; text updates can retain the version and release. The farm exposes Update buttons and seed pages reveal an owner-only link. Forms prefill and lock the ID, preserve Python entries, screenshots and media, and invite sprouting makers to add their first release. Update uploads use distinct hashed filenames to protect other pending PRs, and retries include uploaded content in their identity.

Changed files:
- `worker/seeds.mjs`, `worker/manifest.mjs`: optional releases, ownership, updates and status.
- `docs/manifest.schema.json`, `farm/farm.py`, `scripts/check-manifest.py`, `scripts/check-submission.py`, `.github/workflows/manifest-check.yml`: schema, installer and CI.
- `scripts/build-site.py`, `scripts/share-cards.py`, `site/assets/{farm,seeds,session}.js`, `site/assets/site.css`: rendering and forms.
- `tests/{worker.test.mjs,test_farm.py,test_submission.py,test_site.py,test_share.py}`: regressions; this report.

Simplification: creation and updates share the submission pipeline and schema; no framework or dependency added.

Verification: `python3 -m unittest` (109 passed), `node --test tests/worker.test.mjs` (35 passed), `python3 scripts/build-site.py` (4 pages), and `python3 scripts/check-manifest.py manifests/*.json` (4 valid). Changed JS syntax checks, Python compilation, and `git diff --check` passed. UI behavior was exercised with DOM fakes and generated HTML/image drawing assertions.

Limitations: live GitHub/R2 and rendered browser layout were not exercised. The four existing hand-added manifests currently omit `author.tiinyverse`; their verified profile must be recorded, or a stored seed owner must exist, before their makers receive update access. No ownership was inferred from names or unrelated URLs. No browser, GUI, wrangler, Docker, or repository commit was used.
