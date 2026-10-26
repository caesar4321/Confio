// Salida de emergencia — the Hyperliquid leg (Futuros).
//
// Same rule as the BSC legs: it runs only while the on-chain heartbeat says
// the exit is open (assertExitOpen before EVERY send), talks to nobody but
// Hyperliquid's public API (no Confío server), and moves the member's own
// money to the member's own address. Hyperliquid actions are signed fresh
// here with the member's key (Hyperliquid nonces are timestamps, so nothing
// can be pre-signed). Three steps, each resumable:
//   1. close every open position (reduce-only IOC at the mark ± 5%, then
//      wider), and only go on once Hyperliquid shows none left open;
//   2. move each builder-market (HIP-3) balance back to the main balance;
//   3. withdraw everything to the destination on Arbitrum (Hyperliquid's own
//      bridge: no gas for the member, a $1 Hyperliquid fee).

import { DerivedEvmWallet } from '../evmWallet';
import { assertExitOpen } from './heartbeat';
import { nextNonce, signAction } from '../hyperliquidSigning';
import { USDC_COLLATERAL, fetchBounded } from '../hyperliquidInfo';

const API = 'https://api.hyperliquid.xyz';
const USDC_TOKEN = 'USDC:0x6d1e7cde53ba9467b783cb7c530ce054';
const SIGNATURE_CHAIN_ID = '0xa4b1';
const WITHDRAW_FEE_USD = 1;

export type HyperCoreStep = 'close' | 'gather' | 'withdraw';

export interface HyperCorePosition { coin: string; dex: string; asset: number; szi: number; szDecimals: number; markPx: number }
export interface HyperCoreExitPlan {
  positions: HyperCorePosition[];
  dexFree: { dex: string; amount: number }[];
  coreFree: number;
  /** Everything the account is worth, open positions included (their margin and P&L). */
  accountValue: number;
  /** Dexes holding a collateral other than USDC: not withdrawable by this exit. */
  otherCollateral: string[];
  /** Free USDC in the spot balance (where a unified account keeps it). */
  spotFree: number;
  /** What reaches the destination if prices hold: everything minus the $1 fee. */
  estimatedOutUsd: number;
}
export interface HyperCoreExitResult { closed: string[]; gathered: string[]; withdrawnUsd: number | null }

