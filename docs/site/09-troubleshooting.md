---
title: Troubleshooting
slug: troubleshooting
order: 9
summary: The messages the farm prints, what each one means, and what to do next.
---

Every failure from the command line is one line beginning `farm:` on standard error, and the exit
code is 1. Argument mistakes exit 2 with the usage instead. Start with `farm status` and the app's
log at `~/tiinyapps/<id>/farm.log`.

## Installing the command

**`error: externally-managed-environment`** from pip. Homebrew Python and recent Debian refuse to
install into the system Python. Use `pipx install tiinyapp-farm` instead.

**`HTTP 403 from tiinyapp.farm/manifests/...`** on a brand new install. Cloudflare's browser
integrity check answers 403 to Python's default user agent. The command sends its own user agent to
avoid exactly this, so a 403 here means a very old copy: upgrade with
`pip install --upgrade tiinyapp-farm` and try again.

**`Could not reach tiinyapp.farm`** or `Could not reach <host>`. A network or DNS problem between
you and the catalog, printed without the underlying error text because those can contain
credentials.

## Installing an app

**`<id> is already installed; use farm update.`** The app has a `current` version. `farm update`
moves it forward.

**`<id> is up to date; no downgrade performed.`** The catalog version is not newer than yours.
Nothing was changed.

**`Checksum mismatch; archive was not unpacked or run.`** The bytes that arrived are not the bytes
the manifest describes. Nothing was extracted. Either the release was replaced without the manifest
being updated, or something modified the download. Do not work around it.

**`Archive size does not match the manifest.`** The same situation, caught on the byte count.

**`Release checksum is pending; this catalog draft cannot be installed.`** The listing is a draft.
It becomes installable when its maker publishes a real archive.

**`This app needs Python X.Y or newer.`** The interpreter running `farm` is older than the app
requires. Install the command under a newer Python.

**`This app has no release to install yet.`** The app is listed with a "No release yet" badge.

**`Unsafe archive member; paths, links and special files are refused.`** or
**`Archive exceeds extraction limits.`** The archive breaks the rules in
[Permissions and archive rules](/docs/permissions/). This is the author's problem to fix, not
something to bypass.

## Starting and stopping

**`Port 7788 is already in use; use farm start <id> --port N.`** Something already holds the port.
Either stop it, or start on a free one: `farm start <id> --port 7799`.

**`Port 8425 is already in use, and <id> cannot be moved off it.`** The same thing, for an app whose
manifest says its port is fixed. `--port` cannot help here, so find what holds the port and stop it.

**`<id> runs on port 8425 only and cannot be moved, so start it without --port.`** You passed
`--port` to an app whose manifest declares a fixed port. Run it without the flag.

**`<id> exited at startup (exit 1).`** followed by up to ten log lines. The app started and died.
The log lines are the reason; the full log is at `~/tiinyapps/<id>/farm.log`.

**`<id> timed out waiting for readiness after 10 s.`** The process is alive but its port, or its
health path, never answered in time. Check the log. An app that puts itself into the background
instead of staying in the foreground also lands here.

**`<id> is a library, not a runnable app.`** It has nothing to start. Use it from your own code.

**`<id> is already running.`** Nothing to do. `farm status` shows its process id and port.

**`App did not stop; keeping its process records.`** or **`App did not stop after SIGKILL; ...`**
The process ignored both signals. The records are deliberately kept so nothing else assumes the
port is free. Deal with the process yourself, then run `farm stop` again.

**`Invalid device settings; run farm device.`** `~/.tiinyapps/device.json` exists but does not hold
a base URL and a key as text. Run `farm device` again.

**`Invalid current version record.`** or **`Installed version metadata does not match current.`**
The install directory was edited by hand. `farm remove <id>` then `farm install <id>` puts it back.

## Connecting your Tiiny

**The prompt refuses to run.** `farm device` will not fall back to echoing what you type. Run it in
a real terminal, or use the scripted form:
`farm device --base http://openai.api.tiiny/v1 --key-stdin < key-file`.

