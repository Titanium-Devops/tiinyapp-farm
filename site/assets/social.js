import { refreshSession } from './session.js';

const node = (tag, text = '') => {
  const result = document.createElement(tag);
  result.textContent = text;
  return result;
};

export function commentCard(comment, remove) {
  const card = node('article'); card.className = 'seed-comment';
  const author = comment.author || {};
  const heading = node('div'); heading.className = 'comment-author';
  if (author.avatar && (author.avatar.startsWith('/media/') || author.avatar.startsWith('https://'))) {
    const avatar = node('img'); avatar.src = author.avatar; avatar.alt = '';
    avatar.width = 40; avatar.height = 40; avatar.loading = 'lazy';
    heading.append(avatar);
  }
  const name = node(author.handle ? 'a' : 'span', author.name || 'A maker');
  if (author.handle) name.href = '/makers/' + encodeURIComponent(author.handle) + '/';
  heading.append(name);
  const at = new Date(comment.at);
  if (!Number.isNaN(at.getTime())) {
    const time = node('time', at.toLocaleString()); time.dateTime = at.toISOString();
    heading.append(time);
  }
  const body = node('p', comment.text); body.className = 'comment-text';
  card.append(heading, body);
  if (comment.canDelete) {
    const button = node('button', 'Delete comment'); button.type = 'button'; button.className = 'btn ghost';
    button.addEventListener('click', () => remove(comment.id, button)); card.append(button);
  }
  return card;
}

const root = document.querySelector('[data-seed-social]');
if (root) {
  const byId = id => document.getElementById(id);
  const endpoint = '/api/seeds/' + encodeURIComponent(root.dataset.seedSocial);
  const status = message => { byId('social-status').textContent = message; };
  let user = null;
  let busy = false;
  async function request(path, options = {}) {
    const response = await fetch(endpoint + path, { credentials: 'same-origin', cache: 'no-store', ...options });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The request could not be completed.');
    return data;
  }
  const post = data => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  async function refresh() {
    const social = await request('/social');
    byId('thumb-count').textContent = String(social.thumbs);
    byId('seed-thumb').setAttribute('aria-pressed', String(social.mine));
    const comments = byId('seed-comments'); comments.replaceChildren();
    for (const comment of social.comments) comments.append(commentCard(comment, remove));
    if (!social.comments.length) comments.append(node('p', 'No comments yet.'));
  }
  function controls() {
    byId('seed-thumb').disabled = busy || !user;
    byId('comment-submit').disabled = busy || !user?.tiinyverse;
    root.querySelectorAll('.seed-comment button').forEach(button => { button.disabled = busy; });
  }
  async function mutate(action, success) {
    if (busy) return;
    busy = true; controls(); status('Saving…');
    let saved = false;
    try {
      await action(); saved = true;
      await refresh(); status(success);
    } catch (error) {
      status((saved ? 'Saved, but the latest counts could not load. Refresh the page. ' : '') + (error.message || 'Connection interrupted. Please try again.'));
    } finally { busy = false; controls(); }
  }
  function remove(id) {
    return mutate(() => request('/comments/' + encodeURIComponent(id), { method: 'DELETE' }), 'Comment removed.');
  }
  byId('seed-thumb').addEventListener('click', () => mutate(() => request('/thumb', post({})), 'Your thumbs up is saved.'));
  byId('comment-form').addEventListener('submit', event => {
    event.preventDefault();
    const text = byId('comment-text').value.trim();
    if (!text || text.length > 1000) { status('Write a comment between 1 and 1,000 characters.'); return; }
    mutate(async () => {
      await request('/comments', post({ text }));
      byId('comment-text').value = '';
    }, 'Your comment is posted.');
  });
  (async () => {
    let sessionError = false;
    try { user = await refreshSession(); } catch { sessionError = true; }
    byId('comment-form').hidden = !user?.tiinyverse;
    byId('social-signin').hidden = !!user?.tiinyverse;
    if (user && !user.tiinyverse) byId('social-signin').querySelector('a').textContent = 'Verify you own a Tiiny on Submit an app to leave a comment.';
    await refresh(); controls();
    status(sessionError ? 'Comments loaded. Your sign-in could not be checked; refresh to try again.' : '');
  })().catch(error => status(error.message || 'Comments could not load. Refresh to try again.'));
}
