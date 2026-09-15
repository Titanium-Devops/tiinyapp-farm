---
title: CLI reference
slug: cli
order: 3
summary: Every farm command, every flag, the environment it reads, the environment it hands an app, and its exit codes.
---

The `tiinyapp-farm` package installs one command, `farm`. It is a single Python file on the
standard library and it runs on macOS, Linux and Windows with Python 3.9 or newer.

```
farm --version
```

Each command below takes an app id: lowercase letters, digits and single dashes, starting with a
letter. `tiiny` is reserved and is refused as an id.

## farm device

Save the device base URL and API key that every app is launched with.

| Flag | Meaning |
| --- | --- |
| `--find` | Look for a Tiiny and print what answered. Saves nothing and needs no key |
| `--base URL` | The device HTTP or HTTPS base URL. Also read from `TIINY_BASE` |
| `--key-stdin` | Read the API key from standard input instead of prompting. Also read from `TIINY_KEY` |
| `--json` | With `--find` only. One JSON object of what answered |

With no flags and no `TIINY_BASE` or `TIINY_KEY` in the environment it looks for a Tiiny first, then
prompts for both values without echoing, and refuses to run if the terminal cannot hide the input.
One Tiiny found is offered as the default, so pressing enter takes it:

```
Found jason's Tiiny (TNYM26072400300011Q) at 172.17.7.177, over the cable, base http://172.17.7.177/v1
Device base URL [http://172.17.7.177/v1] (hidden):
Device API key (hidden):
```

Several found are numbered and it asks which. Nothing found is the prompt as it always was. With
either flag, or with either variable set, it takes the scripted path, skips the search, and fails
rather than prompting for anything missing. Explicit flags win over the environment. The result is
written atomically to `~/.tiinyapps/device.json` with mode 0600 on macOS and Linux.

## farm device --find

```
farm device --find
farm device --find --json
```

Where the Tiinys are, before anybody has typed an address. It saves nothing, and it never reads or
asks for a key, because none of the three ways it looks needs one. Looking and saving are separate
jobs, so `--find` with `--base` or `--key-stdin` is refused rather than quietly doing one of them.

| Looked at | What it is |
| --- | --- |
| Every USB cable in this machine | A cable is a point to point /30 inside `172.17`, the box on the first usable address and this machine on the second. `bind` says which ones are ours, and arithmetic gives the box's side |
| This network | One datagram, `GADGET_DISCOVER_V1` to UDP 39217, broadcast and to each cable. A Tiiny sends back the whole of its `device.json`, so this finds one whose address has moved |
| The TiinyOS client | `http://openai.api.tiiny/v1`, asked only when the first two found nothing, because the box it serves is the box on the cable |

One line per Tiiny: its name and serial number, the address to use, how it was reached, and the base
URL `farm device` would save.

```
jason's Tiiny (TNYM26072400300011Q) at 172.17.7.177, over the cable, base http://172.17.7.177/v1
Run farm device to save it. It offers this address and asks for the key.
```

One box that answers on the cable and on the network is one line, not two: the serial number in
`device.json` is what says how many Tiinys are really there, and the cable is offered first because
a /30 never moves and a network address does.

The whole search is capped at six seconds and every socket in it carries a timeout, so a filtered
port cannot hang it. Measured at 0.9 seconds on an M-series Mac with one Tiiny on the cable.

### Which Python does the looking

macOS grants the local network per binary, and grants it silently, so the same code finds a Tiiny
under one Python and gets no route at all under another. The farm therefore does the looking under
the Python it runs apps with, not under the one running the CLI, because an app is what you are
going to run. When that one is refused, the farm asks the other Pythons on this machine, exactly as
a failed `farm start` does, and keeps the first that gets through.

Under the launcher this is the bundled Python and the permission belongs to the app bundle, so the
same path needs nothing special there.

### The three answers

| It says | What happened |
| --- | --- |
| One line per Tiiny | Found. `farm device` will offer the first one |
| `No Tiiny answered.` and what was tried | Nothing is there. Exit 1 |
| `... was refused your local network`, and the Local Network settings path | macOS is blocking that Python. Never reported as no Tiiny found, because it is not the same thing |

A refused Python that another Python could get past says which one found it, and that the farm has
saved it and will run apps with it from now on.

```
jason's Tiiny (TNYM26072400300011Q) at 172.17.7.177, over the cable, base http://172.17.7.177/v1
/opt/homebrew/bin/python3 found it. The Python the farm was using cannot reach your local network, so the farm will run apps with that one from now on, and has saved it.
```

