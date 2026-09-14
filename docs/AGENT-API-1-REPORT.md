# AGENT-API-1 report: the farm as something an agent can drive

Worker report against `docs/AGENT-API-1.md`. Everything measured below was measured on Jason's Mac
(Darwin 25.6.0, Apple silicon, Python 3.14.6, node 22.23.1), against the live site and against the
USB-attached Tiiny this Mac already had in `~/.tiinyapps/device.json`. Its key is never printed
here; it went from `/Users/sem/.tiiny_1_api_key` into `farm device --key-stdin` on standard input
and nowhere else.

The branch was rebased onto `origin/main` partway through, because the self-update work landed
there while this was being written. `catalog.json` had changed shape, so the description of it here
is the new one.

## What was built

1. **`--json` on eight commands**: `list`, `status`, `check`, `update`, `install`, `start`, `stop`
   and `doctor`. One JSON object on standard output, the prose on standard error, exit codes
   unchanged. No `--json` path reads standard input.
2. **`/docs/openapi.json`**, built by `scripts/build-site.py` from `worker/openapi.py`: **39 paths,
   41 operations**, OpenAPI 3.1.
3. **The guide** at `docs/site/11-agents.md`, served at `/docs/agents/`, with `/llms.txt` now a
   short plain-text index pointing at it and at the OpenAPI document.

## The route walk, in both directions

`tests/test_openapi.py` reads every comparison `worker/*.mjs` makes against a URL path, whether
that is a string, an array, a prefix or a regular expression, and checks it against the document
both ways. `tests/worker.test.mjs` asks for every documented route through `worker.fetch` and fails
when one falls through to the catch-all or answers a status the document does not list.

Both were made to fail on purpose before being trusted:

```
# an undocumented route added to worker/proof.mjs
FAIL: test_every_route_the_worker_answers_is_in_the_document
      (comparison=('matches', ...), modules=['proof.mjs'])
AssertionError: False is not true : no path in the document is sent here

# a documented path renamed so nothing routes to it
FAIL: test_every_route_the_worker_answers_is_in_the_document
AssertionError: False is not true : no path in the document is sent here
```

The live probe found a real documentation gap on its first run: `POST /api/seeds/<id>/comments`
answers 404 when the app is not in the catalog, because the catalog check runs before the sign-in
check, and the document did not say so. Fixed in `worker/openapi.py` rather than in the test.

## The suites

```
$ python3 -m unittest                  # tests/ in this worktree
Ran 310 tests in 39.949s
OK (skipped=2)

$ node --test tests/worker.test.mjs
# tests 60
# pass 60
# fail 0
```

An external validator is not installed on this machine, so one was put in a scratch virtual
environment rather than reported as absent:

```
$ pip install openapi-spec-validator && python3 -c "...validate(spec)..."
openapi-spec-validator: valid OpenAPI 3.1.0 - 39 paths
```

## The page, in two browsers

`docs/agent-api-shots/` holds the screenshots. Chromium at 1440x900 and WebKit at 390x844, both
through playwright-core, against a local server on port 7862 serving the built site.

| | Chromium 1440x900 | WebKit 390x844 |
| --- | --- | --- |
| Page width against viewport | 1440 / 1440, no overflow | 390 / 390, no overflow |
| Code blocks | 26 | 26 |
| Wider than their box | 11 | 25 |
| Of those, not scrolling inside themselves | 0 | 0 |
| Spilling past the viewport | 0 | 0 |
| On this page contents | present | present |

One block measured on the phone: 358 px wide inside a 390 px viewport, 790 px of content,
`overflow-x: auto`. It scrolls inside itself and the page does not move.

## Every example, run as written

Reads, against the live site and the attached Tiiny:

| Example | Result |
| --- | --- |
| `curl .../device.json` on port 39218 | 200, serial `TNYM26072400300011Q`, and the box lists its own cable and network addresses |
| The discovery script in the guide | Found `jason's Tiiny` at `http://172.17.7.177/v1` over the cable in 1.0 s |
| `curl https://tiinyapp.farm/catalog.json` | 200, `{"cli": "0.1.10", "apps": [7 apps]}` |
| `curl https://tiinyapp.farm/manifests/tiiny-brain.json` | 200 |
| The catalog reader in Python | Printed all seven apps |
| `farm install`, `start --port 7861`, `status`, `stop`, `list`, `check`, `doctor`, all `--json` | Below |

