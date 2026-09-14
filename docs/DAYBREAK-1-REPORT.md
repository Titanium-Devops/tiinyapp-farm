# DAYBREAK-1 report: Daybreak comes to the farm

Worker report against `docs/DAYBREAK-1.md`. Everything below was measured on Jason's
Mac (Darwin 25.6.0, Apple silicon, Python 3.14.6, Docker 29.5.3) unless it says
otherwise. The Tiiny in the live section is the USB-attached box this Mac already had
in `~/.tiinyapps/device.json`; its address and key are never printed here.

* Release: <https://github.com/webdevtodayjason/daybreak/releases/tag/v0.1.0>
* Asset: `daybreak-0.1.0.tar.gz`, sha256 `c25c7fda5d6c0dfa773db76a006306a3a9493057a4d909b11a2b90b9d89933eb`, 1900488 bytes
* Manifest: `manifests/daybreak.json`

## The gates

```
$ python3 scripts/scan-archive.py daybreak-0.1.0.tar.gz manifests/daybreak.json
scan ok: True | findings: []            (43 imports listed)

$ python3 scripts/check-manifest.py manifests/daybreak.json
Valid: manifests/daybreak.json

# the offline selfcheck, built by scripts/check-submission.py's selfcheck_command
$ docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
    --pids-limit 64 --memory 512m --cpus 1 --user 65534:65534 \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
    -v .../daybreak-0.1.0:/app:ro -w /app python:3.11-slim \
    python3 daybreak --serve --selfcheck
daybreak 0.1.0 selfcheck
  database                 /tmp/daybreak-selfcheck-kfte10s9/daybreak.db
  device configured        no
  no Tiiny configured (no TIINY_HOST/TIINY_KEY and no ~/.tiinyapps/device.json). Fetching will run, enrichment waits
  r2 offsite sync not present in this build (inert)
  /                        200 229743 bytes
  /healthz                 200 120 bytes
  /api/items?limit=5       200 12 bytes
  /api/clusters            200 15 bytes
  /api/stats               200 1663 bytes
  /cam.jpg                 503
  /nope                    404
  database written         106496 bytes
daybreak selfcheck OK
container selfcheck exit=0 in 0.6s

$ python3 -m unittest          # the farm's own suite, in this worktree
Ran 212 tests in 33.601s
OK (skipped=2)
```

The app's own checks, all from a clean HOME with no device: `python3 db.py`,
`python3 jobs.py --selfcheck`, `python3 r2.py --selfcheck`, `python3 device.py`,
`python3 server.py --selfcheck` and `python3 daybreak --selfcheck` each exit 0.
`python3 -m py_compile` is clean on every module and `bash -n` on all four
`deploy/*.sh`.

## Prove it: install and run

Fresh venv, the published CLI from real PyPI, HOME redirected to a scratch directory,
and a local catalog directory holding only this manifest. The archive itself comes
from GitHub over HTTPS, so this is the real published asset.

```
$ python -V
Python 3.14.6
$ farm --version
farm 0.1.7

$ farm install daybreak --yes
Looking up daybreak in the catalog.
Daybreak 0.1.0
A live world-news wall that your Tiiny reads, writes up and keeps.
Made by Jason Brashear. The farm has reviewed it.
Needs: Python 3.11 or newer, port 8811
It can reach your files, the network and your Tiiny.
Downloading 1.9 MB from github.com.
The download matches the checksum the catalog lists.
Unpacking it into .../proof2/home/tiinyapps/daybreak/0.1.0.
Ready. Run: farm start daybreak

$ farm start daybreak --port 7871
Daybreak is running.
Open http://localhost:7871
A live world-news wall that your Tiiny reads, writes up and keeps.
Stop it with: farm stop daybreak

$ curl -s http://localhost:7871/healthz
{"ok":true,"ts":1789386377.75,"db":".../daybreak/data/daybreak.db","version":"0.1.0","device":false}

$ curl -s -o /dev/null -w "GET / -> %{http_code} %{size_download} bytes\n" http://localhost:7871/
GET / -> 200 229743 bytes

$ farm list
Installed:
  daybreak 0.1.0 Daybreak [running] - A live world-news wall that your Tiiny reads, writes up and keeps.
Catalog:
  daybreak 0.1.0 Daybreak - A live world-news wall that your Tiiny reads, writes up and keeps.

$ farm stop daybreak
Stopped daybreak.
```

