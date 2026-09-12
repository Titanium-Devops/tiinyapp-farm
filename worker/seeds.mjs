import { fail, json, remote, sha256 } from './index.mjs';
import { checkManifest } from './manifest.mjs';
const ORIGIN = 'https://tiinyapp.farm';
const API = 'https://api.github.com/repos/Titanium-Devops/tiinyapp-farm';
const MAX = 50 * 1024 * 1024;
export function releaseURL(value) {
  let url; try { url = new URL(value); } catch { fail(400, 'Use a public HTTPS release URL.'); }
  // Reject IP literals, local names, credentials and nonstandard ports. Redirects are never followed.
  if (url.protocol !== 'https:' || url.username || url.password || url.hash || (url.port && url.port !== '443') ||
      !/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(url.hostname) || /(^|\.)(localhost|local|internal|test|invalid)$/i.test(url.hostname)) fail(400, 'Use a public HTTPS release URL.');
  return url.href;
}
export function buildManifest(input, user, release, now) {
  const list = key => typeof input[key] === 'string' ? input[key].split(',').map(s => s.trim()).filter(Boolean) : [];
  const today = new Date(now).toISOString().slice(0, 10);
  const manifest = {
    id: input.id, name: input.name, pitch: input.pitch, description: input.description, version: input.version,
    author: { name: user.tiinyverse.name, url: user.tiinyverse.profileUrl, tiinyverse: user.tiinyverse.profileUrl },
    license: input.license, homepage: input.homepage || input.repo || user.tiinyverse.profileUrl,
    ...(input.repo ? { repo: input.repo } : {}), screenshots: [], release,
    entry: input.command ? { command: input.command } : null,
    requires: { ...(input.python ? { python: input.python } : {}), ports: list('ports').map(Number),
      device: { models: list('models'), npuUnits: Number(input.npuUnits || 0) } },
    permissions: list('permissions'), tags: list('tags'), verified: false, addedAt: today, updatedAt: today,
    ...(input.selfcheck === 'true' ? { selfcheck: true } : {}), ...(input.health ? { health: input.health } : {}),
  };
  checkManifest(manifest);
  return manifest;
}
export async function seedRoutes(ctx) {
  const { path, request, env, requireUser, get, put, fetcher, now } = ctx;
  async function github(route, method = 'GET', body, allow404 = false) {
    if (!env.FARM_GITHUB_TOKEN) fail(503, 'Seed submission is not configured yet.');
    const publicChecks = method === 'GET' && route.startsWith('/commits/');
    const result = await remote(fetcher, API + route, { method, headers: {
      ...(publicChecks ? {} : { Authorization: `Bearer ${env.FARM_GITHUB_TOKEN}` }), Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'tiinyapp-farm', 'Content-Type': 'application/json',
    }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) }, 1024 * 1024);
    if (result.status === 404 && allow404) return null;
    if (!result.ok) fail(502, 'GitHub could not finish the seed review request. Please try again.');
    return result.status === 204 ? {} : JSON.parse(result.text());
  }
  if (path === '/api/seeds/mine' && request.method === 'GET') {
    const user = await requireUser(), keys = await get('user-seeds:' + user.id) || [];
    const seeds = [];
    for (const key of keys) {
      const seed = await get('seed:' + key);
      if (!seed || seed.userId !== user.id) continue;
      const item = { id: seed.id, version: seed.version, name: seed.name, state: seed.state, prUrl: seed.prUrl, checks: [], reviews: [] };
      if (seed.pr) {
        try {
          const pr = await github('/pulls/' + seed.pr);
          item.state = pr.merged_at ? 'merged' : pr.state === 'closed' ? 'closed' : pr.draft ? 'draft' : 'awaiting review';
          const checks = await github('/commits/' + pr.head.sha + '/check-runs?per_page=100');
          item.checks = checks.check_runs.map(check => ({ name: check.name, status: check.conclusion || check.status }));
          const statuses = await github('/commits/' + pr.head.sha + '/status?per_page=100');
          item.checks.push(...statuses.statuses.map(status => ({ name: status.context, status: status.state })));
          const reviews = await github('/pulls/' + seed.pr + '/reviews?per_page=100');
          const latest = new Map();
          for (const review of reviews) if (review.state !== 'COMMENTED') latest.set(review.user.id, review.state);
          item.reviews = [...latest.values()];
          item.labelPending = seed.state === 'label pending';
        } catch { item.unavailable = true; }
      }
      seeds.push(item);
    }
    return json({ seeds });
  }
  if (path === '/api/seeds' && request.method === 'POST') {
    const user = await requireUser();
    if (!user.tiinyverse) fail(403, 'Prove your Tiiny before planting a seed.');
    if (!env.FARM_GITHUB_TOKEN) fail(503, 'Seed submission is not configured yet.');
    let form;
    if (request.headers.get('Content-Type')?.startsWith('multipart/form-data')) {
      let size = 0;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 30000);
      const stream = request.body.pipeThrough(new TransformStream({ transform(chunk, controller) {
        size += chunk.byteLength;
        if (size > MAX + 32768) fail(413, 'Uploads must be 50 MB or smaller.');
        controller.enqueue(chunk);
      } }), { signal: controller.signal });
      try { form = await new Response(stream, { headers: request.headers }).formData(); }
      catch (error) { if (controller.signal.aborted) fail(408, 'The upload took too long. Please try again.'); if (error.status) throw error; fail(400, 'Send the seed form with a tar.gz file.'); }
      finally { clearTimeout(timer); }
    } else fail(415, 'Send the seed form as multipart/form-data.');
    const input = {};
    for (const [key, value] of form) if (typeof value === 'string') {
      if (value.length > 12000) fail(400, 'A form field is too long.');
      input[key] = value.trim();
    }
    const file = form.get('archive'), upload = file && typeof file !== 'string' && file.size > 0;
    if (!!input.releaseUrl === !!upload) fail(400, 'Choose either a release URL or one tar.gz upload.');
    if (upload && (file.size > MAX || !/^[a-zA-Z0-9][a-zA-Z0-9._-]*\.tar\.gz$/.test(file.name))) fail(400, 'Upload a tar.gz file up to 50 MB with a simple filename.');
    // Validate all ordinary fields before fetching archives or creating external resources.
    let manifest = buildManifest(input, user, { url: ORIGIN + '/placeholder.tar.gz', sha256: '0'.repeat(64), size: 1 }, now());
    const key = `${manifest.id}@${manifest.version}`, previous = await get('seed:' + key);
    const owner = await get('seedowner:' + manifest.id);
    if (owner && owner !== user.id) fail(409, 'That seed name is already used by another maker.');
    if (previous?.pr) {
      if (previous.userId !== user.id) fail(409, 'That seed release already exists.');
      if (previous.state === 'label pending') {
        await github('/issues/' + previous.pr + '/labels', 'POST', { labels: ['from-the-site'] });
        previous.state = 'awaiting review'; await put('seed:' + key, previous);
      }
      return json({ id: previous.id, prUrl: previous.prUrl, statusUrl: '/seeds/mine/' });
    }
    if (previous?.state === 'submission uncertain') fail(409, 'This seed is being reconciled after an interrupted review request. Please contact a farmhand before retrying.');
    const existing = await github('/contents/manifests/' + manifest.id + '.json', 'GET', undefined, true);
    if (existing) fail(409, 'That seed ID is already in the field. Choose a new ID or ask a maintainer about an update.');
    const recent = (await get('seed-rate:' + user.id) || []).filter(t => t > now() - 3600000);
    if (recent.length >= 5) fail(429, 'Five planting attempts per hour; please try again later.');
    await put('seed-rate:' + user.id, [...recent, now()]);
    let bytes, release;
    if (upload) {
      bytes = new Uint8Array(await file.arrayBuffer());
      release = { url: `${ORIGIN}/seeds-files/${manifest.id}/${manifest.version}/${file.name}` };
    } else {
      const address = releaseURL(input.releaseUrl);
      const response = await remote(fetcher, address, {}, MAX);
      if (response.status !== 200) fail(422, 'Use a direct release URL that answers 200 without a redirect.');
      bytes = response.bytes; release = { url: address };
    }
    if (bytes.length < 2 || bytes[0] !== 0x1f || bytes[1] !== 0x8b) fail(400, 'The release must be a gzip archive.');
    release.sha256 = await sha256(bytes); release.size = bytes.length;
    manifest = buildManifest(input, user, release, now());
    const branch = 'farm/' + manifest.id + '-' + crypto.randomUUID();
    const record = { userId: user.id, id: manifest.id, name: manifest.name, version: manifest.version, branch, state: 'preparing', createdAt: new Date(now()).toISOString() };
    await put('seedowner:' + manifest.id, user.id);
    await put('seed:' + key, record);
    const keys = await get('user-seeds:' + user.id) || [];
    if (!keys.includes(key)) await put('user-seeds:' + user.id, [...keys, key]);
    let objectKey, branchCreated = false, creatingPR = false;
    try {
      if (upload) {
        objectKey = `seeds/${manifest.id}/${manifest.version}/${file.name}`;
        await env.SEEDS.put(objectKey, bytes, { httpMetadata: { contentType: 'application/gzip' }, customMetadata: { sha256: release.sha256 } });
      }
      const repository = await github('');
      const base = repository.default_branch;
      const ref = await github('/git/ref/heads/' + encodeURIComponent(base));
      await github('/git/refs', 'POST', { ref: 'refs/heads/' + branch, sha: ref.object.sha });
      branchCreated = true;
      const content = btoa(Array.from(new TextEncoder().encode(JSON.stringify(manifest, null, 2) + '\n'), byte => String.fromCharCode(byte)).join(''));
      await github('/contents/manifests/' + manifest.id + '.json', 'PUT', {
        message: `Give ${manifest.id} a plot for community review\n\nSubmitted through the farm by a verified TiinyVerse owner.\n\nConfidence: medium\nScope-risk: narrow\nTested: Farm manifest validation and archive SHA-256\nNot-tested: Awaiting CI and maintainer review`, content, branch,
      });
      creatingPR = true;
      const pr = await github('/pulls', 'POST', { title: `Plant ${manifest.id} ${manifest.version}`, head: branch, base,
        body: `Submitted from tiinyapp.farm by ${user.tiinyverse.profileUrl}.\n\nManifest and archive checksum validated by the farm. CI checks and human review are still required.\n\nThe site keeps verified=false; a maintainer decides whether to merge.` });
      record.pr = pr.number; record.prUrl = pr.html_url; record.state = 'label pending';
      await put('seed:' + key, record);
      await github('/issues/' + pr.number + '/labels', 'POST', { labels: ['from-the-site'] });
      record.state = 'awaiting review'; await put('seed:' + key, record);
      return json({ id: manifest.id, prUrl: record.prUrl, statusUrl: '/seeds/mine/' }, 201);
    } catch (error) {
      if (creatingPR && !record.pr) {
        // A timeout may mean GitHub accepted the PR. Keep its branch and archive
        // intact; a maintainer can reconcile using the recorded branch.
        record.state = 'submission uncertain'; await put('seed:' + key, record);
        return json({ id: manifest.id, statusUrl: '/seeds/mine/', warning: 'The review request was interrupted. Your archive is safe; a farmhand must reconcile this submission before you retry.' }, 202);
      }
      if (record.pr) return json({ id: manifest.id, statusUrl: '/seeds/mine/', warning: 'The seed reached review, but its site label is pending. Submit the same form again to retry the label.' }, 202);
      record.state = 'submission failed'; await put('seed:' + key, record);
      if (objectKey) await env.SEEDS.delete(objectKey);
      if (branchCreated) { try { await github('/git/refs/heads/' + branch, 'DELETE'); } catch { /* Reported via the stored failed submission and branch. */ } }
      throw error;
    }
  }
  return null;
}
