# Phase 6: plain words, and Windows

Jason, reading the live site as a developer: "This entire site is not intuitive. It doesn't look polished
and feels like AI slop. I like the homepage a little bit, but for the rest, we're trying to be too cute
and it's not making sense. Tell it what for step 2? I can't follow along and I'm a developer." Also:
"Why is that version of Python required? Why is macOS or Linux required? What if they're running on
Windows?"

Two jobs. Tests green at the end. No framework, no dependency.

## A. Every instruction is literal

The home page hero keeps its warmth (the sprout, the field, "Little apps, grown for your Tiiny"). Every
other sentence on the site is written for a developer who has never seen the site and is skimming.
Rules:
- Say what a thing is before naming it. The CLI is "the farm CLI (`farm`)". Never "farmhand". A
  submission is "an app" in every instruction; "seed" may remain only as the section eyebrow flavour
  ("Seeds", "Plant an app") when a plain heading sits right under it.
- Each step names the exact command, what it asks for, where the answer comes from, and where it stores
  it. Example for the install page:
  1. Install the CLI: `pip install tiinyapp-farm`. Python 3.9 or newer. macOS, Linux and Windows.
  2. Connect your Tiiny: `farm device`. It asks for two things: the API base URL (on the Mac with the
     TiinyOS client that is `http://openai.api.tiiny/v1`; from any other computer it is
     `http://<your-tiiny-ip>/v1`) and the API key, which you copy from TiinyOS > Settings > API Key. Both
     are saved in `~/.tiinyapps/device.json`, readable only by you. Run it again to change them.
  3. Install and run an app: `farm install <app-id>` then `farm start <app-id>`. `farm list`,
     `farm stop`, `farm update`, `farm remove` do what they say.
- The submit page (/seeds/): heading "Submit an app". Tabs: "1 Sign in", "2 Verify you own a Tiiny",
  "3 Submit your app". Card 2 says exactly: "Paste the URL of your TiinyVerse profile. We give you a
  short code. Put that code anywhere in your TiinyVerse bio, save, then press Verify. We read your
  public profile once to confirm you own it (the same idea as a DNS TXT record). You can remove the code
  afterwards." Card 3 explains what happens after Send in one sentence: "This opens a pull request on
  the catalog; automated checks run, a maintainer reviews it, and it appears in the catalog when merged.
  Track it on Your apps."
- /farm/ is "Your apps" (nav label too). Public maker page: "Apps by <name>". "Sprouting" becomes
  "No release yet". "Farmhand review" becomes "Maintainer review". "Thumbs up" stays. Status words on
  the app page: "Checks running", "Checks failed: <reason>", "Waiting for a maintainer", "In the catalog".
- App page: sections in this order: what it does, install (commands), what it needs (Python, ports,
  models, NPU units, permissions, each in one plain line), release (version, size, checksum, link),
  maker, comments. Every label is a plain noun.
- FAQ answers are two sentences maximum and answer the question asked.
- Remove every sentence that only adds flavour (e.g. "A little care before the field"). Keep the warm
  colour and type; the personality lives in the visuals, not in the instructions.

## B. Windows and the Python floor
- farm/farm.py: no `fcntl` at import time. Use a small lock helper: `fcntl.flock` on POSIX,
  `msvcrt.locking` on Windows, same call sites. Paths through `pathlib` everywhere; no `/tmp`; process
  start/stop works on Windows (`subprocess` with `creationflags` where needed; stop uses `terminate()`).
  The config file permission call is best effort on Windows.
- pyproject: `requires-python = ">=3.9"` (nothing in the code needs newer; if a real 3.10+ feature is
  used, keep the floor there and say why in the report). Site copy says the same floor.
- CI: a `tests` job matrix over ubuntu-latest, macos-latest, windows-latest with Python 3.9 and 3.12
  running `python -m unittest tests.test_farm` (the installer tests only, with the device faked).
  Keep the existing jobs.

## Verify
`python3 -m unittest`, `node --test tests/worker.test.mjs`, `python3 scripts/build-site.py`. Write
docs/PHASE-6-REPORT.md (short) naming any sentence you kept that is not literal and why. Never launch a
browser, wrangler, docker or any GUI. Do not commit.
