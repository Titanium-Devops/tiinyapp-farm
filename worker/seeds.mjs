import { fail, json, remote, sha256 } from './index.mjs';
import { checkManifest } from './manifest.mjs';
import { catalog } from './makers.mjs';
const LEGACY = new Set(['tiiny-bench', 'onelane', 'story-lantern', 'titanium-tiiny-bot']);
function compareVersion(a, b) {
  const left = a.split('.').map(BigInt), right = b.split('.').map(BigInt);
  for (let i = 0; i < 3; i++) if (left[i] !== right[i]) return left[i] > right[i] ? 1 : -1;
  return 0;
}
const ORIGIN = 'https://tiinyapp.farm';
const API = 'https://api.github.com/repos/Titanium-Devops/tiinyapp-farm';
const MAX = 50 * 1024 * 1024;
export function releaseURL(value) {
  let url; try { url = new URL(value); } catch { fail(400, 'Use a public HTTPS release URL.'); }
  // Reject IP literals, local names, credentials and nonstandard ports. Every redirect hop is checked here too.
  if (url.protocol !== 'https:' || url.username || url.password || url.hash || (url.port && url.port !== '443') ||
      !/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(url.hostname) || /(^|\.)(localhost|local|internal|test|invalid)$/i.test(url.hostname)) fail(400, 'Use a public HTTPS release URL.');
  return url.href;
}
// A seed with no start command is a library, and says so, without the maker knowing the word.
function tags(input) {
  const given = typeof input.tags === 'string' ? input.tags.split(',').map(t => t.trim().toLowerCase()).filter(Boolean) : [];
  const entry = input.command || (input.entry && input.entry !== 'null');
  return !entry && !given.includes('library') ? [...given, 'library'] : given;
}
export function buildManifest(input, user, release, now) {
  const list = key => typeof input[key] === 'string' ? input[key].split(',').map(s => s.trim()).filter(Boolean) : [];
  const today = new Date(now).toISOString().slice(0, 10);
  const parsed = (key, fallback) => {
    if (!input[key]) return fallback;
    try { return JSON.parse(input[key]); } catch { fail(400, 'Send valid ' + key + ' details.'); }
  };
  const media = parsed('media', undefined);
  const links = Object.fromEntries(['repo', 'video', 'homepage'].filter(key => input[key]).map(key => [key, input[key]]));
  const manifest = {
    ...(media === undefined ? {} : { media }), links,
    id: input.id, name: input.name, pitch: input.pitch, description: input.description, version: input.version,
    author: { name: user.tiinyverse.name, url: user.tiinyverse.profileUrl, tiinyverse: user.tiinyverse.profileUrl },
    license: input.license, homepage: input.homepage || input.repo || user.tiinyverse.profileUrl,
    ...(input.repo ? { repo: input.repo } : {}), screenshots: parsed('screenshots', []), ...(release ? { release } : {}),
    entry: input.command ? { command: input.command } : parsed('entry', null),
    requires: { ...(input.python ? { python: input.python } : {}), ports: list('ports').map(Number),
      device: { models: list('models'), npuUnits: Number(input.npuUnits || 0) } },
    permissions: list('permissions'), tags: tags(input), verified: false, addedAt: today, updatedAt: today,
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
  const owns = async (user, manifest) => {
    if (!user.tiinyverse) return false;
    const owner = await get('seedowner:' + manifest.id);
    return owner ? owner === user.id : LEGACY.has(manifest.id) && manifest.author?.tiinyverse === user.tiinyverse.profileUrl;
  };
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
      const social = await get('social:' + seed.id);
      item.thumbs = social?.thumbs?.length || 0; item.comments = social?.comments?.length || 0;
      try {
        const published = await env.ASSETS.fetch(new Request(ORIGIN + '/manifests/' + seed.id + '.json'));
        if (published.ok) {
          const manifest = await published.json();
          if (manifest.id === seed.id) { item.url = '/apps/' + seed.id + '/'; item.canUpdate = await owns(user, manifest); }
        }
      } catch { /* A pending seed has no static catalog page yet. */ }
      seeds.push(item);
    }
    // Include hand-added plots, which have no submission history in storage.
    let published = [];
    try { published = await catalog(env); } catch { /* Stored review status remains available. */ }
    if (Array.isArray(published)) for (const manifest of published) {
      if (!await owns(user, manifest)) continue;
      const items = seeds.filter(seed => seed.id === manifest.id);
      if (items.length) items.forEach(seed => { seed.canUpdate = true; });
      else {
        const social = await get('social:' + manifest.id);
        seeds.push({ id: manifest.id, name: manifest.name, version: manifest.version,
          state: manifest.release ? 'published' : 'sprouting', url: '/apps/' + manifest.id + '/',
          canUpdate: true, checks: [], reviews: [], thumbs: social?.thumbs?.length || 0, comments: social?.comments?.length || 0 });
      }
    }
    return json({ seeds });
  }
  const update = request.method === 'PUT' && path.match(/^\/api\/seeds\/([a-z][a-z0-9]*(?:-[a-z0-9]+)*)$/);
  if ((path === '/api/seeds' && request.method === 'POST') || update) {
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
    if (input.releaseUrl && upload) fail(400, 'Choose either a release URL or one tar.gz upload.');
    if (upload && (file.size > MAX || !/^[a-zA-Z0-9][a-zA-Z0-9._-]*\.tar\.gz$/.test(file.name))) fail(400, 'Upload a tar.gz file up to 50 MB with a simple filename.');
    // Validate all ordinary fields before fetching archives or creating external resources.
    let manifest = buildManifest(input, user, { url: ORIGIN + '/placeholder.tar.gz', sha256: '0'.repeat(64), size: 1 }, now());
    if (update && input.id !== update[1]) fail(400, 'The seed ID cannot change during an update.');
    let existing, current;
    if (update) {
      existing = await github('/contents/manifests/' + manifest.id + '.json', 'GET', undefined, true);
      if (!existing) fail(404, 'That seed is not in the field yet.');
      try { current = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(existing.content.replace(/\s/g, '')), c => c.charCodeAt(0)))); }
      catch { fail(502, 'The current seed manifest could not be read.'); }
      if (current.id !== manifest.id) fail(502, 'The current seed manifest does not match its ID.');
      if (!await owns(user, current)) fail(403, 'Only this seed’s verified maker can update it.');
      const comparison = compareVersion(manifest.version, current.version);
      if (comparison < 0 || ((upload || input.releaseUrl) && comparison <= 0)) fail(400, 'Use a strictly newer version when adding a release; text updates may keep the current version.');
    }
    const uploadedBytes = upload ? new Uint8Array(await file.arrayBuffer()) : null;
    const updateHash = update ? await sha256(new TextEncoder().encode(JSON.stringify(input) + existing.sha + (uploadedBytes ? await sha256(uploadedBytes) : ''))) : '';
    const key = `${manifest.id}@${manifest.version}` + (update ? ':update:' + updateHash : '');
    // Separate pending updates must never overwrite or clean up another PR’s archive.
    const uploadName = upload ? (update ? updateHash + '-' : '') + file.name : null;
    const previous = await get('seed:' + key);
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
    if (!update && await github('/contents/manifests/' + manifest.id + '.json', 'GET', undefined, true)) fail(409, 'That seed ID is already in the field. Use Update from your farm.');
    const recent = (await get('seed-rate:' + user.id) || []).filter(t => t > now() - 3600000);
    if (recent.length >= 5) fail(429, 'Five planting attempts per hour; please try again later.');
    await put('seed-rate:' + user.id, [...recent, now()]);
    let bytes, release = current?.release;
    if (upload) {
      bytes = uploadedBytes;
      release = { url: `${ORIGIN}/seeds-files/${manifest.id}/${manifest.version}/${uploadName}` };
    } else if (input.releaseUrl) {
      const address = releaseURL(input.releaseUrl);
      // GitHub release downloads answer 302 to a storage host; follow up to three https hops.
      let hop = address, response;
      for (let i = 0; i < 4; i++) {
        response = await remote(fetcher, hop, {}, MAX);
        if (![301, 302, 303, 307, 308].includes(response.status)) break;
        const location = response.headers?.get?.('location');
        if (!location || i === 3) fail(422, 'The release URL redirects too many times.');
        hop = releaseURL(new URL(location, hop).href);
      }
      if (response.status !== 200) fail(422, `That release link answered ${response.status}, not 200. Open it in a browser first; it must download the tar.gz.`);
      bytes = response.bytes; release = { url: address };
    }
    if (bytes && (bytes.length < 2 || bytes[0] !== 0x1f || bytes[1] !== 0x8b)) fail(400, 'The release must be a gzip archive.');
    if (bytes) { release.sha256 = await sha256(bytes); release.size = bytes.length; }
    manifest = buildManifest(input, user, release, now());
    if (current) manifest.addedAt = current.addedAt;
    const branch = 'farm/' + manifest.id + '-' + crypto.randomUUID();
    const record = { userId: user.id, id: manifest.id, name: manifest.name, version: manifest.version, branch, state: 'preparing', createdAt: new Date(now()).toISOString() };
    await put('seedowner:' + manifest.id, user.id);
    await put('seed:' + key, record);
    const keys = await get('user-seeds:' + user.id) || [];
    if (!keys.includes(key)) await put('user-seeds:' + user.id, [...keys, key]);
    let objectKey, branchCreated = false, creatingPR = false;
    try {
      if (upload) {
        objectKey = `seeds/${manifest.id}/${manifest.version}/${uploadName}`;
        await env.SEEDS.put(objectKey, bytes, { httpMetadata: { contentType: 'application/gzip' }, customMetadata: { sha256: release.sha256 } });
      }
      const repository = await github('');
      const base = repository.default_branch;
      const ref = await github('/git/ref/heads/' + encodeURIComponent(base));
      await github('/git/refs', 'POST', { ref: 'refs/heads/' + branch, sha: ref.object.sha });
      branchCreated = true;
      const content = btoa(Array.from(new TextEncoder().encode(JSON.stringify(manifest, null, 2) + '\n'), byte => String.fromCharCode(byte)).join(''));
      const validation = bytes ? 'Farm manifest validation and archive SHA-256' : 'Farm manifest validation';
      await github('/contents/manifests/' + manifest.id + '.json', 'PUT', {
        message: `${update ? 'Keep' : 'Give'} ${manifest.id} ${update ? 'current through' : 'a plot for'} community review\n\nSubmitted through the farm by a verified TiinyVerse owner.\n\nConfidence: medium\nScope-risk: narrow\nTested: ${validation}\nNot-tested: Awaiting CI and maintainer review`, content, branch, ...(update ? { sha: existing.sha } : {}),
      });
      creatingPR = true;
      const pr = await github('/pulls', 'POST', { title: `${update ? 'Tend' : 'Plant'} ${manifest.id} ${manifest.version}`, head: branch, base,
        body: `Submitted from tiinyapp.farm by ${user.tiinyverse.profileUrl}.\n\n${bytes ? 'Manifest and archive checksum validated by the farm.' : release ? 'Manifest validated; the existing release is retained.' : 'Manifest validated; this seed is sprouting with no release yet.'} CI checks and human review are still required.\n\nThe site keeps verified=false; a maintainer decides whether to merge.` });
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
        return json({ id: manifest.id, statusUrl: '/seeds/mine/', warning: 'The review request was interrupted. Your submission is saved; a farmhand must reconcile this submission before you retry.' }, 202);
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
