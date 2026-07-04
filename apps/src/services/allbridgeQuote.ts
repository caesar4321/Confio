// Allbridge Core quote math, ported to dependency-free TypeScript.
//
// Decision (b), 2026-07-04: the CLIENT quotes the bridge leg (user-driven
// architecture — the user signs everything, so the user's device prices it),
// while the server supplies only guard threshold + Confío fee + kill switch
// (cusdPlusConvertParams). We port the pool math instead of importing
// @allbridge/bridge-core-sdk because the SDK drags web3/tronweb/algosdk into
// the Metro bundle.
//
// Faithful port of dist/src/utils/calculation/index.js (SDK v5, stableswap
// curve, SYSTEM_PRECISION = 3, floor rounding everywhere the SDK floors,
// including getY's +1 rounding offset). Validated against the real SDK's
// getAmountToBeReceived — see scripts/validate-allbridge-port.mjs (deltas
// must be ≤ 1 micro-unit). Re-run the validation if Allbridge bumps their
// SDK major.

const CORE_API = 'https://core.api.allbridgecoreapi.net';
const WAD = 10n ** 18n;
const SNAPSHOT_TTL_MS = 30_000;

interface PoolInfo {
  aValue: bigint;
  dValue: bigint;
  tokenBalance: bigint; // system precision (3)
  vUsdBalance: bigint; // system precision (3)
}

interface TokenSide {
  decimals: number;
  feeShareWad: bigint; // feeShare scaled 1e18
  pool: PoolInfo;
}

interface Snapshot {
  algUsdc: TokenSide;
  bscUsdt: TokenSide;
  fetchedAt: number;
}

export type BridgeDirection = 'alg_to_bsc' | 'bsc_to_alg';

export interface BridgeQuote {
  sendUsd: number;
  receiveUsd: number;
  costUsd: number;
  costPct: number;
  /** source-side pool depth in USD — the binding liquidity constraint */
  poolDepthUsd: number;
}

let cache: Snapshot | null = null;

const parseFeeShareWad = (feeShare: string): bigint => {
  // "0.0015" → 1500000000000000n without float drift
  const [intPart, fracPart = ''] = feeShare.split('.');
  const frac = (fracPart + '0'.repeat(18)).slice(0, 18);
  return BigInt(intPart) * WAD + BigInt(frac);
};

const pickToken = (chain: any, symbol: string): TokenSide => {
  const t = (chain?.tokens || []).find((x: any) => x.symbol === symbol);
  if (!t?.poolInfo) throw new Error(`allbridge: ${symbol} pool missing`);
  return {
    decimals: t.decimals,
    feeShareWad: parseFeeShareWad(t.feeShare),
    pool: {
      aValue: BigInt(t.poolInfo.aValue),
      dValue: BigInt(t.poolInfo.dValue),
      tokenBalance: BigInt(t.poolInfo.tokenBalance),
      vUsdBalance: BigInt(t.poolInfo.vUsdBalance),
    },
  };
};

export const fetchSnapshot = async (force = false): Promise<Snapshot> => {
  if (!force && cache && Date.now() - cache.fetchedAt < SNAPSHOT_TTL_MS) {
    return cache;
  }
  const res = await fetch(`${CORE_API}/token-info`);
  if (!res.ok) throw new Error(`allbridge token-info ${res.status}`);
  const data = await res.json();
  cache = {
    algUsdc: pickToken(data.ALG, 'USDC'),
    bscUsdt: pickToken(data.BSC, 'USDT'),
    fetchedAt: Date.now(),
  };
  return cache;
};

// ── SDK math, BigInt edition ────────────────────────────────────────────

const isqrt = (n: bigint): bigint => {
  if (n < 0n) throw new Error('isqrt of negative');
  if (n < 2n) return n;
  let x = 1n << (BigInt(n.toString(2).length + 1) / 2n);
  let y = (x + n / x) / 2n;
  while (y < x) {
    x = y;
    y = (x + n / x) / 2n;
  }
  return x;
};

