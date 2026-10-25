// Bitcoin & gold detail — price, 24h sparkline, position, who backs it, and
// the buy/sell entry.
//
// Same grammar as StockDetailScreen, simpler: these trade 24/7 on
// PancakeSwap, so there is no market-hours line. The chart has the stock
// range selector (1H–MAX, cryptoOhlc); on 1D the server's 24h sparkline
// stands in until candles arrive. The funding line names the Confío dollar the
// person actually holds (cUSD+ if Ondo-eligible, otherwise cUSD).

import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StatusBar,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import Svg, { Polyline } from 'react-native-svg';
import Icon from 'react-native-vector-icons/Feather';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';

import { Text } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { CryptoAssetMark } from '../components/CryptoAssetMark';
import { colors } from '../config/theme';
import { CRYPTO_TRADING_UI_ENABLED } from '../config/features';
import { useCryptoCapabilities, useCryptoHoldings, useCryptoMarket, useCryptoOhlc } from '../hooks/useCrypto';
import { GM_RANGES, GM_RANGE_ACCESSIBILITY_LABELS, GmRange } from '../hooks/useGmMarket';
import { fromBaseUnits } from '../services/cryptoSwapMath';
import { MainStackParamList } from '../types/navigation';
import { useNumberFormat } from '../utils/numberFormatting';
import {
  custodyNote,
  feePctLabel,
  formatUnits,
  formatUsdPrice,
  fundingDollarName,
} from '../utils/cryptoPresentation';

type NavProp = NativeStackNavigationProp<MainStackParamList>;
type DetailRoute = RouteProp<MainStackParamList, 'CryptoDetail'>;

const CHART_W = 320;
const CHART_H = 110;

