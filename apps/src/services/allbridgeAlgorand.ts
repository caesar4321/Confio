// Allbridge Core deposit tail for the Ahorrar leg-AB atomic group.
//
// Builds the 5 transactions that follow the cUSD burn inside ONE Algorand
// group (ORCHESTRATION.md §1): [bridge-fee payment, USDC axfer → bridge app,
// swapAndBridge ABI call, padding call ×2]. ARC-4 resolves the two txn
// references by relative position (immediately before the app call), and
// cusd.py's burn uses relative indexing — so prefixing the sponsored burn
// transactions in front composes cleanly with no contract changes.
//
// Ported from @allbridge/bridge-core-sdk dist/src/services/bridge/alg
// (the SDK itself would drag algokit/web3/tronweb into Metro). Structural
// parity is checked by apps/scripts/validate-allbridge-alg-builder.mts.
//
// Live wiring (bridge app id, padding app id, chain ids) comes from the
// same /token-info snapshot the quote service uses — never hardcoded, so an
// Allbridge redeploy can't silently strand us.

import algosdk from 'algosdk';
import { randomBytes } from '@noble/hashes/utils';

const CORE_API = 'https://core.api.allbridgecoreapi.net';

// swapAndBridge(paymentRef, assetTransferRef, recipient, destinationChainId,
//               receiveToken, nonce, budget)void — ARC-56 spec from the SDK's
// BridgeClient; `budget` has a default of 1000 which the typed client fills.
const SWAP_AND_BRIDGE = algosdk.ABIMethod.fromSignature(
  'swapAndBridge(pay,axfer,byte[32],byte,byte[32],byte[32],uint64)void',
);
const SWAP_AND_BRIDGE_BUDGET = 1000n;

/** The SDK adds extraFee = 8 inner txns to the app call (feeForInner(8)). */
const INNER_TXNS = 8n;

export interface AllbridgeAlgConfig {
  bridgeAppId: bigint;
  bridgeAppAddress: string;
  paddingUtilAppId: bigint;
  sourceChainId: number; // ALG = 15
  destChainId: number; // BSC = 2
  usdcAssetId: bigint; // 31566704 on mainnet
  usdtBscAddress: string; // receive token on BSC
}

/** Bridge wiring from /token-info — same snapshot family as the quotes. */
export const fetchAllbridgeAlgConfig = async (): Promise<AllbridgeAlgConfig> => {
  const res = await fetch(`${CORE_API}/token-info`);
  if (!res.ok) throw new Error(`allbridge token-info ${res.status}`);
  const data = await res.json();
  const alg = data.ALG;
  const usdc = (alg?.tokens || []).find((t: any) => t.symbol === 'USDC');
  const usdtBsc = (data.BSC?.tokens || []).find((t: any) => t.symbol === 'USDT');
  if (!alg?.bridgeId || !alg?.paddingUtilId || !usdc || !usdtBsc) {
    throw new Error('allbridge: ALG bridge wiring missing from token-info');
  }
  return {
    bridgeAppId: BigInt(alg.bridgeId),
    bridgeAppAddress: alg.bridgeAddress,
    paddingUtilAppId: BigInt(alg.paddingUtilId),
    sourceChainId: alg.chainId,
    destChainId: data.BSC.chainId,
    usdcAssetId: BigInt(usdc.tokenAddress),
    usdtBscAddress: usdtBsc.tokenAddress,
  };
};

/** Messenger fee (paid in microAlgo with the payment txn). messenger=1 = Allbridge. */
export const fetchBridgeFeeMicroAlgo = async (
  sourceChainId: number,
  destChainId: number,
): Promise<bigint> => {
  const res = await fetch(`${CORE_API}/receive-fee`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sourceChainId,
      destinationChainId: destChainId,
      messenger: 1,
    }),
  });
  if (!res.ok) throw new Error(`allbridge receive-fee ${res.status}`);
  const json = await res.json();
  return BigInt(json.fee);
};