`--json` answers `{"command": "device", "ok": ..., "blocked": ..., "python": ..., "moved": ...,
"found": [...]}`, one `found` entry per Tiiny with its `serial`, `name`, `address`, `via`, `base`
and the `interfaces` its `device.json` lists. `blocked` is true when macOS refused the local
network, `python` is the interpreter whose answer this is, and `moved` is the one the farm changed
to and saved, or null. `ok` is false and the exit code 1 when nothing answered.

After saving it names the installed apps these settings reach, which is every installed app that
declares the `device` permission or asks for device models, and offers one `farm start` command to
try them with. Neither value is ever printed back.

## farm install

```
farm install <id>
farm install <id> --yes
```

| Flag | Meaning |
| --- | --- |
| `--yes`, `-y` | Accept the install prompt without asking |

Fetches `<id>.json` from the catalog and says what it is about to install: the name and version,
the one-line summary, who made it and whether the farm has reviewed it, what it needs, and what it
can reach. Then it asks once, and prints one line per step as it happens, naming the download size,
the checksum result and where the files land. The last line is the command to run next, or for a
library the file to copy or import. Under the printing it downloads the release, checks the SHA-256
and the exact byte size, unpacks into a staging directory, and moves the result into
`~/tiinyapps/<id>/<version>` before writing `launcher.json` and `current`. It refuses an app that
is already installed, a release whose checksum is still `pending`, and an app that needs a newer
Python than the interpreter running the command. A manifest larger than 1 MiB is refused, a
download over 512 MiB is refused, and unpacked contents are capped at 2 GiB and 100,000 entries.

## farm update

```
farm update
farm update <id>
farm update <id> --yes
farm update --all
```

| Flag | Meaning |
| --- | --- |
| `--yes`, `-y` | Take the update without asking. With no id, take every one of them |
| `--all` | Take every app with a newer version without asking |

With no id it asks the catalog about every app you have installed and numbers the ones with a newer
version, each with the release's one-line note when the catalog carries one and the day the entry
changed when it does not. Then it asks once:

```
Looking up all 2 apps you have installed in the catalog.
1. AINode Pocket 0.0.9, 0.1.0 is out, dated 2026-09-14.
2. Tiiny Brain 0.1.0, 0.1.1 is out, dated 2026-09-14.
Update which? A number, "all", or Enter to leave them.
```

A number takes that one, `all` takes each in order, and Enter leaves them. With nothing newer it
says so in one line and asks nothing. Run from a script, where nothing is a terminal, it prints the
list and updates nothing; `--all` or `--yes` takes every one of them without asking. An app whose
catalog entry cannot be read is named rather than silently skipped.

With an id it asks about that app alone and the answer defaults to yes:

```
AINode Pocket 0.1.0 is installed and 0.1.1 is out. Update it? [Y/n]
```

Then it does the same work as `farm install` and says the same things, with four differences: the
new version must be strictly newer than the installed one or nothing happens, the running app is
stopped only after the new archive is verified and unpacked, the `data` directory is kept and said
to be kept, and a running app is started again on the port it was really on. An app that is already
the newest the catalog has says so in one line.

## farm check

```
farm check
farm check --all
```

The same command as `farm update` with no id, under the word most people reach for.

## farm start

```
farm start
farm start <id>
farm start <id> --port 7799
```

| Flag | Meaning |
| --- | --- |
| `--port N` | Replace the app's first declared port. Must be 1 to 65535. Refused by an app whose manifest says its port is fixed |
| `--python PATH` | Run this app with this Python, and keep it for later starts on this machine |
| `--load` | Load whatever model the app needs without asking first |
| `--no-model-check` | Start even if the models the app needs are not loaded (or set `FARM_NO_MODEL_CHECK=1`) |

### The models an app needs

Before anything is launched, `farm start` checks what the manifest declares in
`requires.device.models` against what your Tiiny has loaded. An app that needs a chat model and is
started without one starts perfectly well and then answers every message with an error, which reads
as a broken app rather than an empty NPU, so the farm refuses instead and says what is missing:

```
Titanium Tiiny Bot needs chat on your Tiiny, and what is loaded is embedding Qwen/Qwen3-Embedding-0.6B 1 unit and tts Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice 7 units.
Load Qwen/Qwen3-8B for chat now? [Y/n]
```

