import React, { useCallback, useMemo } from 'react';
import { Image, Pressable, ScrollView, StatusBar, StyleSheet, View } from 'react-native';
import { Text } from '../components/common/AppText';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect, useIsFocused, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';

import {
  GET_ACTIVE_PRESALE,
  GET_MY_PRESALE_ONCHAIN_INFO,
  GET_PRESALE_CURVE_STATS,
  GET_PRESALE_STATUS,
} from '../apollo/queries';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import StocksMark from '../components/svg/StocksMark';
import { CryptoAssetMark } from '../components/CryptoAssetMark';
import OndoLogo from '../assets/png/Ondo.png';
import { VenueAttribution, venueA11y } from '../components/VenueAttribution';
import { FEATURED_STOCK_TICKERS } from '../config/stockPresentation';
import { colors } from '../config/theme';
import { useAccount } from '../contexts/AccountContext';
import { useGmMarket } from '../hooks/useGmMarket';
import { useCryptoCapabilities, useCryptoHoldings, useCryptoMarket } from '../hooks/useCrypto';
import { usePerpsCapabilities, usePerpsMarkets, usePerpsPositions } from '../hooks/usePerps';
import FuturesMark from '../components/svg/FuturesMark';
import { PerpMarketMark } from '../components/futures/PerpMarketMark';
import {
  SIDE_COLORS,
  formatPctSigned,
  formatUsd as formatPerpUsd,
  formatUsdSigned,
  pnlColor,
  sideLabel,
  stepLabel,
  positionValueUsd,
} from '../utils/perpsPresentation';
import { formatUsdPrice } from '../utils/cryptoPresentation';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { MainStackParamList } from '../types/navigation';
import { useNumberFormat } from '../utils/numberFormatting';
import { formatUsdDeltaAbs } from '../utils/savingsFormat';

type Nav = NativeStackNavigationProp<MainStackParamList>;

const METAL_ETF_TICKERS = new Set(['GLD', 'SLV']);

const num = (v: unknown): number | null => {
  const n = typeof v === 'number' ? v : parseFloat(String(v ?? ''));
  return Number.isFinite(n) ? n : null;
};

/**
 * Invertir — the tab for growing money, with two doors: U.S. stocks (Ondo,
 * geo-eligible users only) and the $CONFIO presale.
 *
 * Each door carries its own live signal instead of a paragraph: the stocks
 * card shows today's market (or the user's own position), the presale card
 * shows the phase, price and how far the raise has come. Red days are allowed
 * here (a hub), never on Home.
 */
