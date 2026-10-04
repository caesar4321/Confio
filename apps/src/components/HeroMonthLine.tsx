// Home hero line: "Octubre · Entró US$420 · Salió US$310 ›" (design Variant A).
// Plain white text on the brand field — deliberately NOT a pill, so Home never
// reads as three buttons next to Enviar/Recibir. No motion (calm Home, 7E).
import React from 'react';
import { StyleSheet, TouchableOpacity } from 'react-native';
import { Text } from './common/AppText';
import { colors } from '../config/theme';
import type { MonthSummary } from '../apollo/monthSummary';
import { capitalize, formatUsd, MASK, monthName } from '../utils/monthSummary';

type Props = {
  summary: MonthSummary;
  masked: boolean;
  onPress: () => void;
};

export function HeroMonthLine({ summary, masked, onPress }: Props) {
  const month = capitalize(monthName(summary.month));
  const income = masked ? MASK : formatUsd(summary.current.incomeUsd, { whole: true });
  const spending = masked ? MASK : formatUsd(summary.current.spendingUsd, { whole: true });
  const label = masked
    ? `${month}: resumen del mes. Abrir tu mes`
    : `${month}: entraron ${income.replace('US$', '')} dólares, salieron ${spending.replace('US$', '')} dólares. Abrir tu mes`;

  return (
    <TouchableOpacity
      onPress={onPress}
      activeOpacity={0.7}
      style={styles.row}
      hitSlop={{ top: 6, bottom: 6, left: 12, right: 12 }}
      accessibilityRole="button"
      accessibilityLabel={label}
      testID="hero-month-line"
    >
      <Text style={styles.text}>
        {month} · Entró <Text style={styles.amount}>{income}</Text> · Salió{' '}
        <Text style={styles.amount}>{spending}</Text> ›
      </Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  row: {
    minHeight: 44,
    justifyContent: 'center',
    alignSelf: 'center',
    paddingHorizontal: 8,
  },
  text: {
    color: colors.white,
    fontSize: 15,
    fontWeight: '600',
    textAlign: 'center',
    fontVariant: ['tabular-nums'],
  },
  amount: {
    fontWeight: '700',
  },
});
