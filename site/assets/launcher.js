// Every download is a real link in the markup, so the panel works with JavaScript switched off.
// This adds the one thing a static page cannot know: which of the rows is for the computer
// reading it. The recommendation starts hidden, so nothing is claimed until we know.
async function thisComputer() {
  const hints = navigator.userAgentData;
  if (hints) {
    const platform = hints.platform || '';
    if (/windows/i.test(platform)) return 'windows';
    if (/android/i.test(platform)) return '';
    if (/linux|cros/i.test(platform)) return 'linux';
    if (/mac/i.test(platform)) {
      // Safari tells nobody which Mac this is, so only ask where the answer exists.
      let architecture = '';
      try {
        ({ architecture } = await hints.getHighEntropyValues(['architecture']));
      } catch { architecture = ''; }
      return architecture === 'x86' ? 'mac-intel' : 'mac';
    }
    return '';
  }
  const platform = navigator.platform || navigator.userAgent || '';
  if (/windows|win32|win64/i.test(platform)) return 'windows';
  if (/android/i.test(platform)) return '';
  if (/linux|x11|ubuntu|fedora|cros/i.test(platform)) return 'linux';
  if (/mac|iphone|ipad|ipod/i.test(platform)) return 'mac';
  return '';
}

const grid = document.querySelector('[data-launcher]');
if (grid) {
  thisComputer().then(here => {
    const row = here && grid.querySelector(`[data-platform="${here}"]`);
    if (!row) return;
    row.classList.add('on');
    row.querySelector('[data-launcher-recommended]')?.removeAttribute('hidden');
  });
}

// The same copy button the app pages use. That handler lives in the catalog module, which this
// page has no other reason to load, so the behaviour is repeated here rather than the module.
const CHECK = 'm5 12 5 5L20 7';
document.addEventListener('click', async event => {
  const button = event.target.closest?.('[data-copy]');
  if (!button) return;
  const command = button.closest('.cmd')?.querySelector('span')?.textContent || '';
  const original = button.innerHTML;
  try {
    await navigator.clipboard.writeText(command);
    button.innerHTML = `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none"
      stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75"><path d="${CHECK}"/></svg>`;
    window.setTimeout(() => { button.innerHTML = original; }, 1200);
  } catch {
    button.setAttribute('aria-label', 'Could not copy command');
  }
});
