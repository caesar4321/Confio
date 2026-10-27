// One Futuros market: the price, how it moves, what it costs to hold, and
// the two doors — Largo (you win if it rises) or Corto (you win if it falls).
// An open position in this market is shown in place of the doors.

import React, { useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StatusBar, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';

import { Text } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { VenueAttribution } from '../components/VenueAttribution';
import { AreaChart } from '../components/futures/AreaChart';
import { CandleChart } from '../components/futures/CandleChart';
import { PerpMarketMark } from '../components/futures/PerpMarketMark';
import { colors } from '../config/theme';
import { useGmMarket } from '../hooks/useGmMarket';
import { useLiveMid } from '../hooks/useLiveMids';
import { mergeLive, useMarketStream } from '../hooks/useMarketStream';
import {
  OHLC_INTERVALS,
  OhlcInterval,
  PERPS_RANGES,
  PERPS_RANGE_LABELS,
  PerpsRange,
  usePerpsCandles,
  usePerpsOhlc,
  usePerpsCapabilities,
  usePerpsMarkets,
  usePerpsPositions,
} from '../hooks/usePerps';
import { MainStackParamList } from '../types/navigation';
import {
  ASSET_CLASS_LABELS,
  DOWN,
  SIDE_COLORS,
  UP,
  formatCompactUsd,
  formatPctSigned,
  formatPerpPrice,
  formatUsdSigned,
  fundingLine,
  livePnl,
  pnlColor,
  sideLabel,
} from '../utils/perpsPresentation';

type Nav = NativeStackNavigationProp<MainStackParamList>;
type R = RouteProp<MainStackParamList, 'FuturesMarket'>;
type ChartMode = 'line' | 'candles';

// The chart a member last picked, for the next market they open (this app session).
let lastChartMode: ChartMode = 'line';
let lastInterval: OhlcInterval = '5m';
const INTERVAL_LABELS: Record<OhlcInterval, string> = {
  '1m': '1 minuto', '3m': '3 minutos', '5m': '5 minutos', '15m': '15 minutos', '1h': '1 hora', '4h': '4 horas', '1d': '1 día',
};

export const FuturesMarketScreen = () => {
  const navigation = useNavigation<Nav>();
  const { coin } = useRoute<R>().params;
  const { capabilities } = usePerpsCapabilities();
  const enabled = Boolean(capabilities?.enabled);
  const { byCoin, loading, refetch: refetchMarkets } = usePerpsMarkets(enabled);
  const market = byCoin(coin);
  const { positions, refetch: refetchPositions } = usePerpsPositions(true);
  // Hyperliquid's live price while this screen is open.
  const liveMid = useLiveMid(coin);
  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = async () => {
    setRefreshing(true);
    await Promise.all([refetchMarkets().catch(() => {}), refetchPositions().catch(() => {})]);
    setRefreshing(false);
  };
  const position = (positions ?? []).find((p) => p.coin === coin && p.state !== 'done');
  const [range, setRange] = useState<PerpsRange>('1D');
  const { closes, loading: chartLoading, failed } = usePerpsCandles(coin, range);
  const [mode, setModeState] = useState<ChartMode>(lastChartMode);
  const [interval, setIntervalState] = useState<OhlcInterval>(lastInterval);
  const setMode = (m: ChartMode) => { lastChartMode = m; setModeState(m); };
  const setInterval_ = (i: OhlcInterval) => { lastInterval = i; setIntervalState(i); };
  const candleMode = mode === 'candles';
  const ohlc = usePerpsOhlc(coin, interval, candleMode);
  const stream = useMarketStream(coin, interval, candleMode);
  const candles = useMemo(() => mergeLive(ohlc.candles, stream.live), [ohlc.candles, stream.live]);
  const { stocks } = useGmMarket(true);
  const logoUrl = useMemo(
    () => stocks.find((s) => s.ticker.toUpperCase() === (market?.ticker || '').toUpperCase())?.logoUrl,
    [stocks, market?.ticker],
  );

  if (!market) {
    return (
      <View style={[styles.container, styles.center]}>
        {loading ? <ActivityIndicator color={colors.primaryDark} /> : (
          <>
            <Text style={styles.unavailable}>{capabilities?.blockedMessage || 'Este mercado no está disponible.'}</Text>
            {/* No longer open to new trades (a market or its dex taken off
                the list), but a position in it is still the member's to
                manage and close. */}
            {position && (
              <Pressable onPress={() => navigation.navigate('FuturesPosition', { positionId: position.id })}
                style={{ marginTop: 16 }} accessibilityRole="button">
                <Text style={styles.back}>Ver mi posición</Text>
              </Pressable>
            )}
            <Pressable onPress={() => navigation.goBack()} style={{ marginTop: 16 }}>
              <Text style={styles.back}>Volver</Text>
            </Pressable>
          </>
        )}
      </View>
    );
  }

  const change = market.dayChangePct;
  const chartUp = closes.length >= 2 ? closes[closes.length - 1] >= closes[0] : (change ?? 0) >= 0;
  const canOpen = Boolean(capabilities?.openEnabled) && !position;
  const guides = position && position.entryPx ? [
    { value: position.entryPx, color: '#64748B', label: `Entrada ${formatPerpPrice(position.entryPx)}`, dashed: true },
    ...(position.liquidationPx ? [{ value: position.liquidationPx, color: DOWN, label: `Liquidación ${formatPerpPrice(position.liquidationPx)}`, dashed: true }] : []),
  ] : [];

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
      <Header
        navigation={navigation as any}
        title={market.name}
        subtitle={`${market.ticker} · ${ASSET_CLASS_LABELS[market.assetClass]}`}
        titleAccessory={<PerpMarketMark ticker={market.ticker} logoUrl={logoUrl} size={30} />}
        backgroundColor={colors.heroField}
        isLight
        showBackButton
      />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { void onRefresh(); }} tintColor={colors.primary} colors={[colors.primary]} />}>
        <View style={styles.card}>
          <View style={styles.priceRow}>
            <Text style={styles.price}>{formatPerpPrice(liveMid ?? market.markPx)}</Text>
            <View style={[styles.change, { backgroundColor: (change ?? 0) >= 0 ? '#D1FAE5' : '#FEE2E2' }]}>
              <Text style={[styles.changeText, { color: (change ?? 0) >= 0 ? '#047857' : '#B91C1C' }]}>
                {formatPctSigned(change)} 24 h
              </Text>
            </View>
          </View>
          <View style={styles.modes}>
            {([['line', 'Línea'], ['candles', 'Velas']] as [ChartMode, string][]).map(([m, label]) => (
              <Pressable key={m} onPress={() => setMode(m)} style={[styles.modeBtn, mode === m && styles.modeBtnActive]}
                accessibilityRole="button" accessibilityState={{ selected: mode === m }} testID={`perps-chart-mode-${m}`}>
                <Text style={[styles.modeText, mode === m && styles.modeTextActive]}>{label}</Text>
              </Pressable>
            ))}
          </View>
          {candleMode ? (
            <>
              <View style={styles.chart}>
                <CandleChart
                  key={`${coin}:${interval}`}
                  candles={candles}
                  daily={interval === '1d'}
                  guides={guides.map((g) => ({ value: g.value, color: g.color, label: g.label }))}
                  emptyText={ohlc.loading ? 'Cargando velas…' : ohlc.failed ? 'No se pudo cargar el gráfico' : 'Aún no hay suficientes datos'}
                  testID="perps-candles"
                />
              </View>
              <View style={styles.ranges}>
                {OHLC_INTERVALS.map((i) => (
                  <Pressable key={i} onPress={() => setInterval_(i)} style={[styles.range, interval === i && styles.rangeActive]}
                    accessibilityRole="button" accessibilityLabel={`Velas de ${INTERVAL_LABELS[i]}`}
                    accessibilityState={{ selected: interval === i }} testID={`perps-interval-${i}`}>
                    <Text style={[styles.rangeText, interval === i && styles.rangeTextActive]}>{i === '1d' ? '1D' : i}</Text>
                  </Pressable>
                ))}
              </View>
              <View style={styles.book} testID="perps-bbo">
                <View style={styles.bookCell}>
                  <Text style={styles.bookLabel}>Bid · vendes a</Text>
                  <Text style={[styles.bookValue, { color: DOWN }]}>{formatPerpPrice(stream.bbo?.bid)}</Text>
                </View>
                <View style={styles.bookCell}>
                  <Text style={styles.bookLabel}>Ask · compras a</Text>
                  <Text style={[styles.bookValue, { color: UP }]}>{formatPerpPrice(stream.bbo?.ask)}</Text>
                </View>
                <View style={styles.bookCell}>
                  <Text style={styles.bookLabel}>Spread</Text>
                  <Text style={styles.bookValue}>
                    {stream.bbo ? `${formatPctSigned(((stream.bbo.ask - stream.bbo.bid) / stream.bbo.bid) * 100, 3).replace('+', '')}` : '—'}
                  </Text>
                </View>
              </View>
              <Text style={styles.bookNote}>
                Velas, bid y ask salen del mismo libro de órdenes de Hyperliquid donde se ejecuta tu orden.
              </Text>
            </>
          ) : (
            <>
              <View style={styles.chart}>
                <AreaChart
                  values={closes}
                  color={chartUp ? UP : DOWN}
                  guides={guides}
                  emptyText={chartLoading ? 'Cargando gráfico…' : failed ? 'No se pudo cargar el gráfico' : 'Aún no hay suficientes datos'}
                  testID="perps-chart"
                />
              </View>
              <View style={styles.ranges}>
                {PERPS_RANGES.map((r) => (
                  <Pressable key={r} onPress={() => setRange(r)} style={[styles.range, range === r && styles.rangeActive]}
                    accessibilityRole="button" accessibilityLabel={PERPS_RANGE_LABELS[r]} accessibilityState={{ selected: range === r }}>
                    <Text style={[styles.rangeText, range === r && styles.rangeTextActive]}>{r}</Text>
                  </Pressable>
                ))}
              </View>
            </>
          )}
          <View style={styles.live}><View style={styles.liveDot} /><Text style={styles.liveText}>Opera 24/7 en Hyperliquid</Text></View>
        </View>

        {position && (
          <Pressable style={({ pressed }) => [styles.posCard, pressed && styles.pressed]}
            onPress={() => navigation.navigate('FuturesPosition', { positionId: position.id })}
            accessibilityRole="button" accessibilityLabel={`Tu posición: ${sideLabel(position.side)} ${position.leverage}x`}>
            <View style={styles.posHead}>
              <View style={[styles.sideTag, { backgroundColor: SIDE_COLORS[position.side].soft }]}>
                <Icon name={position.side === 'long' ? 'trending-up' : 'trending-down'} size={14}
                  color={SIDE_COLORS[position.side].text} />
                <Text style={[styles.sideTagText, { color: SIDE_COLORS[position.side].text }]}>
                  {sideLabel(position.side)} {position.leverage}x
                </Text>
              </View>
              <Text style={styles.posLabel}>Tu posición</Text>
              <Icon name="chevron-right" size={18} color={colors.text.light} style={{ marginLeft: 'auto' }} />
            </View>
            <Text style={[styles.posPnl, { color: pnlColor(livePnl(position, liveMid)) }]}>
              {formatUsdSigned(livePnl(position, liveMid))}
            </Text>
            <Text style={styles.posSub}>
              {(() => {
                // The % from the same live result as the dollars above it.
                const pnl = livePnl(position, liveMid);
                const roe = pnl != null && position.marginUsedUsd ? (pnl / position.marginUsedUsd) * 100
                  : position.returnOnEquity != null ? position.returnOnEquity * 100 : null;
                return roe != null ? `${formatPctSigned(roe)} sobre tu margen` : 'Abriendo…';
              })()}
            </Text>
          </Pressable>
        )}

        <View style={styles.stats}>
          <Stat icon="repeat" label="Financiamiento" value={fundingLine(market.fundingRate)}
            hint="Cada hora, los largos pagan a los cortos (o al revés) para mantener el precio cerca del mercado real." />
          <Stat icon="bar-chart-2" label="Volumen 24 h" value={formatCompactUsd(market.dayVolumeUsd)} />
          <Stat icon="layers" label="Interés abierto" value={formatCompactUsd(market.openInterestUsd)} />
          <Stat icon="zap" label="Apalancamiento" value={`Hasta ${market.maxLeverage}x`} />
        </View>

        {canOpen ? (
          <View style={styles.doors}>
            <Door side="long" onPress={() => navigation.navigate('FuturesOrder', { coin, side: 'long' })} ticker={market.ticker} />
            <Door side="short" onPress={() => navigation.navigate('FuturesOrder', { coin, side: 'short' })} ticker={market.ticker} />
          </View>
        ) : !position ? (
          <View style={styles.notice}>
            <Icon name="info" size={16} color={colors.text.secondary} />
            <Text style={styles.noticeText}>
              {capabilities?.blockedMessage || 'Abrir posiciones nuevas no está disponible en este momento.'}
            </Text>
          </View>
        ) : null}

        <View style={styles.card}>
          <Text style={styles.sectionLabel}>Cómo funciona</Text>
          {[
            { icon: 'trending-up', text: 'Largo: ganas si el precio sube. Corto: ganas si baja. El apalancamiento multiplica ambas cosas.' },
            { icon: 'shield', text: 'Cada posición tiene su propio margen: lo máximo que puedes perder en ella es ese margen.' },
            { icon: 'repeat', text: 'Tu margen sale de tus dólares y cruza a Hyperliquid; al cerrar, vuelve. Cada salida y entrada paga el 0,9% de Confío Dollar.' },
            { icon: 'lock', text: 'Confío no es un exchange ni un bróker: firmas tú con tu llave y el dinero queda a tu nombre.' },
          ].map((r) => (
            <View key={r.icon} style={styles.how}>
              <Icon name={r.icon} size={16} color={colors.primaryDark} />
              <Text style={styles.howText}>{r.text}</Text>
            </View>
          ))}
        </View>
        <VenueAttribution venue="hyperliquid" testID="futures-market-venue" />
        <Text style={[styles.disclaimer, styles.disclaimerAfterVenue]}>
          Los futuros perpetuos son de alto riesgo: puedes perder todo el margen de una posición. No es asesoría financiera.
        </Text>
      </ScrollView>
    </View>
  );
};

