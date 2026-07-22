// BNB auto-convert — the BSC mirror of the mainnet ALGO→USDC auto-swap.
//
// Confío is a dollar app: mis-deposited BNB at a user's address (someone
// withdrew BNB from Binance to their Confío 0x address) is swapped to USDT
// via PancakeSwap V2, client-signed with the user's own key. The USDT lands
// at the user's own address, where the server's monitor_bridge_arrivals
// treats it like any external deposit (gas dusting + savings resume).
//
// Invariants this flow preserves:
//   - The swap pays its own gas out of the mis-deposited BNB; sponsor dust
//     is never spent, and the live dust target (keepWei) is left behind so
//     the user's next savings leg doesn't immediately need re-dusting.
//   - Every outbound BNB tx this produces goes through the server relay,
//     which records it in the BnbAutoConvert ledger. That keeps "outbound
//     BNB not in the ledger = dust extraction" a deterministic signal.
//   - The relay only accepts swapExactETHForTokens to the router, so this
//     service (and only this shape of tx) clears the selector guard.
//
// All knobs come from cusdPlusConvertParams — nothing chain-wiring is
// hardcoded in a release except the canonical WBNB/USDT addresses, which
// are fixed on BSC mainnet.

import { gql } from '@apollo/client';
import {
  bscBnbBalance,
  bscGasPrice,
  bscEthCall,
  sendCall,
  selector,
  encodeUint,
  encodeAddress,
} from './evmWallet';
import { getActiveEvmWallet } from './secureDeterministicWallet';
import { installBscServerTransport } from './bscServerRpc';
import { USDT_BSC } from './cusdPlusVault';

const IN_FLIGHT = gql`
  query BnbAutoConvertInFlightCheck {
    cusdPlusConversionsInFlight {
      conversionId
      status
    }
  }
`;

// The monitor matches a USDT arrival >= 90% of an awaited bridge quote as
// that conversion's leg B. A sweep firing while bridge USDT is still in
// flight could therefore be mis-attributed (funds still reach the same
// user, but the saga's books lie). Statuses that mean "arrival awaited":
const AWAITING_BRIDGE = new Set(['SRC_COMMITTED', 'STUCK']);

const REGISTER_ARRIVAL = gql`
  mutation RegisterBscUsdtArrival($txHash: String!) {
    registerBscUsdtArrival(txHash: $txHash) {
      success
      recorded
      error
    }
  }
`;

const bridgeArrivalAwaited = async (): Promise<boolean> => {
  const { apolloClient } = await import('../apollo/client');
  const { data } = await apolloClient.query({
    query: IN_FLIGHT,
    fetchPolicy: 'network-only', // stale cache here defeats the guard
  });
  return (data?.cusdPlusConversionsInFlight || []).some((r: any) =>
    AWAITING_BRIDGE.has(r.status),
  );
};

// WBNB comes from the router itself (WETH()), never a hardcoded constant:
// the 2026-07-22 rehearsal caught a fabricated WBNB address producing
// reasonless reverts (wrong token → CREATE2 pairFor → empty contract).
// Chain truth beats constants. Cached — routers never change their WETH.
let cachedWbnb: string | null = null;
const routerWbnb = async (router: string): Promise<string> => {
  if (!cachedWbnb) {
    const ret = await bscEthCall(router, selector('WETH()'));
    cachedWbnb = '0x' + ret.replace(/^0x/, '').slice(-40);
  }
  return cachedWbnb;
};

// Single-hop WBNB→USDT via the V2 router measured well under this; the
// fixed limit also lets us budget the swap value without a circular
// estimate (estimateGas fails when value + fee exceeds the balance).
const SWAP_GAS_LIMIT = 250_000n;

export interface BnbAutoConvertParams {
  /** PancakeSwap V2 router (server-config; also relay-allowlisted). */
  router: string;
  /** Skip swaps smaller than this — gas/slippage overhead isn't worth it. */
  minSwapWei: bigint;
  /** BNB left at the address (live gas-dust target from the server). */
  keepWei: bigint;
  /** Slippage floor applied to the getAmountsOut quote, in bps. */
  slippageBps: bigint;
  /** cUSD+ vault (server config) — lets the sweep finish the mint leg. */
  vaultAddress?: string;
}

