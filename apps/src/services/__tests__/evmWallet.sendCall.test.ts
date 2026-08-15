import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, hexToBytes } from '@noble/hashes/utils';
import {
  deriveEvmKeyFromMasterSecret,
  sendCall,
  setBscTransport,
  signEip191Message,
} from '../evmWallet';

describe('EIP-191 ownership proof', () => {
  it('matches the eth-account signature used by the backend verifier', () => {
    const message = [
      'Confio wallet reenrollment v1',
      'user_id:1',
      'account_id:2',
      `old_algorand_address:${'A'.repeat(58)}`,
      'old_bsc_address:',
      'nonce:test',
    ].join('\n');

    expect(signEip191Message(message, '11'.repeat(32))).toBe(
      '0x792cbb03f8dc9324d3d36fc50b829748fdb0256c2a09f9086ef0bc638ecebd54' +
      '2817617cbe1707c6ca1064b8da6976c7f4b0627a8685a1d1980df7f0ac34d2291b'
    );
  });
});

describe('server reenrollment derivation parity', () => {
  it('keeps the personal/0 HKDF vector identical to the backend verifier', () => {
    const wallet = deriveEvmKeyFromMasterSecret(new Uint8Array(32).fill(7), {
      accountType: 'personal',
      accountIndex: 0,
    });
    expect(wallet.privKeyHex).toBe(
      'fe5b9e085364e5147163f5bce7a967abbf08f5e065f37b9b9da6a7cec5587153'
    );
    expect(wallet.address).toBe('0x9F4601623B0063cb7529aF49c8d1C10d9F877637');
  });
});

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
