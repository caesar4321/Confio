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
      const { data } = await apolloClient.mutate({
        mutation: SUBMIT_BSC_TX,
        variables: { rawTx },
      });
      const res = data?.submitBscTransaction;
      if (!res?.success) throw new Error(`bsc relay submit: ${res?.error || 'failed'}`);
      return res.txHash as string;
    },
  });
};
