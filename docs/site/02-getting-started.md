---
title: Getting started
slug: getting-started
order: 2
summary: Install the farm command, point it at your Tiiny, then install, start, update and remove apps.
---

An app from the catalog runs on your computer, not on the Tiiny. It reaches the device over the
device's own local API, so the Tiiny has to be switched on and reachable from the machine you are
working at. Nothing here changes TiinyOS.

## Install the command

You need Python 3.9 or newer on macOS, Linux or Windows. The tool itself uses only the Python
standard library, so there is nothing else to install.

```
pip install tiinyapp-farm
farm --version
```

If pip answers "externally managed environment", which Homebrew Python and recent Debian both do,
use pipx instead.

```
pipx install tiinyapp-farm
```

To work from a checkout of the catalog repository rather than the published package:

```
git clone https://github.com/Titanium-Devops/tiinyapp-farm.git
cd tiinyapp-farm
python3 -m pip install .
```

## Find your Tiiny

The command needs two things once: the base URL of the device's API and its API key.

| Value | What to use |
| --- | --- |
| API base URL, on a Mac with the TiinyOS client installed | `http://openai.api.tiiny/v1` |
| API base URL, from any other computer on the same network | `http://<your-tiiny-ip>/v1` |
| API key | TiinyOS, then Settings, then API Key |

The base URL has to be an HTTP or HTTPS URL with no username, password, query or fragment in it.
Anything else is refused.

## Connect it

```
farm device
```

It asks for both values without echoing them and writes `~/.tiinyapps/device.json` with mode 0600
on macOS and Linux. On Windows the file follows the user folder's ACL, which is best effort. If
there is no terminal that can hide what you type, it refuses rather than falling back to echoed
input. Run it again at any time to change either value.

For a script, pass the base URL and pipe the key in, or put both in the environment:

```
farm device --base http://openai.api.tiiny/v1 --key-stdin < private-key-file
TIINY_BASE=http://openai.api.tiiny/v1 TIINY_KEY=... farm device
```

Explicit options win over the environment, and incomplete scripted input fails instead of falling
back to a prompt. The key never has to appear in a command argument, and the command never prints
it back.

After saving, it asks your Tiiny for its device page once. If macOS is blocking that Python from the
local network, which it does silently for a Python you installed yourself, it tells you to turn it on
in System Settings, Privacy and Security, Local Network. See
[The app cannot see my Tiiny](/docs/troubleshooting/) if an app starts but reaches nothing.

## Install an app

Browse the [catalog](/catalog/), then install by the app's id.

```
farm install titanium-tiiny-bot
```

Before anything is downloaded it tells you what it is about to install, then asks once. Answer `y`
to go ahead. In a script, `-y` prints the same lines and answers the prompt for you.

```
Looking up titanium-tiiny-bot in the catalog.
Titanium Tiiny Bot 0.1.15
A local assistant with chat, files, memories and voice.
Made by Titanium Computing. The farm has reviewed it.
Needs: Python 3.11 or newer, port 7788, your Tiiny, for chat, tts, 57 NPU units
It can reach your microphone, your files, the network and your Tiiny.
Install this release? [y/N] y
Downloading 456 KB from github.com.
The download matches the checksum the catalog lists.
Unpacking it into /Users/you/tiinyapps/titanium-tiiny-bot/0.1.15.
Ready. Run: farm start titanium-tiiny-bot
```

A library has nothing to start, so its last line names the file to copy or import instead.

What happens next, in order: the release archive is downloaded, its SHA-256 and its exact byte size
are compared with the manifest, it is unpacked into a staging directory with the archive guards
described in [Permissions and archive rules](/docs/permissions/), and only then does anything land
in your app directory. A checksum that does not match means the archive is never unpacked and never
run.

An app that is already installed is refused with a pointer to `farm update`. An app whose manifest
still carries a pending checksum cannot be installed at all, and an app that needs a newer Python
than the one running the command says so and stops.

## Start it and stop it

```
farm start titanium-tiiny-bot
farm status
farm stop titanium-tiiny-bot
```

