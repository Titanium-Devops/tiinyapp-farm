# CLI-VOICE-1: what the farm says now, measured

Both transcripts below are real runs of the `farm` command, installed as a wheel into a fresh
virtual environment with `pip install --no-index`, against the live catalog at
https://tiinyapp.farm/manifests/. `HOME` was redirected to a scratch directory for every run, so
nothing in `~/tiinyapps` was touched, which is why the paths in the output are long.

Measured on Jason's Mac, macOS 26.6.2 on arm64, Python 3.14.6, on 2026-09-14. The apps were
started on ports 7891 and 7892.

## Before

The version on main, 0.1.5, run the same way.

```
# farm farm 0.1.5 from a fresh venv, HOME=/private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/home-before, live catalog

$ farm install ainode-pocket -y
AINode Pocket 0.1.0
One endpoint and one page for every Tiiny you own.
Permissions: files, network, device
Needs: Python 3.9 or newer, port 8430
Installed ainode-pocket 0.1.0. Run: farm start ainode-pocket

$ farm start ainode-pocket --port 7891
Started ainode-pocket on port 7891: pid 60289; log /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/home-before/tiinyapps/ainode-pocket/farm.log

$ farm install tiiny-bench -y
TiinyBench 0.1.1
Measure what your Tiiny actually does, not what the spec sheet says.
Permissions: files, network, device
Needs: Python 3.9 or newer, port 8425
Installed tiiny-bench 0.1.1. Run: farm start tiiny-bench

$ farm start tiiny-bench --port 7892
Started tiiny-bench on port 7892: pid 60316; log /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/home-before/tiinyapps/tiiny-bench/farm.log

$ farm status
APP PID PORT UPTIME STATUS
ainode-pocket 60289 7891 4s running 0.1.0
tiiny-bench 60316 7892 2s running 0.1.1

$ farm list
Installed:
  ainode-pocket 0.1.0 - AINode Pocket
  tiiny-bench 0.1.1 - TiinyBench
Catalog:
  ainode-pocket 0.1.0 - One endpoint and one page for every Tiiny you own.
  onelane 0.1.2 - Let cooperating apps take turns using one Tiiny.
  story-lantern 0.1.2 - Write, illustrate and narrate bedtime stories on your Tiiny.
  tiiny-bench 0.1.1 - Measure what your Tiiny actually does, not what the spec sheet says.
  tiiny-brain 0.1.1 - Your own notes, held by the machine on your desk.
  titanium-tiiny-bot 0.1.15 - A local assistant with chat, files, memories and voice.

$ printf '%s' "$key" | farm device --base http://openai.api.tiiny/v1 --key-stdin
Device settings saved.

$ farm stop ainode-pocket
Stopped ainode-pocket.

$ farm stop tiiny-bench
Stopped tiiny-bench.
```

## After

The same commands, same catalog, same machine.

```
# farm farm 0.1.5 from a fresh venv, HOME=/private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/home-after, live catalog

$ farm install ainode-pocket -y
Looking up ainode-pocket in the catalog.
AINode Pocket 0.1.0
One endpoint and one page for every Tiiny you own.
Made by Jason Brashear. The farm has reviewed it.
Needs: Python 3.9 or newer, port 8430
It can reach your files, the network and your Tiiny.
Downloading 480 KB from github.com.
The download matches the checksum the catalog lists.
Unpacking it into /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/home-after/tiinyapps/ainode-pocket/0.1.0.
Ready. Run: farm start ainode-pocket

$ farm start ainode-pocket --port 7891
AINode Pocket is running.
Open http://localhost:7891
One endpoint and one page for every Tiiny you own.
Stop it with: farm stop ainode-pocket
Log: /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/home-after/tiinyapps/ainode-pocket/farm.log

$ farm install tiiny-bench -y
Looking up tiiny-bench in the catalog.
TiinyBench 0.1.1
Measure what your Tiiny actually does, not what the spec sheet says.
Made by Jason Brashear. The farm has reviewed it.
Needs: Python 3.9 or newer, port 8425
It can reach your files, the network and your Tiiny.
Downloading 2.3 MB from github.com.
The download matches the checksum the catalog lists.
Unpacking it into /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/home-after/tiinyapps/tiiny-bench/0.1.1.
Ready. Run: farm start tiiny-bench

$ farm start tiiny-bench --port 7892
TiinyBench is running.
Open http://localhost:7892
Measure what your Tiiny actually does, not what the spec sheet says.
Stop it with: farm stop tiiny-bench
Log: /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/home-after/tiinyapps/tiiny-bench/farm.log

$ farm status
APP PID PORT LINK UPTIME STATUS
ainode-pocket 79899 7891 http://localhost:7891 4s running 0.1.0
tiiny-bench 79920 7892 http://localhost:7892 2s running 0.1.1

$ farm list
Installed:
  ainode-pocket 0.1.0 AINode Pocket [running] - One endpoint and one page for every Tiiny you own.
  tiiny-bench 0.1.1 TiinyBench [running] - Measure what your Tiiny actually does, not what the spec sheet says.
Catalog:
  ainode-pocket 0.1.0 AINode Pocket - One endpoint and one page for every Tiiny you own.
  onelane 0.1.2 OneLane - Let cooperating apps take turns using one Tiiny.
  story-lantern 0.1.2 Story Lantern - Write, illustrate and narrate bedtime stories on your Tiiny.
  tiiny-bench 0.1.1 TiinyBench - Measure what your Tiiny actually does, not what the spec sheet says.
  tiiny-brain 0.1.1 Tiiny Brain - Your own notes, held by the machine on your desk.
  titanium-tiiny-bot 0.1.15 Titanium Tiiny Bot - A local assistant with chat, files, memories and voice.

$ printf '%s' "$key" | farm device --base http://openai.api.tiiny/v1 --key-stdin
Device settings saved.
These installed apps will use it: ainode-pocket and tiiny-bench.
Try it now: farm start ainode-pocket

$ farm stop ainode-pocket
Stopped ainode-pocket.

$ farm stop tiiny-bench
Stopped tiiny-bench.
```

