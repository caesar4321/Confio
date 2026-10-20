// "Oro y Bitcoin" — what the crypto & gold did this month, under "Tus acciones".
//
// The twin of StocksCard (same layout, rules and arithmetic): the month's
// result net of the user's own money, value now − value on the 1st − bought
// + sold, so a purchase never reads as a gain (the server computes it,
// users/cashflow_schema.py cryptoMonth). One row per asset held (Bitcoin,
// Oro) with how its price moved. A down month is calm, never red here.
// Facts only, never advice.
import React, { useState } from 'react';
import { TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import type { CryptoMonth } from '../../apollo/monthSummary';
import { formatUsd, MASK, monthName, signedUsd } from '../../utils/monthSummary';
import { formatPercent } from '../../utils/numberLocale';
import { CardShell, CardTitle, CARD_FONT_MULTIPLIER } from './CardShell';
import { HowSheet, investCardStyles as styles, moverIcon, moverVerb } from './StocksCard';
import { CryptoAssetMark } from '../CryptoAssetMark';

/** The settling note follows how long confirmation has taken (the screen polls). */
const SETTLING_NOTE = {
  fast: 'Tu última compra o venta se está confirmando. En unos segundos verás el resultado del mes.',
  slow: 'Tu última compra o venta está tardando más de lo normal en confirmarse. Seguimos revisando.',
  stalled: 'Tu última compra o venta aún no se confirma. Vuelve más tarde para ver el resultado del mes.',
} as const;

const TITLE = 'Oro y Bitcoin';

type Props = {
  /** Only read while state is 'settling'. */
  settlingPhase?: keyof typeof SETTLING_NOTE;
  value: CryptoMonth;
  month: number;
  isCurrent: boolean;
  masked: boolean;
  onOpenAsset: (symbol: string) => void;
  onOpenAll: () => void;
};

export function CryptoCard({ value, month, isCurrent, masked, settlingPhase = 'fast', onOpenAsset, onOpenAll }: Props) {
  const [sheet, setSheet] = useState(false);
  const exact = value.state === 'gain' && value.gainUsd !== null;
  const gain = Number(value.gainUsd);
  const pct = value.gainPct !== null ? Number(value.gainPct) : null;
  const net = Number(value.boughtUsd ?? 0) - Number(value.soldUsd ?? 0);
  const valueText = masked ? MASK : formatUsd(value.valueUsd, { whole: true });
  const valueLabel = isCurrent ? 'Valen hoy' : `Valían al cierre de ${monthName(month)}`;
  // A first purchase on the wire the scan doesn't show yet: its value is not
  // US$0 but unknown, so no number until it settles (seconds).
  const valueUnknown = value.state === 'settling' && value.holdings === 0;

  const facts: string[] = [`${valueLabel} ${valueText}`];
  if (exact && Math.abs(net) >= 0.01) {
    const amount = masked ? MASK : formatUsd(Math.abs(net), { whole: true });
    facts.push(net > 0 ? `Pusiste ${amount}` : `Sacaste ${amount}`);
  }

  const a11y = masked
    ? `${TITLE}. Montos ocultos.`
    : exact
      ? `Tu oro y bitcoin ${gain >= 0 ? 'ganaron' : 'perdieron'} ${Math.abs(gain).toFixed(2)} dólares en ${monthName(month)}. ${facts.join('. ')}.`
      : valueUnknown
        ? `${TITLE}. Tu última compra o venta se está confirmando.`
        // Same precision as the number on screen: under US$1 keeps its cents.
        : `Tu oro y bitcoin valen ${Math.abs(Number(value.valueUsd)) >= 1 || Number(value.valueUsd) === 0
          ? Math.round(Number(value.valueUsd)) : Number(value.valueUsd).toFixed(2)} dólares.`;

  return (
    <CardShell testID="tumes-crypto-card">
      <CardTitle icon="pie-chart" title={TITLE} />
      <TouchableOpacity onPress={onOpenAll} accessibilityRole="button" accessibilityLabel={a11y}
        accessibilityHint="Abre oro y bitcoin" testID="tumes-crypto-open">
        {exact ? (
          <View style={styles.resultRow}>
            <Text style={[styles.result, gain < 0 && styles.resultDown]} numberOfLines={1}
              maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-crypto-gain">
              {masked ? MASK : signedUsd(gain)}
            </Text>
            {!masked && pct !== null && (
              <Text style={styles.pct} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
                {gain < 0 ? '−' : '+'}{formatPercent(Math.abs(pct), 1)}%
              </Text>
            )}
          </View>
        ) : !valueUnknown && (
          <Text style={[styles.result, styles.resultDown]} numberOfLines={1}
            maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-crypto-value">
            {valueText}
          </Text>
        )}
        {!valueUnknown && (
          <Text style={styles.caption} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
            {exact ? `en ${monthName(month)} · ${facts.join(' · ')}` : 'valen hoy'}
          </Text>
        )}
      </TouchableOpacity>

      {value.assets.map((asset) => (
        <TouchableOpacity key={asset.symbol} style={styles.mover} onPress={() => onOpenAsset(asset.symbol)}
          accessibilityRole="button" testID={`tumes-crypto-asset-${asset.symbol}`}>
          <CryptoAssetMark ticker={asset.ticker} category={asset.category} size={20} />
          <Text style={styles.moverText} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>
            <Text style={styles.moverTicker}>{asset.name}</Text>
            {asset.changePct !== null ? ` ${moverVerb(Number(asset.changePct))} en ${monthName(month)}` : ''}
          </Text>
          {asset.changePct !== null && (
            <Icon name={moverIcon(Number(asset.changePct))} size={16} color={colors.text.secondary}
              importantForAccessibility="no" />
          )}
          <Icon name="chevron-right" size={16} color={colors.text.light} importantForAccessibility="no" />
        </TouchableOpacity>
      ))}

      {exact ? (
        <TouchableOpacity onPress={() => setSheet(true)} accessibilityRole="button" style={styles.link}
          hitSlop={{ top: 12, bottom: 12, left: 4, right: 4 }} testID="tumes-crypto-how">
          <Text style={styles.linkText} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER}>¿Cómo lo calculamos?</Text>
        </TouchableOpacity>
      ) : value.state === 'settling' ? (
        <Text style={styles.note} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-crypto-settling-note">
          {SETTLING_NOTE[settlingPhase]}
        </Text>
      ) : (
        <Text style={styles.note} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} testID="tumes-crypto-value-note">
          No tenemos el historial completo de tu oro y bitcoin, así que no podemos calcular cuánto ganaron este mes.
        </Text>
      )}
      {exact && (
        <HowSheet visible={sheet} onClose={() => setSheet(false)} value={value} month={month}
          isCurrent={isCurrent} masked={masked} testID="tumes-crypto-how-sheet"
          body={`${isCurrent ? 'Al valor de hoy' : `Al valor al cierre de ${monthName(month)}`} le restamos lo que valían el 1 y lo que compraste, y le sumamos lo que vendiste: así, poner dinero no cuenta como ganancia. Las compras incluyen el costo de operación y las ventas ya lo descuentan. ${isCurrent ? 'Hoy usamos el precio al que puedes comprar en Confío; para' : 'Para'} el inicio${isCurrent ? '' : ' y el cierre'} del mes, el cierre diario del mercado.`} />
      )}
    </CardShell>
  );
}
