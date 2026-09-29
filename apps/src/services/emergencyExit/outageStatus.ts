// Signed outage status from the independent Worker (workers/outage-status).
//
// Lets the exit tell a real Confío outage from a local block: a network
// attacker can hide Confío from this phone, but cannot forge the Worker's
// Ed25519 signature to claim Confío is down. Anything unverifiable (no
// Worker configured, unreachable, bad signature, malformed) is null, and
// the caller falls back to the phone's own observation.
//
// RN-free (fetch + @noble only) so jest covers it directly.

import { ed25519 } from '@noble/curves/ed25519.js';
import { hexToBytes, utf8ToBytes } from '@noble/hashes/utils';
import { OUTAGE_STATUS_PUBLIC_KEY_HEX, OUTAGE_STATUS_URLS } from './outageStatusConfig';

export interface OutageStatus {
  /** When the Worker last probed Confío (unix seconds). */
  checkedAtSec: number;
  lastUpAtSec: number | null;
  /** First failed probe of the current outage; null while Confío is up. */
  downSinceSec: number | null;
}

const isSec = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v > 0;

const base64ToBytes = (b64: string): Uint8Array => {
  const bin = globalThis.atob(b64);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
};

/** Verify one Worker response body; null unless signed and well-formed. */
export const parseSignedStatus = (body: unknown, publicKeyHex: string): OutageStatus | null => {
  if (!publicKeyHex || !body || typeof body !== 'object') return null;
  const { payload, signature } = body as { payload?: unknown; signature?: unknown };
  if (typeof payload !== 'string' || typeof signature !== 'string') return null;
  try {
    if (!ed25519.verify(base64ToBytes(signature), utf8ToBytes(payload), hexToBytes(publicKeyHex))) return null;
    const p = JSON.parse(payload);
    if (p?.v !== 1 || !isSec(p.checkedAt)) return null;
    if (p.lastUpAt !== null && !isSec(p.lastUpAt)) return null;
    if (p.downSince !== null && !isSec(p.downSince)) return null;
    return { checkedAtSec: p.checkedAt, lastUpAtSec: p.lastUpAt, downSinceSec: p.downSince };
  } catch {
    return null;
  }
};

/** First verifiable status from the configured Worker URLs, else null. */
export const fetchOutageStatus = async (
  urls: readonly string[] = OUTAGE_STATUS_URLS,
  publicKeyHex: string = OUTAGE_STATUS_PUBLIC_KEY_HEX,
  timeoutMs = 6000,
): Promise<OutageStatus | null> => {
  if (!publicKeyHex) return null;
  for (const url of urls) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, { signal: ctrl.signal });
      if (!res.ok) continue;
      const status = parseSignedStatus(await res.json(), publicKeyHex);
      if (status) return status;
    } catch { /* next */ } finally {
      clearTimeout(timer);
    }
  }
  return null;
};