/** Quote the swap through the router's own pricing (eth_call, read-only). */
const quoteUsdtOut = async (router: string, wbnb: string, bnbInWei: bigint): Promise<bigint> => {
  // getAmountsOut(uint256,address[]) with path [WBNB, USDT]. encodeCall only
  // handles static args, so the dynamic array is laid out by hand:
  // head = amountIn, offset(0x40); tail = len(2), WBNB, USDT.
  const data =
    selector('getAmountsOut(uint256,address[])') +
    encodeUint(bnbInWei) +
    encodeUint(0x40n) +
    encodeUint(2n) +
    encodeAddress(wbnb) +
    encodeAddress(USDT_BSC);
  const ret = await bscEthCall(router, data);
  // Return shape: offset, len, amounts[0] (=in), amounts[1] (=out).
  const hex = ret.replace(/^0x/, '');
  if (hex.length < 64 * 4) throw new Error(`getAmountsOut: short return (${ret.slice(0, 20)}…)`);
  return BigInt('0x' + hex.slice(64 * 3, 64 * 4));
};

/**
 * Swap the address's excess BNB to USDT. Returns the tx hash, or null when
 * there's nothing (or too little) to convert. Throws on chain errors — the
 * caller treats this as fire-and-forget and retries on next foreground.
 */
export const maybeAutoConvertBnb = async (
  params: BnbAutoConvertParams,
): Promise<string | null> => {
  installBscServerTransport(); // client signs, SERVER injects (cUSD parity)
  const wallet = await getActiveEvmWallet();

  const balance = await bscBnbBalance(wallet.address);

  // Budget the swap's own fee at the same floored/×1.2 price sendCall will
  // use, so the signed tx can never be underfunded by its own value.
  let gasPriceWei = await bscGasPrice();
  if (gasPriceWei < 100_000_000n) gasPriceWei = 100_000_000n;
  gasPriceWei = (gasPriceWei * 12n) / 10n;
  const feeBudget = gasPriceWei * SWAP_GAS_LIMIT;

  const swapValue = balance - params.keepWei - feeBudget;
  if (swapValue < params.minSwapWei) return null;

  // Defer (not cancel) while a conversion's bridge USDT is still expected —
  // the next foreground retries after the saga settles. Checked only once a
  // sweep is actually due, so the common no-BNB path costs no query.
  if (await bridgeArrivalAwaited()) return null;

  const wbnb = await routerWbnb(params.router);
  const quoted = await quoteUsdtOut(params.router, wbnb, swapValue);
  const minOut = (quoted * (10_000n - params.slippageBps)) / 10_000n;
  if (minOut <= 0n) return null;

  const deadline = BigInt(Math.floor(Date.now() / 1000) + 600);
  // swapExactETHForTokens(amountOutMin, path, to, deadline) — head words
  // then the path tail, mirroring the quote encoding above.
  const data =
    selector('swapExactETHForTokens(uint256,address[],address,uint256)') +
    encodeUint(minOut) +
    encodeUint(0x80n) +
    encodeAddress(wallet.address) +
    encodeUint(deadline) +
    encodeUint(2n) +
    encodeAddress(wbnb) +
    encodeAddress(USDT_BSC);

  const receipt = await sendCall({
    from: wallet.address,
    privKeyHex: wallet.privKeyHex,
    to: params.router,
    data,
    valueWei: swapValue,
    gasLimit: SWAP_GAS_LIMIT,
  });

  // One-shot UX (Algorand auto-swap parity): don't leave the USDT waiting
  // for the beat scanner + a second foreground. Register the arrival now,
  // then run the same resume that mints recorded deposits — swap, record,
  // mint, all in this session. Best-effort: on any failure the beat scan +
  // next foreground deliver the old two-step behavior, funds never at risk.
  if (params.vaultAddress) {
    try {
      const { apolloClient } = await import('../apollo/client');
      const { data: reg } = await apolloClient.mutate({
        mutation: REGISTER_ARRIVAL,
        variables: { txHash: receipt.transactionHash },
      });
      if (reg?.registerBscUsdtArrival?.recorded) {
        const { resumeSavingsMints } = await import('./savingsLegC');
        await resumeSavingsMints(params.vaultAddress);
      }
    } catch (e) {
      console.warn('[BnbAutoConvert] in-session mint continuation failed (beat scan will finish):', e);
    }
  }
  return receipt.transactionHash;
};
