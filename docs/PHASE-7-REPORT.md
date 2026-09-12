# Phase 7 report

Implemented the approved inner-page frames: numbered Install rows, the three-step Submit flow with three single-column fieldsets, and the App page with a 300 px details rail that stacks below 760 px. Added `/install/`, `/submit/`, `/account/` and permanent legacy redirects. Shared navigation now shows Sign in or the maker's avatar and first name. The homepage hero is preserved; catalog and maker links use the new wording.

Changed files: `scripts/build-site.py`, new `scripts/submit-page.html`, `site/assets/{site.css,seeds.js,session.js,farm.js}`, `worker/{main,index,makers,seeds}.mjs`, `wrangler.toml`, `README.md`, `docs/SUBMIT.md`, and `tests/{test_site.py,test_submission.py,worker.test.mjs}`.

Simplifications: removed the old submit FAQ/grid and duplicated install content on the homepage; replaced the permission multi-select with four checkboxes. Kept API paths and manifest fields stable, including existing update metadata, images, drafts and inline validation. CLI and share-card messages already used the prescribed wording; “Grown by” remains.

Verification:

- `python3 -m unittest`: 118 tests, OK, one platform-specific skip.
- `node --test tests/worker.test.mjs`: 37 passed.
- `python3 scripts/build-site.py`: built four app pages successfully.
- Ruff on changed Python files, mypy on the builder, JavaScript syntax checks and `git diff --check`: passed.
- Structural tests cover navigation, exact layout dimensions, fieldsets, release visibility, permission serialization, update preservation and hash-selected sign-in steps.

Limitations: no browser or GUI was launched, so pixel-level rendering was not checked. The remote maker avatar was unavailable in the restricted network; share-card generation used its existing fallback. The reference's `farm list` description was reproduced as requested; the current CLI lists catalog apps and exposes running apps through `farm status`.

No new dependencies, deployment, wrangler, docker or commit.
