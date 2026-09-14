# DAYBREAK-1: Daybreak comes to the farm

Jason, 2026-09-14 06:09 CDT: "We forgot one of the Tiiny apps. This is a major one. It's not
prepared yet for the farm but it should be. https://github.com/webdevtodayjason/daybreak"

Daybreak is a live world-news wall that thinks entirely on the Tiiny: 14 public RSS feeds,
every article summarised, categorised, geotagged, scored and embedded on the device, rendered
as a wall on port 8811. Python standard library, no pip. Today it is two processes (`pipeline.py`
and `server.py`), configured by `TIINY_HOST` and `TIINY_KEY` in the environment, with no
license, no release, a `deploy/` folder of shell scripts and systemd units, and `audio.py`
which shells out to ffmpeg (the farm forbids subprocess in a listed archive). `r2.py` is an
optional offsite sync that is inert without R2_* variables. Read the whole repo first,
including CONTRACT.md and deploy/install.sh, so the farm shape keeps what the deploy shape does.

## In the daybreak repo (Jason's, push to main, plain-prose commits, no em dashes)

1. `LICENSE`: MIT, Titanium Computing, like the other farm apps.
2. One entry: a `daybreak` script (no extension, like `ainode-pocket`) that runs the pipeline
   and the server in one process (threads or the pipeline scheduled from the server's own
   loop, whichever the code already leans to), takes `--port N` and honours `TIINYAPP_PORT`,
   and keeps `python3 pipeline.py` and `python3 server.py` working exactly as the README
   says for people who cloned it. Ctrl-C stops both cleanly. A `--selfcheck` that needs no
   device: creates the database, serves the wall on a spare loopback port, fetches `/` and
   the health route, exits 0 within a few seconds. `/healthz` (or whatever the server already
   has) answers 200 without a device.
3. The device: keep `TIINY_HOST` and `TIINY_KEY`, and when they are unset read the farm's
   `~/.tiinyapps/device.json` ({"base","key"}) the way titanium-tiiny-bot and ainode-pocket
   do (read /Users/sem/code/titanium-bot-lite/lite/device.py for the recipe; never print the
   key). With no device at all the wall still serves and says so on the page, and the
   pipeline waits instead of crashing.
4. The farm archive: `audio.py` uses subprocess for ffmpeg and cannot ship in the listed
   archive; make its use lazy behind a feature that is off unless ffmpeg is on the PATH, and
   exclude `audio.py`, `deploy/` and `r2.py` from the release asset if the wall runs without
   them (measure that it does). Build the asset with a script in the repo (`scripts/release.py`
   or a Makefile target), `COPYFILE_DISABLE=1` on macOS so no `._` files ride along, named
   `daybreak-<version>.tar.gz` with a `daybreak-<version>/` root. Run the farm's scanner on it:
   `python3 /Users/sem/code/tiinyapp-farm-daybreak/scripts/scan-archive.py <archive> <manifest>`
   must answer ok true. Run the farm's offline selfcheck the way CI does (python:3.11-slim,
   read-only mount, HOME=/tmp, no network; the command is in
   /Users/sem/code/tiinyapp-farm-daybreak/scripts/check-submission.py, `selfcheck_command`);
   it must exit 0.
5. Tag `v0.1.0` and publish a GitHub release with the asset attached.

## In the farm worktree (/Users/sem/code/tiinyapp-farm-daybreak, branch daybreak)

`manifests/daybreak.json` in the shape of `manifests/ainode-pocket.json`: id daybreak, name
Daybreak, pitch one sentence in plain words, description from the README in Jason's voice,
version 0.1.0, author Jason with the same tiinyverse profile as the other four, license MIT,
homepage and repo the GitHub URL, release url/sha256/size computed from the real downloaded
asset (never typed), entry `python3 daybreak --serve` (or whatever you built), `port`
`{"argv": "--port"}`, requires python "3.11", ports [8811], device models [] (it uses
whatever chat and embedding models are loaded; say so in the description), permissions
files, network, device, `health` the route you kept, `selfcheck` true, verified true,
featured false, tags news, wall, osint. No `media` yet: the orchestrator draws the art with
the house style after your PR. `python3 scripts/check-manifest.py` must say Valid.
Commit, push the branch, open a PR against main with gh; never push main, never merge.

## Prove it

From a fresh venv with the published farm (`pip install tiinyapp-farm`, real PyPI is fine for
the CLI) and HOME redirected to a scratch directory: `farm install daybreak` from a LOCAL
catalog copy that carries your manifest (the live catalog will not have it until the PR
merges; the use-check report shows how to serve a local catalog, or install from the
manifest file if the CLI allows), `farm start daybreak --port 7871`, the wall answers on
7871, `farm stop`. Paste the transcript in docs/DAYBREAK-1-REPORT.md with what is not
proven (a real feed run against the device is yours to try only if the key is on this Mac in
~/.tiinyapps/device.json; never print it).

## Rules

Model opus. No em dashes anywhere. Spell it Tiiny. Never read ~/.api_keys or any file with
key, token or secret in its name. Ports 7871 to 7879 only. Report back in under 40 lines: the
release URL, the PR URL, the scan and selfcheck lines, the transcript, and what is not proven.
