// Home month card (design A, approved 2026-10-04): a crisp white card inside
// the mint hero with two stat blocks, like a fresh fintech summary:
//   ↓ ENTRÓ EN SEPTIEMBRE  US$215  |  ↑ SALIÓ  US$176  ›
// Each amount lives in its own block, so a bigger number only fits its own
// box (it shrinks to fit, never wraps a sentence).
//
// Fixed footprint: every state (month, invitation, loading) is the same two
// single-line rows, so the card's height never changes and Enviar/Recibir
// below never move. Dark text on white: full contrast, any size.
import React from 'react';
import { StyleSheet, TouchableOpacity, useWindowDimensions, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from './common/AppText';
import { colors } from '../config/theme';
import type { MonthSummary } from '../apollo/monthSummary';
import type { HeroMonthState } from '../hooks/useMonthHeroLine';
import { formatUsd, MASK, monthName } from '../utils/monthSummary';

// One deterministic size per device: the user's font scale (capped) is
// applied here, with explicit line heights and a fixed strip height, so the
// shrink-to-fit amounts can never change the row's height (any state, any
// width): Enviar/Recibir below never move.
const MAX_SCALE = 1.3;
const LABEL = { size: 11, line: 14 };
const VALUE = { size: 20, line: 26 };
const PAD_V = 10;

function useStripMetrics() {
  const { fontScale } = useWindowDimensions();
  const k = Math.min(Math.max(fontScale || 1, 1), MAX_SCALE);
  return {
    label: { fontSize: LABEL.size * k, lineHeight: LABEL.line * k },
    value: { fontSize: VALUE.size * k, lineHeight: VALUE.line * k },
    height: Math.ceil(PAD_V * 2 + (LABEL.line + 1 + VALUE.line) * k),
  };
}

type Metrics = ReturnType<typeof useStripMetrics>;

type Flow = 'in' | 'out';

/** Tiny arrow chip, sized to the label's line so rows keep their height. */
function FlowChip({ flow, size }: { flow: Flow; size: number }) {
  const tone = flow === 'in' ? colors.flowIn : colors.flowOut;
  return (
    <View style={[styles.chip, { width: size, height: size, borderRadius: size / 2, backgroundColor: tone.chip }]}>
      <Icon name={flow === 'in' ? 'arrow-down' : 'arrow-up'} size={Math.round(size * 0.7)} color={tone.text} />
    </View>
  );
}

function Block({ label, value, m, flow }: { label: string; value: string; m: Metrics; flow?: Flow }) {
  return (
    <View style={styles.block}>
      <View style={styles.labelRow}>
        <Text style={[styles.label, m.label, styles.labelText]} numberOfLines={1} adjustsFontSizeToFit
          allowFontScaling={false}>{label}</Text>
        {flow ? <FlowChip flow={flow} size={m.label.lineHeight} /> : null}
      </View>
      <Text style={[styles.value, m.value]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}
        allowFontScaling={false}>{value}</Text>
    </View>
  );
}

type Props = {
  summary: MonthSummary;
  masked: boolean;
  onPress: () => void;
};

export function HeroMonthLine({ summary, masked, onPress }: Props) {
  const m = useStripMetrics();
  const month = monthName(summary.month);
  // Exact amounts, like the balance above (no "K"/"M" shorthand).
  const income = formatUsd(summary.current.incomeUsd, { whole: true });
  const spending = formatUsd(summary.current.spendingUsd, { whole: true });
  const label = masked
    ? `${month}: resumen del mes. Abrir tu mes`
    : `${month}: entraron ${income.replace('US$', '')} dólares, salieron ${spending.replace('US$', '')} dólares. Abrir tu mes`;

  return (
    <TouchableOpacity
      onPress={onPress}
      activeOpacity={0.75}
      style={[styles.strip, { height: m.height }]}
      accessibilityRole="button"
      accessibilityLabel={label}
      testID="hero-month-line"
    >
      <Block m={m} flow="in" label={`ENTRÓ EN ${month.toUpperCase()}`} value={masked ? MASK : income} />
      <View style={styles.divider} />
      <Block m={m} flow="out" label="SALIÓ" value={masked ? MASK : spending} />
      <Icon name="chevron-right" size={20} color={colors.text.light} />
    </TouchableOpacity>
  );
}

/** Not enough activity yet: invite owners into Tu mes (same footprint). */
export function HeroMonthInvite({ onPress }: { onPress: () => void }) {
  const m = useStripMetrics();
  return (
    <TouchableOpacity
      onPress={onPress}
      activeOpacity={0.75}
      style={[styles.strip, { height: m.height }]}
      accessibilityRole="button"
      accessibilityLabel="Tu mes: mira lo que entra y sale. Abrir tu mes"
      testID="hero-month-invite"
    >
      <Block m={m} label="TU MES" value="Mira lo que entra y sale" />
      <Icon name="chevron-right" size={20} color={colors.text.light} />
    </TouchableOpacity>
  );
}

/** While the first answer loads: the same two rows, invisible, with faint
 *  bars on top (same height as the strip). */
export function HeroMonthLinePlaceholder() {
  const m = useStripMetrics();
  return (
    <View style={[styles.strip, { height: m.height }]} importantForAccessibility="no-hide-descendants"
      accessibilityElementsHidden testID="hero-month-line-placeholder">
      <View style={styles.placeholderBars} pointerEvents="none">
        <View style={[styles.bar, styles.barShort]} />
        <View style={styles.bar} />
      </View>
    </View>
  );
}

/** Home's slot (owners): placeholder, month strip or invitation; nothing
 *  for employees. */
export function HeroMonthSlot({ state, masked, onPress }: {
  state: HeroMonthState;
  masked: boolean;
  /** month: the month shown (open Tu mes on it); undefined: the invitation. */
  onPress: (month?: MonthSummary) => void;
}) {
  switch (state.kind) {
    case 'month':
      return <HeroMonthLine summary={state.summary} masked={masked} onPress={() => onPress(state.summary)} />;
    case 'invite':
      return <HeroMonthInvite onPress={() => onPress(undefined)} />;
    case 'loading':
      return <HeroMonthLinePlaceholder />;
    default:
      return null;
  }
}

const styles = StyleSheet.create({
  strip: {
    alignSelf: 'stretch',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 44,
    paddingHorizontal: 16,
    paddingVertical: PAD_V,
    borderRadius: 16,
    backgroundColor: colors.white,
    shadowColor: '#065F46',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.12,
    shadowRadius: 10,
    elevation: 3,
  },
  block: { flex: 1 },
  divider: { width: StyleSheet.hairlineWidth, alignSelf: 'stretch', backgroundColor: colors.border },
  labelRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  labelText: { flexShrink: 1 },
  chip: { alignItems: 'center', justifyContent: 'center' },
  label: {
    fontWeight: '600',
    letterSpacing: 0.6,
    color: colors.text.secondary,
  },
  value: {
    fontWeight: '700',
    color: colors.textFlat,
    fontVariant: ['tabular-nums'],
    marginTop: 1,
  },
  placeholderBars: { flex: 1, justifyContent: 'center', gap: 6 },
  bar: { height: 12, width: '70%', borderRadius: 6, backgroundColor: colors.surfaceMuted },
  barShort: { height: 8, width: '40%' },
});
