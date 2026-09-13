import { mediaPattern } from './makers.mjs';
import { createApp, json } from './index.mjs';
import { proofRoutes } from './proof.mjs';
import { releaseRoutes } from './release.mjs';
import { seedRoutes } from './seeds.mjs';
import { artRoutes } from './art.mjs';
const app = createApp({ proofRoutes, releaseRoutes, seedRoutes, artRoutes });

// A single durable coordinator prevents KV's eventual consistency from allowing
// double code redemption, duplicate profile claims or simultaneous seed writes.
// Durable storage is authoritative; FARM KV is a write-through mirror.
export class FarmCoordinator {
  constructor(ctx, env) { this.ctx = ctx; this.env = env; this.tail = Promise.resolve(); }
  fetch(request) {
    const execute = async () => {
      const storage = this.ctx.storage;
      const farm = {
        get: async key => (await storage.get(key)) ?? null,
        put: async (key, value) => {
          await storage.put(key, JSON.parse(value));
          this.ctx.waitUntil(this.env.FARM.put(key, value).catch(() => console.error('FARM mirror write failed')));
        },
        delete: async key => {
          await storage.delete(key);
          this.ctx.waitUntil(this.env.FARM.delete(key).catch(() => console.error('FARM mirror delete failed')));
        },
      };
      return app(request, { ...this.env, FARM: farm });
    };
    // Read-only lookups must not sit behind a large upload or GitHub PR request.
    // In particular, CI's ten-second owner lookup remains responsive.
    // Drawing app art holds the model for a minute or more, which no other maker should wait
    // behind; the route reserves its own daily slot and refuses a second drawing for the same app.
    // A release check stays in the queue: it runs in seconds, and the queue is what makes its
    // once-a-minute limit per app hold, so two presses cannot open two pull requests.
    const { pathname } = new URL(request.url);
    if (request.method === 'GET' && ['/api/owners'].includes(pathname)) return execute();
    if (request.method === 'POST' && /^\/api\/seeds\/[a-z][a-z0-9]*(?:-[a-z0-9]+)*\/art$/.test(pathname)) return execute();
    const operation = this.tail.then(execute);
    this.tail = operation.catch(() => {});
    return operation;
  }
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/') || /^\/(account|farm|plant|seeds|makers)(?:\/|$)/.test(url.pathname)) {
      return env.FARM_COORDINATOR.get(env.FARM_COORDINATOR.idFromName('farm')).fetch(request);
    }
    if (url.pathname.startsWith('/media/')) {
      if (!['GET', 'HEAD'].includes(request.method)) return json({ error: 'Use GET or HEAD for images.' }, 405);
      const key = url.pathname.slice(1);
      if (!mediaPattern.test(key)) return json({ error: 'Image not found.' }, 404);
      const object = await env.SEEDS.get(key);
      if (!object) return json({ error: 'Image not found.' }, 404);
      const contentType = { png: 'image/png', jpg: 'image/jpeg', webp: 'image/webp' }[key.split('.').pop()];
      return new Response(request.method === 'HEAD' ? null : object.body, { headers: {
        'Content-Type': contentType, 'Content-Length': String(object.size),
        'Cache-Control': 'public, max-age=31536000, immutable', 'X-Content-Type-Options': 'nosniff',
      } });
    }
    if (url.pathname.startsWith('/seeds-files/')) {
      if (!['GET', 'HEAD'].includes(request.method)) return json({ error: 'Use GET or HEAD for app files.' }, 405);
      const path = url.pathname.slice('/seeds-files/'.length);
      if (!/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*\/(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\/[a-zA-Z0-9][a-zA-Z0-9._-]*\.tar\.gz$/.test(path)) return json({ error: 'That app file does not exist.' }, 404);
      const object = await env.SEEDS.get('seeds/' + path);
      if (!object) return json({ error: 'That app file does not exist.' }, 404);
      return new Response(request.method === 'HEAD' ? null : object.body, { headers: {
        'Content-Type': 'application/gzip', 'Content-Length': String(object.size),
        'Content-Disposition': `attachment; filename="${path.split('/').pop()}"`,
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'public, max-age=300',
        ...(object.httpEtag ? { ETag: object.httpEtag } : {}),
      } });
    }
    return env.ASSETS.fetch(request);
  },
};
