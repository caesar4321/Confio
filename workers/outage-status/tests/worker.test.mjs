import assert from 'node:assert/strict';
import { generateKeyPairSync, verify } from 'node:crypto';
import { afterEach, test } from 'node:test';
import worker from '../src/index.ts';

const originalFetch = globalThis.fetch;
const originalNow = Date.now;
const { privateKey, publicKey } = generateKeyPairSync('ed25519');
const envFor = () => {
  const values = new Map();
  return {
    CONFIO_GRAPHQL_URL: 'https://confio.example/graphql/',
    STATUS_SIGNING_KEY: privateKey.export({ type: 'pkcs8', format: 'der' }).toString('base64'),
    STATUS: {
      get: async (key) => values.has(key) ? JSON.parse(values.get(key)) : null,
      put: async (key, value) => { values.set(key, value); },
    },
  };
};
const probe = async (env, time, response) => {
  Date.now = () => time * 1000;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, env.CONFIO_GRAPHQL_URL);
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), { query: '{__typename}' });
    if (response instanceof Error) throw response;
    return response;
  };
  const pending = [];
  await worker.scheduled({}, env, { waitUntil: (promise) => pending.push(promise) });
  await Promise.all(pending);
};
const status = async (env) => {
  const response = await worker.fetch(new Request('https://worker.example/v1/status'), env);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  const body = await response.json();
  assert.equal(verify(null, Buffer.from(body.payload), publicKey, Buffer.from(body.signature, 'base64')), true);
  assert.equal(verify(null, Buffer.from(body.payload + ' '), publicKey, Buffer.from(body.signature, 'base64')), false);
  return JSON.parse(body.payload);
};
afterEach(() => { globalThis.fetch = originalFetch; Date.now = originalNow; });

test('no observation is unavailable, not an invented outage', async () => {
  const response = await worker.fetch(new Request('https://worker.example/v1/status'), envFor());
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: 'no_probe_yet' });
});

test('signed observations preserve an outage start and reset after recovery', async () => {
  const env = envFor();
  await probe(env, 1000, Response.json({ data: { __typename: 'Query' } }));
  assert.deepEqual(await status(env), { v: 1, checkedAt: 1000, lastUpAt: 1000, downSince: null });
  await probe(env, 1300, new Response('unavailable', { status: 503 }));
  await probe(env, 1600, new Error('network unavailable'));
  assert.deepEqual(await status(env), { v: 1, checkedAt: 1600, lastUpAt: 1000, downSince: 1300 });
  await probe(env, 1900, Response.json({ errors: [{ message: 'authentication required' }] }, { status: 401 }));
  assert.deepEqual(await status(env), { v: 1, checkedAt: 1900, lastUpAt: 1900, downSince: null });
  await probe(env, 2200, new Response('<html>proxy error</html>'));
  assert.deepEqual(await status(env), { v: 1, checkedAt: 2200, lastUpAt: 1900, downSince: 2200 });
});

test('first failed probe starts the window now, never retroactively', async () => {
  const env = envFor();
  await probe(env, 1000, new Error('network unavailable'));
  assert.deepEqual(await status(env), { v: 1, checkedAt: 1000, lastUpAt: null, downSince: 1000 });
});

test('public endpoint cannot trigger probes or change state', async () => {
  const env = envFor();
  for (const [path, method] of [['/v1/status', 'POST'], ['/probe', 'GET'], ['/', 'GET']]) {
    const response = await worker.fetch(new Request(`https://worker.example${path}`, { method }), env);
    assert.equal(response.status, 404);
  }
  assert.equal(await env.STATUS.get('status_v1'), null);
});
