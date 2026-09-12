# tiinyapp.farm

Community apps for the Tiiny AI Pocket Lab that run beside the device on your own computer.
Browse at https://tiinyapp.farm, install with one command, share the device without collisions.

Brought to you by [Titanium Bot](https://titanium.bot). Made by Titanium Computing.

- `manifests/` one JSON file per app, the whole catalog.
- `farm/` the installer: `farm install <app>`, `farm start`, `farm stop`, `farm update`, `farm list`.
- `site/` the static catalog, built from the manifests.
- `.github/workflows/` the checks a submitted manifest must pass.

See `SPEC.md`.

## Phase 1 installer

Python 3.11 or newer on macOS or Linux; runtime dependencies are all standard library.

```sh
python3 -m pip install .
farm device
farm install titanium-tiiny-bot
farm start titanium-tiiny-bot
farm status
farm stop titanium-tiiny-bot
```

Story Lantern and OneLane are **pending release drafts**. They can be validated
with `--allow-pending`, but installation is refused until their checksums are set.
The Lite manifest records the included local archive's checksum and size; its
public release URL remains unverified. Nothing is downloaded or run
by manifest validation. The installer displays permissions and requirements and
asks once; `--yes` explicitly accepts that prompt for automation.

```sh
python3 scripts/check-manifest.py --allow-pending manifests/story-lantern.json
FARM_CATALOG="$PWD/manifests" python3 farm/farm.py list
python3 -m unittest
```

`FARM_CATALOG` defaults to `https://tiinyapp.farm/manifests/`. It also accepts a local
directory or `file://` directory URL. Local catalogs may refer to local tar archives
by absolute/relative path or `file://` URL. Remote catalogs must use HTTP(S) release
URLs. For `farm list`, a remote catalog directory serves either a JSON array of app
IDs (or objects with `id`) or HTML links to its manifest JSON files.

Installed versions live in `~/tiinyapps/<id>/<version>`; `current` is an atomically
written version pointer. `launcher.json` registers the entry for `farm start`.
The app runs in its version directory with `FARM_DATA_DIR` and `TIINY_DATA_DIR`
pointing at `~/tiinyapps/<id>/data`. Standard output and errors append to `farm.log`;
`farm.pid` holds the process ID. A runtime file lock distinguishes a live process
from a stale PID. Entries run directly, without a shell. Apps must remain in the
foreground and keep inherited descriptors open; daemonizing/closing all inherited
file descriptors is not supported by this launcher.

`farm device` reads both the base URL and API key without echo and atomically saves
`~/tiinyapps/device.json` with mode `0600`. If a secure terminal is unavailable, it
refuses to fall back to echoed input. Scripts can import settings with
`farm device --base http://device:8800/v1 --key-stdin < private-key-file`, or run
`farm device` with `TIINY_BASE` and `TIINY_KEY` in the environment. Both forms save
the configuration for later launches. Explicit options take precedence over the
environment; incomplete scripted input fails without prompting. Keys never need
to appear in command arguments. The launcher passes `TIINY_BASE`, `TIINY_KEY`,
and the derived `TIINY_HOST`. Cooperating apps share `ONELANE_DIR=~/tiinyapps/.onelane`.
Story Lantern additionally receives `LANTERN_HOME`, its database/log paths, and
`PORT`; its upstream device management still expects plain HTTP port 8800.
Story Lantern currently retries contention but has not adopted OneLane, so merely
setting the shared path cannot guarantee cross-app serialization for that app.

`farm start <id>` rejects already-listening ports, then waits up to ten seconds
for all declared ports while checking that the child remains alive. A manifest's
optional `"health": "/api/health"` requests HTTP GET on its first port, returning
a JSON object (with `version`, and optional `ok`); other ports use TCP connections.
Failed startup exits 1, prints the last ten log lines, and removes process records.
Apps without declared ports receive a short process-liveness check.

`farm start <id> --port 7790` overrides the primary port and exports `TIINYAPP_PORT`.
Lite also receives `TIINY_PORT` and an updated `--port` argument; Story Lantern
receives `PORT`. Other apps must honor `TIINYAPP_PORT`. `farm status` displays the
recorded ports and compares the health-reported version with the installed
manifest, suggesting a restart on mismatch. Without health version data it uses
the launch record and labels unavailable health data.

`farm update <id>` installs only a newer version, preserves data and previous code,
and stops a running old version after the new archive is verified and unpacked.
Start it again with `farm start <id>`. `farm stop <id>` sends SIGINT to the process
group and escalates to SIGKILL after five seconds. `farm remove <id>` stops it and
keeps `data/`; `farm remove <id> --purge` deletes that app's data too. Shared device
settings and locks survive app removal. OneLane is a library: it can be installed,
but `farm start onelane` explains that it has no runnable entry.

Archives are tar/tar.gz, bounded to 512 MiB downloaded and 2 GiB unpacked. Traversal,
links, special files and duplicate file entries are refused. Checksums and byte
sizes must match before extraction. These checks do not sandbox installed app code;
permissions describe what the author declares. `verified` remains false until CI
and human review. The site and submission CI are later phases.
