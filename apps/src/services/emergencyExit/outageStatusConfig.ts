// The outage-status Worker (workers/outage-status). Both values come from
// its deployment: the URL(s) ending in /v1/status, and the public key
// printed by `npm run keygen` there. Until both are set the Worker is
// ignored and the emergency exit keeps the local 72h outage rule.
//
// Shipped in the bundle on purpose: the exit must be able to check the
// Worker when Confío's servers are gone.
export const OUTAGE_STATUS_URLS: readonly string[] = [];
export const OUTAGE_STATUS_PUBLIC_KEY_HEX = '';
