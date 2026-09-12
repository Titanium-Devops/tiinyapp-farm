import { fail, json } from './index.mjs';
export async function socialRoutes(ctx) {
  const { path, request, env, get, put, requireUser, currentUser, bodyJSON, now, random } = ctx;
  const match = path.match(/^\/api\/seeds\/([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\/(social|thumb|comments)(?:\/([a-f0-9]{32}))?$/);
  if (!match) return null;
  const [, seedId, action, commentId] = match;
  const allowed = action === 'social' ? request.method === 'GET' && !commentId
    : action === 'thumb' ? request.method === 'POST' && !commentId
      : commentId ? request.method === 'DELETE' : request.method === 'POST';
  if (!allowed) fail(405, 'That action does not use this method.');
  // Only seeds in the deployed catalog have a public conversation.
  const response = await env.ASSETS.fetch(new Request(`https://tiinyapp.farm/manifests/${seedId}.json`));
  if (!response.ok) fail(404, 'That seed is not in the field.');
  let manifest; try { manifest = await response.json(); } catch { fail(404, 'That seed is not in the field.'); }
  if (manifest.id !== seedId) fail(404, 'That seed is not in the field.');
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
    return { thumbs: social.thumbs.length, mine: !!user && social.thumbs.includes(user.id), comments };
  }
  if (action === 'social') return json(await view());
  if (action === 'thumb') {
    const index = social.thumbs.indexOf(user.id);
    if (index < 0) social.thumbs.push(user.id);
    else social.thumbs.splice(index, 1);
  } else if (request.method === 'POST') {
    if (!user.tiinyverse) fail(403, 'Prove your Tiiny before leaving a comment.');
    const input = await bodyJSON(request);
    if (typeof input.text !== 'string' || !input.text.trim() || [...input.text].length > 1000) fail(400, 'Write a comment of 1 to 1000 characters.');
    const rateKey = 'comment-rate:' + user.id;
    const recent = (await get(rateKey) || []).filter(time => time > now() - 3600000);
    if (recent.length >= 5) fail(429, 'Five comments per hour; give the field a little time.');
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
