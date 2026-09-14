---
title: Publish an app
slug: publish
order: 4
summary: Prove you own a Tiiny, submit your app, pass the checks, and keep the listing current after a release.
---

Every app in the catalog was submitted by a person who proved they own a Tiiny, passed a set of
automated checks, and was merged by a maintainer. Nothing is published automatically. There are
three ways in, and they all end at the same pull request on the catalog repository.

## Sign in

Go to [Submit an app](/submit/) and sign in with an email code or with GitHub. While signed in you
can use the other method as well to attach it to the same account, and afterwards either one brings
you back to the same place.

An email code is six digits and lasts ten minutes. Five wrong attempts retire it. Three codes per
hour per address is the limit, so if you ask again too soon you are told to wait.

Neither sign-in method is proof that you own a Tiiny. That is the next step.

## Prove you own a Tiiny

Paste the public TiinyVerse profile URL for your account. It has to be the
`https://www.tiinyverse.com/users/<uuid>` form. The farm gives you a short code that looks like
`farm-1a2b3c`. Put it anywhere in your TiinyVerse bio, save your profile, and press Verify within
24 hours.

The farm reads your public profile, looks for that exact code, and takes your display name from the
page. That name becomes the maker name on your apps; you do not type it. One TiinyVerse profile
belongs to one farm account, and a profile already claimed by someone else is refused.

This is the same idea as a DNS TXT record: you put a value somewhere only the owner can edit, and
the other side reads it once.

## Submit through the site

[Submit an app](/submit/) is two short pages, with a live preview of the card people will see.

