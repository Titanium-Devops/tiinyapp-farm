let pending;

export function refreshSession() {
  if (pending) return pending;
  pending = fetch('/api/me', { credentials: 'same-origin', cache: 'no-store' })
    .then(async response => {
      if (!response.ok) throw new Error('Could not load your account.');
      const { user } = await response.json();
      document.querySelectorAll('[data-farm-nav]').forEach(anchor => {
        anchor.replaceChildren();
        anchor.href = user ? '/account/' : '/submit/#account-panel';
        if (!user) {
          anchor.textContent = 'Sign in';
          return;
        }
        const name = user.tiinyverse?.name || user.github?.name || user.github?.login || user.email?.split('@')[0] || 'Your apps';
        const firstName = name.trim().split(/\s+/)[0];
        const avatar = document.createElement(user.avatarKey ? 'img' : 'span');
        avatar.className = 'nav-avatar';
        if (user.avatarKey) {
          avatar.src = '/' + user.avatarKey;
          avatar.alt = '';
          avatar.width = 24;
          avatar.height = 24;
        } else {
          avatar.textContent = firstName.charAt(0).toUpperCase();
          avatar.setAttribute('aria-hidden', 'true');
        }
        const label = document.createElement('span');
        label.textContent = firstName;
        anchor.append(avatar, label);
      });
      // Parts of an app page only its own maker sees: the update link, the art panel and the release check.
      const mine = [...document.querySelectorAll('[data-seed-update], [data-art-owner], [data-seed-release]')];
      if (mine.length) {
        for (const part of mine) part.hidden = true;
        if (user?.tiinyverse) {
          const response = await fetch('/api/seeds/mine', { credentials: 'same-origin', cache: 'no-store' });
          if (response.ok) {
            const { seeds } = await response.json();
            for (const part of mine) {
              const id = part.dataset.seedUpdate || part.dataset.artOwner || part.dataset.seedRelease;
              part.hidden = !seeds.some(seed => seed.id === id && seed.canUpdate);
            }
          }
        }
      }
      return user;
    }).finally(() => { pending = null; });
  return pending;
}

refreshSession().catch(() => {});
