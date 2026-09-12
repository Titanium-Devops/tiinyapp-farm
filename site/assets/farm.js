import { refreshSession } from './session.js';

const byId = id => document.getElementById(id);
const status = message => { byId('farm-status').textContent = message; };
let currentUser;
async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The farm could not finish that request.');
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
  byId('maker-name').textContent = proof?.name || 'Your maker card';
  byId('maker-handle').textContent = user.handle ? '@' + user.handle : 'Your handle grows after your Tiiny proof.';
  byId('maker-bio').textContent = user.bio || 'Tell the field a little about yourself.';
  byId('bio').value = user.bio || '';
  byId('maker-fields').disabled = !proof;
  byId('maker-proof').textContent = proof ? 'Verified Tiiny owner' : 'Finish your Tiiny proof on the seeds page to edit your maker card.';
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
async function refreshSeeds() {
  const { seeds } = await api('/api/seeds/mine');
  byId('my-seeds').replaceChildren();
  for (const seed of seeds) {
    const card = element('article', ''); card.className = 'plot';
    card.append(element('h3', seed.name), element('p', `v${seed.version} · ${seed.state}`));
    const list = element('ul', '');
    for (const check of seed.checks || []) list.append(element('li', `${check.name}: ${check.status}`));
    const reviews = seed.reviews || [];
    card.append(list, element('p', reviews.length ? 'Review: ' + reviews.join(', ').toLowerCase().replaceAll('_', ' ') : 'No maintainer review yet.'));
    card.append(element('p', `${seed.thumbs || 0} thumbs up · ${seed.comments || 0} comments`));
    if (seed.unavailable) card.append(element('p', 'Live checks are temporarily unavailable. Refresh to try again.'));
    else if (!(seed.checks || []).length) card.append(element('p', 'Checks have not reported yet.'));
    if (seed.labelPending) card.append(element('p', 'Site label pending. Resubmit the same seed form to retry without creating another review.'));
    if (seed.url && (seed.url.startsWith('/apps/') || seed.url.startsWith('https://'))) {
      const anchor = element('a', 'Visit seed page'); anchor.href = seed.url; card.append(anchor);
    }
    if (seed.canUpdate) {
      const update = element('a', 'Update'); update.className = 'btn hay';
      update.href = '/seeds/?update=' + encodeURIComponent(seed.id); card.append(update);
    }
    if (!seed.url) card.append(element('p', 'Your seed page grows here once the seed joins the field.'));
    byId('my-seeds').append(card);
  }
  status(seeds.length ? 'Your seeds are up to date.' : 'No seeds yet. Your first plot is waiting.');
}
async function working(button, action) {
  button.disabled = true;
  status('One moment, tending to that…');
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
    status('Your maker card is saved.');
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
