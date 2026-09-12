import { ensureMaker } from './makers.mjs';
import { fail, json, remote } from './index.mjs';
export function profileId(value) {
  if (typeof value !== 'string' || !/^https:\/\/www\.tiinyverse\.com\/users\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) || !value.startsWith('https://www.tiinyverse.com/users/')) {
    fail(400, 'Use https://www.tiinyverse.com/users/<uuid> for your profile.');
  }
  return value.split('/').pop().toLowerCase();
}
function decode(value) {
  return value.replace(/<[^>]*>/g, '').replace(/&(?:amp|lt|gt|quot|apos|#39|#\d+|#x[\da-f]+);/gi, entity => {
    const named = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&apos;': "'", '&#39;': "'" };
    if (named[entity]) return named[entity];
    const code = parseInt(entity.slice(entity[2].toLowerCase() === 'x' ? 3 : 2, -1), entity[2].toLowerCase() === 'x' ? 16 : 10);
    return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : '';
  }).trim();
}
export function displayName(html) {
  // Prefer the visible profile heading; metadata is a fallback for SSR variants.
  const heading = html.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/i);
  let name = heading && decode(heading[1]);
  if (!name) {
    for (const tag of html.match(/<meta\b[^>]*>/gi) || []) {
      if (/\bproperty\s*=\s*["']og:title["']/i.test(tag)) {
        name = decode(tag.match(/\bcontent\s*=\s*["']([^"']*)["']/i)?.[1] || '').replace(/\s*[|–-]\s*TiinyVerse.*$/i, '');
      }
    }
  }
  if (!name || name.length > 160) fail(422, 'The profile display name could not be read. Please try again later.');
  return name;
}
export async function proofRoutes(ctx) {
  const { request, path, url, get, put, now, requireUser, bodyJSON, random, fetcher } = ctx;
  if (path === '/api/owners' && request.method === 'GET') {
    const id = profileId(url.searchParams.get('profile'));
    const owner = await get('tvowner:' + id), user = owner && await get('user:' + owner);
    const verified = !!user?.tiinyverse && profileId(user.tiinyverse.profileUrl) === id;
    return json({ verified, name: verified ? user.tiinyverse.name : null });
  }
  if (path === '/api/tiinyverse/link' && request.method === 'POST') {
    const user = await requireUser(), input = await bodyJSON(request), id = profileId(input?.profileUrl);
    if (user.tiinyverse) fail(409, 'Your TiinyVerse profile is already verified.');
    const owner = await get('tvowner:' + id);
    if (owner && owner !== user.id) fail(409, 'That TiinyVerse profile belongs to another farm account.');
    const code = 'farm-' + random(3);
    user.tiinyverseChallenge = { profileUrl: 'https://www.tiinyverse.com/users/' + id, code, expires: now() + 86400000 };
    await put('user:' + user.id, user);
    return json({ ...user.tiinyverseChallenge, instruction: 'Put this in your TiinyVerse bio, then press Verify.' });
  }
  if (path === '/api/tiinyverse/verify' && request.method === 'POST') {
    const user = await requireUser(), challenge = user.tiinyverseChallenge;
    if (!challenge || challenge.expires <= now()) fail(400, 'Request a new bio code; the last one has expired.');
    const id = profileId(challenge.profileUrl), owner = await get('tvowner:' + id);
    if (owner && owner !== user.id) fail(409, 'That TiinyVerse profile belongs to another farm account.');
    const result = await remote(fetcher, challenge.profileUrl, { headers: { 'User-Agent': 'tiinyapp-farm-verifier/1.0' } });
    if (result.status !== 200) fail(422, 'The profile could not be read. Make sure it is public.');
    const html = result.text();
    if (!new RegExp('(?<![a-zA-Z0-9_-])' + challenge.code + '(?![a-zA-Z0-9_-])').test(html)) fail(422, 'The bio code is not on your profile yet. Add it and try Verify again.');
    user.tiinyverse = { profileUrl: challenge.profileUrl, name: displayName(html), verifiedAt: new Date(now()).toISOString() };
    delete user.tiinyverseChallenge;
    await ensureMaker(user, get, put, random);
    await put('user:' + user.id, user); await put('tvowner:' + id, user.id);
    return json({ tiinyverse: user.tiinyverse });
  }
  return null;
}
