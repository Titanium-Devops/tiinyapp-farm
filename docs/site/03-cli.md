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
| `--base URL` | The device HTTP or HTTPS base URL. Also read from `TIINY_BASE` |
| `--key-stdin` | Read the API key from standard input instead of prompting. Also read from `TIINY_KEY` |

With no flags and no `TIINY_BASE` or `TIINY_KEY` in the environment it prompts for both without
echoing, and refuses to run if the terminal cannot hide the input. With either flag, or with either
variable set, it takes the scripted path and fails rather than prompting for anything missing.
Explicit flags win over the environment. The result is written atomically to
`~/.tiinyapps/device.json` with mode 0600 on macOS and Linux.

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

`device`, `login`, `publish`, `release`, `remove` and `self-update` have no `--json`.

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
