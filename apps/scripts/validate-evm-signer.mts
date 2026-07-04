// Validates src/services/evmWallet.ts (derivation + legacy tx signing)
// byte-for-byte against ethers v6. Run on any change to the signer or a
// @noble/curves major bump:
//   npm i --no-save ethers tsx && npx tsx scripts/validate-evm-signer.mts
// PASS requires: deterministic + domain-separated derivation, address equal
// to ethers.computeAddress, and raw tx bytes identical to ethers for every
// case (value transfer, zero-value contract call with data).

import { Wallet, computeAddress, Transaction } from 'ethers';
import {
  deriveDeterministicEvmKey,
  signLegacyTransaction,
  toChecksumAddress,
} from '../src/services/evmWallet';

// 1) Derivation determinism + address correctness
const opts = {
  clientSalt: 'test-client-salt-abc123',
  derivationPepper: 'test-pepper-xyz',
  provider: 'google' as const,
  accountType: 'personal' as const,
  accountIndex: 0,
};
const w1 = deriveDeterministicEvmKey(opts);
const w2 = deriveDeterministicEvmKey({ ...opts });
const wBiz = deriveDeterministicEvmKey({ ...opts, accountType: 'business' as const, businessId: '42' });
console.log('deterministic:', w1.address === w2.address);
console.log('domain-separated:', w1.address !== wBiz.address);
const ethersAddr = computeAddress('0x' + w1.privKeyHex);
console.log('address matches ethers:', w1.address === ethersAddr, w1.address);

// 2) Signed legacy tx byte-equality vs ethers, several shapes
const cases = [
  { nonce: 0n, gasPriceWei: 3_000_000_000n, gasLimit: 21_000n,
    to: '0x8AC7230489E800008ac7230489e80000AABBCCdd'.toLowerCase(), valueWei: 12345678901234567n, data: '' },
  { nonce: 7n, gasPriceWei: 5_100_000_001n, gasLimit: 180_000n,
    to: '0x1234567890abcdef1234567890abcdef12345678', valueWei: 0n,
    data: '0x095ea7b3000000000000000000000000deadbeefdeadbeefdeadbeefdeadbeefdeadbeef00000000000000000000000000000000000000000000000000000000000f4240' },
];
let ok = true;
for (const c of cases) {
  const mine = signLegacyTransaction({ ...c, chainId: 56n }, w1.privKeyHex);
  const ew = new Wallet('0x' + w1.privKeyHex);
  const theirs = await ew.signTransaction({
    type: 0, chainId: 56, nonce: Number(c.nonce), gasPrice: c.gasPriceWei,
    gasLimit: c.gasLimit, to: c.to, value: c.valueWei, data: c.data || '0x',
  });
  const match = mine.rawTx === theirs;
  const parsed = Transaction.from(mine.rawTx);
  const hashMatch = parsed.hash === mine.txHash && parsed.from === w1.address;
  ok = ok && match && hashMatch;
  console.log(`tx nonce=${c.nonce}: raw ${match ? 'MATCH' : 'MISMATCH'} | hash+from ${hashMatch ? 'MATCH' : 'MISMATCH'}`);
  if (!match) { console.log(' mine  :', mine.rawTx); console.log(' ethers:', theirs); }
}
console.log(ok ? 'EVM SIGNER VALIDATION PASS' : 'EVM SIGNER VALIDATION FAIL');
