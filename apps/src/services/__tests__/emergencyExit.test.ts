// Pure-logic coverage for the emergency exit: the reachability timing
// policy and the Algorand exit planner. Execution paths (RPC, signing)
// are covered by the disaster drill, not unit tests.

import {
  classifyReachability,
  OUTAGE_IMMEDIATE_SECONDS,
} from '../emergencyExit/reachability';
import {
  planAlgorandExit, AlgoAccountState, CUSD_APP_ID, CUSD_ASSET_ID, USDC_ASSET_ID,
} from '../emergencyExit/algorandExit';

const T0 = 1_800_000_000;

describe('classifyReachability', () => {
  it('normal state resets the outage window', () => {
    const r = classifyReachability({
      confioOk: true, chainOk: true, prevOutageStartSec: T0, chainNowSec: T0 + 999,
    });
    expect(r.state).toBe('normal');
    expect(r.outageStartSec).toBeNull();
    expect(r.immediate).toBe(false);
  });

  it('fresh outage starts the window at chain-now, not immediate', () => {
    const r = classifyReachability({
      confioOk: false, chainOk: true, prevOutageStartSec: null, chainNowSec: T0,
    });
    expect(r.state).toBe('outage');
    expect(r.outageStartSec).toBe(T0);
    expect(r.immediate).toBe(false);
  });

  it('outage past 24h (chain time) unlocks immediate exit', () => {
    const r = classifyReachability({
      confioOk: false, chainOk: true,
      prevOutageStartSec: T0, chainNowSec: T0 + OUTAGE_IMMEDIATE_SECONDS,
    });
    expect(r.immediate).toBe(true);
    expect(r.prominent).toBe(true);
  });

  it('full offline neither advances nor resets the window', () => {
    const r = classifyReachability({
      confioOk: false, chainOk: false, prevOutageStartSec: T0, chainNowSec: null,
    });
    expect(r.state).toBe('offline');
    expect(r.outageStartSec).toBe(T0); // preserved
    expect(r.immediate).toBe(false);
  });

  it('explicit ban is immediate regardless of everything else', () => {
    const r = classifyReachability({
      confioOk: true, chainOk: true, prevOutageStartSec: null, chainNowSec: T0, banned: true,
    });
    expect(r.state).toBe('banned');
    expect(r.immediate).toBe(true);
  });
});

