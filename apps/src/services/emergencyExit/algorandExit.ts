// Algorand leg of the emergency exit (docs/plans/salida-de-emergencia-design.md).
//
// This module is THE sanctioned exception to the app-wide rule in
// algorandService.ts ("we intentionally do NOT create any direct Algod
// client"): the emergency path exists precisely for when Confío's backend
// is dark, so it composes, signs and broadcasts through public algod
// endpoints with failover. Zero GraphQL.
//
// Direct mode fees are the user's own (flat min fee per txn) — the
// contract-side non-sponsored forms were verified in cusd.py.
//
// Asset transfers ONLY — no close-out, no ALGO sweep (decisions
// 2026-07-22). MBR is SPONSOR money, so a close-out would be the exact
// farming primitive the subsidy policy flags, and would permanently flag
// legit returning users (same derived address) as farmers. And a
// spendable-ALGO sweep isn't worth existing either: normal accounts hold
// ~zero spendable ALGO (auto-convert cleans mis-deposits; the sponsor
// funds exact MBR shortfalls), so a sweep would only ever move a Direct-
// mode gas top-up's leftover cents — which are MORE useful left behind:
// the account stays alive, and stray future deposits to the old address
// (old QRs, saved contacts) can be moved later using that leftover gas.
// Net result: the exit moves ZERO native ALGO, so it cannot interact
// with the farming detector at all.
//
// Redeem-first: cUSD exits as USDC via the non-sponsored burn group
// ([cUSD axfer → app, burn_for_collateral app call]) — "permissionless ≠
// accessible": no external wallet can compose this group, so we do it
// BEFORE the assets leave. Falls back to a raw cUSD transfer (degraded,
// screen warns) when the burn is impossible (below MIN_BURN, missing
// opt-ins) or reverts (paused/frozen).
//
// Resumable: completed steps record their txid in the injected KV store;
// re-runs skip them and re-read live balances before every remaining step.

import { CHAIN_ENDPOINTS } from './chainClock';
import type { KVStore } from './reachability';

// Bundled mainnet wiring (design doc: chain wiring ships in the app
// bundle — the config queries that normally serve it are dead in an
// outage). Verified against .env.mainnet 2026-07-22.
export const CUSD_APP_ID = 3198259271;
export const CUSD_ASSET_ID = 3198259450;
export const USDC_ASSET_ID = 31566704;
// Contract's MIN_BURN (cusd.py): burns below 1 cUSD revert.
const MIN_BURN_MICRO = 1_000_000n;

// ── Public algod REST with failover ─────────────────────────────────────

