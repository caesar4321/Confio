// One Emergency Exit transaction: execute([assertSilent(), leg]) sent by the
// user's EOA to its own address through ConfioBatchDelegate (EIP-7702).
//
// The heartbeat check and the value-moving leg are in ONE atomic batch, so
// the leg can only land if the chain itself says Confío has been silent for
// silenceRequired. No RPC, DNS or device state can fake that.
//
// Self-call path: the delegate skips signature checks when msg.sender is the
// EOA itself, so nonce/deadline/intentId/signature are zero/empty. An EOA that
// was never delegated (or points at another delegate) sends a type-4 tx that
// installs the trusted delegate in the same transaction — self-sponsored, so
// the authorization nonce is the tx nonce + 1.

import {
  BscRevertedError,
  BATCH_DELEGATE_NONCE_SLOT,
  DerivedEvmWallet,
  TRUSTED_BATCH_DELEGATES,
  bscEstimateGas,
  bscGasPrice,
  bscGetCode,
  bscGetNonce,
  bscGetStorageAt,
  bscSendRawTransaction,
  bscWaitForReceipt,
  BscReceipt,
  encodeExecuteCalldata,
  receiptExecutedBatch,
  selector,
  signLegacyTransaction,
  signSetCodeAuthorization,
  signSetCodeTransaction,
  BSC_NETWORK,
} from '../evmWallet';
import { BUNDLED_HEARTBEAT, ConfioAliveError, isUsableAddress, readHeartbeat } from './heartbeat';

/** execute() wrapper + assertSilent(): calldata, nonce SSTORE, the extra call. */
export const GATE_GAS_OVERHEAD = 60_000n;
/** EIP-7702 per-authorization cost (25k) plus headroom. */
export const AUTH_GAS_OVERHEAD = 30_000n;

const ZERO32 = '0x' + '00'.repeat(32);
/** The delegate the exit installs — read lazily (the list is build-pinned). */
const exitDelegate = (): string => TRUSTED_BATCH_DELEGATES[0];

export const isDelegatedToTrusted = (code: string): boolean =>
  (code || '').toLowerCase() === '0xef0100' + exitDelegate().replace(/^0x/, '').toLowerCase();

/** The gated batch for one leg — exported for tests. */
export const gatedCalls = (heartbeat: string, leg: { to: string; data: string }) => [
  { to: heartbeat, valueWei: 0n, data: selector('assertSilent()') },
  { to: leg.to, valueWei: 0n, data: leg.data },
];

export const sendGatedCall = async (params: {
  wallet: DerivedEvmWallet;
  to: string;
  data: string;
  /** Gas for the leg alone; estimated (×1.3) when omitted. */
  gasLimit?: bigint;
  heartbeatAddress?: string;
}): Promise<BscReceipt> => {
  const { wallet, to, data } = params;
  const heartbeat = params.heartbeatAddress ?? BUNDLED_HEARTBEAT.address;
  const eoa = wallet.address;

  // The gate primitive guards itself, not only its callers: with no (or a
  // zero) heartbeat address the batch's first call would hit a codeless
  // address, which the delegate counts as a pass — an UNGATED exit.
  if (!isUsableAddress(heartbeat)) throw new ConfioAliveError({ state: 'not_configured' });
  const gate = await readHeartbeat(heartbeat);
  if (gate.state !== 'open') throw new ConfioAliveError(gate);

  const [nonce, code, nonceWord, rawGasPrice] = await Promise.all([
    bscGetNonce(eoa),
    bscGetCode(eoa),
    bscGetStorageAt(eoa, BATCH_DELEGATE_NONCE_SLOT),
    bscGasPrice(),
  ]);
  const execNonce = BigInt(nonceWord && nonceWord !== '0x' ? nonceWord : 0);
  let gasPrice = rawGasPrice < 100_000_000n ? 100_000_000n : rawGasPrice;
  gasPrice = (gasPrice * 12n) / 10n;

  const legGas = params.gasLimit ?? ((await bscEstimateGas(eoa, to, data)) * 13n) / 10n;
  const calldata = encodeExecuteCalldata(gatedCalls(heartbeat, { to, data }), 0n, 0n, ZERO32, '0x');
  const delegated = isDelegatedToTrusted(code);

  const signed = delegated
    ? signLegacyTransaction(
        {
          nonce,
          gasPriceWei: gasPrice,
          gasLimit: legGas + GATE_GAS_OVERHEAD,
          to: eoa,
          valueWei: 0n,
          data: calldata,
          chainId: BSC_NETWORK.chainId,
        },
        wallet.privKeyHex,
      )
    : signSetCodeTransaction(
        {
          nonce,
          maxPriorityFeePerGas: gasPrice,
          maxFeePerGas: gasPrice,
          gasLimit: legGas + GATE_GAS_OVERHEAD + AUTH_GAS_OVERHEAD,
          to: eoa,
          valueWei: 0n,
          data: calldata,
          // The sender's nonce is bumped before authorizations are processed.
          authorizationList: [signSetCodeAuthorization(exitDelegate(), nonce + 1n, wallet.privKeyHex)],
          chainId: BSC_NETWORK.chainId,
        },
        wallet.privKeyHex,
      );

  await bscSendRawTransaction(signed.rawTx);
  let receipt: BscReceipt;
  try {
    receipt = await bscWaitForReceipt(signed.txHash);
  } catch (e) {
    // A revert is definitive. If Confío beat in the meantime, say so — the
    // caller must stop, not fall back to another (equally gated) send.
    // An unreadable heartbeat is NOT "Confío is alive": keep the original
    // revert so the engine's fallback can still run (it is gated too).
    if (e instanceof BscRevertedError) {
      const status = await readHeartbeat(heartbeat).catch(() => null);
      if (status && (status.state === 'alive' || status.state === 'quiet')) {
        throw new ConfioAliveError(status);
      }
    }
    throw e;
  }

  const verdict = receiptExecutedBatch(receipt, eoa, execNonce);
  if (verdict === 'executed') return receipt;
  if (verdict === 'noop') {
    // Mined with status 1 but nothing ran (the authorization did not apply).
    // Definitive and nothing moved: the caller may retry.
    throw new BscRevertedError(signed.txHash);
  }
  // Mined but we cannot prove what ran: treat like an unconfirmed broadcast
  // so the caller reconciles instead of sending again.
  throw Object.assign(new Error(`bsc tx outcome unknown: ${signed.txHash}`), {
    broadcast: true,
    txHash: signed.txHash,
  });
};
