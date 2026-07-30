// EIP-7702 protocol rehearsal against a REAL EVM node (anvil, prague).
//
// Closes the one gap the Foundry suite models with vm.etch: the actual
// designation mechanics. A fresh user EOA with ZERO gas money signs (a) our
// authorization tuple and (b) our EIP-712 batch intent using the app's own
// evmWallet.ts functions; a sponsor account broadcasts the type-4
// transaction. PASS = the node accepts the authorization encoding, installs
// the 0xef0100 designation, executes the batch as the EOA, and the user
// still holds zero native balance.
//
// Run (needs forge artifacts: cd contracts/cusd_plus && forge build):
//   npm i --no-save ethers tsx && npx tsx scripts/rehearsal-7702.mts
//
// The sponsor here is a local anvil key; in production it is the KMS signer
// (cusd_plus/sponsor_7702.py builds the same transaction shape).

import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { Wallet, JsonRpcProvider, ContractFactory, Contract, Interface, NonceManager } from 'ethers';
import {
  hashBatchIntent,
  signIntentDigest,
  signSetCodeAuthorization,
  privKeyToAddress,
} from '../src/services/evmWallet';
import { hexToBytes } from '@noble/hashes/utils';

const CHAIN_ID = 31337n;
const ARTIFACTS = join(import.meta.dirname, '..', '..', 'contracts', 'cusd_plus', 'out');

const artifact = (sol: string, name: string) => {
  const a = JSON.parse(readFileSync(join(ARTIFACTS, `${sol}.sol`, `${name}.json`), 'utf8'));
  return { abi: a.abi, bytecode: a.bytecode.object as string };
};

const main = async () => {
  const anvil = spawn(join(homedir(), '.foundry', 'bin', 'anvil'),
    ['--hardfork', 'prague', '--port', '8547', '--silent']);
  try {
    await new Promise((r) => setTimeout(r, 1500));
    const provider = new JsonRpcProvider('http://127.0.0.1:8547', Number(CHAIN_ID));

    // anvil's funded key #0 plays the sponsor; the user is a fresh key with
    // NOTHING — exactly a production savings user.
    const sponsorWallet = new Wallet(
      '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80', provider);
    const sponsor = new NonceManager(sponsorWallet);
    const userPriv = 'a'.repeat(63) + '1';
    const user = privKeyToAddress(hexToBytes(userPriv));

    const del = artifact('ConfioBatchDelegate', 'ConfioBatchDelegate');
    const delegate = await (await new ContractFactory(del.abi, del.bytecode, sponsor).deploy())
      .waitForDeployment();
    const delegateAddr = (await delegate.getAddress()).toLowerCase();

    const tok = artifact('CusdPlusVault.t', 'MockToken');
    const token = await (await new ContractFactory(tok.abi, tok.bytecode, sponsor).deploy('USDT'))
      .waitForDeployment();
    const tokenAddr = await token.getAddress();
    await (await (token as Contract).mint(user, 1000n * 10n ** 18n)).wait();

    console.log('user EOA:', user, '· BNB balance:', await provider.getBalance(user));

    // The production deposit shape: approve + pull-style transfer, signed
    // ONCE by the user, broadcast + paid by the sponsor.
    const erc20 = new Interface(tok.abi);
    const sink = Wallet.createRandom().address;
    const calls = [
      { to: tokenAddr, valueWei: 0n, data: erc20.encodeFunctionData('approve', [sponsorWallet.address, 1n]) },
      { to: tokenAddr, valueWei: 0n, data: erc20.encodeFunctionData('transfer', [sink, 400n * 10n ** 18n]) },
    ];

    const auth = signSetCodeAuthorization(delegateAddr, 0n, userPriv, CHAIN_ID); // account nonce 0
    const digest = hashBatchIntent(calls, 0n, 9_999_999_999n, user, CHAIN_ID);
    const intentSig = signIntentDigest(digest, userPriv);

    const dif = new Interface(del.abi);
    const tx = await sponsor.sendTransaction({
      type: 4,
      to: user,
      data: dif.encodeFunctionData('execute', [
        calls.map((c) => [c.to, c.valueWei, c.data]), 0n, 9_999_999_999n, intentSig,
      ]),
      gasLimit: 1_000_000,
      authorizationList: [{
        address: auth.address,
        nonce: BigInt(auth.nonce),
        chainId: BigInt(auth.chainId),
        signature: { r: auth.r, s: auth.s, yParity: auth.yParity as 0 | 1 },
      }],
    });
    const rec = await tx.wait();

    const code = (await provider.getCode(user)).toLowerCase();
    const delegated = code === '0xef0100' + delegateAddr.slice(2);
    const sinkBal = await (token as Contract).balanceOf(sink);
    const userBnb = await provider.getBalance(user);
    const execNonce = await provider.call({ to: user, data: dif.encodeFunctionData('nonces') });

    console.log('tx status:', rec?.status, '· gas used:', rec?.gasUsed);
    console.log('delegation installed (0xef0100‖delegate):', delegated);
    console.log('batch executed (sink got 400 tokens):', sinkBal === 400n * 10n ** 18n);
    console.log('delegate nonce advanced:', BigInt(execNonce) === 1n);
    console.log('user BNB still ZERO:', userBnb === 0n);

    const pass = rec?.status === 1 && delegated && sinkBal === 400n * 10n ** 18n
      && BigInt(execNonce) === 1n && userBnb === 0n;
    console.log(pass ? '7702 REHEARSAL PASS' : '7702 REHEARSAL FAIL');
    process.exitCode = pass ? 0 : 1;
  } finally {
    anvil.kill();
  }
};

main().catch((e) => { console.error(e); process.exitCode = 1; });
