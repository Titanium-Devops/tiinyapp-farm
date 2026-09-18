import { fail, json } from './index.mjs';
import { catalog } from './makers.mjs';
import { profileId } from './proof.mjs';

// A seed is the farm's thumbs up: one per person per app, given again to take it back. The
// stored record still calls the list thumbs so no key has to be rewritten; every answer carries
// both names with the same number.
export const seedCount = record => (record?.thumbs || []).length;
export async function seedsForApps(get, apps) {
  const counts = {};
  for (const app of apps) {
    const record = await get('social:' + app.id);
    counts[app.id] = { seeds: seedCount(record), comments: (record?.comments || []).length };
  }
  return counts;
}
// Who to credit an app's seeds to. The manifest's author profile is the same thing the maker
// page filters on, and tvowner: already maps a profile to the account that proved it, so an app
// listed before the farm recorded owners is reached as easily as one submitted through the site.
// seedowner: answers for an app whose author profile was never verified.
async function makerOf(get, app) {
  let owner = null;
  try { owner = await get('tvowner:' + profileId(app.author?.tiinyverse)); } catch { owner = null; }
  if (!owner) owner = await get('seedowner:' + app.id);
  const user = owner && await get('user:' + owner);
  // A maker who hid their page is not listed here either.
  return user?.handle && user.tiinyverse && user.public !== false ? user.handle : null;
}
export async function makerSeeds(get, apps, counts) {
  const totals = {};
  for (const app of apps) {
    const handle = await makerOf(get, app);
    if (!handle) continue;
    totals[handle] = { seeds: (totals[handle]?.seeds || 0) + (counts[app.id]?.seeds || 0) };
  }
  return totals;
}
export async function socialRoutes(ctx) {
  const { path, request, env, get, put, requireUser, currentUser, bodyJSON, now, random } = ctx;
  // One read for a whole page of apps: the catalog grid and the launcher both ask once rather
  // than once per tile. A minute of cache is short enough that a seed given now shows up while
  // the visitor is still looking at the page.
  if (path === '/api/social/counts') {
    if (request.method !== 'GET') fail(405, 'That action does not use this method.');
    const apps = await catalog(env);
    const counts = await seedsForApps(get, apps);
    return json({ apps: counts, makers: await makerSeeds(get, apps, counts) },
      200, { 'Cache-Control': 'public, max-age=60' });
  }
  const match = path.match(/^\/api\/seeds\/([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\/(social|thumb|seed|comments)(?:\/([a-f0-9]{32}))?$/);
  if (!match) return null;
  const [, seedId, route, commentId] = match;
  // /seed is the name a person reads; /thumb is the name the first release shipped with.
  const action = route === 'seed' ? 'thumb' : route;
  const allowed = action === 'social' ? request.method === 'GET' && !commentId
    : action === 'thumb' ? request.method === 'POST' && !commentId
      : commentId ? request.method === 'DELETE' : request.method === 'POST';
  if (!allowed) fail(405, 'That action does not use this method.');
  // Only seeds in the deployed catalog have a public conversation.
  const response = await env.ASSETS.fetch(new Request(`https://tiinyapp.farm/manifests/${seedId}.json`));
  if (!response.ok) fail(404, 'That app is not in the catalog.');
  let manifest; try { manifest = await response.json(); } catch { fail(404, 'That app is not in the catalog.'); }
  if (manifest.id !== seedId) fail(404, 'That app is not in the catalog.');
  const key = 'social:' + seedId, social = await get(key) || { thumbs: [], comments: [] };
  const user = action === 'social' ? await currentUser() : await requireUser();
  const admins = new Set((env.FARM_ADMINS || '').split(',').map(id => id.trim()).filter(Boolean));
  const canDelete = comment => !!user && (comment.userId === user.id || admins.has(user.id));
  async function view() {
    const comments = [];
    for (const comment of social.comments) {
      const author = await get('user:' + comment.userId);
      comments.push({ id: comment.id, author: { handle: author?.handle || null,
        name: author?.tiinyverse?.name || 'A maker', avatar: author?.avatarKey ? '/' + author.avatarKey : null },
        text: comment.text, at: comment.at, canDelete: canDelete(comment) });
    }
    return { thumbs: social.thumbs.length, seeds: social.thumbs.length,
      mine: !!user && social.thumbs.includes(user.id), comments };
  }
  if (action === 'social') return json(await view());
  if (action === 'thumb') {
    const index = social.thumbs.indexOf(user.id);
    if (index < 0) social.thumbs.push(user.id);
    else social.thumbs.splice(index, 1);
  } else if (request.method === 'POST') {
    if (!user.tiinyverse) fail(403, 'Verify you own a Tiiny before leaving a comment.');
    const input = await bodyJSON(request);
    if (typeof input.text !== 'string' || !input.text.trim() || [...input.text].length > 1000) fail(400, 'Write a comment of 1 to 1000 characters.');
    const rateKey = 'comment-rate:' + user.id;
    const recent = (await get(rateKey) || []).filter(time => time > now() - 3600000);
    if (recent.length >= 5) fail(429, 'You can post five comments per hour. Please try again later.');
    // Keep rate history separate so deleting comments cannot reset the limit.
    await put(rateKey, [...recent, now()]);
    social.comments.push({ id: random(16), userId: user.id, text: input.text.trim(), at: new Date(now()).toISOString() });
  } else {
    const index = social.comments.findIndex(comment => comment.id === commentId);
    if (index < 0) fail(404, 'That comment is not here.');
    if (!canDelete(social.comments[index])) fail(403, 'Only the author or a farm admin can remove this comment.');
    social.comments.splice(index, 1);
  }
  await put(key, social);
  return json(await view(), action === 'comments' && request.method === 'POST' ? 201 : 200);
}