describe('planAlgorandExit', () => {
  const CUSD = 1001, CONFIO = 1002, USDC = 1003;
  const account: AlgoAccountState = {
    address: 'SELF',
    amountMicro: 1_500_000n,
    minBalanceMicro: 400_000n,
    assets: [
      { id: CUSD, amountMicro: 25_000_000n },
      { id: CONFIO, amountMicro: 0n },
      { id: USDC, amountMicro: 3_000_000n },
    ],
    appLocalStateIds: [77],
  };

  it('moves exactly the funded assets, nothing else', () => {
    const plan = planAlgorandExit(account, [CUSD, USDC]);
    expect(plan.steps).toEqual([
      { kind: 'assetTransfer', assetId: CUSD, amountMicro: 25_000_000n },
      { kind: 'assetTransfer', assetId: USDC, amountMicro: 3_000_000n },
    ]);
    expect(plan.destMissingOptIns).toEqual([]);
  });

  it('funded asset with no destination opt-in is blocked, never burned', () => {
    const plan = planAlgorandExit(account, [CUSD]);
    expect(plan.destMissingOptIns).toEqual([USDC]);
    expect(plan.steps.find((s) => s.assetId === USDC)).toBeUndefined();
  });

  it('never emits native-ALGO or close-out steps — zero sponsor money moves', () => {
    // Close-outs (sponsor MBR → dest) and ALGO sweeps are the farming
    // primitives; they must be unrepresentable in the plan for any input.
    const plan = planAlgorandExit(account, [CUSD, CONFIO, USDC]);
    expect(new Set(plan.steps.map((s) => s.kind))).toEqual(new Set(['assetTransfer']));
  });

  describe('redeem-first cUSD burn', () => {
    const withCusd = (cusdMicro: bigint, opts: { selfUsdc?: boolean; app?: boolean } = {}): AlgoAccountState => ({
      address: 'SELF',
      amountMicro: 1_500_000n,
      minBalanceMicro: 400_000n,
      assets: [
        { id: CUSD_ASSET_ID, amountMicro: cusdMicro },
        ...(opts.selfUsdc === false ? [] : [{ id: USDC_ASSET_ID, amountMicro: 0n }]),
      ],
      appLocalStateIds: opts.app === false ? [] : [CUSD_APP_ID],
    });

    it('burns when every prerequisite holds, then moves the USDC output', () => {
      const plan = planAlgorandExit(withCusd(5_000_000n), [CUSD_ASSET_ID, USDC_ASSET_ID]);
      expect(plan.steps).toEqual([
        { kind: 'burnCusd', amountMicro: 5_000_000n },
        // zero pre-balance USDC is still planned: the burn output arrives
        // before this step's live re-read.
        { kind: 'assetTransfer', assetId: USDC_ASSET_ID, amountMicro: 0n },
      ]);
    });

    it('falls back to raw cUSD transfer when the destination rejects USDC', () => {
      const plan = planAlgorandExit(withCusd(5_000_000n), [CUSD_ASSET_ID]);
      expect(plan.steps).toEqual([
        { kind: 'assetTransfer', assetId: CUSD_ASSET_ID, amountMicro: 5_000_000n },
      ]);
    });

    it('falls back below the contract MIN_BURN', () => {
      const plan = planAlgorandExit(withCusd(900_000n), [CUSD_ASSET_ID, USDC_ASSET_ID]);
      expect(plan.steps.map((s) => s.kind)).toEqual(['assetTransfer']);
    });

    it('falls back when self lacks the USDC opt-in or the app opt-in', () => {
      for (const acct of [withCusd(5_000_000n, { selfUsdc: false }), withCusd(5_000_000n, { app: false })]) {
        const plan = planAlgorandExit(acct, [CUSD_ASSET_ID, USDC_ASSET_ID]);
        expect(plan.steps.find((s) => s.kind === 'burnCusd')).toBeUndefined();
      }
    });
  });
});

describe('looksLikeBanResponse', () => {
  const { looksLikeBanResponse } = require('../emergencyExit/banSignal');

  it('matches the security middleware signature exactly', () => {
    expect(looksLikeBanResponse(403, 'Your account has been suspended. Please contact support.')).toBe(true);
  });

  it('ignores bare 403s (proxies, WAFs) and non-403 suspensions', () => {
    expect(looksLikeBanResponse(403, 'Access denied.')).toBe(false);
    expect(looksLikeBanResponse(403, undefined)).toBe(false);
    expect(looksLikeBanResponse(500, 'suspended')).toBe(false);
  });
});

describe('banSignal transitions', () => {
  const memStore = () => {
    const m = new Map<string, string>();
    return {
      get: async (k: string) => m.get(k) ?? null,
      set: async (k: string, v: string) => { m.set(k, v); },
      del: async (k: string) => { m.delete(k); },
    };
  };

  it('marks once per episode, notifies subscribers on the transition only', async () => {
    jest.isolateModules(() => {}); // reset module-level memory via fresh require
    const sig = require('../emergencyExit/banSignal');
    const store = memStore();
    await sig.clearBanSignal(store); // known state
    let notified = 0;
    const off = sig.onBanSignal(() => { notified += 1; });

    expect(await sig.markBanSignal(store)).toBe(true);   // transition
    expect(await sig.markBanSignal(store)).toBe(false);  // already banned
    expect(notified).toBe(1);
    expect(await sig.isBanSignaled(store)).toBe(true);

    await sig.clearBanSignal(store);
    expect(await sig.isBanSignaled(store)).toBe(false);
    expect(await sig.markBanSignal(store)).toBe(true);   // new episode
    expect(notified).toBe(2);
    off();
  });
});
