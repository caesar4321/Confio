// The primary-dollar ACCOUNT surface (IA inversion, 2026-07-30). Two
// variants off the same screen, keyed on savings.enabled:
// - Eligible: "Confío Dollar+" — vault position + yield, Ahorrar/Retirar.
// - Geo-ineligible: "Confío Dollar" — raw wallet USDT branded as the plain
//   dollar (USDT only ever appears in fine print), Recibir/Enviar/Retirar.
// Stocks moved OUT to StocksListScreen + their own home row: investments
// have red days and belong visually apart from the payment dollar.
//
// Locked design decisions this screen encodes:
// - Accumulating-share model stays invisible: USD values only, never share
//   counts. "cUSD+" is a product name, not a displayed unit.
// - The rate is live and server-driven (oracle gross minus Confío's 15%
//   share). Copy never hardcodes "3%" — rates float with US Treasuries.
// - Savings language is "ahorro/rendimiento" (bank-replacement mental model).
//   No crypto jargon anywhere; raw USDT is "dólares digitales" in fine print.

import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  Image,
  Alert,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { gql, useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { useNumberFormat } from '../utils/numberFormatting';
import { GET_MY_BALANCES } from '../apollo/queries';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { formatUsdDeltaAbs } from '../utils/savingsFormat';
import { RouteSheet, RouteOption } from '../components/RouteSheet';
import { MovementRow } from '../components/MovementRow';
import { useSavingsResume } from '../hooks/useSavingsResume';
import { useAuth } from '../contexts/AuthContext';
import { useCountry } from '../contexts/CountryContext';
import { isKoyweRoutingEnabledForCountry } from '../config/env';
import { CUSD_CONVERSION_UI_ENABLED } from '../config/features';
import OndoLogo from '../assets/png/Ondo.png';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

// Cache-first vault-address lookup for the pull-to-refresh mint kick (same
// query useSavingsResume warms, so this is normally a cache hit).
const VAULT_ADDRESS_FOR_REFRESH = gql`
  query CusdPlusVaultAddressRefresh {
    cusdPlusConvertParams {
      vaultAddress
    }
  }
`;

export const SavingsScreen = () => {
  const navigation = useNavigation<NavProp>();
  const { formatNumber } = useNumberFormat();
  const portfolio = useSavingsPortfolio();
  // Finish any pending cUSD+ mints (leg C) on mount + every re-foreground —
  // the savings sibling of the USDC→cUSD auto-swap resume contract.
  useSavingsResume();
  const { savings, movements, usdtBalanceUsd } = portfolio;
  // The variant switch: eligible = yield account, ineligible = plain dollar.
  const isYieldVariant = savings.enabled;

  const { data: balancesData, refetch: refetchBalances } = useQuery(GET_MY_BALANCES, {
    fetchPolicy: 'cache-and-network',
  });
  const cusdAvailable = parseFloat(balancesData?.myBalances?.cusd || '0') || 0;

  // Pull-to-refresh: the "did my deposit arrive?" gesture. Kicks the pending
  // mint resume (same leg the foreground listener runs) and force-refetches
  // both balance queries; server-side caches are ~30s, so this is as fresh
  // as the server will serve.
  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      try {
        const { apolloClient } = await import('../apollo/client');
        const { resumeSavingsMints } = await import('../services/savingsLegC');
        const { data: vp } = await apolloClient.query({
          query: VAULT_ADDRESS_FOR_REFRESH,
          fetchPolicy: 'cache-first',
        });
        const vaultAddress = vp?.cusdPlusConvertParams?.vaultAddress;
        if (vaultAddress) await resumeSavingsMints(vaultAddress);
      } catch {}
      await Promise.all([portfolio.refetch(), refetchBalances()]);
    } catch {
      // Refresh is best-effort; the 60s poll self-heals.
    } finally {
      setRefreshing(false);
    }
  }, [portfolio.refetch, refetchBalances]);

  const hasSavings = savings.balanceUsd > 0;
  const hasUsdt = usdtBalanceUsd > 0;
  // The account total this screen owns: vault position + raw wallet USDT.
  // Stocks are deliberately absent — they live in AccionesList now.
  const accountTotalUsd = savings.balanceUsd + usdtBalanceUsd;
  const hasAnything = accountTotalUsd > 0;

  // Adaptive precision (2 dp, 3 dp under 1¢) so small savers still see the
  // daily tick; below display resolution the part is omitted entirely —
  // "+$0.00" reads as broken.
  // Savings-only deltas since the stocks split (stocks report in their row).
  const tickerParts: string[] = [];
  const hoyDelta = formatUsdDeltaAbs(savings.earnedTodayUsd);
  if (hoyDelta) {
    tickerParts.push(`Hoy ${savings.earnedTodayUsd >= 0 ? '+' : '\u2212'}${hoyDelta}`);
  }
  const mesDelta = formatUsdDeltaAbs(savings.earnedMonthUsd);
  if (mesDelta && savings.earnedMonthUsd > 0) {
    tickerParts.push(`Este mes +${mesDelta}`);
  }

  const fmtUsd = (v: number, digits = 2) =>
    `$${formatNumber(v, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

  const [saveSheet, setSaveSheet] = useState(false);
  const [withdrawSheet, setWithdrawSheet] = useState(false);

  // Ramp routing mirrors TopUp/Sell: Koywe countries use the Koywe rail
  // (bank off-ramp still pending there); everyone else rides Guardarian,
  // whose savings sell (USDT-BSC) is live.
  const { userProfile } = useAuth() as any;
  const { selectedCountry, userCountry } = useCountry();
  const rampCountryCode =
    userProfile?.phoneCountry || selectedCountry?.[2] || userCountry?.[2] || 'AR';
  const isKoyweCountry = isKoyweRoutingEnabledForCountry(rampCountryCode);

  // ── Ahorrar sources ─────────────────────────────────────────────────────
  // Bank first: new money onramps DIRECT to the savings chain (no conversion
  // leg at all). Converting existing cUSD is for money already inside — a
  // valid move, not the promoted entry. Costs are server-quoted in-flow,
  // never printed here.
  const saveOptions: RouteOption[] = [
    {
      icon: 'credit-card',
      title: 'Recargar desde mi banco',
      subtitle: 'Dinero nuevo llega directo a tu ahorro, sin conversión',
      onPress: () => {
        // Savings rail: Koywe delivers USDT-BSC to the user's own address.
        navigation.navigate('TopUp', { destination: 'cusd_plus' });
      },
    },
    {
      icon: 'download',
      title: 'Recibir USDT',
      subtitle: 'Red BNB Smart Chain (BEP-20) · desde un exchange u otra billetera',
      onPress: () => navigation.navigate('ReceiveSavings', { destination: 'cusd_plus' }),
    },
    // cUSD → cUSD+ conversion hidden while the bridge leg has no home
    // (see CUSD_CONVERSION_UI_ENABLED).
    ...(CUSD_CONVERSION_UI_ENABLED
      ? [
          {
            icon: 'refresh-cw',
            title: 'Desde mi saldo cUSD',
            subtitle:
              cusdAvailable > 0
                ? `${fmtUsd(cusdAvailable)} disponibles · verás el costo antes de confirmar`
                : 'No tienes cUSD disponible ahora',
            disabled: cusdAvailable <= 0,
            onPress: () => navigation.navigate('ConvertSavings'),
          } as RouteOption,
        ]
      : []),
  ];

  // ── Retirar destinations ────────────────────────────────────────────────
  // Mirrors the Ahorrar sheet: the outside world (bank, direct rail — no
  // conversion hop) leads; the in-app destination comes second.
  const withdrawOptions: RouteOption[] = [
    {
      icon: 'home',
      title: 'A mi banco',
      subtitle: 'Directo desde tu ahorro, sin conversión',
      onPress: () => {
        if (!isKoyweCountry) {
          // Guardarian rail: sell USDT-BSC straight from the savings vault
          // (redeemToUsdt pays the ramp's deposit address directly).
          setWithdrawSheet(false);
          navigation.navigate('Sell', { destination: 'cusd_plus' });
          return;
        }
        // TODO(cusd+): direct off-ramp from the savings chain via Koywe —
        // skips the double hop through cUSD/Algorand.
        Alert.alert('Muy pronto', 'El retiro a tu banco abre en breve.');
      },
    },
    // cUSD+ → cUSD conversion hidden alongside the forward leg.
    ...(CUSD_CONVERSION_UI_ENABLED
      ? [
          {
            icon: 'dollar-sign',
            title: 'A mi saldo cUSD',
            subtitle: 'Para enviar, pagar o guardar · al instante',
            onPress: () => navigation.navigate('WithdrawSavings'),
          } as RouteOption,
        ]
      : []),
  ];

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        {/* Brand field: emerald gradient + coin ring, padding on headerInner
            (Yoga insets absolute children by parent padding). */}
        <View style={styles.header}>
          <BrandFieldBackground id="savingsField" ringCy="28%" />
          <View style={styles.headerInner}>
          <View style={styles.headerTopRow}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn}>
              <Icon name="arrow-left" size={24} color={colors.white} />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>
              {isYieldVariant ? 'Confío Dollar+' : 'Confío Dollar'}
            </Text>
            <View style={styles.headerIconBtn} />
          </View>

          {/* Hero: ONE account number (vault + raw wallet USDT — money must
              never vanish between landing and the silent mint) + the rate
              (account-grammar: the product card is gone, so the hero owns
              rate + deltas). Empty state sells the outcome. */}
          <View style={styles.hero}>
            <Text style={styles.heroLabel}>
              {isYieldVariant ? 'Valor total' : 'Tu saldo'}
            </Text>
            <Text style={styles.heroAmount}>{fmtUsd(accountTotalUsd)}</Text>
            {isYieldVariant && hasSavings && savings.netApyPct > 0 && (
              <Text style={styles.heroRate}>
                Rindiendo ~{formatNumber(savings.netApyPct, { maximumFractionDigits: 1 })}% anual
              </Text>
            )}
            {/* Landed-but-not-minted money, named honestly per variant:
                eligible users see it as "on its way" to the vault; for
                ineligible users the raw balance IS the product, so the
                mechanics go to fine print instead. */}
            {isYieldVariant && hasUsdt && (
              <Text style={styles.heroSplit}>
                En camino a tu ahorro {fmtUsd(usdtBalanceUsd)}
              </Text>
            )}
            {!isYieldVariant && hasAnything && (
              <Text style={styles.heroSplit}>
                Tu saldo se guarda como dólares digitales (USDT) en tu propia dirección
              </Text>
            )}
            {hasAnything ? (
              isYieldVariant && tickerParts.length > 0 && (
                <View style={styles.heroTickerRow}>
                  <Icon name="trending-up" size={14} color={colors.white} />
                  <Text style={styles.heroTicker}>{tickerParts.join('  ·  ')}</Text>
                </View>
              )
            ) : (
              <Text style={styles.heroEmptyHint}>
                {isYieldVariant
                  ? savings.netApyPct > 0
                    ? `Gana ~${formatNumber(savings.netApyPct, { maximumFractionDigits: 1 })}% anual — tu dinero crece mientras duerme`
                    : 'Tu dinero puede crecer mientras duerme'
                  : 'Dólares digitales, siempre tuyos'}
              </Text>
            )}
          </View>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.primary}
            colors={[colors.primary]}
          />
        }
      >
        {/* ACCOUNT grammar (2026-07-30): the hero already carries balance +
            rate, so no product card — just actions, then the history. All
            education lives in ProtectedSavings (reached from the link row
            below AND the Home stats tile); duplicating it here buried it
            under Movimientos anyway. */}
        {isYieldVariant ? (
          <View style={styles.ctaRow}>
            <TouchableOpacity style={styles.ctaPrimary} onPress={() => setSaveSheet(true)} activeOpacity={0.85}>
              <Icon name="arrow-down-circle" size={18} color={colors.white} />
              <Text style={styles.ctaPrimaryText}>Ahorrar</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.ctaSecondary, !hasSavings && styles.ctaDisabled]}
              onPress={() => setWithdrawSheet(true)}
              disabled={!hasSavings}
              activeOpacity={0.85}
            >
              <Text style={[styles.ctaSecondaryText, !hasSavings && styles.ctaDisabledText]}>
                Retirar
              </Text>
            </TouchableOpacity>
          </View>
        ) : (
          /* Ineligible variant: the plain-dollar account. Recibir always;
             Enviar moves raw wallet USDT (sponsor-paid 7702 transfer — THE
             exit that must exist wherever deposits do); Retirar redeems any
             legacy vault balance (exits are never geo-gated). */
          <View style={styles.ctaRow}>
            <TouchableOpacity
              style={styles.ctaPrimary}
              onPress={() => navigation.navigate('ReceiveSavings', { destination: 'usdt' })}
              activeOpacity={0.85}
            >
              <Icon name="download" size={18} color={colors.white} />
              <Text style={styles.ctaPrimaryText}>Recibir</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.ctaSecondary, !hasUsdt && styles.ctaDisabled]}
              onPress={() => navigation.navigate('SendUsdt')}
              disabled={!hasUsdt}
              activeOpacity={0.85}
            >
              <Text style={[styles.ctaSecondaryText, !hasUsdt && styles.ctaDisabledText]}>
                Enviar
              </Text>
            </TouchableOpacity>
            {hasSavings && (
              <TouchableOpacity
                style={styles.ctaSecondary}
                onPress={() => setWithdrawSheet(true)}
                activeOpacity={0.85}
              >
                <Text style={styles.ctaSecondaryText}>Retirar</Text>
              </TouchableOpacity>
            )}
          </View>
        )}

        {/* Issuer geo-gate: entry hidden, money always reachable. */}
        {!isYieldVariant && (
          <View style={[styles.geoNotice, styles.geoNoticeStandalone]}>
            <Icon name="globe" size={14} color={colors.text.secondary} />
            <Text style={styles.geoNoticeText}>
              El rendimiento no está disponible en tu país por requisitos
              del emisor (Ondo Finance). Tu dinero siempre es tuyo: puedes
              recibirlo, enviarlo y retirarlo cuando quieras.
            </Text>
          </View>
        )}

        {/* ONE education door instead of inline sections: everything
            (respaldo, tasa, costos, retiros) lives in ProtectedSavings. */}
        <TouchableOpacity
          style={styles.howItWorksRow}
          onPress={() => navigation.navigate('ProtectedSavings')}
          activeOpacity={0.8}
        >
          <View style={styles.howItWorksIconWrap}>
            <Icon name="shield" size={16} color={colors.primaryDark} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.howItWorksTitle}>¿Cómo funciona?</Text>
            <Text style={styles.howItWorksSub}>
              {isYieldVariant
                ? 'Respaldo, rendimiento y costos — sin letra chica'
                : 'Respaldo verificable y costos — sin letra chica'}
            </Text>
          </View>
          <Icon name="chevron-right" size={18} color={colors.text.light} />
        </TouchableOpacity>

        {/* Partnership: real logo, nominative use. */}
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
              onPress={() => navigation.navigate('SavingsMovements')}
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

      </ScrollView>

      <RouteSheet
        visible={saveSheet}
        title="¿Desde dónde quieres ahorrar?"
        options={saveOptions}
        onClose={() => setSaveSheet(false)}
      />
      <RouteSheet
        visible={withdrawSheet}
        title="¿A dónde quieres retirar?"
        options={withdrawOptions}
        onClose={() => setWithdrawSheet(false)}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: { backgroundColor: colors.primary, overflow: 'hidden' },
  headerInner: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 24 },
  headerTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: colors.white },

  hero: { alignItems: 'center', marginTop: 16 },
  heroLabel: { fontSize: 13, color: colors.white, opacity: 0.85 },
  heroAmount: { fontSize: 40, fontWeight: 'bold', color: colors.white, marginTop: 4 },
  heroSplit: { fontSize: 13, color: colors.white, opacity: 0.9, marginTop: 6, fontWeight: '600' },
  heroRate: { fontSize: 13, fontWeight: '600', color: colors.white, opacity: 0.95, marginTop: 6 },
  heroTickerRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8 },
  heroTicker: { fontSize: 13, color: colors.white, opacity: 0.9 },
  heroEmptyHint: { fontSize: 13, color: colors.white, opacity: 0.85, marginTop: 8, textAlign: 'center', paddingHorizontal: 24 },

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

  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    marginBottom: 16,
  },

  geoNotice: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
    marginTop: 14,
    padding: 10,
    borderRadius: 10,
    backgroundColor: colors.neutralDark,
  },
  geoNoticeText: { flex: 1, fontSize: 12, lineHeight: 17, color: colors.text.secondary },
  geoNoticeStandalone: { marginTop: 0, marginBottom: 16 },
  // Standalone action row (account grammar — no product card around it).
  ctaRow: { flexDirection: 'row', gap: 10, marginBottom: 16 },
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
  ctaPrimaryText: { color: colors.white, fontSize: 15, fontWeight: '700' },
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

  howItWorksRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: colors.white,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 14,
    marginBottom: 12,
  },
  howItWorksIconWrap: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  howItWorksTitle: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  howItWorksSub: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },

  movementsEmpty: {
    alignItems: 'center',
    backgroundColor: colors.white,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
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
});
