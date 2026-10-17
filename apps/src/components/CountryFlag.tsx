import React from 'react';
import { StyleProp, StyleSheet, TextStyle, View, ViewStyle } from 'react-native';
import { SvgXml } from 'react-native-svg';
import { Text } from './common/AppText';
import { toIso2 } from '../config/localRails';
import { FLAG_XML } from '../assets/flags/flagXml';
import { emojiFromIso2, isoFromFlagEmoji } from '../utils/flagIso';

export { isoFromFlagEmoji };

// Round flags bundled with the app (HatScripts/circle-flags, MIT — see
// assets/flags/LICENSE.md), so every phone draws the same flag: emoji flags
// render as rectangles on iPhone and as bare letters on some Android fonts.
// Every country in utils/countries.ts has one, plus EU.

const resolveIso = (iso?: string | null, emoji?: string | null): string =>
  toIso2(iso) || isoFromFlagEmoji(emoji);

export const hasCountryFlag = (iso?: string | null, emoji?: string | null): boolean =>
  Boolean(FLAG_XML[resolveIso(iso, emoji)]);

interface Props {
  /** ISO-2, or one of the ISO-3 codes config/localRails maps. */
  iso?: string | null;
  /** A flag emoji, for data that carries one instead of a code. */
  emoji?: string | null;
  size?: number;
  /** A ring around the circle, e.g. the background color where flags overlap. */
  ringColor?: string;
  style?: StyleProp<ViewStyle>;
}

/** A circular country flag. A code without an image falls back to its
 * emoji; nothing usable renders nothing. */
export const CountryFlag: React.FC<Props> = ({ iso, emoji, size = 20, ringColor, style }) => {
  const code = resolveIso(iso, emoji);
  const xml = FLAG_XML[code];
  if (!xml) {
    const fallback = emoji || emojiFromIso2(code);
    if (!fallback) return null;
    const emojiStyle: TextStyle = { fontSize: size * 0.9, lineHeight: size * 1.15 };
    return <Text style={[emojiStyle, style as StyleProp<TextStyle>]}>{fallback}</Text>;
  }
  const ring = ringColor ? Math.max(1.5, Math.round(size / 12)) : 0;
  const outer = size + ring * 2;
  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[
        styles.wrap,
        { width: outer, height: outer, borderRadius: outer / 2 },
        ringColor ? { borderWidth: ring, borderColor: ringColor, backgroundColor: ringColor } : null,
        style,
      ]}
    >
      <SvgXml xml={xml} width={size} height={size} />
    </View>
  );
};

interface FlagLabelProps extends Omit<Props, 'style'> {
  children?: React.ReactNode;
  textStyle?: StyleProp<TextStyle>;
  style?: StyleProp<ViewStyle>;
  numberOfLines?: number;
}

/** A flag followed by text — where copy used to read `${flag} ${text}`. The
 * flag sits beside the Text rather than inside it, so its size and baseline
 * don't depend on the font. Without a usable flag it is just the text. */
export const FlagLabel: React.FC<FlagLabelProps> = ({
  children, textStyle, style, numberOfLines, size, ...flag
}) => {
  const fontSize = (StyleSheet.flatten(textStyle) as TextStyle | undefined)?.fontSize ?? 14;
  return (
    <View style={[styles.label, style]}>
      <CountryFlag {...flag} size={size ?? Math.round(fontSize * 1.15)} style={styles.labelFlag} />
      <Text style={[styles.labelText, textStyle]} numberOfLines={numberOfLines}>{children}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  label: { flexDirection: 'row', alignItems: 'center' },
  labelFlag: { marginRight: 6 },
  labelText: { flexShrink: 1 },
});
