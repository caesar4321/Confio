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

    it('names WHY cUSD ships raw — the recipient will ask', () => {
      // The 2026-07-22 drill: 0.008 cUSD dust went out raw with no explanation.
      expect(planAlgorandExit(withCusd(8_172n), [CUSD_ASSET_ID, USDC_ASSET_ID]).cusdFallbackReason)
        .toBe('below_min_burn');
      expect(planAlgorandExit(withCusd(5_000_000n), [CUSD_ASSET_ID]).cusdFallbackReason)
        .toBe('dest_missing_usdc');
      expect(planAlgorandExit(withCusd(5_000_000n, { selfUsdc: false }), [CUSD_ASSET_ID, USDC_ASSET_ID]).cusdFallbackReason)
        .toBe('self_missing_usdc');
      expect(planAlgorandExit(withCusd(5_000_000n, { app: false }), [CUSD_ASSET_ID, USDC_ASSET_ID]).cusdFallbackReason)
        .toBe('not_opted_into_app');
      // The happy burn path carries no reason at all.
      expect(planAlgorandExit(withCusd(5_000_000n), [CUSD_ASSET_ID, USDC_ASSET_ID]).cusdFallbackReason)
        .toBeUndefined();
    });
  });
});

// The 24h wait is per-episode anti-coercion. It used to be a one-time
// toll: `elapsed >= 24h` only ever becomes MORE true, and nothing spent
// the unlock — so one served wait left an account permanently drainable
// in a single session.
describe('cooloff lifecycle', () => {
  const {
    getExitEligibility, consumeExitCooloff, requestExitCooloff,
    NORMAL_COOLOFF_SECONDS, COOLOFF_VALID_SECONDS,
  } = require('../emergencyExit/reachability');
  const KEY = 'personal_0';
  const STORE_KEY = `confio_emergency_cooloff_v1_${KEY}`;
  const NOW = 1_900_000_000;

  const store = (seed?: Record<string, string>) => {
    const m = new Map<string, string>(Object.entries(seed ?? {}));
    return {
      map: m,
      get: async (k: string) => m.get(k) ?? null,
      set: async (k: string, v: string) => { m.set(k, v); },
      del: async (k: string) => { m.delete(k); },
    };
  };
  const normal = { state: 'normal', immediate: false, chainNowSec: NOW } as any;
  const at = (secondsAgo: number) => store({ [STORE_KEY]: String(NOW - secondsAgo) });

  it('is pending before 24h and eligible after', async () => {
    expect((await getExitEligibility(store(), KEY, normal)).reason).toBe('no_request');
    expect((await getExitEligibility(at(3600), KEY, normal)).reason).toBe('cooloff_pending');
    expect((await getExitEligibility(at(NORMAL_COOLOFF_SECONDS), KEY, normal)).eligible).toBe(true);
  });

  it('an unused unlock expires, and the stale key is dropped', async () => {
    const s = at(NORMAL_COOLOFF_SECONDS + COOLOFF_VALID_SECONDS + 1);
    const elig = await getExitEligibility(s, KEY, normal);
    expect(elig).toMatchObject({ eligible: false, reason: 'cooloff_expired' });
    // Dropped, so the screen offers a fresh wait instead of a dead button.
    expect(s.map.has(STORE_KEY)).toBe(false);
  });

  it('stays usable through the whole validity window', async () => {
    const s = at(NORMAL_COOLOFF_SECONDS + COOLOFF_VALID_SECONDS - 60);
    expect((await getExitEligibility(s, KEY, normal)).eligible).toBe(true);
  });

  it('consuming the unlock re-arms the wait', async () => {
    const s = at(NORMAL_COOLOFF_SECONDS);
    expect((await getExitEligibility(s, KEY, normal)).eligible).toBe(true);
    await consumeExitCooloff(s, KEY);
    expect((await getExitEligibility(s, KEY, normal)).reason).toBe('no_request');
  });

  it('immediate states never consult the cooloff at all', async () => {
    const banned = { state: 'banned', immediate: true, chainNowSec: NOW } as any;
    expect(await getExitEligibility(store(), KEY, banned))
      .toEqual({ eligible: true, reason: 'immediate' });
  });

  it('re-requesting does not restart a running wait', async () => {
    const s = at(3600);
    const { requestedAtSec } = await requestExitCooloff(s, KEY);
    expect(requestedAtSec).toBe(NOW - 3600);
  });
});