Each kind is met by any loaded model of that kind. A need with a slash in it is an exact model id
and is met by that model only. A manifest may also declare `requires.device.prefers`, the kinds an
app is better with and works without. Those never stop a start; they get one line as the app
starts, and appear as a hint in `farm status` and `farm doctor`:

```
Daybreak works better with embedding, image and rerank models loaded, and is starting without them.
```
 The offer picks the cheapest downloaded model of that kind that fits
what the NPU has free, numbers them when there are several, and says so rather than offering one
when nothing of that kind is downloaded or nothing fits. Loading waits for your Tiiny to say the
model is running before the app starts, for as long as the device's own estimate for that model
suggests.

`--load` says yes to all of it without asking, and works the same for a machine: `--json --load`
loads what is missing and then starts the app, and the answer carries `loaded` with the model ids
it had to load. `--json` on its own never asks and never loads, and answers with what is missing
instead:

```json
{"command": "start", "id": "titanium-tiiny-bot", "ok": false, "started": false,
 "prefers": [{"kind": "embedding", "loaded": true}],
 "missing": [{"kind": "chat", "loaded": [], "available": ["Qwen/Qwen3-8B", "openai/gpt-oss-20b"]}]}
```

With no id it numbers the installed apps that are not running and could be, then asks the same
question `farm update` asks:

```
2 installed apps are ready to start.
1. TiinyBench 0.1.1
2. Tiiny Brain 0.1.1
Start which? A number, "all", or Enter to leave them.
```

Exactly one candidate is a plain `Start TiinyBench? [Y/n]` rather than a list of one, and the answer
defaults to yes. A library is never on the list, because it has nothing to start, and neither is an
app that is already running. With nothing left to start it says which of those is the reason in one
line. Run from a script, where nothing is a terminal, it prints the list and names the ids to run by
hand. A port belongs to one app, so `--port` with no id is refused.

A start that worked ends with the link to open on its own line, the one-line summary, how to stop
it, and the log path last:

```
AINode Pocket is running.
Port 8430 was busy, so it started on 8431.
Open http://localhost:8431
One endpoint and one page for every Tiiny you own.
Stop it with: farm stop ainode-pocket
Log: /Users/you/tiinyapps/ainode-pocket/farm.log
```

A newer version in the catalog adds one line under the link, `Version 0.1.1 is out. Run: farm update
<id>`. The link is `http://localhost:<port>` on the port the app really took, and the path is the
root unless the manifest's `open` field names a first page. A `health` path is a probe, not a page, and
is never used as the link. The process ID is not in that block; `farm status` has it.

Runs the entry from the version directory with no shell involved. A Python entry becomes
`<interpreter> -m <module> <args>`; a command entry is split into arguments the way a shell would
split them, and a leading `python` or `python3` is replaced with the interpreter running `farm`.
Any declared port that is already listening stops the start with the port message. Readiness is
then waited for, up to ten seconds: the first port is checked with the manifest's health path if it
has one, and every other port with a TCP connection. Failure prints the last ten lines of
`farm.log`, removes the process records, and exits 1.

The chosen port is exported as `TIINYAPP_PORT`, and the manifest's `port` field says how that app
takes it: a flag on its command line, a different environment variable, or nothing at all when its
port is fixed. An app with a fixed port refuses `--port` in one line naming the port it runs on,
and a busy port on such an app is not answered with advice that cannot work.

Before it launches anything, when a Tiiny is on file, it asks the device for its page from the Python
the app would run under. If macOS is refusing that Python the local network, the farm tries the other
Pythons on this machine, runs the app with the first one that reaches your Tiiny, says so in one
line, and saves that choice for later starts. `--python PATH` makes the choice yourself and is never
second guessed. None of this ever fails a start.

## farm self-update

```
farm self-update
```

Moves the farm itself forward and touches nothing else. No app is stopped, started, updated or
removed by it. In a normal installation it runs `pip install --upgrade tiinyapp-farm` with the
interpreter the farm is installed in; when the farm lives in a pipx virtual environment it runs
`pipx upgrade tiinyapp-farm` instead, because pip inside one of those is not how pipx expects to be
moved. It prints the last line of what pip or pipx said, then the version you are on now.

## farm doctor

```
farm doctor
```

Checks the things a person would otherwise have to ask somebody else about, each as a sentence, with
a line beginning `Fix:` under anything that fails:

