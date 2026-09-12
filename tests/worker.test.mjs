import test from 'node:test';
import assert from 'node:assert/strict';
import { gzipSync } from 'node:zlib';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import { spawnSync } from 'node:child_process';
import { createApp, sha256, boundedBody } from '../worker/index.mjs';
import { proofRoutes } from '../worker/proof.mjs';
import { seedRoutes, releaseURL } from '../worker/seeds.mjs';
import { checkManifest } from '../worker/manifest.mjs';
import worker, { FarmCoordinator } from '../worker/main.mjs';
const ORIGIN = 'https://tiinyapp.farm';
const PROFILE = 'https://www.tiinyverse.com/users/39628b1e-e94e-4bd8-800e-5437d5336e1f';
const archive = gzipSync(Buffer.from('fixture source archive; extraction is checked separately in Python CI'));
class Store {
  values = new Map();
  async get(key, type) { const value = this.values.get(key); return type === 'json' && value ? JSON.parse(value) : value ?? null; }
  async put(key, value) { this.values.set(key, value); }
  async delete(key) { this.values.delete(key); }
}
function fixture() {
  let clock = Date.parse('2026-09-12T12:00:00Z');
  const store = new Store(), objects = new Map(), mails = [], calls = [], manifests = [], published = new Map();
  let html = '<h1>Aster &amp; Fern</h1>', githubId = 42, githubFail = '', profileStatus = 200, resendStatus = 200;
  const env = { FARM: store, SESSION_SECRET: 'test-secret-with-at-least-32-characters', RESEND_API_KEY: 'resend-secret',
    GITHUB_CLIENT_ID: 'client', GITHUB_CLIENT_SECRET: 'client-secret', FARM_GITHUB_TOKEN: 'farm-only-secret',
    SEEDS: { async put(key, value, options) { objects.set(key, { value, options }); },
      async get(key) { const object = objects.get(key); return object && { body: object.value, size: object.value.length, httpEtag: '"fixture"' }; },
      async delete(key) { objects.delete(key); } },
    ASSETS: { fetch: async request => {
      const path = new URL(request.url).pathname;
      if (path === '/catalog.json') return Response.json([...published.values()]);
      const seed = published.get(path.match(/^\/manifests\/(.+)\.json$/)?.[1]);
      return seed ? Response.json(seed) : new Response('static farm');
    } } };
  const fetcher = async (url, options = {}) => {
    calls.push({ url: String(url), ...options });
    const reply = (body, status = 200) => new Response(JSON.stringify(body), { status });
    if (String(url) === 'https://api.resend.com/emails') { mails.push(JSON.parse(options.body)); return reply({ id: 'mail' }, resendStatus); }
    if (String(url).startsWith('https://www.tiinyverse.com/')) {
      assert.equal(options.headers['User-Agent'], 'tiinyapp-farm-verifier/1.0'); assert.equal(options.redirect, 'manual'); assert.ok(options.signal);
      return new Response(html, { status: profileStatus });
    }
    if (String(url) === 'https://github.com/login/oauth/access_token') return reply({ access_token: 'never-store-this-token' });
    if (String(url) === 'https://api.github.com/user') return reply({ id: githubId, login: 'gardener' + githubId, name: 'GitHub name', avatar_url: 'https://example.org/avatar.png' });
    if (String(url).startsWith('https://api.github.com/repos/Titanium-Devops/tiinyapp-farm')) {
      if (String(url).includes('/commits/')) assert.equal(options.headers.Authorization, undefined);
      else assert.equal(options.headers.Authorization, 'Bearer farm-only-secret');
      const route = String(url).replace('https://api.github.com/repos/Titanium-Devops/tiinyapp-farm', '');
      if (githubFail && route.includes(githubFail)) return reply({ error: 'fake failure' }, 500);
      if (route === '') return reply({ default_branch: 'main' });
      if (route.startsWith('/contents/') && options.method === 'GET') {
        const seed = published.get(route.match(/manifests\/(.+)\.json$/)?.[1]);
        return seed ? reply({ sha: 'c'.repeat(40), content: Buffer.from(JSON.stringify(seed)).toString('base64') }) : reply({}, 404);
      }
      if (route.startsWith('/contents/') && options.method === 'PUT') { manifests.push(JSON.parse(Buffer.from(JSON.parse(options.body).content, 'base64').toString())); return reply({ content: {} }); }
      if (route.startsWith('/git/ref/')) return reply({ object: { sha: 'a'.repeat(40) } });
      if (route.startsWith('/git/refs')) return reply({});
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
  const app = createApp({ fetcher, now: () => clock, proofRoutes, seedRoutes });
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
  return { env, store, objects, mails, manifests, published, calls, call, email, proof, fetcher,
    advance: n => { clock += n; }, html: s => { html = s; }, githubId: n => { githubId = n; }, githubFail: s => { githubFail = s; },
    profileStatus: n => { profileStatus = n; }, resendStatus: n => { resendStatus = n; } };
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
  assert.equal(first.user.handle, null); assert.equal(first.user.bio, ''); assert.equal(first.user.avatarKey, null);
  assert.equal((await f.call('/farm/')).headers.get('Location'), '/seeds/');
  assert.equal((await f.call('/seeds/mine/')).headers.get('Location'), '/farm/');
  assert.equal((await f.call('/makers/unknown/')).status, 404);
  await f.proof(first.cookie);
  const user = (await (await f.call('/api/me', undefined, first.cookie)).json()).user;
  assert.match(user.handle, /^aster-fern-[a-f0-9]{4}$/);
  assert.equal((await f.call('/farm/', undefined, first.cookie)).headers.get('Cache-Control'), 'private, no-store');
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
  assert.deepEqual(await (await f.call(endpoint + '/social')).json(), { thumbs: 0, mine: false, comments: [] });
  assert.equal((await f.call('/api/seeds/not-here/social')).status, 404);
  assert.equal((await f.call(endpoint + '/thumb', {})).status, 401);
  const first = await f.email();
  assert.equal((await f.call(endpoint + '/comments', { text: 'Hi' }, first.cookie)).status, 403);
  let social = await (await f.call(endpoint + '/thumb', {}, first.cookie)).json();
  assert.equal(social.thumbs, 1); assert.equal(social.mine, true);
  social = await (await f.call(endpoint + '/thumb', {}, first.cookie)).json(); assert.equal(social.thumbs, 0); assert.equal(social.mine, false);
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

test('private seed cards include live social counts and only published page links', async () => {
  const f = fixture(), first = await f.email(); await f.proof(first.cookie);
  await f.call('/api/seeds', seedForm(), first.cookie);
  let seeds = (await (await f.call('/api/seeds/mine', undefined, first.cookie)).json()).seeds;
  assert.equal(seeds[0].url, undefined);
  socialFixture(f);
  await f.call('/api/seeds/little-library/thumb', {}, first.cookie);
  await f.call('/api/seeds/little-library/comments', { text: 'Growing well' }, first.cookie);
  seeds = (await (await f.call('/api/seeds/mine', undefined, first.cookie)).json()).seeds;
  assert.equal(seeds[0].url, '/apps/little-library/'); assert.equal(seeds[0].thumbs, 1); assert.equal(seeds[0].comments, 1);
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
  assert.match(html, /<h1>Apps by Aster &amp; Fern<\/h1>/);
  assert.match(html, />Your apps<\/a>/);
  assert.match(html, /No apps in the catalog yet\./);
  assert.doesNotMatch(html, /Bring your seeds|Seeds in the field/);
  assert.match(html, /src="\/assets\/share.js"/);
  assert.match(html, /<button[^>]*type="button"[^>]*data-share /);
  assert.match(html, /data-share-status role="status" aria-live="polite"/);
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
  for (const state of ['merged', 'published', 'sprouting']) assert.equal(appStatus({ state }), 'In the catalog');
  assert.equal(appStatus({ state: 'awaiting review', checks: [] }), 'Checks running');
  assert.equal(appStatus({ state: 'awaiting review', checks: [{ name: 'CI', status: 'queued' }] }), 'Checks running');
  assert.equal(appStatus({ state: 'awaiting review', checks: [{ name: 'CI', status: 'success' }] }), 'Waiting for a maintainer');
  assert.equal(appStatus({ state: 'awaiting review', checks: [{ name: 'CI', status: 'timed_out' }] }), 'Checks failed: CI (timed out)');
  assert.equal(appStatus({ state: 'awaiting review', url: '/apps/existing/', checks: [{ name: 'CI', status: 'failure' }] }), 'Checks failed: CI (failure)');
  assert.equal(appStatus({ state: 'awaiting review', unavailable: true }), 'Check status unavailable');
  assert.equal(appStatus({ state: 'closed' }), 'Closed without merging');
});