const evmAddressToBytes32 = (address: string): Uint8Array => {
  const hex = address.replace(/^0x/i, '').toLowerCase();
  const out = new Uint8Array(32);
  const raw = new Uint8Array(hex.length / 2);
  for (let i = 0; i < raw.length; i++) {
    raw[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  out.set(raw, 32 - raw.length); // left zero-padded, like the SDK
  return out;
};

export interface DepositTailParams {
  sender: string; // user.algo — owns the USDC released by the burn
  usdcAmountMicro: bigint; // exactly the burn output (1:1 with cUSD burned)
  destBscAddress: string; // user.bsc (evmWallet.ts) — never a treasury
  feeMicroAlgo: bigint; // from fetchBridgeFeeMicroAlgo (sponsor tops this up)
  suggestedParams: algosdk.SuggestedParams;
  config: AllbridgeAlgConfig;
}

/**
 * The five deposit transactions, unsigned and ungrouped — the caller
 * concatenates [sponsored burn txns, ...this tail] and assigns one group id.
 * Every sender is the USER (non-custodial); the sponsor only adds fee/ALGO
 * top-ups in the burn prefix.
 */
export const buildAllbridgeDepositTail = (
  p: DepositTailParams,
): algosdk.Transaction[] => {
  const { sender, config, suggestedParams } = p;

  const feePay = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
    sender,
    receiver: config.bridgeAppAddress,
    amount: p.feeMicroAlgo,
    suggestedParams,
  });

  const usdcTransfer = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
    sender,
    receiver: config.bridgeAppAddress,
    amount: p.usdcAmountMicro,
    assetIndex: config.usdcAssetId,
    suggestedParams,
  });

  // App call carries its own fee plus 8 inner txns' worth (SDK parity).
  const appCallParams: algosdk.SuggestedParams = {
    ...suggestedParams,
    flatFee: true,
    fee: BigInt(suggestedParams.minFee) * (1n + INNER_TXNS),
  };
  const appCall = algosdk.makeApplicationCallTxnFromObject({
    sender,
    appIndex: config.bridgeAppId,
    onComplete: algosdk.OnApplicationComplete.NoOpOC,
    suggestedParams: appCallParams,
    appArgs: [
      SWAP_AND_BRIDGE.getSelector(),
      evmAddressToBytes32(p.destBscAddress), // recipient (byte[32])
      new Uint8Array([config.destChainId]), // destinationChainId (byte)
      evmAddressToBytes32(config.usdtBscAddress), // receiveToken (byte[32])
      randomBytes(32), // nonce (byte[32])
      algosdk.encodeUint64(SWAP_AND_BRIDGE_BUDGET), // budget (uint64)
    ],
    foreignAssets: [config.usdcAssetId],
  });

  // Two padding no-op calls (SDK parity: extra opcode budget for the bridge).
  const padding = (note: string) =>
    algosdk.makeApplicationCallTxnFromObject({
      sender,
      appIndex: config.paddingUtilAppId,
      onComplete: algosdk.OnApplicationComplete.NoOpOC,
      suggestedParams,
      note: new TextEncoder().encode(note),
    });

  return [feePay, usdcTransfer, appCall, padding('padding1'), padding('padding2')];
};

// ── Simulate-driven resource population ─────────────────────────────────
// The bridge app reads boxes whose names embed the NONCE (plus messenger
// state), so resource references cannot be hardcoded — the SDK solves this
// with algokit's populateAppCallResources; we do the same with a lean
// fetch+msgpack round-trip against algod's /simulate (RN-friendly, and it
// doubles as the pre-flight check before the user signs).

export interface AlgodSim {
  baseUrl: string; // e.g. https://mainnet-api.4160.nodely.dev
  token?: string;
}

