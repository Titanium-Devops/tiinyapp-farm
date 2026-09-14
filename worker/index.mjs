import { socialRoutes } from './social.mjs';
import { makerDefaults, ensureMaker, makerRoutes } from './makers.mjs';
const ORIGIN = 'https://tiinyapp.farm';
const COOKIE = '__Host-farm';
const DAY = 86400000;
const encoder = new TextEncoder();
export class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
export const fail = (status, message) => { throw new HttpError(status, message); };
export const json = (data, status = 200, headers = {}) => new Response(JSON.stringify(data), {
  status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...headers },
});
const random = (length = 32) => Array.from(crypto.getRandomValues(new Uint8Array(length)), n => n.toString(16).padStart(2, '0')).join('');
export const sha256 = async data => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)), n => n.toString(16).padStart(2, '0')).join('');
const cookies = request => Object.fromEntries((request.headers.get('Cookie') || '').split(';').map(s => s.trim().split('=')));
const cookie = (name, value, age) => `${name}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${age}`;
const redirect = (where, headers = {}) => new Response(null, { status: 302, headers: { Location: where, ...headers } });
async function signature(secret, value) {
  if (!secret || secret.length < 32) fail(503, 'Sign-in is not configured yet.');
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return Array.from(new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(value))), n => n.toString(16).padStart(2, '0')).join('');
}
function equal(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}
export async function boundedBody(response, limit, timeout = 10000) {
  if (Number(response.headers.get('Content-Length')) > limit) { await response.body?.cancel(); fail(413, 'The file or response is too large.'); }
  const reader = response.body?.getReader();
  if (!reader) return new Uint8Array();
  const chunks = []; let size = 0;
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; void reader.cancel().catch(() => {}); }, timeout);
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (timedOut) fail(408, 'The request took too long. Please try again.');
      if (done) break;
      size += value.length;
      if (size > limit) fail(413, 'The file or response is too large.');
      chunks.push(value);
    }
  } catch (error) { await reader.cancel(); throw error; } finally { clearTimeout(timer); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes;
}
// Drawing an image runs minutes past the ten seconds every other outside call is given, so the
// deadline is a parameter rather than a constant.
export async function remote(fetcher, url, options = {}, limit = 200 * 1024, timeout = 10000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetcher(url, { ...options, redirect: 'manual', signal: controller.signal });
    const bytes = await boundedBody(response, limit, timeout);
    return { status: response.status, ok: response.ok, headers: response.headers, bytes, text: () => new TextDecoder().decode(bytes) };
  } finally { clearTimeout(timer); }
}
async function bodyJSON(request) {
  try {
    const value = JSON.parse(new TextDecoder().decode(await boundedBody(request, 16384)));
    if (!value || typeof value !== 'object' || Array.isArray(value)) fail(400, 'Send a valid JSON object.');
    return value;
  }
  catch (e) { if (e instanceof HttpError) throw e; fail(400, 'Send a valid JSON object.'); }
}
export function createApp({ fetcher = fetch, now = () => Date.now(), seedRoutes = async () => null, proofRoutes = async () => null, artRoutes = async () => null } = {}) {
  return async function handle(request, env) {
    const url = new URL(request.url), path = url.pathname;
    const bearerRoute = (request.method === 'POST' && ['/api/seeds', '/api/media'].includes(path)) ||
      (request.method === 'PUT' && /^\/api\/seeds\/[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/.test(path)) ||
      (['GET', 'POST'].includes(request.method) && /^\/api\/seeds\/[a-z][a-z0-9]*(?:-[a-z0-9]+)*\/art$/.test(path)) ||
      (request.method === 'GET' && path === '/api/seeds/mine');
    const bearerMatch = bearerRoute && request.headers.get('Authorization')?.match(/^Bearer\s+(.+)$/i);
    const get = async key => env.FARM.get(key, 'json');
    const put = async (key, value) => env.FARM.put(key, JSON.stringify(value));
    const del = async key => env.FARM.delete(key);
    const signed = async value => `${value}.${await signature(env.SESSION_SECRET, value)}`;
    const unsign = async value => {
      if (!value) return null;
      const dot = value.lastIndexOf('.');
      if (dot < 0) return null;
      const raw = value.slice(0, dot);
      return equal(await signature(env.SESSION_SECRET, raw), value.slice(dot + 1)) ? raw : null;
    };
    async function session() {
      const id = await unsign(cookies(request)[COOKIE]);
      const record = id && await get('session:' + id);
      return record && record.expires > now() ? { id, ...record, user: await get('user:' + record.userId) } : null;
    }
    async function bearerUser() {
      if (!bearerMatch) return null;
      const token = bearerMatch[1];
      if (!/^farm_[a-f0-9]{40}$/.test(token)) return null;
      const hash = await sha256(encoder.encode(token));
      const id = await get('api-token-hash:' + hash);
      const record = id && await get('api-token:' + id);
      if (!record || record.hash !== hash) return null;
      const user = await get('user:' + record.userId);
      if (!user) return null;
      record.lastUsedAt = new Date(now()).toISOString();
      await put('api-token:' + id, record);
      return ensureMaker(user, get, put, random);
    }
    async function setSession(userId) {
      const previous = await session();
      if (previous) await del('session:' + previous.id);
      const id = random();
      await put('session:' + id, { userId, expires: now() + 30 * DAY });
      return cookie(COOKIE, await signed(id), 30 * 86400);
    }
    async function account(index, property, value, intendedUser = null) {
      const owner = await get(index);
      if (intendedUser && owner && owner !== intendedUser) fail(409, 'That sign-in is already linked to another account.');
      const id = intendedUser || owner || crypto.randomUUID();
      const user = await get('user:' + id) || { id, createdAt: new Date(now()).toISOString() };
      if (user[property] && JSON.stringify(user[property]) !== JSON.stringify(value)) {
        if (property === 'email' || user.github.id !== value.id) fail(409, 'This account already has a different sign-in linked.');
      }
      user[property] = value;
      makerDefaults(user);
      await put('user:' + id, user); await put(index, id);
      return user;
    }
    try {
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method) && !bearerMatch && request.headers.get('Origin') !== ORIGIN) fail(403, 'Please submit this form from tiinyapp.farm.');
      if (path === '/api/auth/start' && request.method === 'POST') {
        const input = await bodyJSON(request);
        const email = typeof input?.email === 'string' ? input.email.trim().toLowerCase() : '';
        if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) fail(400, 'Enter a valid email address.');
        if (!env.RESEND_API_KEY) fail(503, 'Email sign-in is not configured yet.');
        const address = await sha256(encoder.encode(email));
        const history = (await get('email-rate:' + address) || []).filter(t => t > now() - 3600000);
        if (history.length >= 3) fail(429, 'Three codes per hour; please try again later.');
        await put('email-rate:' + address, [...history, now()]);
        // Rejection sampling avoids bias in the six-digit code.
        let number;
        do { number = crypto.getRandomValues(new Uint32Array(1))[0]; } while (number >= 4294000000);
        const code = String(number % 1000000).padStart(6, '0'), salt = random();
        const current = await session();
        await put('email-code:' + address, { hash: await signature(env.SESSION_SECRET, salt + code), salt,
          expires: now() + 600000, attempts: 0, userId: current?.userId || null });
        const result = await remote(fetcher, 'https://api.resend.com/emails', { method: 'POST', headers: {
          Authorization: `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json',
        }, body: JSON.stringify({ from: 'Titanium Bot <farm@tiinyapp.farm>', to: [email],
          subject: 'Your tiinyapp.farm sign-in code', text: `Your sign-in code is ${code}. It expires in 10 minutes.` }) });
        if (!result.ok) { await del('email-code:' + address); fail(502, 'The code could not be sent. Please try again later.'); }
        return json({ sent: true });
      }
      if (path === '/api/auth/verify' && request.method === 'POST') {
        const input = await bodyJSON(request);
        const email = typeof input?.email === 'string' ? input.email.trim().toLowerCase() : '';
        const address = await sha256(encoder.encode(email)), key = 'email-code:' + address;
        const challenge = await get(key), current = await session();
        if (!challenge || challenge.expires <= now() || challenge.attempts >= 5) fail(400, 'That code has expired or is invalid. Request a new one.');
        if (challenge.userId !== (current?.userId || null)) fail(403, 'Finish linking from the account that requested this code.');
        challenge.attempts++; await put(key, challenge);
        if (typeof input.code !== 'string' || !/^\d{6}$/.test(input.code) ||
            !equal(challenge.hash, await signature(env.SESSION_SECRET, challenge.salt + input.code))) fail(400, 'That code has expired or is invalid. Request a new one.');
        await del(key);
        const user = await account('email:' + address, 'email', email, challenge.userId);
        return json({ user }, 200, { 'Set-Cookie': await setSession(user.id) });
      }
      if (path === '/api/auth/github' && request.method === 'GET') {
        if (!env.GITHUB_CLIENT_ID || !env.GITHUB_CLIENT_SECRET) fail(503, 'GitHub sign-in is not configured yet.');
        const state = random(), current = await session();
        await put('oauth:' + state, { expires: now() + 600000, userId: current?.userId || null });
        const target = new URL('https://github.com/login/oauth/authorize');
        target.search = new URLSearchParams({ client_id: env.GITHUB_CLIENT_ID, scope: 'read:user', state,
          redirect_uri: ORIGIN + '/api/auth/github/callback' }).toString();
        return redirect(target.href, { 'Set-Cookie': cookie('__Host-farm-oauth', await signed(state), 600) });
      }
      if (path === '/api/auth/github/callback' && request.method === 'GET') {
        const state = url.searchParams.get('state'), stored = state && /^[a-f0-9]{64}$/.test(state) && await get('oauth:' + state);
        const current = await session();
        if (!stored || stored.expires <= now() || state !== await unsign(cookies(request)['__Host-farm-oauth']) ||
            stored.userId !== (current?.userId || null)) fail(403, 'GitHub sign-in expired or the state did not match.');
        await del('oauth:' + state);
        const code = url.searchParams.get('code');
        if (!code) fail(400, 'GitHub sign-in was not completed.');
        const tokenResponse = await remote(fetcher, 'https://github.com/login/oauth/access_token', {
          method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({ client_id: env.GITHUB_CLIENT_ID, client_secret: env.GITHUB_CLIENT_SECRET,
            code, redirect_uri: ORIGIN + '/api/auth/github/callback' }),
        });
        const token = tokenResponse.ok && JSON.parse(tokenResponse.text()).access_token;
        if (!token) fail(502, 'GitHub sign-in could not be completed.');
        const profileResponse = await remote(fetcher, 'https://api.github.com/user', { headers: {
          Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'User-Agent': 'tiinyapp-farm',
        } });
        if (!profileResponse.ok) fail(502, 'GitHub profile could not be read.');
        const profile = JSON.parse(profileResponse.text());
        if (!Number.isSafeInteger(profile.id) || !profile.login) fail(502, 'GitHub returned an invalid profile.');
        const github = { id: profile.id, login: profile.login, name: profile.name || profile.login, avatar: profile.avatar_url || '' };
        const user = await account('github:' + github.id, 'github', github, stored.userId);
        const response = redirect('/submit/', { 'Set-Cookie': await setSession(user.id) });
        response.headers.append('Set-Cookie', cookie('__Host-farm-oauth', '', 0));
        return response;
      }
      if (path === '/api/auth/logout' && request.method === 'POST') {
        const current = await session(); if (current) await del('session:' + current.id);
        return json({ signedOut: true }, 200, { 'Set-Cookie': cookie(COOKIE, '', 0) });
      }
      const sessionUser = async () => { const user = (await session())?.user; return user ? ensureMaker(user, get, put, random) : null; };
      const currentUser = async () => bearerMatch ? bearerUser() : sessionUser();
      if (path === '/api/me' && request.method === 'GET') return json({ user: await currentUser() });
      if (path === '/api/tokens' && request.method === 'POST') {
        const user = await sessionUser();
        if (!user) fail(401, 'Sign in to your account first.');
        if (!user.tiinyverse) fail(403, 'Verify you own a Tiiny before creating an API token.');
        const input = await bodyJSON(request), name = typeof input.name === 'string' ? input.name.trim() : '';
        if (!name || name.length > 80) fail(400, 'Give this API token a name of 80 characters or fewer.');
        const key = 'user-api-tokens:' + user.id;
        const ids = await get(key) || [];
        const active = [];
        for (const id of ids) if (await get('api-token:' + id)) active.push(id);
        if (active.length >= 5) fail(409, 'You can have up to five API tokens. Revoke one before creating another.');
        const token = 'farm_' + random(20), hash = await sha256(encoder.encode(token)), id = random(16);
        const record = { id, userId: user.id, name, prefix: token.slice(0, 13), hash,
          createdAt: new Date(now()).toISOString(), lastUsedAt: null };
        await put('api-token:' + id, record);
        await put('api-token-hash:' + hash, id);
        await put(key, [...active, id]);
        return json({ token, id, name, prefix: record.prefix, createdAt: record.createdAt, lastUsedAt: null }, 201);
      }
      if (path === '/api/tokens' && request.method === 'GET') {
        const user = await sessionUser();
        if (!user) fail(401, 'Sign in to your account first.');
        const key = 'user-api-tokens:' + user.id, ids = await get(key) || [], active = [], tokens = [];
        for (const id of ids) {
          const record = await get('api-token:' + id);
          if (!record || record.userId !== user.id) continue;
          active.push(id);
          tokens.push({ id: record.id, name: record.name, prefix: record.prefix,
            createdAt: record.createdAt, lastUsedAt: record.lastUsedAt });
        }
        if (active.length !== ids.length) await put(key, active);
        return json({ tokens });
      }
      const tokenDelete = request.method === 'DELETE' && path.match(/^\/api\/tokens\/([a-f0-9]{32})$/);
      if (tokenDelete) {
        const user = await sessionUser();
        if (!user) fail(401, 'Sign in to your account first.');
        const id = tokenDelete[1], record = await get('api-token:' + id);
        if (!record || record.userId !== user.id) fail(404, 'That API token was not found.');
        await del('api-token:' + id);
        await del('api-token-hash:' + record.hash);
        const key = 'user-api-tokens:' + user.id, ids = await get(key) || [];
        await put(key, ids.filter(value => value !== id));
        return json({ revoked: true });
      }
      const context = { request, env, url, path, get, put, del, now, fetcher, bodyJSON, random,
        currentUser, requireUser: async () => { const user = await currentUser(); if (!user) fail(401, 'Sign in to your account first.'); return user; } };
      return await socialRoutes(context) || await makerRoutes(context) || await proofRoutes(context) || await artRoutes(context) || await seedRoutes(context) || json({ error: 'This route does not exist.' }, 404);
    } catch (error) {
      return json({ error: error instanceof HttpError ? error.message : 'The request could not be completed. Please try again.' }, error.status || 502);
    }
  };
}
