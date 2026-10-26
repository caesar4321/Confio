// Futuros — every Hyperliquid market the member can trade, long or short.
//
// Positions first (they are the member's money), then the markets: search,
// asset-class tabs and a sort, synced from Hyperliquid by the server (no
// hand-picked list). A position stopped between steps shows its next step
// here, so nothing is ever left half-done out of sight.

import React, { useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, ScrollView, StatusBar, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';

import { Text, TextInput } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { VenueAttribution } from '../components/VenueAttribution';
import { PerpMarketMark } from '../components/futures/PerpMarketMark';
import { colors } from '../config/theme';
import { useGmMarket } from '../hooks/useGmMarket';
import { usePerpsCapabilities, usePerpsMarkets, usePerpsPositions } from '../hooks/usePerps';
import type { AssetClass, PerpMarket, PerpPosition } from '../services/perps';
import { MainStackParamList } from '../types/navigation';
import {
  ASSET_CLASS_LABELS,
  ASSET_CLASS_ORDER,
  SIDE_COLORS,
  formatCompactUsd,
  formatPctSigned,
  formatPerpPrice,
  formatUsd,
  formatUsdSigned,
  pnlColor,
  sideLabel,
  stepLabel,
  positionValueUsd,
} from '../utils/perpsPresentation';

type Nav = NativeStackNavigationProp<MainStackParamList>;
type Tab = 'all' | AssetClass;
type Sort = 'volume' | 'gainers' | 'losers';
const ROW_HEIGHT = 68;

export const FuturesMarketsScreen = () => {
  const navigation = useNavigation<Nav>();
  const { capabilities, loading: capsLoading } = usePerpsCapabilities();
  const enabled = Boolean(capabilities?.enabled);
  const { markets, loading } = usePerpsMarkets(enabled);
  const { positions, unknown: positionsUnknown, refetch: refetchPositions } = usePerpsPositions(true);
  const { stocks } = useGmMarket(true);
  const [tab, setTab] = useState<Tab>('all');
  const [sort, setSort] = useState<Sort>('volume');
  const [query, setQuery] = useState('');

  useFocusEffect(useCallback(() => { refetchPositions().catch(() => {}); }, [refetchPositions]));

  const logos = useMemo(() => new Map(stocks.map((s) => [s.ticker.toUpperCase(), s.logoUrl])), [stocks]);
  const classes = useMemo(
    () => ASSET_CLASS_ORDER.filter((c) => markets.some((m) => m.assetClass === c)),
    [markets],
  );
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = markets.filter((m) => (tab === 'all' || m.assetClass === tab)
      && (!q || m.ticker.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)));
    const byChange = (m: PerpMarket) => m.dayChangePct ?? 0;
    return [...filtered].sort((a, b) => (sort === 'volume'
      ? (b.dayVolumeUsd ?? 0) - (a.dayVolumeUsd ?? 0)
      : sort === 'gainers' ? byChange(b) - byChange(a) : byChange(a) - byChange(b)));
  }, [markets, tab, sort, query]);

  const live = (positions ?? []).filter((p) => p.state !== 'done');
  const equity = live.reduce((sum, p) => sum + positionValueUsd(p), 0);
  const unrealized = live.reduce((sum, p) => sum + (p.unrealizedPnlUsd ?? 0), 0);

  const renderMarket = ({ item }: { item: PerpMarket }) => {
    const change = item.dayChangePct;
    const up = (change ?? 0) >= 0;
    return (
      <Pressable
        onPress={() => navigation.navigate('FuturesMarket', { coin: item.coin })}
        style={({ pressed }) => [styles.marketRow, pressed && styles.pressed]}
        accessibilityRole="button"
        accessibilityLabel={`${item.name}, ${formatPerpPrice(item.markPx)}, ${formatPctSigned(change)} en 24 horas`}
      >
        <PerpMarketMark ticker={item.ticker} logoUrl={logos.get(item.ticker.toUpperCase())} size={40} />
        <View style={styles.marketText}>
          <Text style={styles.marketName} numberOfLines={1}>{item.name}</Text>
          <View style={styles.marketMeta}>
            <Text style={styles.marketTicker}>{item.ticker}</Text>
            <View style={styles.levChip}><Text style={styles.levChipText}>hasta {item.maxLeverage}x</Text></View>
          </View>
        </View>
        <View style={styles.marketRight}>
          <Text style={styles.marketPrice}>{formatPerpPrice(item.markPx)}</Text>
          <View style={[styles.changePill, { backgroundColor: change == null ? '#F3F4F6' : up ? '#D1FAE5' : '#FEE2E2' }]}>
            <Text style={[styles.changeText, { color: change == null ? '#6B7280' : up ? '#047857' : '#B91C1C' }]}>
              {formatPctSigned(change)}
            </Text>
          </View>
        </View>
      </Pressable>
    );
  };

  const header = (
    <View>
      {/* Above the fold, like Ondo's line on the stocks list: where orders execute. */}
      <View style={styles.venueTop}><VenueAttribution venue="hyperliquid" testID="futures-venue" /></View>
      {positionsUnknown && (
        <Pressable style={styles.unknownBanner} onPress={() => { void refetchPositions(); }} accessibilityRole="button">
          <Icon name="alert-circle" size={16} color="#92400E" />
          <Text style={styles.unknownText}>No pudimos leer tus posiciones ahora. Tu dinero sigue a tu nombre. Toca para reintentar.</Text>
        </Pressable>
      )}
      {live.length > 0 && (
        <View style={styles.portfolio}>
          <View style={styles.portfolioHead}>
            <View>
              <Text style={styles.portfolioLabel}>Tus posiciones</Text>
              <Text style={styles.portfolioValue}>{formatUsd(equity)}</Text>
            </View>
            <View style={styles.portfolioPnl}>
              <Text style={styles.portfolioPnlLabel}>Ganancia abierta</Text>
              <Text style={[styles.portfolioPnlValue, { color: pnlColor(unrealized) }]}>{formatUsdSigned(unrealized)}</Text>
            </View>
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.positionStrip}>
            {live.map((p) => <PositionChip key={p.id} position={p} logoUrl={logos.get(p.ticker.toUpperCase())}
              onPress={() => navigation.navigate('FuturesPosition', { positionId: p.id })} />)}
          </ScrollView>
        </View>
      )}

      <View style={styles.search}>
        <Icon name="search" size={18} color={colors.text.light} />
        <TextInput
          style={styles.searchInput}
          value={query}
          onChangeText={setQuery}
          placeholder="Buscar Bitcoin, oro, Nvidia, S&P 500…"
          placeholderTextColor={colors.text.light}
          autoCorrect={false}
          autoCapitalize="none"
          accessibilityLabel="Buscar mercado"
        />
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
        {(['all', ...classes] as Tab[]).map((t) => (
          <Pressable key={t} onPress={() => setTab(t)} style={[styles.tab, tab === t && styles.tabActive]}
            accessibilityRole="tab" accessibilityState={{ selected: tab === t }}>
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
              {t === 'all' ? 'Todos' : ASSET_CLASS_LABELS[t]}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
      <View style={styles.sortRow}>
        {([['volume', 'Más operados'], ['gainers', 'Suben más'], ['losers', 'Bajan más']] as [Sort, string][]).map(([key, label]) => (
          <Pressable key={key} onPress={() => setSort(key)} style={styles.sortBtn} accessibilityRole="button"
            accessibilityState={{ selected: sort === key }}>
            <Text style={[styles.sortText, sort === key && styles.sortTextActive]}>{label}</Text>
          </Pressable>
        ))}
        <Text style={styles.count}>{rows.length} mercados</Text>
      </View>
    </View>
  );

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
      <Header
        navigation={navigation as any}
        title="Futuros"
        subtitle="Largo o corto, con apalancamiento · 24/7"
        backgroundColor={colors.heroField}
        isLight
        showBackButton
      />
      {!enabled && !capsLoading ? (
        <View style={styles.blocked}>
          <Icon name="info" size={22} color={colors.text.secondary} />
          <Text style={styles.blockedText}>
            {capabilities?.blockedMessage || 'Los futuros no están disponibles para tu cuenta.'}
          </Text>
          {live.length > 0 && <Text style={styles.blockedHint}>Puedes seguir viendo y cerrando tus posiciones.</Text>}
          {positionsUnknown && (
            <Pressable style={[styles.unknownBanner, { marginTop: 16 }]} onPress={() => { void refetchPositions(); }}
              accessibilityRole="button">
              <Icon name="alert-circle" size={16} color="#92400E" />
              <Text style={styles.unknownText}>No pudimos leer tus posiciones ahora. Tu dinero sigue a tu nombre. Toca para reintentar.</Text>
            </Pressable>
          )}
          {live.map((p) => (
            <Pressable key={p.id} style={styles.blockedRow}
              onPress={() => navigation.navigate('FuturesPosition', { positionId: p.id })}>
              <Text style={styles.blockedRowText}>{p.ticker} · {sideLabel(p.side)} {p.leverage}x</Text>
              <Icon name="chevron-right" size={18} color={colors.text.light} />
            </Pressable>
          ))}
        </View>
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(m) => m.coin}
          renderItem={renderMarket}
          ListHeaderComponent={header}
          ListEmptyComponent={
            <Text style={styles.empty}>{loading ? 'Cargando mercados…' : 'Ningún mercado coincide con tu búsqueda.'}</Text>
          }
          ListFooterComponent={
            <Text style={styles.footer}>
              Las órdenes se ejecutan en Hyperliquid. Confío no es un exchange ni un bróker: tu dinero queda en
              cuentas a tu nombre. Operar con apalancamiento puede hacerte perder todo el margen.
            </Text>
          }
          contentContainerStyle={styles.listContent}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          keyboardShouldPersistTaps="handled"
        />
      )}
    </View>
  );
};

