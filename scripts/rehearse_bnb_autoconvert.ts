// BNB auto-convert mainnet rehearsal — drives the PRODUCTION primitives
// (apps/src/services/evmWallet.ts: selector/encode/sign/sendCall) against
// real BSC, since the RN-coupled service module itself can't load in Node.
// The quote/calldata lines are verbatim copies of bnbAutoConvert.ts; any
// drift between the two is a rehearsal bug — diff them when editing.
//
// Phases (pick with argv):
//   quote                       read-only getAmountsOut sanity (free)
//   keygen                      make + persist the rehearsal key, print address
//   swap                        run the swap with production sendCall
//   sweep <sponsor>             return USDT + leftover BNB to the sponsor
//   balances                    print BNB/USDT at the rehearsal address
//
// Key custody rule (memory: keys NEVER only in tmp): the key persists at
// .rehearsal_key_bsc in the repo root until the sweep leaves nothing.

import { readFileSync, writeFileSync, existsSync } from 'fs';
import {
  bscBnbBalance,
  bscGasPrice,
  bscEthCall,
  sendCall,
  selector,
  encodeUint,
  encodeAddress,
  privKeyToAddress,
} from '../apps/src/services/evmWallet';

// WBNB from router.WETH() — rehearsal caught a fabricated hardcoded value.
let cachedWbnb: string | null = null;
const routerWbnb = async (router: string): Promise<string> => {
  if (!cachedWbnb) {
    const ret = await bscEthCall(router, selector('WETH()'));
    cachedWbnb = '0x' + ret.replace(/^0x/, '').slice(-40);
  }
  return cachedWbnb;
};
const USDT_BSC = '0x55d398326f99059fF775485246999027B3197955';
const ROUTER = '0x10ED43C718714eb63d5aA57B78B54704E256024E';
const KEY_FILE = new URL('../.rehearsal_key_bsc', import.meta.url).pathname;
const SWAP_GAS_LIMIT = 250_000n;

// ── verbatim from bnbAutoConvert.ts ─────────────────────────────────────
const quoteUsdtOut = async (router: string, wbnb: string, bnbInWei: bigint): Promise<bigint> => {
  const data =
    selector('getAmountsOut(uint256,address[])') +
    encodeUint(bnbInWei) +
    encodeUint(0x40n) +
    encodeUint(2n) +
    encodeAddress(wbnb) +
    encodeAddress(USDT_BSC);
  const ret = await bscEthCall(router, data);
  const hex = ret.replace(/^0x/, '');
  if (hex.length < 64 * 4) throw new Error(`getAmountsOut: short return (${ret.slice(0, 20)}…)`);
  return BigInt('0x' + hex.slice(64 * 3, 64 * 4));
};

const swapCalldata = (wbnb: string, minOut: bigint, recipient: string, deadline: bigint): string =>
  selector('swapExactETHForTokens(uint256,address[],address,uint256)') +
  encodeUint(minOut) +
  encodeUint(0x80n) +
  encodeAddress(recipient) +
  encodeUint(deadline) +
  encodeUint(2n) +
  encodeAddress(wbnb) +
  encodeAddress(USDT_BSC);
// ── end verbatim ────────────────────────────────────────────────────────

const loadKey = (): { address: string; privKeyHex: string } => {
  const privKeyHex = readFileSync(KEY_FILE, 'utf8').trim();
  return { address: privKeyToAddress(Buffer.from(privKeyHex, 'hex')), privKeyHex };
};

const usdtBalance = async (addr: string): Promise<bigint> => {
  const ret = await bscEthCall(USDT_BSC, selector('balanceOf(address)') + encodeAddress(addr));
  return BigInt(ret === '0x' ? 0 : ret);
};

