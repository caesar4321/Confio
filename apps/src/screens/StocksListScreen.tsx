// Acciones de EE.UU. — the Ondo Stocks explorer.
//
// Language: this block is the ONLY place the app says "inversión". Prices are
// live-ish (24h change colored), the market chip states reality, and the
// footer names risk plainly. Buying power = cUSD+ (sweep model) — stated in
// the header hint so nobody hunts for a separate "deposit to invest" step.

import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  SectionList,
  ScrollView,
  StatusBar,
  Image,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { FEATURED_STOCK_TICKERS, STOCK_TAGLINES } from '../config/stockPresentation';
import { useNumberFormat } from '../utils/numberFormatting';
import { useGmMarket, useGmHighlights, GmStock } from '../hooks/useGmMarket';
import { TickerLogo } from '../components/TickerLogo';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { formatUsdDeltaAbs } from '../utils/savingsFormat';
import OndoLogo from '../assets/png/Ondo.png';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

export const StocksListScreen = () => {
  const navigation = useNavigation<NavProp>();
  const { formatNumber } = useNumberFormat();
  const { savings, stocks: myStocks, loading: portfolioLoading, refetch: refetchPortfolio } = useSavingsPortfolio();
  const { session, stocks, loading } = useGmMarket(myStocks.enabled);
  const highlights = useGmHighlights(myStocks.enabled);
  const [search, setSearch] = useState('');

  // Every row carries BOTH numbers with the app-wide hierarchy: the big
  // right-side number is always MY balance ($0.00 included, gray), exactly
  // like the home wallet rows; market price + day % are the small secondary
  // line beneath it. Featured assets precede the market-cap ranking.
  const positionByTicker = useMemo(() => {
    const map: Record<string, number> = {};
    myStocks.positions.forEach((p) => {
      map[p.ticker] = p.valueUsd;
    });
    return map;
  }, [myStocks.positions]);

  const query = search.trim().toLowerCase();
  const filtered = useMemo(
    () => (query
      ? stocks.filter(
        (s) => s.ticker.toLowerCase().includes(query) || s.name.toLowerCase().includes(query),
      )
      : stocks),
    [query, stocks],
  );

  // What you own leads — it used to be scattered through 443 rows, findable
  // only by its non-grey balance. The full list keeps the server's
  // market-cap order: the starter shelf above it already features the
  // indices and metals, so they no longer need to jump the queue here.
  const sections = useMemo(() => {
    if (query) {
      return [{ key: 'results', title: 'Resultados', data: filtered }]
        .filter(section => section.data.length > 0);
    }
    const mine = stocks
      .filter(stock => (positionByTicker[stock.ticker] || 0) > 0)
      .sort((a, b) => (positionByTicker[b.ticker] || 0) - (positionByTicker[a.ticker] || 0));
    return [
      { key: 'mine', title: 'Tus acciones', data: mine },
      { key: 'all', title: `Todas · ${stocks.length}`, data: stocks },
    ].filter(section => section.data.length > 0);
  }, [query, filtered, stocks, positionByTicker]);

  // What the investment is made of: the four largest positions, the rest
  // folded into "Otras". Shares of the total, so the bar always adds up.
  const allocation = useMemo(() => {
    const total = myStocks.totalUsd;
    if (total <= 0) return [];
    const sorted = [...myStocks.positions]
      .filter(p => p.valueUsd > 0)
      .sort((a, b) => b.valueUsd - a.valueUsd);
    const top = sorted.slice(0, 4).map(p => ({ key: p.ticker, label: p.name, share: p.valueUsd / total }));
    const rest = sorted.slice(4).reduce((sum, p) => sum + p.valueUsd, 0);
    const slices = rest > 0 ? [...top, { key: 'other', label: 'Otras', share: rest / total }] : top;
    // Largest-remainder rounding so the legend always reads 100%: rounding
    // each slice alone gave 33+33+33 = 99 (or 101).
    const floors = slices.map(slice => Math.floor(slice.share * 100));
    let remainder = 100 - floors.reduce((sum, n) => sum + n, 0);
    const byRemainder = slices
      .map((slice, index) => ({ index, frac: slice.share * 100 - floors[index] }))
      .sort((a, b) => b.frac - a.frac);
    for (const { index } of byRemainder) {
      if (remainder <= 0) break;
      floors[index] += 1;
      remainder -= 1;
    }
    return slices.map((slice, index) => ({ ...slice, pct: floors[index] }));
  }, [myStocks.positions, myStocks.totalUsd]);
  // Today's move as a percent of yesterday's value (total minus today's P&L).
  const todayBase = myStocks.totalUsd - myStocks.earnedTodayUsd;
  const todayPct = todayBase > 0 ? (myStocks.earnedTodayUsd / todayBase) * 100 : null;

  const starters = useMemo(
    () => FEATURED_STOCK_TICKERS
      .map(ticker => stocks.find(stock => stock.ticker === ticker))
      .filter((stock): stock is GmStock => !!stock),
    [stocks],
  );

  const fmtUsd = (v: number) =>
    `$${formatNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  // `enabled` is also false before the portfolio answers. Saying "no
  // disponibles" then turned eligible users away when they tapped in early
  // (Home's Acciones tile); only say it once eligibility is actually known.
  if (!myStocks.enabled && !myStocks.eligibilityKnown) {
    return (
      <View style={[styles.container, { justifyContent: 'center', alignItems: 'center', padding: 32 }]}>
        {portfolioLoading ? (
          <ActivityIndicator color={colors.primary} />
        ) : (
          <>
            <Text style={{ color: colors.text.secondary, textAlign: 'center' }}>
              No pudimos cargar las acciones.
            </Text>
            <TouchableOpacity onPress={() => { refetchPortfolio().catch(() => {}); }} style={{ marginTop: 16 }}>
              <Text style={{ color: colors.primaryDark, fontWeight: '600' }}>Reintentar</Text>
            </TouchableOpacity>
          </>
        )}
        <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginTop: 16 }}>
          <Text style={{ color: colors.text.secondary }}>Volver</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (!myStocks.enabled) {
    return (
      <View style={[styles.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <Text style={{ color: colors.text.secondary }}>Acciones no disponibles</Text>
        <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginTop: 16 }}>
          <Text style={{ color: colors.primaryDark, fontWeight: '600' }}>Volver</Text>
        </TouchableOpacity>
      </View>
    );
  }

  // One horizontal shelf of cards, each with one factual line.
  const renderShelf = (
    key: string,
    title: string,
    subtitle: string | null,
    items: { stock: GmStock; tagline: string }[],
  ) => {
    if (items.length === 0) return null;
    return (
      <View key={key} style={styles.shelf}>
        <Text style={[styles.shelfTitle, !!subtitle && styles.shelfTitleWithSub]} accessibilityRole="header">{title}</Text>
        {!!subtitle && <Text style={styles.shelfSubtitle}>{subtitle}</Text>}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.shelfRow}>
          {items.map(({ stock, tagline }) => {
            const up = stock.dayChangePct >= 0;
            return (
              <TouchableOpacity
                key={stock.ticker}
                style={styles.shelfCard}
                activeOpacity={0.85}
                onPress={() => navigation.navigate('StockDetail', { ticker: stock.ticker })}
                accessibilityRole="button"
                accessibilityLabel={`${stock.name}. ${tagline}`}
              >
                <TickerLogo ticker={stock.ticker} color={stock.color} logoUrl={stock.logoUrl} size={32} />
                <Text style={styles.shelfName} numberOfLines={1}>{stock.name}</Text>
                <Text style={styles.shelfTagline} numberOfLines={2}>{tagline}</Text>
                <View style={styles.shelfPriceRow}>
                  <Text style={styles.rowMarketPrice}>{fmtUsd(stock.priceUsd)}</Text>
                  <Text style={[styles.rowChange, !up && styles.rowChangeDown]}>
                    {up ? '▲' : '▼'} {formatNumber(Math.abs(stock.dayChangePct), { maximumFractionDigits: 2 })}%
                  </Text>
                </View>
              </TouchableOpacity>
            );
          })}
        </ScrollView>
      </View>
    );
  };

  const renderRow = ({ item }: { item: GmStock }) => {
    const up = item.dayChangePct >= 0;
    const positionValue = positionByTicker[item.ticker] || 0;
    const warning = highlights.warningFor(item.ticker);
    return (
      <TouchableOpacity
        style={styles.row}
        activeOpacity={0.8}
        onPress={() => navigation.navigate('StockDetail', { ticker: item.ticker })}
      >
        <TickerLogo ticker={item.ticker} color={item.color} logoUrl={item.logoUrl} size={42} />
        <View style={{ flex: 1 }}>
          <View style={styles.rowTickerLine}>
            <Text style={styles.rowTicker}>{item.ticker}</Text>
            {warning && (
              <View style={styles.riskBadge}>
                <Text style={styles.riskBadgeText}>{warning.badge}</Text>
              </View>
            )}
          </View>
          <Text style={styles.rowName} numberOfLines={1}>
            {item.name}
          </Text>
        </View>
        <View style={{ alignItems: 'flex-end' }}>
          <Text style={[styles.rowHolding, positionValue <= 0 && styles.rowHoldingZero]}>
            {fmtUsd(positionValue)}
          </Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
            <Text style={styles.rowMarketPrice}>{fmtUsd(item.priceUsd)}</Text>
            <Text style={[styles.rowChange, !up && styles.rowChangeDown]}>
              {up ? '▲' : '▼'}{' '}
              {formatNumber(Math.abs(item.dayChangePct), { maximumFractionDigits: 2 })}%
            </Text>
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        {/* Brand field: emerald gradient + coin ring, padding on headerInner
            (Yoga insets absolute children by parent padding). */}
        <View style={styles.header}>
          <Svg style={StyleSheet.absoluteFill}>
            <Defs>
              <SvgLinearGradient id="stocksField" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={colors.primary} />
                <Stop offset="1" stopColor={colors.primaryDark} />
              </SvgLinearGradient>
            </Defs>
            <Rect width="100%" height="100%" fill="url(#stocksField)" />
            <Circle cx="105%" cy="35%" r="90" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
          </Svg>
          <View style={styles.headerInner}>
          <View style={styles.headerTopRow}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn} accessibilityRole="button" accessibilityLabel="Volver">
              <Icon name="arrow-left" size={24} color={colors.white} />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Acciones de EE.UU.</Text>
            {/* "¿Cómo funciona?" lives up here now: at the end of a 450-row
                list nobody ever reached it. */}
            <TouchableOpacity
              onPress={() => navigation.navigate('OndoStocksInfo')}
              style={styles.headerIconBtn}
              accessibilityRole="button"
              accessibilityLabel="Cómo funcionan las acciones de Estados Unidos"
            >
              <Icon name="help-circle" size={22} color={colors.white} />
            </TouchableOpacity>
          </View>
          {/* Portfolio header (moved here with the Ahorros/Acciones split):
              the invested total + day P&L — red days are honest HERE, never
              on the home or the dollar account. ≥ $0.01 rule via
              formatUsdDeltaAbs; hidden entirely with no positions. */}
          {myStocks.totalUsd <= 0 && (
            // No holdings yet: an invitation, stated plainly. Fractions are
            // the real unlock — people assume a share costs hundreds.
            <View style={styles.inviteHero}>
              <Text style={styles.inviteTitle}>Invierte en las empresas que usas</Text>
              <Text style={styles.inviteSub}>
                Compra fracciones con tus dólares. No necesitas una acción entera.
              </Text>
              <TouchableOpacity
                onPress={() => navigation.navigate('OndoStocksInfo')}
                style={styles.inviteLink}
                accessibilityRole="button"
                accessibilityLabel="Cómo funciona"
              >
                <Text style={styles.inviteLinkText}>¿Cómo funciona?</Text>
                <Icon name="chevron-right" size={16} color={colors.white} />
              </TouchableOpacity>
            </View>
          )}
          {myStocks.totalUsd > 0 && (
            // Yours, and alive: the total, today's move as a pill (red days
            // are honest HERE, never on Home), and what it is made of. No
            // "total return": there is no cost basis to compute it from, and
            // an invented one would be worse than none.
            <View style={styles.portfolioHero}>
              <Text style={styles.portfolioLabel}>Tu inversión en EE.UU.</Text>
              <Text style={styles.portfolioAmount}>{fmtUsd(myStocks.totalUsd)}</Text>
              {formatUsdDeltaAbs(myStocks.earnedTodayUsd) && (
                <View style={[styles.todayPill, myStocks.earnedTodayUsd < 0 && styles.todayPillDown]}>
                  <Text style={[styles.todayPillText, myStocks.earnedTodayUsd < 0 && styles.todayPillTextDown]}>
                    {myStocks.earnedTodayUsd >= 0 ? '▲ +' : '▼ −'}
                    {formatUsdDeltaAbs(myStocks.earnedTodayUsd)}
                    {todayPct !== null ? ` (${formatNumber(Math.abs(todayPct), { maximumFractionDigits: 2 })}%)` : ''} hoy
                  </Text>
                </View>
              )}
              {allocation.length > 0 && (
                <View style={styles.allocation}>
                  <View style={styles.allocationBar}>
                    {allocation.map((slice, index) => (
                      <View
                        key={slice.key}
                        style={[
                          styles.allocationSlice,
                          { flex: slice.share, opacity: 1 - index * 0.2 },
                        ]}
                      />
                    ))}
                  </View>
                  {/* Wrapping items, never truncated: every slice in the bar
                      has a readable label, at any width or text size. */}
                  <View style={styles.allocationLegend}>
                    {allocation.map(slice => (
                      <Text key={slice.key} style={styles.allocationLegendItem}>
                        {`${slice.label} ${slice.pct}%`}
                      </Text>
                    ))}
                  </View>
                </View>
              )}
            </View>
          )}
          <View style={styles.headerMetaRow}>
            <View style={styles.marketChip}>
              <View
                style={[
                  styles.marketDot,
                  { backgroundColor: session === 'closed' ? colors.text.light : colors.primary },
                ]}
              />
              <Text style={styles.marketChipText}>
                {session === 'closed'
                  ? 'Fin de semana · activos seleccionados'
                  : session === 'core'
                    ? 'Operando ahora'
                    : 'Sesión extendida'}
              </Text>
            </View>
            {/* Buying power as an instrument pill — the sweep model at a
                glance: you invest with your savings (cUSD+). */}
            <View style={styles.buyingPowerPill}>
              <Image source={cUSDPlusLogo} style={styles.buyingPowerLogo} />
              <Text style={styles.buyingPower}>
                Para invertir: ${formatNumber(savings.balanceUsd, { maximumFractionDigits: 2 })}
              </Text>
            </View>
          </View>
          </View>
        </View>
      </SafeAreaView>

      <SectionList
        sections={sections}
        stickySectionHeadersEnabled={false}
        keyExtractor={(s) => s.ticker}
        renderItem={renderRow}
        renderSectionHeader={({ section }) => (
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle} accessibilityRole="header">{section.title}</Text>
          </View>
        )}
        contentContainerStyle={styles.listContent}
        initialNumToRender={12}
        maxToRenderPerBatch={10}
        windowSize={11}
        showsVerticalScrollIndicator={false}
        ListHeaderComponent={
          <View>
            {/* Partner attribution ABOVE the fold: with 400+ rows, a footer
                placement is effectively invisible. One slim line here shows
                on first paint and scrolls away with the list — visibility
                without permanently reserving screen. */}
            <View style={styles.partnerRowTop}>
              <Text style={styles.partnerText}>En alianza con</Text>
              <Image source={OndoLogo} style={styles.partnerLogo} />
              <Text style={styles.partnerBrand}>Ondo Finance</Text>
            </View>
            {/* Starter shelf: the four broad, low-effort places to begin.
                Replaces the "¿No sabes por dónde empezar?" box, which framed
                the user as lost and ended on a warning. Hidden while searching. */}
            {!query && starters.length > 0 && renderShelf(
              'starters',
              'Empieza por aquí',
              null,
              starters.map(stock => ({ stock, tagline: STOCK_TAGLINES[stock.ticker] || stock.ticker })),
            )}
            {/* Server-curated shelves (LatAm, crypto trackers). A shelf
                shows only the assets live in the market payload. */}
            {!query && highlights.shelves.map(shelf => renderShelf(
              shelf.key,
              shelf.title,
              shelf.subtitle,
              shelf.items.flatMap(item => {
                const stock = stocks.find(candidate => candidate.ticker === item.ticker);
                return stock ? [{ stock, tagline: item.tagline }] : [];
              }),
            ))}
            <View style={styles.searchBox}>
              <Icon name="search" size={18} color={colors.text.light} />
              <TextInput
                style={styles.searchInput}
                placeholder="Buscar por nombre o símbolo"
                placeholderTextColor={colors.text.light}
                value={search}
                onChangeText={setSearch}
                autoCapitalize="characters"
              />
              {search.length > 0 && (
                <TouchableOpacity onPress={() => setSearch('')} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} accessibilityRole="button" accessibilityLabel="Borrar búsqueda">
                  <Icon name="x-circle" size={18} color={colors.text.light} />
                </TouchableOpacity>
              )}
            </View>

          </View>
        }
        ListEmptyComponent={
          loading ? (
            <View style={styles.empty}>
              <ActivityIndicator color={colors.primary} />
              <Text style={styles.emptyText}>Cargando precios…</Text>
            </View>
          ) : (
            <View style={styles.empty}>
              <Icon name="search" size={36} color={colors.text.light} />
              <Text style={styles.emptyText}>
                {search ? `No encontramos "${search}"` : 'No pudimos cargar los precios. Desliza para reintentar.'}
              </Text>
            </View>
          )
        }
        ListFooterComponent={
          <View>
            {/* Disclosure is layered: the explainer is the ? in the header;
                the issuer's wording closes the list. */}
            {/* Attribution lives in the list header (above the fold); the
                footer keeps only the risk disclaimer + a closing mention. */}
            <Text style={styles.footerDisclaimer}>
              Acciones digitales de Ondo Stocks diseñadas para estar totalmente
              respaldadas. Los dividendos se reinvierten automáticamente.
              Pueden subir o bajar de valor — invierte solo lo que puedas
              mantener. Disponible en jurisdicciones habilitadas. En alianza
              con Ondo Finance.
            </Text>
          </View>
        }
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: { backgroundColor: colors.primary, overflow: 'hidden' },
  headerInner: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 16 },
  headerTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: colors.white },
  portfolioHero: { alignItems: 'center', marginTop: 14 },
  portfolioLabel: { fontSize: 12, color: colors.white, opacity: 0.85 },
  portfolioAmount: { fontSize: 32, fontWeight: 'bold', color: colors.white, marginTop: 2 },
  headerMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 12,
  },
  marketChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: 'rgba(255,255,255,0.15)',
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  marketDot: { width: 7, height: 7, borderRadius: 4 },
  marketChipText: { fontSize: 11, fontWeight: '600', color: colors.white },
  buyingPowerPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: 'rgba(255,255,255,0.15)',
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  buyingPowerLogo: { width: 14, height: 14, borderRadius: 7 },
  buyingPower: { fontSize: 11, color: colors.white, fontWeight: '600' },

  listContent: { padding: 16, paddingBottom: 40 },
  sectionHeader: { paddingTop: 12, paddingBottom: 10 },
  sectionTitle: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
  inviteHero: { marginTop: 14 },
  inviteLink: { flexDirection: 'row', alignItems: 'center', gap: 2, marginTop: 10, alignSelf: 'flex-start' },
  inviteLinkText: { fontSize: 14, fontWeight: '700', color: colors.white, textDecorationLine: 'underline' },
  todayPill: {
    marginTop: 8,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 14,
    backgroundColor: 'rgba(255,255,255,0.2)',
  },
  todayPillDown: { backgroundColor: 'rgba(127,29,29,0.35)' },
  todayPillText: { fontSize: 13, fontWeight: '700', color: colors.white },
  todayPillTextDown: { color: colors.error.border },
  allocation: { alignSelf: 'stretch', marginTop: 14 },
  allocationBar: {
    flexDirection: 'row',
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
    gap: 2,
  },
  allocationSlice: { backgroundColor: colors.white },
  allocationLegend: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    columnGap: 12,
    rowGap: 2,
    marginTop: 6,
  },
  allocationLegendItem: { fontSize: 12, color: colors.white, opacity: 0.9 },
  inviteTitle: { fontSize: 22, fontWeight: 'bold', color: colors.white },
  inviteSub: { fontSize: 14, lineHeight: 20, color: colors.white, opacity: 0.9, marginTop: 4 },
  shelf: { marginTop: 4, marginBottom: 8 },
  shelfTitle: { fontSize: 14, fontWeight: '600', color: colors.text.primary, marginBottom: 10 },
  shelfTitleWithSub: { marginBottom: 2 },
  shelfSubtitle: { fontSize: 12, lineHeight: 16, color: colors.text.secondary, marginBottom: 10 },
  shelfRow: { gap: 10, paddingRight: 16 },
  rowTickerLine: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  riskBadge: {
    backgroundColor: colors.warning.background,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 1,
  },
  riskBadgeText: { fontSize: 10, fontWeight: '700', color: colors.warning.text },
  shelfCard: {
    width: 148,
    backgroundColor: colors.white,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 12,
  },
  shelfName: { fontSize: 15, fontWeight: '700', color: colors.text.primary, marginTop: 8 },
  shelfTagline: { fontSize: 12, lineHeight: 16, color: colors.text.secondary, marginTop: 2, minHeight: 32 },
  shelfPriceRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 8 },

  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.white,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 12,
    height: 46,
    marginBottom: 12,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.text.primary, padding: 0 },

  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: colors.white,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
    padding: 14,
    marginBottom: 8,
  },
  rowTicker: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  rowName: { fontSize: 12, color: colors.text.secondary, marginTop: 1 },
  rowHolding: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  rowHoldingZero: { color: colors.text.light, fontWeight: '500' },
  rowMarketPrice: { fontSize: 12, color: colors.text.secondary },
  rowChange: { fontSize: 12, fontWeight: '700', color: colors.primaryDark, marginTop: 1 },
  rowChangeDown: { color: colors.error.icon },

  empty: { alignItems: 'center', paddingVertical: 48, gap: 10 },
  emptyText: { fontSize: 14, color: colors.text.secondary },

  // Slim one-liner between search and list: seen on first paint, scrolls
  // away with the content — visibility without reserving screen.
  partnerRowTop: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginTop: 2,
    marginBottom: 10,
  },
  partnerText: { fontSize: 12, color: colors.text.light },
  partnerLogo: { width: 16, height: 16, borderRadius: 4 },
  partnerBrand: { fontSize: 12, fontWeight: '700', color: colors.text.secondary },


  footerDisclaimer: {
    fontSize: 11,
    color: colors.text.light,
    textAlign: 'center',
    marginTop: 10,
    lineHeight: 16,
    paddingHorizontal: 8,
  },
});
