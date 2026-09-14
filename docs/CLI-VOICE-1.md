# CLI-VOICE-1: the farm talks to the person who just installed their first app

Jason, 2026-09-14 05:05 CDT, after `farm install ainode-pocket` and `farm start ainode-pocket`:
"for consumers, this should probably show more information, maybe including the local link,
etc. I think when they install something, it should also pull details about what it's
installing. It seemed to install it really fast. It works, I guess, but it's very simplistic
and not very telling for a consumer."

What he saw:

```
Installed ainode-pocket 0.1.0. Run: farm start ainode-pocket
Started ainode-pocket on port 8431 (port 8430 was busy, so it took 8431): pid 44469; log /Users/sem/tiinyapps/ainode-pocket/farm.log
```

## What changes, all in farm/farm.py, standard library only, no colour libraries

1. `farm install <id>` tells the person what it is installing before and while it does it:
   the app's name and pitch, version, who made it and whether the farm reviewed it, what it
   needs (Python version, port, models, permissions in words), then one line per step as it
   happens: fetching the catalog entry, downloading (with the size), verifying the checksum,
   unpacking, ready. The final line says exactly what to type next and what will happen:
   `Ready. Run: farm start ainode-pocket` and, for a library, what to import instead.
   The `-y` path prints the same, without the prompt.
2. `farm start <id>` ends with the thing a person wants: `Open http://localhost:8431` on its
   own line (the port it really took), the one-line pitch, `Stop it with: farm stop <id>`, and
   the log path last. When the port moved, say so in one plain sentence before the link. For
   an app with a health page or a documented first page, use it (manifest `health` is a probe,
   not a page; the link is the root unless the manifest names a landing path, add an optional
   `open` field to the schema for that, default "/").
3. `farm status` shows a link per running app, not only a port. `farm list` shows name,
   version, one-line pitch and whether it is running.
4. `farm device` after saving says which apps will use it and how to test it.
5. Every message reads as a sentence a person would say. No pids in the headline (keep them
   in `farm status`), no "argv", no "manifest" on a consumer line.

## Tests and measurement

- tests/test_farm.py: the install output carries name, pitch, version, author, size and the
  next command; the start output carries the link with the real port and the stop line; the
  moved-port sentence; the library variant; status links.
- Run the real thing from a fresh venv against the live catalog for ainode-pocket and
  tiiny-bench and paste both transcripts in docs/CLI-VOICE-1-REPORT.md, before and after.
- Update docs/site/02-getting-started.md and 03-cli.md examples to the new output.

## Rules

Model opus. No em dashes. Spell it Tiiny. Do not bump pyproject version (orchestrator tags
0.1.6). Commit on branch cli-voice, push it, open a PR against main with gh, never push main,
never merge. Never read ~/.api_keys or any file with key, token or secret in its name. Ports
7891 to 7899 only; never 7788 or 8430.
