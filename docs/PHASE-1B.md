# Phase 1b: what the first real install showed

Measured 2026-09-12 05:20 by the orchestrator with a locally served copy of the 0.1.9 archive and
FARM_CATALOG pointing at a temp directory (35 tests were green; this is the live run):

1. `farm device` cannot take the values from a pipe: it printed "GetPassWarning" and wrote
   nothing. Add `farm device --base <url> --key-stdin` (key read from stdin, never from an
   argument) and honour TIINY_BASE and TIINY_KEY in the environment as a one-shot import, so
   scripts and tests can set the device without a terminal. Keep the interactive prompt as the
   default.
2. `farm start` reported "Started titanium-tiiny-bot: pid 28055" while the port 7788 was already
   held by another copy of Lite; the app exited at once and `farm status` listed nothing, `farm
   stop` said "not running". Start must wait up to 10 s for the app's declared port to answer
   (GET /api/health when the manifest names one, else a TCP connect), and on failure print the
   last ten lines of the app's log and exit 1. Never claim Started for a process that died.
3. Add `farm start <id> --port N` which exports TINYAPP_PORT (and TIINY_PORT for Lite) so two
   copies or a busy port are recoverable without editing anything; `farm status` shows the
   port it actually used.
4. Health should report the app's version; `farm status` compares it with the installed manifest
   version and flags a mismatch ("running 0.1.8, installed 0.1.9: restart to update").
5. Tests for all four. `python3 -m unittest` green. Append "Phase 1b" to docs/PHASE-1-REPORT.md.
   Commit is not possible from your sandbox. No browser or GUI.
