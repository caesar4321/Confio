/** Routing hint only. Server validation and eligibility remain authoritative. */
export function localPaymentQrRoute(raw: string): {methodId: string; country: string} | null {
  const value = raw.trim();
  // Stereum documents encrypted Bolivia bank QR strings as ciphertext|hex.
  // This is only a routing hint; the server decoder establishes validity.
  if (value.length <= 32768 && /^[A-Za-z0-9+/_=-]{32,}\|[a-fA-F0-9]{16}$/.test(value)) {
    return {methodId: 'bo_qr', country: 'BO'};
  }
  if (!value.startsWith('000201') || value.length > 4096) return null;
  const fields: Record<string, string> = {};
  let offset = 0;
  while (offset < value.length) {
    const tag = value.slice(offset, offset + 2);
    const length = value.slice(offset + 2, offset + 4);
    if (!/^\d{2}$/.test(tag) || !/^\d{2}$/.test(length) || tag in fields) return null;
    const end = offset + 4 + Number(length);
    if (end > value.length) return null;
    fields[tag] = value.slice(offset + 4, end);
    offset = end;
  }
  const methodId = ({AR: 'ar_qr', BR: 'br_qr', CO: 'co_qr', PE: 'pe_qr', BO: 'bo_qr'} as Record<string, string>)[fields['58']];
  return methodId ? {methodId, country: fields['58']} : null;
}
