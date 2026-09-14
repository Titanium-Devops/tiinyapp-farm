# UPDATES-1 report: the farm tells you what has a newer version, and updates what you pick

`farm update` with no id now asks the catalog about every app you have installed, numbers the ones
that have moved, and asks once which to take. `farm check` is the same command. `farm update <id>`
asks before it takes anything, says your data is kept, and puts a running app back on the port it
was really on. `farm list`, `farm status` and `farm start` say when something newer is out.

## What changed

- `farm/farm.py`: `newer`, `release_note`, `update_available`, `describe_update` and `interactive`
  as module helpers; `Farm.running_port`, `Farm.newer_version`, `Farm.updates`, `Farm.update` and
  `Farm.check` as methods; one line each added to `Farm.list`, `Farm.status` and `Farm.start`;
  `Farm.install` grew a `restart` flag that swaps its last line, and says the data directory is
  kept on the update path. `farm update` takes an optional id plus `--all`, and `farm check` is a
  new subcommand. Standard library only, no new imports.
- The id is optional on `farm start` and `farm stop` too. Jason, 2026-09-14: "Does it ask me which
  app I want to stop?" Bare `farm stop` numbers the running apps and asks the same question the
  update chooser asks, bare `farm start` numbers the installed apps that are not running and could
  be, and exactly one candidate is a plain yes or no instead of a list of one. All three choosers
  now go through `ask_which`, `ask_yes` and `name_one`.
- `docs/manifest.schema.json` and `docs/site/05-manifest.md`: an optional one-line `release.notes`.
  The release object is `additionalProperties: false`, so without this the note the brief asks for
  could never reach a real catalog entry. It is optional and nothing breaks without it.
- `tests/test_farm.py`: 44 new tests and one fixture helper for a second installed app.
- `docs/site/02-getting-started.md` and `docs/site/03-cli.md`.

Rebased onto main after PR #18. `farm start` keeps both the line this work adds under the link and
the macOS Local Network hint that #18 prints last, and `pyproject.toml` stays at the 0.1.7 main set.

Three judgement calls worth naming. The advisory lookups that `farm start`, `farm status` and
`farm list` now make use a five second timeout rather than the installer's thirty, so an unreachable
catalog cannot stall a start; a lookup that fails prints nothing. And `farm update <id>` against a
catalog entry that is ahead but carries no release says exactly that, rather than claiming the
installed version is the newest there is. And the question treats end of input as nobody being
there rather than as a cancellation, because Windows reports `NUL` as a terminal, so a scripted run
reaches the question and must still leave with nothing changed and exit 0.

## Tests

| Run | Tests | Result |
| --- | --- | --- |
| `python3 -m unittest` on this branch's base | 212 | OK, 2 skipped |
| `python3 -m unittest` after | 256 | OK, 2 skipped |

Measured on Jason's MacBook, Darwin 25.6.0 arm64, Python 3.14.6. The new tests cover the list with
one newer, two newer and none; the number choice, `all`, Enter, an answer that is not on the list,
and the path a script takes; the single-app question with Enter, `y`, `n` and `--yes`; an app that
is already current; the running app stopped, updated and started again on its port; the `status`,
`list` and `start` lines; a release note and the date that stands in for one; a catalog entry that
cannot be read; a pending release and a release-less entry, neither of which is ever offered; the
advisory timeout; end of input at the question, which Windows CI caught, because Windows calls
`NUL` a terminal and a scripted run reaches the question anyway; and the CLI dispatch for `check`
and every `update` form.

Two of the new assertions were checked by breaking the code they cover, to prove they are not
vacuous: with the `status` and `start` lines disabled, exactly those two tests fail.

## The real transcript

A fresh virtual environment, this branch built as a wheel and installed with `--no-index`, `HOME`
redirected to a scratch directory, and the live catalog at `https://tiinyapp.farm/manifests/`. Both
apps were installed at the catalog's version, then pinned back by renaming the installed version
directory and editing the `version` field of `.farm-manifest.json` in the scratch home, so the live
catalog is genuinely ahead of them. AINode Pocket's installed copy also had its declared port moved
to 7861 for this run, since its real port is outside the range this work is allowed to touch. Every
port here is between 7861 and 7869, and something else was holding 7861 so the step-off had
somewhere to go.

