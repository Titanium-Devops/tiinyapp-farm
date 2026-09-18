import test from 'node:test';
import assert from 'node:assert/strict';
import { gzipSync } from 'node:zlib';
import { generateKeyPairSync, createPublicKey } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import { spawnSync } from 'node:child_process';
import { createApp, sha256, boundedBody } from '../worker/index.mjs';
import { proofRoutes } from '../worker/proof.mjs';
import { seedRoutes, releaseURL } from '../worker/seeds.mjs';
import { artRoutes, headerPrompt, iconPrompt, cleanScene, DAILY } from '../worker/art.mjs';
import { releaseRoutes, appJWT, privateKeyBytes, pickRelease, pickURL, serialize } from '../worker/release.mjs';
import { checkManifest } from '../worker/manifest.mjs';
import { seedRows, seedWords, seedStackHTML } from '../worker/catalog.mjs';
import worker, { FarmCoordinator } from '../worker/main.mjs';
const ORIGIN = 'https://tiinyapp.farm';
const PROFILE = 'https://www.tiinyverse.com/users/39628b1e-e94e-4bd8-800e-5437d5336e1f';
const archive = gzipSync(Buffer.from('fixture source archive; extraction is checked separately in Python CI'));
const DRAWINGS = 'https://api.openai.com/v1/images/generations';
// Only the magic bytes matter: the Worker sniffs the type it was sent rather than trusting the ask.
const drawnPNG = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), Buffer.from('fixture icon pixels')]);
const drawnWEBP = Buffer.concat([Buffer.from('RIFF'), Buffer.from([0, 0, 0, 0]), Buffer.from('WEBP'), Buffer.from('fixture header pixels')]);
// A fake app repository with two releases, so the button never touches GitHub in tests.
const APP_REPO = 'maker/fake-app';
const ARCHIVES = new Map(['v0.1.0', 'v0.1.1', 'v0.2.0'].map(tag => [tag, gzipSync(Buffer.from('fake-app ' + tag + ' source'))]));
const archiveURL = tag => `https://github.com/${APP_REPO}/archive/refs/tags/${tag}.tar.gz`;
const assetURL = (tag, name) => `https://github.com/${APP_REPO}/releases/download/${tag}/${name}`;
const githubRelease = (tag, extra = {}) => ({ tag_name: tag, draft: false, prerelease: false, assets: [], body: 'sha256: ' + '0'.repeat(64), ...extra });
const KEYS = generateKeyPairSync('rsa', { modulusLength: 2048, publicKeyEncoding: { type: 'spki', format: 'pem' }, privateKeyEncoding: { type: 'pkcs1', format: 'pem' } });
function listedApp(changes = {}) {
  return { id: 'fake-app', name: 'Fake App', pitch: 'A stand-in app.', description: 'Two releases on GitHub.',
    version: '0.1.0', author: { name: 'Aster & Fern', url: PROFILE, tiinyverse: PROFILE }, license: 'MIT',
    homepage: 'https://github.com/maker/fake-app', repo: 'https://github.com/maker/fake-app', screenshots: [],
    release: { url: archiveURL('v0.1.0'), sha256: 'a'.repeat(64), size: 11 }, entry: { command: 'python3 app.py' },
    requires: { ports: [7788], device: { models: ['chat'], npuUnits: 4 } }, permissions: ['network'],
    tags: ['developer-tools'], verified: false, addedAt: '2026-09-12', updatedAt: '2026-09-12', ...changes };
}
class Store {
  values = new Map();
  async get(key, type) { const value = this.values.get(key); return type === 'json' && value ? JSON.parse(value) : value ?? null; }
  async put(key, value) { this.values.set(key, value); }
  async delete(key) { this.values.delete(key); }
}
function fixture({ appKeys = true } = {}) {
  let clock = Date.parse('2026-09-12T12:00:00Z');
  const store = new Store(), objects = new Map(), mails = [], calls = [], manifests = [], published = new Map();
  const branches = new Map(), releasePulls = [];
  let releases = [githubRelease('v0.1.0'), githubRelease('v0.1.1')], publicOnly = false;
  let html = '<h1>Aster &amp; Fern</h1>', githubId = 42, githubFail = '', profileStatus = 200, resendStatus = 200;
  const draws = [];
  let drawStatus = 200, drawPayload = null;
  const env = { FARM: store, SESSION_SECRET: 'test-secret-with-at-least-32-characters', RESEND_API_KEY: 'resend-secret',
    GITHUB_CLIENT_ID: 'client', GITHUB_CLIENT_SECRET: 'client-secret', FARM_GITHUB_TOKEN: 'farm-only-secret',
    OPENAI_API_KEY: 'drawing-only-secret',
    ...(appKeys ? { FARM_APP_ID: '456', FARM_APP_PRIVATE_KEY: KEYS.privateKey } : {}),
    SEEDS: { async put(key, value, options) { objects.set(key, { value, options }); },
      async get(key) { const object = objects.get(key); return object && { body: object.value, size: object.value.length, httpEtag: '"fixture"' }; },
      async delete(key) { objects.delete(key); } },
    ASSETS: { fetch: async request => {
      const path = new URL(request.url).pathname;
      if (path === '/catalog.json') return Response.json({ cli: '0.1.9', apps: [...published.values()] });
      const seed = published.get(path.match(/^\/manifests\/(.+)\.json$/)?.[1]);
      return seed ? Response.json(seed) : new Response('static farm');
    } } };
  const fetcher = async (url, options = {}) => {
    calls.push({ url: String(url), ...options });
    const reply = (body, status = 200) => new Response(JSON.stringify(body), { status });
    if (String(url) === DRAWINGS) {
      const body = JSON.parse(options.body);
      assert.equal(options.headers.Authorization, 'Bearer drawing-only-secret');
      draws.push(body);
      if (drawStatus !== 200) return new Response(JSON.stringify(drawPayload ?? { error: { message: 'never repeat me' } }), { status: drawStatus });
      if (drawPayload) return reply(drawPayload);
      const pixels = body.output_format === 'png' ? drawnPNG : drawnWEBP;
      return reply({ created: 1, data: [{ b64_json: pixels.toString('base64') }], usage: { output_tokens: 4160, total_tokens: 4300 } });
    }
    if (String(url) === 'https://api.resend.com/emails') { mails.push(JSON.parse(options.body)); return reply({ id: 'mail' }, resendStatus); }
    if (String(url).startsWith('https://www.tiinyverse.com/')) {
      assert.equal(options.headers['User-Agent'], 'tiinyapp-farm-verifier/1.0'); assert.equal(options.redirect, 'manual'); assert.ok(options.signal);
      return new Response(html, { status: profileStatus });
    }
    if (String(url) === 'https://github.com/login/oauth/access_token') return reply({ access_token: 'never-store-this-token' });
    if (String(url) === 'https://api.github.com/user') return reply({ id: githubId, login: 'gardener' + githubId, name: 'GitHub name', avatar_url: 'https://example.org/avatar.png' });
    if (String(url).startsWith('https://api.github.com/repos/' + APP_REPO + '/releases')) {
      if (publicOnly && options.headers?.Authorization) return reply({ message: 'Not Found' }, 404);
      return reply(releases);
    }
    if (ARCHIVES.has(String(url).match(/\/(v\d+\.\d+\.\d+)[./]/)?.[1]) && /github\.com/.test(String(url))) {
      const tag = String(url).match(/\/(v\d+\.\d+\.\d+)[./]/)[1];
      return new Response(ARCHIVES.get(tag));
    }
    if (String(url) === 'https://api.github.com/app/installations/7/access_tokens') {
      assert.match(options.headers.Authorization, /^Bearer eyJ/, 'the installation token is minted with the app JWT');
      return reply({ token: 'app-installation-token' }, 201);
    }
    if (String(url).startsWith('https://api.github.com/repos/Titanium-Devops/tiinyapp-farm')) {
      const route = String(url).replace('https://api.github.com/repos/Titanium-Devops/tiinyapp-farm', '');
      if (String(url).includes('/commits/')) assert.equal(options.headers.Authorization, undefined);
      else if (route === '/installation') assert.match(options.headers.Authorization, /^Bearer eyJ/);
      else assert.ok(['Bearer farm-only-secret', 'Bearer app-installation-token'].includes(options.headers.Authorization),
        'unexpected credential ' + options.headers.Authorization);
      if (githubFail && route.includes(githubFail)) return reply({ error: 'fake failure' }, 500);
      if (route === '/installation') return reply({ id: 7 });
      if (route === '') return reply({ default_branch: 'main' });
      if (route.startsWith('/contents/') && options.method === 'GET') {
        const [, id, ref] = route.match(/manifests\/(.+?)\.json(?:\?ref=(.+))?$/) || [];
        if (ref) {
          const held = branches.get(decodeURIComponent(ref) + ':' + id);
          return held ? reply({ sha: 'd'.repeat(40), content: Buffer.from(held).toString('base64') }) : reply({}, 404);
        }
        const seed = published.get(id);
        return seed ? reply({ sha: 'c'.repeat(40), content: Buffer.from(JSON.stringify(seed)).toString('base64') }) : reply({}, 404);
      }
      if (route.startsWith('/contents/') && options.method === 'PUT') {
        const sent = JSON.parse(options.body), text = Buffer.from(sent.content, 'base64').toString();
        manifests.push(JSON.parse(text));
        if (sent.branch) branches.set(sent.branch + ':' + route.match(/manifests\/(.+?)\.json/)[1], text);
        return reply({ content: {} });
      }
      if (route.startsWith('/git/ref/')) return reply({ object: { sha: 'a'.repeat(40) } });
      if (route.startsWith('/git/refs')) return reply({});
      if (route.startsWith('/pulls?')) return reply(releasePulls.filter(pull => pull.state === 'open'));
      if (/^\/pulls\/\d+$/.test(route) && options.method === 'PATCH') {
        const pull = releasePulls.find(item => item.number === Number(route.split('/')[2]));
        Object.assign(pull, JSON.parse(options.body));
        return reply(pull);
      }
      if (route === '/pulls' && JSON.parse(options.body || '{}').head?.startsWith('farm-release/')) {
        const sent = JSON.parse(options.body);
        const pull = { number: 200 + releasePulls.length, state: 'open', title: sent.title, body: sent.body,
          base: { ref: sent.base }, head: { ref: sent.head, repo: { full_name: 'Titanium-Devops/tiinyapp-farm' } },
          html_url: 'https://github.com/Titanium-Devops/tiinyapp-farm/pull/' + (200 + releasePulls.length) };
        releasePulls.push(pull);
        return reply(pull, 201);
      }
      if (route === '/pulls') return reply({ number: 123, html_url: 'https://github.com/Titanium-Devops/tiinyapp-farm/pull/123' }, 201);
      if (route === '/pulls/123') return reply({ state: 'open', head: { sha: 'b'.repeat(40) } });
      if (route.endsWith('/labels')) return reply([{ name: 'from-the-site' }]);
      if (route.includes('/check-runs')) return reply({ check_runs: [{ name: 'Manifest checks', status: 'completed', conclusion: 'success' }] });
      if (route.includes('/status?')) return reply({ statuses: [{ context: 'build', state: 'success' }] });
      if (route.includes('/reviews?')) return reply([{ user: { id: 9 }, state: 'CHANGES_REQUESTED' }]);
      throw new Error('Unexpected GitHub route: ' + route);
    }
    if (String(url) === 'https://releases.example.org/seed.tar.gz') return new Response(archive);
    if (String(url) === 'https://github.example.org/releases/download/v1/seed.tar.gz') return new Response(null, { status: 302, headers: { location: 'https://objects.example.org/seed.tar.gz' } });
    if (String(url) === 'https://objects.example.org/seed.tar.gz') return new Response(archive);
    if (String(url) === 'https://loop.example.org/a') return new Response(null, { status: 302, headers: { location: 'https://loop.example.org/a' } });
    throw new Error('Unexpected fetch: ' + url);
  };
  const app = createApp({ fetcher, now: () => clock, proofRoutes, releaseRoutes, seedRoutes, artRoutes });
  const call = async (path, body, session = '', extra = {}, method = 'POST') => app(new Request(ORIGIN + path, {
    ...(body === undefined ? {} : { method, body: body instanceof FormData ? body : JSON.stringify(body) }),
    headers: { Origin: ORIGIN, ...(session ? { Cookie: session } : {}), ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...extra },
  }), env);
  async function email(address = 'grower@example.org', session = '') {
    assert.equal((await call('/api/auth/start', { email: address }, session)).status, 200);
    const code = mails.at(-1).text.match(/\b\d{6}\b/)[0];
    const result = await call('/api/auth/verify', { email: address, code }, session);
    assert.equal(result.status, 200, await result.clone().text());
    assert.match(result.headers.get('set-cookie'), /HttpOnly; Secure; SameSite=Lax; Max-Age=2592000/);
    return { cookie: result.headers.get('set-cookie').split(';')[0], user: (await result.json()).user, code };
  }
  async function proof(session) {
    const response = await call('/api/tiinyverse/link', { profileUrl: PROFILE }, session);
    assert.equal(response.status, 200);
    const result = await response.json(); html = `<h1>Aster &amp; Fern</h1><p>${result.code}</p>`;
    assert.equal((await call('/api/tiinyverse/verify', {}, session)).status, 200);
  }
  return { env, store, objects, mails, manifests, published, calls, draws, call, email, proof, fetcher,
    branches, releasePulls, setReleases: list => { releases = list; }, publicOnly: () => { publicOnly = true; },
    advance: n => { clock += n; }, html: s => { html = s; }, githubId: n => { githubId = n; }, githubFail: s => { githubFail = s; },
    profileStatus: n => { profileStatus = n; }, resendStatus: n => { resendStatus = n; }, now: () => clock,
    drawing: (status, payload = null) => { drawStatus = status; drawPayload = payload; } };
}
function seedForm({ upload = false, ...changes } = {}) {
  const form = new FormData();
  for (const [key, value] of Object.entries({ id: 'little-library', name: 'Little library', pitch: 'A seed for your Tiiny', description: 'Source included for review.',
    version: '0.1.0', license: 'MIT', tags: 'library', permissions: 'network', models: 'qwen3:8b', npuUnits: '1', ...changes })) form.set(key, value);
  if (upload) form.set('archive', new Blob([archive], { type: 'application/gzip' }), 'little-library.tar.gz');
  else if (!form.has('releaseUrl')) form.set('releaseUrl', 'https://releases.example.org/seed.tar.gz');
  return form;
}

