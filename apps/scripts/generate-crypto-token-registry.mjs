#!/usr/bin/env node

/**
 * Generate the Emergency Exit's server-independent crypto & metals allowlist
 * (Bitcoin, gold and every other token of the catalog, listed or not).
 *
 * Source: cusd_plus/crypto_tokens.json, the catalog the backend trades from.
 * Output: a plain TypeScript constant compiled into the mobile app. Runtime
 * Emergency Exit code never reads the source JSON or calls Confío.
 */
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const sourcePath = resolve(here, '../../cusd_plus/crypto_tokens.json');
const outputPath = resolve(here, '../src/config/cryptoTokens.generated.ts');
const check = process.argv.includes('--check');

const source = readFileSync(sourcePath, 'utf8');
const parsed = JSON.parse(source);
if (!Array.isArray(parsed.tokens) || parsed.tokens.length === 0) {
  throw new Error('crypto catalog has no tokens');
}
const valid = (entry, label) => {
  if (!/^[A-Za-z0-9._-]{1,32}$/.test(entry.symbol)) throw new Error(`invalid ${label}symbol: ${entry.symbol}`);
  if (!/^0x[0-9a-f]{40}$/.test(entry.address)) throw new Error(`invalid ${label}address for ${entry.symbol}`);
};
const currentEntries = parsed.tokens.map((token) => ({
  symbol: String(token?.symbol || ''),
  address: String(token?.address || '').toLowerCase(),
}));
const seen = new Set();
for (const entry of currentEntries) {
  valid(entry, '');
  if (seen.has(entry.address)) throw new Error(`duplicate address: ${entry.address}`);
  seen.add(entry.address);
}

// An address history, not today's catalog: a token taken off the catalog can
// still be held, so every address an earlier release shipped stays.
const historicalEntries = [];
if (existsSync(outputPath)) {
  const existing = readFileSync(outputPath, 'utf8');
  const row = /\{ symbol: '([^']+)', address: '(0x[0-9a-f]{40})' \}/g;
  for (const match of existing.matchAll(row)) historicalEntries.push({ symbol: match[1], address: match[2] });
  const declared = existing.match(/BUNDLED_CRYPTO_TOKEN_COUNT = (\d+);/);
  if (!declared || Number(declared[1]) !== historicalEntries.length) {
    throw new Error('existing crypto address history is incomplete or malformed');
  }
  for (const entry of historicalEntries) valid(entry, 'historical ');
}

const byAddress = new Map();
for (const entry of [...historicalEntries, ...currentEntries]) {
  if (!byAddress.has(entry.address)) byAddress.set(entry.address, entry);
}
const entries = [...byAddress.values()].sort(
  (a, b) => a.symbol.localeCompare(b.symbol) || a.address.localeCompare(b.address),
);

const digest = createHash('sha256').update(source).digest('hex');
const rows = entries.map(({ symbol, address }) => `  { symbol: '${symbol}', address: '${address}' },`).join('\n');
const generated = `// GENERATED FILE — do not edit by hand.\n// Source: cusd_plus/crypto_tokens.json plus the previously shipped address history\n// Source SHA-256: ${digest}\n// Regenerate: npm run generate:crypto-registry\n\nexport interface BundledCryptoToken {\n  readonly symbol: string;\n  readonly address: string;\n}\n\n/** Append-only history of the crypto & metals catalog on BSC known to this app\n * release (listed or not). Symbols are display-only; addresses are the trust boundary. */\nexport const BUNDLED_CRYPTO_TOKENS: readonly BundledCryptoToken[] = [\n${rows}\n] as const;\n\nexport const BUNDLED_CRYPTO_TOKEN_COUNT = ${entries.length};\nexport const BUNDLED_CRYPTO_TOKEN_SOURCE_SHA256 = '${digest}';\n`;

if (check) {
  const existing = existsSync(outputPath) ? readFileSync(outputPath, 'utf8') : '';
  if (existing !== generated) {
    throw new Error('generated crypto registry is stale; run npm run generate:crypto-registry');
  }
  console.log(`Crypto registry is current: ${entries.length} BSC tokens`);
} else {
  writeFileSync(outputPath, generated);
  console.log(`Wrote ${entries.length} BSC tokens to ${outputPath}`);
}
