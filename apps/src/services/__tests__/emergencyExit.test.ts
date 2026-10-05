// Coverage for the BSC emergency exit engine and its local plumbing:
// receipt accounting, checkpoints, ban signal, account roster. The heartbeat
// gate (gatedTx.ts / heartbeat.ts) has its own suite.

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
    jest.doMock('../emergencyExit/gatedTx', () => ({
      sendGatedCall: (p: any) => (sendCall as any)(p),
      GATE_GAS_OVERHEAD: 60_000n,
      AUTH_GAS_OVERHEAD: 30_000n,
    }));
    jest.doMock('../emergencyExit/heartbeat', () => ({
      BUNDLED_HEARTBEAT: { address: '', owner: '' },
      assertExitOpen: async () => ({ state: 'open' }),
      isConfioAlive: (e: any) => e?.name === 'ConfioAliveError',
    }));
    // Exit sends go through the heartbeat gate (gatedTx.ts); here the gate is
    // open and each gated send is the stubbed sendCall, so these tests keep
    // pinning the engine's legs. Gate behavior has its own suite.
    jest.doMock('../emergencyExit/gatedTx', () => ({
      sendGatedCall: (p: any) => (sendCall as any)(p),
      GATE_GAS_OVERHEAD: 60_000n,
      AUTH_GAS_OVERHEAD: 30_000n,
    }));
    jest.doMock('../emergencyExit/heartbeat', () => ({
      BUNDLED_HEARTBEAT: { address: '', owner: '' },
      assertExitOpen: async () => ({ state: 'open' }),
      isConfioAlive: (e: any) => e?.name === 'ConfioAliveError',
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
    expect(res.sentNow).toEqual(['redeemCusdPlus', 'redeemCusd', 'transferUsdt']);
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
    expect((send.mock.calls as any[]).map(([call]) => call.to.toLowerCase())).toEqual([
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
    expect(second.sentNow).toEqual(['redeemCusdPlus', 'redeemCusd', 'transferUsdt']);
    expect(send).toHaveBeenCalledTimes(6); // 3 legs x 2 exits, not 3
  });

  it('ignores a checkpoint older than its TTL', async () => {
    const send = okSend();
    const mod = loadExit(send);
    const key = `confio_emergency_bsc_ck_v2_${ACCOUNT_KEY}_${DEST.toLowerCase()}`;
    const store = memStore({
      [key]: JSON.stringify({
        ts: Date.now() - 31 * 60 * 1000,
        steps: { redeemCusdPlus: '0xold', redeemCusd: '0xold', transferUsdt: '0xold' },
      }),
    });
    const res = await run(mod, store);
    expect(res.sentNow).toEqual(['redeemCusdPlus', 'redeemCusd', 'transferUsdt']);
  });

  it('ignores a checkpoint timestamp from the future after a device clock rollback', async () => {
    const send = okSend();
    const mod = loadExit(send);
    const key = `confio_emergency_bsc_ck_v2_${ACCOUNT_KEY}_${DEST.toLowerCase()}`;
    const store = memStore({
      [key]: JSON.stringify({
        ts: Date.now() + 60 * 60 * 1000,
        steps: { redeemCusdPlus: '0xold', redeemCusd: '0xold', transferUsdt: '0xold' },
      }),
    });
    const res = await run(mod, store);
    expect(res.sentNow).toEqual(['redeemCusdPlus', 'redeemCusd', 'transferUsdt']);
  });

  it('a FRESH checkpoint still resumes — and reports nothing sent now', async () => {
    const send = okSend();
    const mod = loadExit(send);
    const key = `confio_emergency_bsc_ck_v2_${ACCOUNT_KEY}_${DEST.toLowerCase()}`;
    const store = memStore({
      [key]: JSON.stringify({
        ts: Date.now(),
        steps: { redeemCusdPlus: '0xold', redeemCusd: '0xold', transferUsdt: '0xold' },
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
      [v1key]: JSON.stringify({ redeemCusdPlus: '0xold', redeemCusd: '0xold', transferUsdt: '0xold' }),
    });
    const res = await run(mod, store);
    expect(res.sentNow).toEqual(['redeemCusdPlus', 'redeemCusd', 'transferUsdt']);
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
    jest.doMock('../emergencyExit/gatedTx', () => ({
      sendGatedCall: (p: any) => (send as any)(p),
      GATE_GAS_OVERHEAD: 60_000n,
      AUTH_GAS_OVERHEAD: 30_000n,
    }));
    jest.doMock('../emergencyExit/heartbeat', () => ({
      BUNDLED_HEARTBEAT: { address: '', owner: '' },
      assertExitOpen: async () => ({ state: 'open' }),
      isConfioAlive: (e: any) => e?.name === 'ConfioAliveError',
    }));
    const mod = require('../emergencyExit/bscExit');
    const res = await run(mod, memStore());

    expect(send).toHaveBeenCalledTimes(1);
    expect((send.mock.calls as any[])[0][0]).toMatchObject({ to: mod.BUNDLED_CONFIO_ADDRESS });
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
    jest.doMock('../emergencyExit/gatedTx', () => ({
      sendGatedCall: (p: any) => (send as any)(p),
      GATE_GAS_OVERHEAD: 60_000n,
      AUTH_GAS_OVERHEAD: 30_000n,
    }));
    jest.doMock('../emergencyExit/heartbeat', () => ({
      BUNDLED_HEARTBEAT: { address: '', owner: '' },
      assertExitOpen: async () => ({ state: 'open' }),
      isConfioAlive: (e: any) => e?.name === 'ConfioAliveError',
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
    jest.doMock('../emergencyExit/gatedTx', () => ({
      sendGatedCall: (p: any) => (send as any)(p),
      GATE_GAS_OVERHEAD: 60_000n,
      AUTH_GAS_OVERHEAD: 30_000n,
    }));
    jest.doMock('../emergencyExit/heartbeat', () => ({
      BUNDLED_HEARTBEAT: { address: '', owner: '' },
      assertExitOpen: async () => ({ state: 'open' }),
      isConfioAlive: (e: any) => e?.name === 'ConfioAliveError',
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
      .mockRejectedValueOnce(definitive) // cUSD+ redeem
      .mockRejectedValueOnce(definitive) // raw cUSD+ fallback
      .mockResolvedValueOnce(okReceipt)  // cUSD redeem is unaffected
      .mockResolvedValueOnce(okReceipt); // later raw USDT still exits
    const mod = loadExit(send);
    const result = await run(mod, memStore());
    expect(result.unresolved).toEqual(['cUSD+']);
    expect(result.sentNow).toEqual(['redeemCusd', 'transferUsdt']);
    expect(send).toHaveBeenCalledTimes(4);
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
    jest.doMock('../emergencyExit/gatedTx', () => ({
      sendGatedCall: (p: any) => (send as any)(p),
      GATE_GAS_OVERHEAD: 60_000n,
      AUTH_GAS_OVERHEAD: 30_000n,
    }));
    jest.doMock('../emergencyExit/heartbeat', () => ({
      BUNDLED_HEARTBEAT: { address: '', owner: '' },
      assertExitOpen: async () => ({ state: 'open' }),
      isConfioAlive: (e: any) => e?.name === 'ConfioAliveError',
    }));
    const mod = require('../emergencyExit/bscExit');
    const res = await run(mod, memStore());
    expect(send).not.toHaveBeenCalled();
    expect(res.sentNow).toEqual([]);
    expect(res.txids).toEqual({
      redeemCusdPlus: 'skipped_zero',
      redeemCusd: 'skipped_zero',
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
