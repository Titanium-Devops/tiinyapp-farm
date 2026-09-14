---
title: API reference
slug: api
order: 8
summary: Every route the farm serves, how requests are authenticated, what the limits are, and what an error looks like.
---

The farm runs as a Cloudflare Worker in front of a static site. Everything under `/api/`, plus the
account, maker and app file routes, is handled by the Worker; everything else is a static file.

The base is `https://tiinyapp.farm`. Responses are JSON with `Cache-Control: no-store` unless
stated otherwise.

## Authentication

There are two credentials and they are not interchangeable.

**A session cookie.** Signing in with an email code or with GitHub sets `__Host-farm`, which is
HttpOnly, Secure, SameSite=Lax and lasts 30 days. The site uses it. Signing in again replaces the
previous session rather than adding one.

**A bearer token.** Create one on [Your apps](/account/), copy it once, and send it as
`Authorization: Bearer farm_...`. A token is `farm_` followed by 40 hexadecimal characters. Only
four routes accept one:

| Method | Path |
| --- | --- |
| POST | `/api/seeds` |
| PUT | `/api/seeds/<id>` |
| POST | `/api/media` |
| GET | `/api/seeds/mine` |

Everywhere else a token is ignored and the cookie decides. Creating and revoking tokens needs the
cookie, so a token cannot mint another token. Tokens are stored as SHA-256 hashes, never in the
clear, and each use records the time it was last used.

**The origin rule.** Any POST, PUT, PATCH or DELETE that does not carry a bearer token on one of
those four routes must send `Origin: https://tiinyapp.farm`, or it is refused with 403 and
`Please submit this form from tiinyapp.farm.` This is what stops another site posting with a
visitor's cookie.

## Sign in

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| POST | `/api/auth/start` | `{"email": "you@example.com"}` | `{"sent": true}` and emails a six digit code |
| POST | `/api/auth/verify` | `{"email": "...", "code": "123456"}` | `{"user": {...}}` and sets the session cookie |
| GET | `/api/auth/github` | none | 302 to GitHub's authorize page |
| GET | `/api/auth/github/callback` | none | 302 to `/submit/` and sets the session cookie |
| POST | `/api/auth/logout` | none | `{"signedOut": true}` and clears the cookie |
| GET | `/api/me` | none | `{"user": {...}}`, or `{"user": null}` when signed out |

A code lasts ten minutes and dies after five wrong attempts. Three codes per hour per address. If
you are already signed in when you start either flow, finishing it links that method to your
existing account rather than making a second one; finishing it from a different account is refused
with 403.

Email sign-in answers 503 when the mail credential is not configured, and GitHub sign-in answers
503 when its client id and secret are not.

## Prove you own a Tiiny

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| POST | `/api/tiinyverse/link` | `{"profileUrl": "https://www.tiinyverse.com/users/<uuid>"}` | The code to put in your bio, when it expires, and what to do |
| POST | `/api/tiinyverse/verify` | none | `{"tiinyverse": {"profileUrl": "...", "name": "...", "verifiedAt": "..."}}` |
| GET | `/api/owners?profile=<url>` | none | `{"verified": true, "name": "..."}` |

The code lasts 24 hours. Verify fetches your public profile, looks for the exact code as a whole
word, and reads your display name from the page heading. A profile already claimed by another
account answers 409, an unreadable or private profile answers 422, and a missing code answers 422
with an instruction to add it and try again.

`/api/owners` is the public lookup the pull request checks use to confirm a manifest's owner. It
needs no credential and is the one route that skips the Worker's request queue, so it stays
responsive during an upload.

## Your account

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| POST | `/api/tokens` | `{"name": "Laptop"}` | 201 with `{"token": "farm_...", "id", "name", "prefix", "createdAt", "lastUsedAt"}` |
| GET | `/api/tokens` | none | `{"tokens": [{"id", "name", "prefix", "createdAt", "lastUsedAt"}]}` |
| DELETE | `/api/tokens/<id>` | none | `{"revoked": true}` |
| POST | `/api/maker` | `{"bio": "...", "links": {...}, "avatarKey": null}` | `{"user": {...}}` |
| PUT | `/api/maker/visibility` | `{"public": true}` | `{"public": true}` |

The full token is in the creation response and nowhere else afterwards; only its `prefix` is kept
for display. Five live tokens per account. Creating one needs a verified Tiiny profile.

A bio is at most 600 characters. Maker links are `github`, `website` and `youtube` only, and each
must be an HTTPS URL. An avatar key must be an image you uploaded to your own account. Turning your
profile off leaves your maker page reachable only to signed-in visitors.

