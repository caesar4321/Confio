// "Tus acciones" — what the U.S. stocks did this month, under the dollar slot.
//
// The number is the month's result net of the user's own money:
// value now − value on the 1st − bought + sold, so a purchase never reads as
// a gain (the server computes it, users/cashflow_schema.py stockMonth). A
// down month is stated calmly in the text color, never red here: red days
// are honest on the stocks screen, Tu mes is the month's story. Facts only,
// never advice. Cents on the result (small months are the common case),
// whole dollars elsewhere, like Card B'.
import React, { useState } from 'react';
import { Modal, Pressable, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import type { StockMonth } from '../../apollo/monthSummary';
import { formatUsd, MASK, monthName, signedUsd } from '../../utils/monthSummary';
import { formatPercent, formatUsdAmount } from '../../utils/numberLocale';
import { CardShell, CardTitle, CARD_FONT_MULTIPLIER } from './CardShell';

type Props = {
  value: StockMonth;
  month: number;
  isCurrent: boolean;
  masked: boolean;
  onOpenStock: (ticker: string) => void;
  onOpenStocks: () => void;
};

/** "subió 8,2%" / "bajó 3%" / "se mantuvo" (under 0.05%). */
export function moverVerb(changePct: number): string {
  if (Math.abs(changePct) < 0.05) return 'se mantuvo';
  return `${changePct > 0 ? 'subió' : 'bajó'} ${formatPercent(Math.abs(changePct), 1)}%`;
}

export function StocksCard({ value, month, isCurrent, masked, onOpenStock, onOpenStocks }: Props) {
  const [sheet, setSheet] = useState(false);
  const exact = value.state === 'gain' && value.gainUsd !== null;
  const gain = Number(value.gainUsd);
  const pct = value.gainPct !== null ? Number(value.gainPct) : null;
  const bought = Number(value.boughtUsd ?? 0);
  const sold = Number(value.soldUsd ?? 0);
  const net = bought - sold;
  const valueText = masked ? MASK : formatUsd(value.valueUsd, { whole: true });
  const valueLabel = isCurrent ? 'Valen hoy' : `Valían al cierre de ${monthName(month)}`;

  const facts: string[] = [`${valueLabel} ${valueText}`];
  if (exact && Math.abs(net) >= 0.01) {
    const amount = masked ? MASK : formatUsd(Math.abs(net), { whole: true });
    facts.push(net > 0 ? `Pusiste ${amount}` : `Sacaste ${amount}`);
  }

  const a11y = masked
    ? 'Tus acciones. Montos ocultos.'
    : exact
      ? `Tus acciones ${gain >= 0 ? 'ganaron' : 'perdieron'} ${Math.abs(gain).toFixed(2)} dólares en ${monthName(month)}. ${facts.join('. ')}.`
      : `Tus acciones valen ${Math.round(Number(value.valueUsd))} dólares.`;

  return (
    <CardShell testID="tumes-stocks-card">
      <CardTitle icon="bar-chart-2" title="Tus acciones" />
      <TouchableOpacity onPress={onOpenStocks} accessibilityRole="button" accessibilityLabel={a11y}
        accessibilityHint="Abre tus acciones" testID="tumes-stocks-open">
        {exact ? (
          <View style={styles.resultRow}>
            <Text style={[styles.result, gain < 0 && styles.resultDown]} numberOfLines={1}
              maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-stocks-gain">
              {masked ? MASK : signedUsd(gain)}
            </Text>
            {!masked && pct !== null && (
              <Text style={styles.pct} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
                {pct < 0 ? '−' : '+'}{formatPercent(Math.abs(pct), 1)}%
              </Text>
            )}
          </View>
        ) : (
          <Text style={[styles.result, styles.resultDown]} numberOfLines={1}
            maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-stocks-value">
            {valueText}
          </Text>
        )}
        <Text style={styles.caption} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
          {exact ? `en ${monthName(month)} · ${facts.join(' · ')}` : 'valen hoy'}
        </Text>
      </TouchableOpacity>

      {value.topMover && (
        <TouchableOpacity style={styles.mover} onPress={() => onOpenStock(value.topMover!.ticker)}
          accessibilityRole="button" testID="tumes-stocks-mover">
          <Icon name={Number(value.topMover.changePct) < 0 ? 'trending-down' : 'trending-up'} size={16}
            color={colors.text.secondary} importantForAccessibility="no" />
          <Text style={styles.moverText} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
            <Text style={styles.moverTicker}>{value.topMover.ticker}</Text>
            {` ${moverVerb(Number(value.topMover.changePct))} en ${monthName(month)}`}
          </Text>
          <Icon name="chevron-right" size={16} color={colors.text.light} importantForAccessibility="no" />
        </TouchableOpacity>
      )}

      {exact ? (
        <TouchableOpacity onPress={() => setSheet(true)} accessibilityRole="button" style={styles.link}
          hitSlop={{ top: 12, bottom: 12, left: 4, right: 4 }} testID="tumes-stocks-how">
          <Text style={styles.linkText} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>¿Cómo lo calculamos?</Text>
        </TouchableOpacity>
      ) : (
        <Text style={styles.note} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-stocks-value-note">
          No tenemos el historial completo de tus acciones, así que no podemos calcular cuánto ganaron este mes.
        </Text>
      )}
      {exact && (
        <HowSheet visible={sheet} onClose={() => setSheet(false)} value={value} month={month}
          isCurrent={isCurrent} masked={masked} />
      )}
    </CardShell>
  );
}

function HowSheet({ visible, onClose, value, month, isCurrent, masked }: {
  visible: boolean; onClose: () => void; value: StockMonth; month: number; isCurrent: boolean; masked: boolean;
}) {
  const usd = (v: string | null, sign = '') => (masked ? MASK : `${sign}${formatUsdAmount(Number(v ?? 0), { decimals: 2 })}`);
  const rows: [string, string][] = [
    [`Valían el 1 de ${monthName(month)}`, usd(value.valueStartUsd)],
    ['Compraste', usd(value.boughtUsd, '+ ')],
    ['Vendiste', usd(value.soldUsd, '− ')],
    [isCurrent ? 'Valen hoy' : `Valían al cierre de ${monthName(month)}`, usd(value.valueUsd)],
    ['Resultado del mes', masked ? MASK : signedUsd(Number(value.gainUsd))],
  ];
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.scrim} onPress={onClose} accessibilityLabel="Cerrar" />
      <View style={styles.sheet} testID="tumes-stocks-how-sheet">
        <View style={styles.handle} />
        <Text style={styles.sheetTitle} accessibilityRole="header">¿Cómo lo calculamos?</Text>
        {rows.map(([label, v], i) => (
          <View key={label} style={[styles.sheetRow, i > 0 && styles.sheetDivider, i === rows.length - 1 && styles.sheetTotal]}
            accessible accessibilityLabel={`${label}: ${v}`}>
            <Text style={styles.sheetLabel}>{label}</Text>
            <Text style={styles.sheetValue}>{v}</Text>
          </View>
        ))}
        <Text style={styles.sheetBody}>
          Al valor de hoy le restamos lo que valían el 1 y lo que compraste, y le sumamos lo que vendiste: así, poner
          dinero no cuenta como ganancia. Las compras incluyen el costo de operación. Usamos los precios de Ondo; los
          dividendos ya están en el precio.
        </Text>
        <TouchableOpacity style={styles.cta} onPress={onClose} accessibilityRole="button">
          <Text style={styles.ctaText}>Entendido</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  resultRow: { flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  result: { fontSize: 28, lineHeight: 34, fontWeight: '700', color: colors.flowIn.text, fontVariant: ['tabular-nums'], flexShrink: 1 },
  resultDown: { color: colors.textFlat },
  pct: { fontSize: 15, fontWeight: '600', color: colors.text.secondary, fontVariant: ['tabular-nums'] },
  caption: { fontSize: 13, lineHeight: 18, color: colors.text.secondary, marginTop: 6, fontVariant: ['tabular-nums'] },
  mover: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44, marginTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  moverText: { flex: 1, fontSize: 14, color: colors.textFlat },
  moverTicker: { fontWeight: '700' },
  note: { fontSize: 13, lineHeight: 18, color: colors.text.secondary, marginTop: 10 },
  link: { marginTop: 10, minHeight: 32, justifyContent: 'center', alignSelf: 'flex-start' },
  linkText: { fontSize: 13, fontWeight: '600', color: colors.flowIn.textSmall },
  scrim: { flex: 1, backgroundColor: 'rgba(17,24,39,0.4)' },
  sheet: { backgroundColor: colors.white, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 20, paddingBottom: 32 },
  handle: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, marginBottom: 16 },
  sheetTitle: { fontSize: 20, fontWeight: '700', color: colors.textFlat, marginBottom: 8 },
  sheetRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, paddingVertical: 12 },
  sheetDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  sheetTotal: { borderTopWidth: 1, borderTopColor: colors.textFlat },
  sheetLabel: { fontSize: 15, color: colors.textFlat, flexShrink: 1 },
  sheetValue: { fontSize: 15, fontWeight: '600', color: colors.textFlat, fontVariant: ['tabular-nums'] },
  sheetBody: { fontSize: 14, lineHeight: 20, color: colors.text.secondary, marginTop: 8 },
  cta: { marginTop: 20, minHeight: 48, borderRadius: 14, backgroundColor: colors.primaryDark, alignItems: 'center', justifyContent: 'center' },
  ctaText: { fontSize: 16, fontWeight: '700', color: colors.white },
});
