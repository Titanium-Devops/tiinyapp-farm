// The farm's house art. The style and the two prompt builders below are the same words as
// farm/art.py; tests/art-prompts.json is the fixture both sides are measured against, so a
// change here that is not made there turns both suites red.
import { fail, json, remote } from './index.mjs';
import { imageType, mediaPattern } from './makers.mjs';

const ORIGIN = 'https://tiinyapp.farm';
const IMAGES = 'https://api.openai.com/v1/images/generations';
export const MODEL = 'gpt-image-2';
export const HEADER_SIZE = '1536x1024';
export const ICON_SIZE = '1024x1024';
export const QUALITY = 'high';
export const MAX_SCENE = 200;
export const MIN_SCENE = 3;
// Three pairs per app per day. A maker who needs a fourth has a scene problem, not a quota problem.
export const DAILY = 3;
const DAY = 86400000;
// A generation runs far past the ten seconds every other call to the outside world gets.
const DRAW_TIMEOUT = 120000;
const DRAW_BYTES = 12 * 1024 * 1024;
const STORE_BYTES = 8 * 1024 * 1024;
// One drawing at a time per app, so a double press cannot spend two pairs.
const INFLIGHT = 180000;

export const STYLE =
  "Hand-painted storybook art in the tiinyapp.farm house style: a small farm at night, drawn " +
  "with soft rounded shapes, thick dark outlines and flat cel shading in a few steps, with a " +
  "gentle bloom around every light. Deep midnight blue and near-black indigo carry the whole " +
  "frame, lit by two sources only: warm lantern amber pooling on wood and earth, and a cool " +
  "cyan glow coming off the living things, sprout leaves, glass dials and threads of light. " +
  "Fireflies and small sparks of dust drift in the air. Something is always growing in the " +
  "frame: a leaf, a shoot, or a small round sprout robot with a cyan visor and a green sprout " +
  "on its head. Warm, quiet and unhurried.";

export const PALETTE =
  "Palette: midnight #090D14 and deep indigo for the ground and the dark, signal cyan #00C8F0 " +
  "for every cool glow, lantern amber for every warm one, leaf green for anything growing, and " +
  "small warm gold firefly points.";

export const NEGATIVE =
  "Never include text, letters, numbers, logos, watermarks, signatures, user interface panels " +
  "or labelled charts. Never photographic, never a 3D render, never real people; the only " +
  "characters are the farm's sprout robots and soft storybook figures.";

export const HEADER_FRAME =
  "Draw this as a wide landscape header, 1536 by 1024. Put the subject just right of centre " +
  "with room to breathe, keep the top third sky or dark rafters, and let one warm light fall " +
  "from the left. Build three layers of depth: leaves or grass along the bottom edge, the " +
  "subject in the middle, a far farm silhouette with lit windows behind. Fill the frame edge " +
  "to edge.";

export const ICON_FRAME =
  "Draw this as a single square app icon, 1024 by 1024, on a fully transparent background. One " +
  "object or one tight little scene, centred, seen from slightly above, resting on a small base " +
  "of dark foliage and stone. Make it a sticker: one thick dark navy outline around the whole " +
  "shape, a clear margin on every side, nothing running off the edge, and the glow on the " +
  "object itself rather than on the background.";

// Collapse a maker's scene line to one tidy sentence, or say why it cannot be used.
export function cleanScene(scene) {
  if (typeof scene !== 'string') fail(400, "Describe your app's scene in one sentence.");
  const text = scene.split(/\s+/).filter(Boolean).join(' ');
  if (text.length < MIN_SCENE) fail(400, "Describe your app's scene in one sentence.");
  if (text.length > MAX_SCENE) fail(400, `Keep the scene to ${MAX_SCENE} characters or fewer.`);
  // Whitespace is already gone; anything else below 32 is a control character.
  for (const character of text) if (character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127) fail(400, "Describe your app's scene in one sentence.");
  return '.!?'.includes(text.at(-1)) ? text : text + '.';
}

export const headerPrompt = scene => `${STYLE}\n\nThe scene: ${cleanScene(scene)}\n\n${HEADER_FRAME}\n\n${PALETTE}\n\n${NEGATIVE}`;
export const iconPrompt = scene => `${STYLE}\n\nThe scene: ${cleanScene(scene)}\n\n${ICON_FRAME}\n\n${PALETTE}\n\n${NEGATIVE}`;

const base64 = value => {
  if (typeof value !== 'string' || !/^[A-Za-z0-9+/]+={0,2}$/.test(value.replace(/\s/g, ''))) fail(502, 'The farm could not read the drawing it was sent.');
  const binary = atob(value.replace(/\s/g, ''));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
};

// One image. The key is read here and never logged, never echoed and never put in a message.
async function draw(ctx, prompt, options) {
  const { env, fetcher } = ctx;
  if (!env.OPENAI_API_KEY) fail(503, 'Drawing app art is not switched on yet.');
  let result;
  try {
    result = await remote(fetcher, IMAGES, { method: 'POST', headers: {
      Authorization: `Bearer ${env.OPENAI_API_KEY}`, 'Content-Type': 'application/json',
    }, body: JSON.stringify({ model: MODEL, prompt, n: 1, quality: QUALITY, ...options }) }, DRAW_BYTES, DRAW_TIMEOUT);
  } catch (error) {
    if (error.status === 408) fail(504, 'The drawing took too long. Please try again.');
    throw error;
  }
  // A refusal is about the words the maker wrote, so it is worth saying; nothing else from the
  // other side is repeated, because its body can carry account and request detail.
  if (result.status === 400) fail(422, 'That scene was refused by the drawing service. Describe it in different words and try again.');
  if (result.status === 429) fail(503, 'The farm is drawing more art than it can right now. Please try again in a few minutes.');
  if (!result.ok) fail(502, 'The farm could not draw this scene. Please try again.');
  let payload;
  try { payload = JSON.parse(result.text()); } catch { fail(502, 'The farm could not read the drawing it was sent.'); }
  const encoded = payload?.data?.[0]?.b64_json;
  if (!encoded) fail(502, 'The farm could not read the drawing it was sent.');
  const bytes = base64(encoded);
  if (bytes.length > STORE_BYTES) fail(502, 'The drawing came back too large to keep.');
  return { bytes, usage: payload.usage || null };
}

