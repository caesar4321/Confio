// Verify the live response against the exact public key bundled in the app.
// No Cloudflare credentials or signing secret are needed.
import assert from 'node:assert/strict';
import { createPublicKey, verify } from 'node:crypto';
import { readFileSync } from 'node:fs';

const config = readFileSync(new URL('../../../apps/src/services/emergencyExit/outageStatusConfig.ts', import.meta.url), 'utf8');
const keyHex = config.match(/OUTAGE_STATUS_PUBLIC_KEY_HEX\s*=\s*'([a-f0-9]{64})'/)?.[1];
const urls = [...config.matchAll(/'(https:\/\/[^']+\/v1\/status)'/g)].map((match) => match[1]);
assert.ok(keyHex, 'App public key is not configured');
assert.ok(urls.length, 'App status URL is not configured');
const key = createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: Buffer.from(keyHex, 'hex').toString('base64url') }, format: 'jwk' });
for (const url of urls) {
  const response = await fetch(url, { signal: AbortSignal.timeout(15_000) });
  assert.equal(response.status, 200, `${url}: ${response.status} ${response.status === 200 ? '' : await response.text()}`);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  const body = await response.json();
  assert.equal(verify(null, Buffer.from(body.payload), key, Buffer.from(body.signature, 'base64')), true, 'Signature must match the app key');
  assert.equal(verify(null, Buffer.from(body.payload + ' '), key, Buffer.from(body.signature, 'base64')), false, 'Tampered payload must fail');
  const status = JSON.parse(body.payload);
  assert.equal(status.v, 1);
  assert.ok(Number.isSafeInteger(status.checkedAt) && status.checkedAt > 0);
  assert.ok(Math.abs(Date.now() / 1000 - status.checkedAt) <= 1800, 'Probe is stale');
  for (const field of ['lastUpAt', 'downSince']) {
    assert.ok(status[field] === null || (Number.isSafeInteger(status[field]) && status[field] > 0 && status[field] <= status.checkedAt), `Invalid ${field}`);
  }
  console.log(JSON.stringify({ url, signatureVerified: true, tamperRejected: true, status }));
}
