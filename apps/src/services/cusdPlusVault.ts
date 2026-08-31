// cUSD+ vault client — leg C: the actual on-chain mint/redeem.
//
// This is the non-custodial core both savings entry paths converge on:
//   - direct USDT-BSC rail (user already holds USDT on BSC)
//   - conversion flow's final leg (cUSD → burn → Allbridge → USDT-BSC → here)
// The user signs every transaction with their own EVM key (getActiveEvmWallet);
// Confío only sponsors gas (EIP-7702 sponsored batches). Nothing custodial here.
//
// Sizing (measured on a BSC mainnet fork against the real Ondo IM):
//   subscribeAndMint ≈ 599k gas, approve ≈ 46k. sendCall estimates ×1.3.
//
// The vault + USDT addresses are served by the backend (cusdPlusConvertParams
// / a config query) so we never hardcode chain wiring in a release — passed
// in by the caller, which reads them from the server.

import {
  BatchCall,
  DerivedEvmWallet,
  encodeCall,
  sendCall,
  BscReceipt, isOutcomeUnknown } from './evmWallet';
import { getActiveEvmWallet } from './secureDeterministicWallet';
import { installBscServerTransport } from './bscServerRpc';
import { executeSponsoredBatch, fetchSponsored7702Params } from './sponsored7702';

// USDT (Binance-Peg BSC-USD) is fixed on BSC mainnet; the vault address is
// deployment-specific and comes from the server.
export const USDT_BSC = '0x55d398326f99059fF775485246999027B3197955';

const MAX_UINT256 = (1n << 256n) - 1n;

/**
 * Ondo's USDY Instant Manager will not process a redemption below $1.
 *
 * Two DIFFERENT numbers, deliberately (round 3 [P2] #7 — the earlier single
 * constant was cited from ConfioStockRouter's ~$0.98, which is the Global
 * Markets stock manager, not this one):
 *
 *  - IM_MIN_REDEEM_WEI is the hard REJECTION threshold. A position whose
 *    whole redemption lands under it cannot exit through the vault at all.
 *    Set at the real $1.00, so a full position worth $1.00-$1.05 — which
 *    redeems perfectly well — is not refused for no reason.
 *  - IM_MIN_TARGET_WEI is what we AIM a sized slice at, with margin above
 *    the boundary so the vault's double flooring cannot land under it. Any
 *    excess just stays as raw USDT and re-mints on the next savings resume.
 *
 * Ondo documents this as a configurable, USD-denominated value, so treat
 * both as a floor on OUR side rather than a mirror of theirs; if Ondo raises
 * it, the redeem reverts atomically and nothing is lost.
 */
const IM_MIN_REDEEM_WEI = 10n ** 18n;
const IM_MIN_TARGET_WEI = (105n * 10n ** 18n) / 100n;

export interface SubscribeParams {
  /** cUSD+ vault proxy address (from server config). */
  vaultAddress: string;
  /** Universal cUSD vault used to quote the entry fee before Ondo subscribe. */
  cusdAddress?: string;
  /** USDT amount in 18-dp base units (BSC USDT is 18 decimals). */
  usdtWei: bigint;
  /** IM slippage floor in USDY 18-dp units; 0 is safe (direct mint, no book). */
  minUsdyOut?: bigint;
  /** Optional pre-derived wallet (else derived for the active account). */
  wallet?: DerivedEvmWallet;
}

export interface SubscribeResult {
  approveTx?: string;
  mintTx: string;
  recipient: string;
}

export interface MintCusdParams {
  /** Universal cUSD UUPS proxy address (from server config). */
  cusdAddress: string;
  /** Gross USDT entering the Confío dollar perimeter. */
  usdtWei: bigint;
  /** Minimum net cUSD after the contract-authoritative 0.9% fee. */
  minCusdOut?: bigint;
  wallet?: DerivedEvmWallet;
}

const INTERNAL_CONVERSION_MIN_OUT_BPS = 9_950n;

// Reads ride the same server relay as everything else (transport installed
// below); never a direct fetch to a public node from the app.
const ethCall = async (to: string, data: string): Promise<string> => {
  const { bscEthCall } = await import('./evmWallet');
  return bscEthCall(to, data);
};

