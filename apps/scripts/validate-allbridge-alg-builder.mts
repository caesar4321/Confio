// Validates src/services/allbridgeAlgorand.ts against the official SDK and
// against MAINNET ITSELF via algod simulate (no signing, no spending):
//  1. core-field parity with the SDK's group (selector, args, amounts, fees)
//  2. simulate-driven resource population, then a named-resources-only
//     simulation must run CLEAN through the real bridge app end to end.
// Needs a mainnet address holding USDC + ~6 ALGO as SENDER (simulation
// only). Run on Allbridge SDK majors or bridge redeploys:
//   npm i --no-save @allbridge/bridge-core-sdk tsx && npx tsx scripts/validate-allbridge-alg-builder.mts

import { AllbridgeCoreSdk, nodeRpcUrlsDefault, Messenger, FeePaymentMethod } from '@allbridge/bridge-core-sdk';
import algosdk from 'algosdk';
import {
  fetchAllbridgeAlgConfig,
  fetchBridgeFeeMicroAlgo,
  buildAllbridgeDepositTail,
  populateDepositResources,
  assertGroupSimulates,
} from '../src/services/allbridgeAlgorand';

const SENDER = 'AAKAX2W6CYA6P53EW33ZAP4KGCNPONZRTGX4HHGABQXSWDW4MJY7Z4K4HM';
const DEST = '0x9b50414742fCB231e6465a5cAF58f2A1b541460A';

const sdk = new AllbridgeCoreSdk({ ...nodeRpcUrlsDefault, ALG: 'https://mainnet-api.4160.nodely.dev' });
const chains = await sdk.chainDetailsMap();
const usdcAlg = chains['ALG'].tokens.find((t: any) => t.symbol === 'USDC')!;
const usdtBsc = chains['BSC'].tokens.find((t: any) => t.symbol === 'USDT')!;

const sdkTxsRaw: any = await sdk.bridge.rawTxBuilder.send({
  amount: '25',
  fromAccountAddress: SENDER,
  toAccountAddress: DEST,
  sourceToken: usdcAlg,
  destinationToken: usdtBsc,
  messenger: Messenger.ALLBRIDGE,
  gasFeePaymentMethod: FeePaymentMethod.WITH_NATIVE_CURRENCY,
});
const sdkTxs = (Array.isArray(sdkTxsRaw) ? sdkTxsRaw : [sdkTxsRaw]).map((t: any) =>
  algosdk.decodeUnsignedTransaction(typeof t === 'string' ? Buffer.from(t, 'hex') : t),
);
console.log('SDK group size:', sdkTxs.length, sdkTxs.map((t) => t.type));

const cfg = await fetchAllbridgeAlgConfig();
const fee = await fetchBridgeFeeMicroAlgo(cfg.sourceChainId, cfg.destChainId);
const algod = new algosdk.Algodv2('', 'https://mainnet-api.4160.nodely.dev', '');
const sp = await algod.getTransactionParams().do();
const mine = buildAllbridgeDepositTail({
  sender: SENDER,
  usdcAmountMicro: 25_000_000n,
  destBscAddress: DEST,
  feeMicroAlgo: fee,
  suggestedParams: sp,
  config: cfg,
});

const tail = sdkTxs.slice(-5);
let ok = tail.length === mine.length;
const fields: string[] = [];
for (let i = 0; i < 5; i++) {
  const a: any = tail[i];
  const b: any = mine[i];
  const cmp = (name: string, va: any, vb: any) => {
    const eq = JSON.stringify(va) === JSON.stringify(vb);
    if (!eq) { ok = false; fields.push(`tx${i}.${name}: sdk=${va} mine=${vb}`); }
  };
  cmp('type', a.type, b.type);
  cmp('sender', a.sender.toString(), b.sender.toString());
  if (a.type === 'pay') {
    cmp('receiver', a.payment.receiver.toString(), b.payment.receiver.toString());
    cmp('amount', String(a.payment.amount), String(b.payment.amount));
  }
  if (a.type === 'axfer') {
    cmp('receiver', a.assetTransfer.receiver.toString(), b.assetTransfer.receiver.toString());
    cmp('amount', String(a.assetTransfer.amount), String(b.assetTransfer.amount));
    cmp('assetIndex', String(a.assetTransfer.assetIndex), String(b.assetTransfer.assetIndex));
  }
  if (a.type === 'appl') {
    cmp('appId', String(a.applicationCall.appIndex), String(b.applicationCall.appIndex));
    const aa = a.applicationCall.appArgs, ba = b.applicationCall.appArgs;
    cmp('appArgsLen', aa.length, ba.length);
    for (let j = 0; j < Math.min(aa.length, ba.length); j++) {
      if (i === 2 && j === 4) continue; // nonce: random by design
      cmp(`arg${j}`, Buffer.from(aa[j]).toString('hex'), Buffer.from(ba[j]).toString('hex'));
    }
    cmp('fee', String(a.fee), String(b.fee));
  }
}
fields.forEach((f) => console.log('DIFF', f));
console.log(ok ? 'core fields: MATCH' : 'core fields: MISMATCH');

// The real proof: populate resources via simulate, then the group must
// simulate CLEAN with named resources only (bridge validates everything).
const algodSim = { baseUrl: 'https://mainnet-api.4160.nodely.dev' };
const populated = await populateDepositResources(algodSim, mine);
await assertGroupSimulates(algodSim, populated);
console.log('named-resources-only simulate: CLEAN');
console.log(ok ? 'ALG BUILDER VALIDATION PASS' : 'VALIDATION FAIL');
