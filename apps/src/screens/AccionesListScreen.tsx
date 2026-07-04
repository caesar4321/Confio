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
  FlatList,
  StatusBar,
  Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { useNumberFormat } from '../utils/numberFormatting';
import { useGmMarket, GmStock } from '../hooks/useGmMarket';
import { TickerLogo } from '../components/TickerLogo';
import { useAhorrosPortfolio } from '../hooks/useAhorrosPortfolio';
import OndoLogo from '../assets/png/Ondo.png';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

export const AccionesListScreen = () => {
  const navigation = useNavigation<NavProp>();
  const { formatNumber } = useNumberFormat();
  const { session, stocks } = useGmMarket();
  const { savings, stocks: myStocks } = useAhorrosPortfolio();
  const [search, setSearch] = useState('');

  // Every row carries BOTH numbers with the app-wide hierarchy: the big
  // right-side number is always MY balance ($0.00 included, gray), exactly
  // like the home wallet rows; market price + day % are the small secondary
  // line beneath it. Held stocks sort first.
  const positionByTicker = useMemo(() => {
    const map: Record<string, number> = {};
    myStocks.positions.forEach((p) => {
      map[p.ticker] = p.valueUsd;
    });
    return map;
  }, [myStocks.positions]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const base = q
      ? stocks.filter(
          (s) => s.ticker.toLowerCase().includes(q) || s.name.toLowerCase().includes(q),
        )
      : stocks;
    const held = base.filter((s) => (positionByTicker[s.ticker] || 0) > 0);
    const rest = base.filter((s) => !((positionByTicker[s.ticker] || 0) > 0));
    return [...held, ...rest];
  }, [search, stocks, positionByTicker]);

  const fmtUsd = (v: number) =>
    `$${formatNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const renderRow = ({ item }: { item: GmStock }) => {
    const up = item.dayChangePct >= 0;
    const positionValue = positionByTicker[item.ticker] || 0;
    return (
      <TouchableOpacity
        style={styles.row}
        activeOpacity={0.8}
        onPress={() => navigation.navigate('StockDetail', { ticker: item.ticker })}
      >
        <TickerLogo ticker={item.ticker} color={item.color} logoUrl={item.logoUrl} size={42} />
        <View style={{ flex: 1 }}>
          <Text style={styles.rowTicker}>{item.ticker}</Text>
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
        <View style={styles.header}>
          <View style={styles.headerTopRow}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn} accessibilityRole="button" accessibilityLabel="Volver">
              <Icon name="arrow-left" size={24} color="#fff" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Acciones de EE.UU.</Text>
            <View style={styles.headerIconBtn} />
          </View>
          <View style={styles.headerMetaRow}>
            <View style={styles.marketChip}>
              <View
                style={[
                  styles.marketDot,
                  { backgroundColor: session === 'closed' ? '#9CA3AF' : '#34D399' },
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
      </SafeAreaView>

      <FlatList
        data={filtered}
        keyExtractor={(s) => s.ticker}
        renderItem={renderRow}
        contentContainerStyle={styles.listContent}
        initialNumToRender={12}
        maxToRenderPerBatch={10}
        windowSize={11}
        showsVerticalScrollIndicator={false}
        ListHeaderComponent={
          <View>
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
          <View style={styles.empty}>
            <Icon name="search" size={36} color={colors.text.light} />
            <Text style={styles.emptyText}>No encontramos "{search}"</Text>
          </View>
        }
        ListFooterComponent={
          <View>
            <View style={styles.partnerRow}>
              <Text style={styles.partnerText}>En alianza con</Text>
              <Image source={OndoLogo} style={styles.partnerLogo} />
              <Text style={styles.partnerBrand}>Ondo Finance</Text>
            </View>
            <Text style={styles.footerDisclaimer}>
              Acciones tokenizadas respaldadas 1:1 por acciones reales en EE.UU. Los dividendos
              se reinvierten automáticamente. Pueden subir o bajar de valor — invierte solo lo
              que puedas mantener. Disponible en jurisdicciones habilitadas.
            </Text>
          </View>
        }
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: { backgroundColor: colors.primary, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 16 },
  headerTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },
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
  marketChipText: { fontSize: 11, fontWeight: '600', color: '#fff' },
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
  buyingPower: { fontSize: 11, color: '#fff', fontWeight: '600' },

  listContent: { padding: 16, paddingBottom: 40 },

  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#fff',
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
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 14,
    marginBottom: 8,
  },
  tickerCircle: {
    width: 42,
    height: 42,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tickerCircleText: { color: '#fff', fontSize: 11, fontWeight: '800' },
  rowTicker: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  rowName: { fontSize: 12, color: colors.text.secondary, marginTop: 1 },
  rowHolding: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  rowHoldingZero: { color: colors.text.light, fontWeight: '500' },
  rowMarketPrice: { fontSize: 12, color: colors.text.secondary },
  rowChange: { fontSize: 12, fontWeight: '700', color: colors.primaryDark, marginTop: 1 },
  rowChangeDown: { color: '#DC2626' },

  empty: { alignItems: 'center', paddingVertical: 48, gap: 10 },
  emptyText: { fontSize: 14, color: colors.text.secondary },

  partnerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginTop: 16,
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