describe('usdtCreditedTo', () => {
  const { usdtCreditedTo } = require('../emergencyExit/bscExit');
  const USDT = '0x55d398326f99059fF775485246999027B3197955';
  const TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef';
  const DEST = '0xA18392260d04e1253B87E3aA5f12Cd8478F31c16';
  const topicFor = (addr: string) => '0x' + '0'.repeat(24) + addr.slice(2).toLowerCase();
  const log = (over: Record<string, unknown> = {}) => ({
    address: USDT,
    topics: [TRANSFER, topicFor('0x' + '11'.repeat(20)), topicFor(DEST)],
    data: '0x' + (10n ** 18n).toString(16).padStart(64, '0'),
    ...over,
  });

  // The success card states this number as the user's money. Anything it
  // can't prove from the destination's own credit must not be counted.
  it('sums only USDT credits to the destination', () => {
    expect(usdtCreditedTo({ logs: [log(), log()] }, DEST)).toBe(2n * 10n ** 18n);
  });

  it('ignores other tokens, other recipients and other events', () => {
    const other = '0x' + 'ab'.repeat(20);
    expect(usdtCreditedTo({
      logs: [
        log({ address: '0x' + 'cd'.repeat(20) }),                    // not USDT
        log({ topics: [TRANSFER, topicFor(other), topicFor(other)] }), // not ours
        log({ topics: ['0x' + '99'.repeat(32), topicFor(other), topicFor(DEST)] }), // not Transfer
      ],
    }, DEST)).toBe(0n);
  });

  it('matches the destination case-insensitively', () => {
    expect(usdtCreditedTo({ logs: [log()] }, DEST.toLowerCase())).toBe(10n ** 18n);
  });

  it('returns 0 when the receipt carries no logs (degraded / RPC omission)', () => {
    expect(usdtCreditedTo({}, DEST)).toBe(0n);
    expect(usdtCreditedTo({ logs: [] }, DEST)).toBe(0n);
  });
});