export const getErc20Allowance = async (
  owner: string, spender: string, token: string,
): Promise<bigint> => {
  const res = await ethCall(token, encodeCall('allowance(address,address)', [
    { type: 'address', value: owner },
    { type: 'address', value: spender },
  ]));
  return res && res !== '0x' ? BigInt(res) : 0n;
};

/**
 * Deposit USDT-BSC into cUSD+ savings (approve if needed, then
 * subscribeAndMint) and return the mined tx hashes.
 *
 * Preferred rail (server-flagged): ONE user signature over the whole batch,
 * executed sponsor-paid via EIP-7702 — the user's address needs zero BNB.
 * Fallback rail: two self-signed legacy txs (needs the user's OWN BNB —
 * the dust rail was removed 2026-07-30).
 * Idempotent-ish: skips the approve when allowance already covers the amount.
 */
export const subscribeUsdtToSavings = async (
  params: SubscribeParams,
): Promise<SubscribeResult> => {
  installBscServerTransport(); // client signs, SERVER injects (cUSD parity)
  const wallet = params.wallet ?? (await getActiveEvmWallet());
  const from = wallet.address;
  const { vaultAddress, usdtWei } = params;
  let minUsdyOut = params.minUsdyOut;
  if (minUsdyOut == null) {
    if (!params.cusdAddress) {
      throw new Error('cUSD vault required for fee-aware mint preview');
    }
    const preview = await previewCusdMint(params.cusdAddress, usdtWei);
    const oraclePriceWad = await getCurrentOraclePrice(vaultAddress);
    if (oraclePriceWad <= 0n) throw new Error('invalid USDY oracle price');
    const expectedUsdy = preview.netWei * 10n ** 18n / oraclePriceWad;
    minUsdyOut = expectedUsdy * INTERNAL_CONVERSION_MIN_OUT_BPS / 10_000n;
  }

  const approveData = encodeCall('approve(address,uint256)', [
    { type: 'address', value: vaultAddress },
    { type: 'uint', value: MAX_UINT256 },
  ]);
  const mintData = encodeCall('subscribeAndMint(uint256,uint256,address)', [
    { type: 'uint', value: usdtWei },
    { type: 'uint', value: minUsdyOut },
    { type: 'address', value: from },
  ]);
  const needsApprove = (await getErc20Allowance(from, vaultAddress, USDT_BSC)) < usdtWei;

  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) {
    throw new Error('cUSD+ mint requires sponsor');
  }
  const calls: BatchCall[] = [
    ...(needsApprove ? [{ to: USDT_BSC, valueWei: 0n, data: approveData }] : []),
    { to: vaultAddress, valueWei: 0n, data: mintData },
  ];
  const rec = await executeSponsoredBatch({
    wallet,
    calls,
    delegateAddress: sponsored.delegateAddress,
  });
  return {
    approveTx: needsApprove ? rec.txHash : undefined,
    mintTx: rec.txHash,
    recipient: from,
  };
};

/**
 * Convert raw USDT into universal cUSD. Minting is sponsor-required by the
 * contract, so unlike legacy cUSD+ code this function never attempts a
 * self-funded fallback. The holder signs the exact 7702 intent; Confío's
 * sponsor pays gas and is the only party allowed to originate the mint.
 */
export const mintUsdtToCusd = async (params: MintCusdParams): Promise<SubscribeResult> => {
  installBscServerTransport();
  const wallet = params.wallet ?? (await getActiveEvmWallet());
  const from = wallet.address;
  const { cusdAddress, usdtWei } = params;

  const approveData = encodeCall('approve(address,uint256)', [
    { type: 'address', value: cusdAddress },
    { type: 'uint', value: MAX_UINT256 },
  ]);
  const preview = params.minCusdOut == null
    ? await previewCusdMint(cusdAddress, usdtWei)
    : null;
  const mintData = encodeCall('mintWithFee(uint256,uint256,address)', [
    { type: 'uint', value: usdtWei },
    { type: 'uint', value: params.minCusdOut ?? preview!.netWei },
    { type: 'address', value: from },
  ]);
  const needsApprove = (await getErc20Allowance(from, cusdAddress, USDT_BSC)) < usdtWei;
  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) {
    throw new Error('cUSD mint requires sponsor');
  }

  const calls: BatchCall[] = [
    ...(needsApprove ? [{ to: USDT_BSC, valueWei: 0n, data: approveData }] : []),
    { to: cusdAddress, valueWei: 0n, data: mintData },
  ];
  const rec = await executeSponsoredBatch({
    wallet,
    calls,
    delegateAddress: sponsored.delegateAddress,
  });
  return {
    approveTx: needsApprove ? rec.txHash : undefined,
    mintTx: rec.txHash,
    recipient: from,
  };
};

