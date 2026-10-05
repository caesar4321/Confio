// The heartbeat gate: the only thing that opens Salida de emergencia.
// readHeartbeat (what the screen shows), sendGatedCall (every exit tx is
// execute([assertSilent(), leg]) to the user's own address), and the engine's
// behavior when the gate is closed.

export {}; // module scope: keeps helpers from colliding with other test files

const HB = '0x' + 'ab'.repeat(20);
const BEATER = '0x' + 'be'.repeat(20);
const NOW = 1_900_000_000;
const DAY = 86_400;

const word = (v: bigint | number | string) =>
  '0x' + BigInt(v).toString(16).padStart(64, '0');

/** Minimal BSC JSON-RPC stub keyed by method and eth_call selector. */
const rpcStub = (opts: {
  code?: string; beater?: string; silence?: number; lastBeat?: number; fail?: boolean;
}) => {
  const { selector } = jest.requireActual('../evmWallet');
  const sel = (sig: string) => selector(sig).slice(0, 10);
  return jest.fn(async (_url: string, init: any) => {
    if (opts.fail) throw new Error('network down');
    const { method, params } = JSON.parse(init.body);
    let result: any;
    if (method === 'eth_getBlockByNumber') result = { number: '0x10', timestamp: '0x' + NOW.toString(16) };
    else if (method === 'eth_getCode') result = opts.code ?? '0x6080';
    else if (method === 'eth_call') {
      const data: string = params[0].data;
      if (data.startsWith(sel('beater()'))) result = word(opts.beater ?? BEATER);
      else if (data.startsWith(sel('silenceRequired()'))) result = word(opts.silence ?? 14 * DAY);
      else if (data.startsWith(sel('lastBeat()'))) result = word(opts.lastBeat ?? NOW - 3600);
    }
    return { ok: true, json: async () => ({ jsonrpc: '2.0', id: 1, result }) } as any;
  });
};

describe('readHeartbeat', () => {
  const load = () => {
    jest.resetModules();
    return require('../emergencyExit/heartbeat');
  };
  afterEach(() => { (globalThis as any).fetch = undefined; });

  it('is closed and says so when this build has no heartbeat address', async () => {
    const { readHeartbeat } = load();
    await expect(readHeartbeat('')).resolves.toEqual({ state: 'not_configured' });
    await expect(readHeartbeat('0x' + '00'.repeat(20))).resolves.toEqual({ state: 'not_configured' });
  });

  // Audit P2: the Safe may rotate (Ownable2Step); a pinned owner would close
  // every shipped build's exit for good.
  it('does not depend on who owns the heartbeat', async () => {
    (globalThis as any).fetch = rpcStub({ lastBeat: NOW - 15 * DAY });
    const { readHeartbeat } = load();
    expect((await readHeartbeat(HB)).state).toBe('open');
  });

  it('reports a beating Confío as alive with the opening date', async () => {
    (globalThis as any).fetch = rpcStub({ lastBeat: NOW - 3600 });
    const { readHeartbeat } = load();
    await expect(readHeartbeat(HB)).resolves.toEqual({
      state: 'alive', chainNowSec: NOW, lastBeatSec: NOW - 3600,
      silenceSec: 14 * DAY, opensAtSec: NOW - 3600 + 14 * DAY,
    });
  });

  it('turns quiet after two days without a beat, still closed', async () => {
    (globalThis as any).fetch = rpcStub({ lastBeat: NOW - 3 * DAY });
    const { readHeartbeat } = load();
    expect((await readHeartbeat(HB)).state).toBe('quiet');
  });

  it('opens exactly at lastBeat + silenceRequired, as the contract does', async () => {
    (globalThis as any).fetch = rpcStub({ lastBeat: NOW - 14 * DAY });
    const { readHeartbeat } = load();
    expect((await readHeartbeat(HB)).state).toBe('open');
    (globalThis as any).fetch = rpcStub({ lastBeat: NOW - 14 * DAY + 1 });
    expect((await readHeartbeat(HB)).state).toBe('quiet');
  });

  // Audit P2: a wrong address is a fail-OPEN gate on-chain, so the app must
  // refuse to call it open.
  it.each([
    ['no code at the address', { code: '0x' }],
    ['a heartbeat with no beater', { beater: '0x' + '00'.repeat(20) }],
    ['an uninitialized heartbeat', { silence: 0 }],
  ])('never reads %s as open', async (_label, opts) => {
    (globalThis as any).fetch = rpcStub({ ...opts, lastBeat: 0 });
    const { readHeartbeat } = load();
    expect((await readHeartbeat(HB)).state).toBe('invalid');
  });

  it('a null latest block is unreachable, never a throw or a false "alive"', async () => {
    (globalThis as any).fetch = jest.fn(async () => ({
      ok: true, json: async () => ({ jsonrpc: '2.0', id: 1, result: null }),
    }));
    const { readHeartbeat } = load();
    await expect(readHeartbeat(HB)).resolves.toEqual({ state: 'unreachable' });
  });

  it('is unreachable, not open, when no RPC answers', async () => {
    (globalThis as any).fetch = rpcStub({ fail: true });
    const { readHeartbeat } = load();
    expect((await readHeartbeat(HB)).state).toBe('unreachable');
  });

  it('assertExitOpen throws ConfioAliveError unless open', async () => {
    (globalThis as any).fetch = rpcStub({ lastBeat: NOW - 3600 });
    const { assertExitOpen, isConfioAlive } = load();
    const err = await assertExitOpen(HB).catch((e: unknown) => e);
    expect(isConfioAlive(err)).toBe(true);
  });
});

