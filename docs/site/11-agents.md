---
title: The farm for AI assistants
slug: agents
order: 11
summary: Find the person's Tiiny, install and run apps for them, publish what they made, and read every answer as JSON.
---

This page is for an assistant working on somebody's machine or against the farm's API. Everything
here is also true for a person, and the rest of the documentation says the same things at more
length. This is the order an assistant needs them in.

Two addresses are worth remembering. Fetch
[https://tiinyapp.farm/llms.txt](https://tiinyapp.farm/llms.txt) first: it is a short plain-text
index that names this page and everything under it. Then
[https://tiinyapp.farm/docs/openapi.json](/docs/openapi.json) is the whole HTTP surface as OpenAPI
3.1, every route with its authentication, its request and response shapes, its rate limits and its
errors.

## What the farm is

tiinyapp.farm is a reviewed catalog of small apps for the Tiiny AI Pocket Lab. The apps do not go
onto the device. They run on the person's own computer, next to the Tiiny, and talk to it over its
local API. One command-line tool, `farm`, installs them, starts them, updates them and takes them
away again.

Publishing does not put code in the catalog. It opens a pull request, runs automated checks, and
waits for a human maintainer. Never tell somebody their app is published before that pull request
is merged.

## Two secrets, and what to do with each

The person has up to two secrets, and neither one is yours to invent.

**Their Tiiny's API key.** It is in TiinyOS under Settings, API Key. It goes to the farm once, on
standard input, and the farm writes it to `~/.tiinyapps/device.json` with owner-only permissions.
Never put it on a command line, where every other process on the machine can read it out of the
process list, and never write it into a file in their project.

**A farm API token.** They create one at
[https://tiinyapp.farm/account/](https://tiinyapp.farm/account/) and it is shown once. It starts
with `farm_`. Ask them for it; never make one up. Send it only to `https://tiinyapp.farm`, in an
`Authorization: Bearer farm_...` header. Do not print it in a log, commit it, put it in
`farm.json`, or include it in an archive.

> Every `--json` command below writes one JSON object to standard output and nothing else. The
> prose a person would read goes to standard error, and the exit codes do not change: 0 when the
> command did what it was asked, 1 when it did not. No `--json` command ever reads standard input,
> so none of them can stop and ask a question.

## Find the person's Tiiny

The farm does this for you, in one command that saves nothing and needs no key:

```
farm device --find --json
```

```json
{"command": "device", "ok": true, "blocked": false, "python": "/usr/local/bin/python3",
 "moved": null,
 "found": [{"serial": "TNYM26072400300011Q", "name": "jason's Tiiny", "address": "172.17.7.177",
            "via": "cable", "base": "http://172.17.7.177/v1",
            "interfaces": [{"interface": "usb0", "address": "172.17.7.177"},
                           {"interface": "wlan0", "address": "192.168.100.94"}]}]}
```

`via` is `cable`, `network` or `TiinyOS client`, `base` is the URL to hand `farm device --base`, and
`ok` is false with exit 1 when nothing answered. The search is capped at six seconds.

`blocked` is the one to read before you tell somebody there is no Tiiny. macOS grants the local
network per binary and grants it silently, so a Python that has not been allowed gets EHOSTUNREACH
where another gets the device in milliseconds. `blocked` true means the farm could not see, not that
nothing is there, and the right thing to say is the Local Network settings path, not "check your
cable". Reaching a box over the cable or the network clears it, whatever else could not be sent: a
host can forbid broadcast and route everything else, so one datagram that went nowhere is not
evidence on its own. `python` is the interpreter that did the looking, and `moved` is the one the farm changed to
and saved when it had to find another. Do the same in your own code: the answer that counts is the
one from the binary that will be doing the reaching.

Use this before writing your own, and read the rest of this section to know what it is doing.

A Tiiny answers `http://<address>:39218/device.json` on the local network, with no credential. That
answer carries a serial number, so it identifies a box rather than merely finding an open port. It
also lists every address that box has, on the cable and on the network, so one answer tells you the
rest.

```
curl -s --max-time 2 http://172.17.7.177:39218/device.json
```

Look in this order, and stop at the first answer:

1. `TIINY_BASE` in the environment. The farm exports it to every app it starts.
2. `~/.tiinyapps/device.json`, which is what `farm device` wrote: `{"base": ..., "key": ...}`.
3. `farm device --find --json`, or the same search by hand: every USB cable first, then this
   machine's own network, then the TiinyOS client on `http://openai.api.tiiny/v1`.

A cable is a point to point /30 inside `172.17`, so the box takes the first usable address of each
/30 and the host takes the second. Finding our own side gives the box's side by arithmetic, and
`bind` is the only thing that knows which addresses belong to this machine. Over the network, sweep
this host's own /24 and nothing wider. Sweeping more of somebody's network than that to find one
box is not a thing an assistant should do.

Do all of it with sockets. An app in the catalog that reads addresses out of `ifconfig` fails the
archive scan, because there is no permission that grants shell access, and Story Lantern was sent
back for exactly that.

```python
import json, socket, threading, urllib.error, urllib.request

DISCOVERY = 39218


def device_json(address, timeout=0.35):
    """What the box at this address says about itself, or None."""
    try:
        with urllib.request.urlopen(f"http://{address}:{DISCOVERY}/device.json", timeout=timeout) as answer:
            found = json.load(answer)
    except Exception:
        return None
    return found if isinstance(found, dict) and found.get("serial_number") else None


def ours(address):
    """bind() succeeds only on an address that belongs to this machine."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind((address, 0))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def usb_peers():
    """The box's side of every attached cable."""
    return [f"172.17.{third}.{block * 4 + 1}"
            for third in range(256) for block in range(64)
            if ours(f"172.17.{third}.{block * 4 + 2}")]


def lan_peers():
    """This host's own /24. Connecting a UDP socket sends no packet; it picks a route."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        mine = probe.getsockname()[0]
    except OSError:
        return []
    finally:
        probe.close()
    head = mine.rsplit(".", 1)[0]
    return [f"{head}.{last}" for last in range(1, 255) if f"{head}.{last}" != mine]


def search(workers=128):
    """Every Tiiny this machine can see, the cable before the network, one per serial."""
    found, lock = {}, threading.Lock()

    def probe(address, plane):
        device = device_json(address)
        if device:
            with lock:
                found.setdefault(device["serial_number"], {
                    "address": address, "plane": plane, "name": device.get("device_name")})

    for plane, addresses in (("usb", usb_peers()), ("lan", lan_peers())):
        for start in range(0, len(addresses), workers):
            batch = [threading.Thread(target=probe, args=(address, plane))
                     for address in addresses[start:start + workers]]
            for thread in batch:
                thread.start()
            for thread in batch:
                thread.join()
    return list(found.values())


def base_url(address, timeout=2.0):
    """Firmware 1.0 serves the model API on port 80 and older firmware on 8800, so ask:
    a 404 means this port does not serve it, and a 401 means it does."""
    for port in (80, 8800):
        request = urllib.request.Request(f"http://{address}:{port}/v1/models",
                                         headers={"Authorization": "Bearer probe"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                found = answer.status != 404
        except urllib.error.HTTPError as error:
            found = error.code != 404
        except OSError:
            continue
        if found:
            return f"http://{address}/v1" if port == 80 else f"http://{address}:{port}/v1"
    return f"http://{address}/v1"


for device in search():
    print(device["name"], "at", base_url(device["address"]), "over the", device["plane"])
```

The whole search takes about a second on a quiet network, and a box that is not there is not slow,
it is absent. If nothing answers, say so. An address that does not resolve reads better than a
hostname that resolves on one Mac and nowhere else.

There is a cheaper way than sweeping a /24, and the farm's own finder uses it: one datagram. Send
`GADGET_DISCOVER_V1` to UDP port 39217, broadcast or unicast, and every Tiiny in earshot sends the
whole of its `device.json` straight back. Both the port and the token come out of `device.json`
itself. That finds a box whose network address has moved since anybody wrote it down, without
touching the rest of somebody's network.

```python
import json, socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sock.settimeout(1.5)
sock.sendto(b"GADGET_DISCOVER_V1", ("255.255.255.255", 39217))
data, where = sock.recvfrom(65535)
print(where[0], json.loads(data)["serial_number"])
```

The TiinyOS client answers every name under `api.tiiny` on loopback, so a name resolving proves
nothing about whether a Tiiny is there. Ask the surface instead: `http://openai.api.tiiny/v1/models`
with no key answers 401 when a box is behind it, and 404 or a refused connection when there is not.

## Check the models before you start an app

An app that declares it needs a kind of model and is started without one runs, and then answers
every message with an error. It looks like a broken app and it is an empty NPU. Do not start an app
without checking, and do not tell somebody an app is broken until you have:

```
farm models --json
```

```json
{"command": "models", "npu": {"total": 100, "used": 68, "available": 32}, "pending": [],
 "loaded": [{"id": "Qwen/Qwen3-8B", "kind": "chat", "capability": "main", "units": 28,
             "state": "running", "port": 9098, "seconds": 8}],
 "downloaded": [{"id": "openai/gpt-oss-20b", "kind": "chat", "capability": "main", "units": 32,
                 "state": "downloaded", "port": null, "seconds": 20}]}
```

`kind` is the farm's word and `capability` is the device's own. They differ for three of the eight:
the device says `main`, `voice` and `audio` where a manifest says `chat`, `tts` and `asr`.
`embedding`, `rerank`, `image`, `ocr` and `music` are the same word on both sides. `units` is NPU
memory residency, so `available` is what says whether another model fits.

`farm start <id> --json` does the check itself and never asks a question, which is what you want:

```json
{"command": "start", "id": "titanium-tiiny-bot", "ok": false, "started": false,
 "missing": [{"kind": "chat", "loaded": [],
              "available": ["Qwen/Qwen3-8B", "openai/gpt-oss-20b"]}]}
```

Nothing was launched. `available` is what is on the device's disk and could be loaded for that
need. Add `--load` to have the farm load the cheapest one that fits and then start the app, or ask
the person which of `available` they want. `farm start <id> --json --no-model-check` starts it
anyway, which is almost never the right thing to do on somebody's behalf.

While an app runs, `farm status --json` carries the same check per app under `models`:

```json
{"needs": ["chat", "tts"], "unmet": ["chat"], "lost": {"chat": "Qwen/Qwen3-8B"},
 "since": 1789421576.68}
```

`lost` names the model that was meeting a need when the app started and is not loaded any more, and
`since` is when the farm first noticed. An `unmet` of `null` means the farm could not ask the Tiiny,
which is not the same as nothing being loaded.

To watch rather than poll, `farm models --watch --json` writes one object per change to standard
output as it happens, with `event` of `loaded`, `unloaded` or `changed`. It runs until you stop it.

## Put the key where the farm reads it

`farm device` saves the address and the key once. Ask the person for the key, take it on standard
input, and never echo it back.

```
printf '%s' "$TIINY_KEY" | farm device --base http://172.17.7.177/v1 --key-stdin
```

```python
import subprocess

subprocess.run(["farm", "device", "--base", base, "--key-stdin"],
               input=key, text=True, check=True)
```

It writes `~/.tiinyapps/device.json` with mode 0600, names the installed apps those settings reach,
and offers one command to try them with. Run it again to change either value. `TIINY_BASE` and
`TIINY_KEY` in the environment do the same job without a file.

`farm models` takes `--json`, and with `--watch` it streams one object per change rather than
answering once.

`farm device` takes `--json` with `--find` and nowhere else, because saving a key needs the hidden
prompt or standard input and no `--json` command reads either. `login`, `publish`, `release` and
`remove` have no `--json` at all. They print prose and exit 0 or 1.

## Read the catalog

Two files, both public, both static, no credential:

| Path | What it holds |
| --- | --- |
| `/catalog.json` | `{"cli": "0.1.10", "apps": [...]}`: the newest `farm` version and every manifest |
| `/manifests/<id>.json` | One app's manifest, the file the installer reads before it downloads anything |

```
curl -s https://tiinyapp.farm/catalog.json
curl -s https://tiinyapp.farm/manifests/tiiny-brain.json
```

```python
import json, urllib.request

request = urllib.request.Request("https://tiinyapp.farm/catalog.json",
                                 headers={"User-Agent": "your-assistant/1.0"})
with urllib.request.urlopen(request, timeout=30) as answer:
    catalog = json.load(answer)

for app in catalog["apps"]:
    print(app["id"], app["version"], app["pitch"])
```

What to read in a manifest before you install anything for somebody:

- `permissions` is what the app declares it can reach: `microphone`, `files`, `network`, `device`.
  Tell the person this before you install, not after. The farm does not sandbox anything.
- `requires.ports` is what it will listen on, and `requires.device.models` is what it wants loaded
  on the Tiiny.
- `entry` is `null` for a library. There is nothing to start and `farm start` will refuse.
- No `release` key means there is nothing to install yet, and a `release.sha256` of `pending` means
  the same thing.
- `port` says how that app takes the port the farm gives it: `{"argv": "--port"}` for a flag,
  `{"env": "PORT"}` for a variable, or `null` when its port is fixed and cannot be moved.

Every field is documented in the [manifest reference](/docs/manifest/), and
[manifest.schema.json](/docs/manifest.schema.json) is the machine-readable version.

## Install, start and stop an app

```
farm install tiiny-brain --json -y
farm start tiiny-brain --json
farm status --json
farm stop tiiny-brain --json
```

```python
import json, subprocess


def farm(*arguments):
    """One farm command, answered as an object. The prose goes to standard error."""
    done = subprocess.run(["farm", *arguments, "--json"], capture_output=True, text=True)
    answer = json.loads(done.stdout)
    if "error" in answer:
        raise RuntimeError(answer["error"]["message"])
    return answer


farm("install", "tiiny-brain", "-y")
started = farm("start", "tiiny-brain")
print("Open", started["url"])
```

`install` needs `-y`, because with `--json` the farm will not stop to ask. It answers where the app
landed and what it declares:

```json
{"command": "install", "installed": true, "id": "tiiny-brain", "name": "Tiiny Brain",
 "version": "0.1.1", "path": "/Users/you/tiinyapps/tiiny-brain/0.1.1", "library": false,
 "ports": [8500], "permissions": ["files", "network", "device"]}
```

`start` answers the port the app really took and the link to hand the person. `--port N` moves it,
and if the declared port is busy the farm steps up to the next free one on its own and the answer
says which one it used:

```json
{"command": "start", "id": "tiiny-brain", "already": false, "version": "0.1.1", "running": true,
 "pid": 67772, "ports": [7861], "port": 7861, "url": "http://localhost:7861",
 "log": "/Users/you/tiinyapps/tiiny-brain/farm.log"}
```

`already` is true when it was running before you asked. `log` is the file to read when an app is
misbehaving; a failed start puts its last ten lines in the error message for you.

`status` answers one row per running app, with the version the app reports through its own health
path when it has one:

```json
{"command": "status", "running": [
  {"id": "tiiny-brain", "pid": 67772, "ports": [7861], "port": 7861,
   "url": "http://localhost:7861", "uptime": 5, "version": "0.1.1", "installed": "0.1.1",
   "restartToUpdate": false, "health": null, "updateAvailable": null}]}
```

`health` is `null` when the app declares no health path, `ok` when it answered, `unavailable` when
it did not, and `unversioned` when it answered without a usable version. `restartToUpdate` is true
when the running version is behind the installed one.

`stop` says whether it stopped something. `false` means it was not running, which is not an error:

```json
{"command": "stop", "id": "tiiny-brain", "stopped": true}
```

`list` answers what is installed here and the whole catalog, with `installed` on a catalog row
telling you which version this machine has:

```json
{"command": "list",
 "installed": [{"id": "tiiny-brain", "name": "Tiiny Brain", "version": "0.1.1",
                "pitch": "Your own notes, held by the machine on your desk.",
                "running": false, "updateAvailable": null}],
 "catalog": [{"id": "tiiny-brain", "name": "Tiiny Brain", "version": "0.1.1",
              "pitch": "Your own notes, held by the machine on your desk.",
              "release": "ready", "installed": "0.1.1"}]}
```

`release` is `ready`, `pending` or `none`, and only `ready` can be installed.

`start` and `stop` with no id ask a person which one they meant, so with `--json` they refuse and
name the apps instead:

```json
{"error": {"command": "start",
           "message": "Run: farm start <id>, naming one of daybreak and tiiny-brain."}}
```

Every failure has that shape, the message is the sentence the person would have read, and the exit
code is 1.

## Keep apps current

`farm check --json` asks the catalog about everything installed and changes nothing:

```json
{"command": "check",
 "updates": [{"id": "tiiny-brain", "name": "Tiiny Brain", "installed": "0.1.1",
              "available": "0.1.2", "notes": "Faster starts.", "updatedAt": "2026-09-14"}],
 "unreachable": [], "updated": []}
```

`unreachable` names the apps whose catalog entry could not be read, so a network problem is never
silently reported as "nothing new". Add `--all` to take every one of them, and the ids you took
come back in `updated`. `farm update --json` with no id is the same command and answers the same
object, with `"command": "check"` in it.

`farm update <id> --json` takes one, and says what moved:

```json
{"command": "update", "id": "tiiny-brain", "updated": true, "previous": "0.1.1",
 "available": "0.1.2", "version": "0.1.2", "running": true, "pid": 67901,
 "ports": [7861], "port": 7861, "url": "http://localhost:7861"}
```

An app that was running is stopped only after the new release is downloaded and verified, its
`data` directory is kept, and it is started again on the port it was really on. `updated` is false
when there was nothing newer to take, and `available` then tells you whether the catalog has a
newer version that has no release to install yet.

## Run the doctor and act on each finding

`farm doctor --json` checks the things a person would otherwise have to ask somebody else about,
and answers every line it prints as a finding:

```json
{"command": "doctor", "ok": true, "farm": "0.1.10", "findings": [
  {"check": "device", "ok": true, "message": "Your Tiiny at 172.17.7.177 answered this Python in 4 ms.",
   "fix": null, "address": "172.17.7.177", "milliseconds": 4},
  {"check": "key", "ok": true, "message": "The key on file is accepted by your Tiiny.", "fix": null},
  {"check": "models", "ok": true, "message": "Your Tiiny lists 4 models: ...", "fix": null,
   "models": ["Qwen/Qwen3-8B", "Qwen/Qwen3-Embedding-0.6B"]}]}
```

Work through the findings and act on every one whose `ok` is false. `fix` is the sentence printed
under it, and it says what to do. The top-level `ok` is the exit status, and it is not the same
thing: a Tiiny with no models loaded is a finding with a fix, and the command still exits 0.

| `check` | What it looked at, and what to do when it is false |
| --- | --- |
| `farm` | The farm's own version and the Python it runs apps with |
| `cli` | A newer farm is published. Run `farm self-update` |
| `settings` | The device address on file |
| `device` | Whether that address answered this Python, and how long it took |
| `key` | Whether the Tiiny accepted the key on file. Ask for it again and run `farm device` |
| `pythons` | The other Pythons on the machine, each with whether it reaches the Tiiny |
| `python` | macOS is refusing this Python the local network. The fix names one that works |
| `apps` | Nothing is installed yet |
| `app` | One installed app the farm cannot read, or a library with nothing to start |
| `port` | One declared port, carrying `id` and `port`, and who is holding it |
| `models` | What the Tiiny has loaded |

The macOS local network one is worth knowing about. macOS refuses a binary it has never been
granted, silently, so an app started in the background simply cannot see the Tiiny. The farm tries
the other Pythons on the machine and runs apps with the first one that works. When none does, the
fix is System Settings, Privacy and Security, Local Network.

## Publish an app for a person

Work from the project folder. `farm.json` is the whole maker-written shape, and unknown fields are
refused:

```json
{
  "id": "my-app",
  "name": "My App",
  "pitch": "One line, with no line break.",
  "description": "What it does, who it is for, and important limits.",
  "version": "0.1.0",
  "license": "MIT",
  "category": "developer-tools",
  "entry": {"command": "python -m my_app"},
  "permissions": ["network", "device"],
  "links": {
    "repo": "https://github.com/example/my-app",
    "homepage": "https://example.com/my-app",
    "video": "https://youtu.be/dQw4w9WgXcQ"
  },
  "media": {
    "icon": "art/icon.png",
    "header": "art/header.webp",
    "screenshots": ["art/one.png", "art/two.jpg"]
  }
}
```

The field rules:

- `id` is required. A lowercase letter, then lowercase letters, digits and single dashes. `tiiny`
  is reserved. It becomes the catalog URL and the `farm install` command and can never change.
- `name`, `pitch` and `description` are required and not empty. `pitch` is one line of 100
  characters or fewer.
- `version` is exactly three nonnegative numbers. A release change needs a strictly newer one.
- `license` is required. Prefer a clear SPDX identifier such as MIT.
- `category` is one of `assistant`, `family`, `audio`, `developer-tools` or `library`.
- `entry` is required. It is `null` for a library, a command string, `{"command": "..."}`, or
  `{"python": "package.module", "args": ["arg"]}`.
- `permissions` is required, has no duplicates, and uses `microphone`, `files`, `network` and
  `device` only. Use `[]` when the app needs none. Declare everything the app actually uses.
- `links` may hold `repo`, `homepage` and `video` only, each an HTTPS URL, and `video` is a YouTube
  watch or `youtu.be` link.
- `media` may hold `icon`, `header` and `screenshots` only. They are paths inside the project, PNG,
  JPEG or WebP, up to 2 MiB each, and at most eight screenshots.

Then:

```
printf '%s' "$FARM_TOKEN" | farm login --token-stdin
farm publish
```

`farm login` saves the token to `~/.tiinyapps/token` with owner-only permissions. `--token` for one
run and `FARM_TOKEN` in the environment do the same job, in that order of precedence. `farm
publish` reads `farm.json`, asks for any required value it is missing, packs the folder into
`<id>-<version>.tar.gz` while skipping `.git`, `node_modules`, `__pycache__` and `.venv`, uploads
the local images, and submits. It prints the pull request URL and a link to Your apps. Use `farm
publish --update` for an app that is already listed.

Remember that shell access is refused outright by the archive scan, in every `.py` file in the
archive, examples and tests included. An app that imports `subprocess`, `ctypes`, `os.system` or
`os.exec*` will be sent back whatever it declares.

When `farm publish` cannot be used, the same two calls over HTTP. Upload each image first and keep
the URL it answers with:

```
curl --fail-with-body \
  -H "Authorization: Bearer $FARM_TOKEN" \
  -H "Content-Type: image/png" \
  --data-binary @art/icon.png \
  https://tiinyapp.farm/api/media
```

Then submit the form. `media` and `screenshots` are JSON strings holding the URLs you just got
back, `archive` is a gzip tar up to 50 MB, and you send either `archive` or `releaseUrl` and never
both:

```
curl --fail-with-body \
  -H "Authorization: Bearer $FARM_TOKEN" \
  -F 'id=my-app' \
  -F 'name=My App' \
  -F 'pitch=One useful line' \
  -F 'description=What the app does and what people should know.' \
  -F 'version=0.1.0' \
  -F 'license=MIT' \
  -F 'tags=developer-tools' \
  -F 'entry={"command":"python -m my_app"}' \
  -F 'permissions=network,device' \
  -F 'repo=https://github.com/example/my-app' \
  -F 'archive=@my-app-0.1.0.tar.gz;type=application/gzip' \
  https://tiinyapp.farm/api/seeds
```

```python
import json, urllib.request

def upload(path, content_type, token):
    """One image, answered as a URL to put in the submission form."""
    request = urllib.request.Request(
        "https://tiinyapp.farm/api/media", data=open(path, "rb").read(), method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": content_type,
                 "User-Agent": "your-assistant/1.0"})
    with urllib.request.urlopen(request, timeout=60) as answer:
        return json.load(answer)["url"]
```

An update is the same form sent with `PUT` to `https://tiinyapp.farm/api/seeds/<id>`. Three answers
come back as 202 rather than an error, each carrying a `warning` that says what to do next, so read
it rather than retrying blindly. The complete field list is in the
[API reference](/docs/api/#apps), and every shape is in
[openapi.json](/docs/openapi.json).

Watch the review with `farm status <id> --json`, which needs the token:

```json
{"command": "status", "id": "my-app", "state": "awaiting review",
 "checks": [{"name": "Manifest checks", "status": "success"}],
 "reviews": ["APPROVED"], "prUrl": "https://github.com/...", "unavailable": false}
```

`unavailable` means GitHub could not be read just then and `state` is the farm's stored one.

## Keep a listing current after a release

Once an app is in the catalog, its listing is bumped from its GitHub release rather than uploaded
again. The maker tags the repository, publishes the release on GitHub, and runs `farm release` from
the project folder. That command uses their own GitHub login through the `gh` command, not their
farm token, and opens the pull request from their fork when they cannot push to the catalog. It
measures the checksum and the size from the bytes GitHub serves and never reads a number out of the
release notes.

There is nothing to run on a schedule. The farm checks every listed app hourly and opens the same
pull request on its own. One pull request per app: an open one is refreshed rather than stacked on.
The maker can also press Check for a new release on their app page, and that route takes the
session cookie only, so an assistant with a token cannot press it for them.

Two manifest fields control this, and they are set by pull request rather than from `farm.json`:
`updates` is `auto` by default and `manual` leaves the version alone, and `prereleases` is false by
default, so only full GitHub releases count.

## Ask the farm to draw the art

An app with no icon can have one. Write one sentence saying what is in the picture, and the farm
draws a wide header and a square icon in the same style as every other app on the shelf. Describe
the objects in the scene, not the app.

```
curl --fail-with-body \
  -H "Authorization: Bearer $FARM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scene": "a corkboard of pinned cards joined by threads of light"}' \
  https://tiinyapp.farm/api/seeds/my-app/art
```

```python
import json, urllib.request

request = urllib.request.Request(
    "https://tiinyapp.farm/api/seeds/my-app/art", method="POST",
    data=json.dumps({"scene": "a corkboard of pinned cards joined by threads of light"}).encode(),
    headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
             "User-Agent": "your-assistant/1.0"})
# A drawing takes a minute or two, so give it room.
with urllib.request.urlopen(request, timeout=300) as answer:
    art = json.load(answer)
print(art["header"], art["icon"], art["remaining"])
```

Both images are filed as the maker's own images and answered as URLs you can put straight into
`media`. The scene is 3 to 200 characters on one line, and anything else answers 400 without
spending a try. Three drawings per app per day, one at a time, and a second request while one is
running answers 409. A refusal from the drawing service answers 422 and a failure answers 502, and
neither costs a try. `GET` the same path to read the pair last drawn and how many are left.

## The Tiiny's own API, and how the farm fits around it

The farm installs and runs apps. It is not in the way of the device. Apps talk to the Tiiny
directly at `http://<address>/v1`, which is OpenAI-compatible, with the same key the farm saved.

Every app the farm starts is handed this environment:

| Variable | What it holds |
| --- | --- |
| `TIINY_BASE` | The device base URL from the saved settings |
| `TIINY_KEY` | The device API key |
| `TIINY_HOST` | Just the host part, bracketed when it is an IPv6 literal |
| `TIINYAPP_PORT` | The port the farm chose for this app |
| `FARM_DATA_DIR` | `~/tiinyapps/<id>/data`, which survives an update |
| `TIINY_DATA_DIR` | The same directory, under the name Tiiny apps expect |
| `ONELANE_DIR` | The shared lock directory two apps use to take turns |

So an app written against the farm reads its key and address from the environment rather than
asking anybody:

```python
import json, os, urllib.request

request = urllib.request.Request(
    os.environ["TIINY_BASE"].rstrip("/") + "/chat/completions", method="POST",
    data=json.dumps({"model": "Qwen/Qwen3-8B",
                     "messages": [{"role": "user", "content": "Say hello."}]}).encode(),
    headers={"Authorization": "Bearer " + os.environ["TIINY_KEY"],
             "Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=120) as answer:
    print(json.load(answer)["choices"][0]["message"]["content"])
```

One Tiiny serves one inference at a time. Two apps asking at once is how somebody gets device error
150004, which is what [OneLane](/apps/onelane/) is for: a single file an app copies in beside its
own code, which holds a kernel-level lock so the second request waits its turn. Somebody with more
than one Tiiny can put [AINode Pocket](/apps/ainode-pocket/) in front of the fleet instead, which
serves one OpenAI-compatible endpoint whose `/v1/models` is the union across their devices and
routes each request to a device that has that model loaded.

## What to tell the person at the end

After a publish, give them both links, and nothing more confident than what actually happened:

1. The pull request URL, so they can watch the checks and the review.
2. Your apps, [https://tiinyapp.farm/account/](https://tiinyapp.farm/account/).

After installing and starting something, give them the `url` from the answer, say what the app
declared it can reach, and tell them `farm stop <id>` is how it goes away again.