/**
 * Send raw wallet USDT to any BSC address — the exit for landed-but-not-
 * minted money and for geo-ineligible users' "Confío Dollar" balance.
 *
 * Preferred rail: ONE user signature, sponsor-paid via EIP-7702 (policy
 * allows the USDT transfer selector since 2026-07-30) — the user's address
 * needs zero BNB. Fallback: a self-signed legacy transfer (works only with
 * user-funded BNB at the address; the dust rail was removed 2026-07-30).
 */
export const transferUsdt = async (params: {
  /** Recipient BSC address (0x…), unrestricted — exits are never gated. */
  to: string;
  /** Amount in 18-dp base units. */
  amountWei: bigint;
  wallet?: DerivedEvmWallet;
}): Promise<{ txHash: string }> => {
  installBscServerTransport();
  const wallet = params.wallet ?? (await getActiveEvmWallet());
  const data = encodeCall('transfer(address,uint256)', [
    { type: 'address', value: params.to },
    { type: 'uint', value: params.amountWei },
  ]);

  const sponsored = await fetchSponsored7702Params();
  if (sponsored.enabled && sponsored.delegateAddress) {
    try {
      const calls: BatchCall[] = [{ to: USDT_BSC, valueWei: 0n, data }];
      const rec = await executeSponsoredBatch({
        wallet,
        calls,
        delegateAddress: sponsored.delegateAddress,
      });
      return { txHash: rec.txHash };
    } catch (e) {
      // Fall back ONLY when we know nothing can still land. A receipt
      // timeout means the sponsored tx is already on the network with an
      // unknown outcome — broadcasting a second, self-signed transfer there
      // is how the SAME payment gets made twice (and this function funds
      // ramp deposits, so the second one goes to a provider that has already
      // been paid). Surface it instead, hash and all, so the caller can
      // reconcile rather than re-send.
      if (isOutcomeUnknown(e)) throw e;
      console.warn('[cusdPlusVault] sponsored transfer failed before broadcast, using legacy path', e);
    }
  }

  const rec: BscReceipt = await sendCall({
    from: wallet.address,
    privKeyHex: wallet.privKeyHex,
    to: USDT_BSC,
    data,
    gasLimit: 80_000n,
  });
  return { txHash: rec.transactionHash };
};

/** Vault share balance (ERC20 balanceOf) for an owner address. */
export const getVaultShares = async (
  vaultAddress: string, owner: string,
): Promise<bigint> => {
  const res = await ethCall(vaultAddress, encodeCall('balanceOf(address)', [
    { type: 'address', value: owner },
  ]));
  return res && res !== '0x' ? BigInt(res) : 0n;
};

/** Raw wallet USDT (18dp), read through the server relay like everything else. */
export const getUsdtBalanceWei = async (owner: string): Promise<bigint> => {
  return getErc20BalanceWei(USDT_BSC, owner);
};

export const getErc20BalanceWei = async (token: string, owner: string): Promise<bigint> => {
  const { selector, encodeAddress } = await import('./evmWallet');
  const hex = await ethCall(token, selector('balanceOf(address)') + encodeAddress(owner));
  return hex && hex !== '0x' ? BigInt(hex) : 0n;
};

const previewCusdRedeem = async (
  cusdAddress: string,
  grossCusdWei: bigint,
): Promise<{ feeWei: bigint; netWei: bigint }> => {
  const hex = (await ethCall(cusdAddress, encodeCall('previewRedeem(uint256)', [
    { type: 'uint', value: grossCusdWei },
  ]))).replace(/^0x/, '');
  if (hex.length < 128) throw new Error('invalid cUSD fee preview');
  return {
    feeWei: BigInt('0x' + hex.slice(0, 64)),
    netWei: BigInt('0x' + hex.slice(64, 128)),
  };
};

