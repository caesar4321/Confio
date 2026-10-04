// App-wide text primitives. Every Text/TextInput in the app renders through
// these so the whole UI uses Instrument Sans (DESIGN.md typography).
//
// Why a wrapper instead of a global default: React 19 removed defaultProps
// on function components, so `Text.defaultProps` can no longer set a font,
// and Android ignores `fontWeight`/`fontStyle` for custom fonts unless each
// weight and slant is a separately named file. So we resolve weight + style
// to the static file here (InstrumentSans-Regular … -BoldItalic; file name ==
// PostScript name, which is what both platforms look up) and drop
// fontWeight/fontStyle so neither platform synthesizes a fake bold or slant.
//
// Nested text: React Native passes typography from a parent <Text> to nested
// children. Because every Text sets an explicit family, a child must resolve
// its family from the parent's weight/style plus its own overrides, or a
// plain child inside a bold heading would snap back to Regular. The parent's
// resolved typography travels down via context.
//
// Explicit fontFamily (e.g. 'monospace' for addresses) is left untouched, and
// nested children without their own family keep inheriting it.
//
// The value + type exports share names on purpose: call sites keep writing
// `<Text>` / `useRef<TextInput>(null)` unchanged after the import swap.
// Direct react-native Text/TextInput imports are banned by ESLint
// (@typescript-eslint/no-restricted-imports in .eslintrc.js); this file is the one exception.
import React, { createContext, forwardRef, useContext } from 'react';
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
type Slot = 'regular' | 'medium' | 'semibold' | 'bold';

const SLOT_BY_WEIGHT: Record<string, Slot> = {
  '100': 'regular',
  '200': 'regular',
  '300': 'regular',
  '400': 'regular',
  normal: 'regular',
  regular: 'regular',
  ultralight: 'regular',
  thin: 'regular',
  light: 'regular',
  condensed: 'regular',
  '500': 'medium',
  medium: 'medium',
  '600': 'semibold',
  semibold: 'semibold',
  '700': 'bold',
  bold: 'bold',
  condensedBold: 'bold',
  // Instrument Sans stops at 700; heavier requests render as Bold rather
  // than a synthesized weight.
  '800': 'bold',
  '900': 'bold',
  heavy: 'bold',
  black: 'bold',
};

const ITALIC_FAMILY: Record<Slot, string> = {
  regular: fontFamily.italic,
  medium: fontFamily.mediumItalic,
  semibold: fontFamily.semiboldItalic,
  bold: fontFamily.boldItalic,
};

function slotForWeight(weight?: Weight | number | null): Slot {
  if (weight === undefined || weight === null) return 'regular';
  return SLOT_BY_WEIGHT[String(weight)] ?? 'regular';
}

export function familyForWeight(weight?: Weight | number | null, italic = false): string {
  const slot = slotForWeight(weight);
  return italic ? ITALIC_FAMILY[slot] : fontFamily[slot];
}

// Typography a parent Text hands to nested Text.
type Inherited = {
  weight?: Weight | number;
  italic: boolean;
  explicitFamily?: string;
};
const ROOT: Inherited = { italic: false };
const TextTypography = createContext<Inherited | null>(null);

const NUMERIC_BY_SLOT: Record<Slot, TextStyle['fontWeight']> = {
  regular: '400',
  medium: '500',
  semibold: '600',
  bold: '700',
};

// Android only understands numeric weights and 'normal'/'bold'; named
// aliases ('heavy', 'black', 'condensedBold', …) parse as unset there.
function nativeWeight(weight: Weight | number): TextStyle['fontWeight'] {
  const w = String(weight);
  if (/^[1-9]00$/.test(w) || w === 'normal' || w === 'bold') return w as TextStyle['fontWeight'];
  return NUMERIC_BY_SLOT[slotForWeight(weight)];
}

// Every ancestor that resolved to an Instrument Sans file had its native
// fontWeight/fontStyle stripped, and Android omits untold traits rather than
// inheriting them. So any nested Text that is NOT itself mapped to an
// Instrument Sans file restates the inherited weight/slant explicitly, at
// every depth. Local values always win.
function withInheritedTraits(
  flat: TextStyle,
  parent: Inherited | null,
  weight: Weight | number | undefined,
  italic: boolean,
): TextStyle {
  if (!parent) return flat;
  const own: TextStyle = { ...flat };
  if (flat.fontWeight == null && weight != null) own.fontWeight = nativeWeight(weight);
  if (!flat.fontStyle && italic) own.fontStyle = 'italic';
  return own;
}

export function resolveFontStyle(
  style: StyleProp<TextStyle>,
  parent: Inherited | null = null,
): { style: TextStyle; typography: Inherited } {
  const flat: TextStyle = StyleSheet.flatten(style) || {};
  const base = parent ?? ROOT;
  if (flat.fontFamily) {
    const weight = flat.fontWeight ?? base.weight;
    const italic = flat.fontStyle ? flat.fontStyle === 'italic' : base.italic;
    return {
      style: withInheritedTraits(flat, parent, weight, italic),
      typography: { weight, italic, explicitFamily: flat.fontFamily },
    };
  }
  if (base.explicitFamily) {
    // Inside e.g. a monospace parent: let React Native inherit that family
    // (and apply this child's own weight/style to it) instead of replacing it.
    const weight = flat.fontWeight ?? base.weight;
    const italic = flat.fontStyle ? flat.fontStyle === 'italic' : base.italic;
    return {
      style: withInheritedTraits(flat, parent, weight, italic),
      typography: { weight, italic, explicitFamily: base.explicitFamily },
    };
  }
  const weight = flat.fontWeight ?? base.weight;
  const italic = flat.fontStyle ? flat.fontStyle === 'italic' : base.italic;
  const { fontWeight: _w, fontStyle: _s, ...rest } = flat;
  return {
    style: { ...rest, fontFamily: familyForWeight(weight, italic) },
    typography: { weight, italic },
  };
}

export const Text = forwardRef<RNText, TextProps>(function Text({ style, ...props }, ref) {
  const parent = useContext(TextTypography);
  const resolved = resolveFontStyle(style, parent);
  return (
    <TextTypography.Provider value={resolved.typography}>
      <RNText ref={ref} {...props} style={resolved.style} />
    </TextTypography.Provider>
  );
});
export type Text = RNText;

export const TextInput = forwardRef<RNTextInput, TextInputProps>(function TextInput(
  { style, ...props },
  ref,
) {
  return <RNTextInput ref={ref} {...props} style={resolveFontStyle(style).style} />;
});
export type TextInput = RNTextInput;
