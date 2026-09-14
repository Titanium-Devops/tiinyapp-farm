import { fail, json, remote, sha256 } from './index.mjs';
import { FARM_REPO, GITHUB, compareVersion, ownsSeed, releaseURL } from './catalog.mjs';
// The maker's "Check for a new release" button. It follows the same rules as the hourly
// poller in farm/release.py: GitHub is asked for the newest full release, the archive is
// downloaded and measured here, and one pull request per app is opened or refreshed.
const ORIGIN = 'https://tiinyapp.farm';
const MAX = 50 * 1024 * 1024;
const BRANCH = 'farm-release/';
const MINUTE = 60000;
const TAG = /^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;
const REPO_URL = /^https:\/\/github\.com\/([A-Za-z0-9][A-Za-z0-9._-]*)\/([A-Za-z0-9][A-Za-z0-9._-]*?)(?:\.git)?\/?$/;
const ARCHIVE_URL = /^https:\/\/github\.com\/[^/]+\/[^/]+\/archive\/refs\/tags\/.+\.tar\.gz$/;
const ASSET_URL = /^https:\/\/github\.com\/[^/]+\/[^/]+\/releases\/download\/([^/]+)\/(.+)$/;
const encoder = new TextEncoder();
const base64 = bytes => btoa(Array.from(new Uint8Array(bytes), byte => String.fromCharCode(byte)).join(''));
const base64url = bytes => base64(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

function derLength(length) {
  if (length < 128) return [length];
  const bytes = [];
  for (let value = length; value > 0; value = Math.floor(value / 256)) bytes.unshift(value % 256);
  return [0x80 | bytes.length, ...bytes];
}
// GitHub hands out an App key as PKCS#1 and WebCrypto imports PKCS#8, so wrap one in the other.
export function privateKeyBytes(pem) {
  const der = Uint8Array.from(atob(String(pem).replace(/-----[^-]*-----/g, '').replace(/\s+/g, '')), c => c.charCodeAt(0));
  if (!/BEGIN RSA PRIVATE KEY/.test(pem)) return der;
  const algorithm = [0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00];
  const contents = [0x02, 0x01, 0x00, ...algorithm, 0x04, ...derLength(der.length), ...der];
  return Uint8Array.from([0x30, ...derLength(contents.length), ...contents]);
}
export async function appJWT(env, now) {
  if (!env.FARM_APP_ID || !env.FARM_APP_PRIVATE_KEY) fail(503, 'Release checks are not switched on yet. A maintainer must add the farm app credentials.');
  let key;
  try {
    key = await crypto.subtle.importKey('pkcs8', privateKeyBytes(env.FARM_APP_PRIVATE_KEY),
      { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['sign']);
  } catch { fail(503, 'The farm app private key could not be read.'); }
  const seconds = Math.floor(now / 1000);
  const header = base64url(encoder.encode(JSON.stringify({ alg: 'RS256', typ: 'JWT' })));
  const claims = base64url(encoder.encode(JSON.stringify({ iat: seconds - 60, exp: seconds + 540, iss: String(env.FARM_APP_ID) })));
  const signature = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', key, encoder.encode(`${header}.${claims}`));
  return `${header}.${claims}.${base64url(signature)}`;
}
export function client(fetcher, token) {
  return async (method, path, body, allow = []) => {
    const result = await remote(fetcher, GITHUB + path, {
      method,
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'tiinyapp-farm', 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }, 1024 * 1024);
    if (allow.includes(result.status)) return null;
    if (!result.ok) fail(502, 'GitHub could not finish the release check. Please try again.');
    return result.status === 204 || !result.bytes.length ? {} : JSON.parse(result.text());
  };
}
export async function appToken(env, fetcher, now) {
  const api = client(fetcher, await appJWT(env, now));
  const installation = await api('GET', `/repos/${FARM_REPO}/installation`);
  if (!installation?.id) fail(503, 'The farm app is not installed on the catalog repository.');
  const minted = await api('POST', `/app/installations/${installation.id}/access_tokens`);
  if (!minted?.token) fail(502, 'GitHub did not issue a token for the farm app.');
  return minted.token;
}
export function parseTag(tag) {
  const found = typeof tag === 'string' ? TAG.exec(tag.trim()) : null;
  return found ? found.slice(1).join('.') : null;
}
export function repoPath(url) {
  const found = typeof url === 'string' ? REPO_URL.exec(url.trim()) : null;
  if (!found) fail(400, 'Release tracking needs a github.com repository URL in the manifest.');
  return `${found[1]}/${found[2]}`;
}
export function pickRelease(releases, prereleases = false) {
  let best = null;
  for (const release of Array.isArray(releases) ? releases : []) {
    if (!release || typeof release !== 'object' || release.draft) continue;
    if (release.prerelease && !prereleases) continue;
    const version = parseTag(release.tag_name);
    if (!version) continue;
    if (!best || compareVersion(version, best.version) > 0) best = { version, release };
  }
  return best;
}
export function pickURL(manifest, repo, release, newVersion) {
  const current = manifest.release?.url || '';
  const assets = (release.assets || []).filter(asset => asset && typeof asset.browser_download_url === 'string'
    && typeof asset.name === 'string' && /\.(tar\.gz|tgz)$/.test(asset.name));
  const source = `https://github.com/${repo}/archive/refs/tags/${encodeURIComponent(release.tag_name)}.tar.gz`;
  if (!current) return assets.length === 1 ? assets[0].browser_download_url : source;
  if (ARCHIVE_URL.test(current)) return source;
  const found = ASSET_URL.exec(current);
  if (!found) fail(422, 'The listed archive is not a GitHub release asset or source archive, so this app needs a hand-written update.');
  const wanted = found[2].split(manifest.version).join(newVersion);
  const named = assets.find(asset => asset.name === wanted);
  if (named) return named.browser_download_url;
  if (assets.length === 1) return assets[0].browser_download_url;
  fail(422, `Release ${release.tag_name} has no tar.gz asset named ${wanted}.`);
}
export async function measure(fetcher, url) {
  let hop = releaseURL(url), response;
  for (let i = 0; i < 4; i++) {
    response = await remote(fetcher, hop, {}, MAX, 25000);
    if (![301, 302, 303, 307, 308].includes(response.status)) break;
    const location = response.headers?.get?.('location');
    if (!location || i === 3) fail(422, 'The release archive redirects too many times.');
    hop = releaseURL(new URL(location, hop).href);
  }
  if (response.status !== 200) fail(422, `GitHub answered ${response.status} for the release archive.`);
  const bytes = response.bytes;
  if (bytes.length < 2 || bytes[0] !== 0x1f || bytes[1] !== 0x8b) fail(422, 'That release link did not return a gzip archive.');
  return { url, sha256: await sha256(bytes), size: bytes.length };
}
export const serialize = manifest => JSON.stringify(manifest, null, 2) + '\n';
export function bumped(manifest, version, release, day) {
  return { ...manifest, version, release: { ...(manifest.release || {}), ...release }, updatedAt: day };
}
async function manifestOn(api, id, ref) {
  const found = await api('GET', `/repos/${FARM_REPO}/contents/manifests/${id}.json${ref ? '?ref=' + encodeURIComponent(ref) : ''}`, undefined, [404]);
  if (!found) return null;
  let text;
  try { text = new TextDecoder().decode(Uint8Array.from(atob(found.content.replace(/\s/g, '')), c => c.charCodeAt(0))); }
  catch { fail(502, 'The catalog manifest could not be read.'); }
  try { return { manifest: JSON.parse(text), text, sha: found.sha }; }
  catch { fail(502, 'The catalog manifest could not be read.'); }
}
async function openPullFor(api, branch) {
  for (let page = 1; page <= 5; page++) {
    const pulls = await api('GET', `/repos/${FARM_REPO}/pulls?state=open&per_page=100&page=${page}`);
    if (!Array.isArray(pulls) || !pulls.length) return null;
    const found = pulls.find(pull => pull.head?.ref === branch && (pull.head?.repo?.full_name || FARM_REPO) === FARM_REPO);
    if (found) return found;
    if (pulls.length < 100) return null;
  }
  return null;
}
// One pull request per app: an open one is refreshed in place rather than stacked on.
async function submit(api, id, manifest, base, title, body, message) {
  const branch = BRANCH + id;
  const text = serialize(manifest);
  const content = base64(encoder.encode(text));
  const existing = await openPullFor(api, branch);
  if (existing) {
    const current = await manifestOn(api, id, branch);
    if (current?.text === text) return { prUrl: existing.html_url, opened: false };
    await api('PUT', `/repos/${FARM_REPO}/contents/manifests/${id}.json`,
      { message, branch, content, ...(current ? { sha: current.sha } : {}) });
    await api('PATCH', `/repos/${FARM_REPO}/pulls/${existing.number}`, { title, body });
    return { prUrl: existing.html_url, opened: false };
  }
  const repository = await api('GET', `/repos/${FARM_REPO}`);
  const head = await api('GET', `/repos/${FARM_REPO}/git/ref/heads/${encodeURIComponent(repository.default_branch)}`);
  const created = await api('POST', `/repos/${FARM_REPO}/git/refs`, { ref: 'refs/heads/' + branch, sha: head.object.sha }, [422]);
  if (!created) await api('PATCH', `/repos/${FARM_REPO}/git/refs/heads/${branch}`, { sha: head.object.sha, force: true });
  const onBranch = await manifestOn(api, id, branch);
  await api('PUT', `/repos/${FARM_REPO}/contents/manifests/${id}.json`,
    { message, branch, content, sha: onBranch?.sha || base });
  const pull = await api('POST', `/repos/${FARM_REPO}/pulls`,
    { title, body, head: branch, base: repository.default_branch, maintainer_can_modify: true });
  return { prUrl: pull.html_url, opened: true };
}
function wording(manifest, version, release, repo) {
  return {
    title: `${manifest.name} ${version}`,
    body: `https://github.com/${repo} published v${version} and the catalog still listed ${manifest.version}.\n\n`
      + `url: ${release.url}\nsha256: ${release.sha256}\nsize: ${release.size} bytes\n\n`
      + 'The checksum and the size were measured by downloading that archive here, not read from the '
      + "release notes. Opened by the maker's Check for a new release button.\n",
    message: `${manifest.name} ${version}\n\nRelease url, sha256 and size measured from the published archive.\n\n`
      + 'Confidence: high\nScope-risk: narrow\nTested: Archive downloaded, hashed and sized\n'
      + 'Not-tested: Awaiting CI and maintainer review\n',
  };
}
// The same answers the poller reaches, in the words a maker reads.
export async function checkRelease(ctx, listed) {
  const { env, fetcher, now } = ctx;
  const day = new Date(now()).toISOString().slice(0, 10);
  const said = (status, message, extra = {}) => ({ status, message, checkedAt: now(), version: listed.version, ...extra });
  if (listed.updates === 'manual') return said('manual', 'this app is set to manual updates, so the farm leaves its version alone');
  if (!listed.repo) return said('untracked', 'this app has no GitHub repository in its manifest');
  const repo = repoPath(listed.repo);
  const ready = Boolean(env.FARM_APP_ID && env.FARM_APP_PRIVATE_KEY);
  const api = client(fetcher, ready ? await appToken(env, fetcher, now()) : null);
  // A pull request changes the default branch, so the default branch says what is already listed.
  const source = ready ? await manifestOn(api, listed.id) : null;
  const current = source ? source.manifest : listed;
  // A maker's repository is public and the farm app is not installed on it, so a credential
  // GitHub refuses there is dropped rather than reported as a failure.
  const listing = `/repos/${repo}/releases?per_page=100`;
  const published = await api('GET', listing, undefined, [404]) ?? await client(fetcher, null)('GET', listing);
  const best = pickRelease(published, current.prereleases === true);
  const found = best ? compareVersion(best.version, current.version) : -1;
  if (found < 0) return said('none', `no release newer than v${current.version} on GitHub`, { version: current.version });
  if (found === 0) return said('listed', `already listed at v${current.version}`, { version: current.version });
  if (!source) fail(503, 'Release checks are not switched on yet. A maintainer must add the farm app credentials.');
  const measured = await measure(fetcher, pickURL(current, repo, best.release, best.version));
  const manifest = bumped(current, best.version, measured, day);
  const { title, body, message } = wording(current, best.version, measured, repo);
  const { prUrl } = await submit(api, listed.id, manifest, source.sha, title, body, message);
  return said('found', `v${best.version} found, checks running, a maintainer will review it`,
    { version: best.version, prUrl });
}
export const releaseState = async (get, id) => (await get('release:' + id)) || null;
export async function releaseRoutes(ctx) {
  const { path, request, env, get, put, now, requireUser } = ctx;
  const match = path.match(/^\/api\/seeds\/([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\/release-check$/);
  if (!match) return null;
  if (request.method !== 'POST') fail(405, 'Use POST to check for a new release.');
  const id = match[1];
  const user = await requireUser();
  const response = await env.ASSETS.fetch(new Request(`${ORIGIN}/manifests/${id}.json`));
  if (!response.ok) fail(404, 'That app is not in the catalog.');
  let listed;
  try { listed = await response.json(); } catch { fail(404, 'That app is not in the catalog.'); }
  if (listed?.id !== id) fail(404, 'That app is not in the catalog.');
  if (!await ownsSeed(user, listed, get)) fail(403, 'Only this app’s verified maker can check for a new release.');
  const previous = await get('release:' + id);
  if (previous && now() - previous.checkedAt < MINUTE) {
    const seconds = Math.ceil((MINUTE - (now() - previous.checkedAt)) / 1000);
    const waiting = `checked a moment ago, so try again in ${seconds} seconds`;
    return json({ ...previous, message: waiting, error: waiting }, 429);
  }
  const state = await checkRelease(ctx, listed);
  await put('release:' + id, state);
  return json(state);
}