const previewCusdMint = async (
  cusdAddress: string,
  grossUsdtWei: bigint,
): Promise<{ feeWei: bigint; netWei: bigint }> => {
  const hex = (await ethCall(cusdAddress, encodeCall('previewMint(uint256)', [
    { type: 'uint', value: grossUsdtWei },
  ]))).replace(/^0x/, '');
  if (hex.length < 128) throw new Error('invalid cUSD fee preview');
  return {
    feeWei: BigInt('0x' + hex.slice(0, 64)),
    netWei: BigInt('0x' + hex.slice(64, 128)),
  };
};

/** The vault's share price and guard-validated USDY price, both 1e18. */
export const getVaultPrices = async (
  vaultAddress: string,
): Promise<{ pPlusWad: bigint; oraclePriceWad: bigint }> => {
  const { selector } = await import('./evmWallet');
  const [pp, op] = await Promise.all([
    ethCall(vaultAddress, selector('pPlus()')),
    ethCall(vaultAddress, selector('lastOraclePrice()')),
  ]);
  return {
    pPlusWad: pp && pp !== '0x' ? BigInt(pp) : 0n,
    oraclePriceWad: op && op !== '0x' ? BigInt(op) : 0n,
  };
};

/** Live oracle value the vault's next accrue()/mint will consume. */
const getCurrentOraclePrice = async (vaultAddress: string): Promise<bigint> => {
  const { selector } = await import('./evmWallet');
  const oracleWord = (await ethCall(vaultAddress, selector('ORACLE()'))).replace(/^0x/, '');
  if (oracleWord.length < 64) throw new Error('invalid USDY oracle address');
  const oracleAddress = '0x' + oracleWord.slice(-40);
  const price = await ethCall(oracleAddress, selector('getPrice()'));
  return price && price !== '0x' ? BigInt(price) : 0n;
};

/**
 * USDT a redeemToUsdt(shares) would ACTUALLY deliver — the exact mirror of
 * CusdPlusVault.redeemToUsdt + _imRedeem, which floors TWICE:
 *   usdyOut = shares × pPlus / p      (floor)
 *   usdtOut = usdyOut × p / 1e18      (floor)
 * shares × pPlus / 1e18 is an OVER-estimate and must never be used to decide
 * whether a redeem covers an amount (mirrors cusd_plus/vault.redeem_usdt_out).
 */
export const predictRedeemUsdtOut = (
  shares: bigint, pPlusWad: bigint, oraclePriceWad: bigint,
): bigint => {
  if (oraclePriceWad <= 0n || shares <= 0n) return 0n;
  const usdyOut = (shares * pPlusWad) / oraclePriceWad;
  return (usdyOut * oraclePriceWad) / 10n ** 18n;
};

/** Inverse of the above: shares to burn to net at least `usdtWei`. Rounds UP
 *  and adds a 1-wei-per-floor cushion, so the prediction never lands short. */
export const sharesForUsdtOut = (
  usdtWei: bigint, pPlusWad: bigint,
): bigint => {
  if (pPlusWad <= 0n || usdtWei <= 0n) return 0n;
  return (usdtWei * 10n ** 18n + pPlusWad - 1n) / pPlusWad + 2n;
};

/** Exact mirror of vault.subscribeAndMint at the current validated prices. */
export const predictSubscribeSharesOut = (
  usdtWei: bigint, pPlusWad: bigint, oraclePriceWad: bigint,
): bigint => {
  if (usdtWei <= 0n || pPlusWad <= 0n || oraclePriceWad <= 0n) return 0n;
  const usdyOut = (usdtWei * 10n ** 18n) / oraclePriceWad;
  return (usdyOut * oraclePriceWad) / pPlusWad;
};

/**
 * Everything this wallet can actually move out in one withdrawal: transient
 * USDT plus the fee-net outputs of cUSD and the WHOLE cUSD+ position. Uses
 * predicted/contract-previewed values rather than nominal balances, so the
 * figure can be withdrawn rather than merely displayed.
 */