const simulateGroup = async (
  algod: AlgodSim,
  txns: algosdk.Transaction[],
  allowUnnamed: boolean,
): Promise<algosdk.modelsv2.SimulateResponse> => {
  const clones = txns.map((t) =>
    algosdk.decodeUnsignedTransaction(algosdk.encodeUnsignedTransaction(t)),
  );
  if (clones.length > 1) algosdk.assignGroupID(clones);
  const request = new algosdk.modelsv2.SimulateRequest({
    txnGroups: [
      new algosdk.modelsv2.SimulateRequestTransactionGroup({
        txns: clones.map((txn) => new algosdk.SignedTransaction({ txn })),
      }),
    ],
    allowEmptySignatures: true,
    allowUnnamedResources: allowUnnamed,
  });
  const res = await fetch(`${algod.baseUrl}/v2/transactions/simulate?format=msgpack`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/msgpack',
      ...(algod.token ? { 'X-Algo-API-Token': algod.token } : {}),
    },
    body: algosdk.encodeMsgpack(request),
  });
  if (!res.ok) {
    throw new Error(`algod simulate ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
  const bytes = new Uint8Array(await res.arrayBuffer());
  return algosdk.decodeMsgpack(bytes, algosdk.modelsv2.SimulateResponse);
};

interface ResourceUnit {
  kind: 'app' | 'account' | 'asset' | 'box' | 'holding' | 'local';
  app?: bigint;
  account?: string;
  asset?: bigint;
  boxName?: Uint8Array;
}

const collectUnits = (
  r?: algosdk.modelsv2.SimulateUnnamedResourcesAccessed,
): ResourceUnit[] => {
  if (!r) return [];
  const units: ResourceUnit[] = [];
  (r.apps || []).forEach((a) => units.push({ kind: 'app', app: BigInt(a) }));
  (r.accounts || []).forEach((a) => units.push({ kind: 'account', account: a.toString() }));
  (r.assets || []).forEach((a) => units.push({ kind: 'asset', asset: BigInt(a) }));
  (r.boxes || []).forEach((b) =>
    units.push({ kind: 'box', app: BigInt(b.app), boxName: b.name }),
  );
  // AVM rule: a holding (account x asset) or local (account x app) is only
  // group-available when BOTH parts are referenced by the SAME transaction —
  // keep them as atomic pairs, never decomposed (splitting them across txns
  // is exactly the "unavailable Holding" simulate failure).
  (r.appLocals || []).forEach((al) =>
    units.push({ kind: 'local', account: al.account.toString(), app: BigInt(al.app) }),
  );
  (r.assetHoldings || []).forEach((ah) =>
    units.push({ kind: 'holding', account: ah.account.toString(), asset: BigInt(ah.asset) }),
  );
  return units;
};

const MAX_REFS_PER_TXN = 8;
const MAX_ACCOUNTS_PER_TXN = 4;

/**
 * Simulate with unnamed resources allowed, then rebuild the group's app-call
 * transactions carrying every discovered reference (boxes paired with their
 * app id in the same txn, per AVM rules). The padding calls exist precisely
 * to hold the overflow. Returns REBUILT transactions, ungrouped — assign the
 * final group id (with any burn prefix) afterwards.
 */
export const populateDepositResources = async (
  algod: AlgodSim,
  txns: algosdk.Transaction[],
): Promise<algosdk.Transaction[]> => {
  const sim = await simulateGroup(algod, txns, true);
  const group = sim.txnGroups[0];
  if (group.failureMessage) {
    throw new Error(`allbridge deposit simulate failed: ${group.failureMessage}`);
  }

  // Per-txn units keep their index; group-level units float.
  const floating: ResourceUnit[] = collectUnits(group.unnamedResourcesAccessed);
  const perTxn: ResourceUnit[][] = (group.txnResults || []).map((tr) =>
    collectUnits(tr.unnamedResourcesAccessed),
  );

  // Capacity accounting per app-call txn.
  type Slot = {
    idx: number;
    apps: bigint[];
    accounts: string[];
    assets: bigint[];
    boxes: { app: bigint; name: Uint8Array }[];
  };
  const slots: Slot[] = [];
  txns.forEach((t, idx) => {
    if (t.type === algosdk.TransactionType.appl) {
      slots.push({
        idx,
        apps: [...(t.applicationCall?.foreignApps || [])].map((x) => BigInt(x)),
        accounts: [...(t.applicationCall?.accounts || [])].map((x) => x.toString()),
        assets: [...(t.applicationCall?.foreignAssets || [])].map((x) => BigInt(x)),
        boxes: [...(t.applicationCall?.boxes || [])].map((b) => ({
          app: BigInt(b.appIndex),
          name: b.name,
        })),
      });
    }
  });
  const used = (s: Slot) =>
    s.apps.length + s.accounts.length + s.assets.length + s.boxes.length;

  // Cost of adding a unit to a slot; pairs count their missing parts.
  const costIn = (s: Slot, unit: ResourceUnit): number => {
    const ownApp = BigInt(txns[s.idx].applicationCall?.appIndex ?? 0n);
    const hasApp = unit.app == null || s.apps.includes(unit.app) || ownApp === unit.app;
    const hasAccount = unit.account == null || s.accounts.includes(unit.account);
    const hasAsset = unit.asset == null || s.assets.includes(unit.asset);
    switch (unit.kind) {
      case 'app': return hasApp ? 0 : 1;
      case 'account': return hasAccount ? 0 : 1;
      case 'asset': return hasAsset ? 0 : 1;
      case 'box': return (hasApp ? 0 : 1) + 1;
      case 'holding': return (hasAccount ? 0 : 1) + (hasAsset ? 0 : 1);
      case 'local': return (hasAccount ? 0 : 1) + (hasApp ? 0 : 1);
    }
  };

  const addTo = (s: Slot, unit: ResourceUnit) => {
    const ownApp = BigInt(txns[s.idx].applicationCall?.appIndex ?? 0n);
    if (unit.app != null && unit.app !== ownApp && !s.apps.includes(unit.app)) {
      if (unit.kind !== 'account' && unit.kind !== 'asset' && unit.kind !== 'holding') {
        s.apps.push(unit.app);
      }
    }
    if (unit.account != null && !s.accounts.includes(unit.account)) s.accounts.push(unit.account);
    if (unit.asset != null && !s.assets.includes(unit.asset)) s.assets.push(unit.asset);
    if (unit.kind === 'box') s.boxes.push({ app: unit.app!, name: unit.boxName! });
    if (unit.kind === 'app' && !s.apps.includes(unit.app!) && unit.app !== ownApp) {
      s.apps.push(unit.app!);
    }
  };

  const fits = (s: Slot, unit: ResourceUnit): boolean => {
    if (used(s) + costIn(s, unit) > MAX_REFS_PER_TXN) return false;
    const addsAccount = unit.account != null && !s.accounts.includes(unit.account);
    if (addsAccount && s.accounts.length >= MAX_ACCOUNTS_PER_TXN) return false;
    return true;
  };

  const place = (unit: ResourceUnit, hardIdx?: number) => {
    if (hardIdx != null) {
      // Per-txn resources are pinned to their own transaction (algokit
      // parity) — moving them can break pair availability rules.
      const s = slots.find((x) => x.idx === hardIdx);
      if (!s || !fits(s, unit)) {
        throw new Error('allbridge deposit: per-txn resource does not fit its transaction');
      }
      addTo(s, unit);
      return;
    }
    const ordered = [...slots].sort((a, b) => used(a) - used(b));
    for (const s of ordered) {
      if (fits(s, unit)) {
        addTo(s, unit);
        return;
      }
    }
    throw new Error('allbridge deposit: resource references exceed group capacity');
  };

  perTxn.forEach((units, i) => units.forEach((u) => place(u, i)));
  floating.forEach((u) => place(u));

  // Rebuild app calls with their final resource arrays.
  const rebuilt = [...txns];
  for (const s of slots) {
    const t = txns[s.idx];
    const ac = t.applicationCall!;
    rebuilt[s.idx] = algosdk.makeApplicationCallTxnFromObject({
      sender: t.sender.toString(),
      appIndex: ac.appIndex,
      onComplete: algosdk.OnApplicationComplete.NoOpOC,
      suggestedParams: {
        minFee: 1000n, // unused with flatFee
        flatFee: true,
        fee: t.fee,
        firstValid: t.firstValid,
        lastValid: t.lastValid,
        genesisHash: t.genesisHash,
        genesisID: t.genesisID,
      },
      appArgs: [...ac.appArgs],
      note: t.note && t.note.length ? t.note : undefined,
      foreignApps: s.apps,
      foreignAssets: s.assets,
      accounts: s.accounts,
      boxes: s.boxes.map((b) => ({ appIndex: b.app, name: b.name })),
    });
  }
  return rebuilt;
};

/** Pre-flight: the group must simulate clean with ONLY named resources. */
export const assertGroupSimulates = async (
  algod: AlgodSim,
  txns: algosdk.Transaction[],
): Promise<void> => {
  const sim = await simulateGroup(algod, txns, false);
  const group = sim.txnGroups[0];
  if (group.failureMessage) {
    throw new Error(`group pre-flight failed: ${group.failureMessage}`);
  }
};
