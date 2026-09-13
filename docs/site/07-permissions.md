---
title: Permissions and archive rules
slug: permissions
order: 7
summary: The four kinds of access an app declares, what the scanner refuses and why, and a worked example of a real refusal.
---

Two separate things protect somebody installing an app: what the author declares, which the
installer shows before anything is downloaded, and what an automated scan can see in the source,
which decides whether a submission goes red. Neither is a sandbox. This page is what both actually
do.

## The four permissions

An app declares any of four values in `permissions`. They are what the catalog page and the install
prompt show, in these words.

| Value | Shown as | Means |
| --- | --- | --- |
| `microphone` | Microphone | Can listen through your microphone |
| `files` | Files | Can read or write files on your computer |
| `network` | Network | Can make network connections |
| `device` | Your Tiiny | Can send requests to your Tiiny |

Declare everything you use. `[]` is a valid answer for an app that uses none of them.

## What the scan reads

The scan runs on the unpacked archive during a pull request, and you can run the same code locally:

```
python3 scripts/scan-archive.py your-app-0.1.0.tar.gz manifests/your-app.json
```

It does two passes. Every file in the archive, including dotfiles and files that are not Python, is
read as bytes and matched against a small set of secret patterns. Every `.py` file is parsed into a
syntax tree and its imports and calls are examined. A Python file that will not parse is itself a
finding.

Nothing that matches is ever echoed. The report names the kind of thing found and the file, never
the value, so a failed check does not republish your secret in a public log.

## Secret patterns

| Pattern | What it catches |
| --- | --- |
| AWS access key | `AKIA` or `ASIA` followed by 16 uppercase characters |
| GitHub token | `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_` and `github_pat_` prefixes |
| OpenAI key | `sk-`, including the `sk-proj-` and `sk-svcacct-` forms |
| Bearer token | The word `Bearer` followed by sixteen or more token characters |
| Private key | A `BEGIN ... PRIVATE KEY` header of any kind |

Keep credentials in runtime configuration. The device key reaches your app through the environment,
so there is never a reason for one to be in the archive.

## Network needs the network permission

Importing any of these, at any depth, requires `network` in `permissions`:

`socket`, `ssl`, `http`, `urllib.request`, `urllib3`, `requests`, `httpx`, `aiohttp`, `websockets`,
`ftplib`, `smtplib`, `asyncio`

A local listener counts. An app that serves a page on `localhost` is making network connections as
far as this check is concerned, and it should say so.

## Shell access is forbidden outright

There is no `shell` permission. These are refused whatever you declare:

| Flagged | Why |
| --- | --- |
| `import subprocess`, or any `subprocess.*` import | Running another program is shell access |
| `os.system`, `os.popen` | The same, by another name |
| `os.exec*`, `os.spawn*`, `os.posix_spawn*` | The same |
| `import ctypes`, or any `ctypes.*` import | Native code access is outside anything the scan can read |
| `eval`, `exec`, `__import__`, `importlib.import_module` | Code the scan cannot see until it runs |

Aliased imports are followed, so `import subprocess as sp` and `from os import system as run` are
both caught.

An app that genuinely needs to run another program does not belong in the catalog as it stands.
Adding a permission will not help, because there is no permission that grants it.

## Microphone is declared, never detected

There is no reliable way to spot microphone use in a static read of source, so the check reports
whether you declared it and says so plainly. This one rests on your honesty and on the maintainer
reading your code.

## Archive rules

The same rules apply when a submission is checked and when somebody installs the app, because it is
the same unpacking code.

| Rule | Limit |
| --- | --- |
| Download | 512 MiB |
| Unpacked contents | 2 GiB |
| Entries | 100,000 |
| Uploaded archive through the site | 50 MB |
| Manifest file | 1 MiB |

Refused outright: absolute paths, `..` in a path, backslashes in a name, a colon in any path part,
symlinks, hard links, device files and fifos, the same file path twice, Windows reserved names, and
parts that end in a dot or a space. The checksum and the exact byte size must match the manifest
before anything is extracted, and a mismatch means the archive is never unpacked and never run.

## A worked example

> The refusals below are live today. The two pull requests that show them come from the release
> path on [#5](https://github.com/Titanium-Devops/tiinyapp-farm/pull/5), which has not merged yet.

OneLane and Story Lantern were both tagged 0.1.1 and both bump pull requests went red. Schema,
identity, owner, download and archive all passed on both. The static scan is what failed them:

- OneLane 0.1.1 imports `subprocess` in `examples/two_apps.py` and in `tests/fake_device_test.py`.
- Story Lantern 0.1.1 imports it in `device.py` at line 39, which is new in that version.

Neither import is in the code path that runs on somebody's machine. One is an example, one is a
test, one is a device helper. The scan does not care, because it reads every `.py` file in the
archive and shell access has no permission that grants it.

OneLane 0.1.0 is already listed and fails the same scan today, so this is not something 0.1.1
introduced there. It is what happens when a rule is added after entries exist.

There are two honest ways out and both are a maintainer's call: the apps drop `subprocess` and cut
0.1.2, or the scan changes, for instance by ignoring `examples/` and `tests/` or by adding a
declared permission. Nothing has been decided, and both pull requests are open.

## What none of this proves

A static scan is a filter, not a guarantee. Generated code, aliases it does not follow, behaviour
that is not Python at all, and token formats nobody has listed will all pass it. And once an app is
installed, nothing enforces its declared permissions: the installer shows them and gets a yes, it
does not contain the app afterwards.

That is why a human reads the source before `verified` is set, and why every app in the catalog
ships its source for anyone else to read too.
