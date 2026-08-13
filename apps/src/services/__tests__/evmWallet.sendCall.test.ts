import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, hexToBytes } from '@noble/hashes/utils';
import { sendCall, setBscTransport } from '../evmWallet';

describe('sendCall receipt integrity', () => {
  afterEach(() => setBscTransport(null));

  it('polls the locally signed transaction hash, not the RPC response hash', async () => {
    let rawTx = '';
    let polledHash = '';
    setBscTransport({
      read: async (method, params) => {
        if (method === 'eth_getTransactionCount') return '0x0';
        if (method === 'eth_gasPrice') return '0x5f5e100';
        if (method === 'eth_getTransactionReceipt') {
          polledHash = String(params[0]);
          return { status: '0x1', transactionHash: polledHash, blockNumber: '0x1', logs: [] };
        }
        throw new Error(`unexpected rpc method: ${method}`);
      },
      submit: async (signed) => {
        rawTx = signed;
        return '0x' + 'ff'.repeat(32); // dishonest/broken RPC response
      },
    });

    await sendCall({
      from: '0x' + '11'.repeat(20),
      privKeyHex: '01'.padStart(64, '0'),
      to: '0x' + '22'.repeat(20),
      data: '0x',
      gasLimit: 21_000n,
    });

    const expected = '0x' + bytesToHex(keccak_256(hexToBytes(rawTx.slice(2))));
    expect(polledHash).toBe(expected);
    expect(polledHash).not.toBe('0x' + 'ff'.repeat(32));
  });
});
