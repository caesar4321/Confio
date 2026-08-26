// BSC server-relay transport — cUSD parity for the savings chain.
//
// The client SIGNS locally (keys never leave the device) but every RPC —
// reads and signed-tx submission alike — goes through our Django server
// (bscRpc query / submitBscTransaction mutation), exactly like Algorand's
// submitSponsoredGroup. User IPs never touch public BSC nodes, the server
// observes submissions the moment they happen, and destination allowlisting
// on the server means the relay can't be abused as an open proxy.
//
// installBscServerTransport() is idempotent; savings flows call it before
// their first chain interaction. Scripts/tests never import this module and
// keep evmWallet's direct-fetch default.

import { gql } from '@apollo/client';
import { setBscTransport } from './evmWallet';

const BSC_RPC_QUERY = gql`
  query BscRpc($method: String!, $params: String!) {
    bscRpc(method: $method, params: $params) {
      result
      error
    }
  }
`;

const SUBMIT_BSC_TX = gql`
  mutation SubmitBscTransaction($rawTx: String!) {
    submitBscTransaction(rawTx: $rawTx) {
      success
      txHash
      error
    }
  }
`;

const SPONSOR_BSC_BATCH = gql`
  mutation SponsorBscBatch(
    $calls: [BscCallInput!]!
    $nonce: String!
    $deadline: String!
    $intentSignature: String!
    $authorization: BscAuthorizationInput
    $requestId: String
  ) {
    sponsorBscBatch(
      calls: $calls
      nonce: $nonce
      deadline: $deadline
      intentSignature: $intentSignature
      authorization: $authorization
      requestId: $requestId
    ) {
      success
      txHash
      authorizationRequired
      error
      execution
    }
  }
`;

export interface SponsorBatchResult {
  success: boolean;
  txHash?: string;
  authorizationRequired?: boolean;
  error?: string;
  /** What the sponsor saw on-chain before answering: 'executed' |
   *  'reverted' | 'noop'; absent/null = it didn't observe one in time and
   *  the caller should poll for the receipt itself. */
  execution?: string | null;
}

/** Submit a 7702 sponsored batch (sponsor pays gas; server validates the
 * user-signed intent + optional authorization and broadcasts). Returns the
 * server's verdict verbatim — callers handle authorizationRequired retries. */
export const sponsorBscBatch = async (variables: {
  calls: Array<{ to: string; valueWei: string; data: string }>;
  nonce: string;
  deadline: string;
  intentSignature: string;
  requestId?: string;
  authorization?: {
    chainId: number;
    address: string;
    nonce: string;
    yParity: number;
    r: string;
    s: string;
  };
}): Promise<SponsorBatchResult> => {
  const { apolloClient } = await import('../apollo/client');
  try {
    const { data } = await apolloClient.mutate({
      mutation: SPONSOR_BSC_BATCH,
      variables,
    });
    return (data?.sponsorBscBatch || { success: false, error: 'no response' }) as SponsorBatchResult;
  } catch (e) {
    // The server VALIDATES, BROADCASTS, and only then answers. A transport
    // failure in between means the batch may already be on the network — we
    // simply never saw the verdict. Reporting that as a plain failure is
    // what let a caller retry and pay an already-funded provider order a
    // second time (audit 2026-08-03 [P1] #2).
    //
    // Failures we can PROVE happened before the broadcast stay ordinary
    // errors, so an offline phone or an expired session can retry cleanly.
    if (isDefinitivelyUnsent(e)) throw e;
    throw new BscSubmitOutcomeUnknownError(e);
  }
};

/** A money-moving mutation whose verdict never came back. Carries
 *  `broadcast` so isOutcomeUnknown() treats it like a receipt timeout. */
export class BscSubmitOutcomeUnknownError extends Error {
  readonly broadcast = true;
  readonly cause?: unknown;
  constructor(cause?: unknown) {
    super('bsc tx timeout: sponsored batch verdict unknown');
    this.name = 'BscSubmitOutcomeUnknownError';
    this.cause = cause;
  }
}

/**
 * Did this failure DEFINITIVELY happen before anything could be broadcast?
 *
 * The default answer is NO. Unknown is the safe verdict for money: the cost
 * of a wrong "unknown" is one confusing message, the cost of a wrong
 * "definitely failed" is paying a provider twice.
 *
 * An earlier version accepted `Network request failed` / `Failed to fetch`
 * as proof the request stayed on the device. It is not — React Native
 * reports the same string when a connection drops AFTER the request was
 * fully uploaded, i.e. exactly when the server may already have broadcast
 * (round 3 [P1] #1). Only shapes that prove the connection never carried a
 * request qualify now.
 */
const isDefinitivelyUnsent = (e: any): boolean => {
  // The server parsed, validated and REPLIED with structured errors. Our
  // money-moving mutations report business failures as `success: false`, and
  // post-broadcast exceptions are converted to an unknown verdict
  // server-side, so a GraphQL error means execution never reached a
  // broadcast. (Narrow, and deliberately the ONLY response-based case.)
  if (Array.isArray(e?.graphQLErrors) && e.graphQLErrors.length > 0) return true;

  const net = e?.networkError;
  if (!net) return false;

  // The gateway rejected us before any resolver ran.
  if (net.statusCode === 401 || net.statusCode === 403) return true;

  // No response at all: only connection-establishment failures prove the
  // request was never carried. A generic transport error does NOT.
  if (net.statusCode || net.response) return false;
  const msg = String(net.message || '').toLowerCase();
  return /enotfound|econnrefused|dns|getaddrinfo|unable to resolve host/.test(msg);
};

let installed = false;

export const installBscServerTransport = (): void => {
  if (installed) return;
  installed = true;

  setBscTransport({
    read: async (method: string, params: unknown[]) => {
      const { apolloClient } = await import('../apollo/client');
      const { data } = await apolloClient.query({
        query: BSC_RPC_QUERY,
        variables: { method, params: JSON.stringify(params) },
        fetchPolicy: 'no-cache', // chain state must never come from cache
      });
      const res = data?.bscRpc;
      if (!res || res.error) throw new Error(`bsc relay: ${res?.error || 'no response'}`);
      return JSON.parse(res.result);
    },
    submit: async (rawTx: string) => {
      const { apolloClient } = await import('../apollo/client');
      let data;
      try {
        ({ data } = await apolloClient.mutate({
          mutation: SUBMIT_BSC_TX,
          variables: { rawTx },
        }));
      } catch (e) {
        // Same rule as the sponsored batch: the relay broadcasts before it
        // answers, so a lost response is outcome-unknown, not a failure. A
        // retry would sign a NEW tx at a fresh nonce and could spend twice.
        // Provably-unsent failures stay retryable.
        if (isDefinitivelyUnsent(e)) throw e;
        throw new BscSubmitOutcomeUnknownError(e);
      }
      const res = data?.submitBscTransaction;
      // A server-side REJECTION is definitive — nothing was broadcast.
      if (!res?.success) throw new Error(`bsc relay submit: ${res?.error || 'failed'}`);
      return res.txHash as string;
    },
  });
};
