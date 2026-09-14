// The maker's "Check for a new release" button on an app page. The farm does the
// comparing and the measuring; this only reports what it answered.
const panel = document.querySelector('[data-seed-release]');
const button = document.getElementById('release-check');
const line = document.getElementById('release-status');
const pull = document.getElementById('release-pr');

if (panel && button && line) {
  button.addEventListener('click', async () => {
    button.disabled = true;
    line.textContent = 'Asking GitHub…';
    try {
      const response = await fetch('/api/seeds/' + encodeURIComponent(panel.dataset.seedRelease) + '/release-check',
        { method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      const result = await response.json();
      line.textContent = result.message || result.error || 'The check could not be completed.';
      if (pull && result.prUrl) { pull.href = result.prUrl; pull.hidden = false; }
    } catch {
      line.textContent = 'Connection interrupted. Please try again.';
    } finally {
      button.disabled = false;
    }
  });
}
