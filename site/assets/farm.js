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
  byId('maker-proof').replaceChildren();
  if (proof) { const chip = element('span', 'Verified Tiiny owner'); chip.className = 'chip ok'; byId('maker-proof').append(chip); }
  else byId('maker-proof').textContent = 'Verify you own a Tiiny on Submit an app to edit your profile.';
  byId('maker-avatar').hidden = false;
  if (user.avatarKey) byId('maker-avatar').src = '/' + user.avatarKey;
  else byId('maker-avatar').src = '/brand/tiinyapp-farm-square-logo.png';
  byId('remove-avatar').hidden = !user.avatarKey;
  byId('public-maker').hidden = !proof || !user.handle;
  if (proof && user.handle) byId('public-maker').href = '/makers/' + encodeURIComponent(user.handle) + '/';
  byId('maker-links').replaceChildren();
  for (const [key, title] of [['github', 'GitHub'], ['website', 'Website'], ['youtube', 'YouTube']]) {
    const url = user.links?.[key] || '';
    byId(key).value = url;
    if (url.startsWith('https://')) {
      const anchor = element('a', title); anchor.href = url; anchor.className = 'chip';
      byId('maker-links').append(anchor);
    }
  }
  const visibility = user.public !== false;
  byId('profile-visibility').setAttribute('aria-checked', String(visibility));
  updateVisibilityText(visibility);
  byId('signed-in-with').textContent = [user.email && 'email', user.github && 'GitHub'].filter(Boolean).join(' · ') || 'account';
  byId('create-token').disabled = !proof;
}
function updateVisibilityText(visible) {
  const handle = currentUser?.handle || 'your-handle';
  byId('visibility-text').textContent = visible
    ? `Anyone can open tiinyapp.farm/makers/${handle} and see your apps, bio and links. Your email is never shown.`
    : 'Only signed-in farm members can open your maker page. Your apps stay in the catalog with your name; the link on them asks visitors to sign in.';
}
// Keep stored API states stable while presenting the current review status.
function appStatus(app) {
  if (['merged', 'published', 'sprouting'].includes(app.state)) return 'Published';
  if (app.state === 'closed') return 'Closed';
  if (app.state === 'submission failed') return 'App submission failed';
  if (app.state === 'submission uncertain') return 'App submission needs maintainer assistance';
  const checks = app.checks || [];
  const failed = checks.filter(check => ['failure', 'error', 'timed_out', 'cancelled', 'action_required', 'startup_failure', 'stale'].includes(check.status));
  if (failed.length) return 'Checks failed: ' + failed.map(check => `${check.name} (${check.status.replaceAll('_', ' ')})`).join(', ');
  if (app.unavailable) return 'Check status unavailable';
  if (!checks.length || checks.some(check => !['success', 'neutral', 'skipped'].includes(check.status))) return 'Checks running';
  return 'Waiting for review';
}