async function store(ctx, user, id, bytes, expected) {
  // The maker chose nothing here, so a sniffing failure is the farm's problem to report, not
  // the "choose a PNG" sentence the upload route gives someone who picked the wrong file.
  let ext, contentType;
  try { [ext, contentType] = imageType(bytes); } catch { fail(502, 'The drawing came back in a format the farm cannot keep.'); }
  if (ext !== expected) fail(502, 'The drawing came back in a format the farm cannot keep.');
  const key = `media/${user.id}/${id}/${ctx.random(16)}.${ext}`;
  if (!mediaPattern.test(key)) fail(500, 'The farm could not file this drawing.');
  await ctx.env.SEEDS.put(key, bytes, { httpMetadata: { contentType } });
  return { key, url: ORIGIN + '/' + key };
}

// Who may draw art filed under an app ID: whoever the farm already records as its maker, and
// otherwise anyone verified, because an unclaimed ID has no maker to protect. Art alone never
// changes the catalog; the manifest still moves only through the submission owner gate.
async function mayDraw(ctx, user, id) {
  const owner = await ctx.get('seedowner:' + id);
  if (owner) return owner === user.id;
  let manifest = null;
  try {
    const published = await ctx.env.ASSETS.fetch(new Request(ORIGIN + '/manifests/' + id + '.json'));
    if (published.ok) manifest = await published.json();
  } catch { /* An app with no catalog page yet is unclaimed. */ }
  if (!manifest || manifest.id !== id) return true;
  return manifest.author?.tiinyverse === user.tiinyverse.profileUrl;
}

const recent = (list, now) => (list || []).filter(at => at > now - DAY);

export async function artRoutes(ctx) {
  const { path, request, requireUser, get, put, del, now, bodyJSON } = ctx;
  const match = path.match(/^\/api\/seeds\/([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\/art$/);
  if (!match) return null;
  const id = match[1];
  if (!['GET', 'POST'].includes(request.method)) return json({ error: 'Use GET or POST for app art.' }, 405);
  const user = await requireUser();
  if (!user.tiinyverse) fail(403, 'Verify you own a Tiiny before drawing app art.');
  if (!await mayDraw(ctx, user, id)) fail(403, 'Only this app’s verified maker can draw its art.');
  const rateKey = 'art-rate:' + id, artKey = 'seedart:' + id, flightKey = 'art-inflight:' + id;
  if (request.method === 'GET') {
    const stored = await get(artKey);
    const mine = stored?.userId === user.id ? stored : null;
    return json({ scene: mine?.scene || '', ...(mine?.media || {}),
      remaining: Math.max(0, DAILY - recent(await get(rateKey), now()).length) });
  }
  const input = await bodyJSON(request);
  const scene = typeof input.scene === 'string' ? input.scene : '';
  // Refuse a bad scene line before reserving anything, so a typo does not cost a try.
  const prompts = { header: headerPrompt(scene), icon: iconPrompt(scene) };
  const flight = await get(flightKey);
  if (flight && flight > now() - INFLIGHT) fail(409, 'The farm is still drawing this app. Give it a moment.');
  await put(flightKey, now());
  const history = recent(await get(rateKey), now());
  if (history.length >= DAILY) { await del(flightKey); fail(429, `You can draw art ${DAILY} times a day for one app. Try again tomorrow.`); }
  await put(rateKey, [...history, now()]);
  try {
    const header = await draw(ctx, prompts.header, { size: HEADER_SIZE, output_format: 'webp', output_compression: 82 });
    const icon = await draw(ctx, prompts.icon, { size: ICON_SIZE, output_format: 'png', background: 'transparent' });
    const media = { header: (await store(ctx, user, id, header.bytes, 'webp')).url,
      icon: (await store(ctx, user, id, icon.bytes, 'png')).url };
    const record = { userId: user.id, scene: cleanScene(scene), media, drawnAt: new Date(now()).toISOString(),
      tokens: (header.usage?.output_tokens || 0) + (icon.usage?.output_tokens || 0) };
    await put(artKey, record);
    // The submission this app already has, if any, carries the new pair straight to Your apps.
    for (const key of await get('user-seeds:' + user.id) || []) {
      if (!key.startsWith(id + '@')) continue;
      const seed = await get('seed:' + key);
      if (!seed || seed.userId !== user.id) continue;
      seed.icon = media.icon; seed.media = media;
      await put('seed:' + key, seed);
    }
    return json({ ...media, scene: record.scene, remaining: Math.max(0, DAILY - history.length - 1) }, 201);
  } catch (error) {
    // A failed drawing costs the maker nothing.
    await put(rateKey, history);
    throw error;
  } finally {
    await del(flightKey);
  }
}
