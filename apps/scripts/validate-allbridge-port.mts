// Validates the dependency-free pool-math port in src/services/allbridgeQuote.ts
// against the official SDK. Run whenever Allbridge bumps their SDK major:
//   npm i --no-save @allbridge/bridge-core-sdk tsx && npx tsx scripts/validate-allbridge-port.mts
// PASS requires worst-case receive delta <= $1e-5 across both directions.

import { AllbridgeCoreSdk, nodeRpcUrlsDefault } from '@allbridge/bridge-core-sdk';
import { getBridgeQuote, fetchSnapshot } from '../src/services/allbridgeQuote';

const sdk = new AllbridgeCoreSdk(nodeRpcUrlsDefault);
const chains = await sdk.chainDetailsMap();
const usdcAlg = chains['ALG'].tokens.find((t: any) => t.symbol === 'USDC')!;
const usdtBsc = chains['BSC'].tokens.find((t: any) => t.symbol === 'USDT')!;

await fetchSnapshot(true); // same moment as the SDK's map (within seconds)

let worst = 0;
for (const amt of [100, 500, 1000, 5000, 20000, 40000]) {
  const sdkRecvAB = Number(await sdk.getAmountToBeReceived(String(amt), usdcAlg, usdtBsc));
  const mineAB = (await getBridgeQuote(amt, 'alg_to_bsc')).receiveUsd;
  const sdkRecvBA = Number(await sdk.getAmountToBeReceived(String(amt), usdtBsc, usdcAlg));
  const mineBA = (await getBridgeQuote(amt, 'bsc_to_alg')).receiveUsd;
  const dAB = Math.abs(sdkRecvAB - mineAB);
  const dBA = Math.abs(sdkRecvBA - mineBA);
  worst = Math.max(worst, dAB, dBA);
  console.log(
    `$${amt}: alg→bsc sdk=${sdkRecvAB} port=${mineAB} Δ=${dAB.toExponential(2)} | ` +
    `bsc→alg sdk=${sdkRecvBA} port=${mineBA} Δ=${dBA.toExponential(2)}`
  );
}
console.log(worst <= 1e-5 ? `VALIDATION PASS (worst Δ $${worst})` : `VALIDATION FAIL (worst Δ $${worst})`);
