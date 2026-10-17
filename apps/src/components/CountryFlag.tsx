import React from 'react';
import { StyleProp, StyleSheet, TextStyle, View, ViewStyle } from 'react-native';
import { SvgProps } from 'react-native-svg';
import { Text } from './common/AppText';
import { countryFlag, toIso2 } from '../config/localRails';
import AR from '../assets/flags/ar.svg';
import BO from '../assets/flags/bo.svg';
import BR from '../assets/flags/br.svg';
import CL from '../assets/flags/cl.svg';
import CO from '../assets/flags/co.svg';
import EC from '../assets/flags/ec.svg';
import EU from '../assets/flags/eu.svg';
import GB from '../assets/flags/gb.svg';
import MX from '../assets/flags/mx.svg';
import PE from '../assets/flags/pe.svg';
import PY from '../assets/flags/py.svg';
import US from '../assets/flags/us.svg';
import UY from '../assets/flags/uy.svg';
import VE from '../assets/flags/ve.svg';

// Round flags bundled with the app (HatScripts/circle-flags, MIT — see
// assets/flags/LICENSE.md), so every phone draws the same flag: emoji flags
// render as rectangles on iPhone and as bare letters on some Android fonts.
// Only the countries the money rails list; add a file here to add one.
const FLAGS: Record<string, React.FC<SvgProps>> = {
  AR, BO, BR, CL, CO, EC, EU, GB, MX, PE, PY, US, UY, VE,
};

export const hasCountryFlag = (iso: string): boolean => Boolean(FLAGS[toIso2(iso)]);

interface Props {
  /** ISO-2 or ISO-3 (payment_accounts stores ISO-3). */
  iso: string;
  size?: number;
  /** A ring around the circle, e.g. the background color where flags overlap. */
  ringColor?: string;
  style?: StyleProp<ViewStyle>;
}

/** A circular country flag; a country without a bundled image falls back to its emoji. */
export const CountryFlag: React.FC<Props> = ({ iso, size = 20, ringColor, style }) => {
  const Flag = FLAGS[toIso2(iso)];
  if (!Flag) {
    const emoji = countryFlag(iso);
    if (!emoji) return null;
    const emojiStyle: TextStyle = { fontSize: size * 0.9, lineHeight: size * 1.15 };
    return <Text style={[emojiStyle, style as StyleProp<TextStyle>]}>{emoji}</Text>;
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
      <Flag width={size} height={size} />
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
});