test('email: six digits, HMAC only, normalization, secure session, single redemption, logout', async () => {
  const f = fixture(), signed = await f.email(' GROWER@example.org ');
  assert.match(signed.code, /^\d{6}$/);
  assert.equal(signed.user.email, 'grower@example.org');
  assert.equal(f.mails[0].from, 'Titanium Bot <farm@tiinyapp.farm>');
  assert.ok(!JSON.stringify([...f.store.values]).includes(JSON.stringify(signed.code)));
  assert.equal((await (await f.call('/api/me', undefined, signed.cookie)).json()).user.id, signed.user.id);
  assert.equal((await f.call('/api/auth/verify', { email: signed.user.email, code: signed.code })).status, 400);
  const logout = await f.call('/api/auth/logout', {}, signed.cookie);
  assert.match(logout.headers.get('set-cookie'), /HttpOnly; Secure; SameSite=Lax; Max-Age=0/);
  assert.equal((await (await f.call('/api/me', undefined, signed.cookie)).json()).user, null);
});
test('email throttles three sends per rolling hour, expires and limits guesses', async () => {
  const f = fixture();
  for (let i = 0; i < 3; i++) assert.equal((await f.call('/api/auth/start', { email: 'x@example.org' })).status, 200);
  const entries = [...f.store.values.entries()].filter(([key]) => key.startsWith('email-code:'));
  assert.match(JSON.parse(entries[0][1]).hash, /^[a-f0-9]{64}$/);
  assert.equal((await f.call('/api/auth/start', { email: 'X@example.org' })).status, 429);
  const code = f.mails.at(-1).text.match(/\b\d{6}\b/)[0];
  const wrong = code === '000000' ? '000001' : '000000';
  for (let i = 0; i < 5; i++) assert.equal((await f.call('/api/auth/verify', { email: 'x@example.org', code: wrong })).status, 400);
  assert.equal((await f.call('/api/auth/verify', { email: 'x@example.org', code })).status, 400);
  f.advance(3600001);
  assert.equal((await f.call('/api/auth/start', { email: 'x@example.org' })).status, 200);
  f.advance(600001);
  assert.equal((await f.call('/api/auth/verify', { email: 'x@example.org', code: f.mails.at(-1).text.match(/\b\d{6}\b/)[0] })).status, 400);
});
test('failed email delivery invalidates the challenge; CSRF, bad body and tampered sessions fail', async () => {
  const f = fixture(); f.resendStatus(500);
  assert.equal((await f.call('/api/auth/start', { email: 'x@example.org' })).status, 502);
  assert.ok(![...f.store.values.keys()].some(key => key.startsWith('email-code:')));
  assert.equal((await f.call('/api/auth/start', { email: 'x@example.org' }, '', { Origin: 'https://evil.example' })).status, 403);
  assert.equal((await f.call('/api/auth/start', [])).status, 400);
  assert.equal((await f.call('/api/auth/start', { email: 'bad' })).status, 400);
  assert.equal((await (await f.call('/api/me', undefined, '__Host-farm=forged.signature')).json()).user, null);
});
test('session expires after thirty days and rotating its secret preserves email identity', async () => {
  const f = fixture(), first = await f.email();
  f.advance(30 * 86400000 + 1);
  assert.equal((await (await f.call('/api/me', undefined, first.cookie)).json()).user, null);
  f.env.SESSION_SECRET = 'a-different-32-character-session-secret';
  const second = await f.email(); assert.equal(second.user.id, first.user.id);
});
async function github(f, session = '') {
  const start = await f.call('/api/auth/github', undefined, session);
  assert.equal(start.status, 302);
  const location = new URL(start.headers.get('location'));
  assert.equal(location.searchParams.get('scope'), 'read:user');
  assert.equal(location.searchParams.get('redirect_uri'), ORIGIN + '/api/auth/github/callback');
  const oauthCookie = start.headers.get('set-cookie').split(';')[0];
  return { path: '/api/auth/github/callback?state=' + location.searchParams.get('state') + '&code=fixture', cookies: [session, oauthCookie].filter(Boolean).join('; ') };
}
test('GitHub state cookie and one-time callback; OAuth token never stored', async () => {
  const f = fixture(), flow = await github(f);
  assert.equal((await f.call(flow.path)).status, 403);
  const callback = await f.call(flow.path, undefined, flow.cookies);
  assert.equal(callback.status, 302);
  assert.equal((await f.call(flow.path, undefined, flow.cookies)).status, 403);
  const session = callback.headers.getSetCookie()[0].split(';')[0];
  const { user } = await (await f.call('/api/me', undefined, session)).json();
  assert.equal(user.github.id, 42); assert.equal(user.email, undefined);
  assert.ok(!JSON.stringify([...f.store.values]).includes('never-store-this-token'));
});
test('email then GitHub and GitHub then email link to the same account; cannot steal a linked sign-in', async () => {
  const f = fixture(), first = await f.email();
  const flow = await github(f, first.cookie), callback = await f.call(flow.path, undefined, flow.cookies);
  assert.equal(callback.status, 302);
  const session = callback.headers.getSetCookie()[0].split(';')[0];
  const { user } = await (await f.call('/api/me', undefined, session)).json();
  assert.equal(user.id, first.user.id); assert.equal(user.github.id, 42);
  const other = await f.email('other@example.org'), collision = await github(f, other.cookie);
  assert.equal((await f.call(collision.path, undefined, collision.cookies)).status, 409);
  f.githubId(43);
  const thirdFlow = await github(f), third = await f.call(thirdFlow.path, undefined, thirdFlow.cookies);
  const thirdCookie = third.headers.getSetCookie()[0].split(';')[0];
  const before = (await (await f.call('/api/me', undefined, thirdCookie)).json()).user;
  const linked = await f.email('third@example.org', thirdCookie);
  assert.equal(linked.user.id, before.id); assert.equal(linked.user.github.id, 43);
});
test('email link requires the initiating account session', async () => {
  const f = fixture(), first = await f.email();
  await f.call('/api/auth/start', { email: 'new@example.org' }, first.cookie);
  const code = f.mails.at(-1).text.match(/\b\d{6}\b/)[0];
  assert.equal((await f.call('/api/auth/verify', { email: 'new@example.org', code })).status, 403);
});
test('proof: strict URL, exact code, extracted name, reverse owner lookup, claimed-profile refusal', async () => {
  const f = fixture(), first = await f.email(), second = await f.email('other@example.org');
  assert.equal((await f.call('/api/tiinyverse/link', { profileUrl: PROFILE })).status, 401);
  for (const value of [PROFILE + '?x=1', PROFILE + '/', PROFILE.replace('www.', ''), PROFILE.replace('https:', 'http:'), 'https://evil.example/users/id']) {
    assert.equal((await f.call('/api/tiinyverse/link', { profileUrl: value }, first.cookie)).status, 400);
  }
  assert.deepEqual(await (await f.call('/api/owners?profile=' + encodeURIComponent(PROFILE))).json(), { verified: false, name: null });
  const one = await (await f.call('/api/tiinyverse/link', { profileUrl: PROFILE }, first.cookie)).json();
  assert.match(one.code, /^farm-[a-f0-9]{6}$/);
  await f.call('/api/tiinyverse/link', { profileUrl: PROFILE }, second.cookie);
  f.html('<h1>Aster</h1><p>' + one.code + 'extra</p>');
  assert.equal((await f.call('/api/tiinyverse/verify', {}, first.cookie)).status, 422);
  f.html('<h1>Aster &amp; Fern</h1><p>' + one.code + '</p>');
  assert.equal((await f.call('/api/tiinyverse/verify', {}, first.cookie)).status, 200);
  assert.equal((await f.call('/api/tiinyverse/verify', {}, second.cookie)).status, 409);
  assert.equal((await f.call('/api/tiinyverse/link', { profileUrl: PROFILE }, second.cookie)).status, 409);
  assert.deepEqual(await (await f.call('/api/owners?profile=' + encodeURIComponent(PROFILE))).json(), { verified: true, name: 'Aster & Fern' });
});
test('proof refuses expiry, redirects and pages over 200 KB; missing name fails closed', async () => {
  const f = fixture(), first = await f.email();
  const link = await (await f.call('/api/tiinyverse/link', { profileUrl: PROFILE }, first.cookie)).json();
  f.html(link.code); assert.equal((await f.call('/api/tiinyverse/verify', {}, first.cookie)).status, 422);
  f.profileStatus(302); assert.equal((await f.call('/api/tiinyverse/verify', {}, first.cookie)).status, 422);
  f.profileStatus(200); f.html('x'.repeat(200 * 1024 + 1));
  assert.equal((await f.call('/api/tiinyverse/verify', {}, first.cookie)).status, 413);
  f.advance(86400001); assert.equal((await f.call('/api/tiinyverse/verify', {}, first.cookie)).status, 400);
});
test('release form produces schema-valid manifest with TiinyVerse name, computed checksum and bot PR label', async () => {
  const f = fixture(), first = await f.email(); await f.proof(first.cookie);
  const response = await f.call('/api/seeds', seedForm(), first.cookie);
  assert.equal(response.status, 201, await response.clone().text());
  const manifest = f.manifests[0]; checkManifest(manifest);
  assert.deepEqual(manifest.author, { name: 'Aster & Fern', url: PROFILE, tiinyverse: PROFILE });
  assert.equal(manifest.repo, undefined); assert.equal(manifest.verified, false);
  assert.equal(manifest.release.sha256, await sha256(archive)); assert.equal(manifest.release.size, archive.length);
  assert.ok(f.calls.some(call => call.url.endsWith('/issues/123/labels') && call.body.includes('from-the-site')));
  assert.ok(!f.calls.some(call => call.url === 'https://api.github.com/user'));
  const python = spawnSync('python3', ['-c', 'import json,sys,runpy; runpy.run_path("scripts/check-manifest.py")["check_manifest"](json.load(sys.stdin))'], { input: JSON.stringify(manifest), encoding: 'utf8' });
  assert.equal(python.status, 0, python.stderr);
});
test('API tokens are revealed once, listed without secrets, capped at five and revocable', async () => {
  const f = fixture(), signed = await f.email();
  assert.equal((await f.call('/api/tokens', { name: 'Codex' }, signed.cookie)).status, 403);
  await f.proof(signed.cookie);
  const created = await f.call('/api/tokens', { name: ' Codex ' }, signed.cookie);
  assert.equal(created.status, 201, await created.clone().text());
  const first = await created.json();
  assert.match(first.token, /^farm_[a-f0-9]{40}$/);
  assert.equal(first.name, 'Codex');
  assert.ok(first.token.startsWith(first.prefix));
  assert.ok(!JSON.stringify([...f.store.values]).includes(first.token));
  let listed = await (await f.call('/api/tokens', undefined, signed.cookie)).json();
  assert.deepEqual(listed.tokens, [{ id: first.id, name: 'Codex', prefix: first.prefix,
    createdAt: first.createdAt, lastUsedAt: null }]);
  assert.ok(!JSON.stringify(listed).includes(first.token));
  for (let i = 1; i < 5; i++) assert.equal((await f.call('/api/tokens', { name: `Assistant ${i}` }, signed.cookie)).status, 201);
  assert.equal((await f.call('/api/tokens', { name: 'One too many' }, signed.cookie)).status, 409);
  assert.equal((await f.call('/api/tokens/' + first.id, {}, signed.cookie, {}, 'DELETE')).status, 200);
  listed = await (await f.call('/api/tokens', undefined, signed.cookie)).json();
  assert.equal(listed.tokens.length, 4);
  assert.ok(!listed.tokens.some(token => token.id === first.id));
  assert.equal((await f.call('/api/tokens', { name: 'Replacement' }, signed.cookie)).status, 201);
});
test('Bearer tokens submit apps without Origin, update last use, support media/status and fail after revocation', async () => {
  const f = fixture(), signed = await f.email(); await f.proof(signed.cookie);
  const issued = await (await f.call('/api/tokens', { name: 'Farm CLI' }, signed.cookie)).json();
  const auth = { Authorization: `Bearer ${issued.token}`, Origin: 'https://assistant.example' };
  const submitted = await f.call('/api/seeds', seedForm(), '', auth);
  assert.equal(submitted.status, 201, await submitted.clone().text());
  f.published.set('little-library', f.manifests[0]);
  const updated = await f.call('/api/seeds/little-library', seedForm({ releaseUrl: '', pitch: 'Edited by an assistant' }), '', auth, 'PUT');
  assert.equal(updated.status, 201, await updated.clone().text());
  const mine = await f.call('/api/seeds/mine', undefined, '', { Authorization: auth.Authorization });
  assert.equal(mine.status, 200, await mine.clone().text());
  assert.equal((await mine.json()).seeds[0].id, 'little-library');
  const png = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const upload = await createApp({ fetcher: f.fetcher, proofRoutes, seedRoutes })(new Request(ORIGIN + '/api/media', {
    method: 'POST', headers: auth, body: png,
  }), f.env);
  assert.equal(upload.status, 201, await upload.clone().text());
  const listed = await (await f.call('/api/tokens', undefined, signed.cookie)).json();
  assert.ok(listed.tokens[0].lastUsedAt);
  assert.equal((await f.call('/api/tokens/' + issued.id, {}, signed.cookie, {}, 'DELETE')).status, 200);
  const refused = await f.call('/api/seeds', seedForm({ id: 'revoked-library' }), '', auth);
  assert.equal(refused.status, 401);
});
test('upload stores bytes at the required R2 key, serves download, and never trusts a supplied checksum', async () => {
  const f = fixture(), first = await f.email(); await f.proof(first.cookie);
  const response = await f.call('/api/seeds', seedForm({ upload: true, sha256: 'spoofed' }), first.cookie);
  assert.equal(response.status, 201, await response.clone().text());
  const key = 'seeds/little-library/0.1.0/little-library.tar.gz';
  assert.deepEqual(Buffer.from(f.objects.get(key).value), archive);
  assert.equal(f.manifests[0].release.sha256, await sha256(archive));
  const served = await worker.fetch(new Request(f.manifests[0].release.url), f.env);
  assert.equal(served.status, 200); assert.equal(served.headers.get('Content-Type'), 'application/gzip');
  assert.deepEqual(Buffer.from(await served.arrayBuffer()), archive);
  assert.equal((await worker.fetch(new Request(ORIGIN + '/'), f.env)).status, 200);
  assert.equal((await worker.fetch(new Request(ORIGIN + '/seeds-files/nope'), f.env)).status, 404);
});
test('the launcher feed and its downloads come from R2, typed, cached by name and refused in words', async () => {
  const f = fixture();
  const feed = JSON.stringify({ version: '0.1.0', pub_date: '2026-09-14T12:00:00Z', platforms: {
    'darwin-aarch64': { signature: 'fixture-signature', url: ORIGIN + '/launcher/Tiiny-App-Farm_0.1.0_universal.app.tar.gz' },
  } });
  // Before the first release the feed is simply absent, and a launcher asking for it is told so.
  const early = await worker.fetch(new Request(ORIGIN + '/launcher/latest.json'), f.env);
  assert.equal(early.status, 404);
  assert.equal((await early.json()).error, 'The launcher has not been published yet.');
  f.objects.set('launcher/latest.json', { value: feed, options: {} });
  f.objects.set('launcher/Tiiny-App-Farm_0.1.0_universal.dmg', { value: 'fixture disk image', options: {} });
  f.objects.set('launcher/Tiiny-App-Farm_0.1.0_x64-setup.exe', { value: 'fixture installer', options: {} });
  f.objects.set('launcher/Tiiny-App-Farm_0.1.0_universal.app.tar.gz', { value: 'fixture update archive', options: {} });
  f.objects.set('launcher/Tiiny-App-Farm_0.1.0_universal.app.tar.gz.sig', { value: 'fixture minisign line', options: {} });
  f.objects.set('launcher/notes.zip', { value: 'fixture notes', options: {} });
  const served = await worker.fetch(new Request(ORIGIN + '/launcher/latest.json'), f.env);
  assert.equal(served.status, 200);
  assert.equal(served.headers.get('Content-Type'), 'application/json; charset=utf-8');
  assert.equal(served.headers.get('Cache-Control'), 'no-store');
  assert.equal(served.headers.get('X-Content-Type-Options'), 'nosniff');
  assert.equal(served.headers.get('Content-Disposition'), null, 'the updater reads the feed, it does not save it');
  assert.equal((await served.json()).version, '0.1.0');
  const types = { 'Tiiny-App-Farm_0.1.0_universal.dmg': 'application/x-apple-diskimage',
    'Tiiny-App-Farm_0.1.0_x64-setup.exe': 'application/vnd.microsoft.portable-executable',
    'Tiiny-App-Farm_0.1.0_universal.app.tar.gz': 'application/gzip',
    'Tiiny-App-Farm_0.1.0_universal.app.tar.gz.sig': 'text/plain; charset=utf-8' };
  for (const [name, type] of Object.entries(types)) {
    const download = await worker.fetch(new Request(ORIGIN + '/launcher/' + name), f.env);
    assert.equal(download.status, 200, name);
    assert.equal(download.headers.get('Content-Type'), type, name);
    assert.equal(download.headers.get('Cache-Control'), 'public, max-age=31536000, immutable', name);
    assert.equal(download.headers.get('Content-Disposition'), `attachment; filename="${name}"`, name);
    assert.equal(download.headers.get('ETag'), '"fixture"', name);
    assert.equal(await download.text(), f.objects.get('launcher/' + name).value, name);
  }
  // A name with no version in it could hold different bytes tomorrow, so it is not cached for a year.
  const unversioned = await worker.fetch(new Request(ORIGIN + '/launcher/notes.zip'), f.env);
  assert.equal(unversioned.headers.get('Cache-Control'), 'public, max-age=300');
  assert.equal(unversioned.headers.get('Content-Type'), 'application/zip');
  const head = await worker.fetch(new Request(ORIGIN + '/launcher/Tiiny-App-Farm_0.1.0_universal.dmg', { method: 'HEAD' }), f.env);
  assert.equal(head.status, 200);
  assert.equal(head.headers.get('Content-Length'), String('fixture disk image'.length));
  assert.equal(await head.text(), '');
  // A file that is not there, a type the launcher never ships, and anything shaped like a key of
  // its own are all one sentence and a 404 rather than a stack trace or somebody else's object.
  for (const missing of ['Tiiny-App-Farm_9.9.9_universal.dmg', 'notes.txt', 'seeds/little-library/0.1.0/little-library.tar.gz', '.env', '', 'a..b.dmg']) {
    const refused = await worker.fetch(new Request(ORIGIN + '/launcher/' + missing), f.env);
    assert.equal(refused.status, 404, missing);
    assert.match((await refused.json()).error, /^(That launcher file does not exist\.|The launcher has not been published yet\.)$/, missing);
  }
  const posted = await worker.fetch(new Request(ORIGIN + '/launcher/latest.json', { method: 'POST' }), f.env);
  assert.equal(posted.status, 405);
  assert.equal((await posted.json()).error, 'Use GET or HEAD for launcher downloads.');
});
test('the release history is a feed from R2 and the version history is a page of the site', async () => {
  const f = fixture();
  const history = JSON.stringify({ releases: [{ version: '0.1.0', date: '2026-09-15', files: {} }] });
  // The page lives under /launcher/, where the Worker runs first, and is handed to the site.
  for (const where of ['/launcher/versions/', '/launcher/versions/index.html']) {
    const page = await worker.fetch(new Request(ORIGIN + where), f.env);
    assert.equal(page.status, 200, where);
    assert.equal(await page.text(), 'static farm', where);
  }
  const early = await worker.fetch(new Request(ORIGIN + '/launcher/releases.json'), f.env);
  assert.equal(early.status, 404);
  assert.equal((await early.json()).error, 'The launcher release history has not been published yet.');
  f.objects.set('launcher/releases.json', { value: history, options: {} });
  f.objects.set('launcher/Tiiny-App-Farm-0.1.0.AppImage', { value: 'fixture linux build', options: {} });
  const served = await worker.fetch(new Request(ORIGIN + '/launcher/releases.json'), f.env);
  assert.equal(served.status, 200);
  assert.equal(served.headers.get('Content-Type'), 'application/json; charset=utf-8');
  // A history read from a cache would hide the release the page was built to show.
  assert.equal(served.headers.get('Cache-Control'), 'no-store');
  assert.equal(served.headers.get('Content-Disposition'), null);
  assert.equal((await served.json()).releases[0].version, '0.1.0');
  const linux = await worker.fetch(new Request(ORIGIN + '/launcher/Tiiny-App-Farm-0.1.0.AppImage'), f.env);
  assert.equal(linux.status, 200);
  assert.equal(linux.headers.get('Content-Type'), 'application/octet-stream');
  assert.equal(linux.headers.get('Cache-Control'), 'public, max-age=31536000, immutable');
  assert.equal(linux.headers.get('Content-Disposition'), 'attachment; filename="Tiiny-App-Farm-0.1.0.AppImage"');
  assert.equal(await linux.text(), 'fixture linux build');
  // The page is the only thing under /launcher/ that is not a file, so nothing else falls through.
  const nested = await worker.fetch(new Request(ORIGIN + '/launcher/versions/0.1.0/'), f.env);
  assert.equal(nested.status, 404);
  assert.equal((await nested.json()).error, 'That launcher file does not exist.');
});
test('seed gate, archive selection, unsafe URL, invalid schema and size limits stop submission', async () => {
  const f = fixture(); assert.equal((await f.call('/api/seeds', seedForm())).status, 401);
  const first = await f.email(); assert.equal((await f.call('/api/seeds', seedForm(), first.cookie)).status, 403);
  await f.proof(first.cookie);
  assert.equal((await f.call('/api/seeds', seedForm({ upload: true, releaseUrl: 'https://example.org/a' }), first.cookie)).status, 400);
  for (const changes of [{ id: '../escape' }, { permissions: 'superuser' }, { ports: '70000' }, { version: '01.0.0' }, { releaseUrl: 'https://127.0.0.1/x' }]) {
    assert.equal((await f.call('/api/seeds', seedForm(changes), first.cookie)).status, 400);
  }
  const big = seedForm({ upload: true }); big.set('archive', new Blob([new Uint8Array(50 * 1024 * 1024 + 1)]), 'big.tar.gz');
  assert.ok([400, 413].includes((await f.call('/api/seeds', big, first.cookie)).status));
  assert.equal(f.manifests.length, 0);
});
test('status is private and includes CI checks and current review; repeated submission does not create a second PR', async () => {
  const f = fixture(), first = await f.email(); await f.proof(first.cookie);
  await f.call('/api/seeds', seedForm(), first.cookie);
  assert.equal((await f.call('/api/seeds', seedForm(), first.cookie)).status, 200);
  assert.equal(f.calls.filter(call => call.url.endsWith('/pulls') && call.method === 'POST').length, 1);
  assert.equal((await f.call('/api/seeds/mine')).status, 401);
  const other = await f.email('other@example.org');
  assert.deepEqual((await (await f.call('/api/seeds/mine', undefined, other.cookie)).json()).seeds, []);
  const { seeds } = await (await f.call('/api/seeds/mine', undefined, first.cookie)).json();
  assert.equal(seeds[0].state, 'awaiting review'); assert.equal(seeds[0].checks[0].status, 'success');
  assert.deepEqual(seeds[0].reviews, ['CHANGES_REQUESTED']);
});
test('label failure keeps submitted artifact and retry labels existing PR; uncertain PR response preserves resources', async () => {
  const f = fixture(), first = await f.email(); await f.proof(first.cookie); f.githubFail('/labels');
  assert.equal((await f.call('/api/seeds', seedForm({ upload: true }), first.cookie)).status, 202);
  assert.equal(f.objects.size, 1); f.githubFail('');
  assert.equal((await f.call('/api/seeds', seedForm({ upload: true }), first.cookie)).status, 200);
  assert.equal(f.calls.filter(call => call.url.endsWith('/pulls') && call.method === 'POST').length, 1);
  f.githubFail('/pulls');
  assert.equal((await f.call('/api/seeds', seedForm({ upload: true, id: 'second-library' }), first.cookie)).status, 202);
  assert.equal(f.objects.size, 2);
  assert.equal((await f.call('/api/seeds', seedForm({ upload: true, id: 'second-library' }), first.cookie)).status, 409);
});
test('coordinator consumes a code once under concurrent redemption and ignores stale KV owner data', async () => {
  const f = fixture(), address = 'race@example.org';
  await f.call('/api/auth/start', { email: address });
  const code = f.mails.at(-1).text.match(/\b\d{6}\b/)[0];
  const storage = new Store(), mirror = new Store(), waiting = [];
  for (const [key, raw] of f.store.values) {
    const value = JSON.parse(raw);
    if (key.startsWith('email-code:')) value.expires = Date.now() + 600000;
    await storage.put(key, value);
  }
  const coordinator = new FarmCoordinator({ storage, waitUntil: p => waiting.push(p) }, { ...f.env, FARM: mirror });
  const request = () => new Request(ORIGIN + '/api/auth/verify', { method: 'POST', headers: { Origin: ORIGIN, 'Content-Type': 'application/json' }, body: JSON.stringify({ email: address, code }) });
  const results = await Promise.all([coordinator.fetch(request()), coordinator.fetch(request())]);
  assert.deepEqual(results.map(result => result.status), [200, 400]);
  const id = PROFILE.split('/').pop();
  await mirror.put('tvowner:' + id, JSON.stringify('wrong-owner'));
  await storage.put('tvowner:' + id, 'actual-owner');
  await storage.put('user:actual-owner', { id: 'actual-owner', tiinyverse: { profileUrl: PROFILE, name: 'Durable owner' } });
  const owner = await coordinator.fetch(new Request(ORIGIN + '/api/owners?profile=' + PROFILE));
  assert.deepEqual(await owner.json(), { verified: true, name: 'Durable owner' });
  await Promise.all(waiting);
});
test('public owner reads remain responsive while an upload holds the mutation queue', async () => {
  const storage = new Store();
  const coordinator = new FarmCoordinator({ storage, waitUntil() {} }, { FARM: new Store() });
  coordinator.tail = new Promise(() => {});
  const response = await coordinator.fetch(new Request(ORIGIN + '/api/owners?profile=' + PROFILE));
  assert.equal(response.status, 200);
});
test('a stalled request body is cancelled at its deadline', async context => {
  context.mock.timers.enable({ apis: ['setTimeout'] });
  let cancelled = false;
  const response = new Response(new ReadableStream({ cancel() { cancelled = true; } }));
  const pending = boundedBody(response, 16384);
  context.mock.timers.tick(10000);
  await assert.rejects(pending, /too long/);
  assert.equal(cancelled, true);
});
test('bounded streaming response cancels as soon as its cap is exceeded', async () => {
  let cancelled = false;
  const response = new Response(new ReadableStream({ pull(controller) { controller.enqueue(new Uint8Array(10)); }, cancel() { cancelled = true; } }));
  await assert.rejects(boundedBody(response, 12), /too large/); assert.equal(cancelled, true);
});
test('release URLs reject credential-bearing and local origins', () => {
  for (const url of ['file:///etc/passwd', 'http://example.org/a', 'https://user:pass@example.org/a', 'https://127.1/a', 'https://[::1]/a', 'https://localhost/a', 'https://host.internal/a']) assert.throws(() => releaseURL(url));
});

