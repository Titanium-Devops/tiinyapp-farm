---
title: Manifest reference
slug: manifest
order: 5
summary: Every field of the JSON file that becomes an app's catalog page, with its meaning, its default and its rules.
---

One app is one JSON file at `manifests/<id>.json` in the catalog repository, served at
`https://tiinyapp.farm/manifests/<id>.json`. The site renders it, the installer reads it, and the
pull request checks validate it against
[manifest.schema.json](/docs/manifest.schema.json). The schema refuses any property it does not
know about, at the top level and inside every object.

The filename must match the `id` inside the file.

## Required fields

These fifteen must be present: `id`, `name`, `pitch`, `description`, `version`, `author`,
`license`, `screenshots`, `entry`, `requires`, `permissions`, `tags`, `verified`, `addedAt`,
`updatedAt`. Everything else is optional.

| Field | Type | Meaning and rules |
| --- | --- | --- |
| `id` | string | The name used in `farm install` and in the page URL. Lowercase letters, digits and single dashes, starting with a letter. `tiiny` is reserved. It can never change |
| `name` | string | The name shown in the catalog. Not empty |
| `pitch` | string | One short line explaining what it does. No line breaks. The API caps it at 100 characters |
| `description` | string | Plain words: what it does, who it is for, limits, release readiness |
| `version` | string | `major.minor.patch`, each part a nonnegative number with no leading zero |
| `author` | object | `name` and `url` are required, `tiinyverse` is the owner proof. See below |
| `license` | string | An identifier such as `MIT`. `NOASSERTION` means a license is not confirmed |
| `screenshots` | array | Image URLs, unique. May be empty. `media.gallery` is the newer way to do this |
| `entry` | null or object | How to start the app. See below |
| `requires` | object | `ports` and `device` are required, `python` is optional. See below |
| `permissions` | array | Any of `microphone`, `files`, `network`, `device`, no duplicates. `[]` means none declared |
| `tags` | array | Free text labels, unique, each not empty. Some map to catalog categories |
| `verified` | boolean | Set to `true` only by a maintainer after review. Always `false` in a submission |
| `addedAt` | string | The day the app joined the catalog, `YYYY-MM-DD`. The New badge lasts under 30 days |
| `updatedAt` | string | The day of the most recent manifest change, `YYYY-MM-DD` |

## author

```
"author": {
  "name": "Jason Brashear",
  "url": "https://github.com/webdevtodayjason",
  "tiinyverse": "https://www.tiinyverse.com/users/39628b1e-e94e-4bd8-800e-5437d5336e1f"
}
```

`name` is the verified display name, taken from the TiinyVerse profile rather than typed. `url` is
any public HTTP or HTTPS page. `tiinyverse` is the profile URL the farm verified, and the pull
request checks query the farm for it and refuse an unverified or mismatched owner. Catalog entries
written before the owner gate existed stay readable, but any changed submission has to pass it.

## entry

`entry` says how the app starts, and it has exactly three shapes.

| Shape | Example | What happens |
| --- | --- | --- |
| Python module | `{"python": "lite", "args": ["--port", "7788"]}` | Runs `<interpreter> -m lite --port 7788` |
| Command | `{"command": "python -m my_app"}` | Split into arguments without a shell, then run |
| Library | `null` | Nothing to start. The `library` tag is then required |

A Python module name is dotted identifiers: letters, digits and underscores, not starting with a
digit. `args` is an array of strings. A command entry is split the way a shell would split it, but
no shell is involved, so pipes, redirects and `&&` do not work.

## port

`port` says how the app takes the port `farm start` gives it, so `--port N` works without the CLI
knowing your app by name. It is optional and has three shapes.

| Shape | Example | What happens |
| --- | --- | --- |
| Command line | `{"argv": "--serve"}` | The number goes after that flag, replacing one already there in `entry`, or added if the flag is missing |
| Environment | `{"env": "PORT"}` | That variable is set to the port |
| Fixed | `null` | The port cannot move. `farm start --port N` refuses in one line naming the port |

Leave it out and you get `{"env": "TIINYAPP_PORT"}`, which is what the farm has always done, so an
app that reads `TIINYAPP_PORT` needs nothing here. `TIINYAPP_PORT` is set either way, whatever the
field says. An `argv` flag looks like `--port` or `-p`; an `env` name is letters, digits and
underscores, not starting with a digit. Exactly one of the two keys, never both.

The four catalog apps show all of it: Titanium Tiiny Bot is `{"argv": "--port"}`, TiinyBench is
`{"argv": "--serve"}`, Story Lantern is `{"env": "PORT"}`, and OneLane is `null` because a library
has no port at all.

The submit form does not ask for this field. Set it in a hand-made pull request.

## requires

```
"requires": {
  "python": "3.11",
  "ports": [7788],
  "device": {"models": ["chat", "tts"], "npuUnits": 57}
}
```

| Field | Rule |
| --- | --- |
| `python` | Optional. `major.minor`. The installer refuses to install on an older interpreter. Treated as 3.9 when absent |
| `ports` | Required array of unique integers from 1 to 65535. May be empty. The first one is the primary port |
| `device.models` | Required array of model names the app asks the Tiiny for. May be empty |
| `device.npuUnits` | Required nonnegative integer, what the app expects to use on the device |

## release

