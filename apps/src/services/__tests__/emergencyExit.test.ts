// Pure-logic coverage for the emergency exit: the reachability timing
// policy and the Algorand exit planner. Execution paths (RPC, signing)
// are covered by the disaster drill, not unit tests.

import {
  classifyReachability,
  OUTAGE_IMMEDIATE_SECONDS,
} from '../emergencyExit/reachability';
import { planAlgorandExit, AlgoAccountState } from '../emergencyExit/algorandExit';

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
});
