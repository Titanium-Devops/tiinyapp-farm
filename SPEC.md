# tiinyapp.farm, the spec

Status: draft 2026-09-12, owner Jason Brashear. Domain tiinyapp.farm is registered and on
Cloudflare. Repo: Titanium-Devops/tiinyapp-farm (private until launch).

## What it is
A catalog of community apps for the Tiiny AI Pocket Lab that run BESIDE the device on the
person's computer (TiinyOS has an Agent Store of pre-installed open-source agents and no public
submission path). One manifest per app, one static site, one installer, one submission flow.
First three apps: Titanium Tiiny Bot (/Users/sem/code/titanium-bot-lite), Story Lantern
(github.com/webdevtodayjason/story-lantern), OneLane (github.com/webdevtodayjason/onelane).

## The manifest (manifests/<id>.json)
id (lowercase, dashes; never `tiiny`), name, pitch (one line), description (plain words),
version (0.1.1 style; only the last number moves without the author), author {name, url},
license, homepage, repo, screenshots [urls], release {url, sha256, size}, entry (how to start:
{"python": "lite", "args": ["--port", "7788"]} or {"command": "..."}), requires {python: "3.11",
ports: [7788], device: {models: ["chat", "tts"], npuUnits: 57}}, permissions [microphone, files,
network, device], tags, verified (set only by the farm's CI and a human), addedAt, updatedAt.
A JSON schema in docs/manifest.schema.json validates it; the site renders it in plain words.

## The installer (farm/farm.py, stdlib Python 3.11+, one file, `pip install tiinyapp-farm` later)
- `farm install <id>`: fetch manifests/<id>.json from the catalog (https://tiinyapp.farm/manifests/<id>.json),
  show name, pitch, permissions and what it needs, ask once, download the release archive, verify
  sha256, unpack to ~/tiinyapps/<id>/<version>, write ~/tiinyapps/<id>/current, register a launcher.
- One shared device config at ~/tiinyapps/device.json (0600): base URL and key pasted once; every
  app reads it through the env the launcher sets (TIINY_BASE, TIINY_KEY). OneLane's lock lives at
  a shared path so apps take turns on the device.
- `farm start <id>`, `farm stop <id>` (pid file; SIGINT then SIGKILL after 5 s), `farm status`,
  `farm update <id>` (re-fetch manifest, install the newer version, keep the data dir),
  `farm list` (installed and catalog), `farm remove <id>` (keeps data unless --purge).
- Never runs an archive whose checksum differs; never prints the key.

## The site (site/, static, built by scripts/build-site.py from manifests/)
Cards on Midnight #090D14 with Signal Cyan #00C8F0, Titan mark small in the footer, Tiiny's logo
in "Built for". One page per app rendering the manifest; an "Install" block with the one command;
a "Submit your app" page describing the pull request. Deployed on Coolify like titanium.bot.

## Submission (.github/workflows/manifest-check.yml)
A pull request adds or changes one manifest. CI: schema valid, id unique, release URL reachable,
sha256 matches, archive unpacks, the app's own selfcheck (entry with --selfcheck if declared)
runs in a container with no network except the download, no secrets in the archive, declared
permissions match a static scan of the code (sockets, subprocess, microphone). Merge publishes.
"Verified" is a manual review step recorded in the manifest by a maintainer.

## Order
1. docs/manifest.schema.json, manifests for the three apps, farm/farm.py with tests, and Lite
   packaged as a release archive with a selfcheck entry.
2. The site and its build script.
3. The submission CI.

## Added 2026-09-12 05:00 by Jason
- A fourth app for launch: Tiiny Bench, partially built, at the path recorded in docs/APPS.md.
- The feel of the site: FUN. A fantasy farm: apps are things you grow and pick, the catalog is
  the field, install is "plant it", running apps are "growing", the submit page is "bring your
  seeds". Warm and playful on top of the Midnight palette, Titan and Tiiny's marks present, no
  corporate tone. Phase 2 (the site) designs this; phase 1 only names it.
