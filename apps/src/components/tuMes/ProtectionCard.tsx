// The dollar slot (tu-mes-insights.md §4, R21): Card B "Tu dólar te
// protegió" when the server could prove it, otherwise Card B' "Tu ahorro
// ganó". Design review 3A (28pt), 5A (daily bars), 6A (cents on B' only),
// 9A (the sheet explains the card's own quote, no fetch), 20A (a11y).
import React, { useState } from 'react';
import { Modal, Pressable, StyleSheet, TouchableOpacity, View } from 'react-native';
import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import type { ProtectionValue, SavingsEarned } from '../../apollo/monthSummary';
import { formatUsd, MASK, monthName } from '../../utils/monthSummary';
import { formatLocal, quoteTime, shortDate, SPARK_MIN_DAYS } from '../../utils/monthInsights';
import { formatUsdAmount } from '../../utils/numberLocale';
import { CardShell, CardTitle, CARD_FONT_MULTIPLIER } from './CardShell';

/** Day of the month the comparison starts (the 1st, or the first day a
 *  rate was kept in the launch month). */
function baselineDay(value: ProtectionValue): number {
  const day = Number((value.startDate ?? '').slice(8, 10));
  return Number.isInteger(day) && day >= 1 && day <= 31 ? day : 1;
}

const LOCAL_NAME: Record<string, string> = { BOB: 'bolivianos', VES: 'bolívares', ARS: 'pesos' };

export function ProtectionCard({ value, month, masked }: { value: ProtectionValue; month: number; masked: boolean }) {
  const [sheet, setSheet] = useState(false);
  // Bolivia/Argentina: what they paid in Confío. Venezuela (no on-ramp yet):
  // what those dollars were worth on the 1st. "Hoy" is Binance P2P for both.
  const monthStart = value.basis === 'month_start';
  const startDay = baselineDay(value);
  const startLabel = shortDate(month, startDay);
  const usd = formatUsd(value.protectedUsd, { whole: true });
  const gain = formatLocal(value.gainLocal, value.currency);
  const paid = Number(value.paidLocal);
  const today = Number(value.todayLocal);
  const max = Math.max(paid, today, 1);

  return (
    <CardShell testID="tumes-protection-card">
      <CardTitle icon="shield" title="Tu dólar te protegió" />
      <View accessible accessibilityLabel={masked
        ? 'Tu dólar te protegió. Montos ocultos.'
        : monthStart
          ? `Tu dólar te protegió: tus ${Math.round(Number(value.protectedUsd))} dólares valen hoy ${Math.round(Number(value.gainLocal))} ${LOCAL_NAME[value.currency] ?? value.currency} más que el ${startDay} de ${monthName(month)}.`
          : `Tu dólar te protegió: tus ${Math.round(Number(value.protectedUsd))} dólares hoy valen ${Math.round(Number(value.gainLocal))} ${LOCAL_NAME[value.currency] ?? value.currency} más de lo que pagaste.`}>
        {!masked && (
          <Text style={styles.sentence} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
            {monthStart
              ? <>Tus {usd} valen hoy <Text style={styles.gain}>{gain} más</Text> que el {startDay} de {monthName(month)}.</>
              : <>Tus {usd} hoy valen <Text style={styles.gain}>{gain} más</Text> de lo que pagaste.</>}
          </Text>
        )}
        <Bar label={monthStart ? startLabel : 'Pagaste'} amount={masked ? MASK : formatLocal(paid, value.currency)} share={paid / max}
          color={colors.compareNeutral} />
        <Bar label="Hoy" amount={masked ? MASK : formatLocal(today, value.currency)} share={today / max}
          color={colors.flowIn.bar} />
      </View>
      <TouchableOpacity onPress={() => setSheet(true)} accessibilityRole="button" style={styles.link}
        hitSlop={{ top: 12, bottom: 12, left: 4, right: 4 }} testID="tumes-protection-how">
        <Text style={styles.linkText} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>¿Cómo lo calculamos?</Text>
      </TouchableOpacity>
      <HowSheet visible={sheet} onClose={() => setSheet(false)} value={value} month={month} masked={masked} />
    </CardShell>
  );
}

function Bar({ label, amount, share, color }: { label: string; amount: string; share: number; color: string }) {
  return (
    <View style={styles.barRow}>
      <Text style={styles.barLabel} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>{label}</Text>
      <View style={styles.barTrack}>
        <View style={[styles.barFill, { width: `${Math.max(4, Math.round(share * 100))}%`, backgroundColor: color }]} />
      </View>
      <Text style={styles.barAmount} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>{amount}</Text>
    </View>
  );
}

/** "¿Cómo lo calculamos?" — a snapshot of the card's own quote (9A). */
function HowSheet({ visible, onClose, value, month, masked }: {
  visible: boolean; onClose: () => void; value: ProtectionValue; month: number; masked: boolean;
}) {
  const monthStart = value.basis === 'month_start';
  const startDay = baselineDay(value);
  const perUsd = (rate: string) => (masked ? MASK : `${formatLocal(rate, value.currency, 2)} por dólar`);
  const rows: [string, string][] = [
    [monthStart ? `El ${startDay} de ${monthName(month)} (Binance P2P)` : 'Pagaste en Confío, en promedio', perUsd(value.avgRate)],
    ['Hoy (Binance P2P)', perUsd(value.todayRate)],
    ['Tasa consultada', quoteTime(value.quotedAt)],
  ];
  const body = monthStart
    ? `Comparamos lo que valían tus dólares el ${startDay} de ${monthName(month)} con lo que valen hoy, a la tasa de Binance P2P. Solo cuentan los dólares que tuviste desde ese día.`
    : 'Comparamos lo que pagaste en Confío por tus dólares con lo que valen hoy a la tasa de Binance P2P.';
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.scrim} onPress={onClose} accessibilityLabel="Cerrar" />
      <View style={styles.sheet} testID="tumes-how-sheet">
        <View style={styles.handle} />
        <Text style={styles.sheetTitle} accessibilityRole="header">¿Cómo lo calculamos?</Text>
        {rows.map(([label, v], i) => (
          <View key={label} style={[styles.sheetRow, i > 0 && styles.sheetDivider]} accessible accessibilityLabel={`${label}: ${v}`}>
            <Text style={styles.sheetLabel}>{label}</Text>
            <Text style={styles.sheetValue}>{v}</Text>
          </View>
        ))}
        <Text style={styles.sheetBody}>{body}</Text>
        <TouchableOpacity style={styles.cta} onPress={onClose} accessibilityRole="button">
          <Text style={styles.ctaText}>Entendido</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  );
}

