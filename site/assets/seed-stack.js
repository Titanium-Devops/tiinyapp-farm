// The pile of seeds a person sees beside an app, and the one read that refreshes every pile on
// a page. The same shape is drawn in worker/catalog.mjs for the pages the Worker writes and in
// scripts/build-site.py for the pages the build writes. Keep the three in step.
// Nothing is an empty husk, one to three sit in a row, four to nine fall into two rows, and ten
// or more become a heap of six with the number doing the counting.
export function seedRows(count) {
  const seeds = Math.max(0, Math.trunc(Number(count) || 0));
  if (seeds === 0) return [[0]];
  if (seeds <= 3) return [Array(seeds).fill(1)];
  if (seeds <= 9) {
    const top = Math.floor(seeds / 2);
    return [Array(top).fill(1), Array(seeds - top).fill(1)];
  }
  return [[1], [1, 1], [1, 1, 1]];
}

export function seedWords(count) {
  const seeds = Math.max(0, Math.trunc(Number(count) || 0));
  return seeds === 0 ? 'No seeds yet' : 'Seeds · ' + seeds;
}

const span = className => {
  const element = document.createElement('span');
  element.className = className;
  return element;
};

// Redraw one pile in place. The wrapper keeps its own id and dataset, so the app page can hand
// its rail button's stack straight to this.
export function fillStack(stack, count) {
  const seeds = Math.max(0, Math.trunc(Number(count) || 0));
  const words = seedWords(seeds);
  stack.className = 'seed-stack';
  stack.dataset.seeds = String(seeds);
  stack.setAttribute('role', 'img');
  stack.setAttribute('aria-label', words);
  const pile = span('seed-pile');
  pile.setAttribute('aria-hidden', 'true');
  for (const row of seedRows(seeds)) {
    const line = span('seed-row');
    for (const seed of row) line.append(span(seed ? 'seed' : 'seed seed-husk'));
    pile.append(line);
  }
  const tally = span('seed-count');
  tally.textContent = words;
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