```
"release": {
  "url": "https://github.com/example/my-app/archive/refs/tags/v0.1.0.tar.gz",
  "sha256": "32d62db80bd789206753a418f341604304d69a0bfc8c1823f5f3e4ace9af2ab9",
  "size": 168709
}
```

Optional as a whole. An app with no `release` is listed with a "No release yet" badge and cannot be
installed. When it is present, all three fields are required: a URL, a 64 character lowercase hex
SHA-256, and the exact size in bytes as an integer.

`sha256` may be the literal string `pending` in a local draft. A pending manifest only validates
with `--allow-pending`, its description has to explain the pending release, and it can neither pass
the submission checks nor be installed.

`notes` is optional: one line of at most 200 characters saying what changed in this release. It is
the reason `farm update` shows beside a row when it lists what is newer than the apps you have. With
no note, that row carries `updatedAt` instead.

## Optional fields

| Field | Type | Meaning |
| --- | --- | --- |
| `homepage` | string | The app's public home page, HTTP or HTTPS |
| `repo` | string | Source repository URL. Also what the release path reads to find new releases |
| `port` | null or object | How the app takes the port `farm start` gives it. See below |
| `health` | string | An HTTP path on the first declared port, such as `/api/health`. Needs at least one port |
| `selfcheck` | boolean | When true, the checks run your entry with `--selfcheck` offline. Needs a runnable entry |
| `featured` | boolean | Maintainer-curated placement in the Featured section of the home page |
| `media` | object | `icon`, `header` and `gallery` image URLs. At most eight gallery images, unique |
| `links` | object | `repo`, `homepage` and `video`. All HTTPS. `video` is one YouTube watch or `youtu.be` URL |

Image URLs are either an HTTPS URL or a site-relative path beginning `/assets/` or `/media/`.

`media.icon` and `media.header` are either images you upload or the pair the farm drew for you
from a one-sentence scene. Both land in the same field and both reach the catalog through the same
pull request. See [Art in the farm's hand](/docs/art/).

## Fields that control release tracking

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `updates` | string | `auto` | `auto` lets the farm open a bump pull request when the repository publishes a newer tag. `manual` leaves the app alone |
| `prereleases` | boolean | `false` | Whether release tracking considers GitHub prereleases. Drafts are never considered |

## Rules that cross fields

- The filename must equal the `id`, and the `id` must appear exactly once in the whole catalog.
- `entry: null` requires `library` in `tags`.
- `selfcheck: true` requires a runnable entry, so a library cannot declare one.
- `health` requires at least one declared port.
- `port` carries `argv` or `env`, never both, and `null` means the port is fixed.
- `links.video` must carry exactly one eleven character YouTube video id.
- A `pending` checksum requires the word "pending" in the description, and `--allow-pending` on the
  local checker.
- `verified` is written by a human maintainer in a follow-up commit. The checks never change it.

## A complete example

```
{
  "id": "titanium-tiiny-bot",
  "name": "Titanium Tiiny Bot",
  "pitch": "A local assistant with chat, files, memories and voice.",
  "description": "Runs beside your Tiiny on Mac or Linux. Supports --selfcheck.",
  "version": "0.1.13",
  "author": {
    "name": "Titanium Computing",
    "url": "https://titanium.bot",
    "tiinyverse": "https://www.tiinyverse.com/users/39628b1e-e94e-4bd8-800e-5437d5336e1f"
  },
  "license": "MIT",
  "homepage": "https://titanium.bot",
  "repo": "https://github.com/Titanium-Devops/titanium-bot-lite",
  "screenshots": [],
  "release": {
    "url": "https://github.com/Titanium-Devops/titanium-bot-lite/releases/download/v0.1.13/titanium-tiiny-bot-0.1.13.tar.gz",
    "sha256": "d43e15bae4d06640e5487942bc3489e72f84d4b35a9c26a97a7439ee4d7626d1",
    "size": 455721
  },
  "entry": {"python": "lite", "args": ["--port", "7788"]},
  "port": {"argv": "--port"},
  "requires": {
    "python": "3.11",
    "ports": [7788],
    "device": {"models": ["chat", "tts"], "npuUnits": 57}
  },
  "permissions": ["microphone", "files", "network", "device"],
  "tags": ["assistant", "chat", "voice"],
  "health": "/api/health",
  "selfcheck": true,
  "media": {
    "icon": "https://tiinyapp.farm/assets/titanium-icon.png",
    "header": "https://tiinyapp.farm/assets/titanium-header.webp",
    "gallery": []
  },
  "links": {
    "repo": "https://github.com/Titanium-Devops/titanium-bot-lite",
    "homepage": "https://titanium.bot"
  },
  "verified": true,
  "addedAt": "2026-09-12",
  "updatedAt": "2026-09-13"
}
```

## Categories

`tags` are free text, and a few of them place the app in a catalog category. Anything with no
matching tag is shown under Developer tools.

| Category | Tags that map to it |
| --- | --- |
| Assistants | `assistant`, `chat`, `voice` |
| Family | `stories`, `family` |
| Audio | `audio` |
| Developer tools | `developer-tools`, `coordination`, `benchmark`, `measurement` |
| Libraries | `library` |

## Check it yourself

```
python3 scripts/check-manifest.py manifests/your-app.json
python3 scripts/check-manifest.py --allow-pending manifests/your-app.json
```

The checker implements exactly the subset of JSON Schema this file uses, on the standard library,
and the Worker validates submissions against the same schema file with the same rules.
