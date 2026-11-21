// The beneficiary's direct, self-paid claim path (spec 6.7): exact calldata,
// a type-2 signer that matches eth_account, the BNB check before signing, and
// no heartbeat gate anywhere in the path.
//
// Selectors were checked against the compiled artifact
// contracts/smart_account/out/ConfioSmartAccount.sol/ConfioSmartAccount.json
// (methodIdentifiers). Raw transactions were produced with eth_account 0.13.7.
import {
  DirectRevertError,
  decodeRevert,
  directCalldata,
  directTokenUniverse,
  formatBnbCeil,
  nextDirectStep,
  quoteDirectCall,
  readDirectAccountState,
  readDirectHoldings,
  sendDirectCall,
  signEip1559Transaction,
  type DirectAccountState,
  type RpcFn,
} from '../emergencyExit/directClaim';
import { selector } from '../evmWallet';
import { encodeStockBalanceMulticall } from '../emergencyExit/bscExit';
import {
  findDirectClaimEntry, loadDirectClaimEntries, rememberDirectClaimEntries, DIRECT_CLAIM_STORE_KEY,
} from '../emergencyExit/directClaimStore';
import type { KVStore } from '../emergencyExit/kvStore';
import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, hexToBytes } from '@noble/hashes/utils';

const PK = '1111111111111111111111111111111111111111111111111111111111111111';
const EOA = '0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A';
const ACCOUNT = '0x' + 'cd'.repeat(20);
const USDT = '0x55d398326f99059fF775485246999027B3197955';
const wallet = { address: EOA, privKeyHex: PK } as any;

const word = (v: bigint | number) => '0x' + BigInt(v).toString(16).padStart(64, '0');
const addrWord = (a: string) => '0x' + a.replace(/^0x/, '').toLowerCase().padStart(64, '0');

describe('calldata', () => {
  it('uses the contract selectors', () => {
    expect(directCalldata({ kind: 'initiateClaim' })).toBe('0x2b2bd2d8');
    expect(directCalldata({ kind: 'executeClaim' })).toBe('0xb52de815');
    expect(directCalldata({ kind: 'withdraw', token: USDT, amount: 123456789n, to: EOA })).toBe(
      '0x69328dec'
      + '00000000000000000000000055d398326f99059ff775485246999027b3197955'
      + '00000000000000000000000000000000000000000000000000000000075bcd15'
      + '00000000000000000000000019e7e376e7c213b7e7e7e46cc70a5dd086daff2a',
    );
  });

  it('refuses a malformed withdraw', () => {
    expect(() => directCalldata({ kind: 'withdraw', token: '0x12', amount: 1n, to: EOA })).toThrow('bad_withdraw');
    expect(() => directCalldata({ kind: 'withdraw', token: USDT, amount: 0n, to: EOA })).toThrow('bad_withdraw');
    expect(() => directCalldata({ kind: 'withdraw', token: USDT, amount: 1n, to: '0x' + '00'.repeat(20) })).toThrow();
  });

  it('decodes the contract errors by selector', () => {
    expect(decodeRevert('0x644d871f')).toBe('NotBeneficiary');
    expect(decodeRevert('0x085de625')).toBe('TooEarly');
    expect(decodeRevert(selector('Cooldown()'))).toBe('Cooldown');
    expect(decodeRevert('0xdeadbeef')).toBeNull();
    expect(decodeRevert(null)).toBeNull();
  });
});

describe('type-2 signer', () => {
  const base = {
    nonce: 5n, maxPriorityFeePerGas: 120_000_000n, maxFeePerGas: 120_000_000n, gasLimit: 65_000n,
    to: ACCOUNT, valueWei: 0n, chainId: 56n,
  };

  it('matches eth_account for initiateClaim()', () => {
    const signed = signEip1559Transaction({ ...base, data: '0x2b2bd2d8' }, PK);
    expect(signed.rawTx).toBe('0x02f86e38058407270e008407270e0082fde894cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd80842b2bd2d8c001a01055eb8b9818eff726a8962542fc320c30f443cf1dc2c7bd1915630ce577a38fa04a71a94d9ee68ab7ebf418c182e77ad4754bead7897cc659149976cab65865fe');
    expect(signed.txHash).toBe('0xa3e91e13bd9563bfb1b854c54e9411309e8cd8ac1ddf9752a5970d88b1e92521');
  });

  it('matches eth_account for withdraw(token, amount, to)', () => {
    const data = directCalldata({ kind: 'withdraw', token: USDT, amount: 123456789n, to: EOA });
    const signed = signEip1559Transaction({ ...base, data }, PK);
    expect(signed.txHash).toBe('0xab93d7281d203f1cbd4b1b6bbac4cb83ccd7c4270a7938a656e77aa0e31f0ea7');
  });
});

