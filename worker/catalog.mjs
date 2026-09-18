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

// The pile of seeds a person sees beside an app. One shape, drawn three times: here for the
// pages the Worker writes, in scripts/build-site.py for the pages the build writes, and in
// site/assets/seed-stack.js for the counts the browser refreshes. Keep the three in step.
// 0 is one empty husk, 1 to 3 sit in one row, 4 to 9 fall into two rows, and 10 or more become
// a heap of six with the number doing the counting.
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
export const seedWords = count => {
  const seeds = Math.max(0, Math.trunc(Number(count) || 0));
  return seeds === 0 ? 'No seeds yet' : 'Seeds · ' + seeds;
};
export function seedStackHTML(count, attributes = '') {
  const seeds = Math.max(0, Math.trunc(Number(count) || 0));
  const pile = seedRows(seeds).map(row =>
    '<span class="seed-row">' + row.map(seed => `<i class="seed${seed ? '' : ' seed-husk'}"></i>`).join('') + '</span>').join('');
  const words = seedWords(seeds);
  return `<span class="seed-stack" data-seeds="${seeds}" role="img" aria-label="${words}"${attributes}>`
    + `<span class="seed-pile" aria-hidden="true">${pile}</span>`
    + `<span class="seed-count">${words}</span></span>`;
}
