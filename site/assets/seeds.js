import { refreshSession } from './session.js';
const byId = id => document.getElementById(id);
const status = message => { byId('farm-status').textContent = message; };
let currentUser = null;
let codeEmail = '';
const updateId = new URLSearchParams(window.location.search).get('update');
let originalSeed = null;
let originalCommand = '';
async function prefillSeed() {
  if (!updateId || originalSeed || !currentUser?.tiinyverse) return;
  byId('seed-fields').disabled = true;
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(updateId)) throw new Error('Invalid app ID.');
  const { seeds } = await api('/api/seeds/mine');
  if (!seeds.some(seed => seed.id === updateId && seed.canUpdate)) throw new Error('Only the maker can update this app.');
  const seed = await api('/manifests/' + encodeURIComponent(updateId) + '.json');
  const form = byId('seed-form');
  const values = {
    id: seed.id, name: seed.name, pitch: seed.pitch, description: seed.description,
    version: seed.version, license: seed.license, homepage: seed.links?.homepage ?? seed.homepage,
    repo: seed.links?.repo ?? seed.repo, video: seed.links?.video,
    command: seed.entry?.command ?? (seed.entry?.python ? 'python -m ' + seed.entry.python + ' ' + seed.entry.args.map(arg => JSON.stringify(arg)).join(' ') : ''),
    python: seed.requires.python, ports: seed.requires.ports.join(','),
    models: seed.requires.device.models.join(','), npuUnits: seed.requires.device.npuUnits,
    tags: seed.tags.join(','), health: seed.health,
  };
  for (const [key, value] of Object.entries(values)) form.elements.namedItem(key).value = value ?? '';
  form.elements.namedItem('id').readOnly = true;
  form.elements.namedItem('selfcheck').checked = !!seed.selfcheck;
  for (const option of byId('permissions').options) option.selected = seed.permissions.includes(option.value);
  originalCommand = values.command;
  originalSeed = seed;
  byId('release-heading').textContent = seed.release ? 'Replace your release (optional)' : 'Add your first release';
  byId('release-help').textContent = seed.release ? 'Leave these fields empty to keep the current release. A replacement needs a higher version.' : 'Leave these fields empty to submit without a release.';
  byId('seed-state').textContent = 'Updating ' + seed.name + '. Existing images stay unless you upload replacements.';
  byId('seed-fields').disabled = false;
  showStep(2);
}
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
async function api(path, data, method = 'POST') {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store',
    ...(data === undefined ? {} : { method,
      ...(data instanceof FormData ? { body: data } : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }) }) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request could not be completed.');
  return result;
}
async function working(control, action) {
  const button = control.tagName === 'BUTTON' ? control : control.querySelector('button[type=submit]');
  if (button) button.disabled = true;
  status('Saving…');
  const under = control.id === 'seed-form' ? byId('seed-error') : null;
  if (under) { under.hidden = true; under.textContent = ''; }
  try { await action(); } catch (error) { const text = error.message || 'Connection interrupted. Please try again.'; status(text); if (under) { under.textContent = text; under.hidden = false; markField(text); under.scrollIntoView({ block: 'nearest' }); } }
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
  byId('account-state').textContent = user ? `Signed in${user.email ? ' as ' + user.email : ' with GitHub @' + user.github.login}.` : 'Sign in with an email code or GitHub.';
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
  byId('proof-state').textContent = proof ? `Verified: ${proof.name}. ` : user ? 'Paste your public TiinyVerse profile below.' : 'First, sign in to your account.';
  if (proof) { const anchor = document.createElement('a'); anchor.href = proof.profileUrl; anchor.textContent = 'Your verified profile'; byId('proof-state').append(anchor); }
  byId('seed-state').textContent = proof ? 'Enter your app details below.' : 'Sign in and verify you own a Tiiny to submit an app.';
  challenge(!proof && user?.tiinyverseChallenge?.expires > Date.now() ? user.tiinyverseChallenge : null);
  tabs.forEach((tab, index) => {
    tab.classList.toggle('done', index === 0 ? !!user : index === 1 && !!proof);
    tab.classList.toggle('locked', index === 1 ? !user : index === 2 && !proof);
  });
  showStep(step ?? (proof ? 2 : user ? 1 : 0), focus);
  await prefillSeed();
}
onSubmit('email-start', async () => {
  codeEmail = byId('email').value.trim();
  await api('/api/auth/start', { email: codeEmail });
  status('Check your email for the sign-in code.'); byId('code').focus();
});
onSubmit('email-verify', async () => {
  await api('/api/auth/verify', { email: codeEmail || byId('email').value.trim(), code: byId('code').value });
  byId('code').value = ''; await refreshAccount(1, true); status('You are signed in.');
});
byId('logout')?.addEventListener('click', event => working(event.currentTarget, async () => {
  await api('/api/auth/logout', {}); await refreshAccount(0, true); status('You are signed out.');
}));
onSubmit('tiiny-link', async () => {
  const result = await api('/api/tiinyverse/link', { profileUrl: byId('profileUrl').value.trim() });
  challenge(result); status(result.instruction);
});
byId('tiiny-verify')?.addEventListener('click', event => working(event.currentTarget, async () => {
  await api('/api/tiinyverse/verify', {}); await refreshAccount(2, true); status('Your TiinyVerse profile is verified. You can submit your app.');
}));
onSubmit('seed-form', async () => {
  clearMarks();
  if (updateId && !originalSeed) throw new Error('Load your app before updating it.');
  const form = new FormData(byId('seed-form'));
  if (originalSeed) {
    form.set('screenshots', JSON.stringify(originalSeed.screenshots));
    if (byId('command').value === originalCommand) {
      form.set('entry', JSON.stringify(originalSeed.entry));
      form.delete('command');
    }
  }
  form.set('permissions', [...byId('permissions').selectedOptions].map(option => option.value).join(','));
  if (byId('releaseUrl').value.trim() && byId('archive').files.length) throw new Error('Choose either a release URL or one tar.gz upload.');
  if (byId('archive').files[0]?.size > 50 * 1024 * 1024) throw new Error('Choose an archive no larger than 50 MB.');
  const gallery = [...byId('seed-gallery').files];
  if (gallery.length > 8) throw new Error('Choose up to eight gallery images.');
  const groups = { icon: [...byId('seed-icon').files], header: [...byId('seed-header').files], gallery };
  for (const file of Object.values(groups).flat()) {
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) throw new Error('Choose PNG, JPEG or WebP images no larger than 2 MiB each.');
  }
  const media = { ...originalSeed?.media };
  for (const [kind, files] of Object.entries(groups)) {
    const urls = [];
    for (const file of files) {
      status('Uploading your app images…');
      const response = await fetch('/api/media', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': file.type }, body: file });
      const uploaded = await response.json();
      if (!response.ok) throw new Error(uploaded.error || 'Could not upload your app image.');
      urls.push(uploaded.url);
    }
    if (urls.length) media[kind] = kind === 'gallery' ? urls : urls[0];
  }
  form.set('media', JSON.stringify(media));
  status('Submitting your app for maintainer review…');
  const result = await api(updateId ? '/api/seeds/' + encodeURIComponent(updateId) : '/api/seeds', form, updateId ? 'PUT' : 'POST');
  if (result.warning) { status(result.warning); return; }
  try { localStorage.removeItem(DRAFT); } catch {}
  window.location.assign(result.statusUrl);
});
refreshAccount().catch(error => status(error.message));

