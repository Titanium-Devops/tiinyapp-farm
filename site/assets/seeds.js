import { refreshSession } from './session.js';
const byId = id => document.getElementById(id);
const status = message => { byId('farm-status').textContent = message; };
let currentUser = null;
let codeEmail = '';
const tabs = [...document.querySelectorAll('.seed-tabs [role=tab]')];
function showStep(index, focus = false) {
  tabs.forEach((tab, position) => {
    const selected = position === index;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    byId(tab.getAttribute('aria-controls')).hidden = !selected;
    if (selected && focus) tab.focus();
  });
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => showStep(index));
  tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    showStep(next, true);
  });
});
async function api(path, data) {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store',
    ...(data === undefined ? {} : { method: 'POST',
      ...(data instanceof FormData ? { body: data } : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }) }) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The farm could not finish that request.');
  return result;
}
async function working(control, action) {
  const button = control.tagName === 'BUTTON' ? control : control.querySelector('button[type=submit]');
  if (button) button.disabled = true;
  status('One moment, tending to that…');
  try { await action(); } catch (error) { status(error.message || 'Connection interrupted. Please try again.'); }
  finally { if (button) button.disabled = false; }
}
function onSubmit(id, handler) {
  byId(id)?.addEventListener('submit', event => { event.preventDefault(); working(event.currentTarget, handler); });
}
function challenge(value) {
  byId('bio-challenge').hidden = !value;
  if (value) { byId('bio-code').textContent = value.code; byId('bio-expiry').textContent = 'Expires ' + new Date(value.expires).toLocaleString(); }
}
async function refreshAccount(step, focus = false) {
  const user = await refreshSession(); currentUser = user;
  if (!byId('account-state')) return;
  const proof = user?.tiinyverse;
  byId('account-state').textContent = user ? `Signed in${user.email ? ' as ' + user.email : ' with GitHub @' + user.github.login}.` : 'Start here. No password to remember.';
  byId('account-state').classList.toggle('done', !!user);
  byId('logout').hidden = !user;
  byId('account-farm').hidden = !user;
  byId('github-signin').hidden = !!user?.github;
  byId('github-signin').textContent = user ? 'Link GitHub to this account' : 'Sign in with GitHub';
  byId('email-start').hidden = !!user?.email;
  byId('email-verify').hidden = !!user?.email;
  byId('proof-fields').disabled = !user || !!proof;
  byId('seed-fields').disabled = !proof;
  byId('proof-state').classList.toggle('done', !!proof);
  byId('seed-state').classList.toggle('done', !!proof);
  byId('proof-state').textContent = proof ? `Verified: ${proof.name}. ` : user ? 'Paste your public TiinyVerse profile below.' : 'First, sign in to your farm account.';
  if (proof) { const anchor = document.createElement('a'); anchor.href = proof.profileUrl; anchor.textContent = 'Your verified profile'; byId('proof-state').append(anchor); }
  byId('seed-state').textContent = proof ? 'Your plot is ready. Tell us about your seed.' : 'Unlocks when your account and Tiiny proof are done.';
  challenge(!proof && user?.tiinyverseChallenge?.expires > Date.now() ? user.tiinyverseChallenge : null);
  tabs.forEach((tab, index) => {
    tab.classList.toggle('done', index === 0 ? !!user : index === 1 && !!proof);
    tab.classList.toggle('locked', index === 1 ? !user : index === 2 && !proof);
  });
  showStep(step ?? (proof ? 2 : user ? 1 : 0), focus);
}
onSubmit('email-start', async () => {
  codeEmail = byId('email').value.trim();
  await api('/api/auth/start', { email: codeEmail });
  status('Your code is on its way. Check your inbox.'); byId('code').focus();
});
onSubmit('email-verify', async () => {
  await api('/api/auth/verify', { email: codeEmail || byId('email').value.trim(), code: byId('code').value });
  byId('code').value = ''; await refreshAccount(1, true); status('Welcome to the farm.');
});
byId('logout')?.addEventListener('click', event => working(event.currentTarget, async () => {
  await api('/api/auth/logout', {}); await refreshAccount(0, true); status('You are signed out.');
}));
onSubmit('tiiny-link', async () => {
  const result = await api('/api/tiinyverse/link', { profileUrl: byId('profileUrl').value.trim() });
  challenge(result); status(result.instruction);
});
byId('tiiny-verify')?.addEventListener('click', event => working(event.currentTarget, async () => {
  await api('/api/tiinyverse/verify', {}); await refreshAccount(2, true); status('Your Tiiny proof is done. Time to plant.');
}));
onSubmit('seed-form', async () => {
  const form = new FormData(byId('seed-form'));
  form.set('permissions', [...byId('permissions').selectedOptions].map(option => option.value).join(','));
  if (!!byId('releaseUrl').value.trim() === !!byId('archive').files.length) throw new Error('Choose either a release URL or one tar.gz upload.');
  if (byId('archive').files[0]?.size > 50 * 1024 * 1024) throw new Error('Choose an archive no larger than 50 MB.');
  const gallery = [...byId('seed-gallery').files];
  if (gallery.length > 8) throw new Error('Choose up to eight gallery images.');
  const groups = { icon: [...byId('seed-icon').files], header: [...byId('seed-header').files], gallery };
  for (const file of Object.values(groups).flat()) {
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) throw new Error('Choose PNG, JPEG or WebP images no larger than 2 MiB each.');
  }
  const media = {};
  for (const [kind, files] of Object.entries(groups)) {
    const urls = [];
    for (const file of files) {
      status('Uploading your seed images…');
      const response = await fetch('/api/media', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': file.type }, body: file });
      const uploaded = await response.json();
      if (!response.ok) throw new Error(uploaded.error || 'Could not upload your seed image.');
      urls.push(uploaded.url);
    }
    if (urls.length) media[kind] = kind === 'gallery' ? urls : urls[0];
  }
  form.set('media', JSON.stringify(media));
  status('Sending your seed to the farmhands…');
  const result = await api('/api/seeds', form);
  if (result.warning) { status(result.warning); return; }
  window.location.assign(result.statusUrl);
});
refreshAccount().catch(error => status(error.message));
