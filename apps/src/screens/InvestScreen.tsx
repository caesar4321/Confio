import React, { useCallback, useMemo } from 'react';
import { Image, Pressable, ScrollView, StatusBar, StyleSheet, Text, View } from 'react-native';
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
import OndoLogo from '../assets/png/Ondo.png';
import { FEATURED_STOCK_TICKERS } from '../config/stockPresentation';
import { colors } from '../config/theme';
import { useAccount } from '../contexts/AccountContext';
import { useGmMarket } from '../hooks/useGmMarket';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { MainStackParamList } from '../types/navigation';
import { useNumberFormat } from '../utils/numberFormatting';
import { formatUsdDeltaAbs } from '../utils/savingsFormat';

type Nav = NativeStackNavigationProp<MainStackParamList>;

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
export const InvestScreen = () => {
  const navigation = useNavigation<Nav>();
  const isFocused = useIsFocused();
  const { formatNumber } = useNumberFormat();
  const { stocks } = useSavingsPortfolio();
  const { activeAccount } = useAccount();
  const isEmployee = Boolean(activeAccount?.isEmployee);

  const { stocks: market } = useGmMarket(stocks.enabled && !isEmployee);
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
      refetchPresale().catch(() => {});
      refetchStatus().catch(() => {});
      refetchCurve().catch(() => {});
      if (claimsOpen) refetchOnchain().catch(() => {});
    }, [isEmployee, claimsOpen, refetchPresale, refetchStatus, refetchCurve, refetchOnchain]),
  );

  const usd = (v: number, digits = 2) =>
    `$${formatNumber(v, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

  // Today's market in three names people know: the featured indices/metals.
  const tickerStrip = useMemo(
    () => FEATURED_STOCK_TICKERS.slice(0, 3)
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

  return (
    <View style={styles.screen}>
      {/* Scoped to focus: the tab stays mounted under the other tabs. */}
      {isFocused && <StatusBar barStyle="light-content" backgroundColor={colors.primary} />}
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
  hero: { backgroundColor: colors.primary, overflow: 'hidden' },
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