**About and look.** Name, id, one-line summary, what it does, a category, a license, and optionally
an icon, a header image and up to eight screenshots. Images are PNG, JPEG or WebP up to 2 MiB each.
No art yet? Write one sentence describing your app's scene and press Generate art, and the farm
draws a header and an icon in the same style as every other app on the shelf. See
[Art in the farm's hand](/docs/art/).
The id is lowercase letters, digits and single dashes, it becomes your page URL and your
`farm install` command, and it can never change.

**Release and needs.** A version, then either a direct HTTPS link to a `.tar.gz` or an upload of
one, a start command, the access the app uses, and optional links to a repository, a home page and
a YouTube video. Choosing "Not yet" lists the app with a "No release yet" badge and lets you add
the release later from Your apps. Leaving the start command empty makes it a library: it can be
installed, but there is nothing to run.

A few limits worth knowing before you press the button:

- An upload is at most 50 MB and has to finish inside 30 seconds.
- A release URL is fetched with a 10 second deadline and may redirect up to three times, which is
  what GitHub release downloads do.
- Send one or the other. Both together is refused.
- The archive must really be gzip. The first two bytes are checked.
- Five submissions per hour per account.

The farm measures and hashes the archive itself, writes the manifest, opens a pull request from its
own account, and shows you the checks and the review state on [Your apps](/account/).

The form does not ask for ports, device models or NPU units, so an app submitted this way lists
none of them. Add them in a follow-up manifest change if your app needs them stated.

## Submit from a shell

Create an API token on [Your apps](/account/) first. You can hold five at a time, each one is shown
once, and you need a verified Tiiny profile to make one. Then:

```
pip install tiinyapp-farm
farm login
farm publish
```

`farm publish` reads `farm.json` in the current folder and asks for anything required that is
missing. This is the whole shape of that file; unknown fields are refused.

```
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

| Field | Rule |
| --- | --- |
| `id` | Required. Lowercase letters, digits, single dashes, starting with a letter. `tiiny` is reserved |
| `name` | Required, not empty |
| `pitch` | Required, one line, 100 characters or fewer |
| `description` | Required, not empty |
| `version` | Required. Three nonnegative numbers, `major.minor.patch` |
| `license` | Required. Prefer an SPDX identifier such as `MIT` |
| `category` | Required. One of `assistant`, `family`, `audio`, `developer-tools`, `library` |
| `entry` | Required. `null` for a library, a command string, `{"command": "..."}`, or `{"python": "package.module", "args": []}` |
| `permissions` | Required. Any of `microphone`, `files`, `network`, `device`. Use `[]` for none |
| `links` | Optional. `repo`, `homepage` and `video` only, all HTTPS |
| `media` | Optional. `icon`, `header` and `screenshots`, as paths inside the project |

The command packs the current folder into `<id>-<version>.tar.gz`, skipping `.git`,
`node_modules`, `__pycache__` and `.venv`, refuses any single file over 50 MB and a packed archive
over 50 MB, uploads the images first, then posts the archive. It prints the pull request URL and
your Your apps link. Use `farm publish --update` for an app you have already published, and
`farm status <id>` to read the checks later.

Everything `farm publish` does is also available directly over HTTP. See the
[API reference](/docs/api/).

## Submit by hand with git

You can also open the pull request yourself. Verify your profile on the farm first, because the
checks query the farm for the owner and refuse an unverified or mismatched one.

1. Publish your source and a versioned `.tar` or `.tar.gz` release archive. Put your license and
   everything the app needs to start inside it. Do not bundle API keys, tokens, private keys,
   virtual environments or local user data.
2. Copy a manifest into `manifests/your-app.json`. The filename must match the `id` inside it.
   Follow the [manifest reference](/docs/manifest/).
3. Set `author.tiinyverse` to your exact verified profile URL and `author.name` to the display name
   the farm verified. Leave `verified` false; only a maintainer changes that.
4. Fill in the release URL, the SHA-256 and the exact size in bytes. A `pending` checksum cannot
   pass the checks.
5. Run the local checks, then open the pull request.

Both release numbers can be worked out from the archive itself:

```
python3 - <<'PY'
from pathlib import Path
import hashlib
archive = Path('your-app-0.1.0.tar.gz')
print('sha256:', hashlib.sha256(archive.read_bytes()).hexdigest())
print('size:', archive.stat().st_size)
PY
```

The local checks are the same code the pull request runs:

```
python3 scripts/check-manifest.py manifests/your-app.json
python3 scripts/scan-archive.py your-app-0.1.0.tar.gz manifests/your-app.json
python3 -m unittest
```

## What the checks do

Every added or changed manifest in a pull request is checked, including the destination of a
rename. Deleted manifests need no archive check. The validation code comes from the pull request's
base branch, never from the submitted branch, so a submission cannot change the rules it is judged
by.

| Check | What it means |
| --- | --- |
| schema | The manifest validates against the schema, with no `pending` checksum allowed |
| identity | The `id` matches the filename and appears exactly once in the whole catalog |
| Tiiny owner | The farm confirmed the verified TiinyVerse owner named in the manifest |
| download | The release downloaded, and its SHA-256 and exact byte size match the manifest |
| archive | It unpacked with the path, link, special-file and size guards |
| imports | The list of Python imports found in the archive, for a human to read |
| static scan | No forbidden code and no secret patterns. See [Permissions and archive rules](/docs/permissions/) |
| microphone | Whether microphone access is declared. It is never detected |
| selfcheck | Your offline check ran and exited 0 inside 120 seconds |

An app with no release skips download, archive, static scan and selfcheck. A selfcheck only runs
after a clean static scan. Any red row fails the job.

The bot keeps one comment on the pull request with a check, result and detail column, and the full
results are in the run's artifact. Your app's own output and any secret match are withheld from the
logs and the comment, so a failure tells you the kind of problem without republishing your secret.
Fix it and push again.

## Review and merge

Passing the checks is not approval. A static scan cannot prove code is safe: aliases, generated
code, behaviour that is not Python, and token formats nobody has listed all slip past pattern
matching. It also does not enforce anything at install time on someone's computer.

A maintainer reads the source and the results, then decides. `verified: true` is written by a human
in a follow-up commit, never by the checks. Merging rebuilds the site and publishes the catalog
entry.

## Update a listing

Use Update on [Your apps](/account/) for an app you own, or open a pull request with the same owner
proof. The id can never change. When a change carries a new release the version must be strictly
newer; a text-only change may keep the current version.

If a review request is interrupted halfway, the app shows as `submission uncertain`. A maintainer
reconciles the saved branch before you retry, and your uploaded archive is kept.

## Keep the listing current after a release

Once an app is listed, a new version reaches the catalog from the app's own GitHub release rather
than by typing a manifest. Publish the release, then use any of three doors:

- The farm checks every listed app once an hour and opens the pull request on its own.
- Press **Check for a new release** on your app page or on Your apps while signed in. It runs the
  same check for that one app straight away, at most once a minute.
- Run `farm release` in the project folder, or `farm release <id>` anywhere. It uses your own GitHub
  login through the `gh` command and opens the pull request from your fork if you cannot push to
  the catalog.

All three take the newest full release of the repository named in your manifest, download that
archive, measure its SHA-256 and exact byte size, and move `version`, `release.url`,
`release.sha256`, `release.size` and `updatedAt`. Numbers written in release notes are ignored.
There is one pull request per app: an open one is refreshed rather than another opened beside it.
A maintainer still reviews and merges, and the usual checks run.

Your release tag must be three numbers with an optional leading `v`, so `v0.1.1` or `0.1.1`. The
archive that gets listed keeps the shape of the one already listed: a source archive stays a source
archive for the new tag, and a named release asset stays an asset, matched by file name with the
version swapped.

Two optional manifest fields control this, and they are set by pull request:

- `"updates": "manual"` stops release tracking for the app. The default, `"auto"`, tracks it.
- `"prereleases": true` lets a GitHub prerelease count. The default, `false`, ignores them. A draft
  release is never used.

The button answers in three lines depending on what it finds: `v0.1.1 found, checks running, a
maintainer will review it`, `already listed at v0.1.1`, or `no release newer than v0.1.0 on
GitHub`.

## Limits in one place

| Limit | Value |
| --- | --- |
| Email sign-in codes | 3 per hour per address, each valid 10 minutes, 5 attempts |
| TiinyVerse bio code | Valid 24 hours |
| Submissions | 5 per hour per account |
| Release checks from the button | 1 per minute per app |
| API tokens | 5 per account, each shown once |
| Uploaded archive | 50 MB, 30 seconds to finish |
| Release URL fetch | 10 seconds, up to 3 redirects |
| Image upload | 2 MiB each, PNG, JPEG or WebP |
| Comments | 5 per hour per account, 1,000 characters each |