// ------------------------------------------------------------ fake chain

type Handler = (params: any[]) => any;
function fakeRpc(over: Record<string, Handler> = {}) {
  const calls: Array<{ method: string; params: any[] }> = [];
  const handlers: Record<string, Handler> = {
    eth_estimateGas: () => '0xc350', // 50,000
    eth_gasPrice: () => '0x5f5e100', // 0.1 gwei
    eth_getBalance: () => '0x' + (10n ** 16n).toString(16), // 0.01 BNB
    eth_getTransactionCount: () => '0x7',
    eth_sendRawTransaction: () => '0xhash',
    eth_getTransactionReceipt: () => ({ status: '0x1' }),
    ...over,
  };
  const rpc: RpcFn = async (method, params) => {
    calls.push({ method, params });
    const h = handlers[method];
    if (!h) {
      throw new Error(`unexpected ${method}`);
    }
    return h(params);
  };
  return { rpc, calls };
}

describe('quote and BNB check', () => {
  it('prices the call from the beneficiary address to the account', async () => {
    const { rpc, calls } = fakeRpc();
    const q = await quoteDirectCall({ from: EOA, account: ACCOUNT, call: { kind: 'initiateClaim' }, rpc });
    expect(q.ok).toBe(true);
    if (!q.ok) { return; }
    // 50,000 × 1.3 = 65,000 gas at 0.12 gwei
    expect(q.quote.gasLimit).toBe(65_000n);
    expect(q.quote.maxFeePerGas).toBe(120_000_000n);
    expect(q.quote.needWei).toBe(65_000n * 120_000_000n);
    const estimate = calls.find((c) => c.method === 'eth_estimateGas')!;
    expect(estimate.params[0]).toEqual({ from: EOA, to: ACCOUNT, data: '0x2b2bd2d8' });
  });

  it('returns the contract refusal without spending anything', async () => {
    const { rpc } = fakeRpc({
      eth_estimateGas: () => { throw new DirectRevertError('execution reverted', '0x085de625'); },
    });
    const q = await quoteDirectCall({ from: EOA, account: ACCOUNT, call: { kind: 'executeClaim' }, rpc });
    expect(q).toEqual({ ok: false, reason: 'refused', error: 'TooEarly' });
  });

  it('says how much BNB is missing and never signs when short', async () => {
    const { rpc, calls } = fakeRpc({ eth_getBalance: () => '0x0' });
    const out = await sendDirectCall({ wallet, account: ACCOUNT, call: { kind: 'initiateClaim' }, rpc });
    expect(out).toEqual({ status: 'needs_bnb', needWei: 65_000n * 120_000_000n, balanceWei: 0n, address: EOA });
    expect(calls.map((c) => c.method)).not.toContain('eth_sendRawTransaction');
  });

  it('formats the BNB minimum rounded up', () => {
    expect(formatBnbCeil(7_800_000_000_000n)).toBe('0.00001');
    expect(formatBnbCeil(10n ** 18n)).toBe('1');
    expect(formatBnbCeil(1_230_000_000_000_001n)).toBe('0.00124');
    expect(formatBnbCeil(2n * 10n ** 18n + 10n ** 13n)).toBe('2.00001');
  });
});

