// "Dinero en movimiento" — what the Home "Movido" tile is made of.
//
// Public aggregates only (fundFlowStats, cached 10 min server-side): the
// deposit/withdrawal split, the median withdrawal time and operation counts
// per country. Deliberately NOT here: dollars per country (with a handful of
// people per country that exposes large holders), a monthly chart (one big
// month reads as a crash the month after) and a feed of recent operations
// (amount + country + time can identify someone).

import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { gql, useQuery } from '@apollo/client';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';
import { useCurrency } from '../hooks/useCurrency';
import { MainStackParamList } from '../types/navigation';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { EmptyState } from '../components/EmptyState';

// Its own query (not the Home tile's): an older server without the detail
// fields fails only this screen, never the stats strip. Read with no-cache:
// fundFlowStats has no id, so sharing Apollo's cache let Home's smaller
// response overwrite these fields and hand this screen a partial object.
// The server caches it for 10 minutes, so a fresh read is cheap.
export const FUND_FLOW_DETAIL = gql`
  query FundFlowDetail {
    fundFlowStats {
      totalUsd
      depositedUsd
      withdrawnUsd
      depositCount
      withdrawalCount
      operationCount
      medianWithdrawalMinutes
      withdrawalTimingSamples
      since
      countries {
        countryIso
        countryName
        operationCount
      }
    }
  }
`;

type FlowCountry = { countryIso: string; countryName: string; operationCount: number };

const MONTHS_ES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
];

const isoToFlag = (iso?: string | null) => {
  if (!iso || iso.length !== 2) return '🌎';
  const base = 0x1f1e6;
  const a = iso.toUpperCase().charCodeAt(0) - 65;
  const b = iso.toUpperCase().charCodeAt(1) - 65;
  if (a < 0 || a > 25 || b < 0 || b > 25) return '🌎';
  return String.fromCodePoint(base + a) + String.fromCodePoint(base + b);
};

/** "menos de N" must be strictly true: N is the next whole unit ABOVE the
 * median (floor + 1), so a 9.5-min median reads "menos de 10 minutos" and an
 * exact 60-min median reads "menos de 2 horas", never "menos de 1 hora". */
export const withdrawalTimeLabel = (medianMinutes: number): string => {
  if (medianMinutes < 59) {
    const m = Math.floor(medianMinutes) + 1;
    return `menos de ${m} ${m === 1 ? 'minuto' : 'minutos'}`;
  }
  const h = Math.floor(medianMinutes / 60) + 1;
  return `menos de ${h} ${h === 1 ? 'hora' : 'horas'}`;
};

