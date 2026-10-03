# Contacting tiinyapp.farm support

You are an agent helping a person with tiinyapp.farm. Diagnose first, then draft a request the person can submit. The goal is a request that a maintainer can act on without first asking for basic facts.

There is no support API. Do not open, submit, comment on or poll a support issue unless the person asked you to. The agent drafts and the human submits.

## Diagnose before drafting

Work through these in order and stop when the problem is answered.

1. Check `https://tiinyapp.farm/api/health`. If it reports a failed service, record the exact UTC time and wait for recovery before filing a duplicate outage report.
2. Read the exact error. Do not replace it with a guess. For command-line failures, run the same command with `--json` when that command supports it.
3. Run `farm --version`, then `farm doctor --json`. Keep the version and only the relevant findings. Do not include credentials or an entire log.
4. Check `https://tiinyapp.farm/docs/troubleshooting/` and `https://tiinyapp.farm/docs/cli/`.
5. For an app, read `https://tiinyapp.farm/manifests/<app-id>.json`. Record the app id, listed version, installed version, operating system, Python version and the command that failed.
6. For publishing, record the app id, pull request URL, check name and check result. Read `https://tiinyapp.farm/docs/publish/` before contacting a maintainer.
7. For an API call, read `https://tiinyapp.farm/docs/openapi.json`. Record the HTTP method, path, status, response body, authentication kind and the request time in UTC. Never include a cookie, bearer token or request body containing private data.

Contact a maintainer only when the documentation and public state do not explain the problem, or when only a maintainer can change account state, ownership, review state or service configuration.

## What to include

- The exact failure and what should have happened instead.
- An ISO 8601 UTC timestamp, such as `2026-10-03T20:15:00Z`.
- Farm CLI version, app id and app version when relevant.
- Operating system and Python version for command-line problems.
- The exact command with every secret value replaced by `REDACTED`.
- The exact error, HTTP status and relevant response body.
- Pull request URL and named check for submission problems.
- Two or three example occurrences for an intermittent problem.
- What you already checked and what documentation was missing or unclear.

## What to leave out

Do not include Tiiny API keys, farm tokens, sign-in codes, session cookies, Resend keys, private repository credentials, personal email addresses, message bodies, whole archives, complete logs or private app data. Keep only the few log lines that establish the failure, with secrets and personal data removed.

Do not claim the agent contacted a maintainer, opened an issue or verified a fix unless that action really happened and the person authorized it. Do not create a second issue for the same problem.

## Draft the request

The first line of every body is exactly this shape:

`Drafted with <tool> (AI agent)`

Replace `<tool>` with the tool that prepared the draft. Ask the person to keep that line when submitting it.

Use a subject that names the failure. Keep the body short, factual and complete:

```text
Subject: farm install example-app returns checksum mismatch on 0.2.1

Drafted with <tool> (AI agent)

farm install example-app expected to install the listed 0.2.1 release, but it stopped before unpacking with "checksum mismatch".

- Time: 2026-10-03T20:15:00Z
- Farm CLI: 0.1.17
- App: example-app 0.2.1
- System: macOS 26.0, Python 3.12.7
- Command: farm install example-app --json --yes
- Error: <exact redacted JSON error>
- Impact: the app cannot be installed

Tried first: checked the manifest, reran once, ran farm doctor --json and read the troubleshooting guide. The manifest and downloaded archive still disagree.
```

## Where the person submits it

The preferred channel is email. The person sends the draft to `support@titaniumcomputing.com` from the email address on their farm account. The agent drafts the message and the human submits it.

For a public bug or documentation problem only, the person may open or reply to one issue at `https://github.com/Titanium-Devops/tiinyapp-farm/issues`. Search existing issues first. Do not put account information or private details in a public issue.

Replies go to the person's farm-account email address, not to the drafting agent. Support hours are Monday through Friday, 9 AM to 5 PM Central time. Keep one issue per thread and do not promise a response outside those hours.
