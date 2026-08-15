const BSC_ADDRESS = /^0x[0-9a-fA-F]{40}$/;

/** Opens an address's BNB Smart Chain token holdings without the multichain tab. */
export const bscscanTokenHoldingsUrl = (
  address?: string | null,
): string | null => {
  const normalized = String(address ?? '').trim();
  if (!BSC_ADDRESS.test(normalized)) return null;
  return `https://bscscan.com/tokenholdings?a=${normalized}`;
};
