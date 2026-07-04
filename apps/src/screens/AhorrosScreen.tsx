// Ahorros e Inversiones — portfolio hub (Federico's "bolsa" architecture),
// designed for its END STATE from day one: savings (Confío Dollar+) and US
// stocks (Ondo Stocks) live side by side so enabling stocks later never
// reflows the screen.
//
// Locked design decisions this screen encodes:
// - Accumulating-share model stays invisible: USD values only, never share
//   counts. "cUSD+" is a product name, not a displayed unit.
// - The rate is live and server-driven (oracle gross minus Confío's 15%
//   share). Copy never hardcodes "3%" — rates float with US Treasuries.
// - Conversion cost is passed through transparently before confirming.
// - Stocks section gates on portfolio.stocks.enabled (decision 2dcfada5:
//   server flag at release, dark until demand signal; geofence US/CA/BR).
// - Savings language is "ahorro/rendimiento" (bank-replacement mental model);
//   only the stocks block says "inversión". No crypto jargon anywhere.

import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  Image,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { useNumberFormat } from '../utils/numberFormatting';
import { GET_MY_BALANCES } from '../apollo/queries';
import { useAhorrosPortfolio } from '../hooks/useAhorrosPortfolio';
import { RouteSheet, RouteOption } from '../components/RouteSheet';
import { TickerLogo } from '../components/TickerLogo';
import { MovementRow } from '../components/MovementRow';
import { useGmMarket } from '../hooks/useGmMarket';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';
import OndoLogo from '../assets/png/Ondo.png';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

const EDUCATION_CARDS = [
  {
    icon: 'shield',
    title: 'Respaldado por bonos del Tesoro de EE.UU.',
    body:
      'Tu ahorro está respaldado 1:1 por USDY de Ondo Finance, un token ' +
      'garantizado por bonos del Tesoro de Estados Unidos.',
  },
  {
    icon: 'clock',
    title: 'Retira cuando quieras',
    body: 'Sin plazos, sin penalidades. Tu dinero vuelve a cUSD al instante.',
  },
  {
    icon: 'percent',
    title: 'Sin comisiones ocultas',
    body:
      'La tasa que ves ya descuenta nuestra comisión. Si un movimiento ' +
      'tiene costo, lo ves antes de confirmar — nunca después.',
  },
] as const;