## Images

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| POST | `/api/media` | The image bytes, with an image content type | 201 with `{"key": "media/...", "url": "https://tiinyapp.farm/media/..."}` |
| DELETE | `/api/media/<key>` | none | `{"deleted": true}` |
| GET, HEAD | `/media/<key>` | none | The image |

Up to 2 MiB. The type is read from the file's own first bytes, not its name, and only PNG, JPEG and
WebP are accepted; anything else answers 415. Uploading needs a verified Tiiny profile. You can
only delete your own images. Served images are immutable and cached for a year.

```
curl --fail-with-body \
  -H "Authorization: Bearer $FARM_TOKEN" \
  -H "Content-Type: image/png" \
  --data-binary @art/icon.png \
  https://tiinyapp.farm/api/media
```

## Art in the farm's hand

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| POST | `/api/seeds/<id>/art` | `{"scene": "one sentence"}` | 201 with `{"header", "icon", "scene", "remaining"}` |
| GET | `/api/seeds/<id>/art` | none | The pair last drawn for this app, its scene, and `remaining` |

The farm draws a wide header and a square icon in its house style from one sentence describing the
scene. Both are filed as your images under `media/<you>/<id>/` and answered as URLs you can put
straight into `media`. See [Art in the farm's hand](/docs/art/) for what to write.

The scene is 3 to 200 characters on one line; anything else answers 400 without spending a try. You
need a verified Tiiny profile, and the app ID has to be yours or unclaimed, or the answer is 403.
Three drawings per app per day, and one at a time per app: a second request while one is running
answers 409. A drawing takes a minute or two, so give the call a generous timeout. A refusal from
the drawing service answers 422 and a failure answers 502, and neither costs you a try.

```
curl --fail-with-body \
  -H "Authorization: Bearer $FARM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scene": "a corkboard of pinned cards joined by threads of light"}' \
  https://tiinyapp.farm/api/seeds/my-app/art
```

## Apps

| Method | Path | Sends | Answers |
| --- | --- | --- | --- |
| POST | `/api/seeds` | `multipart/form-data` | 201 with `{"id", "prUrl", "statusUrl"}` |
| PUT | `/api/seeds/<id>` | `multipart/form-data` | The same, for an app you already own |
| GET | `/api/seeds/mine` | none | `{"seeds": [...]}`, your submissions with their checks and reviews |

These are the routes `farm publish` and `farm status <id>` use. The form fields are:

| Field | Meaning |
| --- | --- |
| `id` | The app id. It cannot change on an update |
| `name`, `pitch`, `description`, `version`, `license` | The catalog text. `version` is three numbers |
| `tags` | A comma separated list. The site sends one category |
| `permissions` | A comma separated list of `microphone`, `files`, `network`, `device` |
| `command` | A start command, or `entry` as JSON, or `entry=null` for a library |
| `repo`, `homepage`, `video` | Optional HTTPS links |
| `media` | JSON of already-uploaded image URLs: `icon`, `header`, `gallery` |
| `screenshots` | JSON array of already-uploaded image URLs |
| `python`, `ports`, `models`, `npuUnits` | Runtime needs. `ports` and `models` are comma separated |
| `health`, `selfcheck` | Optional health path, and `selfcheck=true` to declare the offline check |
| `releaseUrl` | A public HTTPS URL that downloads the `.tar.gz` directly |
| `archive` | Or the `.tar.gz` itself, up to 50 MB, with a simple filename |

Send a release URL or an upload, never both. A release URL is fetched with a ten second deadline
and may redirect up to three times; the URL must be HTTPS on port 443, with no credentials, no
fragment, and a real public hostname. The first two bytes of whatever arrives must be gzip. The
farm measures the SHA-256 and the exact size itself; numbers you supply are not used.

An update must carry a strictly newer version when it changes the release, and may keep the current
version for a text-only change.

```
curl --fail-with-body \
  -H "Authorization: Bearer $FARM_TOKEN" \
  -F 'id=my-app' \
  -F 'name=My App' \
  -F 'pitch=One useful line' \
  -F 'description=What the app does and what users should know.' \
  -F 'version=0.1.0' \
  -F 'license=MIT' \
  -F 'tags=developer-tools' \
  -F 'entry={"command":"python -m my_app"}' \
  -F 'permissions=network,device' \
  -F 'repo=https://github.com/example/my-app' \
  -F 'archive=@my-app-0.1.0.tar.gz;type=application/gzip' \
  https://tiinyapp.farm/api/seeds
```

Each entry in `GET /api/seeds/mine` carries `id`, `name`, `version`, `icon`, `state`, `prUrl`, a
`checks` array of `{name, status}`, a `reviews` array, `thumbs`, `comments`, and `canUpdate`. When
GitHub cannot be reached the entry carries `unavailable: true` and its stored state instead. States
you will see are `preparing`, `label pending`, `awaiting review`, `draft`, `closed`, `merged`,
`published`, `submission failed` and `submission uncertain`.

Three answers are 202 rather than an error, and each says what to do: an interrupted review request
that may still have succeeded, a submission that reached review but whose label did not, and the
same form sent again to retry that label.

## Comments and thumbs up

| Method | Path | Answers |
| --- | --- | --- |
| GET | `/api/seeds/<id>/social` | `{"thumbs": 0, "mine": false, "comments": [...]}` |
| POST | `/api/seeds/<id>/thumb` | The same view, with your thumb toggled on or off |
| POST | `/api/seeds/<id>/comments` | 201 and the same view |
| DELETE | `/api/seeds/<id>/comments/<commentId>` | The same view |

Reading needs nothing. A thumb needs a signed-in account. A comment needs a verified Tiiny profile,
is 1 to 1,000 characters, and is limited to five per hour; deleting your comments does not give the
limit back. A comment can be deleted by its author or by a farm admin. Only apps in the deployed
catalog have a conversation, so an unknown id answers 404, and the wrong method for a route answers
405.

Each comment comes back as `{id, author: {handle, name, avatar}, text, at, canDelete}`. The author
name falls back to "A maker" when a profile is not readable, and an email address is never part of
it.

## Check for a new release

| Method | Path | Answers |
| --- | --- | --- |
| POST | `/api/seeds/<id>/release-check` | `{"status", "message", "checkedAt", "version", "prUrl"}` |

Only the app's own verified maker may call it, and only once a minute per app; a second call inside
that minute answers 429 with the number of seconds left. `status` is one of `found`, `listed`,
`none`, `manual` or `untracked`, and `message` is the sentence shown to the maker. A `found` answer
also carries the pull request URL. Without the farm's GitHub App credentials the two answers that
need no credential still work and anything further answers 503.

## Files and pages the Worker serves

| Path | What |
| --- | --- |
| `/media/<key>` | An uploaded image, immutable, cached for a year |
| `/seeds-files/<id>/<version>/<name>.tar.gz` | An archive uploaded through the site, served as a download |
| `/makers/<handle>/` | A maker's public page, built live from the catalog |
| `/makers/<handle>/card.png` | That maker's share card |
| `/account/` | Your apps. Redirects to `/submit/` when you are not signed in |
| `/manifests/<id>.json` | One app manifest, the file the installer reads |
| `/catalog.json` | Every manifest in one array |
| `/categories.json` | The tag to category map and the category order |
| `/llms.txt` | The publishing guide as plain text, for assistants |

Three old paths answer 301: `/plant` to `/install/`, `/seeds` to `/submit/`, and `/farm` to
`/account/`.

## Rate limits and sizes

| Thing | Limit |
| --- | --- |
| Email codes | 3 per hour per address |
| Submissions | 5 per hour per account |
| Comments | 5 per hour per account |
| Release checks | 1 per minute per app |
| App art | 3 per app per day, one drawing at a time |
| API tokens | 5 live per account |
| JSON request body | 16 KiB |
| Image upload | 2 MiB |
| Archive upload | 50 MB, 30 seconds |
| A form text field | 12,000 characters |
| Comment text | 1,000 characters |
| Bio | 600 characters |
| Any outbound fetch the farm makes | 10 seconds, and a bounded body |
| Drawing one image | 2 minutes, and a bounded body |

## Errors

Every failure is JSON with one `error` field holding a sentence meant for a person:

```
{"error": "Verify you own a Tiiny before submitting an app."}
```

| Status | Means |
| --- | --- |
| 400 | The request was wrong: a bad field, a missing value, an invalid manifest |
| 401 | Sign in first |
| 403 | Signed in but not allowed: not the owner, not a verified Tiiny owner, or a missing origin |
| 404 | No such route, app, comment or token |
| 405 | Right path, wrong method |
| 408 | An upload or a fetch took too long |
| 409 | A conflict: an id someone else owns, a profile already claimed, a sixth token |
| 413 | Too large |
| 415 | Wrong content type |
| 422 | Something outside the farm did not cooperate: an unreadable profile, a release link that did not answer 200 |
| 429 | A rate limit. The message says how long to wait |
| 502 | GitHub, the mail service or another dependency failed |
| 503 | A credential is not configured on the farm yet |

An unexpected error answers 502 with `The request could not be completed. Please try again.` rather
than the underlying text, because those can contain credentials.
