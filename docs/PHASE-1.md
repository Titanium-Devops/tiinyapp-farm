# Phase 1: the manifest, the installer, the three apps

Read README.md and SPEC.md. Deliver, each runnable, committing as you go (commits may be blocked
by your sandbox; then leave the tree with only your changes):

1. docs/manifest.schema.json (JSON Schema draft 2020-12) exactly as SPEC.md's manifest section,
   with a `python3 scripts/check-manifest.py <file>` validator that uses no third-party library.
2. manifests/titanium-tiiny-bot.json, manifests/story-lantern.json, manifests/onelane.json. Read
   the three projects to fill them truthfully: /Users/sem/code/titanium-bot-lite (entry
   {"python": "lite", "args": ["--port", "7788"]}, selfcheck `--selfcheck`, ports [7788], device
   models chat and tts, permissions microphone files network device), and the two GitHub repos
   webdevtodayjason/story-lantern and webdevtodayjason/onelane (read them with `gh api` or
   `git clone --depth 1` into /tmp; OneLane is a library: entry null, tag "library"). Release
   URLs point at GitHub release archives (a tag `v<version>` tarball URL); where no release
   exists yet, put the URL the release will have and sha256 "pending" with a note, and make the
   validator accept "pending" only with `--allow-pending`.
3. farm/farm.py: the installer in SPEC.md, stdlib only, one file, with `python3 farm/farm.py` as
   the entry and a `[project.scripts] farm = ...` in pyproject.toml for `pip install`. The catalog
   URL defaults to https://tinyapp.farm/manifests/ and is overridable with FARM_CATALOG (a local
   directory path works too, for tests and for this repo). Device config at
   ~/tinyapps/device.json 0600, written by `farm device` which prompts for the base URL and key
   without echo. Launcher: `farm start <id>` runs the entry with the data dir ~/tinyapps/<id>/data,
   logs to ~/tinyapps/<id>/farm.log, writes ~/tinyapps/<id>/farm.pid; `farm stop` sends SIGINT
   then SIGKILL after 5 s; `farm status` lists running apps with pid, port and uptime.
4. tests/ with unittest: schema validation of the three manifests; install from a local catalog
   directory with a local archive (build one from a temp dir), checksum mismatch refused, start
   and stop against a tiny fake app that prints "ready" and sleeps, update keeping the data dir,
   remove keeping data unless --purge. `python3 -m unittest` green.
5. Package Titanium Tiiny Bot for the farm: in /Users/sem/code/titanium-bot-lite add
   `scripts/release.py` that builds `dist/titanium-tiiny-bot-<version>.tar.gz` from lite/, brand/,
   README.md and lite/VERSION (no vendor/, no data/, no tests/), prints the sha256, and add
   `python3 -m lite --stop` (pid file in the data dir; SIGINT handled so Ctrl-C exits within two
   seconds even mid-turn) and `--selfcheck` already exists. Update its VERSION by one on the last
   number and its README with "install with farm". That repo's tests must stay green.
6. docs/PHASE-1-REPORT.md: what was built, the three manifests' summaries, the test counts, the
   Lite archive sha256, every deviation with its reason. Never launch a browser or any GUI.