export const AhorrosScreen = () => {
  const navigation = useNavigation<NavProp>();
  const { formatNumber } = useNumberFormat();
  const portfolio = useAhorrosPortfolio();
  const { stocks: gmStocks } = useGmMarket();
  const featuredTickers = gmStocks.slice(0, 5);
  const { savings, stocks, movements } = portfolio;

  const { data: balancesData } = useQuery(GET_MY_BALANCES, {
    fetchPolicy: 'cache-and-network',
  });
  const cusdAvailable = parseFloat(balancesData?.myBalances?.cusd || '0') || 0;

  const hasSavings = savings.balanceUsd > 0;
  const hasStocks = stocks.positions.length > 0;
  const hasAnything = portfolio.totalUsd > 0;

  const fmtUsd = (v: number, digits = 2) =>
    `$${formatNumber(v, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

  const [ahorrarSheet, setAhorrarSheet] = useState(false);
  const [retirarSheet, setRetirarSheet] = useState(false);

  // ── Ahorrar sources ─────────────────────────────────────────────────────
  // Bank first: new money onramps DIRECT to the savings chain (no conversion
  // leg at all). Converting existing cUSD is for money already inside — a
  // valid move, not the promoted entry. Costs are server-quoted in-flow,
  // never printed here.
  const ahorrarOptions: RouteOption[] = [
    {
      icon: 'credit-card',
      title: 'Recargar desde mi banco',
      subtitle: 'Dinero nuevo llega directo a tu ahorro, sin conversión',
      onPress: () => {
        // TODO(cusd+): TopUp with destination=cusd_plus so Koywe delivers on
        // the savings chain (USDT-BSC) — never onramp-then-bridge.
        Alert.alert('Muy pronto', 'La recarga directa al ahorro abre en breve.');
      },
    },
    {
      icon: 'refresh-cw',
      title: 'Desde mi saldo cUSD',
      subtitle:
        cusdAvailable > 0
          ? `${fmtUsd(cusdAvailable)} disponibles · verás el costo antes de confirmar`
          : 'No tienes cUSD disponible ahora',
      disabled: cusdAvailable <= 0,
      onPress: () => navigation.navigate('ConvertAhorro'),
    },
  ];

  // ── Retirar destinations ────────────────────────────────────────────────
  const retirarOptions: RouteOption[] = [
    {
      icon: 'dollar-sign',
      title: 'A mi saldo cUSD',
      subtitle: 'Para enviar, pagar o guardar · al instante',
      onPress: () => navigation.navigate('RetirarAhorro'),
    },
    {
      icon: 'home',
      title: 'A mi banco',
      subtitle: 'Retiro directo desde tu ahorro',
      onPress: () => {
        // TODO(cusd+): direct off-ramp from the savings chain via Koywe —
        // skips the double hop through cUSD/Algorand.
        Alert.alert('Muy pronto', 'El retiro a tu banco abre en breve.');
      },
    },
  ];

  const onExplorarAcciones = () => navigation.navigate('AccionesList');

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <View style={styles.headerTopRow}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn}>
              <Icon name="arrow-left" size={24} color="#fff" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Ahorros e Inversiones</Text>
            <View style={styles.headerIconBtn} />
          </View>

          {/* Hero: ONE portfolio number (savings + stocks). Empty state sells
              the outcome, not the product. */}
          <View style={styles.hero}>
            <Text style={styles.heroLabel}>Valor total</Text>
            <Text style={styles.heroAmount}>{fmtUsd(portfolio.totalUsd)}</Text>
            {hasAnything ? (
              <View style={styles.heroTickerRow}>
                <Icon name="trending-up" size={14} color="#fff" />
                <Text style={styles.heroTicker}>
                  Hoy {portfolio.earnedTodayUsd >= 0 ? '+' : ''}
                  {fmtUsd(portfolio.earnedTodayUsd)}
                  {'  ·  '}Este mes +{fmtUsd(portfolio.earnedMonthUsd)}
                </Text>
              </View>
            ) : (
              <Text style={styles.heroEmptyHint}>Tu dinero puede crecer mientras duerme</Text>
            )}
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        {/* ── Ahorro: Confío Dollar+ ──────────────────────────────────────── */}
        <Text style={styles.sectionTitle}>Ahorro</Text>
        <View style={styles.card}>
          <View style={styles.productRow}>
            <View style={styles.productLogoWrap}>
              <Image source={cUSDPlusLogo} style={styles.productLogo} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.productName}>Confío Dollar+</Text>
              <Text style={styles.productSymbol}>cUSD+</Text>
            </View>
            {hasSavings ? (
              <View style={{ alignItems: 'flex-end' }}>
                <Text style={styles.productValue}>{fmtUsd(savings.balanceUsd)}</Text>
                <Text style={styles.productDayChange}>
                  hoy +{fmtUsd(savings.earnedTodayUsd)}
                </Text>
              </View>
            ) : (
              <View style={styles.ratePill}>
                <Text style={styles.ratePillText}>
                  ~{formatNumber(savings.netApyPct, { maximumFractionDigits: 1 })}% anual
                </Text>
              </View>
            )}
          </View>

          {hasSavings && (
            <View style={styles.rateLineRow}>
              <View style={styles.rateDot} />
              <Text style={styles.rateLineText}>
                Rindiendo ~{formatNumber(savings.netApyPct, { maximumFractionDigits: 1 })}% anual
              </Text>
            </View>
          )}

          <Text style={styles.backedLine}>
            Respaldado por bonos del Tesoro de EE.UU. · La tasa varía con los bonos y ya
            descuenta nuestra comisión
          </Text>

          <View style={styles.ctaRow}>
            <TouchableOpacity style={styles.ctaPrimary} onPress={() => setAhorrarSheet(true)} activeOpacity={0.85}>
              <Icon name="arrow-down-circle" size={18} color="#fff" />
              <Text style={styles.ctaPrimaryText}>Ahorrar</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.ctaSecondary, !hasSavings && styles.ctaDisabled]}
              onPress={() => setRetirarSheet(true)}
              disabled={!hasSavings}
              activeOpacity={0.85}
            >
              <Text style={[styles.ctaSecondaryText, !hasSavings && styles.ctaDisabledText]}>
                Retirar
              </Text>
            </TouchableOpacity>
          </View>

          {cusdAvailable > 0 && !hasSavings && (
            <View style={styles.availableRow}>
              <Icon name="info" size={13} color={colors.text.secondary} />
              <Text style={styles.availableText}>
                Tienes {fmtUsd(cusdAvailable)} en cUSD disponibles para ahorrar
              </Text>
            </View>
          )}
        </View>

        {/* ── Inversión: Acciones de EE.UU. (Ondo Stocks) ─────────────────── */}
        {stocks.enabled && (
          <>
            <View style={styles.sectionHeaderRow}>
              <Text style={styles.sectionTitle}>Inversión</Text>
              {/* TODO(gm): market status from the GM API (open/closed/paused) */}
              <View style={styles.marketChip}>
                <View style={styles.marketDot} />
                <Text style={styles.marketChipText}>Mercado abierto</Text>
              </View>
            </View>
            <View style={styles.card}>
              <View style={styles.productRow}>
                <View style={[styles.productLogoWrap, styles.stocksLogoWrap]}>
                  <Icon name="bar-chart-2" size={22} color="#fff" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.productName}>Acciones de EE.UU.</Text>
                  <Text style={styles.productSymbol}>Tesla, NVIDIA, Apple y 200+ más</Text>
                </View>
                {hasStocks && (
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={styles.productValue}>{fmtUsd(stocks.totalUsd)}</Text>
                    <Text
                      style={[
                        styles.productDayChange,
                        stocks.earnedTodayUsd < 0 && styles.dayChangeNegative,
                      ]}
                    >
                      hoy {stocks.earnedTodayUsd >= 0 ? '+' : ''}
                      {fmtUsd(stocks.earnedTodayUsd)}
                    </Text>
                  </View>
                )}
              </View>

              {hasStocks ? (
                <View style={styles.positionsList}>
                  {stocks.positions.map((p) => (
                    <TouchableOpacity
                      key={p.ticker}
                      style={styles.positionRow}
                      activeOpacity={0.8}
                      onPress={() => navigation.navigate('StockDetail', { ticker: p.ticker })}
                    >
                      <View style={styles.tickerCircleSmall}>
                        <Text style={styles.tickerCircleSmallText}>{p.ticker.slice(0, 4)}</Text>
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.positionTicker}>{p.ticker}</Text>
                        <Text style={styles.positionName}>{p.name}</Text>
                      </View>
                      <View style={{ alignItems: 'flex-end' }}>
                        <Text style={styles.positionValue}>{fmtUsd(p.valueUsd)}</Text>
                        <Text
                          style={[
                            styles.positionChange,
                            p.dayChangePct < 0 && styles.dayChangeNegative,
                          ]}
                        >
                          {p.dayChangePct >= 0 ? '+' : ''}
                          {formatNumber(p.dayChangePct, { maximumFractionDigits: 2 })}%
                        </Text>
                      </View>
                    </TouchableOpacity>
                  ))}
                </View>
              ) : (
                <>
                  <View style={styles.tickerStrip}>
                    {featuredTickers.map((t) => (
                      <TouchableOpacity
                        key={t.ticker}
                        style={styles.tickerItem}
                        activeOpacity={0.8}
                        onPress={() => navigation.navigate('StockDetail', { ticker: t.ticker })}
                      >
                        <TickerLogo ticker={t.ticker} color={t.color} logoUrl={t.logoUrl} size={44} />
                        <Text style={styles.tickerName} numberOfLines={1}>
                          {t.name}
                        </Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                  <Text style={styles.stocksEmptyHint}>
                    Invierte en las empresas que conoces, desde $1, sin abrir cuenta en EE.UU.
                  </Text>
                </>
              )}

              <TouchableOpacity
                style={styles.ctaOutline}
                onPress={onExplorarAcciones}
                activeOpacity={0.85}
              >
                <Text style={styles.ctaOutlineText}>
                  {hasStocks ? 'Explorar más acciones' : 'Explorar acciones'}
                </Text>
                <Icon name="arrow-right" size={16} color={colors.primaryDark} />
              </TouchableOpacity>
            </View>
          </>
        )}

        {/* Partnership: real logo, nominative use — Ondo is the issuer of both
            USDY (savings backing) and the tokenized stocks, so this row
            belongs to the product cards above it, not to the history. */}
        <View style={styles.partnerRow}>
          <Text style={styles.partnerText}>En alianza con</Text>
          <Image source={OndoLogo} style={styles.partnerLogo} />
          <Text style={styles.partnerBrand}>Ondo Finance</Text>
        </View>

        {/* Movimientos — house pattern: history right under the balance
            cards. Bounded preview (recent few) so the sections below stay
            reachable; the unbounded list lives in AhorrosMovimientos. */}
        <View style={styles.sectionHeaderRow}>
          <Text style={styles.sectionTitle}>Movimientos</Text>
          {movements.length > 0 && (
            <TouchableOpacity
              style={styles.verTodosBtn}
              onPress={() => navigation.navigate('AhorrosMovimientos')}
              activeOpacity={0.7}
            >
              <Text style={styles.verTodosText}>Ver todos</Text>
              <Icon name="chevron-right" size={15} color={colors.primaryDark} />
            </TouchableOpacity>
          )}
        </View>
        {movements.length === 0 ? (
          <View style={styles.movementsEmpty}>
            <Icon name="clock" size={22} color={colors.text.light} />
            <Text style={styles.movementsEmptyText}>
              Aquí verás tus ahorros, retiros, compras y el rendimiento que ganas.
            </Text>
          </View>
        ) : (
          <View style={styles.card}>
            {movements.slice(0, 4).map((m, idx) => (
              <MovementRow key={m.id} movement={m} topBorder={idx > 0} />
            ))}
          </View>
        )}

        {/* Education (savings-focused; stocks education lives in its flow) */}
        <Text style={styles.sectionTitle}>¿Cómo funciona?</Text>
        {EDUCATION_CARDS.map((c) => (
          <View key={c.icon} style={styles.eduCard}>
            <View style={styles.eduIconWrap}>
              <Icon name={c.icon} size={18} color={colors.primaryDark} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.eduTitle}>{c.title}</Text>
              <Text style={styles.eduBody}>{c.body}</Text>
            </View>
          </View>
        ))}

        {/* Honest footer: floating rate, market risk for stocks, no guarantees */}
        <View style={styles.disclaimer}>
          <Icon name="info" size={14} color={colors.accent} />
          <Text style={styles.disclaimerText}>
            El rendimiento del ahorro proviene de bonos del Tesoro de EE.UU. vía USDY (Ondo
            Finance) y varía día a día; no es una tasa fija ni garantizada.
            {stocks.enabled
              ? ' Las acciones pueden subir o bajar de valor — invierte solo lo que puedas mantener.'
              : ''}{' '}
            Verás todos los costos antes de confirmar cualquier operación.
          </Text>
        </View>
      </ScrollView>

      <RouteSheet
        visible={ahorrarSheet}
        title="¿Desde dónde quieres ahorrar?"
        options={ahorrarOptions}
        onClose={() => setAhorrarSheet(false)}
      />
      <RouteSheet
        visible={retirarSheet}
        title="¿A dónde quieres retirar?"
        options={retirarOptions}
        onClose={() => setRetirarSheet(false)}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: { backgroundColor: colors.primary, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 24 },
  headerTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },

  hero: { alignItems: 'center', marginTop: 16 },
  heroLabel: { fontSize: 13, color: '#fff', opacity: 0.85 },
  heroAmount: { fontSize: 40, fontWeight: 'bold', color: '#fff', marginTop: 4 },
  heroTickerRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8 },
  heroTicker: { fontSize: 13, color: '#fff', opacity: 0.9 },
  heroEmptyHint: { fontSize: 13, color: '#fff', opacity: 0.85, marginTop: 8 },

  scrollContent: { padding: 16, paddingBottom: 40 },

  sectionTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text.primary,
    marginBottom: 10,
    marginTop: 4,
  },
  sectionHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  marketChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: '#fff',
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginBottom: 10,
  },
  marketDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#10B981' },
  marketChipText: { fontSize: 11, fontWeight: '600', color: colors.text.secondary },

  card: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
  },

  productRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  productLogoWrap: { width: 44, height: 44 },
  stocksLogoWrap: {
    borderRadius: 22,
    backgroundColor: '#1D4ED8',
    alignItems: 'center',
    justifyContent: 'center',
  },
  productLogo: { width: 44, height: 44, borderRadius: 22 },
  productName: { fontSize: 17, fontWeight: '700', color: colors.text.primary },
  productSymbol: { fontSize: 13, color: colors.text.secondary, marginTop: 1 },
  productValue: { fontSize: 17, fontWeight: '700', color: colors.text.primary },
  productDayChange: { fontSize: 12, fontWeight: '600', color: colors.primaryDark, marginTop: 1 },
  dayChangeNegative: { color: '#DC2626' },

  ratePill: {
    backgroundColor: colors.primaryLight,
    borderRadius: 14,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  ratePillText: { fontSize: 14, fontWeight: '700', color: colors.primaryDark },

  rateLineRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 12 },
  rateDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.primaryDark },
  rateLineText: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },

  backedLine: { fontSize: 12, color: colors.text.secondary, marginTop: 12, lineHeight: 17 },

  ctaRow: { flexDirection: 'row', gap: 10, marginTop: 14 },
  ctaPrimary: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 13,
  },
  ctaPrimaryText: { color: '#fff', fontSize: 15, fontWeight: '700' },
  ctaSecondary: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surfaceMuted,
    borderRadius: 12,
    paddingVertical: 13,
  },
  ctaSecondaryText: { color: colors.text.primary, fontSize: 15, fontWeight: '700' },
  ctaDisabled: { opacity: 0.5 },
  ctaDisabledText: { color: colors.text.light },
  ctaOutline: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    borderWidth: 1.5,
    borderColor: colors.primaryDark,
    borderRadius: 12,
    paddingVertical: 12,
    marginTop: 14,
  },
  ctaOutlineText: { color: colors.primaryDark, fontSize: 15, fontWeight: '700' },

  availableRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 12 },
  availableText: { fontSize: 12, color: colors.text.secondary, flex: 1 },

  tickerStrip: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 16,
    paddingHorizontal: 2,
  },
  tickerItem: { alignItems: 'center', width: 56 },
  tickerCircle: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tickerCircleText: { color: '#fff', fontSize: 11, fontWeight: '800' },
  tickerName: { fontSize: 10, color: colors.text.secondary, marginTop: 5 },
  stocksEmptyHint: {
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 14,
    lineHeight: 17,
  },

  positionsList: { marginTop: 8 },
  positionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: colors.surfaceMuted,
  },
  tickerCircleSmall: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: '#1D4ED8',
    alignItems: 'center',
    justifyContent: 'center',
  },
  tickerCircleSmallText: { color: '#fff', fontSize: 9, fontWeight: '800' },
  positionTicker: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  positionName: { fontSize: 11, color: colors.text.secondary },
  positionValue: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  positionChange: { fontSize: 11, fontWeight: '600', color: colors.primaryDark },

  movementsEmpty: {
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 20,
    marginBottom: 16,
    gap: 8,
  },
  movementsEmptyText: {
    fontSize: 12,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 17,
  },
  verTodosBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    marginBottom: 10,
  },
  verTodosText: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },

  partnerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginBottom: 16,
    marginTop: -4,
  },
  partnerText: { fontSize: 12, color: colors.text.light },
  partnerLogo: { width: 16, height: 16, borderRadius: 4 },
  partnerBrand: { fontSize: 12, fontWeight: '700', color: colors.text.secondary },

  eduCard: {
    flexDirection: 'row',
    gap: 12,
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 14,
    marginBottom: 10,
  },
  eduIconWrap: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  eduTitle: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  eduBody: { fontSize: 13, color: colors.text.secondary, marginTop: 3, lineHeight: 18 },

  disclaimer: {
    flexDirection: 'row',
    gap: 8,
    backgroundColor: colors.surfaceMuted,
    borderRadius: 12,
    padding: 12,
    marginTop: 6,
  },
  disclaimerText: { flex: 1, fontSize: 11, color: colors.text.secondary, lineHeight: 16 },
});
