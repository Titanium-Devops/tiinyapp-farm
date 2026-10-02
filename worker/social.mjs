import { fail, json } from './index.mjs';
import { catalog } from './makers.mjs';
import { profileId } from './proof.mjs';

// A seed is the farm's thumbs up: one per person per app, given again to take it back. The
// stored record still calls the list thumbs so no key has to be rewritten; every answer carries
// both names with the same number.
export const seedCount = record => (record?.thumbs || []).length;
export const commentCount = record => (record?.commentIds || record?.comments || []).length;
export const COMMENTS_RETAINED = 200;
export const COMMENTS_PAGE = 50;
export async function socialRecord(get, put, seedId) {
  const key = 'social:' + seedId;
  const stored = await get(key) || { thumbs: [], commentIds: [] };
  if (!Array.isArray(stored.comments)) return { key, social: { ...stored, thumbs: stored.thumbs || [], commentIds: stored.commentIds || [] } };
  const commentIds = [];
  for (const comment of stored.comments) {
    await put(`social-comment:${seedId}:${comment.id}`, comment);
    commentIds.push(comment.id);
  }
  const social = { ...stored, thumbs: stored.thumbs || [], commentIds };
  delete social.comments;
  await put(key, social);
  return { key, social };
}
export async function seedsForApps(get, put, apps) {
  const counts = {};
  for (const app of apps) {
    const { social: record } = await socialRecord(get, put, app.id);
    counts[app.id] = { seeds: seedCount(record), comments: commentCount(record) };
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
  const { path, request, env, url, get, put, requireUser, currentUser, bodyJSON, now, random } = ctx;
  // One read for a whole page of apps: the catalog grid and the launcher both ask once rather
  // than once per tile. A minute of cache is short enough that a seed given now shows up while
  // the visitor is still looking at the page.
  if (path === '/api/social/counts') {
    if (request.method !== 'GET') fail(405, 'That action does not use this method.');
    const apps = await catalog(env);
    const counts = await seedsForApps(get, put, apps);
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
  const { key, social } = await socialRecord(get, put, seedId);
  const user = action === 'social' ? await currentUser() : await requireUser();
  // A read is open to anyone, but a token that was sent and matches nobody is said out loud,
  // so the launcher stops calling itself signed in rather than quietly reading as a stranger.
  if (action === 'social' && !user && /^Bearer\s/i.test(request.headers.get('Authorization') || '')) fail(401, 'That farm token is not valid. Make a new one on your account page.');
  const admins = new Set((env.FARM_ADMINS || '').split(',').map(id => id.trim()).filter(Boolean));
  const canDelete = comment => !!user && (comment.userId === user.id || admins.has(user.id));
  async function view() {
    const rawPage = url.searchParams.get('page') || '0';
    if (!/^(0|[1-9][0-9]*)$/.test(rawPage)) fail(400, 'Choose a valid comment page.');
    const page = Number(rawPage), end = Math.max(0, social.commentIds.length - page * COMMENTS_PAGE);
    const start = Math.max(0, end - COMMENTS_PAGE);
    const stored = (await Promise.all(social.commentIds.slice(start, end).map(id => get(`social-comment:${seedId}:${id}`)))).filter(Boolean);
    const userIds = [...new Set(stored.map(comment => comment.userId))];
    const authors = new Map(await Promise.all(userIds.map(async id => [id, await get('user:' + id)])));
    const comments = [];
    for (const comment of stored) {
      const author = authors.get(comment.userId);
      comments.push({ id: comment.id, author: { handle: author?.handle || null,
        name: author?.tiinyverse?.name || 'A maker', avatar: author?.avatarKey ? '/' + author.avatarKey : null },
        text: comment.text, at: comment.at, canDelete: canDelete(comment) });
    }
    return { thumbs: social.thumbs.length, seeds: social.thumbs.length,
      mine: !!user && social.thumbs.includes(user.id), comments,
      page, nextPage: start > 0 ? page + 1 : null };
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
    if (social.commentIds.length >= COMMENTS_RETAINED) fail(409, 'This conversation is full. Remove a comment before adding another.');
    // Keep rate history separate so deleting comments cannot reset the limit.
    await put(rateKey, [...recent, now()]);
    const comment = { id: random(16), userId: user.id, text: input.text.trim(), at: new Date(now()).toISOString() };
    await put(`social-comment:${seedId}:${comment.id}`, comment);
    social.commentIds.push(comment.id);
  } else {
    const index = social.commentIds.indexOf(commentId);
    if (index < 0) fail(404, 'That comment is not here.');
    const comment = await get(`social-comment:${seedId}:${commentId}`);
    if (!comment) fail(404, 'That comment is not here.');
    if (!canDelete(comment)) fail(403, 'Only the author or a farm admin can remove this comment.');
    social.commentIds.splice(index, 1);
    await ctx.del(`social-comment:${seedId}:${commentId}`);
  }
  await put(key, social);
  return json(await view(), action === 'comments' && request.method === 'POST' ? 201 : 200);
}
