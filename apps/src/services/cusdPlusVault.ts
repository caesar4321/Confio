// cUSD+ vault client — leg C: the actual on-chain mint/redeem.
//
// This is the non-custodial core both savings entry paths converge on:
//   - direct USDT-BSC rail (user already holds USDT on BSC)
//   - conversion flow's final leg (cUSD → burn → Allbridge → USDT-BSC → here)
// The user signs every transaction with their own EVM key (getActiveEvmWallet);
// Confío only sponsors gas (server-side dusting). Nothing custodial here.
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
  BscReceipt,
} from './evmWallet';
import { getActiveEvmWallet } from './secureDeterministicWallet';
import { installBscServerTransport } from './bscServerRpc';
import { executeSponsoredBatch, fetchSponsored7702Params } from './sponsored7702';

// USDT (Binance-Peg BSC-USD) is fixed on BSC mainnet; the vault address is
// deployment-specific and comes from the server.
export const USDT_BSC = '0x55d398326f99059fF775485246999027B3197955';

const MAX_UINT256 = (1n << 256n) - 1n;

export interface SubscribeParams {
  /** cUSD+ vault proxy address (from server config). */
  vaultAddress: string;
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

// Reads ride the same server relay as everything else (transport installed
// below); never a direct fetch to a public node from the app.
const ethCall = async (to: string, data: string): Promise<string> => {
  const { bscEthCall } = await import('./evmWallet');
  return bscEthCall(to, data);
};

const currentAllowance = async (
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
 * Fallback rail: the original two self-signed legacy txs (gas dusting).
 * Idempotent-ish: skips the approve when allowance already covers the amount.
 */
export const subscribeUsdtToSavings = async (
  params: SubscribeParams,
): Promise<SubscribeResult> => {
  installBscServerTransport(); // client signs, SERVER injects (cUSD parity)
  const wallet = params.wallet ?? (await getActiveEvmWallet());
  const from = wallet.address;
  const { vaultAddress, usdtWei } = params;
  const minUsdyOut = params.minUsdyOut ?? 0n;

  const approveData = encodeCall('approve(address,uint256)', [
    { type: 'address', value: vaultAddress },
    { type: 'uint', value: MAX_UINT256 },
  ]);
  const mintData = encodeCall('subscribeAndMint(uint256,uint256,address)', [
    { type: 'uint', value: usdtWei },
    { type: 'uint', value: minUsdyOut },
    { type: 'address', value: from },
  ]);
  const needsApprove = (await currentAllowance(from, vaultAddress, USDT_BSC)) < usdtWei;

  // ── 7702 sponsored path ──
  const sponsored = await fetchSponsored7702Params();
  if (sponsored.enabled && sponsored.delegateAddress) {
    try {
      const calls: BatchCall[] = [
        // Approve max once — avoids a re-approve on every future deposit.
        ...(needsApprove ? [{ to: USDT_BSC, valueWei: 0n, data: approveData }] : []),
        { to: vaultAddress, valueWei: 0n, data: mintData },
      ];
      const rec = await executeSponsoredBatch({
        wallet,
        calls,
        delegateAddress: sponsored.delegateAddress,
      });
      // One atomic tx: the approve (if any) shares the mint's hash.
      return {
        approveTx: needsApprove ? rec.transactionHash : undefined,
        mintTx: rec.transactionHash,
        recipient: from,
      };
    } catch (e) {
      // Sponsored rail down ≠ savings down: fall back to the self-signed
      // legacy path (needs gas dust; the server keeps that rail armed).
      console.warn('[cusdPlusVault] sponsored subscribe failed, using legacy path', e);
    }
  }

  // ── legacy self-signed path ──
  let approveTx: string | undefined;
  if (needsApprove) {
    const rec = await sendCall({
      from,
      privKeyHex: wallet.privKeyHex,
      to: USDT_BSC,
      data: approveData,
    });
    approveTx = rec.transactionHash;
  }

  const mintRec: BscReceipt = await sendCall({
    from,
    privKeyHex: wallet.privKeyHex,
    to: vaultAddress,
    data: mintData,
  });

  return { approveTx, mintTx: mintRec.transactionHash, recipient: from };
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

/**
 * Withdraw from cUSD+ back to USDT-BSC (redeemToUsdt). Burns `shares` and
 * sends USDT to `recipient` (defaults to the user's own address; the
 * Guardarian off-ramp passes the sell order's deposit address so the vault
 * pays the ramp directly — no intermediate hop). The USD amount is
 * shares × pPlus (server displays the quote); minUsdtOut is the slippage floor.
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
      return { redeemTx: rec.transactionHash, recipient };
    } catch (e) {
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
