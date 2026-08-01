/**
 * The server hands the app phone numbers in its canonical key form,
 * `"callingcode:localdigits"` (e.g. `"57:3132587634"`) — that is what the
 * `phoneKey` GraphQL field and the transaction-list `fromPhone`/`toPhone`
 * fields carry. It is a storage key, not a phone number: showing it raw reads
 * as "57:3132587634", and passing it into a send makes the server look up a
 * number nobody has.
 *
 * These helpers turn a key back into the shapes the rest of the app expects.
 * Anything that is already E.164 or bare digits passes through unharmed.
 */

export type ParsedPhoneKey = {
  /** Numeric calling code without '+', e.g. "57". Empty when unknown. */
  callingCode: string;
  /** Local digits without the calling code, e.g. "3132587634". */
  localDigits: string;
};

/** Split a canonical key. Returns null for values that aren't key-shaped. */
export const parsePhoneKey = (value?: string | null): ParsedPhoneKey | null => {
  const raw = (value || '').trim();
  if (!raw || !raw.includes(':')) return null;
  const [codePart, ...rest] = raw.split(':');
  const callingCode = codePart.replace(/\D/g, '');
  const localDigits = rest.join('').replace(/\D/g, '');
  if (!callingCode || !localDigits) return null;
  return { callingCode, localDigits };
};

/**
 * Dialable form for sends, invites and display: `"57:3132587634"` →
 * `"+573132587634"`. Values that already start with '+' keep their digits;
 * bare digits are returned unchanged (we can't invent a calling code they
 * didn't carry).
 *
 * Not strictly E.164 for every country: the key stores the number AFTER
 * `canonicalize_phone_digits`, which drops Argentina's optional mobile `9`,
 * and nothing here can put it back. That is safe for routing — the server
 * canonicalizes `+54 9 …` and `+54 …` to the same key — but it means the
 * string is a lookup identifier first and a dialable number second.
 */
export const phoneKeyToE164 = (value?: string | null): string => {
  const raw = (value || '').trim();
  if (!raw) return '';
  const parsed = parsePhoneKey(raw);
  if (parsed) return `+${parsed.callingCode}${parsed.localDigits}`;
  const digits = raw.replace(/\D/g, '');
  if (!digits) return '';
  return raw.startsWith('+') ? `+${digits}` : digits;
};
