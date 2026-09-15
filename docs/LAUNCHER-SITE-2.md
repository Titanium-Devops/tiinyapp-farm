# LAUNCHER-SITE-2: three download buttons and the older versions page

Jason, 2026-09-15 09:42: "put the Apple version, the desktop version for Windows, and the Linux version on the
marketing site. A download now button for each one, with icons for the three, and then have smaller text below
each button saying older versions. You can click that and it shows a history and change logs from different
versions of the executable, so we can always go back and grab older executables in case somebody wants to
roll back."

The farm repo's half. The launcher repo is adding a Linux AppImage and a releases.json (LAUNCHER-7, in
parallel); until it publishes, build against a fixture.

1. /install/: replace the single button block with three "Download now" buttons in a row (stacked at phone
   width), each with its platform mark (an inline SVG Apple, Windows and Linux/Tux mark drawn in the site's
   own style, no external images), the visitor's platform first and filled, the other two outlined; under
   each, in small text, "Older versions" linking to /launcher/versions/#<platform>. Mac keeps the Intel
   line. site/launcher.json gains "linux" (optional filename); the read_launcher check treats it like mac
   and windows when present. The rest of the page (command line steps) stays.
2. /launcher/versions/: a new static page built by scripts/build-site.py from releases.json. Source of truth:
   https://tiinyapp.farm/launcher/releases.json fetched at build time with a short timeout, falling back to
   a checked-in copy site/launcher-releases.json (the build refuses to publish a page with no data unless
   the switch is off). Shape from LAUNCHER-7: newest first, {version, date, commit, notes (markdown), files
   per platform with name, size, sha256, signed, notarised}. Render: one section per version with date and
   the notes, then a small table of the files for that version with a download link to
   /launcher/<versioned name>, size in MB, checksum truncated with the full value in a title, and "signed
   and notarised" / "signed" / "unsigned" in words. Anchors per platform at the top. Say plainly that older
   builds stop receiving updates and that the newest is what the app updates to. Docs nav entry and a line
   on docs/site/12-launcher.md.
3. Tests: read_launcher with linux; the three-button block; the versions page from a fixture and from a
   missing fetch; the switch-off state unchanged. Screenshots at 1440 and 390 for /install/ and
   /launcher/versions/ into docs/launcher-site-shots/.

Rules: worktree `git -C /Users/sem/code/tiinyapp-farm-main worktree add -b launcher-site-2
/Users/sem/code/tiinyapp-farm-site2 main`; never touch /Users/sem/code/tiinyapp-farm or tiinyapp-farm-main;
PR against main, do not merge; no em dashes; Tiiny; keep the farm feeling; gh < /dev/null; report measured
facts separated from plans.