async function refreshSeeds() {
  const { seeds } = await api('/api/seeds/mine');
  byId('my-seeds').replaceChildren();
  for (const seed of seeds) {
    const card = element('article', ''); card.className = 'my';
    const icon = document.createElement('img'); icon.src = seed.icon || '/brand/tiinyapp-farm-square-logo.png'; icon.alt = '';
    const copy = document.createElement('div'), name = element('div', seed.name), meta = document.createElement('div');
    name.className = 'n'; meta.className = 'm'; meta.append(element('span', `v${seed.version}`));
    const state = appStatus(seed), stateNode = element('b', state); stateNode.className = state.startsWith('Checks failed') ? 'bad' : state === 'Checks running' ? 'wait' : '';
    meta.append(stateNode);
    if (['merged', 'published', 'sprouting'].includes(seed.state)) meta.append(element('span', `${seed.thumbs || 0} thumbs · ${seed.comments || 0} comments`));
    copy.append(name, meta); const actions = document.createElement('div'); actions.className = 'act';
    const addAction = (label, href) => { const anchor = element('a', label); anchor.className = 'btn ghost'; anchor.href = href; actions.append(anchor); };
    if (state.startsWith('Checks failed')) { if (seed.prUrl) addAction('See why', seed.prUrl); addAction('Fix and resubmit', '/submit/?update=' + encodeURIComponent(seed.id)); }
    else {
      if (seed.canUpdate) addAction('Update', '/submit/?update=' + encodeURIComponent(seed.id));
      if (seed.url && (seed.url.startsWith('/apps/') || seed.url.startsWith('https://'))) addAction('View', seed.url);
      else if (seed.prUrl) addAction('Details', seed.prUrl);
    }
    card.append(icon, copy, actions);
    byId('my-seeds').append(card);
  }
  status(seeds.length ? 'Your apps are up to date.' : 'No apps yet. Use Submit an app to add one.');
}
const tokenDate = value => value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value)) : 'Never';
async function refreshTokens() {
  const { tokens = [] } = await api('/api/tokens');
  byId('api-tokens').replaceChildren();
  for (const token of tokens) {
    const row = document.createElement('article'); row.className = 'token-row';
    const copy = document.createElement('div');
    const name = element('div', token.name); name.className = 'token-name';
    const created = token.created || token.createdAt;
    const lastUsed = token.lastUsed || token.lastUsedAt;
    const meta = element('div', `${token.prefix} · Created ${tokenDate(created)} · Last used ${tokenDate(lastUsed)}`); meta.className = 'token-meta';
    copy.append(name, meta);
    const revoke = element('button', 'Revoke'); revoke.type = 'button'; revoke.className = 'btn ghost';
    revoke.addEventListener('click', async () => {
      revoke.disabled = true; byId('token-status').textContent = 'Revoking token…';
      try { await api('/api/tokens/' + encodeURIComponent(token.id), { method: 'DELETE' }); await refreshTokens(); byId('token-status').textContent = 'Token revoked.'; }
      catch (error) { revoke.disabled = false; byId('token-status').textContent = error.message; }
    });
    row.append(copy, revoke); byId('api-tokens').append(row);
  }
  byId('token-status').textContent = tokens.length ? `${tokens.length} of 5 tokens.` : 'No API tokens yet.';
}
async function working(button, action) {
  button.disabled = true;
  status('Saving…');
  try { await action(); } catch (error) { status(error.message || 'Connection interrupted. Please try again.'); }
  finally { button.disabled = false; }
}
byId('edit-profile').addEventListener('click', () => {
  const form = byId('maker-form');
  form.hidden = !form.hidden;
  byId('edit-profile').textContent = form.hidden ? 'Edit profile' : 'Cancel';
  byId('edit-profile').setAttribute('aria-expanded', String(!form.hidden));
  if (!form.hidden) byId('bio').focus();
});
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
    byId('maker-form').hidden = true;
    byId('edit-profile').textContent = 'Edit profile';
    byId('edit-profile').setAttribute('aria-expanded', 'false');
    status('Your profile is saved.');
  });
});
byId('remove-avatar').addEventListener('click', event => working(event.currentTarget, async () => {
  await api('/api/media/' + currentUser.avatarKey.replace(/^media\//, ''), { method: 'DELETE' });
  renderMaker(await refreshSession());
  status('Your icon has been removed.');
}));
byId('refresh-seeds').addEventListener('click', event => working(event.currentTarget, refreshSeeds));
byId('create-token').addEventListener('click', () => {
  const form = byId('token-form'); form.hidden = !form.hidden;
  byId('create-token').textContent = form.hidden ? 'Create a token' : 'Cancel';
  if (!form.hidden) byId('token-name').focus();
});
byId('token-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  byId('token-status').textContent = 'Creating token…';
  try {
    const result = await api('/api/tokens', post({ name: byId('token-name').value.trim() }));
    byId('new-token').textContent = result.token;
    byId('token-reveal').hidden = false; byId('token-form').hidden = true;
    byId('create-token').textContent = 'Create a token'; byId('token-name').value = '';
    await refreshTokens(); byId('token-status').textContent = 'Token created. Copy it before leaving this page.';
  } catch (error) { byId('token-status').textContent = error.message; }
  finally { button.disabled = false; }
});
byId('copy-token').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(byId('new-token').textContent); byId('token-status').textContent = 'Token copied.'; }
  catch { byId('token-status').textContent = 'Copy failed. Select the token and copy it manually.'; }
});
byId('profile-visibility').addEventListener('click', event => working(event.currentTarget, async () => {
  const visible = event.currentTarget.getAttribute('aria-checked') !== 'true';
  await api('/api/maker/visibility', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ public: visible }) });
  currentUser.public = visible; event.currentTarget.setAttribute('aria-checked', String(visible)); updateVisibilityText(visible);
  status(visible ? 'Your maker page is public.' : 'Your maker page is for signed-in members.');
}));
byId('account-logout').addEventListener('click', event => working(event.currentTarget, async () => {
  await api('/api/auth/logout', post({})); window.location.replace('/submit/#account-panel');
}));
(async () => {
  const user = await refreshSession();
  if (!user) { window.location.replace('/submit/#account-panel'); return; }
  renderMaker(user);
  await Promise.all([refreshSeeds(), refreshTokens()]);
})().catch(error => status(error.message));