describe('send', () => {
  it('sends a plain self-paid type-2 transaction, with no heartbeat gate', async () => {
    const { rpc, calls } = fakeRpc();
    const out = await sendDirectCall({ wallet, account: ACCOUNT, call: { kind: 'initiateClaim' }, rpc, pollMs: 1 });
    expect(out.status).toBe('executed');
    const raw: string = calls.find((c) => c.method === 'eth_sendRawTransaction')!.params[0];
    // Type-2 envelope, addressed to the account itself, carrying only initiateClaim().
    expect(raw.startsWith('0x02')).toBe(true);
    expect(raw).toContain('94' + ACCOUNT.slice(2));
    expect(raw).toContain('842b2bd2d8');
    // Nothing reads or calls the heartbeat; no execute() wrapper.
    const assertSilent = selector('assertSilent()').slice(2);
    expect(raw).not.toContain(assertSilent);
    expect(calls.some((c) => c.method === 'eth_call')).toBe(false);
    expect(raw).not.toContain(selector('execute((address,uint256,bytes)[],uint256,uint256,bytes32,bytes)').slice(2));
    // Nonce comes from the beneficiary's own pending count.
    expect(calls.find((c) => c.method === 'eth_getTransactionCount')!.params).toEqual([EOA, 'pending']);
  });

  it('reports a mined revert as definitive', async () => {
    const { rpc } = fakeRpc({ eth_getTransactionReceipt: () => ({ status: '0x0' }) });
    const out = await sendDirectCall({ wallet, account: ACCOUNT, call: { kind: 'executeClaim' }, rpc, pollMs: 1 });
    expect(out.status).toBe('reverted');
  });

  it('reports "unknown", never failure, when no receipt arrives in time', async () => {
    const { rpc } = fakeRpc({ eth_getTransactionReceipt: () => null });
    const out = await sendDirectCall({
      wallet, account: ACCOUNT, call: { kind: 'initiateClaim' }, rpc, pollMs: 1, receiptBudgetMs: 5,
    });
    expect(out.status).toBe('unknown');
  });

  it('treats "already known" from a node as broadcast', async () => {
    const { rpc } = fakeRpc({ eth_sendRawTransaction: () => { throw new Error('bsc rpc: already known'); } });
    const out = await sendDirectCall({ wallet, account: ACCOUNT, call: { kind: 'initiateClaim' }, rpc, pollMs: 1 });
    expect(out.status).toBe('executed');
  });

  it('a transport error after signing is "unknown" with the locally computed hash, never a throw', async () => {
    const { rpc, calls } = fakeRpc({
      eth_sendRawTransaction: () => { throw new Error('Network request failed'); },
    });
    const out = await sendDirectCall({ wallet, account: ACCOUNT, call: { kind: 'initiateClaim' }, rpc, pollMs: 1 });
    expect(out.status).toBe('unknown');
    const raw: string = calls.find((c) => c.method === 'eth_sendRawTransaction')!.params[0];
    const expected = '0x' + bytesToHex(keccak_256(hexToBytes(raw.slice(2))));
    expect(out).toEqual({ status: 'unknown', txHash: expected });
  });

  it('a decoded revert on the send is still a definitive refusal', async () => {
    const { rpc } = fakeRpc({
      eth_sendRawTransaction: () => { throw new DirectRevertError('execution reverted', '0x085de625'); },
    });
    const out = await sendDirectCall({ wallet, account: ACCOUNT, call: { kind: 'executeClaim' }, rpc, pollMs: 1 });
    expect(out).toEqual({ status: 'refused', error: 'TooEarly' });
  });

  it('only withdraws to the signer’s own wallet', async () => {
    const { rpc } = fakeRpc();
    await expect(sendDirectCall({
      wallet, account: ACCOUNT, rpc,
      call: { kind: 'withdraw', token: USDT, amount: 1n, to: '0x' + 'ee'.repeat(20) },
    })).rejects.toThrow('withdraw_to_must_be_own_wallet');
  });
});

