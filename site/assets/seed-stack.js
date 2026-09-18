// The pile of seeds a person sees beside an app, and the one read that refreshes every pile on
// a page. The same shape is drawn in worker/catalog.mjs for the pages the Worker writes, in
// scripts/build-site.py for the pages the build writes, and in the desktop launcher.
// Keep them in step.
//
// Rows are counted from the bottom of the pile up. Nothing is one hollow husk and no rows. One
// to three lie in a single row. Four to nine split in two, the wider row underneath. Ten and up
// hold at a nine-seed heap and let the number do the counting, so the pile never shrinks as the
// count rises.
const whole = count => Math.max(0, Math.trunc(Number(count) || 0));

export const seedKind = count => {
  const seeds = whole(count);
  return seeds === 0 ? 'none' : seeds <= 9 ? 'seeds' : 'heap';
};

export function seedRows(count) {
  const seeds = whole(count);
  if (seeds === 0) return [];
  if (seeds <= 3) return [seeds];
  if (seeds <= 9) return [Math.ceil(seeds / 2), Math.floor(seeds / 2)];
  return [5, 4];
}

// What the pile says out loud, in its label and its tooltip. The launcher says the same.
export function seedWords(count) {
  const seeds = whole(count);
  return seeds === 0 ? 'No seeds yet' : seeds === 1 ? '1 seed' : seeds + ' seeds';
}

// What the pile prints beside itself. The site is where a person can act on a count today, so
// the words are the invitation and every count carries them.
export function seedCaption(count) {
  const seeds = whole(count);
  return seeds === 0 ? 'No seeds yet' : 'Seeds \u00b7 ' + seeds;
}

const span = className => {
  const element = document.createElement('span');
  element.className = className;
  return element;
};

// Redraw one pile in place. The wrapper keeps its own id and dataset, so the app page can hand
// its rail button's stack straight to this.
export function fillStack(stack, count) {
  const seeds = whole(count), kind = seedKind(seeds), words = seedWords(seeds);
  stack.className = 'seed-stack';
  stack.dataset.seeds = String(seeds);
  stack.dataset.kind = kind;
  stack.setAttribute('role', 'img');
  stack.setAttribute('aria-label', words);
  stack.title = words;
  const pile = span('seed-pile');
  pile.setAttribute('aria-hidden', 'true');
  if (kind === 'none') {
    const husk = document.createElement('i');
    husk.className = 'seed seed-husk';
    pile.append(husk);
  } else {
    for (const row of seedRows(seeds)) {
      const line = span('seed-row');
      for (let n = 0; n < row; n++) {
        const seed = document.createElement('i');
        seed.className = 'seed';
        line.append(seed);
      }
      pile.append(line);
    }
  }
  const tally = span('seed-count');
  tally.textContent = seedCaption(seeds);
  stack.replaceChildren(pile, tally);
  return stack;
}

export function seedStack(count, appId) {
  const stack = document.createElement('span');
  if (appId) stack.dataset.seedStack = appId;
  return fillStack(stack, count);
}

export async function readCounts() {
  const response = await fetch('/api/social/counts', { cache: 'no-store' });
  if (!response.ok) throw new Error('The seed counts could not be read.');
  const data = await response.json();
  return data && typeof data === 'object' && data.apps ? data.apps : {};
}

// One read per page load, however many times a filtered grid redraws itself.
let pending = null;
export const countsOnce = () => (pending = pending || readCounts());

// One read for the whole page. The app page is left alone: social.js already keeps its single
// pile in step with the button that changes it.
export async function refreshStacks(root = document) {
  const stacks = [...root.querySelectorAll('[data-seed-stack]')];
  if (!stacks.length) return;
  const counts = await countsOnce();
  for (const stack of stacks) {
    const entry = counts[stack.dataset.seedStack];
    if (entry && Number.isFinite(Number(entry.seeds))) fillStack(stack, entry.seeds);
  }
}

if (typeof document !== 'undefined' && !document.querySelector('[data-seed-social]')) {
  // A pile that cannot be refreshed keeps the number the build wrote, which is the honest
  // answer for a visitor with no network rather than a row of zeros.
  refreshStacks().catch(() => {});
}
