# ART-1: every app gets art in the farm's own hand

Jason, 2026-09-13 20:06 CDT: "we need a way for somebody adding their item to the catalog to
describe what their image is and what you've been doing to create that style ... hero image that
you're making for all of the apps I've uploaded: how can we use AI to do that and build it for
anybody who puts an app there, so that there's consistency based on how you were prompting those
images before?"

## What exists

Six pieces of house art under site/assets/art (three header.webp at 1536x1024, three icon.png at
512x512 on transparency), all made with gpt-image-2 by hand, and the Tiiny Brain pair on PR #9.
The commit messages describe the family: a night farm, deep midnight sky, warm lantern light,
cyan-glowing sprout characters, fireflies, a painterly storybook hand, the app's real subject in
the middle (a corkboard of pinned cards joined by threads of light for Tiiny Brain, a lantern and
bench of gauges for TiinyBench, sprouts queuing at a gate for OneLane, a child at a window with
pages flying for Story Lantern). The prompts themselves were never saved. Manifest `media` holds
`icon` and `header` paths under /assets or /media; makers upload their own through POST /api/media
today.

## What changes

1. **The house style is written down once**, in `docs/ART-STYLE.md`: look at all six images (and
   the PR #9 pair) and write the style paragraph that reproduces them, the composition rules for a
   header (wide, subject centre-right, sky top third, lantern light from one side) and an icon
   (one object, centred, glow, transparent ground, no text), the palette (midnight #090D14, signal
   cyan #00C8F0, lantern amber), and the negative rules (no text, no logos, no photoreal, no
   humans in developer tools art). One function builds the two prompts from a maker's one-line
   scene: `farm/art.py` `header_prompt(scene)` and `icon_prompt(scene)`, used by BOTH the Worker
   (ported to worker/art.mjs byte-for-byte in wording, with a test that the two agree) and the
   maintainer script.
2. **The maker describes the scene, the farm draws it.** On /submit/ (the app form) and on the
   maker's own app page: a field "Describe your app's scene in one sentence", a Generate art
   button, a preview of the header and icon, Use these, and Try again. Worker route
   `POST /api/seeds/<id>/art` with `{scene}`: maker-only, three generations per app per day,
   calls the OpenAI images API (model gpt-image-2, `output_format: "webp"` for the header at
   1536x1024 and png with `background: "transparent"` for the icon at 1024x1024, resized to 512
   only if the API cannot; read the current API reference from platform.openai.com before
   assuming parameter names), stores both in R2 under media/<uid>/<seed>/ the way POST /api/media
   does, answers the two URLs, and writes them into the submission's `media`. The key is a Worker
   secret `OPENAI_API_KEY` that the orchestrator sets; the code never logs it. Cost line in the
   report: what one pair costs at list price.
3. **A maintainer script**, `scripts/art.py <app-id> "<scene>"`, same prompt builder, writes
   site/assets/art/<id>-header.webp and <id>-icon.png for apps the maintainers draw themselves.
   Reads OPENAI_API_KEY from the environment only.
4. **Docs**: a new page docs/site/10-art.md (Art in the farm's hand: what the style is, what to
   write in the scene line, what not to expect) linked from the publish guide and the manifest
   reference's `media` field.

## Tests and measurement

- Python: prompt builders against a fixed scene produce fixed strings; the Worker port is checked
  against the same fixtures (a JSON fixture both suites read).
- Worker tests: a fake images API drives the route: maker only, the daily limit, the two objects
  written, the submission updated, the error shapes when the API fails.
- Site: the form field and preview at 1440x900 and 390x844 in headless Chromium and WebKit through
  playwright-core at /Users/sem/orca/workspaces/grok-bot-0.18-reconstructed/gb/.cache/playwright/node_modules,
  screenshots in docs/art-shots/.
- NOT yours: a real generation. You have no key. The orchestrator runs scripts/art.py once with
  the real key after your PR and judges the pair against the shelf; write in the report exactly
  the command to run and what a pass looks like.

## Rules

Model opus. No em dashes anywhere. Spell it Tiiny. Never read ~/.api_keys or any file with key,
token or secret in its name. Commit on the branch house-art, push it and open a PR against main
with gh; never push to main, never merge, never deploy the Worker. Report in under 40 lines: the
PR URL, the style paragraph you wrote, the route and limits, the test counts, the command for the
live test.