export const CryptoDetailScreen = () => {
  const navigation = useNavigation<NavProp>();
  const route = useRoute<DetailRoute>();
  const { formatNumber } = useNumberFormat();
  const { capabilities, loading: capsLoading } = useCryptoCapabilities();
  const enabled = Boolean(capabilities?.enabled);
  const { bySymbol, loading: marketLoading } = useCryptoMarket(enabled);
  const { holdings, loading: holdingsLoading } = useCryptoHoldings();

  const listedAsset = bySymbol(route.params.symbol);
  const position = (holdings ?? []).find((h) => h.symbol === route.params.symbol);
  // A holding carries what a sale needs: a blocked-country or delisted
  // holder sees their position and Vender without the catalog.
  const asset = listedAsset ?? (position ? {
    symbol: position.symbol,
    ticker: position.ticker,
    name: position.name,
    category: position.category,
    custody: position.custody,
    priceUsd: null as number | null,
    dayChangePct: null as number | null,
    sparkline24h: null as number[] | null,
  } : undefined);
  const holds = (() => {
    try {
      return Boolean(position) && BigInt(position!.units || '0') > 0n;
    } catch {
      return false;
    }
  })();

  const [range, setRange] = useState<GmRange>('1D');
  const { closes, loading: chartLoading, failed: chartFailed } = useCryptoOhlc(
    route.params.symbol, range, Boolean(asset));
  const series = useMemo(() => {
    if (closes.length >= 2) return closes;
    if (range !== '1D' || chartFailed) return [];
    return asset?.sparkline24h ?? [];
  }, [closes, range, chartFailed, asset?.sparkline24h]);
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

  if (!asset && (capsLoading || holdingsLoading || (enabled && marketLoading))) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.primaryDark} />
      </View>
    );
  }

  if (!asset) {
    return (
      <View style={[styles.container, styles.center]}>
        <Text style={styles.unavailable}>
          {capabilities?.blockedMessage || 'Oro y bitcoin no están disponibles para tu cuenta.'}
        </Text>
        <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginTop: 16 }}>
          <Text style={styles.back}>Volver</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const change = asset.dayChangePct;
  const up = (change ?? 0) >= 0;
  const chartUp = series.length >= 2 ? series[series.length - 1] >= series[0] : up;
  const funding = fundingDollarName(capabilities?.fundingDollar);
  const tradingOn = CRYPTO_TRADING_UI_ENABLED && Boolean(capabilities?.tradingEnabled);
  // Comprar only for a listed asset the person may buy; Vender always for a holding.
  const canBuy = tradingOn && enabled && Boolean(capabilities?.buyEnabled)
    && Boolean(listedAsset) && position?.listed !== false;
  const custody = custodyNote(asset.custody);
  const feeBps = capabilities?.feeBps ?? null;

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
      <Header
        navigation={navigation as any}
        title={asset.name}
        subtitle={asset.ticker}
        titleAccessory={<CryptoAssetMark ticker={asset.ticker} category={asset.category} size={30} />}
        backgroundColor={colors.heroField}
        isLight
        showBackButton
      />

      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <View style={styles.card}>
          <Text style={styles.price}>
            {formatUsdPrice(asset.priceUsd ?? (position?.valueUsd != null && holds
              ? position.valueUsd / fromBaseUnits(position.units, position.decimals)
              : null))}
          </Text>
          {change != null ? (
            <Text style={[styles.change, !up && styles.changeDown]}>
              {up ? '▲' : '▼'} {formatNumber(Math.abs(change), { maximumFractionDigits: 2 })}% en 24 h
            </Text>
          ) : null}
          <View style={styles.chartWrap}>
            {points ? (
              <Svg width="100%" height={CHART_H} viewBox={`0 0 ${CHART_W} ${CHART_H}`} testID="crypto-sparkline">
                <Polyline
                  points={points}
                  fill="none"
                  stroke={chartUp ? '#059669' : '#DC2626'}
                  strokeWidth="2.5"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              </Svg>
            ) : (
              <View style={styles.chartEmpty}>
                <Text style={styles.chartEmptyText}>
                  {chartLoading
                    ? 'Cargando gráfico…'
                    : chartFailed
                      ? 'No se pudo cargar el gráfico'
                      : 'Aún no hay suficientes datos'}
                </Text>
              </View>
            )}
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rangeRow}>
            {GM_RANGES.map((r) => (
              <TouchableOpacity
                key={r}
                style={[styles.rangePill, range === r && styles.rangePillActive]}
                onPress={() => setRange(r)}
                activeOpacity={0.7}
                accessibilityRole="button"
                accessibilityLabel={GM_RANGE_ACCESSIBILITY_LABELS[r]}
                accessibilityState={{ selected: range === r }}
              >
                <Text style={[styles.rangeText, range === r && styles.rangeTextActive]}>
                  {r === 'MAX' ? 'Máx' : r}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
          <View style={styles.marketRow}>
            <View style={styles.marketDot} />
            <Text style={styles.marketText}>Opera 24/7</Text>
          </View>
        </View>

        {holds && position && (
          <View style={styles.card}>
            <Text style={styles.sectionLabel}>Tu inversión</Text>
            <View style={styles.positionRow}>
              <Text style={styles.positionValue}>
                {position.valueUsd != null
                  ? `$${formatNumber(position.valueUsd, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                  : '—'}
              </Text>
              <Text style={styles.positionUnits}>
                {formatUnits(position.units, position.decimals)} {asset.ticker}
              </Text>
            </View>
          </View>
        )}

        {capabilities?.blockedMessage ? (
          <View style={styles.notice}>
            <Icon name="info" size={16} color={colors.text.secondary} />
            <Text style={styles.noticeText}>{capabilities.blockedMessage}</Text>
          </View>
        ) : null}

        {tradingOn ? (
          <>
            <View style={styles.ctaRow}>
              {canBuy && (
                <TouchableOpacity
                  style={styles.ctaBuy}
                  onPress={() => navigation.navigate('BuyCrypto', { symbol: asset.symbol })}
                  activeOpacity={0.85}
                  accessibilityRole="button"
                  testID="crypto-detail-buy"
                >
                  <Text style={styles.ctaBuyText}>Comprar</Text>
                </TouchableOpacity>
              )}
              <TouchableOpacity
                testID="crypto-detail-sell"
                style={[styles.ctaSell, !holds && styles.ctaDisabled]}
                onPress={() => navigation.navigate('SellCrypto', { symbol: asset.symbol })}
                disabled={!holds}
                activeOpacity={0.85}
                accessibilityRole="button"
              >
                <Text style={[styles.ctaSellText, !holds && styles.ctaDisabledText]}>Vender</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.fundingSource}>
              <Icon name="dollar-sign" size={18} color={colors.primaryDark} />
              <View style={{ flex: 1 }}>
                <Text style={styles.fundingTitle}>Pagas con · {funding}</Text>
                <Text style={styles.fundingSub}>
                  {`Al vender, el dinero vuelve a tu ${funding}.`}
                </Text>
              </View>
            </View>
          </>
        ) : (
          <View style={styles.notice}>
            <Icon name="clock" size={16} color={colors.primaryDark} />
            <Text style={styles.noticeText}>Muy pronto podrás comprar y vender desde aquí.</Text>
          </View>
        )}

        <View style={styles.card}>
          <Text style={styles.sectionLabel}>Cómo funciona</Text>
          {[
            custody ? { icon: 'shield', text: custody } : null,
            { icon: 'repeat', text: 'Compras y vendes a través de PancakeSwap, a cualquier hora.' },
            { icon: 'lock', text: 'Queda en tu cuenta, no en Confío. Puedes venderlo cuando quieras.' },
            // The fee lives here (how it works), never on the trade screens:
            // the receipt itemizes what was actually charged (2026-10-25).
            feeBps != null ? {
              icon: 'percent',
              text: `Confío cobra su comisión de ${feePctLabel(feeBps)}% al comprar y al vender: es la misma que en cualquier retiro o depósito de tu dólar Confío.`,
            } : null,
          ]
            .filter((r): r is { icon: string; text: string } => Boolean(r))
            .map((r) => (
              <View key={r.icon} style={styles.howRow}>
                <Icon name={r.icon} size={16} color={colors.primaryDark} />
                <Text style={styles.howText}>{r.text}</Text>
              </View>
            ))}
        </View>

        <Text style={styles.footerDisclaimer}>
          El precio puede subir o bajar, también de noche y en fines de semana. Puedes perder parte de lo
          que inviertas. No es asesoría financiera.
        </Text>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  center: { justifyContent: 'center', alignItems: 'center' },
  unavailable: { color: colors.text.secondary, textAlign: 'center', paddingHorizontal: 32 },
  back: { color: colors.primaryDark, fontWeight: '600' },
  scrollContent: { padding: 16, paddingBottom: 40 },
  card: { backgroundColor: '#fff', borderRadius: 16, padding: 16, marginBottom: 14 },
  price: { fontSize: 34, fontWeight: 'bold', color: colors.text.primary },
  change: { fontSize: 14, fontWeight: '700', color: colors.primaryDark, marginTop: 3 },
  changeDown: { color: '#DC2626' },
  chartWrap: { marginTop: 14 },
  chartEmpty: { height: CHART_H, alignItems: 'center', justifyContent: 'center' },
  chartEmptyText: { fontSize: 12, color: colors.text.secondary },
  rangeRow: { flexDirection: 'row', gap: 6, marginTop: 10, paddingRight: 4 },
  rangePill: {
    width: 44,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 6,
    borderRadius: 8,
  },
  rangePillActive: { backgroundColor: colors.primaryLight },
  rangeText: { fontSize: 12, fontWeight: '600', color: colors.text.secondary },
  rangeTextActive: { color: colors.primaryDark },
  marketRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 12 },
  marketDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#10B981' },
  marketText: { fontSize: 12, color: colors.text.secondary },
  sectionLabel: { fontSize: 13, fontWeight: '700', color: colors.text.secondary, marginBottom: 10 },
  positionRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  positionValue: { fontSize: 22, fontWeight: 'bold', color: colors.text.primary },
  positionUnits: { fontSize: 14, fontWeight: '600', color: colors.text.secondary },
  notice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 14,
    marginBottom: 14,
  },
  noticeText: { flex: 1, fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
  ctaRow: { flexDirection: 'row', gap: 10, marginBottom: 10 },
  ctaBuy: { flex: 1, alignItems: 'center', backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 14 },
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
  fundingTitle: { fontSize: 13, fontWeight: '700', color: colors.text.primary },
  fundingSub: { fontSize: 12, color: colors.text.secondary, marginTop: 1, lineHeight: 16 },
  howRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', marginBottom: 10 },
  howText: { flex: 1, fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
  footerDisclaimer: { fontSize: 11, color: colors.text.light, textAlign: 'center', lineHeight: 16 },
});