export const InvestScreen = ({ topAccessory }: { topAccessory?: React.ReactNode } = {}) => {
  const navigation = useNavigation<Nav>();
  const isFocused = useIsFocused();
  const { formatNumber } = useNumberFormat();
  const { stocks } = useSavingsPortfolio();
  const { activeAccount } = useAccount();
  const isEmployee = Boolean(activeAccount?.isEmployee);

  const { stocks: market } = useGmMarket(stocks.enabled && !isEmployee);
  // Bitcoin & gold: its own country policy, separate from Ondo's. The list is
  // whatever the server lists (two at launch); nothing is hard-coded here.
  const { capabilities: crypto, refetch: refetchCrypto } = useCryptoCapabilities(isEmployee);
  const cryptoEnabled = Boolean(crypto?.enabled) && !isEmployee;
  const { assets: cryptoAssets } = useCryptoMarket(cryptoEnabled);
  // Always read for owners: a holder whose country was blocked, or whose
  // token was delisted, must still see it and reach Vender.
  const { holdings: cryptoHoldings } = useCryptoHoldings(isEmployee);
  // Futuros: its own country policy and switches. Shown below Oro y Bitcoin
  // and above $CONFIO (cards ordered by risk); never promoted elsewhere.
  const { capabilities: perps, refetch: refetchPerps } = usePerpsCapabilities(isEmployee);
  const perpsEnabled = Boolean(perps?.enabled) && !isEmployee;
  const { markets: perpsMarkets } = usePerpsMarkets(perpsEnabled);
  // Always read for owners: a holder whose country was blocked must still reach Cerrar.
  const { positions: perpsPositions, unknown: perpsUnknown } = usePerpsPositions(!isEmployee, { pollMs: 30_000 });
  const { data: presaleData, refetch: refetchPresale } = useQuery(GET_ACTIVE_PRESALE, { fetchPolicy: 'cache-and-network', skip: isEmployee });
  const { data: statusData, refetch: refetchStatus } = useQuery(GET_PRESALE_STATUS, { fetchPolicy: 'cache-and-network', skip: isEmployee });
  // The live curve — the same source ConfioPresaleScreen buys at. The phase
  // row's price and goal are fixed at creation and go stale as the curve moves.
  const { data: curveData, loading: curveLoading, refetch: refetchCurve } = useQuery(GET_PRESALE_CURVE_STATS, { fetchPolicy: 'cache-and-network', skip: isEmployee });
  const claimsOpen = statusData?.isPresaleClaimsUnlocked === true;
  // Claims being open is global; whether THIS user has anything is not.
  const { data: onchainData, refetch: refetchOnchain } = useQuery(GET_MY_PRESALE_ONCHAIN_INFO, {
    fetchPolicy: 'cache-and-network',
    skip: isEmployee || !claimsOpen,
  });
  // A tab stays mounted: re-read the raise on every return, or the "live"
  // card keeps the price and progress from the first visit.
  useFocusEffect(
    useCallback(() => {
      if (isEmployee) return;
      refetchCrypto().catch(() => {});
      refetchPerps().catch(() => {});
      refetchPresale().catch(() => {});
      refetchStatus().catch(() => {});
      refetchCurve().catch(() => {});
      if (claimsOpen) refetchOnchain().catch(() => {});
    }, [isEmployee, claimsOpen, refetchCrypto, refetchPerps, refetchPresale, refetchStatus, refetchCurve, refetchOnchain]),
  );

  const usd = (v: number, digits = 2) =>
    `$${formatNumber(v, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

  // Today's market in names people know: the featured indices. Gold has its
  // own card now (Oro y Bitcoin), so Ondo's gold/silver ETFs stay inside the
  // stocks list but leave this strip — gold is never shown twice here.
  const tickerStrip = useMemo(
    () => FEATURED_STOCK_TICKERS.filter(ticker => !METAL_ETF_TICKERS.has(ticker)).slice(0, 3)
      .map(ticker => market.find(stock => stock.ticker === ticker))
      .filter((stock): stock is NonNullable<typeof stock> => !!stock),
    [market],
  );

  const phase = presaleData?.activePresalePhase;
  const curve = curveData?.presaleCurveStats;
  const claimable = num(onchainData?.myPresaleOnchainInfo?.claimable) ?? 0;
  const claimsUnlocked = claimsOpen && claimable > 0;
  // Phase values describe its setup, not the moving price or next milestone.
  // Keep the last curve payload during a refresh; never replace missing curve
  // data with a different price or an invented zero-percent progress bar.
  const price = num(curve?.currentPrice);
  const raised = num(curve?.totalRaisedUsd);
  const goal = num(curve?.nextMilestoneUsd);
  const participants = num(curve?.participants);
  const progress = raised != null && goal != null && goal > 0
    ? Math.max(0, Math.min(100, (raised / goal) * 100))
    : null;
  const presaleLive = Boolean(phase) && !claimsOpen;

  if (isEmployee) {
    return (
      <View style={[styles.screen, styles.employee]}>
        <Icon name="briefcase" size={32} color={colors.secondaryDark} />
        <Text style={styles.employeeTitle}>Inversiones del negocio</Text>
        <Text style={styles.employeeText}>El dueño administra las inversiones de esta cuenta.</Text>
      </View>
    );
  }

  const holdsStocks = stocks.positions.length > 0 || stocks.totalUsd > 0;
  const todayDelta = formatUsdDeltaAbs(stocks.earnedTodayUsd);
  const heldCrypto = (cryptoHoldings ?? []).filter(h => {
    try { return BigInt(h.units || '0') > 0n; } catch { return false; }
  });
  const holdsCrypto = heldCrypto.length > 0;
  // null = unknown: never print a confident $0.00 for someone who holds.
  const cryptoValueKnown = cryptoHoldings !== null && heldCrypto.every(h => h.valueUsd != null);
  const cryptoTotal = heldCrypto.reduce((sum, h) => sum + (h.valueUsd ?? 0), 0);
  // One row per listed asset (when discovery is on) plus any held asset the
  // market doesn't list for this person: those are sell-only.
  const listedSymbols = new Set(cryptoEnabled ? cryptoAssets.map(a => a.symbol) : []);
  const cryptoRows = [
    ...(cryptoEnabled ? cryptoAssets : []).map(a => ({
      symbol: a.symbol, ticker: a.ticker, name: a.name, category: a.category,
      priceUsd: a.priceUsd, dayChangePct: a.dayChangePct, valueUsd: null as number | null, sellOnly: false,
    })),
    ...heldCrypto.filter(h => !listedSymbols.has(h.symbol)).map(h => ({
      symbol: h.symbol, ticker: h.ticker, name: h.name, category: h.category,
      priceUsd: null as number | null, dayChangePct: null as number | null, valueUsd: h.valueUsd, sellOnly: true,
    })),
  ];

  const livePerps = (perpsPositions ?? []).filter(p => p.state !== 'done');
  const perpsEquity = livePerps.reduce((sum, p) => sum + positionValueUsd(p), 0);
  const topPerps = [...perpsMarkets]
    .sort((a, b) => (b.dayVolumeUsd ?? 0) - (a.dayVolumeUsd ?? 0))
    .slice(0, 3);

  return (
    <View style={styles.screen}>
      {/* Scoped to focus: the tab stays mounted under the other tabs. */}
      {isFocused && <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />}
      <ScrollView contentContainerStyle={{ paddingBottom: 32 }} showsVerticalScrollIndicator={false}>
        <View style={styles.hero}>
          <BrandFieldBackground id="investField" ringCx="100%" ringCy="20%" ringR={90} ringWidth={22} />
          <View style={styles.heroInner}>
            {/* Careful and open-ended: no promise of growth (the presale
                carries real risk), and no count of options — more may come. */}
            <Text style={styles.heroHeadline}>Explora tus opciones</Text>
            <Text style={styles.heroSub}>
              Cada opción funciona distinto y tiene sus propios riesgos. Conoce cómo funciona antes de decidir.
            </Text>
          </View>
        </View>

        <View style={styles.cards}>
          {topAccessory}
          {stocks.enabled && (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Acciones de EE. UU."
              // The label names the card; the hint carries what is on it, so
              // a screen reader hears the balance and the restriction too.
              accessibilityHint={[
                holdsStocks ? `Tu inversión: ${usd(stocks.totalUsd)}` : null,
                holdsStocks && todayDelta ? `hoy ${stocks.earnedTodayUsd >= 0 ? 'más' : 'menos'} ${todayDelta}` : null,
                'No disponible para residentes de EE.UU. ni de Brasil',
                holdsStocks ? 'Abre tus acciones' : 'Abre el explorador de acciones',
              ].filter(Boolean).join('. ')}
              onPress={() => navigation.navigate('StocksList')}
              style={({ pressed }) => [styles.card, pressed && styles.pressed]}
            >
              <View style={styles.cardHead}>
                <StocksMark size={44} />
                <View style={styles.cardHeadText}>
                  <Text style={styles.cardTitle}>Acciones de EE.UU.</Text>
                  <Text style={styles.cardSub}>
                    {holdsStocks ? 'Tu inversión' : `Fracciones de ${market.length > 0 ? `${market.length} ` : ''}empresas y ETF`}
                  </Text>
                </View>
                {holdsStocks && (
                  <View style={styles.cardValue}>
                    <Text style={styles.cardValueText}>{usd(stocks.totalUsd)}</Text>
                    {todayDelta ? (
                      <Text style={[styles.delta, stocks.earnedTodayUsd < 0 && styles.deltaDown]}>
                        hoy {stocks.earnedTodayUsd >= 0 ? '+' : '−'}{todayDelta}
                      </Text>
                    ) : null}
                  </View>
                )}
              </View>

              {tickerStrip.length > 0 && (
                <View style={styles.tickers}>
                  {tickerStrip.map(stock => {
                    const up = stock.dayChangePct >= 0;
                    return (
                      <View key={stock.ticker} style={styles.ticker}>
                        <Text style={styles.tickerName}>{stock.name}</Text>
                        <Text style={[styles.delta, !up && styles.deltaDown]}>
                          {up ? '▲' : '▼'} {formatNumber(Math.abs(stock.dayChangePct), { maximumFractionDigits: 2 })}%
                        </Text>
                      </View>
                    );
                  })}
                </View>
              )}

              <View style={[styles.cta, styles.ctaStocks]}>
                <Text style={styles.ctaText}>{holdsStocks ? 'Ver mis acciones' : 'Explorar acciones'}</Text>
                <Icon name="arrow-right" size={18} color={colors.white} />
              </View>
              {/* Same attribution as the stocks screen: the real logo. */}
              <View style={styles.partnerRow}>
                <Text style={styles.partnerText}>En alianza con</Text>
                <Image source={OndoLogo} style={styles.partnerLogo} />
                <Text style={styles.partnerBrand}>Ondo Finance</Text>
              </View>
              <Text style={styles.partner}>No disponible para residentes de EE.UU. ni de Brasil.</Text>
            </Pressable>
          )}
          {!stocks.enabled && stocks.eligibilityKnown && (
            // Not a silent gap: the U.S. and Brazil are a large share of our
            // users, and they deserve to know the option exists and why they
            // do not see it. Not tappable — there is nothing to open.
            <View
              style={[styles.card, styles.cardMuted]}
              accessible
              accessibilityLabel="Acciones de EE. UU., no disponible para tu cuenta"
            >
              <View style={styles.cardHead}>
                <View style={styles.mutedMark}><StocksMark size={44} /></View>
                <View style={styles.cardHeadText}>
                  <Text style={[styles.cardTitle, styles.mutedText]}>Acciones de EE.UU.</Text>
                  <Text style={styles.cardSub}>No disponible para tu cuenta por ahora</Text>
                </View>
              </View>
              <Text style={styles.mutedNote}>No se ofrece a residentes de EE.UU. ni de Brasil.</Text>
            </View>
          )}

          {cryptoRows.length > 0 && (cryptoEnabled || holdsCrypto) && (
            <View style={styles.card} testID="invest-crypto-card">
              <View style={styles.cardHead}>
                <View style={styles.cryptoHeadMarks}>
                  {cryptoRows.slice(0, 2).map((asset, index) => (
                    <View key={asset.symbol} style={index > 0 ? styles.cryptoHeadMarkOverlap : undefined}>
                      <CryptoAssetMark ticker={asset.ticker} category={asset.category} size={index === 0 ? 34 : 30} />
                    </View>
                  ))}
                </View>
                <View style={styles.cardHeadText}>
                  <Text style={styles.cardTitle}>Oro y Bitcoin</Text>
                  <Text style={styles.cardSub}>{holdsCrypto ? 'Tu inversión' : 'Para guardar valor, 24/7'}</Text>
                </View>
                {holdsCrypto && (
                  <View style={styles.cardValue}>
                    <Text style={styles.cardValueText}>{cryptoValueKnown ? usd(cryptoTotal) : '—'}</Text>
                  </View>
                )}
              </View>

              <View style={styles.cryptoRows}>
                {cryptoRows.map(asset => {
                  const change = asset.dayChangePct;
                  const up = (change ?? 0) >= 0;
                  return (
                    <Pressable
                      key={asset.symbol}
                      accessibilityRole="button"
                      accessibilityLabel={asset.name}
                      accessibilityHint={[
                        asset.priceUsd != null ? `Precio ${formatUsdPrice(asset.priceUsd)}` : null,
                        change != null ? `24 horas ${up ? 'más' : 'menos'} ${formatNumber(Math.abs(change), { maximumFractionDigits: 2 })}%` : null,
                        'Abre el detalle',
                      ].filter(Boolean).join('. ')}
                      onPress={() => navigation.navigate('CryptoDetail', { symbol: asset.symbol })}
                      style={({ pressed }) => [styles.cryptoRow, pressed && styles.pressed]}
                    >
                      <CryptoAssetMark ticker={asset.ticker} category={asset.category} size={36} />
                      <View style={styles.cardHeadText}>
                        <Text style={styles.cryptoName}>{asset.name}</Text>
                        <Text style={styles.cardSub}>{asset.sellOnly ? `${asset.ticker} · Solo venta` : asset.ticker}</Text>
                      </View>
                      <View style={styles.cardValue}>
                        <Text style={styles.cryptoPrice}>
                          {asset.sellOnly ? formatUsdPrice(asset.valueUsd) : formatUsdPrice(asset.priceUsd)}
                        </Text>
                        {change != null ? (
                          <Text style={[styles.delta, !up && styles.deltaDown]}>
                            {up ? '▲' : '▼'} {formatNumber(Math.abs(change), { maximumFractionDigits: 2 })}% 24h
                          </Text>
                        ) : null}
                      </View>
                      <Icon name="chevron-right" size={18} color={colors.text.light} />
                    </Pressable>
                  );
                })}
              </View>
              {/* Stated on the card: these move day and night. */}
              <Text style={styles.riskNote}>
                Su precio sube y baja todo el tiempo, también de noche y en fines de semana.
              </Text>
              <VenueAttribution venue="pancakeswap" testID="invest-crypto-venue" />
            </View>
          )}

          {(perpsEnabled || livePerps.length > 0 || perpsUnknown) && (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Futuros. ${venueA11y('hyperliquid')}`}
              accessibilityHint={livePerps.length > 0 ? `Tus posiciones: ${formatPerpUsd(perpsEquity)}` : 'Abre los mercados de futuros'}
              onPress={() => navigation.navigate('FuturesMarkets')}
              style={({ pressed }) => [styles.card, pressed && styles.pressed]}
              testID="invest-futures-card"
            >
              <View style={styles.cardHead}>
                <FuturesMark size={44} />
                <View style={styles.cardHeadText}>
                  <Text style={styles.cardTitle}>Futuros</Text>
                  <Text style={styles.cardSub}>
                    {livePerps.length > 0 ? 'Tu posición' : 'Largo o corto, con apalancamiento · 24/7'}
                  </Text>
                </View>
                {livePerps.length > 0 && (
                  <View style={styles.cardValue}>
                    <Text style={styles.cardValueText}>{formatPerpUsd(perpsEquity)}</Text>
                  </View>
                )}
              </View>

              {perpsUnknown && livePerps.length === 0 && (
                <Text style={styles.riskNote}>No pudimos leer tus futuros ahora. Tu dinero sigue a tu nombre en Hyperliquid.</Text>
              )}
              {livePerps.length > 0 ? (
                <View style={styles.cryptoRows}>
                  {livePerps.map(p => {
                    const pending = stepLabel(p.nextAction, p.state);
                    const roe = p.returnOnEquity != null ? p.returnOnEquity * 100 : null;
                    return (
                      <Pressable
                        key={p.id}
                        accessibilityRole="button"
                        accessibilityLabel={`${p.ticker} ${sideLabel(p.side)} ${p.leverage}x`}
                        accessibilityHint={pending || `Ganancia ${formatUsdSigned(p.unrealizedPnlUsd)}`}
                        onPress={() => navigation.navigate('FuturesPosition', { positionId: p.id })}
                        style={({ pressed }) => [styles.cryptoRow, pressed && styles.pressed]}
                      >
                        <PerpMarketMark ticker={p.ticker} size={36} leverage={p.leverage} badgeColor={SIDE_COLORS[p.side].solid} />
                        <View style={styles.cardHeadText}>
                          <Text style={styles.cryptoName}>{p.ticker} · {sideLabel(p.side)} {p.leverage}x</Text>
                          <Text style={[styles.cardSub, pending ? styles.pendingText : null]} numberOfLines={1}>
                            {pending || p.name}
                          </Text>
                        </View>
                        {!pending && (
                          <View style={styles.cardValue}>
                            <Text style={[styles.cryptoPrice, { color: pnlColor(p.unrealizedPnlUsd) }]}>
                              {formatUsdSigned(p.unrealizedPnlUsd)}
                            </Text>
                            <Text style={[styles.delta, { color: pnlColor(roe) }]}>{formatPctSigned(roe)}</Text>
                          </View>
                        )}
                        <Icon name="chevron-right" size={18} color={colors.text.light} />
                      </Pressable>
                    );
                  })}
                </View>
              ) : topPerps.length > 0 ? (
                <View style={styles.tickers}>
                  {topPerps.map(m => {
                    const up = (m.dayChangePct ?? 0) >= 0;
                    return (
                      <View key={m.coin} style={styles.ticker}>
                        <Text style={styles.tickerName}>{m.ticker}</Text>
                        <Text style={[styles.delta, !up && styles.deltaDown]}>
                          {up ? '▲' : '▼'} {formatNumber(Math.abs(m.dayChangePct ?? 0), { maximumFractionDigits: 2 })}%
                        </Text>
                      </View>
                    );
                  })}
                </View>
              ) : null}

              <View style={[styles.cta, styles.ctaFutures]}>
                <Text style={styles.ctaText}>{livePerps.length > 0 ? 'Ver futuros' : 'Explorar futuros'}</Text>
                <Icon name="arrow-right" size={18} color={colors.white} />
              </View>
              {/* The riskiest product short of the presale: said on the card. */}
              <Text style={styles.riskNote}>
                Alto riesgo: con apalancamiento puedes perder todo el margen de una posición.
              </Text>
              <VenueAttribution venue="hyperliquid" testID="invest-futures-venue" />
            </Pressable>
          )}

          <Pressable
            accessibilityRole="button"
            accessibilityLabel="$CONFIO"
            onPress={() => navigation.navigate('ConfioPresale')}
            style={({ pressed }) => [styles.card, pressed && styles.pressed]}
          >
            <View style={styles.cardHead}>
              <Image source={require('../assets/png/CONFIO.png')} style={styles.confioLogo} />
              <View style={styles.cardHeadText}>
                <Text style={styles.cardTitle}>{presaleLive ? '$CONFIO · Preventa' : '$CONFIO'}</Text>
                <Text style={styles.cardSub}>
                  {claimsUnlocked
                    ? 'Tus tokens de la preventa están listos'
                    : presaleLive
                      ? [phase?.name, price != null ? `${usd(price, price < 1 ? 4 : 2)} por token` : null].filter(Boolean).join(' · ')
                      : 'La moneda de Confío'}
                </Text>
              </View>
              {presaleLive && (
                <View style={styles.liveBadge}>
                  <View style={styles.liveDot} />
                  <Text style={styles.liveText}>Activa</Text>
                </View>
              )}
            </View>

            {presaleLive && price == null && (
              <Text style={styles.riskNote}>
                {curveLoading ? 'Cargando datos de la preventa…' : 'Datos de la preventa no disponibles por ahora.'}
              </Text>
            )}
            {presaleLive && progress != null && (
              <View style={styles.progressBlock}>
                <View style={styles.progressTrack}>
                  <View style={[styles.progressFill, { width: `${progress}%` }]} />
                </View>
                <View style={styles.progressMeta}>
                  <Text style={styles.progressRaised}>
                    {raised != null ? usd(raised, 0) : '—'}
                    {goal ? <Text style={styles.progressOf}>{` · meta ${usd(goal, 0)}`}</Text> : null}
                  </Text>
                  {participants != null && participants > 0 ? (
                    <Text style={styles.progressOf}>
                      {`${formatNumber(participants, { maximumFractionDigits: 0 })} participantes`}
                    </Text>
                  ) : null}
                </View>
              </View>
            )}

            <View style={[styles.cta, styles.ctaConfio]}>
              <Text style={styles.ctaText}>
                {claimsUnlocked ? 'Reclamar mis tokens' : presaleLive ? 'Participar en la preventa' : 'Conocer $CONFIO'}
              </Text>
              <Icon name="arrow-right" size={18} color={colors.white} />
            </View>
            {presaleLive && (
              <>
                {/* Stated on the card itself, not only inside the flow: a
                    presale is the riskiest thing on this tab. */}
                <Text style={styles.riskNote}>
                  Un token nuevo puede perder valor o tener poca liquidez. Participa solo con lo que puedas arriesgar.
                </Text>
                <Text style={styles.partner}>No disponible para residentes de EE.UU.</Text>
              </>
            )}
          </Pressable>
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  hero: { backgroundColor: colors.heroField, overflow: 'hidden' },
  heroInner: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 56 },
  heroHeadline: { fontSize: 26, fontWeight: '800', color: colors.white, marginTop: 4 },
  heroSub: { fontSize: 15, lineHeight: 21, color: colors.white, opacity: 0.9, marginTop: 4 },

  cards: { paddingHorizontal: 16, marginTop: -36, gap: 14 },
  card: {
    backgroundColor: colors.white,
    borderRadius: 22,
    padding: 18,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.06,
    shadowRadius: 12,
    elevation: 3,
  },
  pressed: { opacity: 0.85 },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  cardHeadText: { flex: 1 },
  cardTitle: { fontSize: 18, fontWeight: '800', color: colors.text.primary },
  cardSub: { fontSize: 13, color: colors.text.secondary, marginTop: 2 },
  cardValue: { alignItems: 'flex-end' },
  cardValueText: { fontSize: 18, fontWeight: '800', color: colors.text.primary },
  confioLogo: { width: 44, height: 44, borderRadius: 22 },
  cryptoHeadMarks: { flexDirection: 'row', alignItems: 'center', width: 44 },
  cryptoHeadMarkOverlap: { marginLeft: -20, marginTop: 14 },
  cryptoRows: { marginTop: 12 },
  cryptoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 56,
    paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  cryptoName: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  cryptoPrice: { fontSize: 15, fontWeight: '700', color: colors.text.primary },

  tickers: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 14 },
  ticker: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: colors.neutral,
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  tickerName: { fontSize: 13, fontWeight: '600', color: colors.text.primary },
  delta: { fontSize: 12, fontWeight: '700', color: colors.primaryDark },
  deltaDown: { color: colors.error.icon },

  liveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: '#EDE9FE',
    borderRadius: 12,
    paddingHorizontal: 9,
    paddingVertical: 4,
  },
  liveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.secondary },
  liveText: { fontSize: 12, fontWeight: '700', color: colors.secondaryDark },

  progressBlock: { marginTop: 16 },
  progressTrack: { height: 10, borderRadius: 5, backgroundColor: '#EDE9FE', overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 5, backgroundColor: colors.secondary },
  progressMeta: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 8 },
  progressRaised: { fontSize: 14, fontWeight: '800', color: colors.text.primary },
  progressOf: { fontSize: 13, fontWeight: '400', color: colors.text.secondary },

  cta: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginTop: 16,
    height: 48,
    borderRadius: 14,
  },
  ctaStocks: { backgroundColor: colors.primaryDark },
  ctaConfio: { backgroundColor: colors.secondaryDark },
  ctaFutures: { backgroundColor: '#0F172A' },
  pendingText: { color: '#92400E', fontWeight: '600' },
  ctaText: { fontSize: 15, fontWeight: '700', color: colors.white },
  partner: { fontSize: 12, color: colors.text.light, textAlign: 'center', marginTop: 10 },
  partnerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 12 },
  partnerText: { fontSize: 12, color: colors.text.light },
  partnerLogo: { width: 16, height: 16, borderRadius: 4 },
  partnerBrand: { fontSize: 12, fontWeight: '700', color: colors.text.secondary },
  cardMuted: { backgroundColor: colors.neutral, shadowOpacity: 0, elevation: 0 },
  mutedMark: { opacity: 0.45 },
  mutedText: { color: colors.text.secondary },
  mutedNote: { fontSize: 13, lineHeight: 18, color: colors.text.secondary, marginTop: 12 },
  riskNote: { fontSize: 12, lineHeight: 17, color: colors.text.secondary, textAlign: 'center', marginTop: 12 },

  employee: { alignItems: 'center', justifyContent: 'center', padding: 32, gap: 8 },
  employeeTitle: { fontSize: 20, fontWeight: '700', color: colors.text.primary },
  employeeText: { fontSize: 15, lineHeight: 22, color: colors.text.secondary, textAlign: 'center' },
});
