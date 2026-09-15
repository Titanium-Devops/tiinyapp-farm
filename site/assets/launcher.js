// All three downloads are in the markup with real links, so the page works with JavaScript
// switched off. This only moves the visitor's own platform to the front of the row and fills
// its button, which is the one piece a static page cannot know on its own.
const row = document.querySelector('[data-launcher]');
if (row) {
  const platform = navigator.userAgentData?.platform || navigator.platform || navigator.userAgent || '';
  const here = /windows|win32|win64/i.test(platform) ? 'windows'
    : /android/i.test(platform) ? ''
      : /linux|x11|ubuntu|fedora|cros/i.test(platform) ? 'linux'
        : /mac|iphone|ipad|ipod/i.test(platform) ? 'mac' : '';
  const cell = here && row.querySelector(`[data-platform="${here}"]`);
  if (cell) {
    row.prepend(cell);
    for (const button of row.querySelectorAll('.get-now')) {
      const mine = button.closest('[data-platform]') === cell;
      button.classList.toggle('hay', mine);
      button.classList.toggle('ghost', !mine);
    }
  }
}