// The server names the field in its message ("tags: must not be empty", "A null entry requires the library tag").
const FIELD_WORDS = { entry: 'command', tags: 'tags', version: 'version', license: 'license', id: 'id', name: 'name', description: 'description', release: 'releaseUrl', ports: 'ports', python: 'python' };
function clearMarks() {
  for (const input of document.querySelectorAll('#seed-form [aria-invalid]')) input.removeAttribute('aria-invalid');
  for (const note of document.querySelectorAll('#seed-form .field-error')) note.remove();
}
function flag(input, text) {
  input.setAttribute('aria-invalid', 'true');
  const note = document.createElement('p'); note.className = 'field-error'; note.textContent = text;
  (input.closest('.seed-field') || input.parentElement).append(note);
}
function markField(text) {
  clearMarks();
  const word = Object.keys(FIELD_WORDS).find(key => new RegExp('\\b' + key + '\\b', 'i').test(text));
  const input = word && byId(FIELD_WORDS[word]);
  if (input) { flag(input, text); input.scrollIntoView({ block: 'center' }); input.focus({ preventScroll: true }); }
}
// Browser validation: mark every empty required field and say so under it, then jump to the first.
const seedForm = byId('seed-form');
if (seedForm) {
  seedForm.addEventListener('invalid', event => {
    const input = event.target; event.preventDefault();
    if (!input.hasAttribute('aria-invalid')) flag(input, input.validity.valueMissing ? 'This field is required.' : (input.validationMessage || 'Check this value.'));
    const first = seedForm.querySelector('[aria-invalid]'); if (first === input) { input.scrollIntoView({ block: 'center' }); input.focus({ preventScroll: true }); }
  }, true);
}
// A draft of the seed form survives reloads and failed sends. ponytail: localStorage, one key, no expiry.
const DRAFT = 'farm-seed-draft';
const draftForm = byId('seed-form');
if (draftForm) {
  try {
    const saved = JSON.parse(localStorage.getItem(DRAFT) || '{}');
    for (const [name, value] of Object.entries(saved)) { const el = draftForm.elements[name]; if (el && el.type !== 'file' && !el.value) el.value = value; }
  } catch {}
  draftForm.addEventListener('input', event => {
    const input = event?.target; if (input?.hasAttribute?.('aria-invalid') && input.checkValidity?.()) { input.removeAttribute('aria-invalid'); input.closest?.('.seed-field')?.querySelector('.field-error')?.remove(); }
    const data = {}; for (const el of draftForm.elements) if (el.name && el.type !== 'file' && el.type !== 'submit') data[el.name] = el.value;
    try { localStorage.setItem(DRAFT, JSON.stringify(data)); } catch {}
  });
}
