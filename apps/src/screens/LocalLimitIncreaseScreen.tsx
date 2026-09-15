import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  SafeAreaView,
  ScrollView,
  StatusBar,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';

import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { useAccount } from '../contexts/AccountContext';
import { GET_MY_RAMP_ADDRESS } from '../apollo/queries';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { RampStepHeader } from '../components/ramps/RampStepHeader';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
import { formatRampMoney, USD_UNIT } from '../utils/rampFormat';
import { getDiditResultSessionId, startDiditVerification } from '../services/diditService';
import {
  LIMIT_INCREASE_REQUEST,
  LIMIT_INCREASE_REQUIREMENTS,
  LOCAL_MONEY_LIMITS,
  LocalLimits,
  startLimitIncreaseVerification,
  syncLimitIncreaseVerification,
} from '../services/localMoney';

type Nav = NativeStackNavigationProp<MainStackParamList, 'LocalLimitIncrease'>;

// Enhanced due diligence to move more than the default monthly limit.
// The app asks the questions (occupation prefilled from the economic activity
// already declared for Recarga/Retiro); Didit collects and screens the
// documents in one session — proof of address plus the source-of-funds files —
// without repeating the identity checks the person already passed.
const INCOME_TYPES = [
  { id: 'employed', title: 'Empleado', body: 'Recibes un sueldo', icon: 'briefcase' },
  { id: 'self_employed', title: 'Independiente', body: 'Tienes un negocio o trabajas por tu cuenta', icon: 'tool' },
  { id: 'not_employed', title: 'Sin empleo formal', body: 'Ahorros, inversiones, pensión o apoyo familiar', icon: 'home' },
];
const SOURCES = [
  { id: 'salary', label: 'Sueldo' },
  { id: 'business_income', label: 'Mi negocio' },
  { id: 'savings', label: 'Ahorros' },
  { id: 'investments', label: 'Inversiones' },
  { id: 'family_support', label: 'Apoyo familiar' },
  { id: 'other', label: 'Otro' },
];
const IN_REVIEW = ['submitted', 'in_review'];
const STATUS_STEPS = ['Documentos recibidos', 'Preparando envío automático', 'Documentos enviados al procesador'];