function PositionChip({ position, logoUrl, onPress }: { position: PerpPosition; logoUrl?: string; onPress: () => void }) {
  const pending = stepLabel(position.nextAction, position.state);
  const roe = position.returnOnEquity != null ? position.returnOnEquity * 100 : null;
  const side = SIDE_COLORS[position.side];
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.chip, pressed && styles.pressed]}
      accessibilityRole="button"
      accessibilityLabel={`${position.ticker} ${sideLabel(position.side)} ${position.leverage}x${pending ? `. ${pending}` : ''}`}>
      <View style={styles.chipHead}>
        <PerpMarketMark ticker={position.ticker} logoUrl={logoUrl} size={30} leverage={position.leverage}
          badgeColor={side.solid} />
        <View style={{ flex: 1 }}>
          <Text style={styles.chipTicker} numberOfLines={1}>{position.ticker}</Text>
          <Text style={[styles.chipSide, { color: side.text }]}>{sideLabel(position.side)}</Text>
        </View>
      </View>
      {pending ? (
        <View style={styles.chipPending}>
          <View style={styles.pendingDot} />
          <Text style={styles.chipPendingText} numberOfLines={2}>{pending}</Text>
        </View>
      ) : (
        <>
          <Text style={[styles.chipPnl, { color: pnlColor(position.unrealizedPnlUsd) }]}>
            {formatUsdSigned(position.unrealizedPnlUsd)}
          </Text>
          <Text style={[styles.chipRoe, { color: pnlColor(roe) }]}>{formatPctSigned(roe)}</Text>
        </>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  unknownBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: '#FFFBEB', borderRadius: 14,
    paddingHorizontal: 14, paddingVertical: 12, marginBottom: 12, borderWidth: 1, borderColor: '#FDE68A',
  },
  unknownText: { flex: 1, fontSize: 13, lineHeight: 18, color: '#92400E', fontWeight: '600' },
  container: { flex: 1, backgroundColor: colors.neutral },
  listContent: { paddingBottom: 40 },
  venueTop: { paddingHorizontal: 16, marginBottom: 4 },
  pressed: { opacity: 0.85 },
  portfolio: {
    margin: 16, marginBottom: 6, backgroundColor: '#0F172A', borderRadius: 22, paddingVertical: 16,
  },
  portfolioHead: { flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: 18 },
  portfolioLabel: { fontSize: 13, color: '#94A3B8', fontWeight: '600' },
  portfolioValue: { fontSize: 28, fontWeight: '800', color: '#FFFFFF', marginTop: 2 },
  portfolioPnl: { alignItems: 'flex-end', justifyContent: 'flex-end' },
  portfolioPnlLabel: { fontSize: 12, color: '#94A3B8' },
  portfolioPnlValue: { fontSize: 17, fontWeight: '800', marginTop: 2 },
  positionStrip: { paddingHorizontal: 14, gap: 10, marginTop: 14 },
  chip: { width: 150, backgroundColor: '#FFFFFF', borderRadius: 16, padding: 12 },
  chipHead: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  chipTicker: { fontSize: 14, fontWeight: '800', color: '#111827' },
  chipSide: { fontSize: 12, fontWeight: '700' },
  chipPnl: { fontSize: 17, fontWeight: '800', marginTop: 10 },
  chipRoe: { fontSize: 12, fontWeight: '700', marginTop: 1 },
  chipPending: { flexDirection: 'row', gap: 6, marginTop: 10, alignItems: 'flex-start' },
  pendingDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#F59E0B', marginTop: 4 },
  chipPendingText: { flex: 1, fontSize: 12, fontWeight: '600', color: '#92400E', lineHeight: 16 },
  search: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 16, marginTop: 12,
    backgroundColor: '#FFFFFF', borderRadius: 14, paddingHorizontal: 14, borderWidth: 1, borderColor: colors.border,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.text.primary, paddingVertical: 12 },
  tabs: { paddingHorizontal: 16, gap: 8, marginTop: 12 },
  tab: { paddingHorizontal: 14, minHeight: 36, justifyContent: 'center', borderRadius: 18, backgroundColor: '#FFFFFF',
    borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: '#0F172A', borderColor: '#0F172A' },
  tabText: { fontSize: 13, fontWeight: '700', color: colors.text.secondary },
  tabTextActive: { color: '#FFFFFF' },
  sortRow: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 12, marginTop: 8, marginBottom: 4 },
  sortBtn: { paddingHorizontal: 6, minHeight: 34, justifyContent: 'center' },
  sortText: { fontSize: 12, fontWeight: '600', color: colors.text.light },
  sortTextActive: { color: colors.primaryDark, fontWeight: '800' },
  count: { marginLeft: 'auto', fontSize: 12, color: colors.text.light, paddingRight: 6 },
  marketRow: {
    height: ROW_HEIGHT, flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16,
    backgroundColor: '#FFFFFF', borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  marketText: { flex: 1 },
  marketName: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  marketMeta: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 3 },
  marketTicker: { fontSize: 12, color: colors.text.secondary, fontWeight: '600' },
  levChip: { backgroundColor: '#F1F5F9', borderRadius: 6, paddingHorizontal: 6, paddingVertical: 1 },
  levChipText: { fontSize: 11, fontWeight: '700', color: '#475569' },
  marketRight: { alignItems: 'flex-end', gap: 4 },
  marketPrice: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  changePill: { borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2, minWidth: 64, alignItems: 'center' },
  changeText: { fontSize: 12, fontWeight: '800' },
  empty: { textAlign: 'center', color: colors.text.secondary, padding: 32 },
  footer: { fontSize: 11, lineHeight: 16, color: colors.text.light, textAlign: 'center', padding: 24 },
  blocked: { padding: 24, gap: 12, alignItems: 'center' },
  blockedText: { fontSize: 15, color: colors.text.secondary, textAlign: 'center', lineHeight: 21 },
  blockedHint: { fontSize: 13, color: colors.text.light, textAlign: 'center' },
  blockedRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', alignSelf: 'stretch',
    backgroundColor: '#FFFFFF', borderRadius: 14, padding: 16 },
  blockedRowText: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
});