## The busy port, on a real run

The move onto a free port could not be shown above, because the only way to trigger it for
ainode-pocket is to hold port 8430, which this work was told not to touch. So this run uses the
same wheel and the same live release archive with one change: a local copy of the live manifest
whose declared port is 7891 instead of 8430, with 7891 held by another process. Everything else,
including the download from GitHub, is the live entry.

```
$ farm install ainode-pocket -y
The download matches the checksum the catalog lists.
Unpacking it into /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/home-moved/tiinyapps/ainode-pocket/0.1.0.
Ready. Run: farm start ainode-pocket

$ farm start ainode-pocket
AINode Pocket is running.
Port 7891 was busy, so it started on 7892.
Open http://localhost:7892
One endpoint and one page for every Tiiny you own.
Stop it with: farm stop ainode-pocket
Log: /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/home-moved/tiinyapps/ainode-pocket/farm.log

$ farm status
APP PID PORT LINK UPTIME STATUS
ainode-pocket 80915 7892 http://localhost:7892 0s running 0.1.0

$ farm start ainode-pocket
AINode Pocket is already running.
Open http://localhost:7892
Stop it with: farm stop ainode-pocket

$ farm stop ainode-pocket
Stopped ainode-pocket.
```

## What the tests hold

`tests/test_farm.py` covers each line above so it cannot quietly go back:

| Test | What it holds |
| --- | --- |
| `test_install_tells_a_person_what_it_is_installing` | Name, version, pitch, maker, review state, download size, checksum result, where it landed and the next command |
| `test_install_names_the_download_size_a_person_can_picture` | 480 KB, 2.3 MB, 900 bytes |
| `test_install_says_when_nobody_is_named_and_nothing_was_reviewed` | The unnamed and unreviewed wording |
| `test_start_ends_with_the_link_the_pitch_and_how_to_stop_it` | The link, the pitch, the stop line, the log path last, and no process ID in the block |
| `test_busy_port_moves_a_movable_app_up_and_says_so` | The moved-port sentence and the link on the port it really took |
| `test_an_app_already_running_is_told_where_to_open_it` | A second start still gives the link |
| `test_status_shows_a_link_for_every_running_app` | The LINK column |
| `test_the_open_field_names_the_first_page_and_a_health_probe_is_not_one` | `open` sets the path, `health` never does |
| `test_invalid_open_pages_are_refused` | The `open` field's shape, and that it needs a declared port |
| `test_a_library_says_what_to_import_instead_of_a_command` | The library ending, with the file to copy |
| `test_catalog_list` and `test_list_says_which_installed_app_is_running` | Name, version, pitch and running state per row |
| `test_device_names_the_apps_that_will_use_it_and_how_to_try_one` | Which installed apps use the device, and one command to try |
| `test_no_consumer_line_carries_a_word_only_a_maker_needs` | No "argv", no "manifest", no process ID on a consumer line |

`python3 -m unittest` ran 188 tests before this work and 203 after, all passing, 2 skipped in both
(Windows-only paths), on the same machine.