Writes, against a stand-in server on port 7863 that answers the farm's shapes and prints what
arrived, because a real submission would open a pull request on the catalog:

| Example | What the server received |
| --- | --- |
| The `curl` media upload | `POST /api/media`, `image/png`, the bearer header |
| The `curl` submission form | `POST /api/seeds`, `multipart/form-data`, fields `id name pitch description version license tags entry permissions repo archive`, filename `my-app-0.1.0.tar.gz` |
| The `curl` art call | `POST /api/seeds/my-app/art`, `application/json`, the scene |
| The Python `upload()` and the art call | The same two requests |
| `farm publish` with the guide's exact `farm.json` | Four `POST /api/media` (png, webp, png, jpeg) then `POST /api/seeds` carrying `command`, `media`, `homepage`, `repo`, `video` |

The one example not run is the `/v1/chat/completions` call, which reads `TIINY_KEY` out of the
environment the farm hands an app. Running it here would have meant putting that key in an
environment of my own, and the rule for this task was that the key only ever goes into
`farm device --key-stdin`. The same key and the same auth header were exercised by `farm doctor`,
which asks the device for `/v1/models`.

## The transcript

A fresh virtual environment, `pip install .` from this branch, and a scratch `HOME`. `$VENV` and
`$HOME` below stand in for two long scratch paths; nothing else is edited.

```
$ python3 -m venv $VENV && $VENV/bin/pip install . && $VENV/bin/farm --version
farm 0.1.10

$ $VENV/bin/farm device --base http://172.17.7.177/v1 --key-stdin < /Users/sem/.tiiny_1_api_key
Device settings saved.
No app you have installed uses your Tiiny yet. Run: farm list to see what the catalog has.

$ $VENV/bin/farm install tiiny-brain --json -y   # and daybreak, and onelane
{"command": "install", "installed": true, "id": "tiiny-brain", "name": "Tiiny Brain",
 "version": "0.1.1", "path": "$HOME/tiinyapps/tiiny-brain/0.1.1", "library": false,
 "ports": [8500], "permissions": ["files", "network", "device"]}

$ $VENV/bin/farm start tiiny-brain --port 7861 --json
{"command": "start", "id": "tiiny-brain", "already": false, "version": "0.1.1", "running": true,
 "pid": 67772, "ports": [7861], "port": 7861, "url": "http://localhost:7861",
 "log": "$HOME/tiinyapps/tiiny-brain/farm.log"}

$ $VENV/bin/farm status --json
{"command": "status", "running": [{"id": "tiiny-brain", "pid": 67772, "ports": [7861],
 "port": 7861, "url": "http://localhost:7861", "uptime": 5, "version": "0.1.1",
 "installed": "0.1.1", "restartToUpdate": false, "health": null, "updateAvailable": null}]}

$ $VENV/bin/farm stop tiiny-brain --json
{"command": "stop", "id": "tiiny-brain", "stopped": true}
$ $VENV/bin/farm stop tiiny-brain --json      # again, and it is not an error
{"command": "stop", "id": "tiiny-brain", "stopped": false}

$ $VENV/bin/farm start --json                  # no id, and nobody to ask
{"error": {"command": "start",
           "message": "Run: farm start <id>, naming one of daybreak and tiiny-brain."}}
exit 1

$ $VENV/bin/farm install onelane --json        # no --yes, and nobody to ask
{"error": {"command": "install", "id": "onelane",
           "message": "Add --yes: with --json the farm never asks you to confirm an install."}}
exit 1

$ $VENV/bin/farm check --json
{"command": "check", "updates": [], "unreachable": [], "updated": []}
```

`check` is empty because all three installed apps are the newest the live catalog has. The
non-empty shape is pinned by `tests/test_farm.py` against a local catalog instead.

`farm doctor --json`, with the JSON on standard output and the prose on standard error. It exits 1,
because something on this Mac really is holding port 8500:

