// Which chain does this address belong to?
//
// Sending to an address from the wrong chain destroys the funds, and the two
// formats are trivially distinguishable, so the app should always be able to
// say "that's an Algorand address, you're sending on BNB Smart Chain" instead
// of a generic "invalid format". One table, used by the QR scanner and by
// every paste/typed-entry validator.

export type AddressNetwork = 'algorand' | 'bsc';

export const NETWORK_LABEL: Record<AddressNetwork, string> = {
  algorand: 'Algorand',
  bsc: 'BNB Smart Chain',
};

// Anchored: the whole string must BE the address (paste / typed entry).
const EXACT: Record<AddressNetwork, RegExp> = {
  algorand: /^[A-Z2-7]{58}$/,
  bsc: /^0x[0-9a-fA-F]{40}$/,
};

// Unanchored: the address is embedded (QR payloads — algorand://ADDR,
// ethereum:0x…@56). The alphabets cannot collide, since base32 has no
// '0' or 'x'.
const EMBEDDED: Record<AddressNetwork, RegExp> = {
  algorand: /[A-Z2-7]{58}/,
  bsc: /0x[0-9a-fA-F]{40}/,
};

/**
 * Algorand is base32 and conventionally upper-case, so normalising is safe.
 * An EVM address must NOT be upper-cased — it is hex, and the mixed case
 * carries the EIP-55 checksum.
 */
const normalize = (value: string, network: AddressNetwork): string =>
  network === 'algorand' ? value.toUpperCase() : value;

/** Extract an address for `network` from a scanned payload, or null. */
export const findAddress = (
  value: string, network: AddressNetwork,
): string | null => {
  const match = normalize(String(value ?? ''), network).match(EMBEDDED[network]);
  return match ? match[0] : null;
};

/** True when the whole trimmed string is a valid address for `network`. */
export const isAddressForNetwork = (
  value: string | null | undefined, network: AddressNetwork,
): boolean => {
  const raw = String(value ?? '').trim();
  if (!raw) return false;
  return EXACT[network].test(normalize(raw, network));
};

/**
 * Which chain a pasted/typed address belongs to, or null if it isn't a
 * well-formed address for either.
 */
export const detectAddressNetwork = (
  value: string | null | undefined,
): AddressNetwork | null => {
  if (isAddressForNetwork(value, 'bsc')) return 'bsc';
  if (isAddressForNetwork(value, 'algorand')) return 'algorand';
  return null;
};

/**
 * The message for "well-formed, but for the other chain" — the failure most
 * likely to cost someone their money, so it never gets folded into a generic
 * format error. Returns null when `value` is not the other chain's address,
 * leaving the caller's own format message to apply.
 */
export const wrongNetworkMessage = (
  value: string | null | undefined, expected: AddressNetwork,
): string | null => {
  const actual = detectAddressNetwork(value);
  if (!actual || actual === expected) return null;
  return (
    `Esa es una dirección de ${NETWORK_LABEL[actual]}. `
    + `Para este envío necesitas una de ${NETWORK_LABEL[expected]}.`
  );
};
