# DEVICE-FIND-1: the farm finds the Tiiny

Jason, 2026-09-14 14:40: "will the launcher not be able to FIND the tiiny?" Today `farm device` asks for the
base URL blind, and the launcher brief only probes the TiinyOS hostname and offers a manual box. A person
with a Pocket Lab on the cable and no TiinyOS client gets nothing found. AINode Pocket already solves
this with the standard library; the farm gets the same finder, in the CLI, so the launcher and the CLI
share one answer.

## What to build, in /Users/sem/code/tiinyapp-farm-main's farm/farm.py (stdlib only, Python 3.9+)

1. `farm device --find` (and `farm device --find --json`): look for Tiinys and print what was found, in
   this order, all with short timeouts and never longer than ~6 s total:
   a. The USB gadget link: each box is a point-to-point /30 under 172.17.0.0/16, the device on the
      .177-style address and the host on the next one. Find the host's own 172.17.x.x addresses by the
      bind trick AINode Pocket uses (no ifconfig, no subprocess, no psutil), derive the device address,
      GET http://<device>:39218/device.json (unauthenticated; carries serial_number, interfaces usb0 /
      wlan0 / eth0 with their addresses, the discovery token and ports).
   b. The UDP responder: send the token GADGET_DISCOVER_V1 to port 39217 as a broadcast on each
      interface and unicast to any /30 candidate; the device answers with device.json in one datagram.
      This finds a Tiiny on the LAN too.
   c. The TiinyOS client's hostname http://openai.api.tiiny/v1 (what the Mac client publishes).
   Read the finder in /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/pocket/repo/pocket/ (device.py and its neighbours; constants USB_NET_PREFIX, DISCOVERY_PORT 39218, UDP_DISCOVERY_PORT 39217, DISCOVERY_TOKEN) and port the logic, not the code; keep the farm's own voice.
2. Output: one line per device found: serial (or "a Tiiny"), the address to use, how it was reached
   (cable, network, TiinyOS client), and the base URL the farm would save (`http://<address>/v1`, the
   vhost form on port 80 that the farm already documents; say if device.json shows port 8800 open too).
   With `--json`: {"command": "device", "found": [{"serial":..., "address":..., "via":..., "base":...,
   "interfaces": [...]}]}. Nothing found: a sentence that says what was tried and the manual form, exit 1.
3. `farm device` with no arguments runs the finder first: one device found means it offers that base as
   the default at the hidden prompt ("Device base URL [http://172.17.7.177/v1]:"), several means a
   numbered pick, none means the prompt as today. `--base` skips the finder. The key is still asked
   hidden or read from --key-stdin; never printed.
4. `farm doctor` gains a finding: when no device is on file, it runs the finder and says what it saw.
5. Docs: docs/site/02-getting-started.md and 03-cli.md (the device section), 11-agents.md's "Find the
   person's Tiiny" section, and worker/openapi.py if anything there describes device setup. README's
   command table row for device. No em dashes. Tiiny spelled that way.

## Proof

Measured on this Mac against Jason's real Tiiny on the cable at 172.17.7.177 (do not touch Jason's
~/.tiinyapps; use a scratch HOME): `farm device --find` prints the device with its serial in under 6 s;
`--json` validates; with the cable's interface down or absent (simulate by monkeypatching the bind step
in tests, do not unplug anything) the finder says nothing was found and how to enter it by hand. Tests
for each probe with sockets patched, for the --json shape, for the prompt default, and for doctor's line.
The finder must never hang on a filtered port (timeouts on every socket). Python 3.9 and 3.14 both.
Run the whole suite. No version bump; the orchestrator tags 0.1.12.

## Rules

Worktree: `git -C /Users/sem/code/tiinyapp-farm-main worktree add -b device-find /Users/sem/code/tiinyapp-farm-find main`.
Never touch /Users/sem/code/tiinyapp-farm or tiinyapp-farm-main. PR against main, do not merge. The
device key is never read by this wave at all; the finder needs no key. Every `gh` call needs
`< /dev/null`. Timeouts on everything. Report measured facts separated from plans.
