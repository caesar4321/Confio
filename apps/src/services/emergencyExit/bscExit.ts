// BSC leg of the emergency exit (docs/plans/salida-de-emergencia-design.md).
//
// Direct mode: user pays gas, transactions go straight to public BSC RPCs
// with failover — zero GraphQL, zero relay. This intentionally REPLACES
// the app's server-relay transport (bscServerRpc) for the duration of the
// exit: routing an emergency through Confío infrastructure would defeat
// its purpose.
//
// Redeem-first policy: "permissionless ≠ accessible" — external wallets
// have no UI for either vault redeem, so the default exit converts cUSD+
// and cUSD into plain USDT-BSC before value leaves. Both fee-bearing exits
// pay USDT DIRECTLY to the destination. Fallback when a vault leg is dead:
// transfer the raw cUSD+/cUSD, flagged so the screen can warn.
//
// Resumable: every completed step records its tx hash in the injected KV
// store; re-running skips completed steps and re-reads live balances so
// a crash mid-exit never double-spends or strands a leg.

import {
  bscBnbBalance,
  bscGasPrice,
  bscEthCall,
  bscGetTransactionReceipt,
  sendCall,
  selector,
  encodeUint,
  encodeAddress,
  setBscTransport,
  isOutcomeUnknown,
  DerivedEvmWallet,
} from '../evmWallet';
import { CHAIN_ENDPOINTS } from './chainClock';
import type { KVStore } from './reachability';
import { BUNDLED_ONDO_STOCK_TOKENS } from '../../config/ondoStockTokens.generated';
import { CUSD_BSC_VAULT_ADDRESS } from '../../config/env';

// Bundled chain wiring (design doc: "token addresses/ABIs ship in the app
// bundle") — in an outage the config query that normally serves the vault
// address is dead. Verified against config/settings.py default AND
// contracts/cusd_plus/DEPLOYMENT.md (ERC1967 proxy) on 2026-07-22.
// USDT is defined here rather than imported from cusdPlusVault so this
// module stays free of react-native imports — the disaster drill drives
// it from Node against mainnet (same value as cusdPlusVault.USDT_BSC).
export const BUNDLED_VAULT_ADDRESS = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1';
// Filled from the release environment after the UUPS proxy is deployed. It is
// compiled into the app bundle; an empty value means cUSD is not deployed in
// that environment yet.
export const BUNDLED_CUSD_ADDRESS = CUSD_BSC_VAULT_ADDRESS;
const USDT_BSC = '0x55d398326f99059fF775485246999027B3197955';
export const BUNDLED_CONFIO_ADDRESS = '0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8';
const MULTICALL3 = '0xcA11bde05977b3631167028862bE2a173976CA11';
const ONDO_BALANCE_CHUNK = 250;

/** keccak256("Transfer(address,address,uint256)") — same constant as
 *  cusd_plus/tasks.py TRANSFER_TOPIC. */
const TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef';

/**
 * USDT credited to `dest` by this receipt, read from its logs.
 *
 * The screen may only state an amount the CHAIN proves: shares are not
 * dollars (cUSD+ is a yield-bearing vault, so share count × price-per-share
 * is the value), and redeemToUsdt's output isn't known until it executes.
 */
export const usdtCreditedTo = (
  receipt: { logs?: Array<{ address?: string; topics?: string[]; data?: string }> },
  dest: string,
): bigint => {
  let total = 0n;
  for (const log of receipt.logs ?? []) {
    if ((log.address ?? '').toLowerCase() !== USDT_BSC.toLowerCase()) continue;
    const topics = log.topics ?? [];
    if ((topics[0] ?? '').toLowerCase() !== TRANSFER_TOPIC) continue;
    if (('0x' + (topics[2] ?? '').slice(-40)).toLowerCase() !== dest.toLowerCase()) continue;
    total += BigInt(log.data && log.data !== '0x' ? log.data : 0);
  }
  return total;
};

// ── Direct failover transport ───────────────────────────────────────────

