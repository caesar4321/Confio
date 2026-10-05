// Public BSC RPC endpoints for Salida de emergencia
// (docs/plans/salida-de-emergencia-design.md). The exit must work exactly
// when Confío is gone, so it never uses Confío's relay: these endpoints are
// public, keyless and Confío-independent by design — the sanctioned
// exception to the "no direct chain clients in the app" policy.
//
// Breadth is the whole defense here (mirrors the server's RPC-pool lesson,
// 2026-07-31: the dataseed family silently dropped eth_getLogs for weeks —
// a single-family pool is a single point of failure). The exit only needs
// basic methods (blocks, balances, nonce, gasPrice, eth_call, storage,
// sendRawTransaction), which every endpoint below serves keylessly; the
// NodeReal URL is the public one from the official BNB Chain docs. Ordered
// by observed reliability; every consumer iterates in order with failover.
const BSC_RPCS = [
  'https://bsc-mainnet.nodereal.io/v1/64a9df0874fb4a93b9d0a3849de012d3',
  'https://bsc-dataseed.bnbchain.org',
  'https://bsc-rpc.publicnode.com',
  'https://bsc-dataseed1.defibit.io',
  'https://bsc-dataseed1.ninicoin.io',
  'https://bsc.drpc.org',
  'https://1rpc.io/bnb',
];

export const CHAIN_ENDPOINTS = { BSC_RPCS };
