// Cuenta inteligente visual tokens. Everything maps to the app's theme
// (config/theme.ts) except the two colors that belong to the product's own
// mark (components/svg/CuentaInteligenteMark): the deep emerald disc and the
// lamp yellow. The account's field and its primary actions use the deep
// emerald, so the paid account reads as a distinct place inside the same app
// (Inicio is the bright mint field). The yellow appears only in the mark.
//
// Never here: violet, sparkles or padlocks (they read as a locked AI feature),
// and red/green for balances (overview surfaces stay calm).
import { colors } from '../../config/theme';

export const SA = {
  deep: '#065F46', // the mark's disc; white text on it is 7.7:1
  deepPressed: colors.primaryDeep, // '#064E3B'
  onDeep: colors.white,
  onDeepMuted: colors.primaryMuted, // '#A7F3D0', 6.2:1 on deep
  page: colors.surface,
  card: colors.white,
  text: colors.text.primary,
  muted: colors.text.secondary,
  faint: colors.text.light,
  line: colors.border,
  mint: colors.primarySoft,
  mintLine: colors.primaryMuted,
  mintText: colors.successText, // '#047857', 5.5:1 on white
  noticeBg: colors.warning.background,
  noticeLine: colors.warning.border,
  noticeText: colors.warning.text,
  errorText: colors.error.text,
} as const;

/** The soft card shadow used by the offer and wallet cards. */
export const cardShadow = {
  shadowColor: colors.primaryDeep,
  shadowOffset: { width: 0, height: 4 },
  shadowOpacity: 0.06,
  shadowRadius: 12,
  elevation: 2,
} as const;

/** Minimum touch target (pt). */
export const HIT = 44;
