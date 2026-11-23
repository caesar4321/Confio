/** Display hint only: a Pix code that names its own amount (a dynamic charge,
 *  field 25, or a static code with field 54) is paid at that exact amount in
 *  reais. The server decides; this only picks which screen parts to show. */
export function pixChargeHint(raw: string): boolean {
  const fields = emvFields(raw.trim());
  if (!fields || fields['58'] !== 'BR') return false;
  if ('54' in fields) return true;
  return Object.entries(fields).some(([tag, value]) => {
    const n = Number(tag);
    if (n < 26 || n > 51) return false;
    const inner = emvFields(value);
    return Boolean(inner && (inner['00'] || '').toLowerCase() === 'br.gov.bcb.pix' && inner['25']);
  });
}

/** Display hint only: a Colombian Bre-B QR (pesos) or an Argentine QR
 *  (pesos) with its own amount (field 54) is paid at exactly that amount.
 *  The server decides. */
export function fixedQrAmountHint(raw: string): boolean {
  const fields = emvFields(raw.trim());
  if (!fields || !fields['54']) return false;
  return (fields['58'] === 'CO' && fields['53'] === '170') || (fields['58'] === 'AR' && fields['53'] === '032');
}

function emvFields(value: string): Record<string, string> | null {
  if (value.length > 4096) return null;
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
  return fields;
}

/** Routing hint only. Server validation and eligibility remain authoritative. */
export function localPaymentQrRoute(raw: string): {methodId: string; country: string} | null {
  const value = raw.trim();
  // Bolivian bank QR strings arrive encrypted as ciphertext|hex.
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
