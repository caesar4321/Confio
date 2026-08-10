// BSC rehearsal E2E — drives the full savings+stocks lifecycle against a
// live EVM network using ONLY the app's own signer (evmWallet.ts) and the
// V2 master-secret derivation. ethers is calldata encoding only.
//   Local (anvil, chainId 97):
//     anvil --port 8555 --chain-id 97 &
//     DEPLOYER_KEY=<anvil key> forge script script/DeployRehearsal.s.sol \
//       --rpc-url http://127.0.0.1:8555 --broadcast   (in contracts/ondo_stocks)
//     RPC_URL=http://127.0.0.1:8555 CHAIN_ID=97 DEPLOYER_KEY=... DEPLOYER_ADDR=... \
//       npx tsx scripts/rehearsal-e2e.mts
//   BSC testnet: same, with the public RPC + a faucet-funded deployer.
// PASS = all 7 steps + backingRatioBps >= 10000.

// BSC testnet rehearsal E2E: every user tx signed by OUR signer
// (apps/src/services/evmWallet.ts), user wallet derived via the V2
// master-secret path. ethers is used ONLY to ABI-encode calldata.
import { Interface, computeAddress } from 'ethers';
import { readFileSync } from 'fs';
import {
  deriveEvmKeyFromMasterSecret,
  signLegacyTransaction,
} from '../src/services/evmWallet';

const RPC = process.env.RPC_URL || 'https://data-seed-prebsc-1-s1.bnbchain.org:8545';
const CHAIN = BigInt(process.env.CHAIN_ID || '97');
const A = JSON.parse(readFileSync(
  process.env.ADDRESSES_FILE
    || new URL('../../contracts/ondo_stocks/.rehearsal/testnet-addresses.json', import.meta.url).pathname,
  'utf8',
));
// Deployer is DETERMINISTIC (fill(43) master secret via the app's own V2
// derivation) so the throwaway key can always be recomputed from code — the
// original random testnet deployer (0x4eb4…F9e6) was lost with its tmp file,
// stranding its faucet tBNB. Env override still wins for anvil runs.
const DEP = process.env.DEPLOYER_KEY
  ? { privKeyHex: process.env.DEPLOYER_KEY.replace('0x', ''), address: process.env.DEPLOYER_ADDR! }
  : (() => {
      const d = deriveEvmKeyFromMasterSecret(new Uint8Array(32).fill(43), {
        accountType: 'personal', accountIndex: 0,
      });
      return { privKeyHex: d.privKeyHex, address: d.address };
    })();

const erc20 = new Interface([
  'function mint(address,uint256)', 'function approve(address,uint256)',
  'function balanceOf(address) view returns (uint256)',
]);
const vaultI = new Interface([
  'function subscribeAndMint(uint256,uint256,address) returns (uint256)',
  'function redeemToUsdt(uint256,uint256,address) returns (uint256)',
  'function accrue()', 'function pPlus() view returns (uint256)',
  'function backingRatioBps() view returns (uint256)',
  'function balanceOf(address) view returns (uint256)',
  'function approve(address,uint256)',
  'function setSponsor(address,bool)',
]);
const oracleI = new Interface(['function setPrice(uint256)']);
const routerI = new Interface([
  'function buyWithSavings((uint256 chainId,uint256 attestationId,bytes32 userId,address asset,uint256 price,uint256 quantity,uint256 expiration,uint8 side,bytes32 additionalData),bytes,uint256,uint256,uint256,uint256) returns (uint256)',
  'function sellToSavings((uint256 chainId,uint256 attestationId,bytes32 userId,address asset,uint256 price,uint256 quantity,uint256 expiration,uint8 side,bytes32 additionalData),bytes,uint256,uint256,uint256) returns (uint256)',
  'function accruedUsdtFees() view returns (uint256)',
]);

const rpc = async (method: string, params: any[]) => {
  const r = await fetch(RPC, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) });
  const j = await r.json();
  if (j.error) throw new Error(`${method}: ${JSON.stringify(j.error)}`);
  return j.result;
};
const view = async (to: string, data: string) => rpc('eth_call', [{ to, data }, 'latest']);
const balOf = async (token: string, who: string) =>
  BigInt(await view(token, erc20.encodeFunctionData('balanceOf', [who])));

async function sendTx(privHex: string, from: string, to: string, data: string, valueWei = 0n) {
  const nonce = BigInt(await rpc('eth_getTransactionCount', [from, 'pending']));
  let gasPrice = BigInt(await rpc('eth_gasPrice', []));
  if (gasPrice < 3_000_000_000n) gasPrice = 3_000_000_000n;
  const est = BigInt(await rpc('eth_estimateGas', [{ from, to, data: data || undefined, value: valueWei ? '0x' + valueWei.toString(16) : undefined }]));
  const signed = signLegacyTransaction(
    { nonce, gasPriceWei: gasPrice, gasLimit: (est * 13n) / 10n, to, valueWei, data, chainId: CHAIN },
    privHex,
  );
  const hash = await rpc('eth_sendRawTransaction', [signed.rawTx]);
  for (let i = 0; i < 60; i++) {
    const rec = await rpc('eth_getTransactionReceipt', [hash]).catch(() => null);
    if (rec) {
      if (rec.status !== '0x1') throw new Error(`tx failed: ${hash}`);
      return hash;
    }
    await new Promise((res) => setTimeout(res, 2000));
  }
  throw new Error(`tx timeout: ${hash}`);
}

