# tiinyapp.farm

Community apps for the Tiiny AI Pocket Lab. They run on your own computer, beside the device, and
talk to it over its local API. Nothing is installed onto the Tiiny.

One command, `farm`, installs them, starts them, updates them and takes them away again. Browse the
catalog at [tiinyapp.farm](https://tiinyapp.farm).

Brought to you by [Titanium Bot](https://titanium.bot). Made by Titanium Computing.

## Install

Python 3.9 or newer on macOS, Linux or Windows. The tool is one file on the standard library, so
there is nothing else to install.

```sh
pip install tiinyapp-farm
```

If pip answers "externally managed environment", which Homebrew Python and recent Debian both do,
use pipx instead.

```sh
pipx install tiinyapp-farm
```

To work from a checkout instead of the published package:

```sh
git clone https://github.com/Titanium-Devops/tiinyapp-farm.git
cd tiinyapp-farm
python3 -m pip install .
```

## Your first app

```sh
farm device --find               # where is my Tiiny? saves nothing, needs no key
farm device                      # save your Tiiny's address and API key, once
farm install tiiny-brain         # fetch, verify and unpack it
farm start tiiny-brain           # run it and wait for its port
```

The last line of a start that worked is the link to open. `farm stop tiiny-brain` ends it, and
`farm status` says what is running in the meantime.

## Commands

Every command takes an app id: lowercase letters, digits and single dashes, starting with a letter.
`tiiny` is reserved.

### Apps

| Command | What it does | Flags |
| --- | --- | --- |
| `farm install <id>` | Fetches the manifest, shows what the app needs and can reach, asks once, then verifies the checksum and size and unpacks it | `--yes`, `-y`, `--json` |
| `farm update [id]` | Installs a strictly newer version, keeps `data`, restarts a running app on the port it was on. With no id it lists everything newer and asks which to take | `--yes`, `-y`, `--all`, `--json` |
| `farm start [id]` | Runs the app from its version directory, waits up to ten seconds for its ports, and prints the link. With no id it lists what is not running and asks | `--port PORT`, `--python PYTHON`, `--json` |
| `farm stop [id]` | Sends SIGINT to the process group, then SIGKILL after five seconds. With no id it lists what is running and asks | `--json` |
| `farm remove <id>` | Stops the app and deletes everything under its directory except `data` | `--purge` |
| `farm list` | Installed apps with their version and whether each is running, then the whole catalog | `--json` |
| `farm status [id]` | With no id, a row per running app: pid, port, link, uptime, status. With an id, your submission of that app and its checks | `--token TOKEN`, `--json` |
| `farm check` | The same as `farm update` with no id, under the word most people reach for | `--yes`, `-y`, `--all`, `--json` |

`--port N` replaces the app's first declared port and is refused by an app whose manifest says its
port is fixed. `--python PATH` picks the interpreter to run that app with and keeps the choice for
later starts. `--purge` deletes the app's saved data as well. `--all` and `--yes` are what a script
uses where nobody is there to answer a question.

### The device

| Command | What it does | Flags |
| --- | --- | --- |
| `farm device --find` | Looks for a Tiiny on the cable, on this network and at the TiinyOS client, and prints what answered | `--json` |
| `farm device` | Saves the device base URL and API key that every app is launched with | `--base BASE`, `--key-stdin` |
| `farm models` | Says what your Tiiny has loaded, what is on its disk and what the NPU has free | `--load ID`, `--unload ID`, `--force`, `--watch`, `--interval N`, `--json` |

`--find` saves nothing and needs no key. It prints one line per Tiiny with its serial number, the
address to use, how it was reached and the base URL to save, and exits 1 when nothing answered.

```sh
farm device --find
jason's Tiiny (TNYM26072400300011Q) at 172.17.7.177, over the cable, base http://172.17.7.177/v1
```

It looks under the Python the farm runs apps with, because macOS grants the local network per
binary and an app is what you are going to run. A Python that has been refused is told so, with the
settings path that lifts it, and never reported as no Tiiny found. If another Python on the machine
can get through, the farm keeps that one and says so.

With no flags `farm device` runs that search first and offers what it found as the default, then
prompts for both values without echoing, and refuses to run if the terminal cannot hide the input.
With either flag, or with `TIINY_BASE` or `TIINY_KEY` set, it skips the search, takes the scripted
path and fails rather than prompting for what is missing. Explicit flags win over the environment.
Neither value is ever printed back.

```sh
farm device --base http://openai.api.tiiny/v1 --key-stdin < private-key-file
```

### Models

An app declares the kinds of model it cannot work without, and `farm start` checks them before it
launches anything, because an app started without its model runs and then fails at every message.

```sh
farm models                      # what is loaded, what is on disk, what is free
farm models --load Qwen/Qwen3-8B # load one by name, if it fits the free units
farm models --unload Qwen/Qwen3-8B     # and take it out again
farm models --watch              # a line every time one is loaded or unloaded
farm start titanium-tiiny-bot    # refuses and offers to load what is missing
farm start titanium-tiiny-bot --load   # loads it without asking, then starts
```

An unload is held back when a running app needs that model; `--force` does it anyway. A watch stops
on its own when whatever was reading it goes away.

`farm status` and `farm doctor` say when a model an app needs is no longer loaded.
`--no-model-check`, or `FARM_NO_MODEL_CHECK=1`, starts it anyway.

### Health

| Command | What it does | Flags |
| --- | --- | --- |
| `farm doctor` | Checks the whole path from this machine to your Tiiny and says what to do about anything that fails | `--json` |
| `farm self-update` | Moves the farm itself forward and touches nothing else | none |

`farm self-update` runs `pip install --upgrade tiinyapp-farm` with the interpreter the farm is
installed in, or `pipx upgrade tiinyapp-farm` when the farm lives in a pipx virtual environment. No
app is stopped, started, updated or removed by it.

### Makers

| Command | What it does | Flags |
| --- | --- | --- |
| `farm login` | Saves a farm API token to `~/.tiinyapps/token` | `--token-stdin` |
| `farm publish` | Packs the current folder and submits it, which opens a pull request | `--token TOKEN`, `--update` |
| `farm release` | Bumps a listed app from its newest GitHub release | none, or an app id |

A token is `farm_` followed by 40 characters. Create one on
[Your apps](https://tiinyapp.farm/account/). It is shown once.

Run `farm login` once and `publish`, `status` and the rest read the saved token, so you never have
to pass one. `--token` works, but it puts the token in the process list where every other process on
the machine can read it. `FARM_TOKEN` in the environment does the same job without that.

### On every command

| Flag | Meaning |
| --- | --- |
| `-h`, `--help` | The usage and the flags for that command |
| `--version` | The farm version, on `farm` itself |
| `--no-update-check` | Do not look for a newer farm. Accepted before or after the subcommand |

Commands end by saying so, in one line, when the catalog is publishing a newer farm than the one
you are running. That lookup happens at most once a day, gets two seconds, is skipped without a word
when you are offline, and never runs when output is not a terminal. `FARM_NO_UPDATE_CHECK=1` turns
it off for good.

### Answering a machine with --json

Eight commands take `--json`: `install`, `update`, `start`, `stop`, `list`, `status`, `check` and
`doctor`. The command does the same work and answers one JSON object on standard output, with
nothing else on it. Everything a person would have read goes to standard error instead, and the exit
codes do not move.

No `--json` command reads standard input, so none of them can stop and ask a question. `install`
needs `--yes`, `start` and `stop` need an app id rather than offering the chooser, and `check` lists
what is newer without taking any of it unless you add `--all` or `--yes`. A failure answers
`{"error": {"command": ..., "message": ...}}` and exits 1.

```sh
farm install tiiny-brain --json --yes
farm start tiiny-brain --json
farm doctor --json
```

`login`, `publish`, `release`, `remove` and `self-update` have no `--json`, and `device` takes it
only with `--find`. `farm models --watch --json` streams one object per change instead of answering
once.

### Exit codes

| Code | When |
| --- | --- |
| 0 | The command did what it was asked |
| 1 | The command failed, or was cancelled with Ctrl-C |
| 2 | The arguments were wrong |

## What farm doctor checks

```sh
farm doctor
```

Each check is a sentence, with a line beginning `Fix:` under anything that fails. It exits 0 when
everything passes and 1 when anything does not, and prints plain text you can paste to somebody who
can help.

- The farm version, and which Python it runs apps with.
- Whether the catalog is publishing a newer farm than the one you are on.
- The Tiiny on file, whether that Python reaches it, and how long it took.
- Whether the key on file is accepted. That question is asked by the Python that can reach the
  device, and the key is never printed.
- Which other Pythons on this machine reach the Tiiny. On macOS this is usually the answer when one
  Python is being refused the local network.
- Every installed app, the port it declares, and whether that port is free or who is holding it.
- The models your Tiiny lists.

## Environment

What the farm reads:

| Variable | Effect |
| --- | --- |
| `FARM_CATALOG` | Where manifests come from. Defaults to `https://tiinyapp.farm/manifests/`. A local directory or a `file://` directory URL also works |
| `FARM_API_ORIGIN` | The farm's API origin. Defaults to `https://tiinyapp.farm` |
| `FARM_TOKEN` | An API token, used when `--token` is not given |
| `FARM_NO_UPDATE_CHECK` | Set to anything and the farm never looks for a newer farm |
| `TIINY_BASE` | Device base URL for `farm device` in its scripted form |
| `TIINY_KEY` | Device API key for `farm device` in its scripted form |
| `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` | The proxy the farm fetches through, and the hosts it does not |
| `FARM_NO_MODEL_CHECK` | Set to anything and `farm start` never checks the models an app needs |

The farm takes its proxy from those variables and never from macOS System Settings, because asking
the machine corrupts the process it is asked in and everything that process then starts.

What the farm hands an app it starts:

| Variable | Value |
| --- | --- |
| `FARM_DATA_DIR` | `~/tiinyapps/<id>/data` |
| `TIINY_DATA_DIR` | The same directory, under the name Tiiny apps expect |
| `ONELANE_DIR` | `~/tiinyapps/.onelane`, the shared device lock directory |
| `TIINY_BASE` | The device base URL from your saved settings |
| `TIINY_KEY` | The device API key from your saved settings |
| `TIINY_HOST` | The host part of the base URL, bracketed if it is an IPv6 literal |
| `TIINYAPP_PORT` | The port the app was started on, when it declares any |
| `PYTHONUNBUFFERED` | `1`, so output reaches `farm.log` as it happens |

An app whose manifest names an environment variable in its `port` field also gets that variable.

`TIINY_KEY` is the whole key, and every app the farm starts is handed it. That is how an app talks
to your Tiiny at all, and it is what the install prompt means when it says an app can reach your
Tiiny. Installing an app hands it nothing. Starting one does. Read what `farm install` says an app
can reach before you start it, and remember that `verified` stays false until a human has looked.

A local catalog may point at local tar archives by path or `file://` URL. A remote catalog must use
HTTP or HTTPS release URLs, and for `farm list` it must serve either a JSON array of app ids, or
objects with an `id`, or HTML links to the manifest files.

## Where the files are

Your settings live in `~/.tiinyapps`, and the apps live in `~/tiinyapps`.

| Path | What it is |
| --- | --- |
| `~/.tiinyapps/device.json` | The device base URL and API key, written atomically with mode 0600 on macOS and Linux |
| `~/.tiinyapps/token` | Your farm API token |
| `~/.tiinyapps/update-check.json` | When the farm last looked for a newer farm |
| `~/tiinyapps/<id>/<version>/` | The app's code, which it runs from |
| `~/tiinyapps/<id>/current` | A pointer to the installed version, written atomically |
| `~/tiinyapps/<id>/launcher.json` | The entry `farm start` runs |
| `~/tiinyapps/<id>/data/` | The app's own data. Kept by `farm remove`, deleted by `--purge` |
| `~/tiinyapps/<id>/farm.log` | Standard output and errors, appended |
| `~/tiinyapps/<id>/farm.pid` | The process ID of a running app |
| `~/tiinyapps/<id>/process.json` | What it was started with: the ports, the time and the identity |
| `~/tiinyapps/<id>/.run.lock` | Held for as long as the app runs, so a stale PID is never mistaken for a live one |
| `~/tiinyapps/.locks/<id>.lock` | One lock per app id, so two farm commands cannot work on the same app at once |
| `~/tiinyapps/.onelane` | The shared device lock directory, so cooperating apps take turns on the Tiiny |

On Windows permissions are best effort and follow the user folder ACL. Device settings and the
shared lock directory survive app removal.

Archives are tar or tar.gz, bounded to 512 MiB downloaded and 2 GiB unpacked. Traversal, links,
special files and duplicate entries are refused, and the SHA-256 and exact byte size must match
before anything is extracted. These checks do not sandbox installed app code. Permissions describe
what the author declares, and `verified` stays false until CI and a human review.

## For agents

An assistant working on somebody's machine should read these three, in this order.

- [https://tiinyapp.farm/llms.txt](https://tiinyapp.farm/llms.txt) is a short plain-text index of
  everything below.
- [https://tiinyapp.farm/docs/agents/](https://tiinyapp.farm/docs/agents/) is the whole job: finding
  the person's Tiiny, handling their two secrets, installing and running apps for them, publishing
  what they made, and the shape of every `--json` answer.
- [https://tiinyapp.farm/docs/openapi.json](https://tiinyapp.farm/docs/openapi.json) is the HTTP
  surface as OpenAPI 3.1, every route with its authentication, shapes, rate limits and errors.

Two rules worth carrying over. Never put a key or a token on a command line, where every other
process can read it out of the process list. Never tell somebody their app is published before the
pull request is merged.

## Submit an app

Read [the contributor guide](docs/SUBMIT.md) or
[Publish an app](https://tiinyapp.farm/docs/publish/). PR checks validate the changed manifests,
verify archive checksums and sizes, unpack them safely, and scan for unsafe code, undeclared network
access and secret patterns. A declared `"selfcheck": true` runs the entry with `--selfcheck` in an
offline container for at most 120 seconds. Shell and subprocess use is forbidden. Microphone access
is declared, not detected. The checks report one PR comment, and only a maintainer sets
`verified: true`.

`farm publish` does the same from your project folder. It reads `farm.json`, asks for anything it is
missing, packs the folder while skipping `.git`, `node_modules`, `__pycache__` and `.venv`, and
refuses any single file or packed archive over 50 MB.

## Keep a listing current

A listed app is bumped from its own GitHub release, three ways that do the same work:
`.github/workflows/release-poll.yml` hourly, the Check for a new release button on the app's page,
and `farm release` from a shell. Each downloads the release archive, measures its checksum and size
itself, and opens one pull request per app for a maintainer to merge. An open one is refreshed
rather than another opened beside it.

`farm release` uses your own GitHub login through the `gh` command, not a farm token, and opens the
pull request from your fork if you cannot push to the catalog. The engine is `farm/release.py` and
the poller is `scripts/poll-releases.py`. All three open their pull requests with the farm's GitHub
App so the manifest checks run on them. [docs/GITHUB-APP.md](docs/GITHUB-APP.md) has its settings
and the two secret names.

## Publish the farm CLI

Update `project.version` in `pyproject.toml`, then push the matching `v*` tag. The workflow tests,
builds a wheel and a source distribution, smoke-tests `farm`, and publishes through PyPI trusted
publishing with no token secret. A tag alone does not create that trust relationship: a maintainer
configures PyPI's trusted publisher for this repository, workflow `publish.yml` and environment
`pypi` first.

The site workflow builds and tests before deploying a push to main. Pushes that change only `docs/`
skip it, and PR builds still run.

## The repository

- `manifests/` one JSON file per app, which is the whole catalog.
- `farm/` the installer and the release engine.
- `site/` the static catalog, built from the manifests.
- `docs/site/` the documentation the site publishes.
- `.github/workflows/` the checks a submitted manifest must pass.

`SPEC.md` is the contract. Run the tests with `python3 -m unittest`, and validate a manifest without
downloading or running anything:

```sh
python3 scripts/check-manifest.py manifests/tiiny-brain.json
FARM_CATALOG="$PWD/manifests" python3 farm/farm.py list
```

A manifest with a pending release validates with `--allow-pending`, but installing it is refused
until its checksum is set.

## License

MIT. See [LICENSE](LICENSE).
