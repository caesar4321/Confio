// Card C — "Pagos habituales" (tu-mes-insights.md §5; design review 7A,
// 11A, 15A, 16B, 20A, 22A). Payments seen in 2 of the last 3 months. The
// pill is always the viewed month's expected day; days before today are
// grey and hollow (passed, never "paid"). Tap a row → that person's
// movements.
import React, { useState } from 'react';
import { StyleSheet, TouchableOpacity, useWindowDimensions, View } from 'react-native';
import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import type { RecurringPayment } from '../../apollo/monthSummary';
import { categoryLabel, formatUsd, MASK, monthName } from '../../utils/monthSummary';
import { daysIn, isPastDay, RECURRING_VISIBLE, shortDate } from '../../utils/monthInsights';
import { CardShell, CardTitle, CARD_FONT_MULTIPLIER } from './CardShell';

// Avatar tints shared with "Con quién" (never violet: $CONFIO only).
const AVATAR_TINTS = [
  { bg: '#D1FAE5', fg: '#065F46' },
  { bg: '#DBEAFE', fg: '#1E40AF' },
  { bg: '#FEF3C7', fg: '#92400E' },
  { bg: '#FFE4E6', fg: '#9F1239' },
];
function tintFor(key: string) {
  let h = 0;
  for (let i = 0; i < key.length; i += 1) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return AVATAR_TINTS[h % AVATAR_TINTS.length];
}

type Props = {
  items: RecurringPayment[];
  year: number;
  month: number;
  today: Date;
  masked: boolean;
  onOpen: (item: RecurringPayment) => void;
};

export function RecurringCard({ items, year, month, today, masked, onOpen }: Props) {
  const [expanded, setExpanded] = useState(false);
  // Large text: name / caption / amount stack instead of shrinking (21A).
  const stacked = useWindowDimensions().fontScale >= 1.3;
  const sorted = [...items].sort((a, b) => a.expectedDay - b.expectedDay || a.name.localeCompare(b.name));
  const visible = expanded ? sorted : sorted.slice(0, RECURRING_VISIBLE);
  const hidden = sorted.length - visible.length;
  const last = daysIn(year, month);
  const isCurrent = year === today.getFullYear() && month === today.getMonth() + 1;

  if (sorted.length === 0) {
    return (
      <CardShell testID="tumes-recurring-card">
        <CardTitle icon="calendar" title="Pagos habituales" />
        <Text style={styles.empty} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-recurring-empty">
          Cuando pagues a alguien cada mes, lo verás aquí.
        </Text>
      </CardShell>
    );
  }

  return (
    <CardShell testID="tumes-recurring-card">
      <CardTitle icon="calendar" title="Pagos habituales" />
      <DayTrack items={sorted} year={year} month={month} last={last} today={today} isCurrent={isCurrent} />
      {visible.map((item, i) => {
        const past = isPastDay(year, month, item.expectedDay, today);
        const tint = tintFor(item.counterpartyKey);
        const name = item.name || 'Sin nombre';
        const caption = item.category ? `${categoryLabel(item.category)} · casi cada mes` : 'casi cada mes';
        const amount = masked ? MASK : `~${formatUsd(item.expectedAmountUsd, { whole: true })}`;
        const date = shortDate(month, item.expectedDay);
        return (
          <TouchableOpacity key={item.counterpartyKey} style={[styles.row, i > 0 && styles.divider]}
            onPress={() => onOpen(item)} accessibilityRole="button" testID={`tumes-recurring-${item.counterpartyKey}`}
            accessibilityLabel={`${name}, pago habitual, ${masked ? 'monto oculto' : `alrededor de ${Math.round(Number(item.expectedAmountUsd))} dólares`}, el ${item.expectedDay} de ${monthName(month)}.`}>
            <View style={[styles.avatar, { backgroundColor: tint.bg }]}>
              <Text style={[styles.avatarText, { color: tint.fg }]} maxFontSizeMultiplier={1.2}>
                {name.trim().charAt(0).toUpperCase() || '?'}
              </Text>
            </View>
            <View style={[styles.body, stacked && styles.bodyStacked]}>
            <View style={styles.main}>
              <Text style={styles.name} numberOfLines={1} ellipsizeMode="tail" maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>{name}</Text>
              <Text style={styles.caption} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>{caption}</Text>
            </View>
            <View style={[styles.end, stacked && styles.endStacked]}>
              <Text style={styles.amount} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>{amount}</Text>
              <View style={[styles.pill, past && styles.pillPast]} testID={past ? 'tumes-pill-past' : 'tumes-pill'}>
                <Text style={[styles.pillText, past && styles.pillTextPast]} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>{date}</Text>
              </View>
            </View>
            </View>
          </TouchableOpacity>
        );
      })}
      {(hidden > 0 || expanded) && sorted.length > RECURRING_VISIBLE && (
        <TouchableOpacity style={[styles.more, styles.divider]} onPress={() => setExpanded(!expanded)}
          accessibilityRole="button" testID="tumes-recurring-more">
          <Text style={styles.moreText} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
            {expanded ? 'Ver menos' : `+${hidden} más`}
          </Text>
        </TouchableOpacity>
      )}
    </CardShell>
  );
}