function Stat({ icon, label, value, hint }: { icon: string; label: string; value: string; hint?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Pressable style={styles.stat} onPress={() => hint && setOpen((v) => !v)} disabled={!hint}
      accessibilityRole={hint ? 'button' : undefined} accessibilityHint={hint}>
      <View style={styles.statHead}>
        <Icon name={icon} size={14} color={colors.text.light} />
        <Text style={styles.statLabel}>{label}</Text>
        {hint ? <Icon name="help-circle" size={13} color={colors.text.light} /> : null}
      </View>
      <Text style={styles.statValue} numberOfLines={2}>{value}</Text>
      {open && hint ? <Text style={styles.statHint}>{hint}</Text> : null}
    </Pressable>
  );
}

function Door({ side, onPress, ticker }: { side: 'long' | 'short'; onPress: () => void; ticker: string }) {
  const c = SIDE_COLORS[side];
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.door, { backgroundColor: c.solid }, pressed && styles.pressed]}
      accessibilityRole="button" accessibilityLabel={`Abrir ${sideLabel(side).toLowerCase()} en ${ticker}`}
      testID={`perps-open-${side}`}>
      <Icon name={side === 'long' ? 'arrow-up-right' : 'arrow-down-right'} size={22} color="#FFFFFF" />
      <View>
        <Text style={styles.doorTitle}>{side === 'long' ? 'Largo' : 'Corto'}</Text>
        <Text style={styles.doorSub}>{side === 'long' ? 'Ganas si sube' : 'Ganas si baja'}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  center: { alignItems: 'center', justifyContent: 'center', padding: 32 },
  unavailable: { color: colors.text.secondary, textAlign: 'center' },
  back: { color: colors.primaryDark, fontWeight: '700' },
  scroll: { padding: 16, paddingBottom: 40 },
  pressed: { opacity: 0.85 },
  card: { backgroundColor: '#FFFFFF', borderRadius: 20, padding: 16, marginBottom: 14 },
  priceRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  price: { fontSize: 32, fontWeight: '800', color: colors.text.primary },
  change: { borderRadius: 10, paddingHorizontal: 10, paddingVertical: 5 },
  changeText: { fontSize: 13, fontWeight: '800' },
  chart: { marginTop: 14 },
  modes: { flexDirection: 'row', alignSelf: 'flex-start', backgroundColor: '#F3F4F6', borderRadius: 10, padding: 3, marginTop: 12 },
  modeBtn: { paddingHorizontal: 14, minHeight: 32, justifyContent: 'center', borderRadius: 8 },
  modeBtnActive: { backgroundColor: '#FFFFFF' },
  modeText: { fontSize: 13, fontWeight: '700', color: colors.text.secondary },
  modeTextActive: { color: colors.text.primary },
  book: { flexDirection: 'row', marginTop: 12, backgroundColor: '#F9FAFB', borderRadius: 12, paddingVertical: 10 },
  bookCell: { flex: 1, alignItems: 'center' },
  bookLabel: { fontSize: 11, color: colors.text.secondary, fontWeight: '600' },
  bookValue: { fontSize: 14, fontWeight: '800', color: colors.text.primary, marginTop: 2 },
  bookNote: { fontSize: 11, color: colors.text.light, marginTop: 8, lineHeight: 15 },
  ranges: { flexDirection: 'row', gap: 6, marginTop: 10 },
  range: { flex: 1, minHeight: 40, alignItems: 'center', justifyContent: 'center', borderRadius: 10 },
  rangeActive: { backgroundColor: colors.primaryLight },
  rangeText: { fontSize: 12, fontWeight: '700', color: colors.text.secondary },
  rangeTextActive: { color: colors.primaryDark },
  live: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 10 },
  liveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#10B981' },
  liveText: { fontSize: 12, color: colors.text.secondary },
  posCard: { backgroundColor: '#FFFFFF', borderRadius: 20, padding: 16, marginBottom: 14, borderWidth: 1.5, borderColor: '#0F172A' },
  posHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sideTag: { flexDirection: 'row', alignItems: 'center', gap: 4, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 3 },
  sideTagText: { fontSize: 12, fontWeight: '800' },
  posLabel: { fontSize: 13, fontWeight: '700', color: colors.text.secondary },
  posPnl: { fontSize: 26, fontWeight: '800', marginTop: 10 },
  posSub: { fontSize: 13, color: colors.text.secondary, marginTop: 2 },
  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 14 },
  stat: { width: '48%', flexGrow: 1, backgroundColor: '#FFFFFF', borderRadius: 16, padding: 14 },
  statHead: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  statLabel: { fontSize: 12, fontWeight: '700', color: colors.text.light },
  statValue: { fontSize: 15, fontWeight: '800', color: colors.text.primary, marginTop: 6 },
  statHint: { fontSize: 12, lineHeight: 17, color: colors.text.secondary, marginTop: 6 },
  doors: { flexDirection: 'row', gap: 12, marginBottom: 14 },
  door: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10, borderRadius: 18, paddingVertical: 16, paddingHorizontal: 16 },
  doorTitle: { fontSize: 17, fontWeight: '800', color: '#FFFFFF' },
  doorSub: { fontSize: 12, fontWeight: '600', color: 'rgba(255,255,255,0.85)' },
  notice: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#FFFFFF', borderRadius: 14, padding: 14, marginBottom: 14 },
  noticeText: { flex: 1, fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
  sectionLabel: { fontSize: 13, fontWeight: '800', color: colors.text.secondary, marginBottom: 12 },
  how: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', marginBottom: 12 },
  howText: { flex: 1, fontSize: 13, lineHeight: 18, color: colors.text.secondary },
  disclaimer: { fontSize: 11, lineHeight: 16, color: colors.text.light, textAlign: 'center' },
  disclaimerAfterVenue: { marginTop: 10 },
});
