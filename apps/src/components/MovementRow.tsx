// Shared row for Ahorros e Inversiones movements — used by the hub's
// "Movimientos" preview (recent few) and the full AhorrosMovimientos screen,
// so the two can never drift apart visually.

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { AhorroMovement } from '../hooks/useAhorrosPortfolio';

const MOVEMENT_ICONS: Record<string, string> = {
  deposit: 'arrow-down-circle',
  withdraw: 'arrow-up-circle',
  buy: 'shopping-cart',
  sell: 'repeat',
  yield: 'trending-up',
};

const formatMovementDate = (iso: string) =>
  new Date(iso).toLocaleDateString('es', { day: 'numeric', month: 'short' });

interface Props {
  movement: AhorroMovement;
  topBorder?: boolean;
}

export const MovementRow = ({ movement: m, topBorder }: Props) => (
  <View style={[styles.row, topBorder && styles.rowBorder]}>
    <View style={styles.icon}>
      <Icon
        name={MOVEMENT_ICONS[m.type] || 'circle'}
        size={16}
        color={colors.primaryDark}
      />
    </View>
    <View style={{ flex: 1 }}>
      <Text style={styles.title}>{m.title}</Text>
      <Text style={styles.date}>{formatMovementDate(m.createdAt)}</Text>
    </View>
    <Text style={[styles.amount, m.amountUsd < 0 && styles.amountOut]}>
      {m.amountUsd >= 0 ? '+' : '−'}${Math.abs(m.amountUsd).toFixed(2)}
    </Text>
  </View>
);

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 10,
  },
  rowBorder: { borderTopWidth: 1, borderTopColor: '#F3F4F6' },
  icon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
  date: { fontSize: 11, color: colors.text.light, marginTop: 1 },
  amount: { fontSize: 14, fontWeight: '700', color: colors.primaryDark },
  amountOut: { color: colors.text.primary },
});
