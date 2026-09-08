import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useMutation, useQuery } from '@apollo/client';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';

import { GET_MY_BILLING_OBLIGATIONS, GET_MY_BILLING_SUMMARY } from '../apollo/queries';
import { parseInstitutionLink } from '../utils/institutionLinks';
import {
  CLAIM_INSTITUTION_MEMBERSHIP,
  CREATE_MEMBER_PAYMENT_INTENT,
} from '../apollo/mutations';
import { colors } from '../config/theme';
import { useAuthReady } from '../contexts/AuthContext';

type Obligation = {
  id: string;
  institutionName: string;
  memberReference: string;
  amountMinor: number;
  amountRemainingMinor: number;
  currency: string;
  periodKey?: string;
  periodStart: string;
  periodEnd: string;
  dueAt: string;
  status: string;
  description?: string;
  institutionApplicationStatus?: string;
  institutionMemberStatus?: string;
  institutionAppliedAt?: string;
};

const money = (minor: number, currency: string) =>
  new Intl.NumberFormat('es-PE', { style: 'currency', currency }).format(minor / 100);

type InstitutionGroup = { institutionName: string; rows: Obligation[] };

/** Group by institution, institutions ordered by soonest due date then name. */
const groupByInstitution = (rows: Obligation[]): InstitutionGroup[] => {
  const byName = new Map<string, Obligation[]>();
  for (const row of rows) {
    const existing = byName.get(row.institutionName);
    if (existing) existing.push(row);
    else byName.set(row.institutionName, [row]);
  }
  const due = (row: Obligation) => {
    const value = new Date(row.dueAt).getTime();
    return Number.isNaN(value) ? Number.POSITIVE_INFINITY : value;
  };
  return [...byName.entries()]
    .map(([institutionName, list]) => ({
      institutionName,
      rows: [...list].sort((a, b) => due(a) - due(b)),
    }))
    .sort((a, b) => {
      const soonest = (group: InstitutionGroup) =>
        group.rows.reduce((min, row) => Math.min(min, due(row)), Number.POSITIVE_INFINITY);
      const delta = soonest(a) - soonest(b);
      if (delta !== 0 && Number.isFinite(delta)) return delta;
      return a.institutionName.localeCompare(b.institutionName, 'es');
    });
};

const statusCopy: Record<string, string> = {
  open: 'Pendiente',
  past_due: 'Vencida',
  payment_pending: 'Procesando',
  paid: 'Pagada',
  disputed: 'En revisión',
  held: 'En espera',
  void: 'Anulada',
  uncollectible: 'Cerrada',
  draft: 'Borrador',
};