test('maker defaults, proof-derived stable handle, private farm and escaped public page', async () => {
  const f = fixture(), first = await f.email();
  assert.equal(first.user.handle, null); assert.equal(first.user.bio, ''); assert.equal(first.user.avatarKey, null); assert.equal(first.user.public, true);
  assert.equal((await f.call('/account/')).headers.get('Location'), '/submit/');
  assert.equal((await f.call('/seeds/mine/')).headers.get('Location'), '/account/');
  assert.equal((await f.call('/makers/unknown/')).status, 404);
  await f.proof(first.cookie);
  const user = (await (await f.call('/api/me', undefined, first.cookie)).json()).user;
  assert.match(user.handle, /^aster-fern-[a-f0-9]{4}$/);
  assert.equal((await f.call('/account/', undefined, first.cookie)).headers.get('Cache-Control'), 'private, no-store');
  assert.equal((await f.call('/api/maker', { bio: '<script>bad</script>', links: { website: 'https://example.org/' }, handle: 'stolen' }, first.cookie)).status, 200);
  assert.equal((await f.call('/api/maker', { bio: 'x'.repeat(601), links: {} }, first.cookie)).status, 400);
  assert.equal((await f.call('/api/maker', { bio: '', links: { website: 'javascript:alert(1)' } }, first.cookie)).status, 400);
  f.env.ASSETS.fetch = async () => new Response(JSON.stringify([
    { id: 'merged-seed', name: 'A <seed>', pitch: 'In the field', author: { tiinyverse: PROFILE } },
    { id: 'other-seed', name: 'Other', author: { tiinyverse: 'other' } },
  ]));
  const page = await f.call('/makers/' + user.handle + '/'); assert.equal(page.status, 200);
  const html = await page.text(); assert.ok(html.includes('&lt;script&gt;')); assert.ok(!html.includes('<script>bad'));
  assert.ok(html.includes('/apps/merged-seed/')); assert.ok(!html.includes('other-seed'));
  assert.equal((await (await f.call('/api/me', undefined, first.cookie)).json()).user.handle, user.handle);
});

