# The farm's house style

Eight pieces of art made the shelf look like one shelf: the headers and icons for OneLane, Story
Lantern, Tiiny Bench, and the Tiiny Brain pair on pull request 9. They were drawn by hand with
gpt-image-2 and the prompts were never saved. This page is those prompts, recovered by looking at
the pictures, so that every app added from now on lands in the same world.

The strings the model actually receives live in `farm/art.py` and, word for word, in
`worker/art.mjs`. `tests/art-prompts.json` is the fixture both sides are measured against. Change
the words here and you change them there, or the tests go red.

## The style, in one paragraph

Hand-painted storybook art: a small farm at night, drawn with soft rounded shapes, thick dark
outlines and flat cel shading in a few steps, with a gentle bloom around every light. Deep midnight
blue and near-black indigo carry the whole frame, lit by two sources only: warm lantern amber
pooling on wood and earth, and a cool cyan glow coming off the living things, sprout leaves, glass
dials and threads of light. Fireflies and small sparks of dust drift in the air. Something is
always growing in the frame: a leaf, a shoot, or a small round sprout robot with a cyan visor and a
green sprout on its head. Warm, quiet and unhurried.

## What the eight pictures have in common

Look at them side by side and the rules are not subtle.

- **It is always night, and never black.** The darkest ground is around `#090D14`, but the sky is
  deep blue with visible stars, and the shadows keep colour in them.
- **Two lights, never three.** An oil lantern or a lit window gives warm amber. Everything alive or
  measuring gives cyan. Nothing is lit white.
- **The subject is the app, literally.** OneLane is sprouts queuing at a gate. Tiiny Bench is a
  workbench of glowing gauges. Story Lantern is a child at a window with storybook pages flying
  out. Tiiny Brain is a corkboard of pinned cards joined by threads of light. The metaphor is drawn
  as a real object on a real farm, not as an abstraction.
- **The farm is behind everything.** A barn with lit windows, a silo, a windmill, a wooden fence,
  rolling dark hills. Even the two interior scenes put a window or an open wall in the frame so the
  farm shows through it.
- **Something is growing in shot.** A potted sprout with a face, a row of sprout robots, glowing
  cyan leaves in the foreground.
- **Fireflies.** Small warm gold points and a few cyan ones, scattered, never in a pattern.
- **No lettering anywhere.** The gauges have tick marks and needles and no numbers. The books have
  scribbles and no words.

## Composition: a header

`size: "1536x1024"`, wide. This is the band across the top of an app page and the art behind the
card in the catalog, so it gets cropped from both sides on a phone.

- Subject just right of centre, with room to breathe.
- Top third is sky, or the dark rafters of a shed.
- One warm light source from the left.
- Three layers of depth: leaves or grass along the bottom edge, the subject in the middle, a far
  farm silhouette with lit windows behind.
- Fills the frame edge to edge. No border, no vignette frame, no margin.

## Composition: an icon

`size: "1024x1024"` with `background: "transparent"`, kept at 512 by 512 on the shelf. The model
will not draw a square smaller than 1024, because its smallest accepted image is 655,360 pixels, so
the maintainer script shrinks the icon and the Worker keeps it at 1024. This one sits on a card at
72 pixels and in a ledger row at 56, so it has to read at thumbnail size.

- One object, or one tight little scene, centred, seen from slightly above.
- It rests on a small base of dark foliage and stone, which is what gives all four existing icons
  the same footing.
- It is a sticker: one thick dark navy outline around the whole shape, a clear margin on every
  side, nothing running off the edge.
- The glow is on the object, not on the background. The background is not there.
- No text, ever, and no app name.

## The palette

| Role | Colour |
| --- | --- |
| Ground, dark, the darkest shadow | midnight `#090D14` |
| The sky and the mid tones | deep indigo, roughly `#141B2E` to `#1D2A4A` |
| Every cool glow: leaves, dials, threads of light, visors | signal cyan `#00C8F0` |
| Every warm glow: lanterns, windows, lamp light on wood | lantern amber, roughly `#F7B955` |
| Anything growing | leaf green |
| Fireflies | small warm gold points |

These are the site's own colours. `#090D14` is the page background and `#00C8F0` is its accent, so
the art and the page it sits on are lit by the same two lights.

## What the farm will not draw

Every prompt ends with the same refusals, and they are not negotiable:

- No text, letters, numbers, logos, watermarks, signatures, interface panels or labelled charts.
  Lettering is what makes generated art look generated, and an app name burned into an icon is
  wrong the moment the app is renamed.
- Nothing photographic and nothing that looks like a 3D render.
- No real people. The characters are the farm's sprout robots and soft storybook figures. Story
  Lantern has a child at a window because it is a children's app drawn as a storybook; a developer
  tool gets objects and sprouts, not faces.

## Writing the scene line

The maker writes one sentence. The farm supplies the night, the farm, the lanterns, the sprouts and
the palette, so the sentence should only carry what is different about this app.

Good scene lines, one per existing app, reconstructed from what is in the pictures:

| App | Scene |
| --- | --- |
| OneLane | sprouts queuing in a line at a lantern-lit wooden gate |
| Tiiny Bench | a workbench of glowing gauges and a stopwatch under a shed lantern |
| Story Lantern | a child at a window with storybook pages flying into the night sky |
| Tiiny Brain | a corkboard of pinned cards joined by threads of light |

What makes a line work:

- Name objects, not qualities. "A corkboard of pinned cards" draws. "Fast and reliable" does not.
- One subject. Two subjects fight for the centre and the header loses its focus.
- Leave out the style. Saying "dark" or "glowing" or "cute" is already in the prompt twice and only
  pushes the picture further than it should go.
- Leave out your app's name. It cannot be drawn, and asking for it invites lettering.

Under 200 characters. Line breaks are collapsed and control characters are refused. The maker's
sentence is placed between the style and the composition rules, so the framing and the refusals are
the last thing the model reads.

## The two surfaces that use this

- **Makers** press Generate art on the submit form or on their own app page. The Worker route
  `POST /api/seeds/<id>/art` runs both prompts, files the pair in R2 and answers the two URLs.
  Three drawings per app per day.
- **Maintainers** run `python3 scripts/art.py <app-id> "<scene>"` with `OPENAI_API_KEY` in the
  environment, which writes `site/assets/art/<id>-header.webp` and `site/assets/art/<id>-icon.png`
  for apps the maintainers draw themselves.

Both use `header_prompt(scene)` and `icon_prompt(scene)`. There is no third way to make house art.

The Worker reads its key from the secret `OPENAI_API_KEY`, set once with
`wrangler secret put OPENAI_API_KEY`. Without it the route answers 503 and says the farm is not
drawing yet. The key is never logged, never returned and never part of an error message.
