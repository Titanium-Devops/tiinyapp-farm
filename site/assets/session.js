let pending;

export function refreshSession() {
  if (pending) return pending;
  pending = fetch('/api/me', { credentials: 'same-origin', cache: 'no-store' })
    .then(async response => {
      if (!response.ok) throw new Error('Could not load your account.');
      const { user } = await response.json();
      document.querySelectorAll('[data-farm-nav]').forEach(anchor => {
        anchor.textContent = 'Your apps';
        anchor.href = '/farm/';
      });
      const update = document.querySelector('[data-seed-update]');
      if (update) {
        update.hidden = true;
        if (user?.tiinyverse) {
          const response = await fetch('/api/seeds/mine', { credentials: 'same-origin', cache: 'no-store' });
          if (response.ok) {
            const { seeds } = await response.json();
            update.hidden = !seeds.some(seed => seed.id === update.dataset.seedUpdate && seed.canUpdate);
          }
        }
      }
      return user;
    }).finally(() => { pending = null; });
  return pending;
}

refreshSession().catch(() => {});
