// EIP-7702 sponsored execution — the client half of cusd_plus/sponsor_7702.
//
// The user's EOA never needs BNB: the client signs an EIP-712 intent over
// the exact call batch (plus, on first use, the one-time authorization
// designating ConfioBatchDelegate at its own address) and the SERVER
// broadcasts a sponsor-paid transaction to the user's EOA. The delegate
// re-verifies the user's signature on-chain, so the sponsor can only
// execute what was signed. Keys never leave the device; same address,
// same balances, normal self-signed txs keep working.
//
// Failure mode handled here: if the authorization's account nonce raced
// (some other tx from this EOA landed between signing and mining), the
// delegation silently doesn't apply and the sponsored tx mines as a no-op.
// Detection = the delegate's intent nonce didn't advance; recovery = one
// retry with freshly read nonces.

import {
  BatchCall,
  DerivedEvmWallet,
  bscEthCall,
  bscGetCode,
  bscGetNonce,
  bscWaitForReceipt,
  hashBatchIntent,
  selector,
  signIntentDigest,
  signSetCodeAuthorization,
  BscReceipt,
} from './evmWallet';

const DELEGATION_PREFIX = '0xef0100';

/** Server-served 7702 config (cusdPlusConvertParams). */
export interface Sponsored7702Params {
  enabled: boolean;
  delegateAddress: string | null;
}

export const fetchSponsored7702Params = async (): Promise<Sponsored7702Params> => {
  const { gql } = await import('@apollo/client');
  const { apolloClient } = await import('../apollo/client');
  const { data } = await apolloClient.query({
    query: gql`
      query Sponsored7702Params {
        cusdPlusConvertParams {
          sponsored7702Enabled
          batchDelegateAddress
        }
      }
    `,
    fetchPolicy: 'cache-first',
  });
  const p = data?.cusdPlusConvertParams;
  return {
    enabled: Boolean(p?.sponsored7702Enabled && p?.batchDelegateAddress),
    delegateAddress: p?.batchDelegateAddress || null,
  };
};

export const delegateNonce = async (eoa: string): Promise<bigint> => {
  // nonces() on the EOA itself; a codeless (not yet delegated) EOA returns
  // empty data — that IS nonce 0.
  const res = await bscEthCall(eoa, selector('nonces()'));
  return res && res !== '0x' ? BigInt(res) : 0n;
};

export const isDelegatedTo = async (eoa: string, delegate: string): Promise<boolean> => {
  const code = ((await bscGetCode(eoa)) || '0x').toLowerCase();
  return code === DELEGATION_PREFIX + delegate.toLowerCase().slice(2);
};

/**
 * Execute `calls` as the user's EOA via a sponsor-paid transaction.
 * Waits for the receipt AND proves execution actually happened (delegate
 * nonce advanced); retries once with fresh nonces on the races the server
 * reports (authorization_required / stale_auth_nonce) or a silent no-op.
 * Returns the mined receipt. Throws on policy rejection or exhaustion.
 */
export const executeSponsoredBatch = async (params: {
  wallet: DerivedEvmWallet;
  calls: BatchCall[];
  delegateAddress: string;
}): Promise<BscReceipt> => {
  const { sponsorBscBatch } = await import('./bscServerRpc');
  const { wallet, calls, delegateAddress } = params;
  const from = wallet.address;

  let lastError = 'unknown';
  for (let attempt = 0; attempt < 2; attempt++) {
    const execNonce = await delegateNonce(from);
    const deadline = BigInt(Math.floor(Date.now() / 1000) + 600);

    const digest = hashBatchIntent(calls, execNonce, deadline, from);
    const intentSignature = signIntentDigest(digest, wallet.privKeyHex);

    // First use (or re-delegation): the authorization tuple rides along.
    // The server re-checks delegation state authoritatively either way.
    let authorization;
    if (!(await isDelegatedTo(from, delegateAddress))) {
      const accountNonce = await bscGetNonce(from);
      authorization = signSetCodeAuthorization(delegateAddress, accountNonce, wallet.privKeyHex);
    }

    const res = await sponsorBscBatch({
      calls: calls.map((c) => ({ to: c.to, valueWei: c.valueWei.toString(), data: c.data })),
      nonce: execNonce.toString(),
      deadline: deadline.toString(),
      intentSignature,
      authorization,
    });

    if (!res.success) {
      lastError = res.error || 'sponsor rejected';
      // Nonce races are retryable with fresh reads; policy errors are not.
      if (res.authorizationRequired || res.error === 'stale_auth_nonce') continue;
      throw new Error(`sponsored batch rejected: ${lastError}`);
    }

    const receipt = await bscWaitForReceipt(res.txHash as string);
    if ((await delegateNonce(from)) > execNonce) return receipt; // executed for real
    // Mined but the delegate nonce didn't move: the delegation never
    // applied (silent 7702 no-op). Fresh reads, one more shot.
    lastError = 'delegation_not_applied';
  }
  throw new Error(`sponsored batch failed: ${lastError}`);
};