// y = (sqrt(x(4ad³ + x(4a(d−x) − d)²)) + x(4a(d−x) − d)) / 8ax, floored, +1
const getY = (x: bigint, a: bigint, d: bigint): bigint => {
  const common = 4n * a * (d - x) - d;
  const sqrt = isqrt(x * (x * common * common + 4n * a * d * d * d));
  const result = (common * x + sqrt) / (8n * a * x);
  return result === 0n ? 0n : result + 1n;
};

/** token units (source decimals) → vUsd (system precision 3) */
const swapToVUsd = (amountInt: bigint, side: TokenSide): bigint => {
  if (amountInt <= 0n) return 0n;
  // (amount − amount·feeShare) → system precision, single exact floor
  const netScaled = amountInt * (WAD - side.feeShareWad); // scale: units·1e18
  const divisor = WAD * 10n ** BigInt(side.decimals - 3);
  const inSystem = netScaled / divisor;
  const newTokenBalance = side.pool.tokenBalance + inSystem;
  const y = getY(newTokenBalance, side.pool.aValue, side.pool.dValue);
  const out = side.pool.vUsdBalance - y;
  return out > 0n ? out : 0n;
};

/** vUsd (system precision 3) → token units (dest decimals) */
const swapFromVUsd = (vUsd: bigint, side: TokenSide): bigint => {
  if (vUsd <= 0n) return 0n;
  const newVUsdBalance = vUsd + side.pool.vUsdBalance;
  const y = getY(newVUsdBalance, side.pool.aValue, side.pool.dValue);
  const resultSystem = side.pool.tokenBalance - y;
  if (resultSystem <= 0n) return 0n;
  const resultTokens = resultSystem * 10n ** BigInt(side.decimals - 3);
  return (resultTokens * (WAD - side.feeShareWad)) / WAD;
};

const quoteInt = (amountInt: bigint, src: TokenSide, dst: TokenSide): bigint =>
  swapFromVUsd(swapToVUsd(amountInt, src), dst);

// ── Public API ──────────────────────────────────────────────────────────

const sides = (s: Snapshot, dir: BridgeDirection): [TokenSide, TokenSide] =>
  dir === 'alg_to_bsc' ? [s.algUsdc, s.bscUsdt] : [s.bscUsdt, s.algUsdc];

const toInt = (usd: number, decimals: number): bigint =>
  BigInt(Math.round(usd * 1e6)) * 10n ** BigInt(decimals - 6);

const toUsd = (units: bigint, decimals: number): number =>
  Number(units / 10n ** BigInt(decimals - 6)) / 1e6;

export const getBridgeQuote = async (
  amountUsd: number,
  direction: BridgeDirection = 'alg_to_bsc',
): Promise<BridgeQuote> => {
  const snap = await fetchSnapshot();
  const [src, dst] = sides(snap, direction);
  const receive = quoteInt(toInt(amountUsd, src.decimals), src, dst);
  const receiveUsd = toUsd(receive, dst.decimals);
  return {
    sendUsd: amountUsd,
    receiveUsd,
    costUsd: amountUsd - receiveUsd,
    costPct: amountUsd > 0 ? (100 * (amountUsd - receiveUsd)) / amountUsd : 0,
    poolDepthUsd: Number(src.pool.tokenBalance) / 1e3,
  };
};

/**
 * Largest amount ≤ maxUsd whose total cost stays under thresholdPct — the
 * partial-fill guard (client-visible partial fills; never auto-tranche).
 * Pure math over one cached snapshot: no extra network calls.
 */
export const maxFillUnderThreshold = async (
  maxUsd: number,
  thresholdPct: number,
  direction: BridgeDirection = 'alg_to_bsc',
): Promise<number> => {
  const snap = await fetchSnapshot();
  const [src, dst] = sides(snap, direction);
  const costPctOf = (usd: number): number => {
    const recv = toUsd(quoteInt(toInt(usd, src.decimals), src, dst), dst.decimals);
    return usd > 0 ? (100 * (usd - recv)) / usd : 0;
  };
  if (costPctOf(maxUsd) <= thresholdPct) return maxUsd;
  let lo = 0;
  let hi = maxUsd;
  // cents precision in ~40 iterations
  while (hi - lo > 0.01) {
    const mid = (lo + hi) / 2;
    if (costPctOf(mid) <= thresholdPct) lo = mid;
    else hi = mid;
  }
  return Math.floor(lo * 100) / 100;
};