/** The dollar slot when the gain shrank or reversed (founder decision
 *  2026-10-04): never a loss, never local amounts; the dollars kept their
 *  dollar value. */
export function StableCard({ value, masked }: { value: ProtectionValue; masked: boolean }) {
  const usd = formatUsd(value.protectedUsd, { whole: true });
  return (
    <CardShell testID="tumes-stable-card">
      <CardTitle icon="shield" title="Tu dólar se mantuvo" />
      <Text style={styles.sentence} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}
        accessibilityLabel={masked ? 'Tu dólar se mantuvo. Monto oculto.'
          : `Tu dólar se mantuvo: tus ${Math.round(Number(value.protectedUsd))} dólares siguen valiendo lo mismo.`}>
        {masked ? 'Tus dólares siguen valiendo lo mismo.' : <>Tus {usd} siguen valiendo {usd}.</>}
      </Text>
    </CardShell>
  );
}

/** Card B' — savings earned, an estimate (R23) with cents (6A). */
export function SavingsCard({ value, month, masked }: { value: SavingsEarned; month: number; masked: boolean }) {
  const amount = `~${formatUsdAmount(Number(value.earnedUsd), { decimals: 2 })}`;
  const days = value.daily.map((d) => Number(d.usd));
  const max = Math.max(...days, 0);
  const showBars = days.length >= SPARK_MIN_DAYS && max > 0;
  return (
    <CardShell testID="tumes-savings-card">
      <CardTitle icon="trending-up" title="Tu ahorro ganó" />
      <View accessible accessibilityLabel={masked
        ? `Tu ahorro ganó, oculto, en ${monthName(month)}.`
        : `Tu ahorro ganó alrededor de ${value.earnedUsd} dólares en ${monthName(month)}.`}>
        <Text style={styles.savings} numberOfLines={1} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
          {masked ? MASK : amount}
        </Text>
        {showBars && (
          <View style={styles.spark} importantForAccessibility="no-hide-descendants" accessibilityElementsHidden
            testID="tumes-savings-bars">
            {days.map((v, i) => (
              <View key={value.daily[i].date}
                style={[styles.sparkBar, { height: `${Math.max(6, Math.round((v / max) * 100))}%` },
                  i === days.length - 1 && styles.sparkLast]} />
            ))}
          </View>
        )}
        <Text style={styles.caption} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>en {monthName(month)}</Text>
      </View>
    </CardShell>
  );
}

const styles = StyleSheet.create({
  sentence: { fontSize: 15, lineHeight: 20, color: colors.textFlat, marginBottom: 12 },
  gain: { fontWeight: '700', color: colors.flowIn.textSmall },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 8 },
  barLabel: { width: 64, fontSize: 13, color: colors.text.secondary },
  barTrack: { flex: 1, height: 10, borderRadius: 5, overflow: 'hidden' },
  barFill: { height: 10, borderRadius: 5 },
  barAmount: { fontSize: 15, fontWeight: '600', color: colors.textFlat, fontVariant: ['tabular-nums'], flexShrink: 0 },
  link: { marginTop: 14, minHeight: 32, justifyContent: 'center', alignSelf: 'flex-start' },
  linkText: { fontSize: 13, fontWeight: '600', color: colors.flowIn.textSmall },
  savings: { fontSize: 28, lineHeight: 34, fontWeight: '700', color: colors.flowIn.text, fontVariant: ['tabular-nums'] },
  spark: { flexDirection: 'row', alignItems: 'flex-end', gap: 2, height: 40, marginTop: 10 },
  sparkBar: { flex: 1, backgroundColor: colors.flowIn.bar, borderRadius: 2 },
  sparkLast: { backgroundColor: colors.flowIn.text },
  caption: { fontSize: 13, lineHeight: 18, color: colors.text.secondary, marginTop: 6 },
  scrim: { flex: 1, backgroundColor: 'rgba(17,24,39,0.4)' },
  sheet: { backgroundColor: colors.white, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 20, paddingBottom: 32 },
  handle: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, marginBottom: 16 },
  sheetTitle: { fontSize: 20, fontWeight: '700', color: colors.textFlat, marginBottom: 8 },
  sheetRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, paddingVertical: 12 },
  sheetDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  sheetLabel: { fontSize: 15, color: colors.textFlat, flexShrink: 1 },
  sheetValue: { fontSize: 15, fontWeight: '600', color: colors.textFlat, fontVariant: ['tabular-nums'] },
  sheetBody: { fontSize: 14, lineHeight: 20, color: colors.text.secondary, marginTop: 8 },
  cta: { marginTop: 20, minHeight: 48, borderRadius: 14, backgroundColor: colors.primaryDark, alignItems: 'center', justifyContent: 'center' },
  ctaText: { fontSize: 16, fontWeight: '700', color: colors.white },
});