- the farm version and which Python it runs apps with
- the Tiiny on file, whether that Python reaches it and how long it took
- whether the key on file is accepted, asked by the Python that can reach the device, never printed
- which other Pythons on this machine reach the Tiiny
- every installed app, the port it declares, and whether it is free or who is holding it
- the models your Tiiny lists

It exits 0 when everything passes and 1 when anything does not, and prints plain text you can paste
to somebody who can help.

## farm stop

```
farm stop
farm stop <id>
```

With no id it numbers the running apps with the port each one took, then asks:

```
2 apps are running.
1. AINode Pocket 0.1.0 on port 7863
2. TiinyBench 0.1.1 on port 7864
Stop which? A number, "all", or Enter to leave them.
```

Exactly one running app is a plain `Stop AINode Pocket? [Y/n]`, and nothing running says so in one
line. A script gets the list and the ids to run by hand, and stops nothing.

With an id it sends SIGINT to the process group, waits up to five seconds, then sends SIGKILL and waits two more.
On Windows the process is terminated through a handle held across the identity check, so a recycled
process ID cannot be hit by mistake. An app that was not running is reported, not treated as an
error. If the process still will not die, the process records are kept rather than removed.

## farm models

```
farm models
farm models --json
farm models --watch
```

What your Tiiny has loaded right now, what it has on disk, and what is left of the NPU:

```
Your Tiiny has 4 models loaded, using 68 of 100 NPU units.
  chat Qwen/Qwen3-8B 28 units running
  embedding Qwen/Qwen3-Embedding-0.6B 1 unit running
  image Tongyi-MAI/Z-Image-Turbo 32 units running
  tts Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice 7 units running
16 more models are downloaded and not loaded:
  chat openai/gpt-oss-20b 32 units
32 NPU units are free.
```

The kind is the device's own capability for that model, in the farm's word for it. Your Tiiny says
`main`, `voice` and `audio`; a manifest and this list say `chat`, `tts` and `asr`. The other five,
`embedding`, `rerank`, `image`, `ocr` and `music`, are the same word on both sides. NPU units are
memory residency rather than a compute reservation, so several models are resident at once and the
free figure is what says whether another one fits.

| Flag | Meaning |
| --- | --- |
| `--load ID` | Load one model on your Tiiny, by name |
| `--unload ID` | Unload one model on your Tiiny, by name |
| `--force` | Unload one a running app needs |
| `--watch` | Keep looking, and print a line whenever a model changes state. Ctrl-C to stop |
| `--interval N` | Seconds between looks with `--watch`. Default 3 |
| `--json` | One JSON object of the lot, or with `--watch` one object per change |

### Loading and unloading one model

```
farm models --load Qwen/Qwen3-8B
farm models --unload Qwen/Qwen3-8B
```

A load that will not fit what the NPU has free is refused with the number, and nothing is asked of
the device:

```
Qwen/Qwen3-30B-A3B-Instruct needs 55 units and your Tiiny has 32 units free, 23 short. Unload something first: farm models --unload <id>
```

A load waits for your Tiiny to say the model is running before it answers, for as long as the
device's own estimate for that model suggests. A model that is already loaded, or an unload of one
that is not, says so and asks the device for nothing.

An unload is held back when a running installed app declares it needs that model and nothing else
loaded would meet the need:

```
titanium-tiiny-bot is running and needs Qwen/Qwen3-8B. Stop it first, or unload anyway with: farm models --unload Qwen/Qwen3-8B --force
```

A second model of the same kind being loaded means the need is met either way, so nothing is held
back. With `--json`, both flags answer with the state they left, in the same shape as `farm models
--json`.

```
16:33:55 Qwen/Qwen3-TTS-12Hz-1.7B-Base is loaded for tts, 5 units, 73 of 100 NPU units in use.
16:33:59 Qwen/Qwen3-TTS-12Hz-1.7B-Base for tts is not loaded any more, 68 of 100 NPU units in use.
```

A watch stops on its own when whatever was reading it goes away, so a launcher that is killed
rather than quit does not leave one polling for ever. On POSIX the pipe says so as soon as the
reader closes; on Windows the watch stops at its next write instead.

`--watch --json` writes one object per change to standard output as it happens, which is what a
launcher reads:

```json
{"command": "models", "event": "loaded", "id": "Qwen/Qwen3-8B", "kind": "chat",
 "capability": "main", "units": 28, "state": "running",
 "npu": {"total": 100, "used": 96, "available": 4}, "at": 1789421728}
```

