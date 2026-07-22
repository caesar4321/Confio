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
// TODO(phase 2, redeem-first): compose the non-sponsored cUSD burn group
// ([cUSD axfer → app, burn_for_collateral call]) so cUSD exits as USDC.
// Until then cUSD transfers raw and the screen shows the redemption-tool
// warning (design doc §3 fallback).
//
// Resumable: completed steps record their txid in the injected KV store;
// re-runs skip them and re-read live balances before every remaining step.

import { CHAIN_ENDPOINTS } from './chainClock';
import type { KVStore } from './reachability';

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

export type AlgoExitStep = { kind: 'assetTransfer'; assetId: number; amountMicro: bigint };

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

  for (const a of account.assets) {
    if (a.amountMicro === 0n) continue;
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

const stepId = (s: AlgoExitStep): string => `${s.kind}_${s.assetId}`;

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
}

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

  for (const step of plan.steps) {
    const id = stepId(step);
    if (ck[id]) continue;

    const sp = await suggestedParams(sdk);
    // Live re-read: the plan's amount may be stale after a resume.
    const live = await fetchAlgoAccount(address);
    const bal = live.assets.find((a) => a.id === step.assetId)?.amountMicro ?? 0n;
    if (bal === 0n) { ck[id] = 'skipped_zero'; await store.set(key, JSON.stringify(ck)); continue; }
    const txn = sdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
      sender: address, receiver: dest, assetIndex: step.assetId, amount: bal, suggestedParams: sp,
    });

    const signed = await sign(txn.toByte());
    const txid = await submitAndConfirm(signed);
    ck[id] = txid;
    await store.set(key, JSON.stringify(ck));
    completed.push(id);
  }

  return { completed, txids: ck, destMissingOptIns: plan.destMissingOptIns };
};
