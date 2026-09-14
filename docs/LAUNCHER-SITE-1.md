# LAUNCHER-SITE-1: the site, the Worker and the update feed for the launcher

Jason, 2026-09-14 13:57: "Build it." The launcher itself is being built in another repo by another worker.
This wave is the farm side: docs/LAUNCHER.md section "What the site shows a consumer who has no CLI" and
"Auto update" and decision 6. Read /Users/sem/code/tiinyapp-farm-main/docs/LAUNCHER.md first.

## Fixed names

Product "Tiiny App Farm" (the launcher), identifier farm.tiinyapp.launcher, deep link scheme `tiinyfarm`
(`tiinyfarm://install/<id>`). Feed https://tiinyapp.farm/launcher/latest.json (Tauri updater JSON shape),
artifacts at https://tiinyapp.farm/launcher/<file>, both served by the existing Worker from the R2 bucket
farm-seeds under the key prefix `launcher/` (the same way /seeds-files/ serves `seeds/`). Mac and Windows
x64 only; the download page says plainly that Linux uses the CLI.

## Deliverables

1. Worker: GET /launcher/latest.json and /launcher/<file> from R2 `launcher/...`, correct content types,
   immutable cache for versioned artifact names, no cache for latest.json, 404 in words when absent. Tests
   in tests/worker.test.mjs.
2. Site (scripts/build-site.py): the launcher is OFF until a feed exists. Add one switch, a `launcher`
   block read from a small JSON file in the repo (say site/launcher.json: {"enabled": false, "version":
   null, "mac": null, "windows": null}). When enabled: /install/ opens with the platform-detected download
   button (the other platform as a small link underneath) and the three pip/pipx steps move under "Prefer
   the command line?"; every app page gets a primary "Open in Tiiny App Farm" button that follows
   tiinyfarm://install/<id> with the CLI block as the visible fallback and a one-line "Get the launcher"
   link; the home hero's second button becomes "Get the launcher". When disabled (today), the pages render
   exactly as they do now, byte for byte where possible, so this PR is safe to merge before the launcher
   ships. Tests in tests/test_site.py for both states.
3. Docs: a page docs/site/12-launcher.md ("The launcher") in the same voice as the others: what it is,
   Mac and Windows, one download, same install directory and device file as the CLI, how to switch to the
   CLI later, what it never does (no sandbox, no Docker, no databases that are servers), and a
   troubleshooting line for Gatekeeper/SmartScreen. Add it to the docs nav. It is fine for it to say
   "not released yet" while site/launcher.json is disabled; word it so one edit removes that.
4. A short recipe in docs/SUBMIT.md or docs/site/04-publish.md telling makers an icon and a `health` path
   are now strongly recommended, and why (the launcher grid is icon first; health lets it say ready).

## Proof

Build the site locally (python3 scripts/build-site.py), diff the built output against main with the switch
off (expect no page changes except the new docs page and nav), then with the switch on in a scratch copy:
screenshots of /install/, one app page and the home hero at 1440 and 390 into docs/launcher-site-shots/,
no horizontal scroll, buttons reachable. Worker tests and Python tests green.

## Rules

Work in /Users/sem/code/tiinyapp-farm-launcher-site (create it with
`git -C /Users/sem/code/tiinyapp-farm-main worktree add -b launcher-site /Users/sem/code/tiinyapp-farm-launcher-site main`).
Never touch /Users/sem/code/tiinyapp-farm (another session uses it) or tiinyapp-farm-main. Do not deploy the
Worker; do not merge; open a PR against main and report. No version bump. No em dashes in anything a person
reads. Spell it Tiiny. Keep the "Grown by" farm feeling. Every `gh` call needs `< /dev/null`. Timeouts on
everything. Report measured facts separated from plans.
