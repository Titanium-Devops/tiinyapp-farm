// Generate art. One panel, two surfaces: the submit form, where the pair is staged into the form
// the maker is filling in, and a maker's own app page, where Use these carries the pair to the
// update form, because a published app's images move through the same pull request as everything
// else. The style itself lives in the Worker; this only asks for it and shows what came back.
const byId = id => document.getElementById(id);
const panel = document.querySelector('[data-art-panel]');

if (panel) {
  const onAppPage = !!panel.dataset.artOwner;
  const scene = byId('scene');
  const state = byId('art-state');
  const result = byId('art-result');
  const staged = byId('art-media');
  let drawn = null;

  const say = message => { if (state) state.textContent = message; };
  const appId = () => (panel.dataset.artOwner || byId('seed-id')?.value || '').trim();

  function show(art) {
    drawn = art && art.icon && art.header ? art : null;
    if (!drawn) { result.hidden = true; return; }
    byId('art-header').src = drawn.header;
    byId('art-icon').src = drawn.icon;
    result.hidden = false;
  }

  async function ask(path, body) {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store',
      ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || 'The farm could not draw this. Please try again.');
    return payload;
  }

  const left = remaining => remaining === undefined ? ''
    : ` ${remaining} drawing${remaining === 1 ? '' : 's'} left today.`;

  async function generate(button) {
    const id = appId();
    if (!/^[a-z][a-z0-9]*(-[a-z0-9]+)*$/.test(id)) { say('Fill in the app ID first. That is where the art is filed.'); return; }
    if (!scene.value.trim()) { say("Write one sentence saying what is in the picture."); scene.focus(); return; }
    button.disabled = true;
    say('Drawing. This takes a minute or two, so leave this page open.');
    try {
      const art = await ask('/api/seeds/' + encodeURIComponent(id) + '/art', { scene: scene.value });
      show(art);
      say('Here is what the farm drew.' + left(art.remaining));
    } catch (error) {
      show(null);
      say(error.message);
    } finally { button.disabled = false; }
  }

  // On the form, keeping the pair means filling in the media the submission will carry. The card
  // preview beside the form is the same two images, so it updates with them.
  function keep() {
    if (!drawn) return;
    if (onAppPage) {
      window.location.assign('/submit/?update=' + encodeURIComponent(panel.dataset.artOwner) + '&art=use');
      return;
    }
    staged.value = JSON.stringify({ icon: drawn.icon, header: drawn.header });
    const icon = byId('preview-icon');
    if (icon) icon.src = drawn.icon;
    const art = byId('preview-art');
    if (art) { art.style.backgroundImage = `url("${drawn.header}")`; const label = byId('preview-art-label'); if (label) label.hidden = true; }
    say('Kept. These go with your app when you submit it.');
  }

  byId('art-generate')?.addEventListener('click', event => generate(event.currentTarget));
  byId('art-again')?.addEventListener('click', event => generate(event.currentTarget));
  byId('art-use')?.addEventListener('click', keep);

  // What the app already has: the scene last used and the pair it produced.
  async function restore() {
    const id = appId();
    if (!/^[a-z][a-z0-9]*(-[a-z0-9]+)*$/.test(id)) return;
    try {
      const art = await ask('/api/seeds/' + encodeURIComponent(id) + '/art');
      if (art.scene && !scene.value.trim()) scene.value = art.scene;
      show(art);
      if (art.icon) say('The last art the farm drew for this app.' + left(art.remaining));
      else if (art.remaining !== undefined) say(`Three drawings a day for one app.${left(art.remaining)}`);
      return art;
    } catch { /* Signed out, or an app that has never been drawn. Nothing to restore. */ }
  }

  if (onAppPage) {
    // The panel is revealed by session.js once the farm says this maker owns the app.
    new MutationObserver((records, observer) => {
      if (panel.hidden) return;
      observer.disconnect();
      restore();
    }).observe(panel, { attributes: true, attributeFilter: ['hidden'] });
  } else {
    const query = new URLSearchParams(window.location.search);
    if (query.get('update')) restore().then(art => { if (query.get('art') === 'use' && art?.icon) keep(); });
  }
}