test('maker visibility saves immediately and private pages and cards require a signed-in session', async () => {
  const f = fixture(), owner = await f.email(), member = await f.email('member@example.org');
  await f.proof(owner.cookie);
  const user = (await (await f.call('/api/me', undefined, owner.cookie)).json()).user;
  assert.equal((await f.call('/api/maker/visibility', { public: false }, '', {}, 'PUT')).status, 401);
  assert.equal((await f.call('/api/maker/visibility', { public: 'false' }, owner.cookie, {}, 'PUT')).status, 400);
  const hidden = await f.call('/api/maker/visibility', { public: false }, owner.cookie, {}, 'PUT');
  assert.deepEqual(await hidden.json(), { public: false });
  assert.equal((await (await f.call('/api/me', undefined, owner.cookie)).json()).user.public, false);

  const requests = [], png = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);
  f.env.ASSETS.fetch = async request => {
    const path = new URL(request.url).pathname; requests.push(path);
    if (path === '/catalog.json') return Response.json([]);
    if (path === `/makers/${user.handle}/card.png`) return new Response(png, { headers: { 'Content-Type': 'image/png' } });
    return new Response('Not found', { status: 404 });
  };

  const anonymousPage = await f.call(`/makers/${user.handle}/`);
  assert.equal(anonymousPage.status, 200); assert.match(anonymousPage.headers.get('Content-Type'), /^text\/html/);
  const gate = await anonymousPage.text();
  assert.match(gate, /This maker's page is for signed-in members\./); assert.match(gate, /href="\/submit\/">Sign in<\/a>/);
  const anonymousCard = await f.call(`/makers/${user.handle}/card.png`);
  assert.equal(anonymousCard.status, 200); assert.match(anonymousCard.headers.get('Content-Type'), /^text\/html/);
  assert.match(await anonymousCard.text(), /This maker's page is for signed-in members\./);
  assert.deepEqual(requests, []);

  const memberPage = await f.call(`/makers/${user.handle}/`, undefined, member.cookie);
  assert.equal(memberPage.status, 200); assert.match(await memberPage.text(), /<h1>Aster &amp; Fern<\/h1>/);
  const memberCard = await f.call(`/makers/${user.handle}/card.png`, undefined, member.cookie);
  assert.equal(memberCard.status, 200); assert.equal(memberCard.headers.get('Content-Type'), 'image/png');
  assert.equal(memberCard.headers.get('Cache-Control'), 'private, no-store'); assert.equal(memberCard.headers.get('Vary'), 'Cookie');

  const shown = await f.call('/api/maker/visibility', { public: true }, owner.cookie, {}, 'PUT');
  assert.deepEqual(await shown.json(), { public: true });
  const publicPage = await f.call(`/makers/${user.handle}/`); assert.match(await publicPage.text(), /<h1>Aster &amp; Fern<\/h1>/);
  const publicCard = await f.call(`/makers/${user.handle}/card.png`);
  assert.equal(publicCard.headers.get('Content-Type'), 'image/png'); assert.equal(publicCard.headers.get('Cache-Control'), 'public, max-age=300');
});

test('media uses sniffed types, caps bodies, enforces owner deletion and origin, serves safely', async () => {
  const f = fixture(), first = await f.email(), second = await f.email('other@example.org');
  const current = createApp({ proofRoutes, seedRoutes, fetcher: f.fetcher, now: () => Date.parse('2026-09-12T12:00:00Z') });
  const send = (path, method, body, session = first.cookie, origin = ORIGIN) => current(new Request(ORIGIN + path, {
    method, body, headers: { Cookie: session, Origin: origin, 'Content-Type': 'image/png' },
  }), f.env);
  const png = Uint8Array.from([137,80,78,71,13,10,26,10,0]);
  assert.equal((await send('/api/media', 'POST', png)).status, 403);
  await f.proof(first.cookie);
  assert.equal((await send('/api/media', 'POST', '<svg></svg>')).status, 415);
  assert.equal((await send('/api/media', 'POST', new Uint8Array(2 * 1024 * 1024 + 1))).status, 413);
  const uploaded = await send('/api/media', 'POST', png); assert.equal(uploaded.status, 201);
  const { key, url } = await uploaded.json(); assert.ok(key.startsWith('media/' + first.user.id + '/'));
  const served = await worker.fetch(new Request(url), f.env);
  assert.equal(served.headers.get('Content-Type'), 'image/png'); assert.equal(served.headers.get('X-Content-Type-Options'), 'nosniff');
  assert.match(served.headers.get('Cache-Control'), /31536000/); assert.deepEqual(new Uint8Array(await served.arrayBuffer()), png);
  assert.equal((await f.call('/api/maker', { bio: '', links: {}, avatarKey: key }, first.cookie)).status, 200);
  assert.equal((await f.call('/api/maker', { bio: '', links: {}, avatarKey: key }, second.cookie)).status, 400);
  assert.equal((await send('/api/' + key, 'DELETE', undefined, second.cookie)).status, 403);
  assert.equal((await send('/api/' + key, 'DELETE', undefined, first.cookie, 'https://evil.example')).status, 403);
  assert.equal((await send('/api/' + key, 'DELETE')).status, 200);
  assert.equal((await worker.fetch(new Request(url), f.env)).status, 404);
  assert.equal((await (await f.call('/api/me', undefined, first.cookie)).json()).user.avatarKey, null);
});

test('seed media and links survive the bot PR; shared schema caps gallery and rejects unsafe/video URLs', async () => {
  const f = fixture(), first = await f.email(); await f.proof(first.cookie);
  const media = { icon: 'https://tiinyapp.farm/media/maker/face.png', header: 'https://example.org/header.webp', gallery: ['https://example.org/gallery.jpg'] };
  const response = await f.call('/api/seeds', seedForm({ media: JSON.stringify(media), video: 'https://youtu.be/abcdefghijk', repo: 'https://example.org/source', homepage: 'https://example.org/' }), first.cookie);
  assert.equal(response.status, 201); assert.deepEqual(f.manifests[0].media, media);
  assert.deepEqual(f.manifests[0].links, { repo: 'https://example.org/source', video: 'https://youtu.be/abcdefghijk', homepage: 'https://example.org/' });
  const base = f.manifests[0];
  const valid = structuredClone(base); delete valid.homepage; checkManifest(valid);
  const invalid = [
    { media: { gallery: Array.from({ length: 9 }, (_, i) => `https://example.org/${i}.png`) } },
    { media: { icon: 'http://example.org/image.png' } }, { media: { icon: 'javascript:alert(1)' } },
    { media: { icon: 'https://user:pass@example.org/x.png' } },
    { links: { video: 'https://youtube.com.evil.example/watch?v=abcdefghijk' } },
    { links: { video: 'https://youtube.com/watch?v=short' } },
    { links: { repo: 'http://example.org/source' } },
  ];
  for (const changes of invalid) {
    const manifest = { ...base, ...changes }; assert.throws(() => checkManifest(manifest));
    const python = spawnSync('python3', ['-c', 'import json,sys,runpy; runpy.run_path("scripts/check-manifest.py")["check_manifest"](json.load(sys.stdin))'], { input: JSON.stringify(manifest), encoding: 'utf8' });
    assert.notEqual(python.status, 0, JSON.stringify(changes));
  }
  const python = spawnSync('python3', ['-c', 'import json,sys,runpy; runpy.run_path("scripts/check-manifest.py")["check_manifest"](json.load(sys.stdin))'], { input: JSON.stringify(valid), encoding: 'utf8' });
  assert.equal(python.status, 0, python.stderr);
});

test('YouTube URLs allow shared watch query ordering and timestamp fragments', async () => {
  const f = fixture(), first = await f.email(); await f.proof(first.cookie);
  await f.call('/api/seeds', seedForm(), first.cookie);
  for (const video of ['https://www.youtube.com/watch?feature=shared&v=abcdefghijk', 'https://youtu.be/abcdefghijk#t=30s', 'https://youtube.com/watch?v=abcdefghijk&t=30s']) {
    const manifest = { ...f.manifests[0], links: { video } }; checkManifest(manifest);
    const python = spawnSync('python3', ['-c', 'import json,sys,runpy; runpy.run_path("scripts/check-manifest.py")["check_manifest"](json.load(sys.stdin))'], { input: JSON.stringify(manifest), encoding: 'utf8' });
    assert.equal(python.status, 0, python.stderr);
  }
  assert.throws(() => checkManifest({ ...f.manifests[0], links: { video: 'https://youtube.com/watch?v=wrong&v=abcdefghijk' } }));
});

function socialFixture(f) {
  f.env.ASSETS.fetch = async request => new URL(request.url).pathname === '/manifests/little-library.json'
    ? new Response(JSON.stringify({ id: 'little-library' })) : new Response('Not found', { status: 404 });
}
test('social: public counts, account thumb toggle, verified comments, limits and safe author projection', async () => {
  const f = fixture(); socialFixture(f);
  const endpoint = '/api/seeds/little-library';
  assert.deepEqual(await (await f.call(endpoint + '/social')).json(), { thumbs: 0, seeds: 0, mine: false, comments: [] });
  assert.equal((await f.call('/api/seeds/not-here/social')).status, 404);
  assert.equal((await f.call(endpoint + '/thumb', {})).status, 401);
  const first = await f.email();
  assert.equal((await f.call(endpoint + '/comments', { text: 'Hi' }, first.cookie)).status, 403);
  let social = await (await f.call(endpoint + '/thumb', {}, first.cookie)).json();
  assert.equal(social.thumbs, 1); assert.equal(social.seeds, 1); assert.equal(social.mine, true);
  social = await (await f.call(endpoint + '/thumb', {}, first.cookie)).json(); assert.equal(social.thumbs, 0); assert.equal(social.seeds, 0); assert.equal(social.mine, false);
  // /seed is the name a person reads and /thumb is the name the first release shipped with.
  social = await (await f.call(endpoint + '/seed', {}, first.cookie)).json();
  assert.equal(social.seeds, 1); assert.equal(social.thumbs, 1); assert.equal(social.mine, true);
  social = await (await f.call(endpoint + '/seed', {}, first.cookie)).json();
  assert.equal(social.seeds, 0); assert.equal(social.mine, false);
  assert.equal((await f.call(endpoint + '/seed', undefined, first.cookie, {}, 'GET')).status, 405);
  await f.proof(first.cookie);
  for (const text of ['', ' ', 'x'.repeat(1001), 123]) assert.equal((await f.call(endpoint + '/comments', { text }, first.cookie)).status, 400);
  const result = await f.call(endpoint + '/comments', { text: '<img src=x onerror=alert(1)>' }, first.cookie);
  assert.equal(result.status, 201);
  social = await result.json();
  assert.equal(social.comments[0].text, '<img src=x onerror=alert(1)>');
  assert.equal(social.comments[0].author.name, 'Aster & Fern');
  assert.match(social.comments[0].author.handle, /^aster-fern-[a-f0-9]{4}$/);
  assert.equal(social.comments[0].canDelete, true);
  assert.ok(!JSON.stringify(social).includes(first.user.email)); assert.ok(!JSON.stringify(social).includes(first.user.id));
  const publicView = await (await f.call(endpoint + '/social')).json();
  assert.equal(publicView.comments[0].canDelete, false);
  for (let i = 1; i < 5; i++) assert.equal((await f.call(endpoint + '/comments', { text: 'Another seed thought' }, first.cookie)).status, 201);
  assert.equal((await f.call(endpoint + '/comments', { text: 'Too soon' }, first.cookie)).status, 429);
  f.advance(3600001);
  assert.equal((await f.call(endpoint + '/comments', { text: 'A fresh hour' }, first.cookie)).status, 201);
});

test('social deletion: author and listed admin only; deleted comments still count against rate limit', async () => {
  const f = fixture(); socialFixture(f);
  const first = await f.email(), other = await f.email('other@example.org'); await f.proof(first.cookie);
  const endpoint = '/api/seeds/little-library';
  let comment;
  for (let i = 0; i < 5; i++) {
    const response = await f.call(endpoint + '/comments', { text: 'A thought' }, first.cookie);
    comment = (await response.json()).comments.at(-1);
  }
  const app = createApp({ now: () => Date.parse('2026-09-12T12:00:00Z') });
  const remove = (id, session, origin = ORIGIN) => app(new Request(ORIGIN + endpoint + '/comments/' + id, {
    method: 'DELETE', headers: { Cookie: session, Origin: origin },
  }), f.env);
  assert.equal((await remove(comment.id, other.cookie)).status, 403);
  assert.equal((await remove(comment.id, first.cookie, 'https://evil.example')).status, 403);
  assert.equal((await remove(comment.id, first.cookie)).status, 200);
  assert.equal((await f.call(endpoint + '/comments', { text: 'Deletion does not reset the rate' }, first.cookie)).status, 429);
  const remaining = (await (await f.call(endpoint + '/social')).json()).comments[0];
  f.env.FARM_ADMINS = ' someone-else, ' + other.user.id + ' ';
  assert.equal((await (await f.call(endpoint + '/social', undefined, other.cookie)).json()).comments[0].canDelete, true);
  assert.equal((await remove(remaining.id, other.cookie)).status, 200);
  assert.equal((await remove(remaining.id, other.cookie)).status, 404);
});

test('coordinator serializes concurrent thumbs/comments and mirrors social records', async () => {
  const f = fixture(); socialFixture(f);
  const first = await f.email(), second = await f.email('other@example.org'); await f.proof(first.cookie);
  const storage = new Store(), mirror = new Store(), pending = [];
  for (const [key, value] of f.store.values) {
    const record = JSON.parse(value); if (key.startsWith('session:')) record.expires = Date.now() + 600000;
    await storage.put(key, record);
  }
  const coordinator = new FarmCoordinator({ storage, waitUntil: promise => pending.push(promise) }, { ...f.env, FARM: mirror });
  const endpoint = ORIGIN + '/api/seeds/little-library';
  const post = (path, cookie, data = {}) => coordinator.fetch(new Request(endpoint + path, {
    method: 'POST', headers: { Origin: ORIGIN, Cookie: cookie, 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }));
  const responses = await Promise.all([post('/thumb', first.cookie), post('/thumb', second.cookie)]);
  assert.deepEqual(responses.map(r => r.status), [200, 200]);
  assert.deepEqual((await storage.get('social:little-library')).thumbs.sort(), [first.user.id, second.user.id].sort());
  await Promise.all([post('/thumb', first.cookie), post('/thumb', first.cookie)]);
  assert.equal((await storage.get('social:little-library')).thumbs.length, 2);
  const comments = await Promise.all(Array.from({ length: 6 }, (_, i) => post('/comments', first.cookie, { text: 'Thought ' + i })));
  assert.deepEqual(comments.map(r => r.status), [201, 201, 201, 201, 201, 429]);
  await Promise.all(pending);
  const durable = await storage.get('social:little-library');
  assert.equal(durable.comments.length, 5); assert.equal(new Set(durable.comments.map(c => c.id)).size, 5);
  assert.deepEqual(await mirror.get('social:little-library', 'json'), durable);
});

test('seed counts: one public read carries every app and every maker in the catalog', async () => {
  const f = fixture();
  const owner = await f.email(); await f.proof(owner.cookie);
  const visitor = await f.email('other@example.org');
  const handle = (await (await f.call('/api/me', undefined, owner.cookie)).json()).user.handle;
  assert.match(handle, /^aster-fern-[a-f0-9]{4}$/);
  f.published.set('fake-app', listedApp());
  f.published.set('little-library', listedApp({ id: 'little-library', name: 'Little Library' }));
  // Neither app has an owner record, the way every app listed before the farm recorded owners
  // is. Both are credited through the verified profile on the manifest instead.
  assert.equal(await f.store.get('seedowner:fake-app'), null);
  const endpoint = '/api/seeds/fake-app';
  assert.equal((await f.call(endpoint + '/seed', {}, owner.cookie)).status, 200);
  assert.equal((await f.call(endpoint + '/seed', {}, visitor.cookie)).status, 200);
  assert.equal((await f.call(endpoint + '/comments', { text: 'Growing well' }, owner.cookie)).status, 201);
  assert.equal((await f.call('/api/seeds/little-library/seed', {}, owner.cookie)).status, 200);
  const response = await f.call('/api/social/counts');
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Cache-Control'), 'public, max-age=60');
  const counts = await response.json();
  assert.deepEqual(counts.apps, { 'fake-app': { seeds: 2, comments: 1 },
    'little-library': { seeds: 1, comments: 0 } });
  assert.deepEqual(counts.makers, { [handle]: { seeds: 3 } });
  // Nothing about a person travels with a public count.
  const text = JSON.stringify(counts);
  assert.ok(!text.includes(owner.user.id) && !text.includes(visitor.user.id));
  assert.ok(!text.includes('example.org'));
  assert.equal((await f.call('/api/social/counts', {})).status, 405);
  // An app whose author profile was never verified is credited through its owner record.
  f.published.set('orphan-app', listedApp({ id: 'orphan-app', name: 'Orphan',
    author: { name: 'Nobody', url: 'https://example.org/nobody', tiinyverse: 'https://example.org/nobody' } }));
  await f.store.put('seedowner:orphan-app', JSON.stringify(owner.user.id));
  assert.equal((await f.call('/api/seeds/orphan-app/seed', {}, owner.cookie)).status, 200);
  assert.deepEqual((await (await f.call('/api/social/counts')).json()).makers, { [handle]: { seeds: 4 } });
  // A maker who hid their page is not listed, the way their page is not served.
  assert.equal((await f.call('/api/maker/visibility', { public: false }, owner.cookie, {}, 'PUT')).status, 200);
  assert.deepEqual((await (await f.call('/api/social/counts')).json()).makers, {});
});

test('a farm_ token gives a seed and leaves a comment without an Origin, the way the launcher will', async () => {
  const f = fixture(); socialFixture(f);
  const signed = await f.email(); await f.proof(signed.cookie);
  const issued = await (await f.call('/api/tokens', { name: 'Launcher' }, signed.cookie)).json();
  const auth = { Authorization: `Bearer ${issued.token}`, Origin: 'https://launcher.example' };
  const endpoint = '/api/seeds/little-library';
  let social = await (await f.call(endpoint + '/seed', {}, '', auth)).json();
  assert.equal(social.seeds, 1); assert.equal(social.mine, true);
  social = await (await f.call(endpoint + '/thumb', {}, '', auth)).json();
  assert.equal(social.seeds, 0); assert.equal(social.mine, false);
  social = await (await f.call(endpoint + '/comments', { text: 'From the launcher' }, '', auth)).json();
  assert.equal(social.comments[0].text, 'From the launcher');
  // A token with no verified Tiiny behind it is refused a comment exactly as a cookie is.
  const plain = await f.email('plain@example.org');
  assert.equal((await f.call('/api/tokens', { name: 'No Tiiny' }, plain.cookie)).status, 403);
  // Reading is still open to anyone, and a wrong token is nobody rather than the cookie holder.
  const wrong = { Authorization: 'Bearer farm_' + 'f'.repeat(40), Origin: 'https://launcher.example' };
  assert.equal((await f.call(endpoint + '/seed', {}, signed.cookie, wrong)).status, 401);
  assert.equal((await f.call(endpoint + '/comments', { text: 'Nope' }, signed.cookie, wrong)).status, 401);
  assert.equal((await f.call(endpoint + '/social')).status, 200);
  // A revoked token stops working.
  assert.equal((await f.call('/api/tokens/' + issued.id, {}, signed.cookie, {}, 'DELETE')).status, 200);
  assert.equal((await f.call(endpoint + '/seed', {}, '', auth)).status, 401);
});

test('the seed stack grows in the shape the three renderers agree on', async () => {
  const browser = await import('../site/assets/seed-stack.js');
  const shapes = { 0: [[0]], 1: [[1]], 3: [[1, 1, 1]], 4: [[1, 1], [1, 1]],
    9: [[1, 1, 1, 1], [1, 1, 1, 1, 1]], 10: [[1], [1, 1], [1, 1, 1]], 57: [[1], [1, 1], [1, 1, 1]] };
  for (const [count, rows] of Object.entries(shapes)) {
    assert.deepEqual(seedRows(Number(count)), rows, 'worker rows for ' + count);
    assert.deepEqual(browser.seedRows(Number(count)), rows, 'browser rows for ' + count);
    const words = Number(count) === 0 ? 'No seeds yet' : 'Seeds · ' + count;
    assert.equal(seedWords(Number(count)), words);
    assert.equal(browser.seedWords(Number(count)), words);
    const html = seedStackHTML(Number(count));
    assert.equal((html.match(/class="seed-row"/g) || []).length, rows.length);
    assert.equal((html.match(/<i class="seed"><\/i>/g) || []).length, rows.flat().filter(Boolean).length);
    assert.ok(html.includes('data-seeds="' + count + '"'));
    assert.ok(html.includes('aria-label="' + words + '"'));
  }
  assert.ok(seedStackHTML(0).includes('<i class="seed seed-husk"></i>'));
  assert.ok(!seedStackHTML(1).includes('husk'));
  // Nothing hostile can reach the markup: the count is a whole number or it is zero.
  assert.equal(seedStackHTML('3"><script>'), seedStackHTML(0));
  assert.ok(!seedStackHTML('3"><script>').includes('<script>'));
  assert.equal(seedStackHTML('7'), seedStackHTML(7));
  assert.equal(seedStackHTML(4.8), seedStackHTML(4));
  assert.ok(seedStackHTML(-4).includes('No seeds yet'));
  assert.ok(seedStackHTML(2, ' data-seed-stack="little-library"').includes('data-seed-stack="little-library"'));
});

test('private seed cards include live social counts and only published page links', async () => {
  const f = fixture(), first = await f.email(); await f.proof(first.cookie);
  await f.call('/api/seeds', seedForm(), first.cookie);
  let seeds = (await (await f.call('/api/seeds/mine', undefined, first.cookie)).json()).seeds;
  assert.equal(seeds[0].url, undefined);
  socialFixture(f);
  await f.call('/api/seeds/little-library/thumb', {}, first.cookie);
  await f.call('/api/seeds/little-library/comments', { text: 'Growing well' }, first.cookie);
  seeds = (await (await f.call('/api/seeds/mine', undefined, first.cookie)).json()).seeds;
  assert.equal(seeds[0].url, '/apps/little-library/'); assert.equal(seeds[0].seeds, 1); assert.equal(seeds[0].thumbs, 1); assert.equal(seeds[0].comments, 1);
});

test('maker pages carry sprout identity, escaped share metadata and accessible share controls', async () => {
  const f = fixture(), first = await f.email(); await f.proof(first.cookie);
  const user = (await (await f.call('/api/me', undefined, first.cookie)).json()).user;
  const bio = 'A "tiny" garden <with> friends & seeds';
  await f.call('/api/maker', { bio, links: {} }, first.cookie);
  f.env.ASSETS.fetch = async () => new Response('[]', { headers: { 'Content-Type': 'application/json' } });
  const html = await (await f.call(`/makers/${user.handle}/`)).text();
  for (const file of ['favicon.ico', 'favicon-32.png', 'favicon-192.png', 'apple-touch-icon.png']) assert.ok(html.includes(`/brand/${file}`));
  assert.match(html, /rel="manifest" href="\/site.webmanifest"/);
  assert.match(html, /name="theme-color" content="#090D14"/);
  assert.match(html, /class="brand-mark" src="\/brand\/icon-512.png" width="36" height="36"/);
  assert.match(html, /property="og:title" content="Apps by Aster &amp; Fern \| tiinyapp.farm"/);
  assert.ok(html.includes(`property="og:url" content="${ORIGIN}/makers/${user.handle}/"`));
  assert.ok(html.includes(`property="og:image" content="${ORIGIN}/makers/${user.handle}/card.png"`));
  assert.match(html, /property="og:image:width" content="1200"/);
  assert.match(html, /property="og:image:height" content="630"/);
  assert.match(html, /name="twitter:card" content="summary_large_image"/);
  assert.match(html, /property="og:description" content="A &quot;tiny&quot; garden &lt;with&gt; friends &amp; seeds"/);
  assert.match(html, /data-share-text="A &quot;tiny&quot; garden &lt;with&gt; friends &amp; seeds"/);
  assert.match(html, /<h1>Aster &amp; Fern<\/h1>/);
  assert.match(html, /<h2>Apps by Aster &amp; Fern<\/h2>/);
  assert.match(html, /href="\/install\/">Install<\/a>/);
  assert.match(html, /href="\/submit\/">Submit an app<\/a>/);
  assert.match(html, /data-farm-nav href="\/submit\/#account-panel">Sign in<\/a>/);
  assert.match(html, /No apps in the catalog yet\./);
  assert.doesNotMatch(html, /Bring your seeds|Seeds in the field/);
  assert.match(html, /src="\/assets\/share.js"/);
  assert.match(html, /<button[^>]*type="button"[^>]*data-share /);
  assert.match(html, /data-share-status role="status" aria-live="polite"/);
});

test("a maker's page carries the seeds their apps have been given, added up", async () => {
  const f = fixture(), maker = await f.email(); await f.proof(maker.cookie);
  const visitor = await f.email('other@example.org');
  const user = (await (await f.call('/api/me', undefined, maker.cookie)).json()).user;
  f.published.set('fake-app', listedApp());
  f.published.set('little-library', listedApp({ id: 'little-library', name: 'Little Library' }));
  const empty = await (await f.call(`/makers/${user.handle}/`)).text();
  assert.ok(empty.includes('data-seeds="0"') && empty.includes('No seeds yet'));
  for (const [app, who] of [['fake-app', maker], ['fake-app', visitor], ['little-library', visitor]]) {
    assert.equal((await f.call(`/api/seeds/${app}/seed`, {}, who.cookie)).status, 200);
  }
  const html = await (await f.call(`/makers/${user.handle}/`)).text();
  assert.match(html, /<div class="maker-head"><h1>Aster &amp; Fern<\/h1><span class="seed-stack" data-seeds="3"/);
  assert.ok(html.includes('Seeds · 3'));
  // The pile is the whole field, not one plot.
  assert.equal((await (await f.call('/api/seeds/fake-app/social')).json()).seeds, 2);
});

test('maker share cards serve build snapshots, handle HEAD and fall back for missing snapshots', async () => {
  const f = fixture(), requests = [];
  const png = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);
  f.env.ASSETS.fetch = async request => {
    const path = new URL(request.url).pathname; requests.push(path);
    if (path === '/makers/known-grower/card.png' || path === '/brand/og-image.png') {
      return new Response(png, { headers: { 'Content-Type': 'image/png', ETag: '"build-card"' } });
    }
    // Some asset configurations return their HTML fallback with status 200.
    return new Response('<html>Not a card</html>', { headers: { 'Content-Type': 'text/html' } });
  };
  const card = await f.call('/makers/known-grower/card.png');
  assert.equal(card.status, 200); assert.equal(card.headers.get('Content-Type'), 'image/png');
  assert.equal(card.headers.get('Cache-Control'), 'public, max-age=300');
  assert.equal(card.headers.get('X-Content-Type-Options'), 'nosniff');
  assert.equal(card.headers.get('ETag'), '"build-card"');
  assert.deepEqual(new Uint8Array(await card.arrayBuffer()), png);
  assert.deepEqual(requests, ['/makers/known-grower/card.png']);
  const fallback = await f.call('/makers/new-grower/card.png');
  assert.equal(fallback.status, 200); assert.deepEqual(new Uint8Array(await fallback.arrayBuffer()), png);
  assert.deepEqual(requests.slice(-2), ['/makers/new-grower/card.png', '/brand/og-image.png']);
  const head = await createApp()(new Request(ORIGIN + '/makers/known-grower/card.png', { method: 'HEAD' }), f.env);
  assert.equal(head.status, 200); assert.equal(await head.text(), '');
  assert.equal(head.headers.get('Content-Type'), 'image/png');
  assert.equal((await f.call('/makers/known-grower/card.png', {})).status, 405);
  assert.equal((await f.call('/makers/INVALID/card.png')).status, 404);
  f.env.ASSETS.fetch = async () => new Response('Not found', { status: 404 });
  assert.equal((await f.call('/makers/new-grower/card.png')).status, 404);
});

test('a release URL may redirect (GitHub releases do); loops are refused', async () => {
  const f = fixture(), first = await f.email(); await f.proof(first.cookie);
  const ok = await f.call('/api/seeds', seedForm({ id: 'redirected-seed', releaseUrl: 'https://github.example.org/releases/download/v1/seed.tar.gz' }), first.cookie);
  assert.equal(ok.status, 201, await ok.clone().text());
  const loop = await f.call('/api/seeds', seedForm({ id: 'looping-seed', releaseUrl: 'https://loop.example.org/a' }), first.cookie);
  assert.equal(loop.status, 422);
});


test('sprouting submission creates a schema-valid manifest without release or archive requests', async () => {
  const f = fixture(), signed = await f.email(); await f.proof(signed.cookie);
  const response = await f.call('/api/seeds', seedForm({ releaseUrl: '' }), signed.cookie);
  assert.equal(response.status, 201, await response.clone().text());
  const manifest = f.manifests[0];
  assert.equal(Object.hasOwn(manifest, 'release'), false); checkManifest(manifest);
  assert.equal(f.objects.size, 0);
  assert.ok(!f.calls.some(call => call.url.includes('releases.example.org')));
  const python = spawnSync('python3', ['-c', 'import json,sys,runpy; runpy.run_path("scripts/check-manifest.py")["check_manifest"](json.load(sys.stdin))'], { input: JSON.stringify(manifest), encoding: 'utf8' });
  assert.equal(python.status, 0, python.stderr);
});

test('owner text updates replace the manifest, preserve release and date, retry once, and allow subsequent edits', async () => {
  const f = fixture(), signed = await f.email(); await f.proof(signed.cookie);
  await f.call('/api/seeds', seedForm(), signed.cookie);
  const current = f.manifests[0]; current.addedAt = '2026-08-01'; f.published.set(current.id, current);
  const form = () => seedForm({ releaseUrl: '', pitch: 'A greener plot' });
  const response = await f.call('/api/seeds/little-library', form(), signed.cookie, {}, 'PUT');
  assert.equal(response.status, 201, await response.clone().text());
  const updated = f.manifests[1];
  assert.deepEqual(updated.release, current.release); assert.equal(updated.version, current.version);
  assert.equal(updated.pitch, 'A greener plot'); assert.equal(updated.addedAt, '2026-08-01');
  const write = f.calls.filter(call => call.method === 'PUT' && call.url.includes('/contents/')).at(-1);
  assert.equal(JSON.parse(write.body).sha, 'c'.repeat(40));
  assert.equal((await f.call('/api/seeds/little-library', form(), signed.cookie, {}, 'PUT')).status, 200);
  assert.equal(f.manifests.length, 2);
  assert.equal((await f.call('/api/seeds/little-library', seedForm({ releaseUrl: '', pitch: 'Another edit' }), signed.cookie, {}, 'PUT')).status, 201);
  const mine = await (await f.call('/api/seeds/mine', undefined, signed.cookie)).json();
  assert.ok(mine.seeds.every(seed => seed.canUpdate));
});

test('updates enforce owner, path identity, verification, CSRF and release version ordering', async () => {
  const f = fixture(), signed = await f.email(); await f.proof(signed.cookie);
  await f.call('/api/seeds', seedForm({ releaseUrl: '' }), signed.cookie);
  f.published.set('little-library', f.manifests[0]);
  const put = (form, cookie = signed.cookie, headers = {}) => f.call('/api/seeds/little-library', form, cookie, headers, 'PUT');
  assert.equal((await put(seedForm(), '')).status, 401);
  assert.equal((await put(seedForm(), signed.cookie, { Origin: 'https://evil.example' })).status, 403);
  const other = await f.email('other@example.org');
  assert.equal((await put(seedForm(), other.cookie)).status, 403);
  const otherUser = JSON.parse(f.store.values.get('user:' + other.user.id));
  otherUser.tiinyverse = { name: 'Other', profileUrl: PROFILE.replace('39628b1e', '49628b1e') };
  await f.store.put('user:' + other.user.id, JSON.stringify(otherUser));
  assert.equal((await put(seedForm(), other.cookie)).status, 403);
  assert.equal((await put(seedForm({ id: 'different-id' }))).status, 400);
  for (const version of ['0.1.0', '0.0.9']) assert.equal((await put(seedForm({ version }))).status, 400);
  assert.equal((await put(seedForm({ version: '0.0.9', releaseUrl: '' }))).status, 400);
  assert.equal((await put(seedForm({ version: '0.10.0' }))).status, 201);
  assert.ok(f.manifests.at(-1).release);
});

test('hand-added seed owners appear in mine and may update by verified profile; stored owner wins', async () => {
  const f = fixture(), signed = await f.email(); await f.proof(signed.cookie);
  await f.call('/api/seeds', seedForm({ releaseUrl: '' }), signed.cookie);
  const legacy = { ...f.manifests[0], id: 'onelane' }; f.published.set('onelane', legacy);
  const mine = await (await f.call('/api/seeds/mine', undefined, signed.cookie)).json();
  assert.ok(mine.seeds.some(seed => seed.id === 'onelane' && seed.canUpdate && seed.state === 'sprouting'));
  const form = () => seedForm({ id: 'onelane', releaseUrl: '', entry: JSON.stringify({ python: 'onelane', args: ['--serve'] }), screenshots: JSON.stringify(['https://example.org/screen.png']) });
  assert.equal((await f.call('/api/seeds/onelane', form(), signed.cookie, {}, 'PUT')).status, 201);
  assert.deepEqual(f.manifests.at(-1).entry, { python: 'onelane', args: ['--serve'] });
  assert.deepEqual(f.manifests.at(-1).screenshots, ['https://example.org/screen.png']);
  await f.store.put('seedowner:onelane', JSON.stringify('another-user'));
  assert.equal((await f.call('/api/seeds/onelane', form(), signed.cookie, {}, 'PUT')).status, 403);
  f.published.set('unclaimed', { ...legacy, id: 'unclaimed' });
  assert.equal((await f.call('/api/seeds/unclaimed', seedForm({ id: 'unclaimed', releaseUrl: '' }), signed.cookie, {}, 'PUT')).status, 403);
});


test('pending upload updates keep distinct immutable archives and include bytes in retry identity', async () => {
  const f = fixture(), signed = await f.email(); await f.proof(signed.cookie);
  await f.call('/api/seeds', seedForm({ releaseUrl: '' }), signed.cookie);
  f.published.set('little-library', f.manifests[0]);
  const form = () => seedForm({ upload: true, version: '0.2.0' });
  const put = body => f.call('/api/seeds/little-library', body, signed.cookie, {}, 'PUT');
  assert.equal((await put(form())).status, 201);
  const first = f.manifests.at(-1).release;
  assert.equal((await put(form())).status, 200);
  const different = form(), otherBytes = gzipSync(Buffer.from('different source'));
  different.set('archive', new Blob([otherBytes]), 'little-library.tar.gz');
  assert.equal((await put(different)).status, 201);
  const second = f.manifests.at(-1).release;
  assert.notEqual(first.url, second.url);
  assert.equal(f.objects.size, 2);
  assert.deepEqual(Buffer.from(await (await worker.fetch(new Request(first.url), f.env)).arrayBuffer()), archive);
  assert.deepEqual(Buffer.from(await (await worker.fetch(new Request(second.url), f.env)).arrayBuffer()), otherBytes);
  f.githubFail('/git/ref/');
  // A failed new update cannot remove either earlier PR's source archive.
  assert.equal((await put(seedForm({ upload: true, version: '0.2.0', pitch: 'Another review' }))).status, 502);
  assert.equal(f.objects.size, 2);
});


test('app review status uses literal labels and preserves pending update status', async () => {
  const source = await readFile(new URL('../site/assets/farm.js', import.meta.url), 'utf8');
  const context = { document: { getElementById: () => ({ addEventListener() {} }) }, refreshSession: () => new Promise(() => {}) };
  runInNewContext(source.replace(/^import .*;$/gm, ''), context);
  const { appStatus } = context;
  for (const state of ['merged', 'published', 'sprouting']) assert.equal(appStatus({ state }), 'Published');
  assert.equal(appStatus({ state: 'awaiting review', checks: [] }), 'Checks running');
  assert.equal(appStatus({ state: 'awaiting review', checks: [{ name: 'CI', status: 'queued' }] }), 'Checks running');
  assert.equal(appStatus({ state: 'awaiting review', checks: [{ name: 'CI', status: 'success' }] }), 'Waiting for review');
  assert.equal(appStatus({ state: 'awaiting review', checks: [{ name: 'CI', status: 'timed_out' }] }), 'Checks failed: CI (timed out)');
  assert.equal(appStatus({ state: 'awaiting review', url: '/apps/existing/', checks: [{ name: 'CI', status: 'failure' }] }), 'Checks failed: CI (failure)');
  assert.equal(appStatus({ state: 'awaiting review', unavailable: true }), 'Check status unavailable');
  assert.equal(appStatus({ state: 'closed' }), 'Closed');
});


test('legacy pages permanently redirect and account stays private', async () => {
  const f = fixture();
  f.env.FARM_COORDINATOR = { idFromName: name => name, get: () => ({ fetch: request => createApp({ proofRoutes, seedRoutes, fetcher: f.fetcher })(request, f.env) }) };
  for (const [legacy, target] of Object.entries({ plant: '/install/', seeds: '/submit/', farm: '/account/', 'seeds/mine': '/account/' })) {
    for (const suffix of ['', '/', '/index.html']) {
      const response = await worker.fetch(new Request(ORIGIN + '/' + legacy + suffix), f.env);
      assert.equal(response.status, 301);
      assert.equal(response.headers.get('Location'), target);
    }
  }
  const anonymous = await worker.fetch(new Request(ORIGIN + '/account/'), f.env);
  assert.equal(anonymous.status, 302);
  assert.equal(anonymous.headers.get('Location'), '/submit/');
});


const artFixture = JSON.parse(await readFile(new URL('./art-prompts.json', import.meta.url), 'utf8'));
const MEDIA = /^https:\/\/tiinyapp\.farm\/media\/[0-9a-f-]+\/little-library\/[a-f0-9]{32}\.(png|webp)$/;

async function maker(f, address = 'grower@example.org') {
  const signed = await f.email(address);
  await f.proof(signed.cookie);
  return signed.cookie;
}
const drawArt = (f, cookie, scene = 'a corkboard of pinned cards joined by threads of light', id = 'little-library') =>
  f.call('/api/seeds/' + id + '/art', { scene }, cookie);

test('the Worker builds the same two prompts as farm/art.py, from the same fixture', () => {
  for (const item of artFixture.cases) {
    assert.equal(cleanScene(item.scene), item.clean);
    assert.equal(headerPrompt(item.scene), item.header);
    assert.equal(iconPrompt(item.scene), item.icon);
  }
  for (const refused of artFixture.refused) assert.throws(() => cleanScene(refused), error => error.status === 400);
  assert.equal(DAILY, 3);
});

test('app art: one pair, the sizes and formats the shelf uses, filed under the app and served back', async () => {
  const f = fixture(), cookie = await maker(f);
  const response = await drawArt(f, cookie);
  assert.equal(response.status, 201, await response.clone().text());
  const drawn = await response.json();
  assert.match(drawn.header, MEDIA);
  assert.match(drawn.icon, MEDIA);
  assert.equal(drawn.scene, 'a corkboard of pinned cards joined by threads of light.');
  assert.equal(drawn.remaining, 2);
  const [header, icon] = f.draws;
  assert.equal(header.model, 'gpt-image-2');
  assert.equal(header.size, '1536x1024');
  assert.equal(header.quality, 'high');
  assert.equal(header.output_format, 'webp');
  assert.equal(header.n, 1);
  assert.equal(header.prompt, headerPrompt('a corkboard of pinned cards joined by threads of light'));
  assert.equal(icon.size, '1024x1024');
  assert.equal(icon.output_format, 'png');
  assert.equal(icon.background, 'transparent');
  assert.equal(icon.prompt, iconPrompt('a corkboard of pinned cards joined by threads of light'));
  assert.equal(f.objects.size, 2);
  for (const [key, object] of f.objects) {
    assert.match(key, /^media\/[0-9a-f-]+\/little-library\/[a-f0-9]{32}\.(png|webp)$/);
    assert.equal(object.options.httpMetadata.contentType, key.endsWith('.png') ? 'image/png' : 'image/webp');
  }
  // The stored pair is reachable through the same image route as an uploaded image.
  const served = await worker.fetch(new Request(drawn.icon), f.env);
  assert.equal(served.status, 200);
  assert.equal(served.headers.get('Content-Type'), 'image/png');
  // The key is never repeated to the maker, in any answer.
  assert.ok(!JSON.stringify(drawn).includes('drawing-only-secret'));
});

test('app art: reading back the pair, its scene and what is left of the daily allowance', async () => {
  const f = fixture(), cookie = await maker(f);
  const empty = await (await f.call('/api/seeds/little-library/art', undefined, cookie)).json();
  assert.deepEqual(empty, { scene: '', remaining: 3 });
  const drawn = await (await drawArt(f, cookie, 'sprouts queuing at a lantern-lit gate')).json();
  const stored = await (await f.call('/api/seeds/little-library/art', undefined, cookie)).json();
  assert.equal(stored.scene, 'sprouts queuing at a lantern-lit gate.');
  assert.equal(stored.header, drawn.header);
  assert.equal(stored.icon, drawn.icon);
  assert.equal(stored.remaining, 2);
});

test('app art: maker only, verified only, and never another maker s app', async () => {
  const f = fixture();
  assert.equal((await drawArt(f, '')).status, 401);
  const signed = await f.email('unverified@example.org');
  assert.equal((await drawArt(f, signed.cookie)).status, 403);
  const owner = await maker(f, 'owner@example.org');
  assert.equal((await f.call('/api/seeds', seedForm(), owner)).status, 201);
  f.githubId(77);
  const stranger = await f.email('stranger@example.org');
  f.html('<h1>Other maker</h1>');
  const link = await (await f.call('/api/tiinyverse/link', { profileUrl: 'https://www.tiinyverse.com/users/8c1f2d3e-4a5b-6c7d-8e9f-0a1b2c3d4e5f' }, stranger.cookie)).json();
  f.html(`<h1>Other maker</h1><p>${link.code}</p>`);
  assert.equal((await f.call('/api/tiinyverse/verify', {}, stranger.cookie)).status, 200);
  const refused = await drawArt(f, stranger.cookie);
  assert.equal(refused.status, 403);
  assert.match((await refused.json()).error, /verified maker/);
  assert.equal(f.draws.length, 0);
  // A method the route does not answer says so instead of drawing.
  assert.equal((await f.call('/api/seeds/little-library/art', {}, owner, {}, 'DELETE')).status, 405);
});

test('app art: three a day for one app, one at a time, and a failed drawing costs nothing', async () => {
  const f = fixture(), cookie = await maker(f);
  for (let i = 0; i < 3; i++) assert.equal((await drawArt(f, cookie)).status, 201);
  const fourth = await drawArt(f, cookie);
  assert.equal(fourth.status, 429);
  assert.match((await fourth.json()).error, /3 times a day/);
  assert.equal(f.draws.length, 6);
  f.advance(86400001);
  assert.equal((await drawArt(f, cookie)).status, 201);
  // A drawing already running for this app refuses the second press rather than spending a try.
  await f.store.put('art-inflight:little-library', JSON.stringify(f.now()));
  const doubled = await drawArt(f, cookie);
  assert.equal(doubled.status, 409);
  assert.equal((await (await f.call('/api/seeds/little-library/art', undefined, cookie)).json()).remaining, 2);
  await f.store.delete('art-inflight:little-library');
  f.drawing(500);
  assert.equal((await drawArt(f, cookie)).status, 502);
  // The failure did not take the maker's second try.
  assert.equal((await (await f.call('/api/seeds/little-library/art', undefined, cookie)).json()).remaining, 2);
  f.drawing(200);
  assert.equal((await drawArt(f, cookie)).status, 201);
});

test('app art: every failure from the drawing service becomes a sentence a maker can act on', async () => {
  const f = fixture(), cookie = await maker(f);
  assert.equal((await f.call('/api/seeds/little-library/art', { scene: 'ab' }, cookie)).status, 400);
  assert.equal((await f.call('/api/seeds/little-library/art', { scene: 'x'.repeat(201) }, cookie)).status, 400);
  assert.equal((await f.call('/api/seeds/little-library/art', {}, cookie)).status, 400);
  assert.equal(f.draws.length, 0, 'a bad scene line never reaches the drawing service');
  f.drawing(400);
  const refused = await drawArt(f, cookie);
  assert.equal(refused.status, 422);
  assert.match((await refused.json()).error, /different words/);
  f.drawing(429);
  assert.equal((await drawArt(f, cookie)).status, 503);
  f.drawing(200, { created: 1, data: [] });
  assert.equal((await drawArt(f, cookie)).status, 502);
  f.drawing(200, { created: 1, data: [{ b64_json: Buffer.from('not an image at all').toString('base64') }] });
  const wrong = await drawArt(f, cookie);
  assert.equal(wrong.status, 502);
  assert.match((await wrong.json()).error, /format the farm cannot keep/);
  f.drawing(200);
  delete f.env.OPENAI_API_KEY;
  const off = await drawArt(f, cookie);
  assert.equal(off.status, 503);
  assert.match((await off.json()).error, /not switched on/);
  assert.equal(f.objects.size, 0, 'nothing is filed when no drawing arrives');
});

test('app art: the pair reaches the submission this app already has', async () => {
  const f = fixture(), cookie = await maker(f);
  assert.equal((await f.call('/api/seeds', seedForm(), cookie)).status, 201);
  const before = await (await f.call('/api/seeds/mine', undefined, cookie, {}, 'GET')).json();
  assert.equal(before.seeds[0].icon, undefined);
  const drawn = await (await drawArt(f, cookie)).json();
  const after = await (await f.call('/api/seeds/mine', undefined, cookie, {}, 'GET')).json();
  assert.equal(after.seeds[0].icon, drawn.icon);
  const record = await f.store.get('seed:little-library@0.1.0', 'json');
  assert.deepEqual(record.media, { header: drawn.header, icon: drawn.icon });
});

test('drawing app art runs outside the coordinator queue, so no other maker waits behind it', async () => {
  const f = fixture();
  const seen = [];
  f.env.FARM_COORDINATOR = { idFromName: () => 'farm', get: () => ({ fetch: request => {
    seen.push(new URL(request.url).pathname);
    return createApp({ fetcher: f.fetcher, proofRoutes, seedRoutes, artRoutes })(request, f.env);
  } }) };
  const coordinator = new FarmCoordinator({ storage: new Map([]), waitUntil: () => {} }, f.env);
  assert.equal(typeof coordinator.fetch, 'function');
  const source = await readFile(new URL('../worker/main.mjs', import.meta.url), 'utf8');
  assert.match(source, /\/art\$\/\.test\(pathname\)\) return execute\(\)/);
  const response = await worker.fetch(new Request(ORIGIN + '/api/seeds/little-library/art', { method: 'POST', headers: { Origin: ORIGIN, 'Content-Type': 'application/json' }, body: '{}' }), f.env);
  assert.equal(seen.at(-1), '/api/seeds/little-library/art');
  assert.equal(response.status, 401);
});

