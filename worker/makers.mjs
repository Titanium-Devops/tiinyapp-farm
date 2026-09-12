import { fail, json, boundedBody } from './index.mjs';
const ORIGIN = 'https://tiinyapp.farm';
export const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const makerDefaults = user => Object.assign(user, { handle: user.handle ?? null, bio: user.bio ?? '', avatarKey: user.avatarKey ?? null, links: user.links ?? {} });
export async function ensureMaker(user, get, put, random) {
  const needsDefaults = ['handle', 'bio', 'avatarKey', 'links'].some(key => !Object.hasOwn(user, key));
  makerDefaults(user);
  if (needsDefaults) await put('user:' + user.id, user);
  if (!user.handle && user.tiinyverse) {
    const slug = user.tiinyverse.name.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60).replace(/-$/, '') || 'maker';
    let handle;
    do { handle = slug + '-' + random(2); } while (await get('maker:' + handle));
    user.handle = handle;
    await put('maker:' + handle, user.id);
    await put('user:' + user.id, user);
  }
  return user;
}
export function httpsURL(value) {
  if (typeof value !== 'string' || value.length > 2048 || /\s/.test(value)) fail(400, 'Use an HTTPS URL.');
  let url; try { url = new URL(value); } catch { fail(400, 'Use an HTTPS URL.'); }
  if (url.protocol !== 'https:' || !url.hostname || url.username || url.password) fail(400, 'Use an HTTPS URL.');
  return url.href;
}
export const mediaPattern = /^media\/[a-zA-Z0-9_-]+\/[a-f0-9]{32}\.(png|jpg|webp)$/;
export function imageType(bytes) {
  if (bytes.length >= 8 && [137,80,78,71,13,10,26,10].every((b, i) => bytes[i] === b)) return ['png', 'image/png'];
  if (bytes.length >= 3 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return ['jpg', 'image/jpeg'];
  if (bytes.length >= 12 && new TextDecoder().decode(bytes.slice(0,4)) === 'RIFF' && new TextDecoder().decode(bytes.slice(8,12)) === 'WEBP') return ['webp', 'image/webp'];
  fail(415, 'Choose a PNG, JPG or WebP image.');
}
export async function catalog(env) {
  const response = await env.ASSETS.fetch(new Request(ORIGIN + '/catalog.json'));
  if (!response.ok) fail(503, 'The field is temporarily unavailable.');
  return response.json();
}
export async function makerRoutes(ctx) {
  const { path, request, env, requireUser, get, put, bodyJSON, random } = ctx;
  if (path === '/seeds/mine' || path === '/seeds/mine/') return new Response(null, { status: 302, headers: { Location: '/farm/', 'Cache-Control': 'no-store' } });
  if (path === '/farm' || path === '/farm/' || path === '/farm/index.html') {
    const user = await ctx.currentUser();
    if (!user) return new Response(null, { status: 302, headers: { Location: '/seeds/', 'Cache-Control': 'no-store' } });
    const response = await env.ASSETS.fetch(new Request(ORIGIN + '/farm/', request));
    const headers = new Headers(response.headers); headers.set('Cache-Control', 'private, no-store'); headers.set('Vary', 'Cookie');
    return new Response(response.body, { status: response.status, headers });
  }
  if (path === '/api/maker' && request.method === 'POST') {
    const user = await requireUser(), input = await bodyJSON(request);
    if (typeof input.bio !== 'string' || [...input.bio].length > 600) fail(400, 'Keep your bio to 600 characters.');
    if (!input.links || typeof input.links !== 'object' || Array.isArray(input.links)) fail(400, 'Send your maker links.');
    const links = {};
    for (const [key, value] of Object.entries(input.links)) {
      if (!['github', 'website', 'youtube'].includes(key)) fail(400, 'Unknown maker link.');
      if (value) links[key] = httpsURL(value);
    }
    const avatarKey = input.avatarKey ?? null;
    if (avatarKey !== null && (typeof avatarKey !== 'string' || !mediaPattern.test(avatarKey) || !avatarKey.startsWith('media/' + user.id + '/') || !await env.SEEDS.get(avatarKey))) fail(400, 'Choose an image uploaded to your farm.');
    Object.assign(user, { bio: input.bio, avatarKey, links }); await put('user:' + user.id, user);
    return json({ user });
  }
  if (path === '/api/media' && request.method === 'POST') {
    const user = await requireUser();
    if (!user.tiinyverse) fail(403, 'Prove your Tiiny before uploading images.');
    const bytes = await boundedBody(request, 2 * 1024 * 1024), [ext, contentType] = imageType(bytes);
    const key = `media/${user.id}/${random(16)}.${ext}`;
    await env.SEEDS.put(key, bytes, { httpMetadata: { contentType } });
    return json({ key, url: ORIGIN + '/' + key }, 201);
  }
  if (path.startsWith('/api/media/') && request.method === 'DELETE') {
    const user = await requireUser(), key = path.slice('/api/'.length);
    if (!mediaPattern.test(key) || !key.startsWith('media/' + user.id + '/')) fail(403, 'Only your own images can be removed.');
    await env.SEEDS.delete(key);
    if (user.avatarKey === key) { user.avatarKey = null; await put('user:' + user.id, user); }
    return json({ deleted: true });
  }
  const match = path.match(/^\/makers\/([a-z0-9]+(?:-[a-z0-9]+)*)\/$/);
  if (match && request.method === 'GET') {
    const id = await get('maker:' + match[1]), user = id && await get('user:' + id);
    if (!user?.tiinyverse || user.handle !== match[1]) fail(404, 'That maker is not in the field.');
    const seeds = (await catalog(env)).filter(seed => seed.author.tiinyverse === user.tiinyverse.profileUrl);
    const links = Object.entries(user.links || {}).map(([label, url]) => `<a href="${escape(url)}">${escape(label)}</a>`).join(' · ');
    const cards = seeds.map(seed => `<article class="plot"><h2><a href="/apps/${escape(seed.id)}/">${escape(seed.name)}</a></h2><p>${escape(seed.pitch)}</p></article>`).join('');
    return new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${escape(user.tiinyverse.name)} | tiinyapp.farm</title><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,800&amp;family=Nunito:wght@400;600;700&amp;display=swap"><link rel="stylesheet" href="/assets/site.css"><script type="module" src="/assets/session.js"></script></head><body><div class="wrap"><header><a class="brand" href="/">tiinyapp.farm</a><nav aria-label="Main navigation"><a href="/#field">The field</a><a data-farm-nav href="/seeds/">Bring your seeds</a></nav></header><main class="sect">${user.avatarKey ? `<img class="maker-avatar" src="/${escape(user.avatarKey)}" alt="">` : ''}<h1>${escape(user.tiinyverse.name)}</h1><p>@${escape(user.handle)} <span class="badge verified">Verified Tiiny</span></p><p class="maker-bio">${escape(user.bio)}</p><p>${links}</p><h2>Seeds in the field</h2><div class="field">${cards || '<p>No seeds in the field yet.</p>'}</div></main></div></body></html>`, { headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } });
  }
  if (path.startsWith('/makers/')) fail(404, 'That maker is not in the field.');
  return null;
}