A start that worked ends with the link to open, what the app is for, and how to stop it:

```
Titanium Tiiny Bot is running.
Open http://localhost:7788
A local assistant with chat, files, memories and voice.
Stop it with: farm stop titanium-tiiny-bot
Log: /Users/you/tiinyapps/titanium-tiiny-bot/farm.log
```

The link is the app's root unless its catalog entry names a first page, and a health path is a
probe rather than a page, so it is never used as the link. `farm status` shows the same link for
every running app beside its process ID, port and uptime.

`farm start` runs the app's entry directly, without a shell, from its own version directory. It
waits up to ten seconds for the app to be ready, checking that the process is still alive the whole
time. If the manifest declares a health path, readiness on the first port means an HTTP GET of that
path returning a JSON object; every other port just has to accept a TCP connection. A start that
fails exits 1, prints the last ten lines of the app's log, and removes its process records so
nothing is left half running.

`farm stop` sends SIGINT to the process group, waits five seconds, then sends SIGKILL. On Windows
it terminates the process through a held handle so that a recycled process ID cannot be hit by
mistake.

## The port rule

Every app declares the port it listens on. Before starting anything, `farm start` checks that
the port is free. If it is taken and the app can be moved (its manifest says how it takes a
port), the farm steps up to the next free port on its own and tells you:

```
Titanium Tiiny Bot is running.
Port 7788 was busy, so it started on 7789.
Open http://localhost:7789
```

An app with a fixed port is refused instead, because nothing can move it. To choose the port
yourself, name it, and the farm never moves a port you chose:

```
farm start titanium-tiiny-bot --port 7799
```

The override replaces the first declared port only. The chosen port is exported to the app as
`TIINYAPP_PORT`, and an app whose manifest says it takes a port some other way gets it that way
too, so `--port` works whatever the app expects. A few apps cannot move at all, and those say so
in one line instead of starting somewhere you did not ask for. `farm status` shows the port an app
was actually started on.

## Keep it current

```
farm update titanium-tiiny-bot
farm start titanium-tiiny-bot
```

`farm update` installs only a strictly newer version. It never downgrades, and it stops the running
old version only after the new archive has been downloaded, verified and unpacked. Your data
directory is kept, the previous version's code is left on disk, and the app is not restarted for
you.

`farm status` compares the version the running app reports through its health path with the version
you have installed, and tells you to restart when they differ.

## Take it away

```
farm remove titanium-tiiny-bot
farm remove titanium-tiiny-bot --purge
```

The first stops the app and deletes its code while keeping its `data` directory. The second deletes
that data too. Your device settings and the shared lock directory survive either one, because they
do not belong to any single app.

## Where everything lives

| Path | What it is |
| --- | --- |
| `~/tiinyapps/<id>/<version>/` | The unpacked app, one directory per installed version |
| `~/tiinyapps/<id>/current` | A one-line pointer to the version in use |
| `~/tiinyapps/<id>/data/` | The app's own data, kept across updates and removal |
| `~/tiinyapps/<id>/farm.log` | Everything the app writes to its output, appended |
| `~/tiinyapps/<id>/farm.pid` | The process ID of a running app |
| `~/tiinyapps/<id>/process.json` | Ports, start time, version and health path of the running app |
| `~/tiinyapps/<id>/launcher.json` | The entry `farm start` uses |
| `~/tiinyapps/.onelane/` | The shared device lock directory apps use to take turns |
| `~/tiinyapps/.locks/` | One lock file per app, so two `farm` commands cannot collide |
| `~/.tiinyapps/device.json` | Your device base URL and key, mode 0600 |
| `~/.tiinyapps/token` | Your farm API token, if you have created one |

Settings written by a pre-0.1 installation at `~/tiinyapps/device.json` are still read if the newer
path does not exist. Running `farm device` again writes the newer path.

## What the farm does not do

The permissions on an app page are what the author declared, and the command shows them to you
before you install. It does not sandbox an installed app, and it cannot enforce those declarations
once the app is running. Every app in the catalog ships its source, so read it if that matters to
you.