// The release-to-listing path: the maker's button, driven by the fake app repository above.
async function ownedApp(f, manifest = listedApp()) {
  const signed = await f.email();
  await f.proof(signed.cookie);
  f.published.set(manifest.id, manifest);
  await f.store.put('seedowner:' + manifest.id, JSON.stringify(signed.user.id));
  return signed;
}
const checkFor = (f, signed, id = 'fake-app') => f.call(`/api/seeds/${id}/release-check`, {}, signed.cookie);

test('the release button opens one pull request and measures the archive itself', async () => {
  const f = fixture(), signed = await ownedApp(f);
  const response = await checkFor(f, signed);
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.status, 'found');
  assert.equal(result.message, 'v0.1.1 found, checks running, a maintainer will review it');
  assert.equal(f.releasePulls.length, 1);
  assert.equal(f.releasePulls[0].head.ref, 'farm-release/fake-app');
  assert.equal(f.releasePulls[0].base.ref, 'main');
  assert.equal(result.prUrl, f.releasePulls[0].html_url);
  const written = f.manifests.at(-1);
  assert.equal(written.version, '0.1.1');
  assert.equal(written.updatedAt, '2026-09-12');
  assert.equal(written.release.url, archiveURL('v0.1.1'));
  assert.equal(written.release.sha256, await sha256(ARCHIVES.get('v0.1.1')));
  assert.equal(written.release.size, ARCHIVES.get('v0.1.1').length);
  assert.notEqual(written.release.sha256, '0'.repeat(64), 'numbers in release notes are never copied');
  checkManifest(written);
  assert.equal(f.branches.get('farm-release/fake-app:fake-app'), serialize(written));
  assert.match(f.releasePulls[0].body, new RegExp(written.release.sha256));
  assert.ok(!f.releasePulls[0].body.includes('—'));
  for (const call of f.calls.filter(item => item.url.includes('/repos/Titanium-Devops/') && !item.url.endsWith('/installation')))
    assert.equal(call.headers.Authorization, 'Bearer app-installation-token', 'every catalog write uses the app token');
});

