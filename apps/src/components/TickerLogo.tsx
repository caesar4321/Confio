// Remote stock logo with an initial-circle fallback.
//
// Design-phase logos come from a public CDN; production swaps the URL source
// to Ondo GM asset metadata (post API-key) without touching call sites. If
// the image fails to load, the branded initial circle takes over — the list
// never shows a broken-image glyph.

import React, { useState } from 'react';
import { View, Text, Image, StyleSheet } from 'react-native';

export const TickerLogo = ({
  ticker,
  color,
  logoUrl,
  size = 42,
}: {
  ticker: string;
  color: string;
  logoUrl?: string;
  size?: number;
}) => {
  const [failed, setFailed] = useState(false);

  if (logoUrl && !failed) {
    return (
      <Image
        source={{ uri: logoUrl }}
        onError={() => setFailed(true)}
        style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: '#fff' }}
      />
    );
  }
  return (
    <View
      style={[
        styles.circle,
        { width: size, height: size, borderRadius: size / 2, backgroundColor: color },
      ]}
    >
      <Text style={[styles.text, { fontSize: Math.max(9, size * 0.26) }]}>
        {ticker.slice(0, 4)}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  circle: { alignItems: 'center', justifyContent: 'center' },
  text: { color: '#fff', fontWeight: '800' },
});