describe('chain state and next step', () => {
  const me = EOA.toLowerCase();
  const state = (over: Partial<DirectAccountState> = {}): DirectAccountState => ({
    owner: '0x' + 'aa'.repeat(20), beneficiary: me, inherited: false, status: 1,
    claimStartedAt: 0, claimExecutableAt: 0, claimCooldownUntil: 0, ...over,
  });

  it('reads the claim fields with eth_call', async () => {
    const answers: Record<string, string> = {
      [selector('owner()')]: addrWord('0x' + 'aa'.repeat(20)),
      [selector('beneficiary()')]: addrWord(EOA),
      [selector('inherited()')]: word(0),
      [selector('status()')]: word(1),
      [selector('claimStartedAt()')]: word(1000),
      [selector('claimExecutableAt()')]: word(2000),
      [selector('claimCooldownUntil()')]: word(0),
    };
    const { rpc } = fakeRpc({
      eth_getCode: () => '0x6080',
      eth_call: ([req]) => answers[req.data],
    });
    const s = await readDirectAccountState(ACCOUNT, rpc);
    expect(s).toEqual(state({ claimStartedAt: 1000, claimExecutableAt: 2000 }));
  });

  it('follows the contract checks', () => {
    expect(nextDirectStep(state(), me, 10)).toEqual({ kind: 'initiate' });
    expect(nextDirectStep(state({ claimCooldownUntil: 50 }), me, 10)).toEqual({ kind: 'cooldown', until: 50 });
    expect(nextDirectStep(state({ claimStartedAt: 5, claimExecutableAt: 20 }), me, 10)).toEqual({ kind: 'wait', executableAt: 20 });
    expect(nextDirectStep(state({ claimStartedAt: 5, claimExecutableAt: 20 }), me, 20)).toEqual({ kind: 'execute' });
    expect(nextDirectStep(state({ status: 3 }), me, 10)).toEqual({ kind: 'inactive' });
    expect(nextDirectStep(state({ beneficiary: '0x' + 'bb'.repeat(20) }), me, 10)).toEqual({ kind: 'not_beneficiary' });
    expect(nextDirectStep(state({ inherited: true, owner: me, status: 4 }), me, 10)).toEqual({ kind: 'withdraw' });
  });

  it('lists non-zero holdings through Multicall3', async () => {
    const universe = directTokenUniverse();
    expect(universe[0].label).toBe('Confío Dollar+');
    const usdtIndex = universe.findIndex((t) => t.address === USDT.toLowerCase());
    expect(usdtIndex).toBeGreaterThan(0);
    // tryAggregate's (bool, bytes)[] return, every call successful.
    const w = (v: bigint | number) => BigInt(v).toString(16).padStart(64, '0');
    const enc = (vals: bigint[]) => {
      let offset = vals.length * 32;
      const offsets: string[] = [];
      const bodies: string[] = [];
      for (const v of vals) {
        offsets.push(w(offset));
        const body = w(1) + w(64) + w(32) + w(v);
        bodies.push(body);
        offset += body.length / 2;
      }
      return '0x' + w(32) + w(vals.length) + offsets.join('') + bodies.join('');
    };
    const chunks: Array<typeof universe> = [];
    for (let i = 0; i < universe.length; i += 250) {
      chunks.push(universe.slice(i, i + 250));
    }
    const { rpc, calls } = fakeRpc({
      eth_call: ([req]) => {
        expect(req.to.toLowerCase()).toBe('0xca11bde05977b3631167028862be2a173976ca11');
        const chunk = chunks.find((c) => encodeStockBalanceMulticall(ACCOUNT, c) === req.data);
        if (!chunk) {
          throw new Error('unexpected multicall');
        }
        return enc(chunk.map((t) => (t.address === USDT.toLowerCase() ? 5n : 0n)));
      },
    });
    const held = await readDirectHoldings(ACCOUNT, [], rpc);
    expect(held).toEqual([{ address: USDT.toLowerCase(), label: 'USDT', balance: 5n }]);
    expect(calls).toHaveLength(chunks.length);
  });
});

describe('device record of the account address', () => {
  const memory = (): KVStore & { map: Map<string, string> } => {
    const map = new Map<string, string>();
    return {
      map,
      get: async (k) => map.get(k) ?? null,
      set: async (k, v) => { map.set(k, v); },
      del: async (k) => { map.delete(k); },
    };
  };

  it('remembers by account, merges fields, and finds by designation', async () => {
    const store = memory();
    await rememberDirectClaimEntries(store, [{ account: ACCOUNT.toUpperCase().replace('0X', '0x'), designationId: 'd1', ownerName: 'Luis R.' }], 1);
    await rememberDirectClaimEntries(store, [{ account: ACCOUNT, chainName: 'BNB Smart Chain', tokens: [USDT] }], 2);
    const entries = await loadDirectClaimEntries(store);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      account: ACCOUNT, designationId: 'd1', ownerName: 'Luis R.', chainName: 'BNB Smart Chain',
      tokens: [USDT.toLowerCase()],
    });
    expect(findDirectClaimEntry(entries, { designationId: 'd1' })?.account).toBe(ACCOUNT);
    expect(findDirectClaimEntry(entries, { designationId: 'zz' })).toBeNull();
  });

  it('ignores junk and a zero address', async () => {
    const store = memory();
    await rememberDirectClaimEntries(store, [{ account: '0x' + '00'.repeat(20) }, { account: 'nope' } as any]);
    expect(store.map.has(DIRECT_CLAIM_STORE_KEY)).toBe(false);
    store.map.set(DIRECT_CLAIM_STORE_KEY, '{not json');
    expect(await loadDirectClaimEntries(store)).toEqual([]);
  });
});
