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

## farm install

```
farm install <id>
farm install <id> --yes
```

| Flag | Meaning |
| --- | --- |
| `--yes`, `-y` | Accept the install prompt without asking |

Fetches `<id>.json` from the catalog, prints the name, version, summary, declared access and
requirements, and asks once. Then it downloads the release, checks the SHA-256 and the exact byte
size, unpacks into a staging directory, and moves the result into
`~/tiinyapps/<id>/<version>` before writing `launcher.json` and `current`. It refuses an app that
is already installed, a release whose checksum is still `pending`, and an app that needs a newer
Python than the interpreter running the command. A manifest larger than 1 MiB is refused, a
download over 512 MiB is refused, and unpacked contents are capped at 2 GiB and 100,000 entries.

## farm update

```
farm update <id>
farm update <id> --yes
```

The same work as `farm install`, with three differences: the new version must be strictly newer
than the installed one or nothing happens, the running app is stopped only after the new archive is
verified and unpacked, and the `data` directory is kept. It does not start the app again.

## farm start

```
farm start <id>
farm start <id> --port 7799
```

| Flag | Meaning |
| --- | --- |
| `--port N` | Replace the app's first declared port. Must be 1 to 65535. Refused by an app whose manifest says its port is fixed |

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

## farm stop

```
farm stop <id>
```

Sends SIGINT to the process group, waits up to five seconds, then sends SIGKILL and waits two more.
On Windows the process is terminated through a handle held across the identity check, so a recycled
process ID cannot be hit by mistake. An app that was not running is reported, not treated as an
error. If the process still will not die, the process records are kept rather than removed.

## farm list

```
farm list
```

Prints installed apps with their version and name, then every app in the catalog with its version
and one-line summary. Catalog entries with no release are marked `[No release yet]` and entries
whose checksum is still pending are marked `[release pending]`.

## farm status

```
farm status
farm status <id>
```

With no argument this is a local command: it prints a header line of `APP PID PORT UPTIME VERSION`
and one row per running app. The version shown is the one the app reports through its health path
when it has one, and a mismatch with the installed manifest is reported as `restart to update`.
Health that cannot be read is labelled rather than guessed.

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

## The environment it reads

| Variable | Effect |
| --- | --- |
| `FARM_CATALOG` | Where manifests come from. Defaults to `https://tiinyapp.farm/manifests/`. A local directory or a `file://` directory URL also works |
| `FARM_API_ORIGIN` | The farm's API origin. Defaults to `https://tiinyapp.farm` |
| `FARM_TOKEN` | An API token, used when `--token` is not given |
| `TIINY_BASE` | Device base URL for `farm device` in its scripted form |
| `TIINY_KEY` | Device API key for `farm device` in its scripted form |

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