test('the button is limited to once a minute and then reuses the open pull request', async () => {
  const f = fixture(), signed = await ownedApp(f);
  const first = await (await checkFor(f, signed)).json();
  const again = await checkFor(f, signed);
  assert.equal(again.status, 429);
  assert.match((await again.json()).message, /checked a moment ago, so try again in \d+ seconds/);
  f.advance(61000);
  const third = await checkFor(f, signed);
  assert.equal(third.status, 200);
  assert.equal((await third.json()).prUrl, first.prUrl);
  assert.equal(f.releasePulls.length, 1, 'one pull request per app, never stacked');
  assert.equal(f.manifests.length, 1, 'an unchanged branch is not rewritten');
});

test('a newer release refreshes the same pull request instead of opening another', async () => {
  const f = fixture(), signed = await ownedApp(f);
  const first = await (await checkFor(f, signed)).json();
  f.setReleases([githubRelease('v0.1.0'), githubRelease('v0.1.1'), githubRelease('v0.2.0')]);
  f.advance(61000);
  const second = await (await checkFor(f, signed)).json();
  assert.equal(second.version, '0.2.0');
  assert.equal(second.prUrl, first.prUrl);
  assert.equal(f.releasePulls.length, 1);
  assert.equal(f.releasePulls[0].title, 'Fake App 0.2.0');
  assert.equal(f.manifests.at(-1).version, '0.2.0');
});