One line in the first `farm status` row is an artefact of that pinning, not a defect: the running
app reports `0.1.0` through its health path while its pinned manifest says `0.0.9`, so the row
carries `restart to update` beside `update available: 0.1.0`.

```
# The farm, from a fresh venv with the built wheel installed --no-index, HOME redirected.

$ farm --version
farm 0.1.6
(exit 0)

$ farm list
Installed:
  ainode-pocket 0.0.9 AINode Pocket [stopped, update available: 0.1.0] - One endpoint and one page for every Tiiny you own.
  tiiny-brain 0.1.0 Tiiny Brain [stopped, update available: 0.1.1] - Your own notes, held by the machine on your desk.
Catalog:
  ainode-pocket 0.1.0 AINode Pocket - One endpoint and one page for every Tiiny you own.
  onelane 0.1.2 OneLane - Let cooperating apps take turns using one Tiiny.
  story-lantern 0.1.2 Story Lantern - Write, illustrate and narrate bedtime stories on your Tiiny.
  tiiny-bench 0.1.1 TiinyBench - Measure what your Tiiny does under real work.
  tiiny-brain 0.1.1 Tiiny Brain - Your own notes, held by the machine on your desk.
  titanium-tiiny-bot 0.1.15 Titanium Tiiny Bot - A local assistant with chat, files, memories and voice.
(exit 0)

# Something else is already listening on 7861.

$ farm start ainode-pocket
AINode Pocket is running.
Port 7861 was busy, so it started on 7862.
Open http://localhost:7862
Version 0.1.0 is out. Run: farm update ainode-pocket
One endpoint and one page for every Tiiny you own.
Stop it with: farm stop ainode-pocket
Log: /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/updates1/home/tiinyapps/ainode-pocket/farm.log
(exit 0)

$ farm status
APP PID PORT LINK UPTIME STATUS
ainode-pocket 65772 7862 http://localhost:7862 0s running 0.1.0, installed 0.0.9: restart to update, update available: 0.1.0
(exit 0)

$ farm check
Looking up all 2 apps you have installed in the catalog.
1. AINode Pocket 0.0.9, 0.1.0 is out, dated 2026-09-14.
2. Tiiny Brain 0.1.0, 0.1.1 is out, dated 2026-09-14.
Nothing was updated. Run: farm update <id> to take one, or farm update --all to take them all.
(exit 0)

$ farm update
Looking up all 2 apps you have installed in the catalog.
1. AINode Pocket 0.0.9, 0.1.0 is out, dated 2026-09-14.
2. Tiiny Brain 0.1.0, 0.1.1 is out, dated 2026-09-14.
Update which? A number, "all", or Enter to leave them. 1
AINode Pocket is running on port 7862, so the farm stops it and starts it again on 7862.
Looking up ainode-pocket in the catalog.
AINode Pocket 0.1.0
One endpoint and one page for every Tiiny you own.
Made by Jason Brashear. The farm has reviewed it.
Needs: Python 3.9 or newer, port 8430
It can reach your files, the network and your Tiiny.
Downloading 480 KB from github.com.
The download matches the checksum the catalog lists.
Unpacking it into /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/updates1/home/tiinyapps/ainode-pocket/0.1.0.
Your data in /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/updates1/home/tiinyapps/ainode-pocket/data is kept.
Ready.
AINode Pocket is running.
Open http://localhost:7862
One endpoint and one page for every Tiiny you own.
Stop it with: farm stop ainode-pocket
Log: /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/updates1/home/tiinyapps/ainode-pocket/farm.log
(exit 0)

$ farm status
APP PID PORT LINK UPTIME STATUS
ainode-pocket 65974 7862 http://localhost:7862 0s running 0.1.0
(exit 0)

$ farm stop ainode-pocket
Stopped ainode-pocket.
(exit 0)

$ farm update
Looking up all 2 apps you have installed in the catalog.
1. Tiiny Brain 0.1.0, 0.1.1 is out, dated 2026-09-14.
Update which? A number, "all", or Enter to leave them. 
Left as they are.
(exit 0)

$ farm update tiiny-brain
Tiiny Brain 0.1.0 is installed and 0.1.1 is out. Update it? [Y/n] y
Looking up tiiny-brain in the catalog.
Tiiny Brain 0.1.1
Your own notes, held by the machine on your desk.
Made by Jason Brashear. The farm has not reviewed it yet.
Needs: Python 3.9 or newer, port 8500, your Tiiny, for embedding, chat
It can reach your files, the network and your Tiiny.
Downloading 86 KB from github.com.
The download matches the checksum the catalog lists.
Unpacking it into /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/updates1/home/tiinyapps/tiiny-brain/0.1.1.
Your data in /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/updates1/home/tiinyapps/tiiny-brain/data is kept.
Ready. Run: farm start tiiny-brain
(exit 0)

$ farm list
Installed:
  ainode-pocket 0.1.0 AINode Pocket [stopped] - One endpoint and one page for every Tiiny you own.
  tiiny-brain 0.1.1 Tiiny Brain [stopped] - Your own notes, held by the machine on your desk.
Catalog:
  ainode-pocket 0.1.0 AINode Pocket - One endpoint and one page for every Tiiny you own.
  onelane 0.1.2 OneLane - Let cooperating apps take turns using one Tiiny.
  story-lantern 0.1.2 Story Lantern - Write, illustrate and narrate bedtime stories on your Tiiny.
  tiiny-bench 0.1.1 TiinyBench - Measure what your Tiiny does under real work.
  tiiny-brain 0.1.1 Tiiny Brain - Your own notes, held by the machine on your desk.
  titanium-tiiny-bot 0.1.15 Titanium Tiiny Bot - A local assistant with chat, files, memories and voice.
(exit 0)

$ farm update
Looking up all 2 apps you have installed in the catalog.
Everything you have installed is the newest the catalog has.
(exit 0)
```

