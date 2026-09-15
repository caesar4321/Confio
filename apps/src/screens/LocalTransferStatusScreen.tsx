import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  SafeAreaView,
  ScrollView,
  StatusBar,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { RouteProp, useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useApolloClient, useQuery } from '@apollo/client';

import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { RampStepHeader } from '../components/ramps/RampStepHeader';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
import { formatRampMoney } from '../utils/rampFormat';
import { infiniaStage } from '../services/infiniaJourney';
import {
  journeyStepIndex,
  journeySteps,
  LOCAL_JOURNEY,
  LOCAL_JOURNEY_BRIDGE,
  LOCAL_JOURNEYS,
  LocalJourney,
} from '../services/localMoney';

type Nav = NativeStackNavigationProp<MainStackParamList, 'LocalTransferStatus'>;
type Route = RouteProp<MainStackParamList, 'LocalTransferStatus'>;

const TERMINAL = new Set(['completed', 'failed', 'needs_review', 'refunded']);
// Stages that never change again: polling stops only for these.
const FINAL = new Set(['completed', 'failed', 'refunded']);
const title = (j: LocalJourney) => (j.direction === 'to_bank' ? j.destinationSummary : 'Hacia tu Confío Dollar');

function Timeline({ journey }: { journey: LocalJourney }) {
  const steps = journeySteps(journey.direction, journey.localAsset);
  const current = journeyStepIndex(journey.direction, journey.stage);
  const done = journey.stage === 'completed';
  return (
    <View style={styles.inputCard}>
      {steps.map((label, index) => {
        const isDone = done || index < current;
        const isActive = !done && index === current;
        return (
          <View key={label} style={styles.timelineRow}>
            <View style={styles.timelineRail}>
              <View style={[styles.timelineDot, isDone && styles.timelineDotDone, isActive && styles.timelineDotActive]}>
                {isDone ? <Icon name="check" size={13} color={colors.white} /> : null}
                {isActive ? <View style={styles.timelineDotInner} /> : null}
              </View>
              {index < steps.length - 1 ? (
                <View style={[styles.timelineLine, isDone && styles.timelineLineDone]} />
              ) : null}
            </View>
            <Text style={[styles.timelineLabel, !isDone && !isActive && styles.timelineLabelTodo,
              isActive && styles.timelineLabelActive]}>
              {label}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

function JourneyDetail({ journeyId }: { journeyId: string }) {
  const navigation = useNavigation<Nav>();
  const query = useQuery(LOCAL_JOURNEY, { variables: { id: journeyId }, fetchPolicy: 'network-only', pollInterval: 5000 });
  const journey: LocalJourney | undefined = query.data?.infiniaJourney;
  // A bank send whose bridge is still 'prepared' is not funded: it needs the
  // owner's confirmation, not patience. Its own query (older servers).
  const bridgeQuery = useQuery(LOCAL_JOURNEY_BRIDGE, {
    variables: { id: journeyId }, fetchPolicy: 'network-only', errorPolicy: 'all', pollInterval: 10000,
  });
  // Until the bridge status is known, a bank send waiting for its funds is not
  // presented as fine: unknown is not "no signature needed".
  const awaitingFunding = journey?.direction === 'to_bank' && journey.stage === 'awaiting_credit';
  const bridgeKnown = Boolean(bridgeQuery.data?.infiniaJourney) && !bridgeQuery.error;
  // Only a fresh answer counts: after a failed refresh, Apollo still holds the
  // previous 'prepared', which must not hide the unknown-status card.
  const unsigned = awaitingFunding && bridgeKnown && bridgeQuery.data?.infiniaJourney?.bridgeStatus === 'prepared';
  const fundingUnknown = awaitingFunding && !bridgeKnown;
  // Final stages stop polling; a transfer under review keeps checking, more
  // slowly, since support can resolve it while this screen stays open.
  useEffect(() => {
    if (!journey) return;
    if (FINAL.has(journey.stage)) {
      query.stopPolling();
      bridgeQuery.stopPolling();
    } else if (journey.stage === 'needs_review') {
      query.startPolling(30000);
    }
  }, [journey?.stage]); // eslint-disable-line react-hooks/exhaustive-deps
  const refreshOnFocus = useRef(() => {});
  refreshOnFocus.current = () => {
    query.refetch().catch(() => {});
    bridgeQuery.refetch().catch(() => {});
  };
  useFocusEffect(useCallback(() => { refreshOnFocus.current(); }, []));

  // A failed request or an unknown id must never look like "still loading".
  const failed = !journey && (Boolean(query.error) || !query.loading);
  const heading = failed ? 'No pudimos cargarla' : !journey ? 'Consultando…'
    : journey.stage === 'completed' ? '¡Listo!'
      : journey.stage === 'refunded' ? 'Fondos devueltos'
      : journey.stage === 'needs_review' ? 'Lo estamos revisando'
        : journey.stage === 'failed' ? 'No se completó'
          : 'En proceso';

  return (
    <>
      <RampReveal delay={0}>
        <RampHero
          eyebrow={journey?.direction === 'to_wallet' ? 'Conversión' : 'Envío'}
          title={heading}
          subtitle={journey ? title(journey)
            : failed ? 'Revisa tu conexión e intenta de nuevo.' : 'Cargando el estado de tu transferencia.'}
          onBack={() => navigation.goBack()}
        />
      </RampReveal>
      {failed ? (
        <View style={styles.emptyCard}>
          <Icon name="alert-circle" size={22} color={colors.textSecondary} />
          <Text style={styles.emptyTitle}>
            {query.error ? 'No pudimos consultar el estado' : 'No encontramos esta transferencia'}
          </Text>
          <TouchableOpacity onPress={() => { query.refetch().catch(() => {}); }}>
            <Text style={styles.warningLink}>Intentar de nuevo</Text>
          </TouchableOpacity>
        </View>
      ) : !journey ? (
        <View style={styles.loadingCard}>
          <ActivityIndicator color={colors.primary} />
        </View>
      ) : (
        <>
          <RampReveal delay={80}>
            <View style={styles.section}>
              <RampStepHeader number={1} title="Estado" accentColor={colors.primaryDark}
                accentBackground={colors.primaryLight} titleColor={colors.dark} />
              {journey.stage === 'needs_review' || journey.stage === 'failed' || journey.stage === 'refunded' ? (
                <View style={styles.warningCard}>
                  <Icon name="alert-triangle" size={18} color={colors.warning.icon} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.warningTitle}>
                      {journey.stage === 'refunded' ? 'Fondos devueltos' : journey.stage === 'failed' ? 'La transferencia no se completó' : 'Estamos revisando la transferencia'}
                    </Text>
                    <Text style={styles.warningText}>
                      {journey.stage === 'refunded'
                        ? `El puente devolvió ${journey.refundAmount ?? ''} USDT a tu billetera. El pago local no se completó.`
                        : 'No la repitas. Si se movieron fondos, los estamos revisando y te escribiremos.'}
                    </Text>
                    <TouchableOpacity onPress={() => navigation.navigate('HomeMessages', { initialChannelId: 'soporte' })}>
                      <Text style={styles.warningLink}>Escríbenos a soporte</Text>
                    </TouchableOpacity>
                    <TouchableOpacity onPress={() => { refreshOnFocus.current(); }}>
                      <Text style={styles.warningLink}>Actualizar</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ) : unsigned ? (
                <View style={styles.warningCard}>
                  <Icon name="info" size={18} color={colors.warning.icon} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.warningTitle}>Falta tu confirmación</Text>
                    <Text style={styles.warningText}>Tus dólares todavía no salieron. Confirma el envío para completarlo.</Text>
                    <TouchableOpacity onPress={() => navigation.navigate('LocalAccountFunding')}>
                      <Text style={styles.warningLink}>Confirmar envío</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ) : fundingUnknown && bridgeQuery.error ? (
                <View style={styles.warningCard}>
                  <Icon name="alert-circle" size={18} color={colors.warning.icon} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.warningTitle}>No pudimos confirmar si tu envío ya salió</Text>
                    <Text style={styles.warningText}>Revisa de nuevo en un momento antes de cerrar la app.</Text>
                    <TouchableOpacity onPress={() => { refreshOnFocus.current(); }}>
                      <Text style={styles.warningLink}>Actualizar</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ) : journey.stage === 'awaiting_wallet_authorization' ? (
                // Pre-direct-bridge journeys still need the owner's signature.
                <View style={styles.warningCard}>
                  <Icon name="info" size={18} color={colors.warning.icon} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.warningTitle}>Tus dólares llegaron</Text>
                    <Text style={styles.warningText}>Confírmalos para traerlos a tu Confío Dollar.</Text>
                    <TouchableOpacity onPress={() => navigation.navigate('InfiniaPayment')}>
                      <Text style={styles.warningLink}>Confirmar</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ) : (
                <Timeline journey={journey} />
              )}
            </View>
          </RampReveal>
          <RampReveal delay={120}>
            <View style={styles.section}>
              <RampStepHeader number={2} title="Detalle" accentColor={colors.primaryDark}
                accentBackground={colors.primaryLight} titleColor={colors.dark} />
              <View style={styles.inputCard}>
                {journey.direction === 'to_bank' ? (
                  <>
                    <View style={styles.reviewRow}>
                      <Text style={styles.reviewLabel}>Destino</Text>
                      <Text style={styles.reviewValue}>{journey.destinationSummary}</Text>
                    </View>
                    <View style={styles.reviewRow}>
                      <Text style={styles.reviewLabel}>{journey.payoutAmount ? (journey.stage === 'completed' ? 'Enviado' : 'Importe a enviar') : 'Recibe al menos'}</Text>
                      <Text style={styles.reviewValueHighlight}>
                        {formatRampMoney(journey.payoutAmount || journey.minimumFxOutput, journey.localAsset)}
                      </Text>
                    </View>
                  </>
                ) : (
                  <View style={styles.reviewRow}>
                    <Text style={styles.reviewLabel}>{journey.walletReceivedAmount ? 'Recibiste, después de conversión' : 'Ingreso a tu Confío Dollar'}</Text>
                    <Text style={styles.reviewValueHighlight}>
                      {journey.walletReceivedAmount ? formatRampMoney(journey.walletReceivedAmount, 'US$') : 'Pendiente'}
                    </Text>
                  </View>
                )}
                <Text style={styles.reference} selectable>Referencia {journey.internalId}</Text>
              </View>
              {!TERMINAL.has(journey.stage) && !unsigned && !fundingUnknown ? (
                <View style={[styles.settlementNotice, { marginTop: 12 }]}>
                  <Icon name="clock" size={13} color={colors.textSecondary} />
                  <Text style={styles.settlementNoticeText}>{journey.direction === 'to_wallet'
                    ? 'La conversión a Confío Dollar se completa con la app abierta. Si la cierras, se retomará cuando vuelvas.'
                    : 'Puedes cerrar la app. Te avisaremos cuando termine.'}</Text>
                </View>
              ) : null}
            </View>
          </RampReveal>
          <RampActionBar primaryLabel="Listo" onPrimaryPress={() => navigation.popToTop()} />
        </>
      )}
    </>
  );
}

const PAGE = 20;

function JourneyList() {
  const navigation = useNavigation<Nav>();
  const apollo = useApolloClient();
  // One loader for everything (first load, return, "Actualizar", retry, polling
  // while empty, "Ver más"): it re-reads every loaded page together and replaces
  // the list in one step, one load at a time. No response is ever merged into a
  // list that changed underneath it, so pages never drift, duplicate or vanish.
  const [pages, setPages] = useState(1);
  const [loadedPages, setLoadedPages] = useState(0);
  const [rows, setRows] = useState<LocalJourney[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const busy = useRef(false);
  const queued = useRef<number | null>(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const load = useCallback(async (pageCount: number): Promise<void> => {
    if (busy.current) {
      queued.current = Math.max(queued.current ?? 0, pageCount);
      return;
    }
    busy.current = true;
    setLoading(true);
    try {
      const byId = new Map<string, LocalJourney>();
      let lastPage = 0;
      for (let page = 0; page < pageCount; page += 1) {
        const result = await apollo.query({
          query: LOCAL_JOURNEYS, variables: { offset: page * PAGE, limit: PAGE }, fetchPolicy: 'network-only',
        });
        const fetched: LocalJourney[] = result.data?.myInfiniaJourneys || [];
        fetched.forEach(row => { if (!byId.has(row.internalId)) byId.set(row.internalId, row); });
        lastPage = fetched.length;
        if (fetched.length < PAGE) break;
      }
      if (!alive.current) return;
      setRows([...byId.values()]);
      setMore(lastPage === PAGE);
      setLoadedPages(pageCount);
      setFailed(false);
    } catch {
      // What is shown stays; a retry link appears.
      if (alive.current) setFailed(true);
    } finally {
      busy.current = false;
      if (alive.current) setLoading(false);
      const next = queued.current;
      queued.current = null;
      if (next !== null && alive.current) load(next);
    }
  }, [apollo]);
  const pagesRef = useRef(pages);
  pagesRef.current = pages;
  useEffect(() => { load(pages); }, [load, pages]);
  // Back on screen: re-read everything loaded (nothing is dropped any more).
  useFocusEffect(useCallback(() => { load(pagesRef.current); }, [load]));
  // A send whose outcome was unknown can land here before its journey exists:
  // while the list is empty, keep checking.
  const empty = rows !== null && rows.length === 0;
  useEffect(() => {
    if (!empty) return undefined;
    const timer = setInterval(() => load(pagesRef.current), 10000);
    return () => clearInterval(timer);
  }, [empty, load]);
  const refresh = () => { load(pagesRef.current); };
  const list = rows || [];
  const pageLoading = pages > loadedPages && loading;
  return (
    <>
      <RampReveal delay={0}>
        <RampHero eyebrow="Transferencias locales" title="Tus envíos" subtitle="Envíos a cuentas locales y conversiones a dólares."
          onBack={() => navigation.goBack()} />
      </RampReveal>
      <View style={styles.section}>
        {list.length > 0 ? (
          <TouchableOpacity onPress={refresh} style={{ alignSelf: 'flex-end', paddingVertical: 6 }}>
            <Text style={styles.warningLink}>Actualizar</Text>
          </TouchableOpacity>
        ) : null}
        {rows === null && !failed ? (
          <ActivityIndicator color={colors.primary} />
        ) : failed && !list.length ? (
          // A failed request is not "no transfers".
          <View style={styles.emptyCard}>
            <Icon name="alert-circle" size={22} color={colors.textSecondary} />
            <Text style={styles.emptyTitle}>No pudimos cargar tus envíos</Text>
            <TouchableOpacity onPress={refresh}>
              <Text style={styles.warningLink}>Intentar de nuevo</Text>
            </TouchableOpacity>
          </View>
        ) : !list.length ? (
          <View style={styles.emptyCard}>
            <Icon name="inbox" size={22} color={colors.textSecondary} />
            <Text style={styles.emptyTitle}>Todavía no hay transferencias</Text>
            <Text style={styles.emptyText}>Cuando envíes o conviertas, las verás aquí.</Text>
            <TouchableOpacity onPress={refresh}>
              <Text style={styles.warningLink}>Actualizar</Text>
            </TouchableOpacity>
          </View>
        ) : list.map(row => (
          <TouchableOpacity key={row.internalId} style={styles.savedCard} activeOpacity={0.7}
            onPress={() => navigation.push('LocalTransferStatus', { journeyId: row.internalId })}>
            <View style={styles.savedCopy}>
              <Text style={styles.savedTitle}>{title(row)}</Text>
              <Text style={styles.savedText}>{infiniaStage(row.stage)}</Text>
            </View>
            <Icon name="chevron-right" size={18} color={colors.text.light} />
          </TouchableOpacity>
        ))}
        {failed && list.length > 0 ? (
          <TouchableOpacity onPress={refresh} style={{ paddingVertical: 12, alignItems: 'center' }}>
            <Text style={styles.warningLink}>No pudimos actualizar tus envíos. Intentar de nuevo</Text>
          </TouchableOpacity>
        ) : list.length > 0 && (more || pages > loadedPages) ? (
          // Older transfers (one still under review included) stay reachable; a
          // requested page that never loaded is retried, not skipped.
          <TouchableOpacity onPress={() => (pages > loadedPages ? load(pages) : setPages(count => count + 1))}
            disabled={pageLoading} style={{ paddingVertical: 12, alignItems: 'center' }}>
            {pageLoading ? <ActivityIndicator color={colors.primary} />
              : <Text style={styles.warningLink}>Ver más</Text>}
          </TouchableOpacity>
        ) : null}
      </View>
    </>
  );
}

export default function LocalTransferStatusScreen() {
  const journeyId = useRoute<Route>().params?.journeyId;
  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {journeyId ? <JourneyDetail journeyId={journeyId} /> : <JourneyList />}
      </ScrollView>
    </SafeAreaView>
  );
}