export const FundFlowScreen = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { currency } = useCurrency();
  const { data, loading, error, refetch } = useQuery(FUND_FLOW_DETAIL, {
    fetchPolicy: 'no-cache',
    errorPolicy: 'all',
    notifyOnNetworkStatusChange: true,
  });
  // Never render a partial snapshot as zeros: the split needs both halves.
  const candidate = data?.fundFlowStats;
  const flow = candidate && candidate.depositedUsd != null && candidate.withdrawnUsd != null
    ? candidate
    : null;

  const whole = (n: number | null | undefined) => {
    if (n == null) return '—';
    const digits = `${Math.round(n)}`;
    return digits.replace(/\B(?=(\d{3})+(?!\d))/g, currency.thousandsSeparator);
  };

  const since = flow?.since ? new Date(flow.since) : null;
  const sinceLabel = since && !isNaN(since.getTime())
    ? `Desde ${MONTHS_ES[since.getUTCMonth()]} de ${since.getUTCFullYear()}`
    : null;

  const deposited = flow?.depositedUsd ?? 0;
  const withdrawn = flow?.withdrawnUsd ?? 0;
  const splitTotal = deposited + withdrawn;
  const countries: FlowCountry[] = flow?.countries ?? [];
  const maxCountry = countries.reduce((m, c) => Math.max(m, c.operationCount), 0);

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Dinero en movimiento"
        backgroundColor={colors.primary}
        isLight
        showBackButton
      />

      {!flow && loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : !flow ? (
        <EmptyState
          icon="wifi-off"
          title="No pudimos cargar estos datos"
          subtitle={error ? 'Revisa tu conexión e inténtalo de nuevo.' : 'Inténtalo de nuevo en un momento.'}
          actionLabel="Reintentar"
          onAction={() => refetch()}
        />
      ) : (
        <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={styles.field}>
            <BrandFieldBackground id="fundFlowField" ringCy="25%" ringR={80} ringWidth={20} />
            <View style={styles.fieldInner}>
              <Text style={styles.fieldEyebrow}>MOVIDO EN CONFÍO</Text>
              <Text style={styles.fieldStat}>
                {whole(flow.totalUsd)}
                <Text style={styles.fieldUnit}> USD</Text>
              </Text>
              <Text style={styles.fieldSubtitle}>
                {whole(flow.operationCount)} depósitos y retiros
                {sinceLabel ? ` · ${sinceLabel.toLowerCase()}` : ''}
              </Text>
            </View>
          </View>

          {/* Both directions, side by side: the withdrawals half is the
              proof LATAM users look for — money gets out. */}
          <View style={styles.card}>
            <View style={styles.splitBar}>
              {splitTotal > 0 && (
                <>
                  <View style={[styles.splitIn, { flex: deposited }]} />
                  <View style={[styles.splitOut, { flex: withdrawn }]} />
                </>
              )}
            </View>
            <View style={styles.splitRow}>
              <View style={styles.splitCol}>
                <View style={styles.legendRow}>
                  <View style={[styles.dot, styles.dotIn]} />
                  <Text style={styles.splitLabel}>Depósitos</Text>
                </View>
                <Text style={styles.splitValue}>{whole(deposited)} USD</Text>
                <Text style={styles.splitCount}>{whole(flow.depositCount)} operaciones</Text>
              </View>
              <View style={styles.splitCol}>
                <View style={styles.legendRow}>
                  <View style={[styles.dot, styles.dotOut]} />
                  <Text style={styles.splitLabel}>Retiros</Text>
                </View>
                <Text style={styles.splitValue}>{whole(withdrawn)} USD</Text>
                <Text style={styles.splitCount}>{whole(flow.withdrawalCount)} operaciones</Text>
              </View>
            </View>
          </View>

          {/* A median, stated as one — never "retiros en minutos": some
              withdrawals take far longer, and the sentence must stay true.
              Hidden until there are enough withdrawals to mean something. */}
          {flow.medianWithdrawalMinutes != null && (
            <View style={[styles.card, styles.timingCard]}>
              <Icon name="clock" size={18} color={colors.primary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.timingTitle}>
                  La mitad de los retiros llegó en {withdrawalTimeLabel(flow.medianWithdrawalMinutes)}
                </Text>
                <Text style={styles.timingSub}>
                  Mediana de {whole(flow.withdrawalTimingSamples)} retiros a cuentas locales, desde la solicitud hasta el pago.
                </Text>
              </View>
            </View>
          )}

          {countries.length > 0 && (
            <>
              <Text style={styles.sectionLabel}>Operaciones por país</Text>
              {countries.map((c) => (
                <View key={c.countryIso} style={styles.row}>
                  <View style={styles.rowHeader}>
                    <Text style={styles.flag}>{isoToFlag(c.countryIso)}</Text>
                    <Text style={styles.countryName} numberOfLines={1}>{c.countryName}</Text>
                    <Text style={styles.count}>{whole(c.operationCount)}</Text>
                  </View>
                  <View style={styles.barTrack}>
                    <View
                      style={[
                        styles.barFill,
                        { width: `${maxCountry > 0 ? Math.max(8, (c.operationCount / maxCountry) * 100) : 0}%` },
                      ]}
                    />
                  </View>
                </View>
              ))}
              <Text style={styles.footnote}>
                Solo países con al menos 5 personas, para proteger la privacidad.
              </Text>
            </>
          )}

          <View style={styles.card}>
            <Text style={styles.howTitle}>Cómo lo contamos</Text>
            <Text style={styles.howText}>
              Contamos el dinero cuando entra a los dólares de Confío (cuando USDC o USDT se
              convierte en Confío Dollar o Dollar+) y cuando sale (cuando se convierte de vuelta
              para retirarlo), sea por banco, efectivo o cripto. Mover dinero entre Confío Dollar y
              Dollar+, o enviarlo a otro usuario, no cuenta. El total es acumulado desde el inicio.
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
  field: { backgroundColor: colors.primary, overflow: 'hidden' },
  fieldInner: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 22 },
  fieldEyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2,
    color: colors.primaryLight,
    marginBottom: 6,
  },
  fieldStat: { fontSize: 30, fontWeight: '800', color: colors.white },
  fieldUnit: { fontSize: 16, fontWeight: '700', color: 'rgba(255,255,255,0.85)' },
  fieldSubtitle: { fontSize: 13, lineHeight: 19, color: 'rgba(255,255,255,0.85)', marginTop: 6 },
  card: {
    backgroundColor: colors.neutral,
    borderRadius: 12,
    padding: 14,
    marginHorizontal: 16,
    marginTop: 16,
  },
  splitBar: {
    flexDirection: 'row',
    height: 10,
    borderRadius: 5,
    overflow: 'hidden',
    backgroundColor: colors.border,
    gap: 2,
  },
  splitIn: { backgroundColor: colors.primary },
  splitOut: { backgroundColor: colors.violet },
  splitRow: { flexDirection: 'row', marginTop: 12, gap: 12 },
  splitCol: { flex: 1 },
  legendRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  dotIn: { backgroundColor: colors.primary },
  dotOut: { backgroundColor: colors.violet },
  splitLabel: { fontSize: 12, fontWeight: '600', color: colors.text.secondary },
  splitValue: { fontSize: 18, fontWeight: '800', color: colors.dark, marginTop: 4 },
  splitCount: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  timingCard: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 },
  timingTitle: { fontSize: 15, fontWeight: '700', color: colors.dark, lineHeight: 20 },
  timingSub: { fontSize: 12, color: colors.text.secondary, marginTop: 4, lineHeight: 17 },
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
  row: {
    backgroundColor: colors.neutral,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 14,
    marginHorizontal: 16,
    marginBottom: 10,
  },
  rowHeader: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  flag: { fontSize: 22 },
  countryName: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.dark },
  count: { fontSize: 15, fontWeight: '700', color: colors.dark },
  barTrack: {
    marginTop: 8,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.border,
    overflow: 'hidden',
  },
  barFill: { height: 6, backgroundColor: colors.primary, borderRadius: 3 },
  footnote: { fontSize: 12, color: colors.text.light, paddingHorizontal: 20, marginTop: 2 },
  howTitle: { fontSize: 14, fontWeight: '700', color: colors.dark },
  howText: { fontSize: 13, lineHeight: 19, color: colors.text.secondary, marginTop: 6 },
});
