import { refreshSession } from './session.js';

const byId = id => document.getElementById(id);
const status = message => { byId('farm-status').textContent = message; };
let currentUser;
async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request could not be completed.');
  return result;
}
const post = data => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
function element(tag, text) {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
}
function renderMaker(user) {
  currentUser = user;
  const proof = user.tiinyverse;
  byId('maker-name').textContent = proof?.name || 'Your profile';
  byId('maker-handle').textContent = user.handle ? '@' + user.handle : 'Your handle is assigned after you verify your TiinyVerse profile.';
  byId('maker-bio').textContent = user.bio || 'Add a bio to your public profile.';
  byId('bio').value = user.bio || '';
  byId('maker-fields').disabled = !proof;
  byId('maker-proof').textContent = proof ? 'Verified Tiiny owner' : 'Verify you own a Tiiny on Submit an app to edit your profile.';
  byId('maker-avatar').hidden = !user.avatarKey;
  if (user.avatarKey) byId('maker-avatar').src = '/' + user.avatarKey;
  else byId('maker-avatar').removeAttribute('src');
  byId('remove-avatar').hidden = !user.avatarKey;
  byId('public-maker').hidden = !proof || !user.handle;
  if (proof && user.handle) byId('public-maker').href = '/makers/' + encodeURIComponent(user.handle) + '/';
  byId('maker-links').replaceChildren();
  for (const [key, title] of [['github', 'GitHub'], ['website', 'Website'], ['youtube', 'YouTube']]) {
    const url = user.links?.[key] || '';
    byId(key).value = url;
    if (url.startsWith('https://')) {
      const anchor = element('a', title); anchor.href = url;
      byId('maker-links').append(anchor);
    }
  }
}
// Keep stored API states stable while presenting the current review status.
function appStatus(app) {
  if (['merged', 'published', 'sprouting'].includes(app.state)) return 'In the catalog';
  if (app.state === 'closed') return 'Closed without merging';
  if (app.state === 'submission failed') return 'App submission failed';
  if (app.state === 'submission uncertain') return 'App submission needs maintainer assistance';
  const checks = app.checks || [];
  const failed = checks.filter(check => ['failure', 'error', 'timed_out', 'cancelled', 'action_required', 'startup_failure', 'stale'].includes(check.status));
  if (failed.length) return 'Checks failed: ' + failed.map(check => `${check.name} (${check.status.replaceAll('_', ' ')})`).join(', ');
  if (app.unavailable) return 'Check status unavailable';
  if (!checks.length || checks.some(check => !['success', 'neutral', 'skipped'].includes(check.status))) return 'Checks running';
  return 'Waiting for a maintainer';
}

async function refreshSeeds() {
  const { seeds } = await api('/api/seeds/mine');
  byId('my-seeds').replaceChildren();
  for (const seed of seeds) {
    const card = element('article', ''); card.className = 'plot';
    card.append(element('h3', seed.name), element('p', `v${seed.version} · ${appStatus(seed)}`));
    if (seed.state === 'sprouting') card.append(element('p', 'No release yet'));
    const list = element('ul', '');
    for (const check of seed.checks || []) list.append(element('li', `${check.name}: ${check.status}`));
    const reviews = seed.reviews || [];
    card.append(list, element('p', reviews.length ? 'Review: ' + reviews.join(', ').toLowerCase().replaceAll('_', ' ') : 'No maintainer review yet.'));
    card.append(element('p', `${seed.thumbs || 0} thumbs up · ${seed.comments || 0} comments`));
    if (seed.unavailable) card.append(element('p', 'Live checks are temporarily unavailable. Refresh to try again.'));
    else if (!(seed.checks || []).length && !['merged', 'published', 'sprouting'].includes(seed.state)) card.append(element('p', 'Checks have not reported yet.'));
    if (seed.labelPending) card.append(element('p', 'Site label pending. Resubmit the same app form to retry without creating another review.'));
    if (seed.url && (seed.url.startsWith('/apps/') || seed.url.startsWith('https://'))) {
      const anchor = element('a', 'View app'); anchor.href = seed.url; card.append(anchor);
    }
    if (seed.canUpdate) {
      const update = element('a', 'Update'); update.className = 'btn hay';
      update.href = '/seeds/?update=' + encodeURIComponent(seed.id); card.append(update);
    }
    if (!seed.url) card.append(element('p', 'Your app page is available after the pull request is merged.'));
    byId('my-seeds').append(card);
  }
  status(seeds.length ? 'Your apps are up to date.' : 'No apps yet. Use Submit an app to add one.');
}
async function working(button, action) {
  button.disabled = true;
  status('Saving…');
  try { await action(); } catch (error) { status(error.message || 'Connection interrupted. Please try again.'); }
  finally { button.disabled = false; }
}
byId('maker-form').addEventListener('submit', event => {
  event.preventDefault();
  working(event.submitter || byId('maker-form').querySelector('[type=submit]'), async () => {
    const links = {};
    for (const key of ['github', 'website', 'youtube']) {
      const url = byId(key).value.trim();
      if (url) {
        if (new URL(url).protocol !== 'https:') throw new Error('Maker links must use HTTPS.');
        links[key] = url;
      }
    }
    const bio = byId('bio').value;
    let avatarKey = currentUser.avatarKey;
    const file = byId('avatar').files[0];
    if (file) {
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) throw new Error('Choose a PNG, JPEG or WebP no larger than 2 MiB.');
      const uploaded = await api('/api/media', { method: 'POST', headers: { 'Content-Type': file.type }, body: file });
      avatarKey = uploaded.key;
    }
    await api('/api/maker', post({ bio, avatarKey, links }));
    byId('avatar').value = '';
    renderMaker(await refreshSession());
    status('Your profile is saved.');
  });
});
byId('remove-avatar').addEventListener('click', event => working(event.currentTarget, async () => {
  await api('/api/media/' + currentUser.avatarKey.replace(/^media\//, ''), { method: 'DELETE' });
  renderMaker(await refreshSession());
  status('Your icon has been removed.');
}));
byId('refresh-seeds').addEventListener('click', event => working(event.currentTarget, refreshSeeds));
(async () => {
  const user = await refreshSession();
  if (!user) { window.location.replace('/seeds/'); return; }
  renderMaker(user);
  await refreshSeeds();
})().catch(error => status(error.message));
