/** '🇧🇴' → 'BO'. Lets data that still carries an emoji (the server's
 * `flagEmoji`, the country tuples) draw the bundled image. '' for anything else. */
export const isoFromFlagEmoji = (emoji?: string | null): string => {
  const points = Array.from(String(emoji || '').trim()).map(ch => ch.codePointAt(0) || 0);
  if (points.length !== 2 || points.some(p => p < 0x1f1e6 || p > 0x1f1ff)) return '';
  return String.fromCharCode(...points.map(p => p - 0x1f1e6 + 65));
};

/** 'BO' → '🇧🇴'; '' unless given two letters. */
export const emojiFromIso2 = (iso: string): string =>
  /^[A-Z]{2}$/.test(iso) ? String.fromCodePoint(...Array.from(iso).map(ch => 0x1f1e6 + ch.charCodeAt(0) - 65)) : '';
