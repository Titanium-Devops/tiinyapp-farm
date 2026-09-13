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