test('a listed release, an older release and manual updates each answer without a pull request', async () => {
  const f = fixture(), signed = await ownedApp(f, listedApp({ version: '0.1.1' }));
  assert.equal((await (await checkFor(f, signed)).json()).message, 'already listed at v0.1.1');
  assert.equal(f.releasePulls.length, 0);

  const older = fixture(), olderSigned = await ownedApp(older, listedApp({ version: '0.1.1' }));
  older.setReleases([githubRelease('v0.1.0')]);
  assert.equal((await (await checkFor(older, olderSigned)).json()).message, 'no release newer than v0.1.1 on GitHub');
  assert.equal(older.releasePulls.length, 0);

  const none = fixture(), noneSigned = await ownedApp(none);
  none.setReleases([]);
  assert.equal((await (await checkFor(none, noneSigned)).json()).message, 'no release newer than v0.1.0 on GitHub');

  const manual = fixture(), manualSigned = await ownedApp(manual, listedApp({ updates: 'manual' }));
  const answer = await (await checkFor(manual, manualSigned)).json();
  assert.equal(answer.status, 'manual');
  assert.equal(manual.releasePulls.length, 0);
  assert.equal(manual.manifests.length, 0);
});

test('drafts and prereleases are skipped unless the manifest opts in', async () => {
  const releases = [githubRelease('v0.1.0'), githubRelease('v0.2.0', { prerelease: true }),
    githubRelease('v0.3.0', { draft: true }), githubRelease('v0.1.1-rc.1')];
  const f = fixture(), signed = await ownedApp(f);
  f.setReleases(releases);
  assert.equal((await (await checkFor(f, signed)).json()).message, 'already listed at v0.1.0');
  assert.equal(f.releasePulls.length, 0);
  const opted = fixture(), optedSigned = await ownedApp(opted, listedApp({ prereleases: true }));
  opted.setReleases(releases);
  const result = await (await checkFor(opted, optedSigned)).json();
  assert.equal(result.version, '0.2.0', 'a draft is never a candidate');
  assert.equal(opted.releasePulls.length, 1);
});