// The checkpoint exists to resume ONE interrupted attempt. v1 never
// expired and was never cleared, so a completed exit left a permanent
// "already done" record: the NEXT exit to the same destination skipped
// every step, sent nothing, and still reported success. Regression cover.
describe('bsc exit checkpoint', () => {
  const WALLET = { address: '0x' + '11'.repeat(20), privKeyHex: '00' } as any;
  const DEST = '0x' + '22'.repeat(20);
  const VAULT = '0x' + '33'.repeat(20);
  const CUSD = '0x' + '44'.repeat(20);
  const CONFIO = '0xcceb3f6127fa9160a26a1b85857ca4c9d56b3fa8';
  const ACCOUNT_KEY = 'personal_0';
  const ONE_TOKEN = '0x' + (10n ** 18n).toString(16).padStart(64, '0');

  const memStore = (seed?: Record<string, string>) => {
    const m = new Map<string, string>(Object.entries(seed ?? {}));
    return {
      map: m,
      get: async (k: string) => m.get(k) ?? null,
      set: async (k: string, v: string) => { m.set(k, v); },
      del: async (k: string) => { m.delete(k); },
    };
  };

  // Load bscExit with the chain layer stubbed: every balance reads as one
  // token, so both legs have something to send unless a checkpoint stops them.
  const loadExit = (sendCall: jest.Mock) => {
    jest.resetModules();
    jest.doMock('../../config/ondoStockTokens.generated', () => ({
      BUNDLED_ONDO_STOCK_TOKENS: [],
    }));
    jest.doMock('../evmWallet', () => ({
      bscBnbBalance: async () => 0n,
      bscGasPrice: async () => 100_000_000n,
      bscEthCall: async (to: string) =>
        to.toLowerCase() === CONFIO ? '0x' + '0'.repeat(64) : ONE_TOKEN,
      sendCall,
      selector: () => '0xdeadbeef',
      encodeUint: (v: bigint) => v.toString(16).padStart(64, '0'),
      encodeAddress: (a: string) => a.slice(2).padStart(64, '0'),
      isOutcomeUnknown: (error: any) => Boolean(error?.broadcast),
      setBscTransport: () => {},
    }));
    return require('../emergencyExit/bscExit');
  };

  const okSend = () => jest.fn(async () => ({
    status: '0x1', transactionHash: '0x' + 'ab'.repeat(32), blockNumber: '0x1', logs: [],
  }));

  const run = async (mod: any, store: any) => mod.executeBscExit({
    wallet: WALLET, dest: DEST, vaultAddress: VAULT,
    minUsdtOutWei: 0n, accountKey: ACCOUNT_KEY, store,
  });

  it('clears the checkpoint once every step resolves', async () => {
    const send = okSend();
    const mod = loadExit(send);
    const store = memStore();
    const res = await run(mod, store);
    expect(res.sentNow).toEqual(['redeemCusdPlus', 'transferUsdt']);
    expect(store.map.size).toBe(0); // nothing left to poison the next exit
  });

  it('redeems bundled cUSD permissionlessly before transferring raw USDT', async () => {
    const send = okSend();
    const mod = loadExit(send);
    const res = await mod.executeBscExit({
      wallet: WALLET,
      dest: DEST,
      vaultAddress: VAULT,
      cusdAddress: CUSD,
      minUsdtOutWei: 0n,
      accountKey: ACCOUNT_KEY,
      store: memStore(),
    });

    expect(res.sentNow).toEqual(['redeemCusdPlus', 'redeemCusd', 'transferUsdt']);
    expect(send.mock.calls.map(([call]) => call.to.toLowerCase())).toEqual([
      VAULT.toLowerCase(),
      CUSD.toLowerCase(),
      '0x55d398326f99059ff775485246999027b3197955',
    ]);
  });

  it('a second exit to the same destination sends again', async () => {
    const send = okSend();
    const mod = loadExit(send);
    const store = memStore();
    await run(mod, store);
    const second = await run(mod, store);
    expect(second.sentNow).toEqual(['redeemCusdPlus', 'transferUsdt']);
    expect(send).toHaveBeenCalledTimes(4); // 2 legs x 2 exits, not 2
  });

  it('ignores a checkpoint older than its TTL', async () => {
    const send = okSend();
    const mod = loadExit(send);
    const key = `confio_emergency_bsc_ck_v2_${ACCOUNT_KEY}_${DEST.toLowerCase()}`;
    const store = memStore({
      [key]: JSON.stringify({
        ts: Date.now() - 31 * 60 * 1000,
        steps: { redeemCusdPlus: '0xold', transferUsdt: '0xold' },
      }),
    });
    const res = await run(mod, store);
    expect(res.sentNow).toEqual(['redeemCusdPlus', 'transferUsdt']);
  });

  it('ignores a checkpoint timestamp from the future after a device clock rollback', async () => {
    const send = okSend();
    const mod = loadExit(send);
    const key = `confio_emergency_bsc_ck_v2_${ACCOUNT_KEY}_${DEST.toLowerCase()}`;
    const store = memStore({
      [key]: JSON.stringify({
        ts: Date.now() + 60 * 60 * 1000,
        steps: { redeemCusdPlus: '0xold', transferUsdt: '0xold' },
      }),
    });
    const res = await run(mod, store);
    expect(res.sentNow).toEqual(['redeemCusdPlus', 'transferUsdt']);
  });

  it('a FRESH checkpoint still resumes — and reports nothing sent now', async () => {
    const send = okSend();
    const mod = loadExit(send);
    const key = `confio_emergency_bsc_ck_v2_${ACCOUNT_KEY}_${DEST.toLowerCase()}`;
    const store = memStore({
      [key]: JSON.stringify({
        ts: Date.now(),
        steps: { redeemCusdPlus: '0xold', transferUsdt: '0xold' },
      }),
    });
    const res = await run(mod, store);
    expect(send).not.toHaveBeenCalled();
    // The screen keys its headline off this: no broadcast ⇒ no "Listo".
    expect(res.sentNow).toEqual([]);
  });

  it('ignores a v1 checkpoint (flat map, no timestamp)', async () => {
    const send = okSend();
    const mod = loadExit(send);
    const v1key = `confio_emergency_bsc_ck_v2_${ACCOUNT_KEY}_${DEST.toLowerCase()}`;
    const store = memStore({
      [v1key]: JSON.stringify({ redeemCusdPlus: '0xold', transferUsdt: '0xold' }),
    });
    const res = await run(mod, store);
    expect(res.sentNow).toEqual(['redeemCusdPlus', 'transferUsdt']);
  });

  it('transfers only the canonical CONFIO contract balance', async () => {
    const send = okSend();
    jest.resetModules();
    jest.doMock('../../config/ondoStockTokens.generated', () => ({
      BUNDLED_ONDO_STOCK_TOKENS: [],
    }));
    jest.doMock('../evmWallet', () => ({
      bscBnbBalance: async () => 0n,
      bscGasPrice: async () => 100_000_000n,
      bscEthCall: async (to: string) =>
        to.toLowerCase() === CONFIO ? ONE_TOKEN : '0x' + '0'.repeat(64),
      sendCall: send,
      selector: () => '0xdeadbeef',
      encodeUint: (v: bigint) => v.toString(16).padStart(64, '0'),
      encodeAddress: (a: string) => a.slice(2).padStart(64, '0'),
      isOutcomeUnknown: (error: any) => Boolean(error?.broadcast),
      setBscTransport: () => {},
    }));
    const mod = require('../emergencyExit/bscExit');
    const res = await run(mod, memStore());

    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0][0]).toMatchObject({ to: mod.BUNDLED_CONFIO_ADDRESS });
    expect(res.sentNow).toEqual(['transferConfio']);
  });

  it('does not raw-transfer cUSD+ while a broadcast redeem outcome is unknown', async () => {
    const timeout = Object.assign(new Error('bsc tx timeout: 0x1234'), { broadcast: true });
    const send = jest.fn(async () => { throw timeout; });
    jest.resetModules();
    jest.doMock('../../config/ondoStockTokens.generated', () => ({
      BUNDLED_ONDO_STOCK_TOKENS: [],
    }));
    jest.doMock('../evmWallet', () => ({
      bscBnbBalance: async () => 0n,
      bscGasPrice: async () => 100_000_000n,
      bscEthCall: async (to: string) =>
        to.toLowerCase() === VAULT.toLowerCase() ? ONE_TOKEN : '0x' + '0'.repeat(64),
      sendCall: send,
      selector: () => '0xdeadbeef',
      encodeUint: (v: bigint) => v.toString(16).padStart(64, '0'),
      encodeAddress: (a: string) => a.slice(2).padStart(64, '0'),
      isOutcomeUnknown: (error: any) => Boolean(error?.broadcast),
      setBscTransport: () => {},
    }));
    const mod = require('../emergencyExit/bscExit');

    await expect(run(mod, memStore())).rejects.toBe(timeout);
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('preserves a raw-redeem warning and partial receipts across a retry', async () => {
    const definitive = new Error('rpc rejected before broadcast');
    const okReceipt = {
      status: '0x1', transactionHash: '0x' + 'ab'.repeat(32), blockNumber: '0x1', logs: [],
    };
    const send = jest.fn()
      .mockRejectedValueOnce(definitive) // redeem failed definitively
      .mockResolvedValueOnce(okReceipt) // raw cUSD+ transfer succeeded
      .mockRejectedValueOnce(definitive) // pre-held USDT failed
      .mockResolvedValueOnce(okReceipt); // USDT succeeds on retry
    jest.resetModules();
    jest.doMock('../../config/ondoStockTokens.generated', () => ({
      BUNDLED_ONDO_STOCK_TOKENS: [],
    }));
    jest.doMock('../evmWallet', () => ({
      bscBnbBalance: async () => 0n,
      bscGasPrice: async () => 100_000_000n,
      bscEthCall: async (to: string) =>
        [VAULT.toLowerCase(), '0x55d398326f99059ff775485246999027b3197955'].includes(to.toLowerCase())
          ? ONE_TOKEN
          : '0x' + '0'.repeat(64),
      sendCall: send,
      selector: () => '0xdeadbeef',
      encodeUint: (v: bigint) => v.toString(16).padStart(64, '0'),
      encodeAddress: (a: string) => a.slice(2).padStart(64, '0'),
      isOutcomeUnknown: () => false,
      setBscTransport: () => {},
    }));
    const mod = require('../emergencyExit/bscExit');
    const store = memStore();

    const partial = await run(mod, store);
    expect(partial).toMatchObject({
      degraded: ['redeemCusdPlus'],
      sentNow: ['redeemCusdPlus'],
      unresolved: ['USDT'],
    });
    const retry = await run(mod, store);
    expect(retry.degraded).toEqual(['redeemCusdPlus']);
    expect(retry.sentNow).toEqual(['transferUsdt']);
    expect(retry.unresolved).toEqual([]);
    expect(retry.txids).not.toHaveProperty('__degraded:redeemCusdPlus');
  });

  it('continues after both cUSD+ exit paths fail definitively', async () => {
    const definitive = new Error('rpc rejected before broadcast');
    const okReceipt = {
      status: '0x1', transactionHash: '0x' + 'ab'.repeat(32), blockNumber: '0x1', logs: [],
    };
    const send = jest.fn()
      .mockRejectedValueOnce(definitive) // redeem
      .mockRejectedValueOnce(definitive) // raw cUSD+ fallback
      .mockResolvedValueOnce(okReceipt); // later raw USDT still exits
    const mod = loadExit(send);
    const result = await run(mod, memStore());
    expect(result.unresolved).toEqual(['cUSD+']);
    expect(result.sentNow).toEqual(['transferUsdt']);
    expect(send).toHaveBeenCalledTimes(3);
  });

  it('records skipped legs without counting them as sent', async () => {
    const send = okSend();
    jest.resetModules();
    jest.doMock('../../config/ondoStockTokens.generated', () => ({
      BUNDLED_ONDO_STOCK_TOKENS: [],
    }));
    jest.doMock('../evmWallet', () => ({
      bscBnbBalance: async () => 0n,
      bscGasPrice: async () => 100_000_000n,
      bscEthCall: async () => '0x' + '0'.repeat(64), // every balance is zero
      sendCall: send,
      selector: () => '0xdeadbeef',
      encodeUint: (v: bigint) => v.toString(16).padStart(64, '0'),
      encodeAddress: (a: string) => a.slice(2).padStart(64, '0'),
      isOutcomeUnknown: (error: any) => Boolean(error?.broadcast),
      setBscTransport: () => {},
    }));
    const mod = require('../emergencyExit/bscExit');
    const res = await run(mod, memStore());
    expect(send).not.toHaveBeenCalled();
    expect(res.sentNow).toEqual([]);
    expect(res.txids).toEqual({
      redeemCusdPlus: 'skipped_zero',
      transferUsdt: 'skipped_zero',
      transferConfio: 'skipped_zero',
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

describe('successProvesUnbanned', () => {
  const { successProvesUnbanned } = require('../emergencyExit/banSignal');

  it('only an auth-carrying request can un-ban', () => {
    expect(successProvesUnbanned({ Authorization: 'JWT abc' })).toBe(true);
    expect(successProvesUnbanned({ authorization: 'JWT abc' })).toBe(true);
  });

  it('anonymous successes (RefreshToken, GetLegalDocument, probes) never clear', () => {
    // Regression: a name-based exempt list missed Apollo's definition-name
    // casing, so anonymous RefreshToken 200s cleared the flag and the next
    // 403 re-navigated — bouncing users off EmergencyExitScreen.
    expect(successProvesUnbanned({})).toBe(false);
    expect(successProvesUnbanned(undefined)).toBe(false);
    expect(successProvesUnbanned({ 'Content-Type': 'application/json' })).toBe(false);
  });
});

describe('accountRoster', () => {
  const { saveAccountRoster, getAccountRoster, exitableAccounts, rosterAccountKey } = require('../emergencyExit/accountRoster');
  const memStore = () => {
    const m = new Map<string, string>();
    return {
      get: async (k: string) => m.get(k) ?? null,
      set: async (k: string, v: string) => { m.set(k, v); },
      del: async (k: string) => { m.delete(k); },
    };
  };

  it('round-trips the roster through the store', async () => {
    const store = memStore();
    expect(await getAccountRoster(store)).toBeNull();
    const roster = [
      { type: 'personal', index: 0, name: 'Julián' },
      { type: 'business', index: 0, businessId: '42', name: 'Arepas SA' },
    ];
    await saveAccountRoster(store, roster);
    expect(await getAccountRoster(store)).toEqual(roster);
  });

  it('exitableAccounts drops employee businesses — their keys are the OWNER\'s', () => {
    const out = exitableAccounts([
      { type: 'business', index: 0, businessId: '7', name: 'Mía' },
      { type: 'business', index: 0, businessId: '9', name: 'Ajena', isEmployee: true },
      { type: 'personal', index: 0, name: 'Yo' },
    ]);
    expect(out.map((a: any) => a.businessId ?? 'personal')).toEqual(['personal', '7']);
  });

  it('always injects personal (fresh device, roster never synced) and dedupes', () => {
    const out = exitableAccounts([
      { type: 'business', index: 0, businessId: '7', name: 'Mía' },
      { type: 'business', index: 0, businessId: '7', name: 'Mía (dup)' },
    ]);
    expect(out[0].type).toBe('personal');
    expect(out).toHaveLength(2);
    expect(exitableAccounts(null)).toEqual([{ type: 'personal', index: 0, name: 'Personal' }]);
  });

  it('rosterAccountKey matches the exit screen / cooloff grammar', () => {
    expect(rosterAccountKey({ type: 'personal', index: 0 })).toBe('personal__0');
    expect(rosterAccountKey({ type: 'business', businessId: '42', index: 0 })).toBe('business_42_0');
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