/** Day 1 → last day; dots on expected days (a "2" when two share a day),
 *  hollow when passed; a tick for today on the current month. Labels only
 *  at the ends (15A). Decorative: the rows carry the same information. */
function DayTrack({ items, year, month, last, today, isCurrent }: {
  items: RecurringPayment[]; year: number; month: number; last: number; today: Date; isCurrent: boolean;
}) {
  const byDay = new Map<number, number>();
  items.forEach((i) => byDay.set(i.expectedDay, (byDay.get(i.expectedDay) ?? 0) + 1));
  const pos = (day: number) => `${((day - 1) / Math.max(1, last - 1)) * 100}%` as const;
  return (
    <View style={styles.track} importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
      <Text style={styles.trackEnd}>1</Text>
      <View style={styles.trackLine}>
        <View style={styles.trackRule} />
        {isCurrent && <View style={[styles.today, { left: pos(today.getDate()) }]} />}
        {[...byDay.entries()].map(([day, count]) => {
          const past = isPastDay(year, month, day, today);
          return (
            <View key={day} style={[styles.dot, past ? styles.dotPast : styles.dotNext, { left: pos(day) }]}>
              {count > 1 && <Text style={styles.dotBadge}>{count}</Text>}
            </View>
          );
        })}
      </View>
      <Text style={styles.trackEnd}>{last}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  track: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 },
  trackEnd: { fontSize: 11, color: colors.text.secondary, fontVariant: ['tabular-nums'] },
  trackLine: { flex: 1, height: 14, justifyContent: 'center' },
  trackRule: { height: 4, borderRadius: 2, backgroundColor: colors.border },
  today: { position: 'absolute', width: 1, height: 14, backgroundColor: colors.textFlat },
  dot: { position: 'absolute', width: 10, height: 10, borderRadius: 5, marginLeft: -5, alignItems: 'center', justifyContent: 'center' },
  dotNext: { backgroundColor: colors.flowOut.text },
  dotPast: { backgroundColor: colors.white, borderWidth: 1.5, borderColor: colors.text.light },
  dotBadge: { position: 'absolute', top: -11, fontSize: 8, fontWeight: '700', color: colors.textFlat },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 60, paddingVertical: 8 },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  avatar: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontSize: 15, fontWeight: '700' },
  body: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12 },
  bodyStacked: { flexDirection: 'column', alignItems: 'flex-start', gap: 4 },
  main: { flex: 1, flexShrink: 1 },
  name: { fontSize: 15, fontWeight: '600', color: colors.textFlat },
  caption: { fontSize: 13, color: colors.text.secondary, marginTop: 1 },
  end: { alignItems: 'flex-end', gap: 4, flexShrink: 0 },
  endStacked: { alignItems: 'flex-start', flexDirection: 'row', gap: 8 },
  amount: { fontSize: 15, fontWeight: '700', color: colors.textFlat, fontVariant: ['tabular-nums'] },
  pill: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 2, backgroundColor: colors.flowIn.chip },
  pillPast: { backgroundColor: colors.surface },
  pillText: { fontSize: 12, lineHeight: 16, fontWeight: '600', color: colors.flowIn.textSmall },
  pillTextPast: { color: colors.text.secondary },
  more: { minHeight: 44, justifyContent: 'center' },
  empty: { fontSize: 14, lineHeight: 20, color: colors.text.secondary },
  moreText: { fontSize: 15, fontWeight: '600', color: colors.flowIn.textSmall },
});
