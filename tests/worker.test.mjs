import test from 'node:test';
import assert from 'node:assert/strict';
import { gzipSync } from 'node:zlib';
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
  const store = new Store(), objects = new Map(), mails = [], calls = [], manifests = [];
  let html = '<h1>Aster &amp; Fern</h1>', githubId = 42, githubFail = '', profileStatus = 200, resendStatus = 200;
  const env = { FARM: store, SESSION_SECRET: 'test-secret-with-at-least-32-characters', RESEND_API_KEY: 'resend-secret',
    GITHUB_CLIENT_ID: 'client', GITHUB_CLIENT_SECRET: 'client-secret', FARM_GITHUB_TOKEN: 'farm-only-secret',
    SEEDS: { async put(key, value, options) { objects.set(key, { value, options }); },
      async get(key) { const object = objects.get(key); return object && { body: object.value, size: object.value.length, httpEtag: '"fixture"' }; },
      async delete(key) { objects.delete(key); } },
    ASSETS: { fetch: async () => new Response('static farm') } };
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
      if (route.startsWith('/contents/') && options.method === 'GET') return reply({}, 404);
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
    throw new Error('Unexpected fetch: ' + url);
  };
  const app = createApp({ fetcher, now: () => clock, proofRoutes, seedRoutes });
  const call = async (path, body, session = '', extra = {}) => app(new Request(ORIGIN + path, {
    ...(body === undefined ? {} : { method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body) }),
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
  return { env, store, objects, mails, manifests, calls, call, email, proof, fetcher,
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
  for (const changes of [{ id: '../escape' }, { permissions: 'superuser' }, { ports: '70000' }, { tags: '' }, { version: '01.0.0' }, { releaseUrl: 'https://127.0.0.1/x' }]) {
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
