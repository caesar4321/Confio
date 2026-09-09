// Institution logo with a monogram fallback, mirroring TickerLogo.
//
// Most institutions will never ship us an asset, so the monogram is the normal
// case rather than the error case: "Colegio de Ingenieros del Perú" reads as
// CIP, which is what members actually call it. If a logo URL is configured and
// fails to load, the monogram takes over — a list never shows a broken-image
// glyph.

import React, { useState } from 'react';
import { View, Text, Image, StyleSheet } from 'react-native';

import { colors } from '../config/theme';

// Spanish connectives carry no identity; "Colegio de Ingenieros del Perú"
// must not read as "CDIDP".
const SKIP = new Set([
  'de', 'del', 'la', 'las', 'el', 'los', 'y', 'e', 'en', 'para', 'por', 'a',
]);

export const institutionMonogram = (name: string): string => {
  const words = (name || '')
    .split(/[\s\-—–]+/)
    .map(word => word.replace(/[^\p{L}\p{N}]/gu, ''))
    .filter(word => word && !SKIP.has(word.toLocaleLowerCase('es')));
  if (!words.length) return '—';
  return words.slice(0, 3).map(word => word[0].toLocaleUpperCase('es')).join('');
};

export const InstitutionLogo = ({
  name,
  logoUrl,
  size = 44,
  background = colors.primaryDark,
}: {
  name: string;
  logoUrl?: string | null;
  size?: number;
  background?: string;
}) => {
  const [failed, setFailed] = useState(false);

  if (logoUrl && !failed) {
    return (
      <Image
        source={{ uri: logoUrl }}
        onError={() => setFailed(true)}
        accessibilityLabel={name}
        style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: colors.white }}
      />
    );
  }

  const monogram = institutionMonogram(name);
  return (
    <View
      style={[
        styles.circle,
        { width: size, height: size, borderRadius: size / 2, backgroundColor: background },
      ]}
      accessibilityLabel={name}
    >
      <Text
        style={[styles.text, { fontSize: Math.max(9, size * (monogram.length > 2 ? 0.3 : 0.36)) }]}
        allowFontScaling={false}
      >
        {monogram}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  circle: { alignItems: 'center', justifyContent: 'center' },
  text: { color: colors.white, fontWeight: '800', letterSpacing: 0.3 },
});
