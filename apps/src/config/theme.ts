export const lightColors = {
  primary: '#34D399', // emerald-400
  primaryText: '#34D399',
  primaryLight: '#D1FAE5', // emerald-100
  primaryDark: '#10B981', // emerald-500
  secondary: '#8B5CF6', // violet-500
  secondaryDark: '#7C3AED', // violet-600 — gradient partner of secondary (mirrors primary/primaryDark)
  secondaryText: '#8B5CF6',
  accent: '#3B82F6', // blue-500
  accentText: '#3B82F6',
  neutral: '#F9FAFB', // gray-50
  neutralDark: '#F3F4F6', // gray-100
  dark: '#111827', // gray-900
  success: '#10B981', // emerald-500
  background: '#FFFFFF',
  surface: '#F9FAFB',
  text: {
    primary: '#1F2937', // gray-800
    secondary: '#6B7280', // gray-500
    light: '#9CA3AF',
  },
  textFlat: '#111827',
  textSecondary: '#6B7280',
  warning: {
    background: '#FEF3C7', // yellow-50
    border: '#FDE68A', // yellow-200
    text: '#92400E', // yellow-800
    icon: '#D97706', // yellow-600
  },
  error: {
    background: '#FEE2E2', // red-100
    border: '#FECACA', // red-200
    text: '#991B1B', // red-800
    icon: '#DC2626', // red-600
  },
  // AuthScreen aliases
  confioGreen: '#34D399',
  white: '#FFFFFF',
  accentPurple: '#8B5CF6',
  darkGray: '#1F2937',
  lightGray: '#F3F4F6',
  // Semantic aliases
  border: '#E5E7EB', // gray-200
  borderLight: '#F3F4F6', // gray-100
  muted: '#9CA3AF', // gray-400
  // Missing aliases
  accentSoft: '#BFDBFE',
  bg: '#F9FAFB',
  danger: '#EF4444',
  dangerLight: '#FEE2E2',
  errorLight: '#FEE2E2',
  gray: '#9CA3AF',
  gray600: '#4B5563',
  grayText: '#6B7280',
  info: '#3B82F6',
  infoLight: '#DBEAFE',
  light: '#F3F4F6',
  mint: '#D1FAE5',
  offRampIcon: '#F59E0B',
  offRampLight: '#FEF3C7',
  primaryDeep: '#064E3B',
  primaryMuted: '#A7F3D0',
  providerColors: {
    moonpay: '#7D00FF',
    mercuryo: '#1ED760',
    transak: '#3258F6',
    ramp: '#05B169'
  },
  successLight: '#D1FAE5',
  successText: '#047857',
  surfaceMuted: '#F3F4F6',
  textTertiary: '#9CA3AF',
  violet: '#8B5CF6',
  violetLight: '#EDE9FE',
  warningLight: '#FEF3C7',
  primarySoft: '#ECFDF5', // emerald-50
  borderMedium: '#D1D5DB', // gray-300
  shadowBase: '#0F172A', // slate-900
  gray700: '#374151', // gray-700
};

// Design tokens — use these instead of raw numbers in new/edited styles.
// Spacing follows a 4pt grid; radius and type sizes collapse the ad-hoc
// values found across screens into one scale.
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  pill: 999,
} as const;

export const fontSize = {
  caption: 12,
  small: 14,
  body: 16,
  subtitle: 18,
  title: 20,
  heading: 24,
  display: 32,
} as const;

export const fontWeight = {
  regular: '400',
  medium: '500',
  semibold: '600',
  bold: '700',
} as const;

// Legacy export for backwards compatibility
export const colors = lightColors;