test('only the signed-in maker of the app can press the button', async () => {
  const f = fixture(), signed = await ownedApp(f);
  assert.equal((await f.call('/api/seeds/fake-app/release-check', {})).status, 401);
  const stranger = await f.email('stranger@example.org');
  assert.equal((await checkFor(f, stranger)).status, 403);
  assert.equal((await f.call('/api/seeds/no-such-app/release-check', {}, signed.cookie)).status, 404);
  assert.equal((await f.call('/api/seeds/fake-app/release-check', undefined, signed.cookie)).status, 405);
  assert.equal((await f.call('/api/seeds/fake-app/release-check', {}, signed.cookie, { Origin: 'https://evil.example' })).status, 403);
  assert.equal(f.releasePulls.length, 0);
});

test('Your apps carries the last release check for an app the maker owns', async () => {
  const f = fixture(), signed = await ownedApp(f);
  const checked = await (await checkFor(f, signed)).json();
  const { seeds } = await (await f.call('/api/seeds/mine', undefined, signed.cookie)).json();
  const mine = seeds.find(seed => seed.id === 'fake-app');
  assert.equal(mine.canUpdate, true);
  assert.equal(mine.release.message, checked.message);
  assert.equal(mine.release.prUrl, checked.prUrl);
  assert.equal(mine.release.status, 'found');
});

test('the app JWT is RS256 over the app id, from a PKCS#1 or a PKCS#8 key', async () => {
  const moment = Date.parse('2026-09-12T12:00:00Z');
  const token = await appJWT({ FARM_APP_ID: '456', FARM_APP_PRIVATE_KEY: KEYS.privateKey }, moment);
  const [header, claims, signature] = token.split('.');
  assert.deepEqual(JSON.parse(Buffer.from(header, 'base64url').toString()), { alg: 'RS256', typ: 'JWT' });
  const body = JSON.parse(Buffer.from(claims, 'base64url').toString());
  assert.equal(body.iss, '456');
  assert.equal(body.iat, Math.floor(moment / 1000) - 60);
  assert.equal(body.exp - body.iat, 600);
  const der = Uint8Array.from(Buffer.from(KEYS.publicKey.replace(/-----[^-]*-----/g, '').replace(/\s+/g, ''), 'base64'));
  const key = await crypto.subtle.importKey('spki', der, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
  assert.ok(await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, Buffer.from(signature, 'base64url'),
    Buffer.from(`${header}.${claims}`)), 'the signature verifies with the app public key');
  const pkcs8 = createPublicKey(KEYS.publicKey) && generateKeyPairSync('rsa', { modulusLength: 2048,
    publicKeyEncoding: { type: 'spki', format: 'pem' }, privateKeyEncoding: { type: 'pkcs8', format: 'pem' } });
  assert.match(await appJWT({ FARM_APP_ID: '7', FARM_APP_PRIVATE_KEY: pkcs8.privateKey }, moment), /^eyJ/);
  assert.deepEqual(privateKeyBytes(pkcs8.privateKey),
    Uint8Array.from(Buffer.from(pkcs8.privateKey.replace(/-----[^-]*-----/g, '').replace(/\s+/g, ''), 'base64')));
});

test('without the app credentials the button still answers, but says a found release needs them', async () => {
  const quiet = fixture({ appKeys: false });
  const signed = await ownedApp(quiet, listedApp({ version: '0.1.1' }));
  assert.equal((await (await checkFor(quiet, signed)).json()).message, 'already listed at v0.1.1');
  const f = fixture({ appKeys: false }), owner = await ownedApp(f);
  const response = await checkFor(f, owner);
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /not switched on yet/);
  assert.equal(f.releasePulls.length, 0);
});

test('the archive shape of the listing is kept: an asset stays an asset, a source archive stays one', () => {
  const packaged = listedApp({ release: { url: assetURL('v0.1.0', 'fake-app-0.1.0.tar.gz'), sha256: 'c'.repeat(64), size: 4 } });
  const release = githubRelease('v0.1.1', { assets: [{ name: 'fake-app-0.1.1.tar.gz', browser_download_url: assetURL('v0.1.1', 'fake-app-0.1.1.tar.gz') }] });
  assert.equal(pickURL(packaged, APP_REPO, release, '0.1.1'), assetURL('v0.1.1', 'fake-app-0.1.1.tar.gz'));
  assert.equal(pickURL(listedApp(), APP_REPO, githubRelease('v0.1.1'), '0.1.1'), archiveURL('v0.1.1'));
  assert.equal(pickRelease([githubRelease('v0.1.0'), githubRelease('v0.1.1')]).version, '0.1.1');
  assert.equal(pickRelease([githubRelease('v0.2.0', { draft: true })]), null);
  assert.throws(() => pickURL(packaged, APP_REPO, githubRelease('v0.1.1', { assets: [
    { name: 'one.tar.gz', browser_download_url: assetURL('v0.1.1', 'one.tar.gz') },
    { name: 'two.tar.gz', browser_download_url: assetURL('v0.1.1', 'two.tar.gz') }] }), '0.1.1'),
  /no tar.gz asset named fake-app-0.1.1.tar.gz/);
});

test('a maker repository the farm app cannot read is asked for without a credential', async () => {
  const f = fixture(), signed = await ownedApp(f);
  f.publicOnly();
  const result = await (await checkFor(f, signed)).json();
  assert.equal(result.status, 'found');
  assert.equal(f.releasePulls.length, 1);
});

// docs/openapi.json is built from worker/openapi.py, and tests/test_openapi.py walks the route
// table against it by reading the source. This is the other half of that: every documented route
// is asked for, through the front door, and has to answer as itself rather than fall through to
// the catch-all, with a status the document lists.
test('openapi: every documented route answers, and answers something the document promises', async () => {
  const loaded = spawnSync('python3', ['-c',
    'import json, runpy; print(json.dumps(runpy.run_path("worker/openapi.py")["spec"]()))'],
    { encoding: 'utf8' });
  assert.equal(loaded.status, 0, loaded.stderr);
  const spec = JSON.parse(loaded.stdout);
  const f = fixture();
  f.env.FARM_COORDINATOR = { idFromName: name => name, get: () => ({
    fetch: request => createApp({ fetcher: f.fetcher, now: f.now, proofRoutes, releaseRoutes, seedRoutes, artRoutes })(request, f.env) }) };
  const wrong = [];
  for (const [path, item] of Object.entries(spec.paths)) {
    if (item['x-farm-source'] === 'assets') continue;
    for (const [method, operation] of Object.entries(item)) {
      if (method === 'x-farm-source') continue;
      const where = path.replace(/\{(\w+)\}/g, (_, name) =>
        operation.parameters.find(parameter => parameter.name === name).example);
      const response = await worker.fetch(new Request(ORIGIN + where,
        { method: method.toUpperCase(), headers: { Origin: ORIGIN } }), f.env);
      const body = await response.text();
      const named = method.toUpperCase() + ' ' + path + ' answered ' + response.status;
      if (body.includes('This route does not exist.')) wrong.push(named + ', the catch-all');
      else if (!operation.responses[String(response.status)]) wrong.push(named + ', undocumented');
    }
  }
  assert.deepEqual(wrong, []);
});
