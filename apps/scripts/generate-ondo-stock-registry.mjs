#!/usr/bin/env node

/**
 * Generate the Emergency Exit's server-independent Ondo Stocks allowlist.
 *
 * Source: the reviewed Ondo BSC registry snapshot used by the backend.
 * Output: a plain TypeScript constant compiled into the mobile app. Runtime
 * Emergency Exit code never reads the source JSON or calls Confío/Ondo.
 */
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const sourcePath = resolve(here, '../../cusd_plus/gm_tokens.json');
const outputPath = resolve(here, '../src/config/ondoStockTokens.generated.ts');
const check = process.argv.includes('--check');

const source = readFileSync(sourcePath, 'utf8');
const parsed = JSON.parse(source);
const currentEntries = Object.entries(parsed).map(([symbol, metadata]) => ({
  symbol,
  address: String(metadata?.address || '').toLowerCase(),
})).sort((a, b) => a.symbol.localeCompare(b.symbol));

if (currentEntries.length < 400) {
  throw new Error(`refusing suspiciously small registry (${currentEntries.length})`);
}
const symbols = new Set();
const addresses = new Set();
for (const entry of currentEntries) {
  if (!/^[A-Za-z0-9._-]{1,32}$/.test(entry.symbol)) {
    throw new Error(`invalid symbol: ${entry.symbol}`);
  }
  if (!/^0x[0-9a-f]{40}$/.test(entry.address)) {
    throw new Error(`invalid BSC address for ${entry.symbol}: ${entry.address}`);
  }
  if (symbols.has(entry.symbol)) throw new Error(`duplicate symbol: ${entry.symbol}`);
  if (addresses.has(entry.address)) throw new Error(`duplicate address: ${entry.address}`);
  symbols.add(entry.symbol);
  addresses.add(entry.address);
}

// Emergency Exit is an address-history allowlist, not today's product
// catalog. If Ondo delists a stock or rotates a contract, users can still
// hold the old token. Preserve every address shipped by an earlier release
// and add the current snapshot on top. Symbols may therefore repeat after a
// contract rotation; the address remains the trust boundary.
const historicalEntries = [];
if (existsSync(outputPath)) {
  const existing = readFileSync(outputPath, 'utf8');
  const row = /\{ symbol: '([^']+)', address: '(0x[0-9a-f]{40})' \}/g;
  for (const match of existing.matchAll(row)) {
    historicalEntries.push({ symbol: match[1], address: match[2] });
  }
  if (!historicalEntries.length) throw new Error('could not parse existing Ondo address history');
  const declared = existing.match(/BUNDLED_ONDO_STOCK_COUNT = (\d+);/);
  if (!declared || Number(declared[1]) !== historicalEntries.length) {
    throw new Error('existing Ondo address history is incomplete or malformed');
  }
  for (const entry of historicalEntries) {
    if (!/^[A-Za-z0-9._-]{1,32}$/.test(entry.symbol)) {
      throw new Error(`invalid historical symbol: ${entry.symbol}`);
    }
  }
}

const byAddress = new Map();
for (const entry of [...historicalEntries, ...currentEntries]) {
  if (!byAddress.has(entry.address)) byAddress.set(entry.address, entry);
}
const entries = [...byAddress.values()].sort(
  (a, b) => a.symbol.localeCompare(b.symbol) || a.address.localeCompare(b.address),
);

const digest = createHash('sha256').update(source).digest('hex');
const rows = entries.map(
  ({ symbol, address }) => `  { symbol: '${symbol}', address: '${address}' },`,
).join('\n');
const generated = `// GENERATED FILE — do not edit by hand.\n// Source: cusd_plus/gm_tokens.json plus the previously shipped address history\n// Source SHA-256: ${digest}\n// Regenerate: npm run generate:ondo-registry\n\nexport interface BundledOndoStockToken {\n  readonly symbol: string;\n  readonly address: string;\n}\n\n/** Append-only history of canonical Ondo Stocks on BSC known to this app release.\n * Symbols are display-only; contract addresses are the trust boundary. */\nexport const BUNDLED_ONDO_STOCK_TOKENS: readonly BundledOndoStockToken[] = [\n${rows}\n] as const;\n\nexport const BUNDLED_ONDO_STOCK_COUNT = ${entries.length};\nexport const BUNDLED_ONDO_STOCK_SOURCE_SHA256 = '${digest}';\n`;

if (check) {
  const existing = readFileSync(outputPath, 'utf8');
  if (existing !== generated) {
    throw new Error('generated Ondo registry is stale; run npm run generate:ondo-registry');
  }
  console.log(`Ondo registry is current: ${entries.length} unique BSC tokens`);
} else {
  writeFileSync(outputPath, generated);
  console.log(`Wrote ${entries.length} unique BSC tokens to ${outputPath}`);
}