`event` is `loaded`, `unloaded` or `changed`.

## farm list

```
farm list
```

Prints installed apps with their id, version, name, whether each one is `[running]` or `[stopped]`,
and its one-line summary, then every app in the catalog with its version, name and summary. An
installed app the catalog has a newer version of carries it in the same brackets, as
`[stopped, update available: 0.1.0]`. Catalog entries with no release are marked `[No release yet]`
and entries whose checksum is still pending are marked `[release pending]`.

## farm status

```
farm status
farm status <id>
```

With no argument this is a local command: it prints a header line of
`APP PID PORT LINK UPTIME STATUS` and one row per running app. The link is the one `farm start`
offered, on the port the app really took. The version shown is the one the app reports through its
health path when it has one, and a mismatch with the installed version is reported as
`restart to update`. A row whose app has a newer version in the catalog ends with
`update available: 0.1.0`. Health that cannot be read is labelled rather than guessed.

An app that declares it needs a model gets a second line whenever your Tiiny does not have that
model loaded now, naming the one that was loaded when the app started if there was one:

```
titanium-tiiny-bot 55663 7788 http://localhost:7788 10s running 0.1.15
  titanium-tiiny-bot is missing chat (Qwen/Qwen3-8B) was loaded when it started and is not now, first noticed just now.
```

The farm writes down when it first saw the need go unmet, because your Tiiny cannot say when a
model was unloaded and the thing worth knowing is whether it happened before or after the app
stopped working. `--json` carries the same under `models`, as `needs`, `unmet`, `lost` and `since`,
with `prefers` beside them for the kinds the app is merely better with. `farm doctor` reports the
same thing for every installed app, running or not, and a preference there is a passing line rather
than something to fix.

With an app id it is a remote command instead: it asks the farm about your own submission of that
app and prints its state, each check with its status, and each review. It needs an API token.

| Flag | Meaning |
| --- | --- |
| `--token TOKEN` | Use this API token. Otherwise `FARM_TOKEN`, otherwise `~/.tiinyapps/token` |

## farm remove

```
farm remove <id>
farm remove <id> --purge
```

| Flag | Meaning |
| --- | --- |
| `--purge` | Delete the app's `data` directory as well |

Stops the app, then deletes everything under `~/tiinyapps/<id>/` except `data`, unless `--purge` is
given. Device settings and the shared lock directory are never touched.

## farm login

```
farm login
printf '%s' "$FARM_TOKEN" | farm login --token-stdin
```

| Flag | Meaning |
| --- | --- |
| `--token-stdin` | Read the token from the first line of standard input |

Prompts without echo, or reads one line, then saves the token to `~/.tiinyapps/token`. The token
must be `farm_` followed by 40 characters or it is refused with a description of what it saw, never
the token itself. Create one on [Your apps](/account/).

## farm publish

```
farm publish
farm publish --update
```

| Flag | Meaning |
| --- | --- |
| `--token TOKEN` | Use this API token instead of `FARM_TOKEN` or `~/.tiinyapps/token` |
| `--update` | Update an app you have already published rather than submitting a new one |

Run from the project folder. It reads `farm.json` if there is one, asks for any required value it
is missing, packs the folder into `<id>-<version>.tar.gz` while skipping `.git`, `node_modules`,
`__pycache__` and `.venv`, uploads any local images, and submits the archive. It refuses any single
file over 50 MB and a packed archive over 50 MB. It prints the pull request URL and a link to Your
apps. See [Publish an app](/docs/publish/) for the whole path and the `farm.json` shape.

## farm release

```
farm release
farm release <id>
```

Run after tagging and publishing a GitHub release. With no argument it reads the app id from
`farm.json` in the current directory. It asks GitHub for the newest full release of the repository
named in your catalog manifest, downloads that archive, measures its SHA-256 and exact size itself,
and opens a pull request that moves `version`, `release.url`, `release.sha256`, `release.size` and
`updatedAt`. It prints the pull request URL.

This command uses your own GitHub login through the `gh` command, not a farm token, and opens the
pull request from your fork if you cannot push to the catalog. There is one pull request per app:
an open one is refreshed rather than another opened beside it.

## When the farm itself is out of date

Every command ends by telling you, in one line, when the catalog is publishing a newer farm than the
one you are running:

```
farm 0.1.10 is out and you are on 0.1.9. Run: farm self-update
```

