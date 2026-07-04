// Stock detail — price, sparkline, and the buy/sell entry.
//
// The chart uses react-native-svg (house rule: no linear-gradient lib) with
// stub OHLC data until the GM API proxy lands. Buying draws from cUSD+
// (sweep model) — the funding line under the CTAs says so explicitly, and
// the total-return note explains why there is no dividends tab.

import React, { useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  Alert,
} from 'react-native';
import Svg, { Polyline } from 'react-native-svg';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { useNumberFormat } from '../utils/numberFormatting';
import { useGmMarket, sparklineFor } from '../hooks/useGmMarket';
import { TickerLogo } from '../components/TickerLogo';
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

  const points = useMemo(() => {
    if (!stock) return '';
    const series = sparklineFor(stock.ticker);
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
  }, [stock]);

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
  const tradability = tradabilityFor(stock);
  const fmtUsd = (v: number) =>
    `$${formatNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const onComprar = () => {
    // TODO(gm): buy flow — USD amount from cUSD+ (sweep) → RFQ/attestation
    // quote preview → confirm → atomic settle. Clone of the Convert pattern.
    Alert.alert('Muy pronto', 'La compra de acciones abre en breve.');
  };

  const onVender = () => {
    // TODO(gm): sell flow — proceeds land back in cUSD+ and keep earning.
    Alert.alert('Muy pronto', 'La venta de acciones abre en breve.');
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
            <TickerLogo ticker={stock.ticker} color={stock.color} logoUrl={stock.logoUrl} size={30} />
            <View style={{ alignItems: 'center' }}>
              <Text style={styles.headerTitle}>{stock.ticker}</Text>
              <Text style={styles.headerSubtitle}>{stock.name}</Text>
            </View>
          </View>
          <View style={styles.headerIconBtn} />
        </View>
      </SafeAreaView>

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
                stroke={up ? '#059669' : '#DC2626'}
                strokeWidth="2.5"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            </Svg>
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
        <Text style={styles.fundingLine}>
          Se compra con tu ahorro: ${formatNumber(savings.balanceUsd, { maximumFractionDigits: 2 })}{' '}
          disponibles en cUSD+ — tu dinero gana rendimiento hasta el momento de la compra.
        </Text>

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

  header: {
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },
  headerSubtitle: { fontSize: 12, color: '#fff', opacity: 0.85, marginTop: 1 },

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
  fundingLine: {
    fontSize: 12,
    color: colors.text.secondary,
    lineHeight: 17,
    marginBottom: 14,
    paddingHorizontal: 4,
  },

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
