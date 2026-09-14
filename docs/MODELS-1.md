# MODELS-1: an app does not start without the models it needs, and the farm watches them

Jason, 2026-09-14 16:10, running the launcher: "we launched an app that requires a model but the model is
not loaded so the app won't work. How do we handle that use case? This should also monitor models loading
and unloading. You should be able to select whether an app requires a specific kind of model or models,
and it should not load if they are not loaded."

Today every manifest already carries `requires.device.models` (a list of kinds: chat, image, tts,
embedding, asr, rerank) and `npuUnits`; the farm prints them at install and never looks again. Titanium
Tiiny Bot started with no chat model loaded and answered every message with "Cannot reach the device".

## What to build, in /Users/sem/code/tiinyapp-farm-main's farm/farm.py (stdlib only, Python 3.9+)

1. `farm models [--json]`: what the Tiiny on file has loaded right now: model id, kind, NPU units, state
   (running, loading, stopped), plus the device's total and free units, and the models it has downloaded
   but not loaded. Kind comes from the device's own capability field (the one AINode Pocket uses: `main`
   is chat, and embedding, tts, asr, image, rerank as the device names them). Read the model lifecycle
   API the way AINode Pocket does: /private/tmp/claude-501/-Users-sem-orca-workspaces-grok-bot-0-18-reconstructed-gb/5d8b03a4-9c9b-4e51-af12-2606d5d99b44/scratchpad/pocket/repo/pocket/device.py (models, running, npu_units, npu_devices, catalog, model_storage, start, stop; the p8800 virtual host on port 80, one inference at a time, 150004 when busy) and /Users/sem/code/tiiny/CAPABILITIES.md and /Users/sem/code/tiiny-sdk-docs/reference/http.md. Port the logic, keep the farm's voice.
2. `farm start <id>` checks `requires.device.models` against what is loaded before it starts anything.
   Each kind is satisfied by any loaded model of that kind. Missing kinds: refuse with one sentence that
   names what is missing and what is loaded, then offer to load: on a terminal, "Load Qwen/Qwen3-8B for chat
   now? [Y/n]" picking the downloaded model of that kind (a numbered pick when several), checking free NPU
   units against the model's units first; `--load` says yes to all of it without asking; `--json` never
   asks and answers {"command":"start","started":false,"missing":[{"kind":"chat","loaded":[],"available":[...]}]}.
   Loading waits for the model to reach running (with the device's own timeout, say what it is) before the
   app starts. `--no-model-check` (or `FARM_NO_MODEL_CHECK=1`) skips it for people who know better.
   A manifest may also name an exact model id instead of a kind (`"models": ["chat", "Tongyi-MAI/Z-Image-Turbo"]`);
   support both in the schema and the check, and document it on the publish page.
3. Monitoring: `farm status [--json]` shows, per running app, whether each needed kind is loaded now, and
   marks an app whose model went away since it started ("Story Lantern: tts model unloaded 3 min ago").
   `farm doctor` gets a finding per installed app with an unmet need. `farm models --watch` prints a line
   whenever a model changes state (poll every 3 s, Ctrl-C to stop); `--watch --json` prints one JSON object
   per change, which is what the launcher will read.
4. Manifests: daybreak.json declares `["chat", "embedding"]` (it enriches and embeds every article). Check
   the other six against what the apps actually call and fix any that are wrong, one commit per manifest
   with the evidence in the message. (The PR manifest check validates against main's schema, so if you
   add the exact-id form it shows red by design; say so.)
5. Docs: 03-cli.md (models, start's check and flags, status), 04-publish.md (what to declare and why),
   11-agents.md (an agent must check models before starting an app; the JSON shapes), README table rows,
   worker/openapi.py untouched unless a route changes.

## Proof

Against Jason's Tiiny at 172.17.7.177 from a scratch HOME (the key: pipe /Users/sem/.tiiny_1_api_key into
`farm device --key-stdin`, never print it, never argv, never a log). Measured: `farm models` lists what is
loaded with kinds and units; with a chat model stopped, `farm start titanium-tiiny-bot` refuses and names
it, `farm start --load` loads it and then starts, `farm status` shows the need met, and after stopping the
model again status marks it. Put the models back the way you found them when done (Jason's own apps use
them; do not leave a model unloaded, and do not exceed the free units). Tests with the device patched for
every branch, the JSON shapes, the watch loop with a fake clock. Whole suite on 3.14 and 3.9. No version
bump; the orchestrator tags 0.1.14.

## Rules

Worktree: `git -C /Users/sem/code/tiinyapp-farm-main worktree add -b models /Users/sem/code/tiinyapp-farm-models main`.
Never touch /Users/sem/code/tiinyapp-farm or tiinyapp-farm-main. Never read ~/.api_keys, the keychain,
~/.claude/.credentials.json or ~/.tinyfish. PR against main, do not merge. Every `gh` call `< /dev/null`.
Timeouts on every socket and command. No em dashes; spell it Tiiny. Report measured facts (name the
machine) separated from plans.