const post = async (path: string, body: unknown, fetcher: typeof fetch = fetch): Promise<any> => {
  const res = await fetchBounded(`${API}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }, fetcher);
  if (!res.ok) throw new Error(`Hyperliquid respondió ${res.status}`);
  return res.json();
};

/** Hyperliquid price rule: ≤ 5 significant figures, ≤ 6 − szDecimals decimals. */
export const wirePrice = (px: number, szDecimals: number, up: boolean): string => {
  if (!(px > 0)) throw new Error('precio inválido');
  const digits = Math.floor(Math.log10(px)) + 1;
  const places = Math.max(0, Math.min(Math.max(5 - digits, 0), 6 - szDecimals));
  const factor = 10 ** places;
  const rounded = (up ? Math.ceil(px * factor) : Math.floor(px * factor)) / factor;
  return String(Number(rounded.toFixed(places)));
};

const wireSize = (szi: number, szDecimals: number) => String(Number(Math.abs(szi).toFixed(szDecimals)));
const usdc = (n: number) => String(Math.floor(n * 1e6) / 1e6);

/** Everything the member has on Hyperliquid, read straight from its public API. */
export const planHyperCoreExit = async (address: string, fetcher: typeof fetch = fetch): Promise<HyperCoreExitPlan> => {
  const dexs: any[] = await post('/info', { type: 'perpDexs' }, fetcher);
  if (!Array.isArray(dexs)) throw new Error('Hyperliquid respondió incompleto. No movimos nada; inténtalo de nuevo.');
  // Keep each dex at its own position: HIP-3 asset ids are built from it.
  const names = ['', ...dexs.slice(1).map((d) => (typeof d?.name === 'string' ? d.name : null))];
  const positions: HyperCorePosition[] = [];
  const dexFree: { dex: string; amount: number }[] = [];
  let coreFree = 0;
  let accountValue = 0;
  const otherCollateral: string[] = [];
  for (const [position, dex] of names.entries()) {
    if (dex === null) continue;
    const [state, metaCtx] = await Promise.all([
      post('/info', dex ? { type: 'clearinghouseState', user: address, dex } : { type: 'clearinghouseState', user: address }, fetcher),
      post('/info', dex ? { type: 'metaAndAssetCtxs', dex } : { type: 'metaAndAssetCtxs' }, fetcher),
    ]);
    // Incomplete answers are not "nothing open": stop rather than withdraw past a position.
    const universe: any[] = metaCtx?.[0]?.universe;
    const ctxs: any[] = metaCtx?.[1];
    if (!Array.isArray(state?.assetPositions) || !Array.isArray(universe) || !Array.isArray(ctxs)) {
      throw new Error('Hyperliquid respondió incompleto. No movimos nada; inténtalo de nuevo.');
    }
    const free = Number(state.withdrawable);
    // An unknown balance is not "nothing to withdraw".
    if (state.withdrawable == null || !Number.isFinite(free)) {
      throw new Error('Hyperliquid respondió incompleto. No movimos nada; inténtalo de nuevo.');
    }
    const usdc = Number(metaCtx[0].collateralToken ?? 0) === USDC_COLLATERAL;
    if (usdc) accountValue += Number(state.marginSummary?.accountValue || 0) || free;
    if (dex && !usdc) {
      // Another collateral (USDH, USDE…) cannot leave as USDC: its balance and
      // its positions (closing them would only free more of it) are listed on
      // the card and left as they are, on the member's own account.
      const value = Number(state.marginSummary?.accountValue || 0);
      const held = state.assetPositions.some((e: any) => Number(e?.position?.szi) !== 0);
      if (free > 0 || value > 0 || held) otherCollateral.push(dex);
      continue;
    }
    if (dex) {
      if (free > 0) dexFree.push({ dex, amount: free });
    } else coreFree = free;
    for (const entry of state.assetPositions) {
      const p = entry?.position;
      const szi = Number(p?.szi);
      if (!p?.coin || !Number.isFinite(szi)) {
        throw new Error('Hyperliquid respondió incompleto. No movimos nada; inténtalo de nuevo.');
      }
      if (szi === 0) continue;
      const index = universe.findIndex((u) => u?.name === p.coin);
      // The current mark only: an old entry price would void the close's price limit.
      if (index < 0 || !(Number(ctxs[index]?.markPx) > 0)) {
        throw new Error(`Hyperliquid no devolvió el mercado de ${p.coin}. No movimos nada; inténtalo de nuevo.`);
      }
      positions.push({
        coin: p.coin, dex, szi,
        asset: position === 0 ? index : 100000 + position * 10000 + index,
        szDecimals: Number(universe[index].szDecimals || 0),
        markPx: Number(ctxs[index].markPx),
      });
    }
  }
  // A unified account keeps its USDC in the spot balance, not in the perps one.
  const spot = await post('/info', { type: 'spotClearinghouseState', user: address }, fetcher);
  if (!Array.isArray(spot?.balances)) throw new Error('Hyperliquid respondió incompleto. No movimos nada; inténtalo de nuevo.');
  const spotUsdc = spot.balances.find((b: any) => b?.token === USDC_COLLATERAL);
  const spotFree = Math.max(0, Number(spotUsdc?.total || 0) - Number(spotUsdc?.hold || 0));
  // Closing releases each position's margin and P&L (less a small closing fee).
  const free = coreFree + dexFree.reduce((sum, d) => sum + d.amount, 0);
  const total = Math.max(free, accountValue) + spotFree;
  return {
    positions, dexFree, coreFree, accountValue, otherCollateral, spotFree,
    estimatedOutUsd: Math.max(0, total - WITHDRAW_FEE_USD),
  };
};

const CLOSE_SLIPPAGES = [0.05, 0.08, 0.12];

const exchange = async (
  action: Record<string, any>, nonce: number, wallet: DerivedEvmWallet, fetcher: typeof fetch,
  { allowOrderErrors = false } = {},
) => {
  const signature = signAction(action, nonce, wallet.privKeyHex);
  const body: Record<string, unknown> = { action, nonce, signature };
  if (['order', 'cancel', 'updateLeverage', 'updateIsolatedMargin'].includes(action.type)) body.vaultAddress = null;
  const answer = await post('/exchange', body, fetcher);
  if (answer?.status !== 'ok') throw new Error(`Hyperliquid rechazó la operación: ${JSON.stringify(answer?.response ?? '')}`);
  const statuses: any[] = answer?.response?.data?.statuses ?? [];
  if (!allowOrderErrors && statuses.some((st) => st?.error)) {
    throw new Error(`Hyperliquid rechazó la operación: ${statuses.map((st) => st?.error).filter(Boolean).join('; ')}`);
  }
  return answer;
};

/**
 * Close, gather, withdraw. Re-reads the live state before each step, so a
 * retry after any interruption simply continues (nothing is sent twice: a
 * closed position is no longer listed, a gathered balance reads zero).
 */
export const executeHyperCoreExit = async (params: {
  wallet: DerivedEvmWallet;
  dest: string;
  onStep?: (step: HyperCoreStep) => void;
  fetcher?: typeof fetch;
}): Promise<HyperCoreExitResult> => {
  const { wallet, dest, onStep } = params;
  const fetcher = params.fetcher ?? fetch;
  if (!/^0x[0-9a-fA-F]{40}$/.test(dest)) throw new Error('Dirección de destino inválida');
  const result: HyperCoreExitResult = { closed: [], gathered: [], withdrawnUsd: null };

  let plan = await planHyperCoreExit(wallet.address, fetcher);
  if (plan.positions.length) onStep?.('close');
  // An IOC can fill partly or not at all: re-read and go again, wider each
  // time, until Hyperliquid shows nothing open. Never withdraw before that.
  for (const slippage of CLOSE_SLIPPAGES) {
    if (!plan.positions.length) break;
    for (const p of plan.positions) {
      await assertExitOpen();
      const isBuy = p.szi < 0;
      const px = wirePrice(p.markPx * (isBuy ? 1 + slippage : 1 - slippage), p.szDecimals, isBuy);
      const answer = await exchange({
        type: 'order',
        orders: [{ a: p.asset, b: isBuy, p: px, s: wireSize(p.szi, p.szDecimals), r: true, t: { limit: { tif: 'Ioc' } } }],
        grouping: 'na',
      }, nextNonce(), wallet, fetcher, { allowOrderErrors: true });
      const status = answer?.response?.data?.statuses?.[0];
      if (status?.filled && !result.closed.includes(p.coin)) result.closed.push(p.coin);
    }
    plan = await planHyperCoreExit(wallet.address, fetcher);
  }
  if (plan.positions.length) {
    throw new Error(`No pudimos cerrar ${plan.positions.map((p) => p.coin).join(', ')}: no hay suficiente liquidez ahora. No retiramos nada; inténtalo de nuevo en unos minutos.`);
  }

  if (plan.dexFree.length) onStep?.('gather');
  for (const d of plan.dexFree) {
    await assertExitOpen();
    const nonce = nextNonce();
    await exchange({
      type: 'sendAsset', signatureChainId: SIGNATURE_CHAIN_ID, hyperliquidChain: 'Mainnet', destination: wallet.address.toLowerCase(),
      sourceDex: d.dex, destinationDex: '', token: USDC_TOKEN, amount: usdc(d.amount), fromSubAccount: '', nonce,
    }, nonce, wallet, fetcher);
    result.gathered.push(d.dex);
  }

  plan = await planHyperCoreExit(wallet.address, fetcher);
  if (plan.spotFree > 0.01) {
    // Spot USDC (a unified account's balance) joins the perps balance first:
    // standard mode, then a transfer between the member's own balances.
    onStep?.('gather');
    const mode = await post('/info', { type: 'userAbstraction', user: wallet.address }, fetcher);
    if (mode !== 'disabled') {
      await assertExitOpen();
      const nonce = nextNonce();
      await exchange({
        type: 'userSetAbstraction', signatureChainId: SIGNATURE_CHAIN_ID, hyperliquidChain: 'Mainnet',
        user: wallet.address.toLowerCase(), abstraction: 'disabled', nonce,
      }, nonce, wallet, fetcher);
    }
    await assertExitOpen();
    const nonce = nextNonce();
    await exchange({
      type: 'sendAsset', signatureChainId: SIGNATURE_CHAIN_ID, hyperliquidChain: 'Mainnet', destination: wallet.address.toLowerCase(),
      sourceDex: 'spot', destinationDex: '', token: USDC_TOKEN, amount: usdc(plan.spotFree), fromSubAccount: '', nonce,
    }, nonce, wallet, fetcher);
    result.gathered.push('spot');
    plan = await planHyperCoreExit(wallet.address, fetcher);
  }
  if (plan.coreFree > WITHDRAW_FEE_USD + 0.01) {
    onStep?.('withdraw');
    await assertExitOpen();
    const time = nextNonce();
    await exchange({
      type: 'withdraw3', signatureChainId: SIGNATURE_CHAIN_ID, hyperliquidChain: 'Mainnet',
      destination: dest.toLowerCase(), amount: usdc(plan.coreFree), time,
    }, time, wallet, fetcher);
    result.withdrawnUsd = Math.max(0, plan.coreFree - WITHDRAW_FEE_USD);
  }
  return result;
};
