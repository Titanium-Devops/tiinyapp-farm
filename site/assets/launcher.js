// The download button already points at the Mac file when the page arrives, so a person with
// JavaScript switched off still gets a working download. This only turns it around on Windows.
// Linux is not detected on purpose: there is no launcher for it, and the note under the button
// says so and points at the command line.
const block = document.querySelector('[data-launcher]');
if (block) {
  const platform = navigator.userAgentData?.platform || navigator.platform || navigator.userAgent || '';
  if (/windows|win32|win64/i.test(platform)) {
    const primary = block.querySelector('[data-launcher-primary]');
    const other = block.querySelector('[data-launcher-other]');
    if (primary) {
      primary.href = block.dataset.windows;
      primary.textContent = 'Download for Windows';
    }
    if (other) {
      other.href = block.dataset.mac;
      other.textContent = 'Mac';
    }
  }
}
