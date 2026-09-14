"""The farm's house art: one written style, two prompts, built from a maker's scene line.

Every app in the catalog is drawn the same way, so the shelf reads as one shelf. The style
lives in docs/ART-STYLE.md in prose and here in the exact strings that go to the model. The
Worker carries the same two builders in worker/art.mjs, word for word, and tests/art-prompts.json
is the fixture both sides are measured against.
"""

MODEL = "gpt-image-2"
HEADER_SIZE = "1536x1024"
ICON_SIZE = "1024x1024"
ICON_PIXELS = 512
QUALITY = "high"
MAX_SCENE = 200
MIN_SCENE = 3

STYLE = (
    "Hand-painted storybook art in the tiinyapp.farm house style: a small farm at night, drawn "
    "with soft rounded shapes, thick dark outlines and flat cel shading in a few steps, with a "
    "gentle bloom around every light. Deep midnight blue and near-black indigo carry the whole "
    "frame, lit by two sources only: warm lantern amber pooling on wood and earth, and a cool "
    "cyan glow coming off the living things, sprout leaves, glass dials and threads of light. "
    "Fireflies and small sparks of dust drift in the air. Something is always growing in the "
    "frame: a leaf, a shoot, or a small round sprout robot with a cyan visor and a green sprout "
    "on its head. Warm, quiet and unhurried."
)

PALETTE = (
    "Palette: midnight #090D14 and deep indigo for the ground and the dark, signal cyan #00C8F0 "
    "for every cool glow, lantern amber for every warm one, leaf green for anything growing, and "
    "small warm gold firefly points."
)

NEGATIVE = (
    "Never include text, letters, numbers, logos, watermarks, signatures, user interface panels "
    "or labelled charts. Never photographic, never a 3D render, never real people; the only "
    "characters are the farm's sprout robots and soft storybook figures."
)

HEADER_FRAME = (
    "Draw this as a wide landscape header, 1536 by 1024. Put the subject just right of centre "
    "with room to breathe, keep the top third sky or dark rafters, and let one warm light fall "
    "from the left. Build three layers of depth: leaves or grass along the bottom edge, the "
    "subject in the middle, a far farm silhouette with lit windows behind. Fill the frame edge "
    "to edge."
)

ICON_FRAME = (
    "Draw this as a single square app icon, 1024 by 1024, on a fully transparent background. One "
    "object or one tight little scene, centred, seen from slightly above, resting on a small base "
    "of dark foliage and stone. Make it a sticker: one thick dark navy outline around the whole "
    "shape, a clear margin on every side, nothing running off the edge, and the glow on the "
    "object itself rather than on the background."
)


class SceneError(ValueError):
    """A scene line the farm will not send to the model."""


def clean_scene(scene):
    """Collapse a maker's scene line to one tidy sentence, or say why it cannot be used."""
    if not isinstance(scene, str):
        raise SceneError("Describe your app's scene in one sentence.")
    text = " ".join(scene.split())
    if len(text) < MIN_SCENE:
        raise SceneError("Describe your app's scene in one sentence.")
    if len(text) > MAX_SCENE:
        raise SceneError(f"Keep the scene to {MAX_SCENE} characters or fewer.")
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise SceneError("Describe your app's scene in one sentence.")
    return text if text[-1] in ".!?" else text + "."


def header_prompt(scene):
    """The prompt for an app's wide header image."""
    return f"{STYLE}\n\nThe scene: {clean_scene(scene)}\n\n{HEADER_FRAME}\n\n{PALETTE}\n\n{NEGATIVE}"


def icon_prompt(scene):
    """The prompt for an app's square icon."""
    return f"{STYLE}\n\nThe scene: {clean_scene(scene)}\n\n{ICON_FRAME}\n\n{PALETTE}\n\n{NEGATIVE}"
