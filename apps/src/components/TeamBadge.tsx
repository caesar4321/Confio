import React from 'react';
import { StyleSheet, View } from 'react-native';

import { Text } from './common/AppText';

type Props = { emoji: string; color: string; size?: number };

/** A team's image: its emoji on its color (no uploads in v1). */
export function TeamBadge({ emoji, color, size = 44 }: Props) {
  return (
    <View style={[styles.badge, { width: size, height: size, borderRadius: size / 2, backgroundColor: color }]}>
      <Text style={{ fontSize: Math.round(size * 0.5), lineHeight: Math.round(size * 0.62) }} allowFontScaling={false}>
        {emoji}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: { alignItems: 'center', justifyContent: 'center' },
});
