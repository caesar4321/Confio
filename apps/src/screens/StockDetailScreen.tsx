// Stock detail — price, range-selector chart, and the buy/sell entry.
//
// The chart uses react-native-svg (house rule: no linear-gradient lib) and
// renders REAL series only: gmOhlc closes for the selected range (1D–MAX),
// with gmMarket.sparkline24h standing in on 1D until candles arrive. Buying
// draws from cUSD+ (sweep model) — the funding line under the CTAs says so
// explicitly, and the total-return note explains why there is no dividends tab.

import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  Image,
} from 'react-native';
import Svg, { Polyline } from 'react-native-svg';
import { Header } from '../navigation/Header';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { useNumberFormat } from '../utils/numberFormatting';
import {
  useGmMarket,
  useGmOhlc,
  sparklineFor,
  GM_RANGES,
  GmRange,
} from '../hooks/useGmMarket';
import { TickerLogo } from '../components/TickerLogo';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';
import { useAhorrosPortfolio } from '../hooks/useAhorrosPortfolio';

type NavProp = NativeStackNavigationProp<MainStackParamList>;
type DetailRoute = RouteProp<MainStackParamList, 'StockDetail'>;

const CHART_W = 320;
const CHART_H = 110;

export const StockDetailScreen = () => {
  const navigation = useNavigation<NavProp>();
  const route = useRoute<DetailRoute>();
  const { formatNumber } = useNumberFormat();
  const { byTicker, tradabilityFor } = useGmMarket();
  const { savings, stocks: stockHoldings } = useAhorrosPortfolio();

  const stock = byTicker(route.params.ticker);
  const position = stockHoldings.positions.find((p) => p.ticker === route.params.ticker);

  const [range, setRange] = useState<GmRange>('1D');
  const { closes } = useGmOhlc(stock?.symbol, range);

  // Range chart from gmOhlc closes. On 1D the market sparkline stands in
  // until candles arrive (same real data source, coarser); deterministic
  // fallback only when the asset ships without any history (cosmetic,
  // never a price display).
  const series = useMemo(() => {
    if (!stock) return [];
    if (closes.length >= 2) return closes;
    if (range !== '1D') return [];
    return stock.sparkline24h && stock.sparkline24h.length >= 2
      ? stock.sparkline24h
      : sparklineFor(stock.ticker);
  }, [stock, closes, range]);

  const points = useMemo(() => {
    if (series.length < 2) return '';
    const min = Math.min(...series);
    const max = Math.max(...series);
    const span = max - min || 1;
    return series
      .map((v, i) => {
        const x = (i / (series.length - 1)) * CHART_W;
        const y = CHART_H - ((v - min) / span) * (CHART_H - 10) - 5;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }, [series]);

  if (!stock) {
    return (
      <View style={[styles.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <Text style={{ color: colors.text.secondary }}>Acción no encontrada</Text>
        <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginTop: 16 }}>
          <Text style={{ color: colors.primaryDark, fontWeight: '600' }}>Volver</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const up = stock.dayChangePct >= 0;
  // The stroke follows the SELECTED range (a green 1Y over a red day would
  // lie); the "hoy" line above stays the 24h change by market convention.
  const chartUp = series.length >= 2 ? series[series.length - 1] >= series[0] : up;
  const tradability = tradabilityFor(stock);
  const fmtUsd = (v: number) =>
    `$${formatNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const onComprar = () => navigation.navigate('BuyStock', { ticker: stock.ticker });
  const onVender = () => navigation.navigate('SellStock', { ticker: stock.ticker });

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <Header
        navigation={navigation as any}
        title={stock.ticker}
        subtitle={stock.name}
        titleAccessory={<TickerLogo ticker={stock.ticker} color={stock.color} logoUrl={stock.logoUrl} size={30} />}
        backgroundColor={colors.primary}
        isLight
        showBackButton
      />

      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        {/* Price + chart */}
        <View style={styles.card}>
          <Text style={styles.price}>{fmtUsd(stock.priceUsd)}</Text>
          <Text style={[styles.change, !up && styles.changeDown]}>
            {up ? '▲' : '▼'} {formatNumber(Math.abs(stock.dayChangePct), { maximumFractionDigits: 2 })}% hoy
          </Text>
          <View style={styles.chartWrap}>
            <Svg width="100%" height={CHART_H} viewBox={`0 0 ${CHART_W} ${CHART_H}`}>
              <Polyline
                points={points}
                fill="none"
                stroke={chartUp ? '#059669' : '#DC2626'}
                strokeWidth="2.5"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            </Svg>
          </View>
          <View style={styles.rangeRow}>
            {GM_RANGES.map((r) => (
              <TouchableOpacity
                key={r}
                style={[styles.rangePill, range === r && styles.rangePillActive]}
                onPress={() => setRange(r)}
                activeOpacity={0.7}
              >
                <Text style={[styles.rangeText, range === r && styles.rangeTextActive]}>
                  {r === 'MAX' ? 'Máx' : r}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          <View style={styles.marketRow}>
            <View
              style={[
                styles.marketDot,
                { backgroundColor: tradability === 'closed' ? '#9CA3AF' : '#10B981' },
              ]}
            />
            <Text style={styles.marketText}>
              {tradability === 'open' && 'Operando ahora'}
              {tradability === 'reduced' &&
                'Sesión extendida — el costo puede ser un poco mayor'}
              {tradability === 'closed' &&
                'Opera de dom. 8pm a vie. 8pm (hora NY) — vuelve pronto'}
            </Text>
          </View>
        </View>

        {/* Position (only when holding) */}
        {position && (
          <View style={styles.card}>
            <Text style={styles.sectionLabel}>Tu posición</Text>
            <View style={styles.positionRow}>
              <Text style={styles.positionValue}>{fmtUsd(position.valueUsd)}</Text>
              <Text
                style={[styles.change, position.dayChangePct < 0 && styles.changeDown]}
              >
                {position.dayChangePct >= 0 ? '+' : ''}
                {formatNumber(position.dayChangePct, { maximumFractionDigits: 2 })}% hoy
              </Text>
            </View>
          </View>
        )}

        {/* CTAs + funding line (sweep model made visible) */}
        <View style={styles.ctaRow}>
          <TouchableOpacity
            style={[styles.ctaBuy, tradability === 'closed' && styles.ctaDisabled]}
            onPress={onComprar}
            disabled={tradability === 'closed'}
            activeOpacity={0.85}
          >
            <Text style={styles.ctaBuyText}>Comprar</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.ctaSell, (!position || tradability === 'closed') && styles.ctaDisabled]}
            onPress={onVender}
            disabled={!position || tradability === 'closed'}
            activeOpacity={0.85}
          >
            <Text style={[styles.ctaSellText, !position && styles.ctaDisabledText]}>Vender</Text>
          </TouchableOpacity>
        </View>
        {/* Funding instrument, payment-method style (sweep model at a
            glance): stocks trade against your savings, amounts stay in $. */}
        <View style={styles.fundingSource}>
          <Image source={cUSDPlusLogo} style={styles.fundingLogo} />
          <View style={{ flex: 1 }}>
            <Text style={styles.fundingTitle}>Se compra y se vende con tu ahorro</Text>
            <Text style={styles.fundingSub}>
              Confío Dollar+ · ${formatNumber(savings.balanceUsd, { maximumFractionDigits: 2 })}{' '}
              disponibles · gana rendimiento hasta el momento de la compra
            </Text>
          </View>
        </View>

        {/* How it works */}
        <View style={styles.card}>
          <Text style={styles.sectionLabel}>Cómo funciona</Text>
          {[
            {
              icon: 'repeat',
              text: 'Dividendos reinvertidos automáticamente — el valor del token los incluye.',
            },
            {
              icon: 'shield',
              text: 'Respaldada 1:1 por acciones reales en custodios regulados de EE.UU. (Ondo Finance).',
            },
            {
              icon: 'clock',
              text: 'Compra y vende desde $1, sin abrir cuenta en EE.UU.',
            },
          ].map((r) => (
            <View key={r.icon} style={styles.howRow}>
              <Icon name={r.icon} size={16} color={colors.primaryDark} />
              <Text style={styles.howText}>{r.text}</Text>
            </View>
          ))}
        </View>

        <Text style={styles.footerDisclaimer}>
          Las acciones pueden subir o bajar de valor. Precios con demora fuera del horario de
          mercado. No es asesoría financiera.
        </Text>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },


  scrollContent: { padding: 16, paddingBottom: 40 },

  card: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    marginBottom: 14,
  },
  price: { fontSize: 34, fontWeight: 'bold', color: colors.text.primary },
  change: { fontSize: 14, fontWeight: '700', color: colors.primaryDark, marginTop: 3 },
  changeDown: { color: '#DC2626' },
  chartWrap: { marginTop: 14 },
  rangeRow: { flexDirection: 'row', gap: 6, marginTop: 10 },
  rangePill: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 6,
    borderRadius: 8,
  },
  rangePillActive: { backgroundColor: colors.primaryLight },
  rangeText: { fontSize: 12, fontWeight: '600', color: colors.text.secondary },
  rangeTextActive: { color: colors.primaryDark },
  marketRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 12 },
  marketDot: { width: 7, height: 7, borderRadius: 4 },
  marketText: { fontSize: 12, color: colors.text.secondary },

  sectionLabel: { fontSize: 13, fontWeight: '700', color: colors.text.secondary, marginBottom: 10 },
  positionRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  positionValue: { fontSize: 22, fontWeight: 'bold', color: colors.text.primary },

  ctaRow: { flexDirection: 'row', gap: 10, marginBottom: 10 },
  ctaBuy: {
    flex: 1,
    alignItems: 'center',
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 14,
  },
  ctaBuyText: { color: '#fff', fontSize: 15, fontWeight: '700' },
  ctaSell: {
    flex: 1,
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 12,
    paddingVertical: 14,
    borderWidth: 1.5,
    borderColor: colors.primaryDark,
  },
  ctaSellText: { color: colors.primaryDark, fontSize: 15, fontWeight: '700' },
  ctaDisabled: { opacity: 0.45, borderColor: colors.text.light },
  ctaDisabledText: { color: colors.text.light },
  fundingSource: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 12,
    marginBottom: 16,
  },
  fundingLogo: { width: 30, height: 30, borderRadius: 15 },
  fundingTitle: { fontSize: 13, fontWeight: '700', color: colors.text.primary },
  fundingSub: { fontSize: 12, color: colors.text.secondary, marginTop: 1 },

  howRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', marginBottom: 10 },
  howText: { flex: 1, fontSize: 13, color: colors.text.secondary, lineHeight: 18 },

  footerDisclaimer: {
    fontSize: 11,
    color: colors.text.light,
    textAlign: 'center',
    lineHeight: 16,
    paddingHorizontal: 8,
  },
});
