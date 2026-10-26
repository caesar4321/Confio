import React, { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Defs, Line, LinearGradient, Path, Polyline, Stop } from 'react-native-svg';

import { Text } from '../common/AppText';

const W = 320;

/**
 * A price line over a soft gradient (react-native-svg, no chart library),
 * with optional horizontal guides: the entry price and the liquidation
 * price of an open position, so the member sees how far each one is.
 */
export function AreaChart({
  values,
  height = 140,
  color,
  guides = [],
  emptyText,
  testID,
}: {
  values: number[];
  height?: number;
  color: string;
  guides?: { value: number; color: string; label: string; dashed?: boolean }[];
  emptyText: string;
  testID?: string;
}) {
  const geometry = useMemo(() => {
    if (values.length < 2) return null;
    const visibleGuides = guides.map((g) => g.value).filter((v) => Number.isFinite(v) && v > 0);
    const all = [...values, ...visibleGuides];
    let min = Math.min(...all);
    let max = Math.max(...all);
    const pad = (max - min) * 0.08 || max * 0.01 || 1;
    min -= pad;
    max += pad;
    const span = max - min || 1;
    const y = (v: number) => height - ((v - min) / span) * height;
    const points = values.map((v, i) => `${((i / (values.length - 1)) * W).toFixed(1)},${y(v).toFixed(1)}`);
    const area = `M0,${height} L${points.join(' L')} L${W},${height} Z`;
    return { points: points.join(' '), area, y };
  }, [values, guides, height]);

  if (!geometry) {
    return (
      <View style={[styles.empty, { height }]}>
        <Text style={styles.emptyText}>{emptyText}</Text>
      </View>
    );
  }
  const gradientId = `area-${color.replace('#', '')}`;
  return (
    <View>
      <Svg width="100%" height={height} viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" testID={testID}>
        <Defs>
          <LinearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={color} stopOpacity="0.28" />
            <Stop offset="1" stopColor={color} stopOpacity="0" />
          </LinearGradient>
        </Defs>
        <Path d={geometry.area} fill={`url(#${gradientId})`} />
        {guides.filter((g) => Number.isFinite(g.value) && g.value > 0).map((g) => (
          <Line key={g.label} x1={0} x2={W} y1={geometry.y(g.value)} y2={geometry.y(g.value)}
            stroke={g.color} strokeWidth={1.2} strokeDasharray={g.dashed ? '5,4' : undefined} />
        ))}
        <Polyline points={geometry.points} fill="none" stroke={color} strokeWidth={2.4}
          strokeLinejoin="round" strokeLinecap="round" />
      </Svg>
      {guides.length > 0 && (
        <View style={styles.legend}>
          {guides.filter((g) => Number.isFinite(g.value) && g.value > 0).map((g) => (
            <View key={g.label} style={styles.legendItem}>
              <View style={[styles.legendSwatch, { backgroundColor: g.color }]} />
              <Text style={styles.legendText}>{g.label}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  empty: { alignItems: 'center', justifyContent: 'center' },
  emptyText: { fontSize: 12, color: '#6B7280' },
  legend: { flexDirection: 'row', gap: 14, marginTop: 8 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendSwatch: { width: 14, height: 3, borderRadius: 2 },
  legendText: { fontSize: 11, color: '#6B7280' },
});
