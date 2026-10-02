import { FARM_REPO } from './catalog.mjs';
import { appToken, client } from './release.mjs';

export async function dispatchReleasePoll(env, fetcher = fetch, now = Date.now()) {
  const token = await appToken(env, fetcher, now);
  const api = client(fetcher, token);
  await api('POST', `/repos/${FARM_REPO}/dispatches`, {
    event_type: 'release-poll',
    client_payload: { source: 'cloudflare-cron', dispatched_at: new Date(now).toISOString() },
  });
}
