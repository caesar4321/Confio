// Tokens this device has seen the member hold (Ondo stocks, gold, Bitcoin…),
// remembered for the Emergency Exit.
//
// The exit's own lists are compiled into the app, so a token listed after
// this build (Ondo adds stocks every week) would be missing from them. A
// member can only come to hold one through the app, which shows its address
// in their holdings first: remembering it here covers it, with no call to
// Confío (or a key to Ondo's API) when the exit runs. The bundled lists stay
// the base; this only adds to them, and the exit moves a token only when the
// chain shows a balance, to the member's own destination.

import type { KVStore } from './kvStore';
import { BUNDLED_ONDO_STOCK_TOKENS } from '../../config/ondoStockTokens.generated';
import { BUNDLED_CRYPTO_TOKENS } from '../../config/cryptoTokens.generated';

export type HeldTokenKind = 'ondo' | 'crypto';

export interface HeldToken {
  readonly symbol: string;
  readonly address: string;
  readonly kind: HeldTokenKind;
}

const KEY = 'confio_emergency_held_tokens_v1';
// The newest ones: a real portfolio holds a few post-build stocks at most.
// Bounds what a bad server answer can add, and newer tokens always get in.
const MAX_TOKENS = 100;

// Already compiled into the exit: never worth a slot.
let compiled: Set<string> | null = null;
const isCompiled = (address: string) => {
  compiled ??= new Set([...BUNDLED_ONDO_STOCK_TOKENS, ...BUNDLED_CRYPTO_TOKENS].map((t) => t.address.toLowerCase()));
  return compiled.has(address);
};

const valid = (t: any): t is HeldToken =>
  t != null
  && typeof t.symbol === 'string' && /^[A-Za-z0-9._-]{1,32}$/.test(t.symbol)
  && typeof t.address === 'string' && /^0x[0-9a-fA-F]{40}$/.test(t.address)
  && (t.kind === 'ondo' || t.kind === 'crypto');

export const loadHeldTokens = async (store: KVStore): Promise<HeldToken[]> => {
  try {
    const raw = await store.get(KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter(valid).map((t) => ({ symbol: t.symbol, address: t.address.toLowerCase(), kind: t.kind }))
      : [];
  } catch {
    return []; // the bundled lists still cover everything they know
  }
};

// One write at a time: two screens reporting holdings together must not
// each read the old list and drop the other's token.
let queue: Promise<unknown> = Promise.resolve();

/** Add these tokens (a no-op, and no write, when all are already known). */
export const rememberHeldTokens = (store: KVStore, tokens: readonly Partial<HeldToken>[]): Promise<void> => {
  const run = queue.then(async () => {
    const fresh = tokens.filter(valid)
      .map((t) => ({ symbol: t.symbol, address: t.address.toLowerCase(), kind: t.kind }))
      .filter((t) => !isCompiled(t.address));
    if (!fresh.length) return;
    const known = await loadHeldTokens(store);
    const seen = new Set(known.map((t) => t.address));
    const added = fresh.filter((t) => {
      if (seen.has(t.address)) return false;
      seen.add(t.address);
      return true;
    });
    if (!added.length) return;
    await store.set(KEY, JSON.stringify([...known, ...added].slice(-MAX_TOKENS)));
  });
  queue = run.catch(() => {});
  return run.catch(() => {}); // remembering is best effort, never a user-facing error
};
