// Remote stock logo with an initial-circle fallback.
//
// Design-phase logos come from a public CDN; production swaps the URL source
// to Ondo GM asset metadata (post API-key) without touching call sites. If
// the image fails to load, the branded initial circle takes over — the list
// never shows a broken-image glyph.

import React, { useEffect, useState } from 'react';
import { View, Image, StyleSheet } from 'react-native';
import { Text } from './common/AppText';

export const TickerLogo = ({
  ticker,
  color,
  logoUrl,
  size = 42,
  onPending,
  onSettled,
}: {
  ticker: string;
  color: string;
  logoUrl?: string;
  size?: number;
  /** Share cards hold their capture on these: this image's URL is loading
   * (mounted or changed), then loaded or failed. */
  onPending?: (url: string) => void;
  onSettled?: (url: string) => void;
}) => {
  // Failure belongs to one URL: a new URL gets its own try.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const failed = !!logoUrl && failedUrl === logoUrl;
  useEffect(() => {
    if (logoUrl && failedUrl !== logoUrl) onPending?.(logoUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logoUrl]);

  if (logoUrl && !failed) {
    return (
      <Image
        source={{ uri: logoUrl }}
        // A share card is captured right after onLoad; Android fades remote
        // images in over 300 ms from that moment, which would ship a faded logo.
        fadeDuration={onSettled ? 0 : undefined}
        onLoad={() => onSettled?.(logoUrl)}
        onError={() => { setFailedUrl(logoUrl); onSettled?.(logoUrl); }}
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
