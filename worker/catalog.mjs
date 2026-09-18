import { fail } from './index.mjs';
// Shared by the submission routes and the release-check routes so neither has to import the other.
export const FARM_REPO = 'Titanium-Devops/tiinyapp-farm';
export const GITHUB = 'https://api.github.com';
// Apps listed before the farm recorded seed owners keep their author proof as the owner record.
const LEGACY = new Set(['tiiny-bench', 'onelane', 'story-lantern', 'titanium-tiiny-bot']);
export function compareVersion(a, b) {
  const left = a.split('.').map(BigInt), right = b.split('.').map(BigInt);
  for (let i = 0; i < 3; i++) if (left[i] !== right[i]) return left[i] > right[i] ? 1 : -1;
  return 0;
}
export function releaseURL(value) {
  let url; try { url = new URL(value); } catch { fail(400, 'Use a public HTTPS release URL.'); }
  // Reject IP literals, local names, credentials and nonstandard ports. Every redirect hop is checked here too.
  if (url.protocol !== 'https:' || url.username || url.password || url.hash || (url.port && url.port !== '443') ||
      !/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(url.hostname) || /(^|\.)(localhost|local|internal|test|invalid)$/i.test(url.hostname)) fail(400, 'Use a public HTTPS release URL.');
  return url.href;
}
export async function ownsSeed(user, manifest, get) {
  if (!user?.tiinyverse) return false;
  const owner = await get('seedowner:' + manifest.id);
  return owner ? owner === user.id : LEGACY.has(manifest.id) && manifest.author?.tiinyverse === user.tiinyverse.profileUrl;
}

// The pile of seeds a person sees beside an app. One shape, drawn four times: here for the pages
// the Worker writes, in scripts/build-site.py for the pages the build writes, in
// site/assets/seed-stack.js for the counts a browser refreshes, and in the desktop launcher.
// Keep them in step; tests compare the markup here against the build's.
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
export const seedWords = count => {
  const seeds = whole(count);
  return seeds === 0 ? 'No seeds yet' : seeds === 1 ? '1 seed' : seeds + ' seeds';
};
// What the pile prints beside itself. The site is where a person can act on a count today, so
// the words are the invitation and every count carries them.
export const seedCaption = count => {
  const seeds = whole(count);
  return seeds === 0 ? 'No seeds yet' : 'Seeds \u00b7 ' + seeds;
};
export function seedStackHTML(count, attributes = '') {
  const seeds = whole(count), kind = seedKind(seeds);
  const pile = kind === 'none' ? '<i class="seed seed-husk"></i>'
    : seedRows(seeds).map(row => '<span class="seed-row">' + '<i class="seed"></i>'.repeat(row) + '</span>').join('');
  return `<span class="seed-stack" data-seeds="${seeds}" data-kind="${kind}" role="img"`
    + ` aria-label="${seedWords(seeds)}" title="${seedWords(seeds)}"${attributes}>`
    + `<span class="seed-pile" aria-hidden="true">${pile}</span>`
    + `<span class="seed-count">${seedCaption(seeds)}</span></span>`;
}
