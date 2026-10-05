// Card A — "Te quedaron" (tu-mes-insights.md §3, §6; design review 1A, 2A,
// 12B, 19A). The single 34pt anchor on Tu mes: Entró − Salió, its two
// tappable totals, the in/out bar, the "Sin contar…" caption, then either
// the comparison with last month or (current month, day ≥ 5) the pace line.
import React, { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, LinearGradient as SvgLinearGradient, Rect, Stop } from 'react-native-svg';
import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import type { MonthSummary } from '../../apollo/monthSummary';
import { formatUsd, MASK, monthName, previousMonth } from '../../utils/monthSummary';
import { formatUsdAmount } from '../../utils/numberLocale';
import type { PaceLine } from '../../utils/monthInsights';
import { CARD_FONT_MULTIPLIER } from './CardShell';

const TICK_MS = 1200;

/** DESIGN.md "tick-settle": money rolls in once and settles; instant with Reduce Motion. */
export function useTickSettle(target: number, runKey: string) {
  const anim = useRef(new Animated.Value(0)).current;
  const [value, setValue] = useState(target);
  // A refresh can change the number mid-roll or after it settled: the roll
  // heads for the latest target, and a settled number jumps straight to it.
  const targetRef = useRef(target);
  const settled = useRef(false);
  targetRef.current = target;
  useEffect(() => {
    if (settled.current) setValue(target);
  }, [target]);
  useEffect(() => {
    let cancelled = false;
    settled.current = false;
    const id = anim.addListener(({ value: v }) => setValue(targetRef.current * v));
    const settle = () => {
      if (cancelled) return;
      settled.current = true;
      setValue(targetRef.current);
    };
    AccessibilityInfo.isReduceMotionEnabled().then((reduce) => {
      if (cancelled) return;
      if (reduce) {
        anim.setValue(1);
        settle();
        return;
      }
      anim.setValue(0);
      Animated.timing(anim, { toValue: 1, duration: TICK_MS, easing: Easing.out(Easing.cubic), useNativeDriver: false })
        .start(settle);
    }).catch(settle);
    return () => {
      cancelled = true;
      anim.stopAnimation();
      anim.removeListener(id);
    };
    // runKey: animate on the first open of each month view only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey]);
  return value;
}

/** Whole dollars, the screen's one precision (design C). */
const money = (value: string | number, masked: boolean) => (masked ? MASK : formatUsd(value, { whole: true }));

/** "+US$39" / "US$0" / "−US$12" (never red: §3). */
export function resultText(result: number, masked: boolean): string {
  if (masked) return MASK;
  const rounded = Math.round(result);
  if (rounded === 0) return formatUsdAmount(0, { decimals: 0 });
  return `${rounded > 0 ? '+' : '−'}${formatUsd(Math.abs(result), { whole: true })}`;
}

export function resultLabel(result: number): string {
  const rounded = Math.round(result);
  if (rounded > 0) return 'Te quedaron';
  if (rounded === 0) return 'Quedaste a mano';
  return 'Salió más de lo que entró';
}

/** "vs agosto: salió US$6 menos, entró US$11 más" (§3). */
export function comparisonText(summary: MonthSummary): string | null {
  if (summary.previous.movementCount === 0) return null;
  const prev = monthName(previousMonth(summary.year, summary.month).month);
  const label = summary.previousIsPartial ? `Mismo período de ${prev}` : `vs ${prev}`;
  const part = (verb: string, now: number, before: number) => {
    const diff = Math.round(now - before);
    if (diff === 0) return `${verb} igual`;
    return `${verb} ${formatUsd(Math.abs(diff), { whole: true })} ${diff > 0 ? 'más' : 'menos'}`;
  };
  return `${label}: ${part('salió', Number(summary.current.spendingUsd), Number(summary.previous.spendingUsd))}, `
    + `${part('entró', Number(summary.current.incomeUsd), Number(summary.previous.incomeUsd))}`;
}

type Props = {
  summary: MonthSummary;
  masked: boolean;
  runKey: string;
  /** null: show the comparison line instead (past months, before day 5). */
  pace: PaceLine | null;
  onOpenIncome: () => void;
  onOpenSpending: () => void;
  /** Shown on a month with no movements yet: an invitation to start. */
  onSend?: () => void;
  onReceive?: () => void;
};

const PACE_ICON = { less: 'check-circle', same: 'minus-circle', more: 'info' } as const;

export function SummaryCard({ summary, masked, runKey, pace, onOpenIncome, onOpenSpending, onSend, onReceive }: Props) {
  const quiet = summary.current.movementCount === 0;
  const income = Number(summary.current.incomeUsd);
  const spending = Number(summary.current.spendingUsd);
  const result = income - spending;
  const shownResult = useTickSettle(result, runKey);         // the one authored motion (19A)
  const total = income + spending;
  const positive = Math.round(result) > 0;
  const comparison = pace ? null : comparisonText(summary);
  const paceColor = pace?.tone === 'less' ? colors.flowIn.textSmall
    : pace?.tone === 'more' ? colors.flowOut.text : colors.text.secondary;

  const summaryLabel = masked
    ? `${resultLabel(result)}, oculto.`
    : `${resultLabel(result)} ${Math.abs(Math.round(result))} dólares.`;

  return (
    <View style={styles.card} testID="tumes-summary-card">
      <Svg style={StyleSheet.absoluteFill} pointerEvents="none">
        <Defs>
          <SvgLinearGradient id="tuMesWash" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={colors.primarySoft} stopOpacity="1" />
            <Stop offset="0.65" stopColor={colors.white} stopOpacity="1" />
          </SvgLinearGradient>
        </Defs>
        <Rect width="100%" height="100%" fill="url(#tuMesWash)" />
      </Svg>

      {/* Non-interactive summary: one spoken label (design review 20A). */}
      <View accessible accessibilityLabel={summaryLabel}>
        <Text style={styles.resultLabel} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>{resultLabel(result)}</Text>
        <Text style={[styles.result, positive && styles.resultPositive]} numberOfLines={1}
          adjustsFontSizeToFit minimumFontScale={0.85} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-result">
          {resultText(shownResult, masked)}
        </Text>
      </View>

      <View style={styles.flows}>
        <TouchableOpacity onPress={onOpenIncome} style={styles.flow} accessibilityRole="button" testID="total-income"
          accessibilityLabel={masked ? 'Entró, oculto' : `Entró ${formatUsd(income, { whole: true })}`}>
          <View style={[styles.chip, { backgroundColor: colors.flowIn.chip }]}>
            <Icon name="arrow-down" size={13} color={colors.flowIn.textSmall} />
          </View>
          <Text style={[styles.flowText, styles.flowIn]} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
            Entró {money(income, masked)}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={onOpenSpending} style={styles.flow} accessibilityRole="button" testID="total-spending"
          accessibilityLabel={masked ? 'Salió, oculto' : `Salió ${formatUsd(spending, { whole: true })}`}>
          <View style={[styles.chip, { backgroundColor: colors.flowOut.chip }]}>
            <Icon name="arrow-up" size={13} color={colors.flowOut.text} />
          </View>
          <Text style={[styles.flowText, styles.flowOut]} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
            Salió {money(spending, masked)}
          </Text>
        </TouchableOpacity>
      </View>

      <View style={styles.bar} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
        {/* Normalized weights (Yoga floors flex sums below 1), no zero-width segments. */}
        {income > 0 && <View style={[styles.barIn, { flex: income / total }]} />}
        {spending > 0 && <View style={[styles.barOut, { flex: spending / total }]} />}
      </View>

      <Text style={styles.caption} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>Sin contar recargas, retiros ni ahorro.</Text>

      {/* Masked: no comparison (a "menos"/"más" would leak the direction). */}
      {comparison && !masked && (
        <Text style={styles.caption} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="month-comparison">{comparison}</Text>
      )}

      {quiet && onSend && onReceive && (
        <View style={styles.actions} testID="tumes-quiet-actions">
          <Text style={styles.caption} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
            Todavía no hay movimientos este mes.
          </Text>
          <View style={styles.actionRow}>
            <TouchableOpacity style={[styles.action, styles.actionPrimary]} onPress={onSend} accessibilityRole="button">
              <Text style={[styles.actionText, styles.actionPrimaryText]}>Enviar</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.action} onPress={onReceive} accessibilityRole="button">
              <Text style={styles.actionText}>Recibir</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {pace && (
        <View style={styles.pace} testID="tumes-pace" accessible
          accessibilityLabel={`${pace.verdict}.${pace.projectionUsd !== null && !masked
            ? ` A este ritmo, alrededor de ${Math.round(pace.projectionUsd)} dólares este mes.` : ''}`}>
          <View style={styles.paceRow}>
            <Icon name={PACE_ICON[pace.tone]} size={16} color={paceColor} />
            <Text style={styles.paceVerdict} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>{pace.verdict}</Text>
          </View>
          {pace.projectionUsd !== null && (
            <Text style={styles.caption} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-projection">
              A este ritmo, ~{money(pace.projectionUsd, masked)} este mes · {pace.previousMonthLabel} {money(pace.previousMonthUsd, masked)}
            </Text>
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.white, borderRadius: 20, padding: 20, overflow: 'hidden',
    borderWidth: StyleSheet.hairlineWidth, borderColor: colors.primaryMuted,
  },
  resultLabel: { fontSize: 13, lineHeight: 18, color: colors.text.secondary },
  result: { fontSize: 34, lineHeight: 40, fontWeight: '700', color: colors.textFlat, fontVariant: ['tabular-nums'] },
  resultPositive: { color: colors.flowIn.text },
  flows: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 16, rowGap: 4, marginTop: 8 },
  flow: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44 },
  chip: { width: 20, height: 20, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  flowText: { fontSize: 15, lineHeight: 20, fontWeight: '600', fontVariant: ['tabular-nums'] },
  flowIn: { color: colors.flowIn.textSmall },
  flowOut: { color: colors.flowOut.text },
  bar: { flexDirection: 'row', height: 8, borderRadius: 4, overflow: 'hidden', backgroundColor: colors.surfaceMuted, gap: 2, marginTop: 4 },
  barIn: { backgroundColor: colors.flowIn.bar, borderRadius: 4 },
  barOut: { backgroundColor: colors.flowOut.bar, borderRadius: 4 },
  caption: { fontSize: 13, lineHeight: 18, color: colors.text.secondary, marginTop: 8, fontVariant: ['tabular-nums'] },
  pace: { marginTop: 12 },
  actions: { marginTop: 4 },
  actionRow: { flexDirection: 'row', gap: 10, marginTop: 10 },
  action: { minHeight: 44, paddingHorizontal: 22, borderRadius: 999, borderWidth: 1, borderColor: colors.primaryMuted,
    backgroundColor: colors.white, justifyContent: 'center' },
  actionPrimary: { backgroundColor: colors.primaryDark, borderColor: colors.primaryDark },
  actionText: { fontSize: 15, fontWeight: '700', color: colors.flowIn.textSmall },
  actionPrimaryText: { color: colors.white },
  paceRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  paceVerdict: { fontSize: 15, lineHeight: 20, fontWeight: '600', color: colors.textFlat, flexShrink: 1 },
});
