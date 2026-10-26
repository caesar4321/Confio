#!/usr/bin/env node
/**
 * Release check (needs network): every bundled Ondo stock's beacon and proxy
 * code hash are in src/config/ondoBeacons.ts. A new one means Ondo started a
 * new token family; add it there, or tokens remembered from it are never
 * admitted by the Emergency Exit.
 */
import { readFileSync } from 'node:fs';
import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, hexToBytes } from '@noble/hashes/utils';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const read = (path) => readFileSync(resolve(here, path), 'utf8');
const tokens = [...read('../src/config/ondoStockTokens.generated.ts').matchAll(/address: '(0x[0-9a-f]{40})'/g)].map((m) => m[1]);
const config = read('../src/config/ondoBeacons.ts');
const beacons = new Set([...config.matchAll(/'(0x[0-9a-f]{40})'/g)].map((m) => m[1]));
const codeHashes = new Set([...config.matchAll(/'(0x[0-9a-f]{64})'/g)].map((m) => m[1]));
const SLOT = '0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50';
const RPCS = ['https://bsc-dataseed.bnbchain.org', 'https://bsc-rpc.publicnode.com', 'https://bsc-dataseed1.defibit.io'];

const batch = async (addresses, method) => {
  const body = addresses.map((a, id) => ({
    jsonrpc: '2.0', id, method, params: method === 'eth_getCode' ? [a, 'latest'] : [a, SLOT, 'latest'],
  }));
  for (const rpc of RPCS) {
    try {
      const res = await fetch(rpc, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const json = await res.json();
      const byId = new Map(json.map((r) => [r.id, r.result]));
      if (addresses.every((_, id) => typeof byId.get(id) === 'string')) {
        return addresses.map((_, id) => byId.get(id));
      }
    } catch { /* next endpoint */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error('every BSC RPC failed');
};

const unknown = new Map();
for (let i = 0; i < tokens.length; i += 40) {
  const chunk = tokens.slice(i, i + 40);
  (await batch(chunk, 'eth_getStorageAt')).forEach((slot, j) => {
    const beacon = '0x' + slot.slice(-40).toLowerCase();
    if (!beacons.has(beacon)) unknown.set(chunk[j], `beacon ${beacon}`);
  });
  (await batch(chunk, 'eth_getCode')).forEach((code, j) => {
    const hash = '0x' + bytesToHex(keccak_256(hexToBytes(code.slice(2))));
    if (!codeHashes.has(hash)) unknown.set(chunk[j], `code ${hash}`);
  });
  await new Promise((r) => setTimeout(r, 500));
}
if (unknown.size) {
  console.error([...unknown].map(([t, what]) => `${t} -> ${what}`).join('\n'));
  throw new Error(`${unknown.size} bundled Ondo tokens use a beacon or proxy code missing from ondoBeacons.ts`);
}
console.log(`All ${tokens.length} bundled Ondo tokens use a known beacon (${beacons.size}) and proxy code (${codeHashes.size}).`);