## What I did not do

- The version in `pyproject.toml` is untouched, as the brief says.
- Nothing was started on 7788, 8430 or 8431, and nothing outside the scratch `HOME` was written.

## The choosers, live

The same scratch `HOME` and wheel, with AINode Pocket on 7863 and TiinyBench on 7864. Their
installed manifests had their declared ports moved into the 7861 to 7869 range for this run.

```
# Two apps running, on 7863 and 7864.

$ farm stop
2 apps are running.
1. AINode Pocket 0.1.0 on port 7863
2. TiinyBench 0.1.1 on port 7864
Stop which? A number, "all", or Enter to leave them. 
Left as they are.
(exit 0)

$ farm stop
2 apps are running.
1. AINode Pocket 0.1.0 on port 7863
2. TiinyBench 0.1.1 on port 7864
Nothing was stopped. Run: farm stop <id>, naming one of ainode-pocket and tiiny-bench.
(exit 0)

$ farm stop
2 apps are running.
1. AINode Pocket 0.1.0 on port 7863
2. TiinyBench 0.1.1 on port 7864
Stop which? A number, "all", or Enter to leave them. 2
Stopped tiiny-bench.
(exit 0)

$ farm stop
Stop AINode Pocket? [Y/n] y
Stopped ainode-pocket.
(exit 0)

$ farm stop
Nothing is running.
(exit 0)

$ farm start
3 installed apps are ready to start.
1. AINode Pocket 0.1.0
2. TiinyBench 0.1.1
3. Tiiny Brain 0.1.1
Start which? A number, "all", or Enter to leave them. 1
AINode Pocket is running.
Open http://localhost:7863
One endpoint and one page for every Tiiny you own.
Stop it with: farm stop ainode-pocket
Log: /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/updates1/home/tiinyapps/ainode-pocket/farm.log
(exit 0)

$ farm start
2 installed apps are ready to start.
1. TiinyBench 0.1.1
2. Tiiny Brain 0.1.1
Start which? A number, "all", or Enter to leave them. n
There is no n in that list, so nothing was started.
(exit 0)

$ farm start
2 installed apps are ready to start.
1. TiinyBench 0.1.1
2. Tiiny Brain 0.1.1
Nothing was started. Run: farm start <id>, naming one of tiiny-bench and tiiny-brain.
(exit 0)
```

Tiiny Brain appears on the start list and was deliberately left alone: it declares a fixed port
outside the range this work may touch.