The version comes from `/catalog.json` on the site, which the build writes from the package version,
so nothing here asks PyPI anything at runtime. It is looked up at most once a day, remembered in
`~/.tiinyapps/update-check.json`, given two seconds before it gives up, and skipped without a word
when you are offline. It never runs before the work you asked for, never after a command that
failed, and never when output is not a terminal, so scripts never see it. `--no-update-check` on any
command, or `FARM_NO_UPDATE_CHECK=1` in the environment, turns it off, and `farm doctor` reports the
same thing among its checks.

## Answering a machine with --json

Eight commands take `--json`: `list`, `status`, `check`, `update`, `install`, `start`, `stop` and
`doctor`. The command does the same work and answers one JSON object on standard output, with
nothing else on it. Everything it would have printed goes to standard error instead, and the exit
codes do not move.

```
farm install tiiny-brain --json -y
farm start tiiny-brain --json
farm doctor --json
```

No `--json` command reads standard input, so none of them can stop and ask a question. `install`
needs `--yes`, `start` and `stop` need an app id rather than offering the chooser, and `check` lists
what is newer without taking any of it unless you add `--all` or `--yes`. A failure answers
`{"error": {"command": ..., "message": ...}}` carrying the same sentence you would have read, and
exits 1. The line about a newer farm is left off a `--json` answer, and `farm doctor --json` carries
it among its findings instead.

`login`, `publish`, `release`, `remove` and `self-update` have no `--json`, and `device` takes it
only with `--find`.

Every shape is documented, with an example of each, in
[The farm for AI assistants](/docs/agents/).

## The environment it reads

| Variable | Effect |
| --- | --- |
| `FARM_CATALOG` | Where manifests come from. Defaults to `https://tiinyapp.farm/manifests/`. A local directory or a `file://` directory URL also works |
| `FARM_API_ORIGIN` | The farm's API origin. Defaults to `https://tiinyapp.farm` |
| `FARM_TOKEN` | An API token, used when `--token` is not given |
| `TIINY_BASE` | Device base URL for `farm device` in its scripted form |
| `TIINY_KEY` | Device API key for `farm device` in its scripted form |
| `FARM_NO_UPDATE_CHECK` | Set to anything and the farm never looks for a newer farm |
| `FARM_NO_MODEL_CHECK` | Set to anything and `farm start` never checks the models an app needs |
| `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` | The proxy the farm fetches through, and the hosts it does not. Lowercase spellings work too |

The farm reads its proxy from those variables only, and never from macOS System Settings. Asking
the machine where its proxy is corrupts the process it is asked in: after that lookup and any name
lookup, everything this process starts, an app included, is killed before it can run. If your proxy
lives in System Settings and nowhere else, put it in `HTTPS_PROXY` as well.

A local catalog may point at local tar archives by path or `file://` URL. A remote catalog must use
HTTP or HTTPS release URLs, and for `farm list` it must serve either a JSON array of app ids, or
objects with an `id`, or HTML links to the manifest files.

## The environment it gives an app

| Variable | Value |
| --- | --- |
| `FARM_DATA_DIR` | `~/tiinyapps/<id>/data` |
| `TIINY_DATA_DIR` | The same directory, under the name Tiiny apps expect |
| `ONELANE_DIR` | `~/tiinyapps/.onelane`, the shared device lock directory |
| `TIINY_BASE` | The device base URL from your saved settings |
| `TIINY_KEY` | The device API key from your saved settings |
| `TIINY_HOST` | The host part of the base URL, bracketed if it is an IPv6 literal |
| `TIINYAPP_PORT` | The port the app was started on, when it declares any |
| `PYTHONUNBUFFERED` | Set to `1`, so output reaches `farm.log` as it happens |

An app whose manifest names an environment variable in its `port` field also gets that variable,
which is how Story Lantern gets `PORT`. Story Lantern additionally gets `LANTERN_HOME`,
`LANTERN_DB`, `LANTERN_SAFETY_JSONL` and `LANTERN_BLOCKLIST`, which are data paths.

## Exit codes

| Code | When |
| --- | --- |
| 0 | The command did what it was asked |
| 1 | The command failed. The reason is printed to standard error as `farm: <reason>` |
| 1 | The command was cancelled with Ctrl-C or end of input. It prints `Cancelled.` |
| 2 | The arguments were wrong. Argparse prints the usage and the problem |

Network and JSON errors are never interpolated into the message, because they can carry
credentials. An unexpected error prints its type and a pointer to the catalog, the app files or the
device settings instead of its text.