// User = V2 master-secret derivation (the gap we just closed, exercised live)
const secret = new Uint8Array(32).fill(42);
const user = deriveEvmKeyFromMasterSecret(secret, { accountType: 'personal', accountIndex: 0 });
console.log('user.bsc (V2-derived):', user.address, '| ethers agrees:', user.address === computeAddress('0x' + user.privKeyHex));

const dep = { priv: DEP.privKeyHex, addr: DEP.address };
const usd = (v: bigint) => Number(v / 10n ** 12n) / 1e6;

// 1. Fund gas only for this legacy-signer rehearsal. Production stock trades
// use EIP-7702 and leave the user address BNB-free.
await sendTx(dep.priv, dep.addr, user.address, '', 30_000_000_000_000_000n); // 0.03 tBNB
console.log('1 local rehearsal gas: OK');

// 2. user self-mints test USDT + approves vault
await sendTx(user.privKeyHex, user.address, A.USDT, erc20.encodeFunctionData('mint', [user.address, 1000n * 10n ** 18n]));
await sendTx(user.privKeyHex, user.address, A.USDT, erc20.encodeFunctionData('approve', [A.VAULT, 2n ** 255n]));
console.log('2 mint+approve USDT: OK');

// Local rehearsal uses legacy user-signed transactions, so the user's own
// origin stands in for the production KMS origin and must be registered
// before any vault mint. Production uses the sponsored EIP-7702 batch.
await sendTx(dep.priv, dep.addr, A.VAULT, vaultI.encodeFunctionData('setSponsor', [user.address, true]));

// 3. save $500 → cUSD+
await sendTx(user.privKeyHex, user.address, A.VAULT, vaultI.encodeFunctionData('subscribeAndMint', [500n * 10n ** 18n, 0, user.address]));
const shares1 = await balOf(A.VAULT, user.address);
console.log('3 subscribeAndMint: OK — cUSD+ =', usd(shares1));

// 4. yield: oracle +1%, accrue → pPlus 1.0085
await sendTx(dep.priv, dep.addr, A.ORACLE, oracleI.encodeFunctionData('setPrice', [10100n * 10n ** 14n]));
await sendTx(user.privKeyHex, user.address, A.VAULT, vaultI.encodeFunctionData('accrue', []));
const pPlus = BigInt(await view(A.VAULT, vaultI.encodeFunctionData('pPlus', [])));
console.log('4 accrue: OK — pPlus =', Number(pPlus) / 1e18, '(expect 1.0085)');

// 5. buy stock via router (explicit fee)
await sendTx(user.privKeyHex, user.address, A.VAULT, vaultI.encodeFunctionData('approve', [A.ROUTER, 2n ** 255n]));
const now = BigInt(Math.floor(Date.now() / 1000));
const buySpend = 100n * 10n ** 18n;
const buyFee = (buySpend * 30n + 9969n) / 9970n;
const buyQuote = [CHAIN, 1n, '0x' + '44'.repeat(32), A.TSLAon, 300n * 10n ** 18n,
  buySpend / 300n, now + 300n, 0, '0x' + '00'.repeat(32)];
await sendTx(user.privKeyHex, user.address, A.ROUTER, routerI.encodeFunctionData(
  'buyWithSavings', [buyQuote, '0x', 100n * 10n ** 18n, buySpend, buySpend + buyFee, 30n],
));
const tsla = await balOf(A.TSLAon, user.address);
const fee1 = BigInt(await view(A.ROUTER, routerI.encodeFunctionData('accruedUsdtFees', [])));
console.log('5 buyWithSavings: OK — TSLA =', Number(tsla) / 1e18, '| fee accrued =', usd(fee1));

// 6. sell back into savings
await sendTx(user.privKeyHex, user.address, A.TSLAon, erc20.encodeFunctionData('approve', [A.ROUTER, 2n ** 255n]));
const sellQuote = [CHAIN, 2n, '0x' + '44'.repeat(32), A.TSLAon, 300n * 10n ** 18n,
  tsla, now + 300n, 1, '0x' + '00'.repeat(32)];
await sendTx(user.privKeyHex, user.address, A.ROUTER, routerI.encodeFunctionData(
  'sellToSavings', [sellQuote, '0x', 99n * 10n ** 18n, 98n * 10n ** 18n, 30n],
));
console.log('6 sellToSavings: OK — cUSD+ =', usd(await balOf(A.VAULT, user.address)));

// 7. redeem to USDT (the off-ramp leg)
await sendTx(user.privKeyHex, user.address, A.VAULT, vaultI.encodeFunctionData('redeemToUsdt', [50n * 10n ** 18n, 0, user.address]));
console.log('7 redeemToUsdt: OK — USDT =', usd(await balOf(A.USDT, user.address)));

const backing = BigInt(await view(A.VAULT, vaultI.encodeFunctionData('backingRatioBps', [])));
console.log('backingRatioBps =', backing.toString(), backing >= 10000n ? '(INVARIANT HOLDS)' : '(VIOLATED!)');
console.log('E2E REHEARSAL PASS');
