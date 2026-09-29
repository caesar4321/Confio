/**
 * Confío outage status — an independent vantage point for the emergency exit.
 *
 * The app cannot tell, from the phone alone, whether Confío is down or just
 * unreachable from that phone (a ring blocking the domain, or a national
 * block). This Worker probes Confío from Cloudflare every 5 minutes and
 * serves a signed statement of what it saw:
 *
 *   GET /v1/status → { payload: "<json>", signature: "<base64 Ed25519>" }
 *   payload = { v: 1, checkedAt, lastUpAt, downSince }   (unix seconds)
 *
 * The app verifies the signature with a public key it ships with, so a
 * network attacker cannot forge "Confío is down" to unlock the immediate
 * exit. Confío's own servers are not involved: this keeps working (and
 * keeps saying "down") after they are gone.
 *
 * The probe matches the app's probeConfio: any well-formed GraphQL response,
 * even an error, proves Confío is alive; a 5xx, a non-JSON body or a network
 * failure does not.
 */

export interface Env {
  STATUS: KVNamespace;
  CONFIO_GRAPHQL_URL: string;
  /** PKCS8 Ed25519 private key, base64 (wrangler secret). */
  STATUS_SIGNING_KEY: string;
}

interface StoredStatus {
  checkedAt: number;
  lastUpAt: number | null;
  downSince: number | null;
}

const STATE_KEY = 'status_v1';
const PROBE_TIMEOUT_MS = 10_000;

const nowSec = () => Math.floor(Date.now() / 1000);

async function probeConfio(url: string): Promise<boolean> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'User-Agent': 'confio-outage-status/1' },
      body: JSON.stringify({ query: '{__typename}' }),
      signal: ctrl.signal,
    });
    if (!res.ok && res.status >= 500) return false;
    await res.json();
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function readStatus(env: Env): Promise<StoredStatus | null> {
  return (await env.STATUS.get<StoredStatus>(STATE_KEY, 'json')) ?? null;
}

async function recordProbe(env: Env): Promise<void> {
  const up = await probeConfio(env.CONFIO_GRAPHQL_URL);
  const previous = await readStatus(env);
  const checkedAt = nowSec();
  const next: StoredStatus = up
    ? { checkedAt, lastUpAt: checkedAt, downSince: null }
    : {
        checkedAt,
        lastUpAt: previous?.lastUpAt ?? null,
        // The outage started at the first failed probe of this episode.
        downSince: previous?.downSince ?? checkedAt,
      };
  await env.STATUS.put(STATE_KEY, JSON.stringify(next));
}

let signingKey: CryptoKey | null = null;

async function getSigningKey(env: Env): Promise<CryptoKey> {
  if (!signingKey) {
    const der = Uint8Array.from(atob(env.STATUS_SIGNING_KEY), (c) => c.charCodeAt(0));
    signingKey = await crypto.subtle.importKey('pkcs8', der, { name: 'Ed25519' }, false, ['sign']);
  }
  return signingKey;
}

const toBase64 = (bytes: ArrayBuffer): string => btoa(String.fromCharCode(...new Uint8Array(bytes)));

async function signedStatus(env: Env): Promise<Response> {
  const status = await readStatus(env);
  if (!status) {
    return new Response(JSON.stringify({ error: 'no_probe_yet' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    });
  }
  const payload = JSON.stringify({ v: 1, ...status });
  const signature = await crypto.subtle.sign(
    { name: 'Ed25519' },
    await getSigningKey(env),
    new TextEncoder().encode(payload),
  );
  return new Response(JSON.stringify({ payload, signature: toBase64(signature) }), {
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (request.method === 'GET' && pathname === '/v1/status') return signedStatus(env);
    return new Response('Not found', { status: 404 });
  },

  async scheduled(_event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(recordProbe(env));
  },
};