**`Use an HTTP(S) base URL without credentials, query or fragment.`** The base URL must be just a
scheme, host, port and path, such as `http://openai.api.tiiny/v1`.

**`Provide --base or TIINY_BASE for device import.`** One of `TIINY_BASE` or `TIINY_KEY` was in the
environment, which chooses the scripted path, and the base URL was missing. Scripted input never
falls back to a prompt.

## Publishing

**`That is not a farm token: got N characters starting '...'`** The token is `farm_` and 40
characters. Copy it again from [Your apps](/account/). The message never shows the token.

**`No terminal to hide the token.`** Pipe it instead:
`printf '%s' "$TOKEN" | farm login --token-stdin`.

**`No API token. Run farm login or pass --token.`** Nothing in `--token`, `FARM_TOKEN` or
`~/.tiinyapps/token`, in that order.

**`farm.json has unknown fields: ...`** Only the fields in [Publish an app](/docs/publish/) are
accepted, so a typo is caught rather than silently ignored.

**`farm.json is missing a required field (...).`** `farm publish` asks for missing values when it
has a terminal. Without one, add the field to `farm.json`.

**`Project file exceeds 50 MB`** or **`The packed project exceeds 50 MB.`** Take large files out of
the project folder, or host them elsewhere and fetch them at runtime.

**`Project symlinks are refused`** A symlink in the project cannot be packed. Replace it with the
file itself.

**`That app ID is already in the catalog. Use Update on Your apps.`** Somebody has that id. If it
is yours, update it instead of submitting again.

**`That app name is already used by another maker.`** The id belongs to a different account.

**`Verify you own a Tiiny before ...`** Submitting, uploading images, creating a token and
commenting all need the TiinyVerse proof. See [Publish an app](/docs/publish/).

**`The bio code is not on your profile yet.`** Save the profile with the code in it, wait for the
page to be public, then press Verify again. The code lasts 24 hours.

**`That release link answered 404, not 200.`** Open the link in a browser: it has to download the
`.tar.gz` directly, with no login and no landing page. GitHub release links work.

**`The release must be a gzip archive.`** Whatever arrived does not begin with the gzip signature.
A `.zip` renamed to `.tar.gz` is the usual cause. Build it with
`tar -czf my-app-0.1.0.tar.gz my-app/`.

**`This app is being reconciled after an interrupted review request.`** A submission was
interrupted at the moment the pull request was being opened, so it may or may not exist. A
maintainer sorts out the saved branch; your archive is kept.

**`App submission is not configured yet.`** or **`Sign-in is not configured yet.`** A credential is
missing on the farm itself. Nothing you can fix from your side.

## Checks that go red

**schema** fails when the manifest breaks the
[manifest reference](/docs/manifest/). Run `python3 scripts/check-manifest.py` on the file for the
exact path and reason.

**identity** fails when the filename and the `id` disagree, or another manifest uses the same id.

**Tiiny owner** fails when `author.tiinyverse` is missing, unverified, or belongs to someone else.
The check fails closed: if it cannot ask the farm, it does not pass you.

**download** fails on a checksum, a size, or a link that no longer serves the archive.

**static scan** fails on forbidden code or a secret pattern. The detail names the file, the line
and the kind, never the matching text. See
[Permissions and archive rules](/docs/permissions/) for the full list and a worked example.

**selfcheck** fails when your entry does not exit 0 within 120 seconds offline. Its output is
withheld, so reproduce it locally with no network and no device.

A run that dies before it can write its report leaves a comment pointing at the failed run instead
of a table. Fix and push again; the comment is updated in place rather than repeated.

## Still stuck

- `farm status` for what is running, on which port, and whether a restart is due.
- `farm status <id>` for the checks and review state of your own submission.
- `~/tiinyapps/<id>/farm.log` for everything the app itself said.
- The app's own repository, which every listing links to.
