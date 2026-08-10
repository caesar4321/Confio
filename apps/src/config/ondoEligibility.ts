// Client-side defense in depth for Ondo Global Markets visibility.
// Keep synchronized with cusd_plus/eligibility.py. The server remains
// authoritative and additionally checks Cloudflare's IP-country signal.
const ONDO_PROHIBITED = new Set([
  'US', 'CA', 'AF', 'BY', 'KP', 'CU', 'IR', 'LY', 'MM', 'RU', 'SY', 'SO',
  'SD', 'SS',
]);

const ONDO_QUALIFIED_ONLY = new Set([
  'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR',
  'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK',
  'SI', 'ES', 'SE', 'IS', 'LI', 'NO', 'BR', 'GB', 'CH', 'HK', 'SG', 'MY',
]);

export const isOndoPhoneCountryEligible = (country?: string | null): boolean => {
  const normalized = String(country || '').trim().toUpperCase();
  if (!normalized) return false;
  return !ONDO_PROHIBITED.has(normalized) && !ONDO_QUALIFIED_ONLY.has(normalized);
};