export const maxWithdrawableUsdtWei = async (params: {
  owner: string;
  vaultAddress?: string | null;
  cusdAddress?: string | null;
}): Promise<bigint> => {
  installBscServerTransport();
  const raw = await getUsdtBalanceWei(params.owner);
  let total = raw;
  if (params.cusdAddress) {
    const cusd = await getErc20BalanceWei(params.cusdAddress, params.owner);
    if (cusd > 0n) total += (await previewCusdRedeem(params.cusdAddress, cusd)).netWei;
  }
  if (!params.vaultAddress) return total;
  const shares = await getVaultShares(params.vaultAddress, params.owner);
  if (shares <= 0n) return total;
  const { pPlusWad, oraclePriceWad } = await getVaultPrices(params.vaultAddress);
  const grossPlus = predictRedeemUsdtOut(shares, pPlusWad, oraclePriceWad);
  // cUSD+ permissionless exits cross the same cUSD fee perimeter. The live
  // cUSD preview is authoritative; using it also remains correct if the Safe
  // lowers the bounded fee after this app ships.
  const plusNet = params.cusdAddress && grossPlus > 0n
    ? (await previewCusdRedeem(params.cusdAddress, grossPlus)).netWei
    : grossPlus;
  return total + plusNet;
};

export class InsufficientWithdrawableError extends Error {
  readonly availableWei: bigint;
  constructor(availableWei: bigint) {
    super('insufficient_withdrawable');
    this.name = 'InsufficientWithdrawableError';
    this.availableWei = availableWei;
  }
}

/**
 * Pay `amountWei` of USDT to `to` (a ramp provider's deposit address),
 * redeeming cUSD+ shares first if raw USDT doesn't cover it — as ONE
 * sponsored batch.
 *
 * Why one batch (audit 2026-08-03 [P1]): the redeem and transfer used to be
 * separate sponsored calls. A failure between them could leave the shares
 * redeemed while the provider order remained unfunded. Atomicity removes
 * that partial-state window entirely: if the redeem
 * under-delivers, the transfer reverts with it and nothing moved.
 *
 * Share sizing: only the shares actually needed are burned, and minUsdtOut is
 * derived from the PREDICTED output of exactly those shares (never from the
 * shortfall alone — a shortfall-sized floor let a whole position burn for a
 * fraction of its value and still satisfy the order, audit [P1] #4).
 */