export default function LocalLimitIncreaseScreen() {
  const navigation = useNavigation<Nav>();
  const { activeAccount } = useAccount();
  const isBusiness = activeAccount?.type === 'business';

  const requestQuery = useQuery(LIMIT_INCREASE_REQUEST, { fetchPolicy: 'network-only', errorPolicy: 'all' });
  const limitsQuery = useQuery(LOCAL_MONEY_LIMITS, { fetchPolicy: 'network-only', errorPolicy: 'all' });
  const addressQuery = useQuery(GET_MY_RAMP_ADDRESS, { fetchPolicy: 'cache-and-network', errorPolicy: 'all' });
  const limits: LocalLimits | undefined = limitsQuery.data?.localMoneyLimits;
  const latest = requestQuery.data?.limitIncreaseRequest;

  const [incomeType, setIncomeType] = useState('');
  const [occupation, setOccupation] = useState('');
  const [expected, setExpected] = useState('');
  const [source, setSource] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // "Pedir un límite mayor" applies to the request it was chosen from: a newer
  // request (Didit finished) shows its own status even if the sync failed.
  const [startNewFrom, setStartNewFrom] = useState<string | null>(null);
  const startNew = startNewFrom !== null && (latest?.id ?? '') === startNewFrom;

  // Prefill the activity the person already declared on the address form.
  useEffect(() => {
    const declared = addressQuery.data?.myRampAddress?.economicActivity;
    if (!declared || occupation) return;
    const label = (addressQuery.data?.economicActivities || [])
      .find((item: { value: string; label: string }) => item.value === declared)?.label;
    setOccupation(label || declared);
  }, [addressQuery.data, occupation]);

  const requirementsQuery = useQuery(LIMIT_INCREASE_REQUIREMENTS, {
    variables: { incomeType }, skip: !incomeType, fetchPolicy: 'network-only', errorPolicy: 'all',
  });
  const requirements: { kind: string; title: string; detail: string }[] =
    requirementsQuery.data?.limitIncreaseRequirements || [];

  const expectedValid = /^\d+([.,]\d{1,2})?$/.test(expected) && Number(expected.replace(',', '.')) > 0;
  const complete = Boolean(incomeType) && occupation.trim().length > 1 && expectedValid && Boolean(source);
  const resuming = latest?.status === 'started' && !startNew;

  // The review happens on the server: re-read the request (and the limit it
  // may raise) whenever the person returns, and follow it while it is open.
  useEffect(() => navigation.addListener('focus', () => {
    requestQuery.refetch().catch(() => {});
    limitsQuery.refetch().catch(() => {});
  }), [navigation]); // eslint-disable-line react-hooks/exhaustive-deps
  const reviewing = Boolean(latest && IN_REVIEW.includes(latest.status));
  useEffect(() => {
    if (!reviewing) return undefined;
    requestQuery.startPolling(30000);
    return () => requestQuery.stopPolling();
  }, [reviewing]); // eslint-disable-line react-hooks/exhaustive-deps
  const approved = latest?.status === 'approved';
  const forwarded = latest?.status === 'forwarded';
  useEffect(() => {
    if (approved || forwarded) limitsQuery.refetch().catch(() => {});
  }, [approved, forwarded]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    if (!complete || submitting) return;
    setSubmitting(true);
    try {
      const session = await startLimitIncreaseVerification({
        incomeType,
        occupation: occupation.trim(),
        expectedMonthlyUsd: expected.replace(',', '.'),
        sourceOfFunds: source,
      });
      // Left while the session was being created: never open Didit over another screen.
      if (!navigation.isFocused()) return;
      const sdk = await startDiditVerification(session.sessionToken);
      if (sdk?.type === 'cancelled') {
        Alert.alert('Verificación pausada', 'Puedes continuar cuando quieras desde aquí.');
        return;
      }
      if (sdk?.type === 'failed') {
        throw new Error(sdk?.errorMessage || 'No se pudo completar la verificación.');
      }
      await syncLimitIncreaseVerification(getDiditResultSessionId(sdk, session.sessionId) || session.sessionId);
      setStartNewFrom(null);
    } catch (error: any) {
      Alert.alert('No pudimos continuar', error?.message || 'Intenta de nuevo.');
    } finally {
      setSubmitting(false);
      requestQuery.refetch().catch(() => {});
    }
  };

  const statusIndex = useMemo(() => (latest ? Math.max(0, IN_REVIEW.indexOf(latest.status)) : 0), [latest]);
  const showStatus = latest && !startNew && (IN_REVIEW.includes(latest.status) || approved || forwarded);

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled">
        <RampReveal delay={0}>
          <RampHero
            eyebrow="Límite mensual"
            title="Aumenta tu límite"
            subtitle={limits?.known && limits.limit
              ? `Hoy puedes mover hasta ${formatRampMoney(limits.limit, USD_UNIT)} al mes. Para mover más, necesitamos conocer el origen de tus fondos.`
              : 'Para mover más cada mes, necesitamos conocer el origen de tus fondos.'}
            onBack={() => navigation.goBack()}
          />
        </RampReveal>

        {isBusiness ? (
          <View style={styles.emptyStateCard}>
            <View style={styles.emptyStateIconWrap}>
              <Icon name="briefcase" size={22} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyStateTitle}>Lo revisamos contigo</Text>
            <Text style={styles.emptyStateText}>
              Para empresas, el aumento de límite usa los estados financieros de tu verificación de empresa. Escríbenos y lo gestionamos.
            </Text>
            <TouchableOpacity style={styles.primaryActionButton}
              onPress={() => navigation.navigate('HomeMessages', { initialChannelId: 'soporte' })}>
              <Text style={styles.primaryActionButtonText}>Escribir a soporte</Text>
            </TouchableOpacity>
          </View>
        ) : requestQuery.error && !requestQuery.data?.limitIncreaseRequest && !requestQuery.loading ? (
          // A failed lookup is not "no request": never show a blank application
          // over a request that may already be in review.
          <View style={styles.emptyCard}>
            <Icon name="alert-circle" size={22} color={colors.textSecondary} />
            <Text style={styles.emptyTitle}>No pudimos cargar tu solicitud</Text>
            <TouchableOpacity onPress={() => { requestQuery.refetch().catch(() => {}); }}>
              <Text style={styles.warningLink}>Intentar de nuevo</Text>
            </TouchableOpacity>
          </View>
        ) : requestQuery.loading && !requestQuery.data ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} />
          </View>
        ) : showStatus ? (
          <RampReveal delay={80}>
            <View style={styles.section}>
              <RampStepHeader number={1} title={approved ? 'Solicitud aprobada' : forwarded ? 'Documentos enviados' : 'Tu solicitud'}
                accentColor={colors.primaryDark} accentBackground={colors.primaryLight} titleColor={colors.dark} />
              <View style={styles.inputCard}>
                {approved ? (
                  <Text style={styles.bannerText}>
                    {latest.userMessage || 'Tu solicitud fue aprobada. Consulta tu límite actualizado en tus transferencias.'}
                  </Text>
                ) : forwarded ? (
                  <Text style={styles.bannerText}>Tus documentos ya están adjuntos a tu cuenta de pagos locales. El procesador determina si corresponde aumentar tu límite.</Text>
                ) : STATUS_STEPS.map((label, index) => {
                  const isDone = index < statusIndex + 1;
                  const isActive = index === statusIndex + 1;
                  return (
                    <View key={label} style={styles.timelineRow}>
                      <View style={styles.timelineRail}>
                        <View style={[styles.timelineDot, isDone && styles.timelineDotDone, isActive && styles.timelineDotActive]}>
                          {isDone ? <Icon name="check" size={13} color={colors.white} /> : null}
                          {isActive ? <View style={styles.timelineDotInner} /> : null}
                        </View>
                        {index < STATUS_STEPS.length - 1 ? (
                          <View style={[styles.timelineLine, isDone && styles.timelineLineDone]} />
                        ) : null}
                      </View>
                      <Text style={[styles.timelineLabel, !isDone && !isActive && styles.timelineLabelTodo,
                        isActive && styles.timelineLabelActive]}>{label}</Text>
                    </View>
                  );
                })}
              </View>
              <View style={[styles.disclaimerPill, { marginTop: 14 }]}>
                <Icon name="info" size={12} color={colors.primaryDark} />
                <Text style={styles.quoteNote}>
                  Enviamos tus documentos automáticamente al procesador de pagos. El procesador evalúa tu solicitud y aplica los límites al recibir tus transacciones.
                </Text>
              </View>
              {approved || forwarded ? (
                <TouchableOpacity style={{ alignSelf: 'center', marginTop: 14 }} onPress={() => setStartNewFrom(latest?.id ?? '')}>
                  <Text style={styles.historyPillText}>{forwarded ? 'Enviar nuevos documentos' : 'Pedir un límite mayor'}</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          </RampReveal>
        ) : (
          <>
            {latest && ['rejected', 'needs_more_info'].includes(latest.status) ? (
              <View style={[styles.warningCard, { marginHorizontal: 22, marginTop: 0, marginBottom: 20 }]}>
                <Icon name="alert-triangle" size={18} color={colors.warning.icon} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.warningTitle}>
                    {latest.status === 'rejected' ? 'No pudimos aprobar tu solicitud' : 'Necesitamos más información'}
                  </Text>
                  {latest.userMessage ? <Text style={styles.warningText}>{latest.userMessage}</Text> : null}
                </View>
              </View>
            ) : (
              <RampReveal delay={60}>
                <View style={styles.bannerCard}>
                  <View style={styles.bannerIconWrap}>
                    <Icon name="shield" size={16} color={colors.primary} />
                  </View>
                  <View style={styles.bannerCopy}>
                    <Text style={styles.bannerTitle}>{resuming ? 'Tienes una verificación sin terminar' : 'Verificación segura con Didit'}</Text>
                    <Text style={styles.bannerText}>
                      Subirás tus documentos en la verificación de Didit. Solo los usamos para revisar tu límite con nuestro procesador de pagos.
                    </Text>
                  </View>
                </View>
              </RampReveal>
            )}

            <RampReveal delay={110}>
              <View style={styles.section}>
                <RampStepHeader number={1} title="Cómo generas tus ingresos" accentColor={colors.primaryDark}
                  accentBackground={colors.primaryLight} titleColor={colors.dark} />
                <View style={styles.methodList}>
                  {INCOME_TYPES.map(item => {
                    const selected = incomeType === item.id;
                    return (
                      <TouchableOpacity key={item.id} style={[styles.methodCard, selected && styles.methodCardSelected]}
                        onPress={() => setIncomeType(item.id)} activeOpacity={0.7}>
                        <View style={[styles.methodIcon, selected && styles.methodIconSelected]}>
                          <Icon name={item.icon} size={18} color={selected ? colors.surface : colors.primary} />
                        </View>
                        <View style={styles.methodCopy}>
                          <Text style={[styles.methodTitle, selected && styles.methodTitleSelected]}>{item.title}</Text>
                          <Text style={[styles.methodText, selected && styles.methodTextSelected]}>{item.body}</Text>
                        </View>
                        <View style={[styles.radioOuter, selected && styles.radioOuterSelected]}>
                          {selected ? <Icon name="check" size={13} color={colors.white} /> : null}
                        </View>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>
            </RampReveal>

            <RampReveal delay={150}>
              <View style={styles.section}>
                <RampStepHeader number={2} title="Tu actividad" accentColor={colors.primaryDark}
                  accentBackground={colors.primaryLight} titleColor={colors.dark} />
                <View style={styles.inputCard}>
                  <Text style={styles.inputLabel}>A qué te dedicas</Text>
                  <View style={[styles.amountInputRow, styles.amountInputRowFocused]}>
                    <TextInput style={styles.textInput} value={occupation} onChangeText={setOccupation}
                      placeholder="Ej. contadora, comerciante" placeholderTextColor={colors.textSecondary} maxLength={120} />
                  </View>
                  <Text style={[styles.inputLabel, { marginTop: 16 }]}>Cuánto esperas mover al mes</Text>
                  <View style={[styles.amountInputRow, styles.amountInputRowFocused]}>
                    <TextInput style={styles.amountInput} value={expected} onChangeText={setExpected}
                      keyboardType="decimal-pad" placeholder="0" placeholderTextColor={colors.textSecondary} />
                    <View style={styles.currencyBadge}>
                      <Text style={styles.currencyBadgeText}>USD</Text>
                    </View>
                  </View>
                  <Text style={[styles.inputLabel, { marginTop: 16 }]}>Origen de tus fondos</Text>
                  <View style={styles.chipRow}>
                    {SOURCES.map(item => (
                      <TouchableOpacity key={item.id} style={[styles.chip, source === item.id && styles.chipSelected]}
                        onPress={() => setSource(item.id)}>
                        <Text style={[styles.chipText, source === item.id && styles.chipTextSelected]}>{item.label}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                </View>
              </View>
            </RampReveal>

            {incomeType ? (
              <RampReveal delay={0}>
                <View style={styles.section}>
                  <RampStepHeader number={3} title="Ten a mano" accentColor={colors.primaryDark}
                    accentBackground={colors.primaryLight} titleColor={colors.dark} />
                  {requirementsQuery.loading && !requirements.length ? (
                    <ActivityIndicator color={colors.primary} />
                  ) : requirements.map(row => (
                    <View key={row.kind} style={styles.savedCard}>
                      <View style={styles.methodIcon}>
                        <Icon name={row.kind === 'proof_of_address' ? 'home' : 'file-text'} size={18} color={colors.primary} />
                      </View>
                      <View style={styles.savedCopy}>
                        <Text style={styles.savedTitle}>{row.title}</Text>
                        <Text style={styles.savedText}>{row.detail}</Text>
                      </View>
                    </View>
                  ))}
                  <Text style={styles.limitText}>
                    El comprobante de domicilio debe estar a tu nombre y mostrar la dirección que registraste.
                  </Text>
                </View>
              </RampReveal>
            ) : null}

            <RampActionBar
              primaryLabel={resuming ? 'Continuar verificación' : 'Continuar a la verificación'}
              onPrimaryPress={submit}
              primaryDisabled={!complete}
              primaryLoading={submitting}
              primaryIconName="shield"
            />
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