const algod = async (path: string, init?: RequestInit): Promise<any> => {
  let lastErr: unknown;
  for (const node of CHAIN_ENDPOINTS.ALGOD_NODES) {
    try {
      const res = await fetch(`${node}${path}`, init);
      if (!res.ok) throw new Error(`algod ${path} http ${res.status}`);
      return await res.json();
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error('all algod endpoints failed');
};

export interface AlgoAccountState {
  address: string;
  amountMicro: bigint;
  minBalanceMicro: bigint;
  assets: Array<{ id: number; amountMicro: bigint }>;
  appLocalStateIds: number[];
}

export const fetchAlgoAccount = async (address: string): Promise<AlgoAccountState> => {
  const info = await algod(`/v2/accounts/${address}`);
  return {
    address,
    amountMicro: BigInt(info.amount ?? 0),
    minBalanceMicro: BigInt(info['min-balance'] ?? 0),
    assets: (info.assets ?? []).map((a: any) => ({
      id: Number(a['asset-id']),
      amountMicro: BigInt(a.amount ?? 0),
    })),
    appLocalStateIds: (info['apps-local-state'] ?? []).map((s: any) => Number(s.id)),
  };
};

// ── Plan (pure — jest-covered) ──────────────────────────────────────────

export type AlgoExitStep =
  | { kind: 'assetTransfer'; assetId: number; amountMicro: bigint }
  | { kind: 'burnCusd'; amountMicro: bigint };

export interface AlgoExitPlan {
  steps: AlgoExitStep[];
  /** Assets the destination has not opted into — their steps are blocked. */
  destMissingOptIns: number[];
}

export const planAlgorandExit = (
  account: AlgoAccountState,
  destOptedAssetIds: number[],
): AlgoExitPlan => {
  const destSet = new Set(destOptedAssetIds);
  const steps: AlgoExitStep[] = [];
  const destMissingOptIns: number[] = [];

  // Redeem-first: burn cUSD → USDC when every prerequisite holds. The
  // burn's USDC lands at the OWN address, so it requires the destination
  // to accept USDC — otherwise burning would just strand a different
  // asset, and the raw-cUSD path is strictly better.
  const cusd = account.assets.find((a) => a.id === CUSD_ASSET_ID);
  const selfHoldsUsdc = account.assets.some((a) => a.id === USDC_ASSET_ID);
  const burnable =
    !!cusd &&
    cusd.amountMicro >= MIN_BURN_MICRO &&
    selfHoldsUsdc &&
    destSet.has(USDC_ASSET_ID) &&
    account.appLocalStateIds.includes(CUSD_APP_ID);
  if (burnable) steps.push({ kind: 'burnCusd', amountMicro: cusd!.amountMicro });

  for (const a of account.assets) {
    if (burnable && a.id === CUSD_ASSET_ID) continue; // burned, not transferred
    // USDC must be planned even at zero pre-balance: the burn's output
    // arrives before this step's live re-read.
    if (a.amountMicro === 0n && !(burnable && a.id === USDC_ASSET_ID)) continue;
    if (!destSet.has(a.id)) {
      destMissingOptIns.push(a.id);
      continue; // blocked until the destination opts in — never burn value
    }
    steps.push({ kind: 'assetTransfer', assetId: a.id, amountMicro: a.amountMicro });
  }

  return { steps, destMissingOptIns };
};

// ── Execution ───────────────────────────────────────────────────────────

export type AlgoSigner = (txnBytes: Uint8Array) => Promise<Uint8Array>;

const ckKey = (accountKey: string, dest: string) =>
  `confio_emergency_algo_ck_v1_${accountKey}_${dest}`;

const stepId = (s: AlgoExitStep): string =>
  s.kind === 'burnCusd' ? s.kind : `${s.kind}_${s.assetId}`;

const suggestedParams = async (sdk: any) => {
  const p = await algod('/v2/transactions/params');
  return {
    flatFee: true,
    fee: BigInt(p['min-fee'] ?? 1000),
    minFee: BigInt(p['min-fee'] ?? 1000),
    firstValid: BigInt(p['last-round']),
    lastValid: BigInt(p['last-round']) + 1000n,
    genesisID: p['genesis-id'],
    genesisHash: sdk.base64ToBytes(p['genesis-hash']),
  };
};

const submitAndConfirm = async (signed: Uint8Array): Promise<string> => {
  let lastErr: unknown;
  let txId: string | null = null;
  for (const node of CHAIN_ENDPOINTS.ALGOD_NODES) {
    try {
      const res = await fetch(`${node}/v2/transactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-binary' },
        body: signed,
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json?.message || `submit http ${res.status}`);
      txId = json.txId;
      break;
    } catch (e) {
      lastErr = e;
    }
  }
  if (!txId) throw lastErr instanceof Error ? lastErr : new Error('submit failed on all nodes');

  for (let i = 0; i < 20; i++) {
    const pend = await algod(`/v2/transactions/pending/${txId}`);
    if (pend['pool-error']) throw new Error(`rejected: ${pend['pool-error']}`);
    if ((pend['confirmed-round'] ?? 0) > 0) return txId;
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error(`confirmation timeout for ${txId}`);
};

export interface AlgoExitResult {
  completed: string[];
  txids: Record<string, string>;
  destMissingOptIns: number[];
  /** Steps that ran in fallback form (burn reverted → raw cUSD transfer). */
  degraded: string[];
}

/** Non-sponsored burn group: [cUSD axfer → app, burn_for_collateral call].
 * Mirrors the proven server builder's app-call shape (foreign assets
 * [USDC, cUSD], user in accounts, 4×min fee — contract asserts ≥3× for
 * the inner clawback + USDC payout). Returns the group's first txid. */
const submitBurnGroup = async (
  sdk: any, address: string, amountMicro: bigint, sign: AlgoSigner,
): Promise<string> => {
  const sp = await suggestedParams(sdk);
  const appAddress = sdk.getApplicationAddress(CUSD_APP_ID);
  const axfer = sdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
    sender: address, receiver: appAddress, assetIndex: CUSD_ASSET_ID,
    amount: amountMicro, suggestedParams: sp,
  });
  const method = new sdk.ABIMethod({ name: 'burn_for_collateral', args: [], returns: { type: 'void' } });
  const appCall = sdk.makeApplicationNoOpTxnFromObject({
    sender: address, appIndex: CUSD_APP_ID,
    appArgs: [method.getSelector()],
    foreignAssets: [USDC_ASSET_ID, CUSD_ASSET_ID],
    accounts: [address],
    suggestedParams: { ...sp, fee: sp.minFee * 4n },
  });
  sdk.assignGroupID([axfer, appCall]);
  const signed: Uint8Array[] = [await sign(axfer.toByte()), await sign(appCall.toByte())];
  const blob = new Uint8Array(signed[0].length + signed[1].length);
  blob.set(signed[0], 0);
  blob.set(signed[1], signed[0].length);
  return submitAndConfirm(blob);
};

export const executeAlgorandExit = async (params: {
  address: string;
  dest: string;
  sign: AlgoSigner;
  accountKey: string;
  store: KVStore;
}): Promise<AlgoExitResult> => {
  const sdk: any = await import('algosdk');
  const { address, dest, sign, store, accountKey } = params;
  if (!sdk.isValidAddress(dest)) throw new Error('bad destination address');
  if (dest === address) throw new Error('destination is own address');

  const [account, destAccount] = await Promise.all([
    fetchAlgoAccount(address),
    fetchAlgoAccount(dest).catch(() => null), // brand-new address: zero opt-ins
  ]);
  const destOpted = destAccount ? destAccount.assets.map((a) => a.id) : [];
  const plan = planAlgorandExit(account, destOpted);

  const key = ckKey(accountKey, dest);
  const raw = await store.get(key);
  const ck: Record<string, string> = raw ? JSON.parse(raw) : {};
  const completed: string[] = [];
  const degraded: string[] = [];
  const record = async (id: string, txid: string) => {
    ck[id] = txid;
    await store.set(key, JSON.stringify(ck));
    completed.push(id);
  };

  for (const step of plan.steps) {
    const id = stepId(step);
    if (ck[id]) continue;

    // Live re-read: the plan's amounts may be stale after a resume.
    const live = await fetchAlgoAccount(address);

    if (step.kind === 'burnCusd') {
      const bal = live.assets.find((a) => a.id === CUSD_ASSET_ID)?.amountMicro ?? 0n;
      if (bal < MIN_BURN_MICRO) { await record(id, 'skipped_below_min'); continue; }
      try {
        await record(id, await submitBurnGroup(sdk, address, bal, sign));
      } catch (e) {
        // Burn reverted (paused contract, frozen address, drained
        // reserves): degrade to a raw cUSD transfer when the destination
        // accepts it, so value still MOVES; surface for the screen.
        if (!destOpted.includes(CUSD_ASSET_ID)) throw e;
        const sp = await suggestedParams(sdk);
        const txn = sdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
          sender: address, receiver: dest, assetIndex: CUSD_ASSET_ID, amount: bal, suggestedParams: sp,
        });
        await record(id, await submitAndConfirm(await sign(txn.toByte())));
        degraded.push(id);
      }
      continue;
    }

    const bal = live.assets.find((a) => a.id === step.assetId)?.amountMicro ?? 0n;
    if (bal === 0n) { await record(id, 'skipped_zero'); continue; }
    const sp = await suggestedParams(sdk);
    const txn = sdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
      sender: address, receiver: dest, assetIndex: step.assetId, amount: bal, suggestedParams: sp,
    });
    await record(id, await submitAndConfirm(await sign(txn.toByte())));
  }

  return { completed, txids: ck, destMissingOptIns: plan.destMissingOptIns, degraded };
};