```
$ $VENV/bin/farm doctor --json > doctor.json 2> doctor.txt ; echo $?
1

$ cat doctor.txt
farm 0.1.10, running apps with $VENV/bin/python3.14 (Python 3.14.6).
The Tiiny on file is at http://172.17.7.177/v1.
Your Tiiny at 172.17.7.177 answered this Python in 13 ms.
The key on file is accepted by your Tiiny.
Other Pythons here: /usr/bin/python3 reaches it, /opt/homebrew/bin/python3.12 does not and /opt/homebrew/bin/python3.13 does not.
daybreak declares port 8811, and it is free.
onelane is a library, so it has no port and nothing to start.
tiiny-brain declares port 8500, and something else is holding it.
Fix: stop whatever has it, or put the app somewhere else: farm start tiiny-brain --port N.
Your Tiiny lists 4 models: Qwen/Qwen3-8B, Qwen/Qwen3-Embedding-0.6B, Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice and Tongyi-MAI/Z-Image-Turbo.
Something above needs attention, and each Fix line says what to do.

$ cat doctor.json
{
  "command": "doctor",
  "ok": false,
  "farm": "0.1.10",
  "findings": [
    {
      "check": "farm",
      "ok": true,
      "message": "farm 0.1.10, running apps with $VENV/bin/python3.14 (Python 3.14.6).",
      "fix": null,
      "farm": "0.1.10",
      "python": "$VENV/bin/python3.14"
    },
    {
      "check": "settings",
      "ok": true,
      "message": "The Tiiny on file is at http://172.17.7.177/v1.",
      "fix": null,
      "base": "http://172.17.7.177/v1"
    },
    {
      "check": "device",
      "ok": true,
      "message": "Your Tiiny at 172.17.7.177 answered this Python in 13 ms.",
      "fix": null,
      "address": "172.17.7.177",
      "milliseconds": 13
    },
    {
      "check": "key",
      "ok": true,
      "message": "The key on file is accepted by your Tiiny.",
      "fix": null
    },
    {
      "check": "pythons",
      "ok": true,
      "message": "Other Pythons here: /usr/bin/python3 reaches it, /opt/homebrew/bin/python3.12 does not and /opt/homebrew/bin/python3.13 does not.",
      "fix": null,
      "pythons": [
        {"path": "/usr/bin/python3", "reaches": true},
        {"path": "/opt/homebrew/bin/python3.12", "reaches": false},
        {"path": "/opt/homebrew/bin/python3.13", "reaches": false}
      ]
    },
    {
      "check": "port",
      "ok": true,
      "message": "daybreak declares port 8811, and it is free.",
      "fix": null,
      "id": "daybreak",
      "port": 8811
    },
    {
      "check": "app",
      "ok": true,
      "message": "onelane is a library, so it has no port and nothing to start.",
      "fix": null,
      "id": "onelane"
    },
    {
      "check": "port",
      "ok": false,
      "message": "tiiny-brain declares port 8500, and something else is holding it.",
      "fix": "stop whatever has it, or put the app somewhere else: farm start tiiny-brain --port N.",
      "id": "tiiny-brain",
      "port": 8500
    },
    {
      "check": "models",
      "ok": true,
      "message": "Your Tiiny lists 4 models: Qwen/Qwen3-8B, Qwen/Qwen3-Embedding-0.6B, Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice and Tongyi-MAI/Z-Image-Turbo.",
      "fix": null,
      "models": ["Qwen/Qwen3-8B", "Qwen/Qwen3-Embedding-0.6B",
                 "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", "Tongyi-MAI/Z-Image-Turbo"]
    }
  ]
}
```

Every message in the JSON is a line in the prose, and every `fix` is the `Fix:` line under it. The
test suite asserts exactly that rather than trusting it.

## For the next Titanium Bot skill

Titan's web tool should fetch **`https://tiinyapp.farm/llms.txt`** first. It is plain text, under
4 KB, and names the two documents worth reading next: `/docs/agents/` for the whole path in prose
and `/docs/openapi.json` for the machine-readable surface. That is the whole skill.

## What was left alone

* `device`, `login`, `publish`, `release`, `remove` and `self-update` have no `--json`. The brief
  named eight commands and those six are not among them. `publish` already prints the two URLs a
  person needs, and `device` prints nothing worth parsing.
* `/docs/openapi.json` answers 404 on the live site until this merges and deploys. Every other
  read example above was run against the live site as it stands today.
* The self-update work is main's, not this branch's. The guide mentions `farm self-update` in one
  line, in the doctor findings table, and nowhere else.
