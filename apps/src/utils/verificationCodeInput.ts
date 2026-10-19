export const VERIFICATION_CODE_LENGTH = 6;

/**
 * Apply what one code box received to the whole six-box code.
 *
 * A box receives more than one digit when the user pastes the code or iOS
 * autofills it from the SMS; those digits fill this box and the ones after
 * it. Typing over a filled box arrives as two digits (old + new) and only
 * replaces that box.
 *
 * Returns the new code and the box to focus next (null: leave focus alone).
 */
export function applyCodeInput(
  code: string[],
  index: number,
  value: string,
): { code: string[]; focusIndex: number | null } {
  let digits = value.replace(/\D/g, '');
  const next = [...code];
  const previous = code[index];

  if (!digits) {
    next[index] = '';
    return { code: next, focusIndex: null };
  }

  // Exactly six digits is the code itself, whether it replaced a selected
  // digit or landed in an empty box. Only a seventh digit means the box's old
  // digit came along ("3" + "834271"): drop it.
  if (previous && digits.length === VERIFICATION_CODE_LENGTH + 1) {
    if (digits.startsWith(previous)) digits = digits.slice(1);
    else if (digits.endsWith(previous)) digits = digits.slice(0, -1);
  }

  // Two digits in a filled box: the old one plus the one just typed.
  const typedOver = !!previous && digits.length === 2 && digits.includes(previous);
  if (digits.length === 1 || typedOver) {
    next[index] = typedOver
      ? (digits[0] === previous ? digits[1] : digits[0])
      : digits;
    return {
      code: next,
      focusIndex: index < VERIFICATION_CODE_LENGTH - 1 ? index + 1 : null,
    };
  }

  // A partial paste is spread as received. "3" + "42" and a selected "3"
  // replaced by "342" arrive identically, and in both the user means 3, 4, 2.

  // A whole code always lands from the first box, wherever it was pasted.
  const start = digits.length >= VERIFICATION_CODE_LENGTH ? 0 : index;
  const pasted = digits.slice(0, VERIFICATION_CODE_LENGTH - start);
  pasted.split('').forEach((digit, offset) => { next[start + offset] = digit; });
  const lastFilled = start + pasted.length - 1;
  return {
    code: next,
    focusIndex: Math.min(lastFilled + 1, VERIFICATION_CODE_LENGTH - 1),
  };
}