describe('sendGatedCall', () => {
  const actual = jest.requireActual('../evmWallet');
  const PK = '11'.repeat(32);
  const EOA = '0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A'; // address of PK
  const DELEGATE = actual.TRUSTED_BATCH_DELEGATES[0];
  const USDT = '0x55d398326f99059fF775485246999027B3197955';
  const LEG = { to: USDT, data: actual.selector('transfer(address,uint256)') + '00'.repeat(64) };

  const batchLog = (nonce: bigint) => ({
    address: EOA, data: '0x',
    topics: [actual.BATCH_EXECUTED_TOPIC, word(nonce)],
  });

  const load = (o: {
    code: string; execNonce?: bigint; receipt?: any; waitError?: Error;
    /** Heartbeat reads in order: [pre-flight, after a revert]. */
    heartbeat?: any[];
  }) => {
    jest.resetModules();
    const signLegacy = jest.fn(actual.signLegacyTransaction);
    const signSetCode = jest.fn(actual.signSetCodeTransaction);
    const sendRaw = jest.fn(async () => '0x');
    jest.doMock('../evmWallet', () => ({
      ...actual,
      bscGetNonce: async () => 7n,
      bscGetCode: async () => o.code,
      bscGetStorageAt: async () => word(o.execNonce ?? 4n),
      bscGasPrice: async () => 100_000_000n,
      bscEstimateGas: async () => 50_000n,
      bscSendRawTransaction: sendRaw,
      bscWaitForReceipt: async () => {
        if (o.waitError) throw o.waitError;
        return o.receipt;
      },
      signLegacyTransaction: signLegacy,
      signSetCodeTransaction: signSetCode,
    }));
    jest.doMock('../emergencyExit/heartbeat', () => {
      const real = jest.requireActual('../emergencyExit/heartbeat');
      const reads = [...(o.heartbeat ?? [])];
      return { ...real, readHeartbeat: async () => reads.shift() ?? { state: 'open' } };
    });
    const mod = require('../emergencyExit/gatedTx');
    return { mod, signLegacy, signSetCode, sendRaw };
  };

  const send = (mod: any) => mod.sendGatedCall({
    wallet: { address: EOA, privKeyHex: PK }, to: LEG.to, data: LEG.data,
    gasLimit: 80_000n, heartbeatAddress: HB,
  });

  it('a delegated account self-calls execute([assertSilent(), leg])', async () => {
    const { mod, signLegacy, signSetCode } = load({
      code: '0xef0100' + DELEGATE.slice(2),
      receipt: { status: '0x1', transactionHash: '0x1', blockNumber: '0x1', logs: [batchLog(4n)] },
    });
    await send(mod);
    expect(signSetCode).not.toHaveBeenCalled();
    const tx = signLegacy.mock.calls[0][0];
    expect(tx.to).toBe(EOA);
    expect(tx.gasLimit).toBe(80_000n + mod.GATE_GAS_OVERHEAD);
    expect(tx.data).toBe(actual.encodeExecuteCalldata(
      mod.gatedCalls(HB, LEG), 0n, 0n, '0x' + '00'.repeat(32), '0x'));
    // The heartbeat check is the FIRST call of the batch.
    expect(mod.gatedCalls(HB, LEG)[0]).toEqual({
      to: HB, valueWei: 0n, data: actual.selector('assertSilent()'),
    });
  });

  it('a never-delegated account installs the trusted delegate in the same tx', async () => {
    const { mod, signLegacy, signSetCode } = load({
      code: '0x',
      execNonce: 0n,
      receipt: { status: '0x1', transactionHash: '0x1', blockNumber: '0x1', logs: [batchLog(0n)] },
    });
    await send(mod);
    expect(signLegacy).not.toHaveBeenCalled();
    const tx = signSetCode.mock.calls[0][0];
    expect(tx.to).toBe(EOA);
    expect(tx.authorizationList).toHaveLength(1);
    expect(tx.authorizationList[0].address.toLowerCase()).toBe(DELEGATE);
    // Self-sponsored: the sender nonce is bumped before the authorization applies.
    expect(tx.authorizationList[0].nonce).toBe('8');
    expect(tx.gasLimit).toBe(80_000n + mod.GATE_GAS_OVERHEAD + mod.AUTH_GAS_OVERHEAD);
  });

  it('an account delegated elsewhere is re-pointed at the trusted delegate', async () => {
    const { mod, signSetCode } = load({
      code: '0xef0100' + '99'.repeat(20),
      receipt: { status: '0x1', transactionHash: '0x1', blockNumber: '0x1', logs: [batchLog(4n)] },
    });
    await send(mod);
    expect(signSetCode).toHaveBeenCalled();
  });

  it('a mined no-op (authorization did not apply) is a definitive failure', async () => {
    const { mod } = load({
      code: '0x',
      receipt: { status: '0x1', transactionHash: '0x1', blockNumber: '0x1', logs: [] },
    });
    await expect(send(mod)).rejects.toMatchObject({ name: 'BscRevertedError' });
  });

  it('an unprovable execution is reported as outcome-unknown, never as success', async () => {
    const { mod } = load({
      code: '0xef0100' + DELEGATE.slice(2),
      receipt: { status: '0x1', transactionHash: '0x1', blockNumber: '0x1', logs: [{ address: USDT, topics: ['0x1'], data: '0x' }] },
    });
    await expect(send(mod)).rejects.toMatchObject({ broadcast: true });
  });

  it('a revert while Confío beats again is ConfioAliveError (stop, no fallback)', async () => {
    const { BscRevertedError } = actual;
    const { mod } = load({
      code: '0xef0100' + DELEGATE.slice(2),
      waitError: new BscRevertedError('0x1'),
      heartbeat: [{ state: 'open' }, { state: 'alive' }],
    });
    await expect(send(mod)).rejects.toMatchObject({ name: 'ConfioAliveError' });
  });

  it('an unreadable heartbeat after a revert keeps the original revert', async () => {
    const { BscRevertedError } = actual;
    const { mod } = load({
      code: '0xef0100' + DELEGATE.slice(2),
      waitError: new BscRevertedError('0x1'),
      heartbeat: [{ state: 'open' }, { state: 'unreachable' }],
    });
    await expect(send(mod)).rejects.toMatchObject({ name: 'BscRevertedError' });
  });

  // Audit P2: the gate primitive guards itself, not only its callers.
  it.each([
    ['no heartbeat address', ''],
    ['the zero address', '0x' + '00'.repeat(20)],
  ])('signs nothing with %s', async (_label, address) => {
    const { mod, signLegacy, signSetCode, sendRaw } = load({ code: '0x' });
    await expect(mod.sendGatedCall({
      wallet: { address: EOA, privKeyHex: PK }, to: LEG.to, data: LEG.data,
      gasLimit: 80_000n, heartbeatAddress: address,
    })).rejects.toMatchObject({ name: 'ConfioAliveError' });
    expect(signLegacy).not.toHaveBeenCalled();
    expect(signSetCode).not.toHaveBeenCalled();
    expect(sendRaw).not.toHaveBeenCalled();
  });

  it('signs nothing when the heartbeat says Confío is alive', async () => {
    const { mod, sendRaw } = load({ code: '0x', heartbeat: [{ state: 'alive' }] });
    await expect(send(mod)).rejects.toMatchObject({ name: 'ConfioAliveError' });
    expect(sendRaw).not.toHaveBeenCalled();
  });
});

