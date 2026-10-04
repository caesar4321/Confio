// Home hero line: "Octubre · Entró US$420 · Salió US$310 ›" (design Variant A).
// Plain text on the brand field — deliberately NOT a pill, so Home never
// reads as three buttons next to Enviar/Recibir. No motion (calm Home, 7E).
//
// Fixed footprint: the line, its masked form and the cold-launch placeholder
// all lay out the same invisible worst-case template (longest month, widest
// compact amounts), with the visible content drawn on top. The row's height
// therefore never depends on the data, masking or loading, at any width or
// font scale, and Enviar/Recibir below never move.
import React from 'react';
import { StyleSheet, TouchableOpacity, View } from 'react-native';
import { Text } from './common/AppText';
import { colors } from '../config/theme';
import type { MonthSummary } from '../apollo/monthSummary';
import { capitalize, formatUsd, MASK, monthName } from '../utils/monthSummary';

type Props = {
  summary: MonthSummary;
  masked: boolean;
  onPress: () => void;
};

/** Sizing layer: invisible, hidden from accessibility, defines the height. */
function Template() {
  return (
    <Text style={[styles.text, styles.invisible]} accessibilityElementsHidden importantForAccessibility="no">
      Septiembre · Entró <Text style={styles.amount}>US$99,999</Text> · Salió{' '}
      <Text style={styles.amount}>US$99,999</Text> ›
    </Text>
  );
}

export function HeroMonthLine({ summary, masked, onPress }: Props) {
  const month = capitalize(monthName(summary.month));
  // Compact on screen (never wider than the template); full amounts for
  // screen readers.
  const income = masked ? MASK : formatUsd(summary.current.incomeUsd, { whole: true, compact: true });
  const spending = masked ? MASK : formatUsd(summary.current.spendingUsd, { whole: true, compact: true });
  const fullIncome = formatUsd(summary.current.incomeUsd, { whole: true }).replace('US$', '');
  const fullSpending = formatUsd(summary.current.spendingUsd, { whole: true }).replace('US$', '');
  const label = masked
    ? `${month}: resumen del mes. Abrir tu mes`
    : `${month}: entraron ${fullIncome} dólares, salieron ${fullSpending} dólares. Abrir tu mes`;

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
      <Template />
      <View style={styles.overlay} pointerEvents="none">
        <Text style={styles.text}>
          {month} · Entró <Text style={styles.amount}>{income}</Text> · Salió{' '}
          <Text style={styles.amount}>{spending}</Text> ›
        </Text>
      </View>
    </TouchableOpacity>
  );
}

/** Holds the line's row on a cold launch (device hint): same template, so
 *  the same height as the line; a faint bar shows on top. */
export function HeroMonthLinePlaceholder() {
  return (
    <View style={styles.row} importantForAccessibility="no-hide-descendants" accessibilityElementsHidden
      testID="hero-month-line-placeholder">
      <Template />
      <View style={styles.overlay} pointerEvents="none">
        <View style={styles.placeholderBar} />
      </View>
    </View>
  );
}

/** Home's slot: the reserved placeholder, the line, or nothing. */
export function HeroMonthSlot({ summary, reserved, masked, onPress }: {
  summary: MonthSummary | null;
  reserved: boolean;
  masked: boolean;
  onPress: (summary: MonthSummary) => void;
}) {
  if (summary) return <HeroMonthLine summary={summary} masked={masked} onPress={() => onPress(summary)} />;
  if (reserved) return <HeroMonthLinePlaceholder />;
  return null;
}

const styles = StyleSheet.create({
  row: {
    minHeight: 44,
    justifyContent: 'center',
    alignSelf: 'center',
    paddingHorizontal: 8,
  },
  text: {
    color: colors.onHeroField,
    // 19 bold = WCAG large text (>= 14pt bold, ~18.7px): deep text-on-mint
    // passes 3:1 anywhere on the field; see colors.onHeroField.
    fontSize: 19,
    fontWeight: '700',
    textAlign: 'center',
    fontVariant: ['tabular-nums'],
  },
  amount: {
    fontWeight: '700',
  },
  invisible: {
    color: 'transparent',
  },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 8,
  },
  placeholderBar: {
    width: 220,
    height: 14,
    borderRadius: 7,
    backgroundColor: 'rgba(6,78,59,0.12)', // onHeroField, faint
  },
});
