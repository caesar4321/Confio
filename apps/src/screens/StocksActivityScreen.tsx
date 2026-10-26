// "Inversiones en movimiento": the community's trading in U.S. stocks,
// Bitcoin, gold and Futuros (Futuros at margin, never the leveraged size),
// the twin of Dinero en movimiento (same hero, cards and bars). Opened from Home's Inversiones proof tile. Against a server
// without investTradingStats it falls back to the stock-only
// "Acciones en movimiento" (gmTradingStats).
//
// Public aggregates only (gmTradingStats, cached 10 min server-side): the
// buy/sale split in dollars and counts, how many people trade, a typical
// purchase, and the most traded stocks. A stock is ranked only once at
// least three different people traded it, so no row points at one person.
import React from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { gql, useQuery } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';
import { MainStackParamList } from '../types/navigation';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { EmptyState } from '../components/EmptyState';
import { formatDecimal } from '../utils/numberLocale';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { usePerpsCapabilities } from '../hooks/usePerps';

export const GM_TRADING_STATS = gql`
  query GmTradingStats {
    gmTradingStats {
      totalUsd
      buyUsd
      sellUsd
      buyCount
      sellCount
      traderCount
      medianBuyUsd
      since
      topAssets {
        symbol
        ticker
        name
        tradeCount
        traderCount
      }
    }
  }
`;

export const INVEST_TRADING_STATS = gql`
  query InvestTradingStats {
    investTradingStats {
      totalUsd
      buyUsd
      sellUsd
      buyCount
      sellCount
      traderCount
      medianBuyUsd
      since
      topAssets {
        symbol
        ticker
        name
        tradeCount
        traderCount
        assetKind
      }
    }
  }
`;

type TopAsset = {
  assetKind?: string | null;
  symbol: string;
  ticker: string;
  name: string;
  tradeCount: number;
  traderCount: number;
};

// Acciones' hue on Home (indigo): violet stays reserved for $CONFIO.
const STOCKS_INDIGO = '#6366F1';

const MONTHS_ES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
];

/** "La mitad de las compras fue de US$3 o menos": the typical purchase,
 * rounded UP to a whole dollar so "o menos" always stays true. */
export const typicalPurchaseLabel = (medianUsd: number): string => {
  const whole = Math.max(1, Math.ceil(medianUsd - 1e-9));
  return `US$${formatDecimal(whole, { decimals: 0 })}`;
};