describe('executeBscExit with a closed gate', () => {
  const WALLET = { address: '0x' + '11'.repeat(20), privKeyHex: '00' } as any;
  const DEST = '0x' + '22'.repeat(20);
  const VAULT = '0x' + '33'.repeat(20);
  const ONE = '0x' + (10n ** 18n).toString(16).padStart(64, '0');

  const memStore = () => {
    const m = new Map<string, string>();
    return {
      get: async (k: string) => m.get(k) ?? null,
      set: async (k: string, v: string) => { m.set(k, v); },
      del: async (k: string) => { m.delete(k); },
    };
  };

  const load = (o: { gateOpen: boolean; send: jest.Mock }) => {
    jest.resetModules();
    jest.doMock('../../config/ondoStockTokens.generated', () => ({ BUNDLED_ONDO_STOCK_TOKENS: [] }));
    jest.doMock('../evmWallet', () => ({
      bscBnbBalance: async () => 0n,
      bscGasPrice: async () => 100_000_000n,
      bscEthCall: async () => ONE,
      selector: () => '0xdeadbeef',
      encodeUint: (v: bigint) => v.toString(16).padStart(64, '0'),
      encodeAddress: (a: string) => a.slice(2).padStart(64, '0'),
      isOutcomeUnknown: (error: any) => Boolean(error?.broadcast),
      setBscTransport: () => {},
    }));
    jest.doMock('../emergencyExit/gatedTx', () => ({
      sendGatedCall: o.send, GATE_GAS_OVERHEAD: 60_000n, AUTH_GAS_OVERHEAD: 30_000n,
    }));
    const realHb = jest.requireActual('../emergencyExit/heartbeat');
    jest.doMock('../emergencyExit/heartbeat', () => ({
      ...realHb,
      assertExitOpen: async () => {
        if (!o.gateOpen) throw new realHb.ConfioAliveError({ state: 'alive' });
        return { state: 'open' };
      },
    }));
    return { mod: require('../emergencyExit/bscExit'), realHb };
  };

  const run = (mod: any) => mod.executeBscExit({
    wallet: WALLET, dest: DEST, vaultAddress: VAULT,
    minUsdtOutWei: 0n, accountKey: 'personal_0', store: memStore(),
  });

  it('signs nothing while Confío is alive', async () => {
    const send = jest.fn();
    const { mod } = load({ gateOpen: false, send });
    await expect(run(mod)).rejects.toMatchObject({ name: 'ConfioAliveError' });
    expect(send).not.toHaveBeenCalled();
  });

  it('stops at the first closed-gate revert — no raw-transfer fallback', async () => {
    let realHb: any;
    const send = jest.fn(async () => { throw new realHb.ConfioAliveError({ state: 'alive' }); });
    const loaded = load({ gateOpen: true, send });
    realHb = loaded.realHb;
    await expect(run(loaded.mod)).rejects.toMatchObject({ name: 'ConfioAliveError' });
    // The cUSD+ redeem was attempted once; the degraded raw-share transfer
    // (an equally gated send) was never tried.
    expect(send).toHaveBeenCalledTimes(1);
  });
});
