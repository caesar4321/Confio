// Trustless clock for emergency-exit timing (docs/plans/salida-de-emergencia-design.md).
//
// Every emergency window — the 24h outage judgment, the 24h normal-state
// cooloff, and later the Exportar-claves 7d gate — is measured against
// BLOCKCHAIN block timestamps, never the device clock. A scammer can walk
// a victim through Settings → Date; nobody can walk them through forging
// a BSC block. This module is part of the sanctioned exception to the
// "no direct chain clients in the app" policy (algorandService.ts): the
// whole point of the emergency path is working while Confío is dark, so
// these endpoints are public and Confío-independent by design.

const BSC_RPCS = [
  'https://bsc-dataseed.bnbchain.org',
  'https://bsc-rpc.publicnode.com',
  'https://bsc-dataseed1.defibit.io',
];

const ALGOD_NODES = [
  'https://mainnet-api.algonode.cloud',
];

export interface ChainNow {
  sec: number;
  source: string;
}

const fetchWithTimeout = async (
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> => {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
};

const bscBlockTimestamp = async (rpc: string, timeoutMs: number): Promise<number> => {
  const res = await fetchWithTimeout(rpc, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 1,
      method: 'eth_getBlockByNumber', params: ['latest', false],
    }),
  }, timeoutMs);
  if (!res.ok) throw new Error(`http ${res.status}`);
  const json = await res.json();
  const ts = parseInt(json?.result?.timestamp ?? '', 16);
  if (!Number.isFinite(ts) || ts <= 0) throw new Error('no timestamp in block');
  return ts;
};

const algorandBlockTimestamp = async (node: string, timeoutMs: number): Promise<number> => {
  const st = await fetchWithTimeout(`${node}/v2/status`, {}, timeoutMs);
  if (!st.ok) throw new Error(`status http ${st.status}`);
  const round = (await st.json())['last-round'];
  const blk = await fetchWithTimeout(`${node}/v2/blocks/${round}`, {}, timeoutMs);
  if (!blk.ok) throw new Error(`block http ${blk.status}`);
  const ts = (await blk.json())?.block?.ts;
  if (!Number.isFinite(ts) || ts <= 0) throw new Error('no ts in block header');
  return ts;
};

/**
 * Current time per the chains. Tries BSC first (one call), then Algorand.
 * Throws only when EVERY endpoint fails — which the callers treat as
 * "chains unreachable", a state in which no timed window advances anyway.
 */
export const chainNow = async (timeoutMs = 8000): Promise<ChainNow> => {
  for (const rpc of BSC_RPCS) {
    try {
      return { sec: await bscBlockTimestamp(rpc, timeoutMs), source: rpc };
    } catch { /* next */ }
  }
  for (const node of ALGOD_NODES) {
    try {
      return { sec: await algorandBlockTimestamp(node, timeoutMs), source: node };
    } catch { /* next */ }
  }
  throw new Error('chainNow: no chain endpoint reachable');
};

export const CHAIN_ENDPOINTS = { BSC_RPCS, ALGOD_NODES };