const main = async () => {
  const phase = process.argv[2];

  if (phase === 'quote') {
    const probe = 4_000_000_000_000_000n; // 0.004 BNB
    const out = await quoteUsdtOut(ROUTER, await routerWbnb(ROUTER), probe);
    console.log(`quote: 0.004 BNB -> ${Number(out) / 1e18} USDT`);
    if (out < 10n ** 17n || out > 10n ** 19n) throw new Error('quote outside sane $0.1–$10 band');
    console.log('QUOTE_OK (encoding + parsing verified against mainnet router)');
    return;
  }

  if (phase === 'keygen') {
    if (existsSync(KEY_FILE)) {
      console.log('key exists:', loadKey().address);
      return;
    }
    const { randomBytes } = await import('crypto');
    const priv = randomBytes(32).toString('hex');
    writeFileSync(KEY_FILE, priv, { mode: 0o600 });
    console.log('rehearsal address:', privKeyToAddress(Buffer.from(priv, 'hex')));
    return;
  }

  const wallet = loadKey();

  if (phase === 'balances') {
    console.log('address', wallet.address);
    console.log('BNB ', Number(await bscBnbBalance(wallet.address)) / 1e18);
    console.log('USDT', Number(await usdtBalance(wallet.address)) / 1e18);
    return;
  }

  if (phase === 'swap') {
    // Production sizing with rehearsal-scale numbers: keep enough BNB for
    // this swap's fee + the two sweep-back txs.
    const balance = await bscBnbBalance(wallet.address);
    let gasPriceWei = await bscGasPrice();
    if (gasPriceWei < 100_000_000n) gasPriceWei = 100_000_000n;
    gasPriceWei = (gasPriceWei * 12n) / 10n;
    const feeBudget = gasPriceWei * SWAP_GAS_LIMIT;
    const sweepReserve = gasPriceWei * 130_000n; // USDT transfer (~60k) + BNB send (21k) + margin
    const swapValue = balance - feeBudget - sweepReserve;
    console.log('balance', balance, 'swapValue', swapValue);
    if (swapValue < 3_000_000_000_000_000n) throw new Error('below production min swap (fund more)');

    const quoted = await quoteUsdtOut(ROUTER, await routerWbnb(ROUTER), swapValue);
    const minOut = (quoted * 9_900n) / 10_000n; // production default 100 bps
    const deadline = BigInt(Math.floor(Date.now() / 1000) + 600);
    console.log(`swapping ${Number(swapValue) / 1e18} BNB, quote ${Number(quoted) / 1e18} USDT, minOut ${Number(minOut) / 1e18}`);

    const receipt = await sendCall({
      from: wallet.address,
      privKeyHex: wallet.privKeyHex,
      to: ROUTER,
      data: swapCalldata(await routerWbnb(ROUTER), minOut, wallet.address, deadline),
      valueWei: swapValue,
      gasLimit: SWAP_GAS_LIMIT,
    });
    console.log('SWAP_OK', receipt.transactionHash, 'status', receipt.status);
    console.log('USDT now', Number(await usdtBalance(wallet.address)) / 1e18);
    return;
  }

  if (phase === 'sweep') {
    const sponsor = process.argv[3];
    if (!/^0x[0-9a-fA-F]{40}$/.test(sponsor || '')) throw new Error('sweep needs sponsor address');
    const usdt = await usdtBalance(wallet.address);
    if (usdt > 0n) {
      const r1 = await sendCall({
        from: wallet.address,
        privKeyHex: wallet.privKeyHex,
        to: USDT_BSC,
        data: selector('transfer(address,uint256)') + encodeAddress(sponsor) + encodeUint(usdt),
        gasLimit: 80_000n,
      });
      console.log('USDT swept:', r1.transactionHash);
    }
    // Return every remaining wei above the exact cost of the final send.
    const bal = await bscBnbBalance(wallet.address);
    let gasPriceWei = await bscGasPrice();
    if (gasPriceWei < 100_000_000n) gasPriceWei = 100_000_000n;
    gasPriceWei = (gasPriceWei * 12n) / 10n;
    const sendable = bal - gasPriceWei * 21_000n;
    if (sendable > 0n) {
      const r2 = await sendCall({
        from: wallet.address,
        privKeyHex: wallet.privKeyHex,
        to: sponsor,
        data: '0x',
        valueWei: sendable,
        gasLimit: 21_000n,
      });
      console.log('BNB swept:', r2.transactionHash);
    }
    console.log('SWEEP_DONE — residual BNB', Number(await bscBnbBalance(wallet.address)) / 1e18,
                'USDT', Number(await usdtBalance(wallet.address)) / 1e18);
    return;
  }

  throw new Error(`unknown phase: ${phase}`);
};

main().catch((e) => { console.error('REHEARSAL_FAIL:', e.message || e); process.exit(1); });
