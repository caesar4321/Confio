// App-wide text primitives. Every Text/TextInput in the app renders through
// these so the whole UI uses Instrument Sans (DESIGN.md typography).
//
// Why a wrapper instead of a global default: React 19 removed defaultProps
// on function components, so `Text.defaultProps` can no longer set a font,
// and Android ignores `fontWeight` for custom fonts unless each weight is a
// separately named family. So we resolve the weight to its static file here
// (InstrumentSans-Regular/Medium/SemiBold/Bold — file name == PostScript
// name, which is what both platforms look up) and drop fontWeight so neither
// platform synthesizes a fake bold on top.
//
// Explicit fontFamily (e.g. 'monospace' for addresses) is left untouched.
//
// The value + type exports share names on purpose: call sites keep writing
// `<Text>` / `useRef<TextInput>(null)` unchanged after the import swap.
// Direct react-native Text/TextInput imports are banned by ESLint
// (@typescript-eslint/no-restricted-imports in .eslintrc.js); this file is the one exception.
import React, { forwardRef } from 'react';
import {
  StyleSheet,
  // eslint-disable-next-line @typescript-eslint/no-restricted-imports
  Text as RNText,
  // eslint-disable-next-line @typescript-eslint/no-restricted-imports
  TextInput as RNTextInput,
} from 'react-native';
import type { StyleProp, TextInputProps, TextProps, TextStyle } from 'react-native';
import { fontFamily } from '../../config/theme';

type Weight = NonNullable<TextStyle['fontWeight']>;

const FAMILY_BY_WEIGHT: Record<string, string> = {
  '100': fontFamily.regular,
  '200': fontFamily.regular,
  '300': fontFamily.regular,
  '400': fontFamily.regular,
  normal: fontFamily.regular,
  regular: fontFamily.regular,
  '500': fontFamily.medium,
  medium: fontFamily.medium,
  '600': fontFamily.semibold,
  semibold: fontFamily.semibold,
  '700': fontFamily.bold,
  bold: fontFamily.bold,
  // Instrument Sans stops at 700; heavier requests render as Bold rather
  // than a synthesized weight.
  '800': fontFamily.bold,
  '900': fontFamily.bold,
  heavy: fontFamily.bold,
  black: fontFamily.bold,
  ultralight: fontFamily.regular,
  thin: fontFamily.regular,
  light: fontFamily.regular,
  condensed: fontFamily.regular,
  condensedBold: fontFamily.bold,
};

export function familyForWeight(weight?: Weight | number): string {
  if (weight === undefined || weight === null) return fontFamily.regular;
  return FAMILY_BY_WEIGHT[String(weight)] ?? fontFamily.regular;
}

export function resolveFontStyle(style: StyleProp<TextStyle>): TextStyle {
  const flat = StyleSheet.flatten(style) || {};
  if (flat.fontFamily) return flat;
  const { fontWeight, ...rest } = flat;
  return { ...rest, fontFamily: familyForWeight(fontWeight) };
}

export const Text = forwardRef<RNText, TextProps>(function Text({ style, ...props }, ref) {
  return <RNText ref={ref} {...props} style={resolveFontStyle(style)} />;
});
export type Text = RNText;

export const TextInput = forwardRef<RNTextInput, TextInputProps>(function TextInput(
  { style, ...props },
  ref,
) {
  return <RNTextInput ref={ref} {...props} style={resolveFontStyle(style)} />;
});
export type TextInput = RNTextInput;
