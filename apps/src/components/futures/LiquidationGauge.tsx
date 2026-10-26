import React from 'react';
import { StyleSheet, View } from 'react-native';

import { Text } from '../common/AppText';
import type { Side } from '../../services/perps';
import { formatPctSigned, formatPerpPrice } from '../../utils/perpsPresentation';

/**
 * How far the price can move against the position before it is
 * liquidated, as a bar from "safe" to "liquidación" with the live price
 * on it. The single most important number of a leveraged position, made
 * something you can see instead of a price you must compare in your head.
 */
export function LiquidationGauge({
  side,
  entryPx,
  markPx,
  liquidationPx,
}: {
  side: Side;
  entryPx: number | null;
  markPx: number | null;
  liquidationPx: number | null;
}) {
  if (!entryPx || !markPx || !liquidationPx || liquidationPx <= 0) return null;
  // Distance left, as a percent of the current price.
  const distance = side === 'long' ? (markPx - liquidationPx) / markPx : (liquidationPx - markPx) / markPx;
  const full = side === 'long' ? (entryPx - liquidationPx) / entryPx : (liquidationPx - entryPx) / entryPx;
  const left = full > 0 ? Math.max(0, Math.min(1, distance / full)) : 0;
  const tone = left > 0.6 ? '#10B981' : left > 0.3 ? '#F59E0B' : '#DC2626';
  return (
    <View style={styles.wrap} accessible accessibilityLabel={`Liquidación a ${formatPerpPrice(liquidationPx)}, a ${formatPctSigned(-distance * 100)} del precio actual`}>
      <View style={styles.head}>
        <Text style={styles.label}>Distancia a la liquidación</Text>
        <Text style={[styles.distance, { color: tone }]}>
          {formatPctSigned((side === 'long' ? -1 : 1) * distance * 100)}
        </Text>
      </View>
      <View style={styles.track}>
        <View style={[styles.fill, { width: `${left * 100}%`, backgroundColor: tone }]} />
      </View>
      <View style={styles.ends}>
        <Text style={styles.end}>Liquidación {formatPerpPrice(liquidationPx)}</Text>
        <Text style={styles.end}>Ahora {formatPerpPrice(markPx)}</Text>
      </View>
      <Text style={styles.hint}>
        {`Si el precio ${side === 'long' ? 'baja' : 'sube'} hasta ${formatPerpPrice(liquidationPx)}, Hyperliquid cierra tu posición y pierdes el margen.`}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 4 },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  label: { fontSize: 13, fontWeight: '700', color: '#6B7280' },
  distance: { fontSize: 15, fontWeight: '800' },
  track: { height: 10, borderRadius: 5, backgroundColor: '#F3F4F6', overflow: 'hidden', marginTop: 10 },
  fill: { height: '100%', borderRadius: 5 },
  ends: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 },
  end: { fontSize: 11, color: '#6B7280' },
  hint: { fontSize: 12, lineHeight: 17, color: '#6B7280', marginTop: 10 },
});
