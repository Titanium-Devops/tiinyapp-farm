---
title: Running an app the farm way
slug: app-authors
order: 6
summary: What the installer expects of your archive, your start command, your ports, your health endpoint and the shared device lock.
---

This page is for the person writing the app. It describes the contract the installer holds you to,
so that `farm install` and `farm start` work on somebody else's machine without you being there.

## Your archive

A release is one `.tar` or `.tar.gz` containing your source and your license. Everything the app
needs to start has to be inside it. Nothing is downloaded or installed for you at install time, so
an app that depends on third-party packages has to say so in its description and ask the person to
install them, or not depend on them.

The installer unpacks into a staging directory first and applies these rules to every member:

| Rule | Refused |
| --- | --- |
| Paths | Absolute paths, `..` anywhere in the path, backslashes, a colon in any part |
| Entry kinds | Anything that is not a regular file or a directory, so no symlinks, devices or fifos |
| Duplicates | The same file path twice in one archive |
| Windows names | Reserved device names, and parts ending in a dot or a space |
| Size | More than 512 MiB downloaded, more than 2 GiB unpacked, more than 100,000 entries |
| Emptiness | An archive with nothing in it |

Executable bits are normalised: a member with any execute bit becomes 0755, everything else 0644.

If the archive has exactly one top-level directory, that directory is treated as the root of your
app, which is what a GitHub source tarball looks like. The one exception is when that directory's
name matches the first part of your Python entry module, because then it is your package and the
archive root is already right.

Do not bundle API keys, tokens, private keys, virtual environments or local user data. The scanner
reads every file in the archive looking for them, and a match fails the submission.

## How it starts

`farm start` runs your entry directly. There is no shell, so pipes, redirects, globs, `&&` and
environment substitution in a command string do nothing. A command entry is split into arguments
the way a shell would split it, and a leading `python` or `python3` is replaced with the
interpreter that is running `farm`, so your app gets the same Python the tool has.

The working directory is your version directory, `~/tiinyapps/<id>/<version>`. Standard output and
standard error are appended to `~/tiinyapps/<id>/farm.log`, and `PYTHONUNBUFFERED=1` is set so the
log is useful while the app runs.

Two things your process must not do:

- Do not daemonize, fork into the background or exit after spawning a child. The command that
  `farm start` launches has to be the long-lived process.
- On macOS and Linux, do not close inherited file descriptors. The launcher holds a lock on one of
  them, and that lock is how `farm status`, `farm stop` and a second `farm start` tell a live
  process from a stale process ID.

## Ports

Declare every port your app listens on in `requires.ports`. The first one is the primary port.

Before starting you, `farm start` refuses any declared port that is already listening, so your app
never has to handle that case itself. The person can then rerun with `--port N`, which replaces the
first declared port only.

Read the port from `TIINYAPP_PORT`. It is always set when the manifest declares any port, and it
carries the override when there is one.

If your app takes its port some other way, say so in the manifest's `port` field and the farm will
use that instead: `{"argv": "--port"}` when the number follows a flag on your command line, or
`{"env": "PORT"}` when you read a different variable. Both are honoured for every app, so you do
not have to change your code to make `--port` work. If your port cannot move at all, write
`"port": null` and `farm start --port N` refuses in one line instead of starting you somewhere you
did not expect.

## Being ready

After launching you, the tool waits up to ten seconds and checks that your process is still alive
the whole time. Readiness means every declared port accepts a TCP connection. If you would rather
prove more than that, declare a health path:

```
"health": "/api/health"
```

An HTTP GET of that path on the first port must answer with a JSON object. An `ok` field that is
`false` counts as not ready; any other value or no field at all is fine. Include a `version` field
holding your three-number version, because `farm status` compares it with the installed manifest
and tells the person to restart when a newer version is on disk. A health response has half a
second to arrive on each attempt.

A start that never becomes ready exits 1, prints the last ten lines of your log, and cleans up the
process records.

## A quick offline check

Declare `"selfcheck": true` alongside a runnable entry and the submission checks will run your
entry with `--selfcheck` appended to its normal arguments. So `{"python": "lite", "args": []}`
becomes `python -m lite --selfcheck`.

It runs in `python:3.11-slim` with no network, no device, and no third-party packages installed.
The app directory is mounted read only, so write to `/tmp` if you need to write anything at all. It
must exit 0 within 120 seconds. Capabilities are dropped, the container cannot gain privileges, and
it is limited to 512 MB, one CPU and 64 processes.

This is the cheapest way to prove your app at least imports and starts. A library cannot declare
one, and a false or missing declaration skips the check.

## Reaching the Tiiny

The launcher hands you the device settings the person saved once:

| Variable | Value |
| --- | --- |
| `TIINY_BASE` | The device API base URL, such as `http://openai.api.tiiny/v1` |
| `TIINY_KEY` | The device API key |
| `TIINY_HOST` | Just the host part of the base URL, bracketed if it is an IPv6 literal |

Read them from the environment. Do not ask the person to paste a key into your own config, do not
write the key anywhere, and never print it. If no settings have been saved yet, the two variables
are simply absent, so fail with a message that tells the person to run `farm device`.

Declare `device` in `permissions` if you talk to the Tiiny at all, and `network` if you import
anything that opens a socket, including a local HTTP server. See
[Permissions and archive rules](/docs/permissions/).

## Taking turns on one device

A Tiiny serves one inference at a time. Two apps hitting it at once produce device error 150004
rather than a queue. OneLane is the catalog's answer: a single Python file you copy beside your own
code that holds a kernel level lock, rides out busy retries, and can track a model budget.

Every app is launched with `ONELANE_DIR` pointing at `~/tiinyapps/.onelane`, a directory shared by
every app on the machine. Use that path for the lock and cooperating apps take turns. It survives
`farm remove`, because it does not belong to any one app.

Note that setting the path is not the same as using it. Story Lantern retries on contention but has
not adopted OneLane, so an app that wants a guarantee has to hold the lock itself.

## Your data

| Variable | Value |
| --- | --- |
| `FARM_DATA_DIR` | `~/tiinyapps/<id>/data` |
| `TIINY_DATA_DIR` | The same directory |

Write everything you keep there. It survives `farm update`, which installs the new version beside
the old one, and it survives `farm remove`. Only `farm remove --purge` deletes it. Do not write
into your version directory: it is replaced on update and deleted on removal.

## Libraries

An app with `entry: null` and the `library` tag is installable but not runnable. `farm install`
says so at the end, and `farm start` explains that there is nothing to launch rather than failing
obscurely. This is how OneLane ships.

## Before you submit

- The archive unpacks cleanly under the rules above and contains your license.
- The entry starts the app in the foreground from the archive root.
- Every port you bind is declared, and you read `TIINYAPP_PORT` or the manifest says how you take
  a port in its `port` field.
- Every access you use is declared in `permissions`.
- Nothing in the archive imports `subprocess` or `ctypes`, and nothing calls `eval`, `exec`,
  `os.system` or `os.popen`.
- No key, token or private key is anywhere in the archive, including dotfiles.
