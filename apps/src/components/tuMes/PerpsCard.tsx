// "Futuros" — what the member's Futuros did this month, under "Oro y Bitcoin".
//
// The twin of CryptoCard, in the member's own money: value now − value on
// the 1st − margin put in + dollars back (the server computes it,
// users/cashflow_schema.py perpsMonth). Margin, never the leveraged size: a
// 10x position on US$100 moved US$100 of the member's money, so that is what
// "Pusiste" says. A down month is calm, never red here. Facts only.
import React, { useState } from 'react';
import { TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import type { PerpsMonth } from '../../apollo/monthSummary';
import { formatUsd, MASK, monthName, signedUsd } from '../../utils/monthSummary';
import { formatPercent } from '../../utils/numberLocale';
import { CardShell, CardTitle, CARD_FONT_MULTIPLIER } from './CardShell';
import { HowSheet, investCardStyles as styles } from './StocksCard';
import FuturesMark from '../svg/FuturesMark';

/** Money between Confío and Futuros takes minutes, not seconds (a bridge). */
const SETTLING_NOTE = {
  fast: 'Tu dinero va en camino entre Confío y Futuros. En unos minutos verás el resultado del mes.',
  slow: 'Tu dinero entre Confío y Futuros está tardando más de lo normal. Seguimos revisando.',
  stalled: 'Tu dinero entre Confío y Futuros aún no llega. Vuelve más tarde para ver el resultado del mes.',
} as const;

const TITLE = 'Futuros';

type Props = {
  /** Only read while state is 'settling'. */
  settlingPhase?: keyof typeof SETTLING_NOTE;
  value: PerpsMonth;
  month: number;
  isCurrent: boolean;
  masked: boolean;
  onOpen: () => void;
};

export function PerpsCard({ value, month, isCurrent, masked, settlingPhase = 'fast', onOpen }: Props) {
  const [sheet, setSheet] = useState(false);
  const exact = value.state === 'gain' && value.gainUsd !== null;
  const gain = Number(value.gainUsd);
  const pct = value.gainPct !== null ? Number(value.gainPct) : null;
  const marginIn = Number(value.marginInUsd ?? 0);
  const back = Number(value.returnedUsd ?? 0);
  const valueText = masked ? MASK : formatUsd(value.valueUsd, { whole: true });
  const valueLabel = isCurrent ? 'Vale hoy' : `Valía al cierre de ${monthName(month)}`;

  const facts: string[] = [];
  if (exact && Number(value.valueUsd) > 0) facts.push(`${valueLabel} ${valueText}`);
  // Each movement as it was (never netted: US$100 in and US$110 back is not "US$10 back").
  const amount = (v: number) => (masked ? MASK : formatUsd(v, { whole: true }));
  if (exact && marginIn >= 0.01) facts.push(`Pusiste ${amount(marginIn)} de margen`);
  if (exact && back >= 0.01) facts.push(`Volvieron ${amount(back)}`);
  const caption = facts.length ? `en ${monthName(month)} · ${facts.join(' · ')}` : `en ${monthName(month)}`;
  const open = value.positions;

  const a11y = masked
    ? `${TITLE}. Montos ocultos.`
    : exact
      ? `Tus futuros ${gain >= 0 ? 'ganaron' : 'perdieron'} ${Math.abs(gain).toFixed(2)} dólares en ${monthName(month)}. ${facts.join('. ')}.`
      : `${TITLE}. Tu dinero va en camino.`;

  return (
    <CardShell testID="tumes-perps-card">
      <CardTitle icon="activity" title={TITLE} />
      <TouchableOpacity onPress={onOpen} accessibilityRole="button" accessibilityLabel={a11y}
        accessibilityHint="Abre Futuros" testID="tumes-perps-open">
        {exact && (
          <>
            <View style={styles.resultRow}>
              <Text style={[styles.result, gain < 0 && styles.resultDown]} numberOfLines={1}
                maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-perps-gain">
                {masked ? MASK : signedUsd(gain)}
              </Text>
              {!masked && pct !== null && (
                <Text style={styles.pct} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
                  {gain < 0 ? '−' : '+'}{formatPercent(Math.abs(pct), 1)}%
                </Text>
              )}
            </View>
            <Text style={styles.caption} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-perps-caption">
              {caption}
            </Text>
          </>
        )}
      </TouchableOpacity>

      {exact && open > 0 && (
        <TouchableOpacity style={styles.mover} onPress={onOpen} accessibilityRole="button" testID="tumes-perps-positions">
          <FuturesMark size={20} />
          <Text style={styles.moverText} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
            <Text style={styles.moverTicker}>{open === 1 ? '1 posición' : `${open} posiciones`}</Text>
            {isCurrent ? ' abierta' + (open === 1 ? '' : 's') : ` al cierre de ${monthName(month)}`}
          </Text>
          <Icon name="chevron-right" size={16} color={colors.text.light} importantForAccessibility="no" />
        </TouchableOpacity>
      )}

      {exact ? (
        <TouchableOpacity onPress={() => setSheet(true)} accessibilityRole="button" style={styles.link}
          hitSlop={{ top: 12, bottom: 12, left: 4, right: 4 }} testID="tumes-perps-how">
          <Text style={styles.linkText} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>¿Cómo lo calculamos?</Text>
        </TouchableOpacity>
      ) : (
        <Text style={styles.note} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-perps-settling-note">
          {SETTLING_NOTE[settlingPhase]}
        </Text>
      )}
      {exact && (
        <HowSheet visible={sheet} onClose={() => setSheet(false)} month={month}
          isCurrent={isCurrent} masked={masked} testID="tumes-perps-how-sheet"
          inLabel="Margen que pusiste" outLabel="Volvió a tu cuenta"
          value={{ valueUsd: value.valueUsd, valueStartUsd: value.valueStartUsd, boughtUsd: value.marginInUsd,
            soldUsd: value.returnedUsd, gainUsd: value.gainUsd }}
          body={`${isCurrent ? 'Al valor de hoy' : `Al valor al cierre de ${monthName(month)}`} le restamos lo que valía el 1 y el margen que pusiste, y le sumamos lo que volvió a tu cuenta: así, poner dinero no cuenta como ganancia. Contamos tu dinero, el margen, nunca el tamaño apalancado: una posición 10x con US$100 movió US$100. El margen incluye el costo de operación y lo que volvió ya lo descuenta. ${isCurrent ? 'Hoy usamos el precio de mercado de Hyperliquid; para' : 'Para'} el inicio${isCurrent ? '' : ' y el cierre'} del mes, el cierre diario.`} />
      )}
    </CardShell>
  );
}