const rpcCall = async (rpc: string, method: string, params: unknown[]): Promise<any> => {
  const res = await fetch(rpc, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  if (!res.ok) throw new Error(`bsc rpc http ${res.status}`);
  const json = await res.json();
  if (json.error) throw new Error(`bsc rpc: ${json.error.message}`);
  return json.result;
};

const failover = async (method: string, params: unknown[]): Promise<any> => {
  let lastErr: unknown;
  for (const rpc of CHAIN_ENDPOINTS.BSC_RPCS) {
    try {
      return await rpcCall(rpc, method, params);
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error('all BSC RPCs failed');
};

/**
 * Install the emergency transport (public RPCs, failover). Returns a
 * restore function — call it after the exit so normal app flows go back
 * to the server relay.
 */
export const installEmergencyBscTransport = (): (() => void) => {
  setBscTransport({
    read: failover,
    submit: (rawTx: string) => failover('eth_sendRawTransaction', [rawTx]),
  });
  return () => setBscTransport(null); // null = evmWallet's direct default; relay reinstalls on next savings use
};

// ── Balances / plan ─────────────────────────────────────────────────────

const erc20Balance = async (token: string, addr: string): Promise<bigint> => {
  const ret = await bscEthCall(token, selector('balanceOf(address)') + encodeAddress(addr));
  return BigInt(ret === '0x' ? 0 : ret);
};

export interface OndoStockHolding {
  symbol: string;
  address: string;
  balanceWei: bigint;
}

const word = (value: bigint | number): string => BigInt(value).toString(16).padStart(64, '0');

/** ABI encode Multicall3.tryAggregate(false, balanceOf calls). Kept local so
 * Emergency Exit does not pull a wallet SDK—or a server—into its trust path. */
export const encodeStockBalanceMulticall = (
  owner: string,
  tokens: readonly { address: string }[],
): string => {
  const calls = tokens.map(({ address }) => {
    const callData = selector('balanceOf(address)') + encodeAddress(owner);
    const raw = callData.slice(2);
    const padded = raw.padEnd(Math.ceil(raw.length / 64) * 64, '0');
    return address.slice(2).padStart(64, '0') + word(64) + word(raw.length / 2) + padded;
  });
  let cursor = tokens.length * 32;
  const offsets = calls.map((call) => {
    const offset = word(cursor);
    cursor += call.length / 2;
    return offset;
  }).join('');
  const array = word(tokens.length) + offsets + calls.join('');
  return selector('tryAggregate(bool,(address,bytes)[])') + word(0) + word(64) + array;
};

const readAbiWord = (hex: string, byteOffset: number): bigint => {
  const start = byteOffset * 2;
  const value = hex.slice(start, start + 64);
  if (value.length !== 64) throw new Error('malformed Multicall response');
  return BigInt('0x' + value);
};

/** Decode Multicall3's (bool success, bytes returnData)[] result. */
export const decodeStockBalanceMulticall = (result: string, expected: number): bigint[] => {
  const hex = result.startsWith('0x') ? result.slice(2) : result;
  const arrayStart = Number(readAbiWord(hex, 0));
  const count = Number(readAbiWord(hex, arrayStart));
  if (count !== expected) throw new Error('unexpected Multicall result count');
  const headsStart = arrayStart + 32;
  const balances: bigint[] = [];
  for (let i = 0; i < count; i++) {
    const tupleStart = headsStart + Number(readAbiWord(hex, headsStart + i * 32));
    const success = readAbiWord(hex, tupleStart) !== 0n;
    const bytesStart = tupleStart + Number(readAbiWord(hex, tupleStart + 32));
    const length = Number(readAbiWord(hex, bytesStart));
    // A failed/short inner call is not a zero balance. Treating it as zero
    // would let one flaky token/RPC disappear from an allegedly complete
    // emergency exit.
    if (!success || length !== 32) throw new Error('Ondo balance call failed');
    balances.push(readAbiWord(hex, bytesStart + 32));
  }
  return balances;
};

/** Read the entire bundled Ondo universe in two eth_call requests today.
 * Contract addresses—not symbols or token metadata—are the allowlist. */
export const readBundledOndoStockHoldings = async (owner: string): Promise<OndoStockHolding[]> => {
  const holdings: OndoStockHolding[] = [];
  for (let start = 0; start < BUNDLED_ONDO_STOCK_TOKENS.length; start += ONDO_BALANCE_CHUNK) {
    const tokens = BUNDLED_ONDO_STOCK_TOKENS.slice(start, start + ONDO_BALANCE_CHUNK);
    const result = await bscEthCall(MULTICALL3, encodeStockBalanceMulticall(owner, tokens));
    const balances = decodeStockBalanceMulticall(result, tokens.length);
    balances.forEach((balanceWei, index) => {
      if (balanceWei > 0n) holdings.push({ ...tokens[index], balanceWei });
    });
  }
  return holdings;
};

export interface BscExitPlan {
  cusdPlusShares: bigint;
  cusdWei: bigint;
  usdtWei: bigint;
  confioWei: bigint;
  bnbWei: bigint;
  ondoStocks: OndoStockHolding[];
  steps: Array<'redeemCusdPlus' | 'redeemCusd' | 'transferUsdt' | 'transferConfio' | 'transferOndoStocks'>;
}

export const planBscExit = async (
  address: string,
  vaultAddress: string,
  cusdAddress: string = BUNDLED_CUSD_ADDRESS,
): Promise<BscExitPlan> => {
  const hasCusd = /^0x[0-9a-fA-F]{40}$/.test(cusdAddress);
  const [cusdPlusShares, cusdWei, usdtWei, confioWei, bnbWei, ondoStocks] = await Promise.all([
    erc20Balance(vaultAddress, address),
    hasCusd ? erc20Balance(cusdAddress, address) : Promise.resolve(0n),
    erc20Balance(USDT_BSC, address),
    erc20Balance(BUNDLED_CONFIO_ADDRESS, address),
    bscBnbBalance(address),
    readBundledOndoStockHoldings(address),
  ]);
  const steps: BscExitPlan['steps'] = [];
  if (cusdPlusShares > 0n) steps.push('redeemCusdPlus');
  if (cusdWei > 0n) steps.push('redeemCusd');
  // USDT step re-reads the live balance at execution time, so it also
  // carries whatever the redeem just delivered if redeem paid the user
  // (it pays the destination directly — this step covers pre-held USDT).
  if (usdtWei > 0n) steps.push('transferUsdt');
  if (confioWei > 0n) steps.push('transferConfio');
  if (ondoStocks.length > 0) steps.push('transferOndoStocks');
  // Deliberately NO BNB sweep (decision 2026-07-22, mirrors Algorand):
  // user BNB ≈ sponsor dust + a Direct-mode gas top-up's leftover cents.
  // Sweeping would leak sponsor dust through polished UI and strip the
  // account of gas it may need for stray future deposits to the old
  // address. Zero native outflow ⇒ zero farming-detector interaction.
  return { cusdPlusShares, cusdWei, usdtWei, confioWei, bnbWei, ondoStocks, steps };
};

/** BNB the user must hold for Direct-mode gas, for the top-up screen. */
export const estimateBscExitGasWei = async (plan: BscExitPlan): Promise<bigint> => {
  let gasPrice = await bscGasPrice();
  if (gasPrice < 100_000_000n) gasPrice = 100_000_000n;
  gasPrice = (gasPrice * 12n) / 10n;
  let units = 0n;
  // Reserve both the attempted redeem and the 120k raw-share fallback. A
  // reverted redeem still consumes gas before the fallback can run.
  if (plan.steps.includes('redeemCusdPlus')) units += 820_000n;
  // cUSD has no Ondo call, but reserve both redeem and raw-token fallback.
  if (plan.steps.includes('redeemCusd')) units += 260_000n;
  if (plan.steps.includes('transferUsdt')) units += 80_000n;
  if (plan.steps.includes('transferConfio')) units += 80_000n;
  // Ondo tokens can execute compliance hooks. Budget conservatively; the
  // actual send uses eth_estimateGas rather than a brittle fixed ceiling.
  units += BigInt(plan.ondoStocks.length) * 200_000n;
  return gasPrice * units;
};

// ── Execution ───────────────────────────────────────────────────────────

export interface BscExitResult {
  completed: string[];
  txids: Record<string, string>;
  /** Steps completed through a degraded fallback (screen must warn). */
  degraded: string[];
  /**
   * Steps this run actually BROADCAST. `txids` can carry hashes from an
   * interrupted earlier attempt, so it cannot answer "did anything happen
   * just now?" — and a screen that says "Listo, tu dinero salió" off a
   * replayed hash is lying about someone's money. Headlines read this.
   */
  sentNow: string[];
  /**
   * USDT (18 dec, wei as a decimal string) this run delivered to the
   * destination, summed from receipt logs. '0' means nothing landed THIS
   * run — a degraded raw-share transfer, an empty account, or a resumed
   * run whose sends happened earlier. The screen must treat '0' as
   * "amount unknown", never as "nothing moved".
   */
  usdtToDest: string;
  /** Assets that remain in the Confío wallet after every safe fallback failed. */
  unresolved: string[];
}

export type BscExitStep =
  | 'redeemCusdPlus'
  | 'redeemCusd'
  | 'transferUsdt'
  | 'transferConfio'
  | `ondoStock:${string}:${string}`;

const stockStep = ({ symbol, address }: OndoStockHolding): BscExitStep =>
  `ondoStock:${symbol}:${address.toLowerCase()}`;

// v2 key: v1 checkpoints were written WITHOUT a timestamp and were never
// cleared, so a completed exit left a permanent "already done" record. A
// later exit to the same destination then skipped every step and reported
// success having moved nothing. Ignoring v1 blobs entirely is the fix for
// devices carrying one.
const ckKey = (accountKey: string, dest: string) =>
  `confio_emergency_bsc_ck_v2_${accountKey}_${dest.toLowerCase()}`;

/**
 * A checkpoint exists to resume ONE interrupted attempt — it is not a
 * memory of past exits. Anything older than this is ignored, so a crash
 * between the last send and the clear can never suppress a future exit.
 * Device-local clock is fine: both stamps come from the same device, and
 * a clock jump only costs a re-read of live balances.
 */
const CK_TTL_MS = 30 * 60 * 1000;
const DEGRADED_REDEEM_CK = '__degraded:redeemCusdPlus';
const DEGRADED_CUSD_REDEEM_CK = '__degraded:redeemCusd';
const PENDING_CK_PREFIX = '__pending:';
const PENDING_DEGRADED_CK_PREFIX = '__pendingDegraded:';

interface Checkpoint { ts: number; steps: Record<string, string>; }

const loadCk = async (store: KVStore, key: string): Promise<Record<string, string>> => {
  const raw = await store.get(key);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as Partial<Checkpoint>;
    // No ts = a v1-shaped blob that slipped through; treat as expired.
    const steps = parsed.steps && typeof parsed.steps === 'object' ? parsed.steps : {};
    const hasPending = Object.keys(steps).some((step) => step.startsWith(PENDING_CK_PREFIX));
    const age = typeof parsed?.ts === 'number' ? Date.now() - parsed.ts : Number.POSITIVE_INFINITY;
    // Ordinary checkpoints expire. A broadcast transaction does not: its
    // receipt must be reconciled before a retry can safely use another nonce.
    if (!hasPending && (age < 0 || age > CK_TTL_MS)) {
      await store.del(key);
      return {};
    }
    return steps;
  } catch {
    return {};
  }
};

export const executeBscExit = async (params: {
  wallet: DerivedEvmWallet;
  dest: string;
  vaultAddress: string;
  /** Bundled cUSD proxy. Empty only before cUSD exists in this environment. */
  cusdAddress?: string;
  /** Slippage floor for the IM redeem; caller derives from displayed value. */
  minUsdtOutWei: bigint;
  accountKey: string;
  store: KVStore;
  /**
   * Fires immediately before each on-chain send. The exit can take tens of
   * seconds across multiple transactions, so the screen names what it is waiting
   * on instead of showing one undifferentiated spinner.
   */
  onStep?: (step: BscExitStep) => void;
}): Promise<BscExitResult> => {
  const {
    wallet, dest, vaultAddress, store, accountKey, onStep,
    cusdAddress = BUNDLED_CUSD_ADDRESS,
  } = params;
  if (!/^0x[0-9a-fA-F]{40}$/.test(dest)) throw new Error('bad destination address');
  if (dest.toLowerCase() === wallet.address.toLowerCase()) throw new Error('destination is own address');

  const restore = installEmergencyBscTransport();
  const key = ckKey(accountKey, dest);
  const ck: Record<string, string> = {};
  const completed: string[] = [];
  const degraded: string[] = [];
  const sentNow: string[] = [];
  const unresolved: string[] = [];
  let usdtToDest = 0n;
  let activeStep: string | null = null;
  let activeDegraded = false;

  const record = async (step: string, txid: string) => {
    ck[step] = txid;
    await store.set(key, JSON.stringify({ ts: Date.now(), steps: ck }));
    completed.push(step);
    if (!txid.startsWith('skipped')) sentNow.push(step);
  };
  const resultSoFar = (): BscExitResult => ({
    completed: [...completed],
    txids: Object.fromEntries(Object.entries(ck).filter(([step]) => !step.startsWith('__'))),
    degraded: [...degraded],
    sentNow: [...sentNow],
    usdtToDest: usdtToDest.toString(),
    unresolved: [...unresolved],
  });
  const persistCheckpoint = () =>
    store.set(key, JSON.stringify({ ts: Date.now(), steps: ck }));
  const pendingError = (txHash: string) => Object.assign(
    new Error(`bsc tx still pending: ${txHash}`),
    { broadcast: true, txHash },
  );
  const reconcilePending = async () => {
    for (const [marker, txHash] of Object.entries(ck)) {
      if (!marker.startsWith(PENDING_CK_PREFIX)) continue;
      const step = marker.slice(PENDING_CK_PREFIX.length);
      const receipt = await bscGetTransactionReceipt(txHash);
      if (!receipt) throw pendingError(txHash);

      delete ck[marker];
      const degradedMarker = PENDING_DEGRADED_CK_PREFIX + step;
      const wasDegraded = Boolean(ck[degradedMarker]);
      delete ck[degradedMarker];
      if (receipt.status === '0x1') {
        ck[step] = txHash;
        completed.push(step);
        if (wasDegraded) {
          ck[step === 'redeemCusd' ? DEGRADED_CUSD_REDEEM_CK : DEGRADED_REDEEM_CK] = '1';
        }
        if (!wasDegraded && (step === 'redeemCusdPlus' || step === 'redeemCusd' || step === 'transferUsdt')) {
          usdtToDest += usdtCreditedTo(receipt, dest);
        }
      } else if (receipt.status !== '0x0') {
        // Unknown receipt shape: retain the pending marker and fail closed.
        ck[marker] = txHash;
        if (wasDegraded) ck[degradedMarker] = '1';
        throw pendingError(txHash);
      }
      await persistCheckpoint();
    }
  };

  try {
    // Keep this inside the restoration boundary. Device storage can fail;
    // that must never leave the emergency public-RPC transport installed
    // for the rest of the app session.
    Object.assign(ck, await loadCk(store, key));
    await reconcilePending();
    if (ck[DEGRADED_REDEEM_CK]) degraded.push('redeemCusdPlus');
    if (ck[DEGRADED_CUSD_REDEEM_CK]) degraded.push('redeemCusd');

    // 1. cUSD+ → USDT paid straight to the destination.
    if (!ck.redeemCusdPlus) {
      const shares = await erc20Balance(vaultAddress, wallet.address);
      if (shares > 0n) {
        onStep?.('redeemCusdPlus');
        activeStep = 'redeemCusdPlus';
        activeDegraded = false;
        try {
          const receipt = await sendCall({
            from: wallet.address,
            privKeyHex: wallet.privKeyHex,
            to: vaultAddress,
            data:
              selector('redeemToUsdt(uint256,uint256,address)') +
              encodeUint(shares) +
              encodeUint(params.minUsdtOutWei) +
              encodeAddress(dest),
            gasLimit: 700_000n,
          });
          usdtToDest += usdtCreditedTo(receipt, dest);
          await record('redeemCusdPlus', receipt.transactionHash);
          activeStep = null;
        } catch (e) {
          // A receipt timeout means the redeem was broadcast and can still
          // settle. Sending the raw shares before its outcome is known is an
          // unsafe fallback and can waste the user's remaining emergency gas.
          if (isOutcomeUnknown(e)) throw e;
          // Ondo leg dead (paused vault, tripped guard, IM outage): fall
          // back to a raw share transfer so value at least MOVES, and
          // surface the degradation for the screen's warning.
          activeDegraded = true;
          try {
            const receipt = await sendCall({
              from: wallet.address,
              privKeyHex: wallet.privKeyHex,
              to: vaultAddress,
              data: selector('transfer(address,uint256)') + encodeAddress(dest) + encodeUint(shares),
              gasLimit: 120_000n,
            });
            ck[DEGRADED_REDEEM_CK] = '1';
            if (!degraded.includes('redeemCusdPlus')) degraded.push('redeemCusdPlus');
            await record('redeemCusdPlus', receipt.transactionHash);
          } catch (fallbackError) {
            if (isOutcomeUnknown(fallbackError)) throw fallbackError;
            unresolved.push('cUSD+');
          }
          activeStep = null;
          activeDegraded = false;
        }
      } else {
        await record('redeemCusdPlus', 'skipped_zero');
      }
    }

    // 2. cUSD → USDT paid straight to the destination. Fee-bearing
    // redeemWithFee is intentionally permissionless; fee-free redemption is
    // sponsor-only and is never part of Emergency Exit.
    if (/^0x[0-9a-fA-F]{40}$/.test(cusdAddress) && !ck.redeemCusd) {
      const cusd = await erc20Balance(cusdAddress, wallet.address);
      if (cusd > 0n) {
        onStep?.('redeemCusd');
        activeStep = 'redeemCusd';
        activeDegraded = false;
        try {
          const receipt = await sendCall({
            from: wallet.address,
            privKeyHex: wallet.privKeyHex,
            to: cusdAddress,
            data:
              selector('redeemWithFee(uint256,uint256,address)') +
              encodeUint(cusd) +
              encodeUint(0n) +
              encodeAddress(dest),
            gasLimit: 140_000n,
          });
          usdtToDest += usdtCreditedTo(receipt, dest);
          await record('redeemCusd', receipt.transactionHash);
          activeStep = null;
        } catch (e) {
          if (isOutcomeUnknown(e)) throw e;
          activeDegraded = true;
          try {
            const receipt = await sendCall({
              from: wallet.address,
              privKeyHex: wallet.privKeyHex,
              to: cusdAddress,
              data: selector('transfer(address,uint256)') + encodeAddress(dest) + encodeUint(cusd),
              gasLimit: 120_000n,
            });
            ck[DEGRADED_CUSD_REDEEM_CK] = '1';
            if (!degraded.includes('redeemCusd')) degraded.push('redeemCusd');
            await record('redeemCusd', receipt.transactionHash);
          } catch (fallbackError) {
            if (isOutcomeUnknown(fallbackError)) throw fallbackError;
            unresolved.push('cUSD');
          }
          activeStep = null;
          activeDegraded = false;
        }
      } else {
        await record('redeemCusd', 'skipped_zero');
      }
    }

    // 3. Pre-held USDT (live re-read — never trust the plan snapshot).
    if (!ck.transferUsdt) {
      const usdt = await erc20Balance(USDT_BSC, wallet.address);
      if (usdt > 0n) {
        onStep?.('transferUsdt');
        activeStep = 'transferUsdt';
        activeDegraded = false;
        try {
          const receipt = await sendCall({
            from: wallet.address,
            privKeyHex: wallet.privKeyHex,
            to: USDT_BSC,
            data: selector('transfer(address,uint256)') + encodeAddress(dest) + encodeUint(usdt),
            gasLimit: 80_000n,
          });
          usdtToDest += usdtCreditedTo(receipt, dest);
          await record('transferUsdt', receipt.transactionHash);
        } catch (e) {
          if (isOutcomeUnknown(e)) throw e;
          unresolved.push('USDT');
        }
        activeStep = null;
      } else {
        await record('transferUsdt', 'skipped_zero');
      }
    }

    // 4. Canonical CONFIO-BSC only. A token with the same symbol at any
    // other address is ignored.
    if (!ck.transferConfio) {
      const confio = await erc20Balance(BUNDLED_CONFIO_ADDRESS, wallet.address);
      if (confio > 0n) {
        onStep?.('transferConfio');
        activeStep = 'transferConfio';
        activeDegraded = false;
        try {
          const receipt = await sendCall({
            from: wallet.address,
            privKeyHex: wallet.privKeyHex,
            to: BUNDLED_CONFIO_ADDRESS,
            data: selector('transfer(address,uint256)') + encodeAddress(dest) + encodeUint(confio),
            gasLimit: 80_000n,
          });
          await record('transferConfio', receipt.transactionHash);
        } catch (e) {
          if (isOutcomeUnknown(e)) throw e;
          unresolved.push('CONFIO');
        }
        activeStep = null;
      } else {
        await record('transferConfio', 'skipped_zero');
      }
    }

    // 5. Every official Ondo Stock known to this app release. The registry
    // is compiled into the client; symbols are labels only and arbitrary
    // wallet tokens are never inspected or transferred.
    const stocks = await readBundledOndoStockHoldings(wallet.address);
    for (const stock of stocks) {
      const step = stockStep(stock);
      if (ck[step]) continue;
      onStep?.(step);
      activeStep = step;
      activeDegraded = false;
      let receipt: Awaited<ReturnType<typeof sendCall>>;
      try {
        receipt = await sendCall({
          from: wallet.address,
          privKeyHex: wallet.privKeyHex,
          to: stock.address,
          data: selector('transfer(address,uint256)') + encodeAddress(dest) + encodeUint(stock.balanceWei),
        });
      } catch (e) {
        // Do not advance to another nonce while a broadcast transaction can
        // still mine. The user must reconcile that hash first.
        if (isOutcomeUnknown(e)) throw e;
        // Continue with the other stocks. Completed sends are checkpointed;
        // a retry re-reads balances and attempts only what remains.
        unresolved.push(stock.symbol);
        activeStep = null;
        continue;
      }
      // Keep checkpoint failures outside the transfer catch. The token did
      // move; reporting it as a failed stock transfer would be false.
      await record(step, receipt.transactionHash);
      activeStep = null;
    }
    // Every step resolved, so this attempt is over: drop the checkpoint.
    // Leaving it is what made the SECOND exit to the same destination a
    // silent no-op that still reported success. Re-running with a stale
    // balance is not a double-spend risk — each step re-reads live
    // balances and the chain enforces the rest.
    if (unresolved.length) {
      await persistCheckpoint();
    } else {
      await store.del(key);
    }
  } catch (e) {
    if (isOutcomeUnknown(e) && activeStep && typeof (e as any)?.txHash === 'string') {
      ck[PENDING_CK_PREFIX + activeStep] = (e as any).txHash;
      if (activeDegraded) ck[PENDING_DEGRADED_CK_PREFIX + activeStep] = '1';
      try {
        await persistCheckpoint();
      } catch (checkpointError) {
        // Preserve the broadcast/unknown error and hash for the UI. Replacing
        // it with a storage error would wrongly invite an immediate retry.
        (e as any).checkpointError = checkpointError;
      }
    }
    // A later leg can fail after earlier assets already moved. Carry those
    // receipts to the screen so the user can verify reality instead of seeing
    // a generic error that hides successful transactions.
    if (e && typeof e === 'object') {
      (e as any).partialResult = resultSoFar();
    }
    throw e;
  } finally {
    restore();
  }

  return resultSoFar();
};