export const fundUsdtDestination = async (params: {
  /** Provider deposit address. Unrestricted — exits are never geo-gated. */
  to: string;
  /** Exact order amount in 18-dp base units. */
  amountWei: bigint;
  /** Server-vouched gross Confío-dollar debit. Present on fee-capable
   *  off-ramp orders; the provider receives amountWei after the fee. */
  grossDebitWei?: bigint | null;
  /** cUSD+ vault proxy; omit when that position is absent. */
  vaultAddress?: string | null;
  /** Universal cUSD proxy; redeemed first when present. */
  cusdAddress?: string | null;
  wallet?: DerivedEvmWallet;
}): Promise<{ txHash: string; redeemedShares: bigint }> => {
  installBscServerTransport();
  const wallet = params.wallet ?? (await getActiveEvmWallet());
  const { to, amountWei, vaultAddress } = params;

  const transferData = encodeCall('transfer(address,uint256)', [
    { type: 'address', value: to },
    { type: 'uint', value: amountWei },
  ]);

  const rawUsdt = await getUsdtBalanceWei(wallet.address);
  let calls: BatchCall[] = [{ to: USDT_BSC, valueWei: 0n, data: transferData }];
  let shares = 0n;
  let redeemedCusd = 0n;
  const feeAware = !!params.grossDebitWei && params.grossDebitWei > 0n;
  // Under the live perimeter, transient raw USDT is never a normal funding
  // source. A fee-aware withdrawal must actually redeem the vouched gross
  // cUSD/cUSD+ amount; otherwise a just-arrived raw balance could pay the
  // provider directly and skip the conversion fee.
  let fundingUsdt = feeAware ? 0n : rawUsdt;

  if (feeAware) {
    // New fee-capable off-ramps normalize mixed cUSD+ into cUSD first and
    // perform ONE fee-bearing cUSD redemption. Two independent exits each
    // ceil their fee and can underfund an exact provider order by one wei.
    if (!params.cusdAddress) throw new InsufficientWithdrawableError(0n);
    const gross = params.grossDebitWei!;
    const cusdOwned = await getErc20BalanceWei(params.cusdAddress, wallet.address);
    const normalizedCalls: BatchCall[] = [];
    if (cusdOwned < gross) {
      const shortfall = gross - cusdOwned;
      if (!vaultAddress) throw new InsufficientWithdrawableError(cusdOwned);
      const owned = await getVaultShares(vaultAddress, wallet.address);
      const { pPlusWad, oraclePriceWad } = await getVaultPrices(vaultAddress);
      if (owned <= 0n || pPlusWad <= 0n || oraclePriceWad <= 0n) {
        throw new InsufficientWithdrawableError(cusdOwned);
      }
      let unwrapShares = sharesForUsdtOut(shortfall, pPlusWad);
      if (unwrapShares > owned) unwrapShares = owned;
      const predictedGross = predictRedeemUsdtOut(
        unwrapShares, pPlusWad, oraclePriceWad);
      if (predictedGross < shortfall || predictedGross < IM_MIN_REDEEM_WEI) {
        throw new InsufficientWithdrawableError(cusdOwned + predictedGross);
      }
      shares = unwrapShares;
      normalizedCalls.push({
        to: vaultAddress,
        valueWei: 0n,
        data: encodeCall('unwrapToCusd(uint256,uint256,address)', [
          { type: 'uint', value: unwrapShares },
          { type: 'uint', value: shortfall },
          { type: 'address', value: wallet.address },
        ]),
      });
    }
    const preview = await previewCusdRedeem(params.cusdAddress, gross);
    if (preview.netWei < amountWei) {
      throw new InsufficientWithdrawableError(preview.netWei);
    }
    normalizedCalls.push({
      to: params.cusdAddress,
      valueWei: 0n,
      data: encodeCall('redeemWithFee(uint256,uint256,address)', [
        { type: 'uint', value: gross },
        { type: 'uint', value: preview.netWei },
        { type: 'address', value: wallet.address },
      ]),
    });
    calls = [...normalizedCalls, ...calls];
    fundingUsdt = preview.netWei;
    redeemedCusd = gross;
  }

  if (!feeAware && fundingUsdt < amountWei && params.cusdAddress) {
    const cusdOwned = await getErc20BalanceWei(params.cusdAddress, wallet.address);
    if (cusdOwned > 0n) {
      const shortfall = amountWei - fundingUsdt;
      // 90 bps is the immutable ceiling. Start with its ceil inverse, then
      // use the contract's live preview as authority (the configured fee may
      // be lower) and fall back to the whole balance for a mixed cUSD/cUSD+
      // withdrawal.
      let gross = (shortfall * 10_000n + 9_910n - 1n) / 9_910n;
      if (params.grossDebitWei && fundingUsdt === 0n) gross = params.grossDebitWei;
      if (gross > cusdOwned) gross = cusdOwned;
      let preview = await previewCusdRedeem(params.cusdAddress, gross);
      if (preview.netWei < shortfall && gross < cusdOwned) {
        gross = cusdOwned;
        preview = await previewCusdRedeem(params.cusdAddress, gross);
      }
      redeemedCusd = gross;
      fundingUsdt += preview.netWei;
      calls = [{
        to: params.cusdAddress,
        valueWei: 0n,
        data: encodeCall('redeemWithFee(uint256,uint256,address)', [
          { type: 'uint', value: gross },
          { type: 'uint', value: preview.netWei },
          { type: 'address', value: wallet.address },
        ]),
      }, ...calls];
    }
  }

  if (!feeAware && fundingUsdt < amountWei) {
    // Short on raw USDT — the shortfall comes out of the vault, in the same
    // batch. An ineligible user (no shares, no vault) never reaches here
    // unless they genuinely cannot cover the amount.
    const shortfall = amountWei - fundingUsdt;
    if (!vaultAddress) throw new InsufficientWithdrawableError(fundingUsdt);

    const owned = await getVaultShares(vaultAddress, wallet.address);
    if (owned <= 0n) throw new InsufficientWithdrawableError(fundingUsdt);

    const { pPlusWad, oraclePriceWad } = await getVaultPrices(vaultAddress);
    if (pPlusWad <= 0n || oraclePriceWad <= 0n) {
      // Unreadable price: sizing the burn would be a guess. Refuse rather
      // than redeem blind — the money is still in the user's own wallet.
      throw new Error('No pudimos leer el precio de tu ahorro. Intenta de nuevo en un momento.');
    }

    // Size the burn ABOVE the shortfall, for two independent reasons:
    //
    //  1. Headroom. Sizing shares to deliver exactly the shortfall and then
    //     flooring at `max(99% of expected, shortfall)` collapses to exactly
    //     the predicted output — a nominal 1% tolerance that is really 0%,
    //     so any Ondo haircut reverts the batch (re-audit [P1] #3).
    //  2. Ondo's Instant Manager has a $1 minimum redemption. A small
    //     shortfall would ask for a sub-$1 redeem the IM rejects outright —
    //     which the old redeem-everything path never hit (re-audit [P1] #2).
    //
    // The ORDER being funded is guaranteed by the transfer leg itself: if the
    // redeem under-delivers, the transfer cannot cover `amountWei` and the
    // whole atomic batch reverts. That frees minUsdtOut to do its real job —
    // protecting the VALUE of the shares being burned.
    const feeAdjustedGross = (shortfall * 10_000n + 9_910n - 1n) / 9_910n;
    const legacyHeadroomGross = (shortfall * 100n) / 99n + 1n;
    const requestedGross = fundingUsdt === 0n && feeAware
      ? params.grossDebitWei!
      : (feeAware ? feeAdjustedGross : legacyHeadroomGross);
    const target = requestedGross > IM_MIN_TARGET_WEI ? requestedGross : IM_MIN_TARGET_WEI;
    const needed = sharesForUsdtOut(target, pPlusWad);
    shares = needed < owned ? needed : owned;
    const expectedGrossOut = predictRedeemUsdtOut(shares, pPlusWad, oraclePriceWad);
    const expectedOut = feeAware && params.cusdAddress
      ? (await previewCusdRedeem(params.cusdAddress, expectedGrossOut)).netWei
      : expectedGrossOut;

    if (expectedOut < IM_MIN_REDEEM_WEI) {
      // The entire position redeems to less than Ondo will process. Nothing
      // we can do on-chain — say so instead of broadcasting a certain revert.
      throw new InsufficientWithdrawableError(fundingUsdt);
    }
    if (fundingUsdt + expectedOut < amountWei) {
      // The whole position still doesn't cover it — the server authorized
      // against shares × pPlus, which over-states what a double-floored
      // redeem delivers. Report the honest figure.
      throw new InsufficientWithdrawableError(fundingUsdt + expectedOut);
    }

    // Pure value protection now, with genuine room: 1% off what these exact
    // shares are predicted to yield. Not raised to the shortfall — doing that
    // is what removed the tolerance in the first place.
    //
    // KNOWN, BOUNDED EXPOSURE (round 3 [P1] #6): this is priced off the
    // CURRENT pPlus, but redeemToUsdt calls accrue() first. If an accrual
    // lands between this read and execution, pPlus rises by at most
    // MAX_ACCRUAL_JUMP_BPS (2%) net of the vault's yield share (~1.7%), so
    // the floor is worth ~0.99/1.017 = 97.35% of execution-time value — a
    // worst case of ~2.65%, and only when a bad IM fill coincides with an
    // accrual. Deliberately NOT tightened here: a tighter client-side floor
    // buys a fraction of a percent and pays for it in reverted withdrawals,
    // which is the trade that broke this path once already. The real fix is
    // contract-side — pass a slippage BPS and let the vault compute the
    // floor AFTER accrue(), where the execution-time value is known.
    const minUsdtOut = (expectedOut * 99n) / 100n;

    calls = [
      {
        to: vaultAddress,
        valueWei: 0n,
        data: encodeCall('redeemToUsdt(uint256,uint256,address)', [
          { type: 'uint', value: shares },
          { type: 'uint', value: minUsdtOut },
          // To OURSELVES: the vault paying the provider directly would bind
          // the burn to a cached valuation. Atomic, so there is no window.
          { type: 'address', value: wallet.address },
        ]),
      },
      ...calls,
    ];
  }

  const sponsored = await fetchSponsored7702Params();
  if (sponsored.enabled && sponsored.delegateAddress) {
    const rec = await executeSponsoredBatch({
      wallet,
      calls,
      delegateAddress: sponsored.delegateAddress,
    });
    return { txHash: rec.txHash, redeemedShares: shares };
  }

  // ── legacy self-signed path (needs the user's OWN BNB) ──
  // Reached only when sponsorship is switched OFF server-side. A sponsored
  // batch that FAILED is never retried here: it may already be on the
  // network, and a second transfer would pay an already-funded provider
  // order twice (audit [P1] #2).
  //
  // Vault-backed funding is NOT offered on this path. Two self-signed
  // transactions cannot give the atomicity this function promises — the
  // redeem could land and the transfer fail, leaving burned shares and an
  // unfunded order, which is the exact failure the batch exists to prevent
  // (re-audit [P2] #8). Raw-USDT-only funding is a single transfer and is
  // still safe, so it continues.
  if (shares > 0n || redeemedCusd > 0n) {
    throw new Error(
      'Los retiros desde tu ahorro no están disponibles en este momento. '
      + 'Intenta de nuevo en unos minutos.',
    );
  }
  const rec: BscReceipt = await sendCall({
    from: wallet.address,
    privKeyHex: wallet.privKeyHex,
    to: USDT_BSC,
    data: transferData,
    gasLimit: 80_000n,
  });
  return { txHash: rec.transactionHash, redeemedShares: shares };
};

