// Confío's on-chain heartbeat — the ONLY thing that opens Salida de emergencia
// (docs/plans/salida-de-emergencia-design.md § Phase 3).
//
// Confío posts ConfioHeartbeat.beat() daily. The exit opens for everyone once
// the chain has gone `silenceRequired` (14 days) without a beat. The screen
// reads that state here; the real enforcement is on-chain: every exit
// transaction runs assertSilent() first, in the same atomic batch, so nothing
// this module concludes can move money while Confío is alive.
//
// Reads go straight to public BSC RPCs (never Confío's relay): the state must
// be readable exactly when Confío is gone.

import { CHAIN_ENDPOINTS } from './bscRpcs';
import { selector } from '../evmWallet';

/**
 * The ConfioHeartbeat PROXY on BSC mainnet (never the implementation), pinned
 * in the build, never taken from a server. A wrong address would be a
 * fail-open gate (ConfioBatchDelegate treats any successful call as a pass,
 * and a codeless address always "succeeds"), so the reader also requires
 * code, a beater and a non-zero silenceRequired before calling anything open.
 * The owner is deliberately NOT pinned: the Safe may rotate (Ownable2Step),
 * and a pinned owner would turn every shipped build's exit permanently
 * closed — possibly after nobody is left to ship a fix.
 * Empty until the proxy is deployed — the exit then stays closed.
 */
export const BUNDLED_HEARTBEAT = {
  // ConfioHeartbeat UUPS proxy, BSC mainnet, deployed 2026-10-05
  // (implementation 0x91D9F13869aa8072E3890Bf4A5351eEA1eC86dc0).
  address: '0xAE49E3AD57531974CD2AEc2633b03770fF4a20FF',
};

/** How long without a beat before the screen says "Confío no responde".
 *  Display only: beats are daily, so two missed days is worth telling. */
export const QUIET_AFTER_SECONDS = 2 * 24 * 3600;

export type HeartbeatState =
  | 'not_configured' // no proxy address in this build
  | 'unreachable' //    no public RPC answered
  | 'invalid' //        address has no code / wrong owner / uninitialized
  | 'alive' //          beating normally
  | 'quiet' //          missed beats, not yet silent long enough
  | 'open'; //          silent ≥ silenceRequired: the exit is open

export interface HeartbeatStatus {
  state: HeartbeatState;
  chainNowSec?: number;
  lastBeatSec?: number;
  silenceSec?: number;
  /** Earliest time the exit opens if no further beat arrives. */
  opensAtSec?: number;
}

const ADDR_RE = /^0x[0-9a-fA-F]{40}$/;

/** A real, non-zero 20-byte address (address(0) would be an ungated batch). */
export const isUsableAddress = (a: string): boolean => ADDR_RE.test(a) && BigInt(a) !== 0n;

const rpc = async (method: string, params: unknown[], timeoutMs = 8000): Promise<any> => {
  let lastErr: unknown;
  for (const url of CHAIN_ENDPOINTS.BSC_RPCS) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
        signal: ctrl.signal,
      });
      if (!res.ok) throw new Error(`http ${res.status}`);
      const json = await res.json();
      if (json.error) throw new Error(json.error.message);
      return json.result;
    } catch (e) {
      lastErr = e;
    } finally {
      clearTimeout(t);
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error('all BSC RPCs failed');
};

const callWord = async (to: string, sig: string, block: string): Promise<bigint> => {
  const ret: string = await rpc('eth_call', [{ to, data: selector(sig) }, block]);
  if (!ret || ret === '0x' || ret.length < 66) throw new Error(`empty ${sig}`);
  return BigInt(ret.slice(0, 66));
};

/**
 * Read the heartbeat at one block. Every value comes from the SAME block, so
 * "now" and "last beat" can never come from different RPC views.
 */
export const readHeartbeat = async (
  address: string = BUNDLED_HEARTBEAT.address,
): Promise<HeartbeatStatus> => {
  if (!isUsableAddress(address)) return { state: 'not_configured' };
  let tag: string;
  let chainNowSec: number;
  try {
    // Load-balanced public nodes occasionally answer `null` for 'latest':
    // that is "unreadable", never a reason to trust anything else.
    const block = await rpc('eth_getBlockByNumber', ['latest', false]);
    if (!block || typeof block.number !== 'string' || typeof block.timestamp !== 'string') {
      return { state: 'unreachable' };
    }
    tag = block.number;
    chainNowSec = Number(BigInt(block.timestamp));
  } catch {
    return { state: 'unreachable' };
  }
  try {
    const code: string = await rpc('eth_getCode', [address, tag]);
    if (!code || code === '0x') return { state: 'invalid', chainNowSec };
    const [beater, silence, lastBeat] = await Promise.all([
      callWord(address, 'beater()', tag),
      callWord(address, 'silenceRequired()', tag),
      callWord(address, 'lastBeat()', tag),
    ]);
    if (beater === 0n || silence === 0n) return { state: 'invalid', chainNowSec };
    const lastBeatSec = Number(lastBeat);
    const silenceSec = Number(silence);
    const opensAtSec = lastBeatSec + silenceSec;
    const state: HeartbeatState = chainNowSec >= opensAtSec
      ? 'open'
      : chainNowSec - lastBeatSec >= QUIET_AFTER_SECONDS ? 'quiet' : 'alive';
    return { state, chainNowSec, lastBeatSec, silenceSec, opensAtSec };
  } catch {
    return { state: 'unreachable', chainNowSec };
  }
};

/**
 * The exit is closed: Confío is alive ('alive' / 'quiet'), or the gate could
 * not be verified ('unreachable' / 'invalid' / 'not_configured'). `status`
 * says which — the screen words them differently.
 */
export class ConfioAliveError extends Error {
  readonly status: HeartbeatStatus;
  constructor(status: HeartbeatStatus) {
    super(`emergency exit closed: heartbeat ${status.state}`);
    this.name = 'ConfioAliveError';
    this.status = status;
  }
}

export const isConfioAlive = (e: unknown): e is ConfioAliveError =>
  e instanceof ConfioAliveError || (e as any)?.name === 'ConfioAliveError';

/** Throws ConfioAliveError unless the chain says the exit is open. */
export const assertExitOpen = async (
  address: string = BUNDLED_HEARTBEAT.address,
): Promise<HeartbeatStatus> => {
  const status = await readHeartbeat(address);
  if (status.state !== 'open') throw new ConfioAliveError(status);
  return status;
};
