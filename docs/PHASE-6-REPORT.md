# Phase 6 report

Implemented both parts without a framework or new dependency.

- `scripts/build-site.py`, `scripts/share-cards.py`, `site/assets/{farm,seeds,session,social}.js`, and `worker/{index,main,makers,proof,seeds,social}.mjs`: literal install, account, verification, submission, review and error text; Your apps navigation; Apps by maker titles; No release yet badges; plain review statuses. App sections now follow description, install, requirements, release, maker, comments. Media sits within the description. Removed decorative instructions and the alternative source-install walkthrough; retained colors, fonts and artwork.
- `farm/farm.py`: deferred POSIX/Windows lock imports, Windows detached launches and termination, process creation-time checks to avoid terminating reused PIDs, portable file URLs, and Windows archive-path validation. Device settings now use `~/.tiinyapps/device.json`, with a read fallback for existing `~/tiinyapps/device.json` settings. Windows permissions are best effort, so site copy accurately describes user-folder permissions instead of promising a POSIX mode guarantee.
- `pyproject.toml` lowers the CLI floor to Python 3.9; no newer runtime feature was necessary. `.github/workflows/site.yml` adds the requested Ubuntu/macOS/Windows × Python 3.9/3.12 installer matrix and preserves existing jobs. `README.md`, `docs/SUBMIT.md`, and the Python/Worker tests were updated to match.

Retained nonliteral wording: “Little apps, grown for your Tiiny” is the explicitly requested hero exception. The TiinyVerse paragraph retains the requested DNS TXT-record analogy, and “Thumbs up” retains the requested control name. No other decorative instructional sentences were retained; app names and maker-authored content remain their own content.

Verification: `python3 -m unittest` passed 117 tests (one Windows-only skip); `node --test tests/worker.test.mjs` passed 36 tests; `python3 scripts/build-site.py` built all four app pages. Ruff, scoped mypy with imports skipped, actionlint, JavaScript syntax checks and diff whitespace checks passed. Python 3.9 syntax parsing passed. The broader mypy import traversal encountered unrelated installed PySide6 stub errors; scoped checks passed.

Limits: native Windows and Python 3.9 execution await the new CI matrix. Windows terminates the direct app process; POSIX retains process-group shutdown. One optional remote card image was unreachable in this environment; the existing fallback rendered successfully. No browser, GUI, wrangler, Docker or commit was launched or created.
