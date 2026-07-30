// Validates src/services/evmWallet.ts (derivation + legacy tx signing)
// byte-for-byte against ethers v6. Run on any change to the signer or a
// @noble/curves major bump:
//   npm i --no-save ethers tsx && npx tsx scripts/validate-evm-signer.mts
// PASS requires: deterministic + domain-separated derivation, address equal
// to ethers.computeAddress, and raw tx bytes identical to ethers for every
// case (value transfer, zero-value contract call with data).

import { Wallet, computeAddress, Transaction, TypedDataEncoder, verifyTypedData } from 'ethers';
import { sha256 } from '@noble/hashes/sha256';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils';
import {
  deriveEvmKeyFromMasterSecret,
  hashBatchIntent,
  signIntentDigest,
  signLegacyTransaction,
  signSetCodeAuthorization,
  toChecksumAddress,
} from '../src/services/evmWallet';

// 1) Derivation determinism + address correctness (V2 master-secret only —
// legacy V1 wallets have no EVM sibling by design)
const masterSecret = sha256(utf8ToBytes('test-master-secret-abc123'));
const opts = { accountType: 'personal', accountIndex: 0 };
const w1 = deriveEvmKeyFromMasterSecret(masterSecret, opts);
const w2 = deriveEvmKeyFromMasterSecret(masterSecret, { ...opts });
const wBiz = deriveEvmKeyFromMasterSecret(masterSecret, { ...opts, accountType: 'business', businessId: '42' });
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
// 3) EIP-7702 authorization tuple vs ethers wallet.authorize
const DELEGATE = '0x7777777777777777777777777777777777777777';
{
  const ew = new Wallet('0x' + w1.privKeyHex);
  const mine = signSetCodeAuthorization(DELEGATE, 5n, w1.privKeyHex, 56n);
  const theirs = await ew.authorize({ address: DELEGATE, nonce: 5, chainId: 56 });
  const authMatch =
    BigInt(mine.r) === BigInt(theirs.signature.r) &&
    BigInt(mine.s) === BigInt(theirs.signature.s) &&
    mine.yParity === theirs.signature.yParity;
  ok = ok && authMatch;
  console.log(`7702 authorization tuple: ${authMatch ? 'MATCH' : 'MISMATCH'}`);
}

// 4) EIP-712 batch intent vs ethers TypedDataEncoder (+ recovery), and the
// shared cross-stack vector (forge test_sharedEip712Vector / Django
// test_shared_eip712_vector). Never change one alone.
{
  const types = {
    Call: [
      { name: 'to', type: 'address' },
      { name: 'value', type: 'uint256' },
      { name: 'data', type: 'bytes' },
    ],
    Execute: [
      { name: 'calls', type: 'Call[]' },
      { name: 'nonce', type: 'uint256' },
      { name: 'deadline', type: 'uint256' },
    ],
  };
  const domain = (verifyingContract: string) => ({
    name: 'ConfioBatchDelegate', version: '1', chainId: 56, verifyingContract,
  });

  const calls = [
    { to: '0x1234567890abcdef1234567890abcdef12345678', valueWei: 0n, data: '0x095ea7b3' + '00'.repeat(64) },
    { to: '0x8AC7230489E800008ac7230489e80000AABBCCdd'.toLowerCase(), valueWei: 3n, data: '0x' },
  ];
  const mineDigest = '0x' + bytesToHex(hashBatchIntent(calls, 9n, 1_900_000_000n, w1.address, 56n));
  const value = {
    calls: calls.map((c) => ({ to: c.to, value: c.valueWei, data: c.data })),
    nonce: 9n, deadline: 1_900_000_000n,
  };
  const theirsDigest = TypedDataEncoder.hash(domain(w1.address), types, value);
  const digestMatch = mineDigest === theirsDigest;

  const sig = signIntentDigest(hashBatchIntent(calls, 9n, 1_900_000_000n, w1.address, 56n), w1.privKeyHex);
  const recovered = verifyTypedData(domain(w1.address), types, value, sig);
  const recoverMatch = recovered === w1.address;

  // Shared fixed vector (verifyingContract 0x…0aa, chainId 56):
  const vectorCalls = [
    { to: '0x1111111111111111111111111111111111111111', valueWei: 0n, data: '0xdeadbeef' },
    { to: '0x2222222222222222222222222222222222222222', valueWei: 1_000_000n, data: '0x' },
  ];
  const vectorDigest = '0x' + bytesToHex(hashBatchIntent(
    vectorCalls, 7n, 1_900_000_000n, '0x00000000000000000000000000000000000000aa', 56n));
  const vectorMatch =
    vectorDigest === '0xcc3b97117afebdebc5713d09e5cbefbed16143c3405bda7b6516c0bc7efce6c6';

  ok = ok && digestMatch && recoverMatch && vectorMatch;
  console.log(`712 digest vs ethers: ${digestMatch ? 'MATCH' : 'MISMATCH'}`);
  console.log(`712 signature recovery: ${recoverMatch ? 'MATCH' : 'MISMATCH'}`);
  console.log(`712 shared cross-stack vector: ${vectorMatch ? 'MATCH' : 'MISMATCH'}`);
}

console.log(ok ? 'EVM SIGNER VALIDATION PASS' : 'EVM SIGNER VALIDATION FAIL');
