// The outage-status Worker (workers/outage-status). Both values come from
// its deployment: the URL(s) ending in /v1/status, and the public key
// printed by `npm run keygen` there. Until both are set the Worker is
// ignored and the emergency exit keeps the local 72h outage rule.
//
// Shipped in the bundle on purpose: the exit must be able to check the
// Worker when Confío's servers are gone.
export const OUTAGE_STATUS_URLS: readonly string[] = [
  'https://confio-outage-status.julianmoon.workers.dev/v1/status',
];
export const OUTAGE_STATUS_PUBLIC_KEY_HEX = '93097fe839a948ae71819eaadcaffb5fdeb55dbdce52c7ea34aa75f725a7fbfe';