export const MembershipsScreen = () => {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const [payingId, setPayingId] = useState<string | null>(null);
  const [claiming, setClaiming] = useState(false);
  const [codeOpen, setCodeOpen] = useState(false);
  const [codeValue, setCodeValue] = useState('');
  const [codeError, setCodeError] = useState('');
  const authReady = useAuthReady();
  const { data, loading, error, refetch } = useQuery(GET_MY_BILLING_OBLIGATIONS, {
    skip: !authReady,
    fetchPolicy: 'network-only',
    notifyOnNetworkStatusChange: true,
  });
  // Distinguishes "not linked yet" from "linked, nothing due". Without it a
  // freshly linked member with no obligations reads as never having linked.
  const { data: summaryData, loading: summaryLoading } = useQuery(GET_MY_BILLING_SUMMARY, {
    skip: !authReady,
    fetchPolicy: 'cache-and-network',
  });
  const [createIntent] = useMutation(CREATE_MEMBER_PAYMENT_INTENT);
  const [claimMembership] = useMutation(CLAIM_INSTITUTION_MEMBERSHIP);

  const provider = route.params?.provider;
  const token = route.params?.token;
  useEffect(() => {
    if (!authReady || !provider || !token) return;
    let alive = true;
    setClaiming(true);
    claimMembership({ variables: { provider, token } })
      .then(({ data: claimData }) => {
        if (!alive) return;
        const result = claimData?.claimInstitutionMembership;
        if (!result?.success) throw new Error(result?.errors?.[0] || 'No se pudo vincular');
        return refetch();
      })
      .catch(() => alive && Alert.alert(
        'No pudimos vincular tu membresía',
        'Vuelve a abrir el enlace enviado por tu institución o solicita uno nuevo.',
      ))
      .finally(() => {
        if (!alive) return;
        // Remove the one-use secret after either outcome; retry requires a
        // fresh institution link, not repeatedly consuming the same token.
        navigation.setParams({ provider: undefined, token: undefined });
        setClaiming(false);
      });
    return () => { alive = false; };
  }, [authReady, claimMembership, navigation, provider, refetch, token]);

  useFocusEffect(useCallback(() => {
    if (authReady) refetch().catch(() => undefined);
  }, [authReady, refetch]));

  const pay = useCallback(async (obligation: Obligation) => {
    if (payingId) return;
    setPayingId(obligation.id);
    try {
      const { data: intentData } = await createIntent({
        variables: { obligationId: obligation.id },
      });
      const result = intentData?.createMemberPaymentIntent;
      if (!result?.success || !result.invoiceId) {
        throw new Error(result?.errors?.[0] || 'No se pudo preparar el pago');
      }
      navigation.navigate('PaymentConfirmation', { invoiceId: result.invoiceId });
    } catch (_) {
      Alert.alert('No pudimos preparar el pago', 'Inténtalo nuevamente en unos momentos.');
    } finally {
      setPayingId(null);
    }
  }, [createIntent, navigation, payingId]);

  const submitCode = useCallback(() => {
    const parsed = parseInstitutionLink(codeValue);
    if (!parsed) {
      setCodeError('Ese enlace no es válido. Pídele a tu institución uno nuevo.');
      return;
    }
    setCodeError('');
    setCodeOpen(false);
    setCodeValue('');
    // Reuses the claim effect above rather than duplicating the mutation.
    navigation.setParams({ provider: parsed.provider, token: parsed.token });
  }, [codeValue, navigation]);

  const obligations: Obligation[] = data?.myBillingObligations || [];
  const selected = obligations.find(row => row.id === route.params?.obligationId);
  const visibleObligations = selected ? [selected] : obligations;
  const outstanding = visibleObligations.filter(row => row.amountRemainingMinor > 0
    && ['open', 'past_due', 'payment_pending', 'held', 'disputed'].includes(row.status));
  const paid = visibleObligations.filter(row => row.status === 'paid');
  const institutionNames = [...new Set(obligations.map(row => row.institutionName))];
  const title = selected?.institutionName || (institutionNames.length === 1 ? institutionNames[0] : 'Mis instituciones');
  // Monotonic on purpose: an obligation proves the link, so a failed summary
  // query can never downgrade a linked member to the "vincula tu institución"
  // state. Unknown stays unknown rather than becoming a confident negative.
  const linked = obligations.length > 0 || !!summaryData?.myBillingSummary?.linked;
  const outstandingGroups = groupByInstitution(outstanding);
  const showInstitutionHeaders = outstandingGroups.length > 1;

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} accessibilityLabel="Volver">
          <Icon name="arrow-left" size={24} color={colors.text.primary} />
        </TouchableOpacity>
        <Text style={styles.title}>{title}</Text>
        <View style={{ width: 24 }} />
      </View>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => refetch()} />}
      >
        {provider && !token && !claiming && (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>Vincula tu institución de forma segura</Text>
            <Text style={styles.muted}>Solicita a tu institución un enlace personal de verificación. Este QR público no vincula tu cuenta ni confirma tu identidad.</Text>
          </View>
        )}
        {selected && (
          <TouchableOpacity onPress={() => navigation.setParams({ obligationId: undefined })}>
            <Text style={styles.link}>Ver todas mis instituciones</Text>
          </TouchableOpacity>
        )}
        {!authReady || (loading && !data) || (summaryLoading && !summaryData) || claiming ? (
          <View style={styles.center}>
            <ActivityIndicator color={colors.primary} />
            <Text style={styles.muted}>{claiming ? 'Vinculando membresía…' : 'Cargando cuotas…'}</Text>
          </View>
        ) : error ? (
          <View style={styles.empty}>
            <Icon name="wifi-off" size={28} color={colors.text.secondary} />
            <Text style={styles.emptyTitle}>No pudimos cargar tus cuotas</Text>
            <TouchableOpacity onPress={() => refetch()}><Text style={styles.link}>Reintentar</Text></TouchableOpacity>
          </View>
        ) : !linked ? (
          <View style={styles.empty}>
            <Icon name="users" size={30} color={colors.primary} />
            <Text style={styles.emptyTitle}>Vincula tu institución</Text>
            <Text style={styles.muted}>Cuando tu institución te envíe su enlace personal de verificación, sus cuotas aparecerán aquí y podrás pagarlas desde Confío.</Text>
            <TouchableOpacity
              style={styles.primaryButton}
              onPress={() => navigation.navigate('Scan')}
              accessibilityRole="button"
              accessibilityLabel="Escanear QR"
            >
              <Icon name="maximize" size={18} color={colors.white} />
              <Text style={styles.primaryText}>Escanear QR</Text>
            </TouchableOpacity>
            {codeOpen ? (
              <View style={styles.codeBox}>
                <TextInput
                  style={styles.input}
                  value={codeValue}
                  onChangeText={value => { setCodeValue(value); if (codeError) setCodeError(''); }}
                  placeholder="Pega aquí el enlace de tu institución"
                  placeholderTextColor={colors.text.light}
                  autoCapitalize="none"
                  autoCorrect={false}
                  multiline
                  accessibilityLabel="Enlace de tu institución"
                />
                {!!codeError && <Text style={styles.errorText}>{codeError}</Text>}
                <TouchableOpacity
                  style={[styles.primaryButton, !codeValue.trim() && styles.buttonDisabled]}
                  disabled={!codeValue.trim()}
                  onPress={submitCode}
                  accessibilityRole="button"
                  accessibilityLabel="Continuar"
                >
                  <Text style={styles.primaryText}>Continuar</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => setCodeOpen(true)}
                accessibilityRole="button"
                accessibilityLabel="Tengo un enlace o código"
              >
                <Text style={styles.secondaryText}>Tengo un enlace o código</Text>
              </TouchableOpacity>
            )}
            <Text style={styles.fine}>Un QR público no verifica tu identidad. Confío no te pedirá tu DNI en esta pantalla.</Text>
          </View>
        ) : obligations.length === 0 ? (
          <View style={styles.empty}>
            <Icon name="check-circle" size={30} color={colors.primary} />
            <Text style={styles.emptyTitle}>Estás al día</Text>
            <Text style={styles.muted}>Tu institución aún no ha emitido cuotas. Cuando lo haga, aparecerán aquí.</Text>
          </View>
        ) : (
          <>
            {(!selected || selected.status !== 'paid') && <Text style={styles.section}>Por pagar</Text>}
            {!selected && outstanding.length === 0 && <Text style={styles.muted}>Estás al día.</Text>}
            {outstandingGroups.map(group => (
              <View key={group.institutionName}>
                {showInstitutionHeaders && (
                  <Text style={styles.groupHeader}>{group.institutionName}</Text>
                )}
                {group.rows.map(row => (
                  <View key={row.id} style={styles.card}>
                    <View style={styles.cardTop}>
                      <View style={styles.logo}><Icon name="award" size={20} color={colors.white} /></View>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.institution}>{row.institutionName}</Text>
                        <Text style={styles.reference}>{row.memberReference}</Text>
                      </View>
                      <Text style={[styles.badge, row.status === 'past_due' && styles.badgeLate]}>
                        {statusCopy[row.status] || row.status}
                      </Text>
                    </View>
                    <Text style={styles.amount}>{money(row.amountRemainingMinor, row.currency)}</Text>
                    <Text style={styles.period}>{row.description || row.periodKey || `${row.periodStart} – ${row.periodEnd}`}</Text>
                    <Text style={styles.reference}>Vence {new Date(row.dueAt).toLocaleDateString('es-PE')}</Text>
                    {['open', 'past_due', 'payment_pending'].includes(row.status) && (
                      <TouchableOpacity
                        style={styles.payButton}
                        disabled={payingId === row.id}
                        onPress={() => pay(row)}
                      >
                        {payingId === row.id
                          ? <ActivityIndicator color={colors.white} />
                          : <Text style={styles.payText}>{row.status === 'payment_pending' ? 'Revisar pago' : 'Pagar ahora'}</Text>}
                      </TouchableOpacity>
                    )}
                  </View>
                ))}
              </View>
            ))}
            {paid.length > 0 && (
              <>
                <Text style={styles.section}>Historial</Text>
                {[...paid].sort((a, b) => Number(b.id === selected?.id) - Number(a.id === selected?.id)).map(row => (
                  <View key={row.id} style={styles.historyRow}>
                    <Icon name="check-circle" size={20} color={colors.primary} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.institution}>{row.institutionName}</Text>
                      <Text style={styles.reference}>{row.periodKey || row.periodEnd}</Text>
                      <Text style={styles.reference}>Pago confirmado</Text>
                      {row.institutionApplicationStatus && (
                        <Text style={styles.reference}>
                          {row.institutionApplicationStatus === 'acknowledged'
                            ? `Institución: pago registrado${['active', 'habil'].includes(row.institutionMemberStatus || '') ? ' · membresía activa' : ['inactive', 'inhabil'].includes(row.institutionMemberStatus || '') ? ' · membresía inactiva' : ''}${row.institutionAppliedAt ? ` · ${new Date(row.institutionAppliedAt).toLocaleDateString('es-PE')}` : ''}`
                            : ['rejected', 'mismatch'].includes(row.institutionApplicationStatus)
                              ? 'La institución está revisando la aplicación. No vuelvas a pagar.'
                              : 'Esperando confirmación de la institución. No vuelvas a pagar.'}
                        </Text>
                      )}
                    </View>
                    <Text style={styles.historyAmount}>{money(row.amountMinor, row.currency)}</Text>
                  </View>
                ))}
              </>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.neutral },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: 16, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 18, fontWeight: '700', color: colors.text.primary },
  content: { padding: 16, paddingBottom: 40 },
  center: { paddingVertical: 64, alignItems: 'center', gap: 12 },
  empty: { marginTop: 48, alignItems: 'center', padding: 24, gap: 12 },
  emptyTitle: { fontSize: 17, fontWeight: '700', textAlign: 'center', color: colors.text.primary },
  muted: { color: colors.text.secondary, textAlign: 'center', lineHeight: 20 },
  link: { color: colors.primaryDark, fontWeight: '700' },
  fine: { fontSize: 12, color: colors.text.light, textAlign: 'center', lineHeight: 17 },
  primaryButton: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, alignSelf: 'stretch', minHeight: 48, borderRadius: 12, backgroundColor: colors.primary, paddingHorizontal: 16 },
  primaryText: { color: colors.white, fontWeight: '700', fontSize: 15 },
  secondaryButton: { alignSelf: 'stretch', minHeight: 48, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16 },
  secondaryText: { color: colors.text.primary, fontWeight: '700', fontSize: 15 },
  buttonDisabled: { opacity: 0.5 },
  codeBox: { alignSelf: 'stretch', gap: 10 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, backgroundColor: colors.white, paddingHorizontal: 14, paddingVertical: 12, minHeight: 72, color: colors.text.primary, fontSize: 14, textAlignVertical: 'top' },
  errorText: { color: colors.danger, fontSize: 13, lineHeight: 18 },
  groupHeader: { fontSize: 15, fontWeight: '700', color: colors.text.primary, marginTop: 6, marginBottom: 10 },
  section: { fontSize: 14, fontWeight: '700', color: colors.text.secondary, marginTop: 12, marginBottom: 10, textTransform: 'uppercase' },
  card: { backgroundColor: colors.white, borderRadius: 16, padding: 16, marginBottom: 12, borderWidth: 1, borderColor: colors.border },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  logo: { width: 38, height: 38, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primary },
  institution: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  reference: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  badge: { fontSize: 11, fontWeight: '700', color: colors.primaryDark, backgroundColor: colors.primaryLight, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 10 },
  badgeLate: { color: colors.danger, backgroundColor: '#FEECEC' },
  amount: { fontSize: 28, fontWeight: '800', color: colors.text.primary, marginTop: 18 },
  period: { fontSize: 13, color: colors.text.secondary, marginTop: 4 },
  payButton: { marginTop: 16, minHeight: 48, borderRadius: 12, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center' },
  payText: { color: colors.white, fontWeight: '700', fontSize: 15 },
  historyRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: colors.border },
  historyAmount: { color: colors.text.primary, fontWeight: '700' },
});
