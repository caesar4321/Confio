import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { Header } from '../navigation/Header';
import { useMutation, useQuery } from '@apollo/client';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';

import {
  GET_INSTITUTION_DIRECTORY,
  GET_MY_BILLING_OBLIGATIONS,
  GET_MY_BILLING_SUMMARY,
} from '../apollo/queries';
import { parseInstitutionLink } from '../utils/institutionLinks';
import { InstitutionLogo } from '../components/InstitutionLogo';
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

type DirectoryEntry = {
  id: string;
  name: string;
  provider: string;
  logoUrl?: string | null;
  linkingAvailable: boolean;
};

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
  const [addOpen, setAddOpen] = useState(false);
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
  // Its own document, not a field on a shared query: a server without
  // institutionDirectory fails this alone and leaves scan/paste working.
  const { data: directoryData } = useQuery(GET_INSTITUTION_DIRECTORY, {
    skip: !authReady,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
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
  const directory: DirectoryEntry[] = directoryData?.institutionDirectory || [];
  const outstandingGroups = groupByInstitution(outstanding);
  const showInstitutionHeaders = outstandingGroups.length > 1;

  // One definition, rendered in both states. A linked member must still be
  // able to add a second institution; gating this on !linked recreated the
  // discovery problem one step further down the funnel.
  const addInstitutionBlock = (
    <View style={styles.addBlock}>
      {directory.length > 0 && (
        <View style={styles.directory}>
          {/* "Disponibles para vincular", never "Instituciones en Confío":
              the heading has to say these are NOT yours yet. */}
          <Text style={styles.directoryTitle}>Disponibles para vincular</Text>
          {directory.map((entry, index) => (
            <View
              key={entry.id}
              style={[styles.directoryRow, index > 0 && styles.directoryRowDivided]}
            >
              <InstitutionLogo
                name={entry.name}
                logoUrl={entry.logoUrl}
                size={36}
                background={colors.primaryDark}
              />
              <Text style={styles.directoryName} numberOfLines={2}>{entry.name}</Text>
              {/* A verb is what disambiguates a row from an owned card. Owned
                  cards carry money; available rows carry an action. Inert
                  until the member-number flow exists. */}
              {entry.linkingAvailable
                ? <Text style={styles.linkAction}>Vincular</Text>
                : (
                  // The View owns the pill. On iOS RCTTextView is a plain
                  // UIView, so a Text's borderRadius skips RCTView's clamping:
                  // radius 999 plus overflow:hidden masked the label away.
                  <View style={styles.soonPill}>
                    <Text style={styles.soonPillText}>Próximamente</Text>
                  </View>
                )}
            </View>
          ))}
        </View>
      )}
      <Text style={styles.addHint}>¿Tu institución te envió un enlace?</Text>
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
  );

  return (
    <View style={styles.safe}>
      {/* The global default is dark-content on white; an emerald header needs
          light-content, and the shared Header owns the top inset so the band
          extends under the status bar instead of starting below it. */}
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <Header
        navigation={navigation as any}
        title={title}
        subtitle={linked
          ? (outstanding.length === 0
            ? 'Estás al día'
            : `${outstanding.length} ${outstanding.length === 1 ? 'cuota pendiente' : 'cuotas pendientes'}`)
          : undefined}
        backgroundColor={colors.primary}
        isLight
        showBackButton
        onBackPress={() => navigation.goBack()}
      />
      <View style={styles.body}>
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
            <View style={styles.emptyDisc}>
              <Icon name="users" size={30} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyTitle}>Aún no tienes instituciones</Text>
            <Text style={styles.muted}>Vincula la tuya para ver y pagar sus cuotas desde Confío.</Text>
            {addInstitutionBlock}
          </View>
        ) : obligations.length === 0 ? (
          <View style={styles.empty}>
            <View style={styles.emptyDisc}>
              <Icon name="check-circle" size={30} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyTitle}>Estás al día</Text>
            <Text style={styles.muted}>Tu institución aún no ha emitido cuotas. Cuando lo haga, aparecerán aquí.</Text>
            {addInstitutionBlock}
          </View>
        ) : (
          <>
            {(!selected || selected.status !== 'paid') && (
              <Text style={styles.section}>Tus cuotas por pagar</Text>
            )}
            {!selected && outstanding.length === 0 && <Text style={styles.muted}>Estás al día.</Text>}
            {outstandingGroups.map(group => (
              <View key={group.institutionName}>
                {showInstitutionHeaders && (
                  <Text style={styles.groupHeader}>{group.institutionName}</Text>
                )}
                {group.rows.map(row => (
                  <View key={row.id} style={styles.card}>
                    <View style={styles.cardTop}>
                      <InstitutionLogo name={row.institutionName} size={44} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.institution}>{row.institutionName}</Text>
                        <Text style={styles.reference}>{row.memberReference}</Text>
                      </View>
                      <View style={[styles.statusPill, row.status === 'past_due' && styles.statusPillLate]}>
                        <Text style={[styles.statusPillText, row.status === 'past_due' && styles.statusPillTextLate]}>
                          {statusCopy[row.status] || row.status}
                        </Text>
                      </View>
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
                <View style={styles.historyCard}>
                {[...paid].sort((a, b) => Number(b.id === selected?.id) - Number(a.id === selected?.id)).map((row, index) => (
                  <View key={row.id} style={[styles.historyRow, index > 0 && styles.historyRowDivided]}>
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
                </View>
              </>
            )}
            {!selected && (
              addOpen ? (
                <View style={styles.addOpenWrap}>{addInstitutionBlock}</View>
              ) : (
                <TouchableOpacity
                  style={styles.addRow}
                  onPress={() => setAddOpen(true)}
                  accessibilityRole="button"
                  accessibilityLabel="Agregar otra institución"
                >
                  <Icon name="plus-circle" size={20} color={colors.primaryDark} />
                  <Text style={styles.addRowText}>Agregar otra institución</Text>
                  <Icon name="chevron-right" size={16} color={colors.text.light} />
                </TouchableOpacity>
              )
            )}
          </>
        )}
      </ScrollView>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  // Card language mirrors HomeScreen's walletCard: soft elevation, never a
  // 1px border. Borders read as wireframe next to the rest of the app.
  safe: { flex: 1, backgroundColor: colors.neutral },
  body: { flex: 1, backgroundColor: colors.neutral },
  content: { padding: 16, paddingBottom: 40 },
  center: { paddingVertical: 64, alignItems: 'center', gap: 12 },

  empty: { marginTop: 32, alignItems: 'center', paddingHorizontal: 8, gap: 14 },
  emptyDisc: { width: 72, height: 72, borderRadius: 36, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center', marginBottom: 2 },
  emptyTitle: { fontSize: 19, fontWeight: '700', textAlign: 'center', color: colors.text.primary, letterSpacing: -0.2 },
  muted: { color: colors.text.secondary, textAlign: 'center', fontSize: 14, lineHeight: 21 },
  fine: { fontSize: 12, color: colors.text.light, textAlign: 'center', lineHeight: 17 },
  link: { color: colors.primaryDark, fontWeight: '700' },

  directory: { alignSelf: 'stretch', backgroundColor: colors.white, borderRadius: 16, paddingHorizontal: 14, paddingBottom: 4, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.04, shadowRadius: 6, elevation: 2 },
  directoryTitle: { fontSize: 11, fontWeight: '700', color: colors.text.light, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: 14, marginBottom: 2 },
  directoryRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14 },
  directoryRowDivided: { borderTopWidth: 1, borderTopColor: colors.borderLight },
  directoryDisc: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  directoryName: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.text.primary, lineHeight: 20 },
  addBlock: { alignSelf: 'stretch', gap: 12, marginTop: 4 },
  addOpenWrap: { marginTop: 20 },
  addHint: { fontSize: 13, color: colors.text.secondary, textAlign: 'center', marginTop: 4 },
  addRow: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: colors.white, borderRadius: 16, paddingHorizontal: 16, paddingVertical: 16, marginTop: 20, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.04, shadowRadius: 6, elevation: 2 },
  addRowText: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.primaryDark },
  linkAction: { fontSize: 13, fontWeight: '700', color: colors.primaryDark },
  // Pills are a View (background, radius) around a Text (type, colour). Never
  // put a rounded background on a Text: iOS does not clamp its radius.
  soonPill: { flexShrink: 0, backgroundColor: colors.neutralDark, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999 },
  soonPillText: { fontSize: 11, fontWeight: '700', color: colors.text.secondary },

  primaryButton: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, alignSelf: 'stretch', minHeight: 52, borderRadius: 14, backgroundColor: colors.primary, paddingHorizontal: 16, shadowColor: colors.primaryDark, shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.25, shadowRadius: 8, elevation: 3 },
  primaryText: { color: colors.white, fontWeight: '700', fontSize: 16 },
  secondaryButton: { alignSelf: 'stretch', minHeight: 52, borderRadius: 14, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.04, shadowRadius: 6, elevation: 2 },
  secondaryText: { color: colors.text.primary, fontWeight: '700', fontSize: 15 },
  buttonDisabled: { opacity: 0.5, shadowOpacity: 0 },
  codeBox: { alignSelf: 'stretch', gap: 12 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 14, backgroundColor: colors.white, paddingHorizontal: 14, paddingVertical: 12, minHeight: 76, color: colors.text.primary, fontSize: 14, lineHeight: 20, textAlignVertical: 'top' },
  errorText: { color: colors.danger, fontSize: 13, lineHeight: 18 },

  groupHeader: { fontSize: 15, fontWeight: '700', color: colors.text.primary, marginTop: 8, marginBottom: 10 },
  section: { fontSize: 11, fontWeight: '700', color: colors.text.light, marginTop: 20, marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.6 },

  card: { backgroundColor: colors.white, borderRadius: 16, padding: 16, marginBottom: 12, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.04, shadowRadius: 6, elevation: 2 },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  // 44/22 circle on primaryDark: identical to HomeScreen's walletLogoContainer.
  logo: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primaryDark },
  institution: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  reference: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  statusPill: { flexShrink: 0, backgroundColor: colors.primaryLight, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999 },
  statusPillLate: { backgroundColor: colors.error.background },
  statusPillText: { fontSize: 11, fontWeight: '700', color: colors.primaryDark },
  statusPillTextLate: { color: colors.error.text },
  // Tabular figures per DESIGN.md: aligned money, never monospace.
  amount: { fontSize: 32, fontWeight: '800', color: colors.text.primary, marginTop: 16, letterSpacing: -0.8, fontVariant: ['tabular-nums'] },
  period: { fontSize: 13, color: colors.text.secondary, marginTop: 4 },
  payButton: { marginTop: 16, minHeight: 52, borderRadius: 14, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center', shadowColor: colors.primaryDark, shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.25, shadowRadius: 8, elevation: 3 },
  payText: { color: colors.white, fontWeight: '700', fontSize: 16 },

  historyCard: { backgroundColor: colors.white, borderRadius: 16, paddingHorizontal: 16, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.04, shadowRadius: 6, elevation: 2 },
  historyRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14 },
  historyRowDivided: { borderTopWidth: 1, borderTopColor: colors.borderLight },
  historyAmount: { color: colors.text.primary, fontWeight: '700', fontVariant: ['tabular-nums'] },
});