export const StocksActivityScreen = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { stocks: stockPortfolio } = useSavingsPortfolio();
  const stocksEnabled = Boolean(stockPortfolio?.enabled);
  // Futuros count in the combined totals at margin (server); a Futuros row
  // opens its market only for someone who can trade it.
  const { capabilities: perps } = usePerpsCapabilities();
  const perpsEnabled = Boolean(perps?.enabled);
  // What the total contains, whoever is looking: the server's combined total
  // includes everyone's Futuros once Futuros exist (capabilities answered),
  // even for a viewer who can't open one.
  const perpsInTotal = perps != null;
  const invest = useQuery(INVEST_TRADING_STATS, {
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
    notifyOnNetworkStatusChange: true,
  });
  // The stock-only breakdown, only when the combined one can't exist here:
  // an older server rejects the whole query (unknown field), or the server
  // withholds it (privacy floor) for someone who may see stocks. Any other
  // failure stays on the combined query, so Reintentar retries it.
  const unsupported = (invest.error?.graphQLErrors ?? []).some(e => /Cannot query field/.test(e.message ?? ''))
    || /Cannot query field/.test(invest.error?.message ?? '');
  const withheld = !invest.loading && !invest.error && invest.data != null
    && invest.data.investTradingStats == null && stocksEnabled;
  const legacy = useQuery(GM_TRADING_STATS, {
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
    notifyOnNetworkStatusChange: true,
    skip: !(unsupported || withheld),
  });
  const investMode = !(unsupported || withheld);
  const { data, loading, error } = investMode ? invest : legacy;
  // Always re-ask for the combined view too: a null may have been a cold or
  // failed snapshot, not the privacy floor, and it can recover.
  const retry = () => {
    invest.refetch().catch(() => {});
    if (!investMode) legacy.refetch().catch(() => {});
  };
  const stats = (investMode ? data?.investTradingStats : data?.gmTradingStats) ?? null;

  const whole = (n: number | null | undefined) => (n == null ? '—' : formatDecimal(n, { decimals: 0 }));
  const since = stats?.since ? new Date(stats.since) : null;
  const sinceLabel = since && !isNaN(since.getTime())
    ? `desde ${MONTHS_ES[since.getUTCMonth()]} de ${since.getUTCFullYear()}`
    : null;
  // The split is withheld below the privacy floor (one side would expose a
  // single person's trades): then only the counts show.
  const splitKnown = stats?.buyUsd != null && stats?.sellUsd != null;
  const buys = stats?.buyUsd ?? 0;
  const buyOps = stats?.buyCount ?? 0;
  const sellOps = stats?.sellCount ?? 0;
  const sells = stats?.sellUsd ?? 0;
  const top: TopAsset[] = stats?.topAssets ?? [];
  const maxTrades = top.reduce((m, a) => Math.max(m, a.tradeCount), 0);
  const operations = (stats?.buyCount ?? 0) + (stats?.sellCount ?? 0);

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title={investMode ? 'Inversiones en movimiento' : 'Acciones en movimiento'}
        backgroundColor={colors.heroField}
        isLight
        showBackButton
      />

      {!stats && loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : !stats ? (
        <EmptyState
          icon="wifi-off"
          title="No pudimos cargar estos datos"
          subtitle={error ? 'Revisa tu conexión e inténtalo de nuevo.' : 'Inténtalo de nuevo en un momento.'}
          actionLabel="Reintentar"
          onAction={retry}
        />
      ) : (
        <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={styles.field}>
            <BrandFieldBackground id="stocksActivityField" ringCy="25%" ringR={80} ringWidth={20} />
            <View style={styles.fieldInner}>
              <Text style={styles.fieldEyebrow}>
                {!investMode ? 'OPERADO EN ACCIONES DE EE.UU.'
                  : perpsInTotal ? 'OPERADO EN ACCIONES, ORO, BITCOIN Y FUTUROS' : 'OPERADO EN ACCIONES, ORO Y BITCOIN'}
              </Text>
              <Text style={styles.fieldStat}>
                {whole(stats.totalUsd)}
                <Text style={styles.fieldUnit}> USD</Text>
              </Text>
              <Text style={styles.fieldSubtitle}>
                {whole(operations)} compras y ventas{sinceLabel ? ` · ${sinceLabel}` : ''}
              </Text>
            </View>
          </View>

          <View style={styles.card}>
            {/* In dollars when the split may be stated; otherwise by number of
                operations (already public), never an empty bar. */}
            <View style={styles.splitBar}>
              {(splitKnown ? buys + sells : buyOps + sellOps) > 0 && (
                <>
                  <View style={[styles.splitIn, { flex: splitKnown ? buys : buyOps }]} />
                  <View style={[styles.splitOut, { flex: splitKnown ? sells : sellOps }]} />
                </>
              )}
            </View>
            <View style={styles.splitRow}>
              <View style={styles.splitCol}>
                <View style={styles.legendRow}>
                  <View style={[styles.dot, styles.dotIn]} />
                  <Text style={styles.splitLabel}>Compras</Text>
                </View>
                {splitKnown && <Text style={styles.splitValue}>{whole(buys)} USD</Text>}
                <Text style={styles.splitCount}>{whole(stats.buyCount)} operaciones</Text>
              </View>
              <View style={styles.splitCol}>
                <View style={styles.legendRow}>
                  <View style={[styles.dot, styles.dotOut]} />
                  <Text style={styles.splitLabel}>Ventas</Text>
                </View>
                {splitKnown && <Text style={styles.splitValue}>{whole(sells)} USD</Text>}
                <Text style={styles.splitCount}>{whole(stats.sellCount)} operaciones</Text>
              </View>
            </View>
            {!splitKnown && (
              <Text style={styles.splitNote}>
                Mostramos los montos de compras y ventas cuando cada lado reúne al menos 3 personas, para que nadie quede expuesto.
              </Text>
            )}
          </View>

          {/* The hook: you don't need much to start. A median stated as one,
              hidden until there are enough purchases to mean something. */}
          {stats.medianBuyUsd != null && (
            <View style={[styles.card, styles.factCard]}>
              <Icon name="zap" size={18} color={colors.primary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.factTitle}>
                  La mitad de las compras fue de {typicalPurchaseLabel(stats.medianBuyUsd)} o menos
                </Text>
                <Text style={styles.factSub}>
                  {whole(stats.traderCount)} personas ya invierten {investMode ? 'en acciones, oro y bitcoin' : 'en acciones de EE.UU.'} desde Confío, empezando con poco.
                </Text>
              </View>
            </View>
          )}

          {top.length > 0 && (
            <>
              <Text style={styles.sectionLabel}>Lo más operado</Text>
              {top.map((asset, index) => (
                <Pressable
                  key={asset.symbol}
                  // A stock opens only for someone who may see stocks: the
                  // detail would answer "no disponible" to anyone else.
                  disabled={asset.assetKind === 'perps' ? !perpsEnabled : asset.assetKind !== 'crypto' && !stocksEnabled}
                  onPress={() => (asset.assetKind === 'perps'
                    ? navigation.navigate('FuturesMarket', { coin: asset.symbol })
                    : asset.assetKind === 'crypto'
                      ? navigation.navigate('CryptoDetail' as any, { symbol: asset.symbol } as any)
                      : navigation.navigate('StockDetail' as any, { ticker: asset.ticker } as any))}
                  style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
                  accessibilityRole="button"
                  accessibilityLabel={`${index + 1}. ${asset.ticker}, ${asset.name}: ${asset.tradeCount} operaciones de ${asset.traderCount} personas`}
                  accessibilityHint={`Ver ${asset.ticker}`}
                >
                  <View style={styles.rowHeader}>
                    <Text style={styles.rank}>{index + 1}</Text>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.ticker} numberOfLines={1}>{asset.ticker}</Text>
                      <Text style={styles.assetName} numberOfLines={1}>
                        {asset.assetKind === 'perps' ? `${asset.name} · Futuros` : asset.name}
                      </Text>
                    </View>
                    <View style={styles.countCol}>
                      <Text style={styles.count}>{whole(asset.tradeCount)}</Text>
                      <Text style={styles.countSub}>{whole(asset.traderCount)} personas</Text>
                    </View>
                    <Icon name="chevron-right" size={18} color={colors.text.light} />
                  </View>
                  <View style={styles.barTrack}>
                    <View
                      style={[
                        styles.barFill,
                        { width: `${maxTrades > 0 ? Math.max(8, (asset.tradeCount / maxTrades) * 100) : 0}%` },
                      ]}
                    />
                  </View>
                </Pressable>
              ))}
              <Text style={styles.footnote}>
                {investMode
                  ? 'Solo lo operado por al menos 3 personas, para proteger la privacidad.'
                  : 'Solo acciones operadas por al menos 3 personas, para proteger la privacidad.'}
              </Text>
            </>
          )}

          {stocksEnabled && <View style={styles.ctaGroup}>
            <Pressable
              onPress={() => navigation.navigate('StocksList' as any)}
              style={({ pressed }) => [styles.ctaPrimary, pressed && styles.rowPressed]}
              accessibilityRole="button"
            >
              <Icon name="trending-up" size={18} color={colors.white} />
              <Text style={styles.ctaPrimaryText}>Explorar acciones</Text>
            </Pressable>
            <Pressable
              onPress={() => navigation.navigate('OndoStocksInfo' as any)}
              style={({ pressed }) => [styles.ctaSecondary, pressed && styles.rowPressed]}
              accessibilityRole="button"
            >
              <Text style={styles.ctaSecondaryText}>¿Qué es Ondo Stocks?</Text>
            </Pressable>
          </View>}

          <View style={styles.card}>
            <Text style={styles.howTitle}>Cómo lo contamos</Text>
            <Text style={styles.howText}>
              Sumamos cada compra y venta {investMode ? 'de acciones de EE.UU., oro y bitcoin' : 'de acciones de EE.UU.'} completada en Confío, por el monto
              exacto que se cobró o se pagó.{investMode && perpsInTotal
                ? ' En Futuros contamos tu dinero: el margen al abrir y lo que vuelve al cerrar, nunca el tamaño apalancado.'
                : ''} No incluye depósitos ni retiros (esos están en Dinero en
              movimiento). El total es acumulado desde el inicio y no muestra a nadie en particular.
            </Text>
          </View>
        </ScrollView>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.white },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scrollContent: { paddingBottom: 32 },
  field: { backgroundColor: colors.heroField, overflow: 'hidden' },
  fieldInner: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 22 },
  fieldEyebrow: { fontSize: 11, fontWeight: '700', letterSpacing: 2, color: colors.primaryLight, marginBottom: 6 },
  fieldStat: { fontSize: 30, fontWeight: '800', color: colors.white },
  fieldUnit: { fontSize: 16, fontWeight: '700', color: 'rgba(255,255,255,0.85)' },
  fieldSubtitle: { fontSize: 13, lineHeight: 19, color: 'rgba(255,255,255,0.85)', marginTop: 6 },
  card: { backgroundColor: colors.neutral, borderRadius: 12, padding: 14, marginHorizontal: 16, marginTop: 16 },
  splitBar: { flexDirection: 'row', height: 10, borderRadius: 5, overflow: 'hidden', backgroundColor: colors.border, gap: 2 },
  splitIn: { backgroundColor: colors.primary },
  splitOut: { backgroundColor: STOCKS_INDIGO },
  splitRow: { flexDirection: 'row', marginTop: 12, gap: 12 },
  splitCol: { flex: 1 },
  legendRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  dotIn: { backgroundColor: colors.primary },
  dotOut: { backgroundColor: STOCKS_INDIGO },
  splitLabel: { fontSize: 12, fontWeight: '600', color: colors.text.secondary },
  splitValue: { fontSize: 18, fontWeight: '800', color: colors.dark, marginTop: 4 },
  splitNote: { fontSize: 12, lineHeight: 17, color: colors.text.secondary, marginTop: 10 },
  splitCount: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  factCard: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 },
  factTitle: { fontSize: 15, fontWeight: '700', color: colors.dark, lineHeight: 20 },
  factSub: { fontSize: 12, color: colors.text.secondary, marginTop: 4, lineHeight: 17 },
  sectionLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.secondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 8,
  },
  row: { backgroundColor: colors.neutral, borderRadius: 12, paddingVertical: 12, paddingHorizontal: 14, marginHorizontal: 16, marginBottom: 10 },
  rowPressed: { opacity: 0.75 },
  rowHeader: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  rank: { width: 20, fontSize: 15, fontWeight: '800', color: colors.text.light, textAlign: 'center' },
  ticker: { fontSize: 15, fontWeight: '700', color: colors.dark },
  assetName: { fontSize: 12, color: colors.text.secondary, marginTop: 1 },
  countCol: { alignItems: 'flex-end' },
  count: { fontSize: 15, fontWeight: '700', color: colors.dark },
  countSub: { fontSize: 11, color: colors.text.secondary, marginTop: 1 },
  barTrack: { marginTop: 8, height: 6, borderRadius: 3, backgroundColor: colors.border, overflow: 'hidden' },
  barFill: { height: 6, backgroundColor: STOCKS_INDIGO, borderRadius: 3 },
  footnote: { fontSize: 12, color: colors.text.light, paddingHorizontal: 20, marginTop: 2 },
  ctaGroup: { marginHorizontal: 16, marginTop: 20, gap: 10 },
  ctaPrimary: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: colors.primaryDark,
    borderRadius: 14,
    paddingVertical: 14,
  },
  ctaPrimaryText: { fontSize: 16, fontWeight: '700', color: colors.white },
  ctaSecondary: { alignItems: 'center', paddingVertical: 10 },
  ctaSecondaryText: { fontSize: 14, fontWeight: '600', color: colors.primaryDark },
  howTitle: { fontSize: 14, fontWeight: '700', color: colors.dark },
  howText: { fontSize: 13, lineHeight: 19, color: colors.text.secondary, marginTop: 6 },
});