`"device":false` is the point of that run: there is no Tiiny in a redirected HOME, and
the wall serves anyway. `/api/stats` carries `tiiny.configured false`, and the board
shows an amber `NO TIINY` band and a `NO DEVICE` reading on the device light instead of
six empty gauges that look like a dead Tiiny.

## No device: the queue survives it

One pass of the pipeline with no device configured, on a fresh database:

```
$ python3 pipeline.py --once
no Tiiny configured (no TIINY_HOST/TIINY_KEY and no ~/.tiinyapps/device.json). Fetching will run, enrichment waits
[fetch] new=1073 checked=59 errors=0 in 11.7s
waiting for a Tiiny: set TIINY_HOST and TIINY_KEY, or run farm device. Articles are still being collected and keep their place in the queue.

items 1073   enriched 0   errors 0
```

Zero enrich errors is the measured claim. A failed enrichment stamps `enrich_error`,
and `db.pending_items` skips any row that has one, so running the queue against an
absent device would have burned 1073 articles that never come back.

## Live, against a real Tiiny

The device file on this Mac points at a USB-attached Tiiny, so this leg ran for real.
It holds `Qwen/Qwen3-8B`, `Qwen/Qwen3-Embedding-0.6B`, `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`
and `Tongyi-MAI/Z-Image-Turbo`. No Ornith.

Daybreak resolved the chat model to `Qwen/Qwen3-8B` on its own, brought embeddings up
(`meta.embeddings=on`), held the device lease for one article at a time, and filed a
real NWS flash flood warning with a summary, a severity, a region and a category. 575
tokens on the odometer. One article took about three minutes on that box, which is the
model, not the plumbing.

## What is not proven

* **Sustained enrichment and clustering on a real device.** One article, measured. Not a
  full queue, not a cluster forming, not a developing-story label, not a dossier,
  synthesis, brief, image render or audio episode against live hardware. Those all pass
  device-free in `jobs.py --selfcheck` and none of them ran against the Tiiny here.
* **Classification quality off the rack.** `Qwen3-8B` graded a flash flood warning as
  severity 2, GLOBAL, politics. Ornith-1.0-35B is what the severity rubric and the 0.80
  cluster threshold were measured against; a smaller model will grade differently and
  nothing here re-measured either number.
* **The three excluded modules in the archive.** `audio.py`, `devtherm.py` and `r2.py`
  are left out of the tar.gz, so podcast episodes, device thermals and offsite sync do
  not exist in a farm install. Measured that the wall and pipeline come up without them;
  not measured that anyone minds.
* **The farm's CI workflow on a real pull request.** Both checks were run locally with
  the farm's own scripts. The owner gate (`check_owner`) queries
  `tiinyapp.farm/api/owners` and was not exercised.
* **Windows and Linux.** macOS only.
* **No media.** No icon and no header, per the brief: the orchestrator draws those.

## Two judgement calls worth reviewing

1. **`verified` is `true`.** The brief says so and the other five listings in this branch
   carry it. `docs/SUBMIT.md` says a hand-made submission should leave it `false` for
   maintainer review, and the schema says only a human maintainer sets it in a follow-up
   commit. Flip it if you would rather it go through that way.
2. **`v0.1.0` was published twice.** The first tag and release went out before the live
   device leg, which then found that Daybreak could not enrich anything at all without
   `onelane` installed, which is every farm install. That release was deleted and
   `v0.1.0` re-cut at the fixed commit rather than shipping a known-broken first release
   into the catalog. Nothing referenced it; it existed for about half an hour.