/**
 * Withdraw from cUSD+ back to USDT-BSC (redeemToUsdt). Burns `shares` and
 * sends USDT to `recipient`, defaulting to the user's own address.
 *
 * NOT the off-ramp path: both ramp rails now go through
 * fundUsdtDestination(), which redeems to the USER and pays the provider in
 * the same atomic batch. Nothing redeems straight to a provider's deposit
 * address any more — that bound the burn to a cached valuation. This is the
 * plain "move my savings back to spendable USDT" primitive.
 *
 * minUsdtOut is the slippage floor; note the vault floors TWICE on the way
 * out, so shares × pPlus over-states the result (see predictRedeemUsdtOut).
 */
export const redeemSavingsToUsdt = async (params: {
  vaultAddress: string;
  shares: bigint;
  minUsdtOut?: bigint;
  recipient?: string;
  wallet?: DerivedEvmWallet;
}): Promise<{ redeemTx: string; recipient: string }> => {
  installBscServerTransport(); // client signs, SERVER injects (cUSD parity)
  const wallet = params.wallet ?? (await getActiveEvmWallet());
  const from = wallet.address;
  const recipient = params.recipient || from;
  const redeemData = encodeCall('redeemToUsdt(uint256,uint256,address)', [
    { type: 'uint', value: params.shares },
    { type: 'uint', value: params.minUsdtOut ?? 0n },
    { type: 'address', value: recipient },
  ]);

  // ── 7702 sponsored path (one signature, zero BNB needed) ──
  const sponsored = await fetchSponsored7702Params();
  if (sponsored.enabled && sponsored.delegateAddress) {
    try {
      const rec = await executeSponsoredBatch({
        wallet,
        calls: [{ to: params.vaultAddress, valueWei: 0n, data: redeemData }],
        delegateAddress: sponsored.delegateAddress,
      });
      return { redeemTx: rec.txHash, recipient };
    } catch (e) {
      // Fall back ONLY when nothing can still land — same rule as the
      // transfer path below. An outcome-unknown sponsored batch is ALREADY
      // on the network; running the legacy self-signed path here would
      // execute the same vault call twice (Codex re-audit 2026-08-02 [P1]).
      if (isOutcomeUnknown(e)) throw e;
      console.warn('[cusdPlusVault] sponsored redeem failed, using legacy path', e);
    }
  }

  // ── legacy self-signed path ──
  const rec = await sendCall({
    from,
    privKeyHex: wallet.privKeyHex,
    to: params.vaultAddress,
    data: redeemData,
  });
  return { redeemTx: rec.transactionHash, recipient };
};
