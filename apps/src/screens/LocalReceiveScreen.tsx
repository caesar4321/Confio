import React, { useCallback, useEffect, useRef, useState } from 'react';
import LocalAccountApplicationScreen from './LocalAccountApplicationScreen';
import {
  ActivityIndicator,
  Alert,
  SafeAreaView,
  ScrollView,
  Share,
  StatusBar,
  Text,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Clipboard from '@react-native-clipboard/clipboard';
import QRCode from 'react-native-qrcode-svg';
import { RouteProp, useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useApolloClient, useQuery } from '@apollo/client';

import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { countryFlag, countryName } from '../config/localRails';
import { useBrebLocationPass } from '../components/breb/BrebLocationGate';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { RampStepHeader } from '../components/ramps/RampStepHeader';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
import { formatRampMoney, formatRampRate, USD_UNIT } from '../utils/rampFormat';
import { requestRampCriticalAuth } from '../utils/rampFlow';
import { createInfiniaJourney } from '../services/infiniaJourney';
import { bridgeRequestId } from '../services/paymentBridge';
import {
  currencyName,
  fetchDepositQuote,
  heldReasonCopy,
  LOCAL_DEPOSITS,
  LOCAL_MONEY_LIMITS,
  LOCAL_MONEY_METHODS,
  LOCAL_RECEIVE_ACCOUNT,
  LocalDeposit,
  LocalDepositQuote,
  LocalLimits,
  LocalMethod,
  LocalReceiveAccount,
} from '../services/localMoney';

type Nav = NativeStackNavigationProp<MainStackParamList, 'LocalReceive'>;
type Route = RouteProp<MainStackParamList, 'LocalReceive'>;

// "Tu propia/tu propio", never "a tu nombre" as a titling promise — see the
// copy rule on RECEIVE_RAILS in config/localRails.ts.
const COPY: Record<string, { hero: string; label: string; rail: string }> = {
  co_breb_receive: { hero: 'Tu propia llave Bre-B', label: 'Tu llave Bre-B', rail: 'Bre-B' },
  br_pix_receive: { hero: 'Tu cuenta Pix', label: 'Tus datos Pix', rail: 'Pix' },
  mx_clabe_receive: { hero: 'Tu propia CLABE', label: 'Tu CLABE', rail: 'SPEI' },
  ar_cvu_receive: { hero: 'Tu propio CVU', label: 'Tu CVU', rail: 'transferencia' },
};

const DEPOSITS_PAGE = 20; // the server's page size for infiniaJourneyDeposits

const shortDate = (value: string) => {
  try {
    return new Date(value).toLocaleString('es', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
};

export default function LocalReceiveScreen() {
  const { methodId } = useRoute<Route>().params;
  // Cobre's Bre-B key lives on its application screen.
  if (methodId === 'cobre_co_breb_receive') return <LocalAccountApplicationScreen />;
  return <InfiniaLocalReceiveScreen />;
}

function InfiniaLocalReceiveScreen() {
  const navigation = useNavigation<Nav>();
  const { methodId } = useRoute<Route>().params;
  const { width } = useWindowDimensions();
  const isCompact = width < 380;

  const accountQuery = useQuery(LOCAL_RECEIVE_ACCOUNT, {
    variables: { methodId }, fetchPolicy: 'network-only', errorPolicy: 'all',
  });
  const account: LocalReceiveAccount | undefined = accountQuery.data?.localReceiveAccount;
  const isPixQr = methodId === 'br_pix_receive' && account?.instructionKind === 'qr';
  const copy = isPixQr
    ? { hero: 'Tu código Pix', label: 'Tu código Pix Copia e Cola', rail: 'Pix' }
    : methodId === 'br_pix_receive' && account?.instructionKind === 'pix_key' && account?.value
      ? { hero: 'Tu propia chave Pix', label: 'Tu chave Pix', rail: 'Pix' }
    : COPY[methodId] || COPY.mx_clabe_receive;
  // A Bre-B key shows only while this account's location pass lasts, also
  // when the screen stays open past it (the server withholds it on reload).
  const brebKeyScreen = methodId === 'co_breb_receive';
  const passOk = useBrebLocationPass(brebKeyScreen);
  // A verification may finish after this screen has already regained focus.
  // Reload the server-withheld key when that pass arrives, without another tab change.
  const accountRefetch = useRef(accountQuery.refetch);
  accountRefetch.current = accountQuery.refetch;
  useEffect(() => {
    if (brebKeyScreen && passOk) accountRefetch.current().catch(() => {});
  }, [brebKeyScreen, passOk]);
  const accountValue = account && (!brebKeyScreen || passOk) ? account.value : '';
  const [accountRetrying, setAccountRetrying] = useState(false);
  // The server withholds a Bre-B key without a recent location check; the
  // check screen renews it and the key loads on return.
  const revealKey = () => navigation.navigate('BrebLocationCheck');
  const methodsQuery = useQuery(LOCAL_MONEY_METHODS, {
    variables: { direction: 'receive' }, fetchPolicy: 'cache-and-network', errorPolicy: 'all',
  });
  const receiveMethod: LocalMethod | undefined = (methodsQuery.data?.localMoneyMethods || [])
    .find((row: LocalMethod) => row.id === methodId);
  const active = account?.status === 'active' && Boolean(account.value);
  const limitsQuery = useQuery(LOCAL_MONEY_LIMITS, { fetchPolicy: 'network-only', errorPolicy: 'all', skip: !active });
  const limits: LocalLimits | undefined = limitsQuery.data?.localMoneyLimits;
  // Every loaded page is refreshed together (poll, return to the screen, after
  // a conversion), so rows never go stale, duplicate, or fall between pages
  // when a new deposit arrives; converted deposits simply drop out.
  const apollo = useApolloClient();
  const [depositPages, setDepositPages] = useState(1);
  const [loadedPages, setLoadedPages] = useState(0);
  const [depositRows, setDepositRows] = useState<LocalDeposit[] | null>(null);
  const [depositsError, setDepositsError] = useState(false);
  const [depositsLoading, setDepositsLoading] = useState(false);
  const [moreDeposits, setMoreDeposits] = useState(false);
  const depositsRun = useRef(0);
  // Busy and queued are scoped to the account generation: a request for a
  // previous account can neither block nor consume the current one's.
  const depositsBusy = useRef<number | null>(null);
  const depositsQueued = useRef<{ gen: number; pages: number } | null>(null);
  const selectedRef = useRef<string | null>(null);
  const localAccountId = active ? account?.localAccountId : undefined;
  // Results from another account, or after unmount, never land.
  useEffect(() => () => { depositsRun.current += 1; }, [localAccountId]);
  // One load at a time. A request that arrives meanwhile (poll, return to the
  // screen, a conversion) is coalesced and runs right after, so a slow load is
  // never discarded by the next poll.
  const loadDeposits = useCallback(async (pageCount: number): Promise<void> => {
    if (!localAccountId) return;
    const run = depositsRun.current;
    if (depositsBusy.current === run) {
      const queued = depositsQueued.current;
      depositsQueued.current = { gen: run, pages: Math.max(queued?.gen === run ? queued.pages : 0, pageCount) };
      return;
    }
    depositsBusy.current = run;
    setDepositsLoading(true);
    try {
      const byId = new Map<string, LocalDeposit>();
      let lastPage = 0;
      for (let page = 0; page < pageCount; page += 1) {
        const result = await apollo.query({
          query: LOCAL_DEPOSITS,
          variables: { account: localAccountId, offset: page * DEPOSITS_PAGE },
          fetchPolicy: 'network-only',
        });
        const rows: LocalDeposit[] = result.data?.infiniaJourneyDeposits || [];
        rows.forEach(row => { if (!byId.has(row.internalId)) byId.set(row.internalId, row); });
        lastPage = rows.length;
        if (rows.length < DEPOSITS_PAGE) break;
      }
      if (run !== depositsRun.current) return;
      const loaded = [...byId.values()];
      setDepositRows(loaded);
      // A selection that is no longer convertible (converted, held) is dropped
      // with the very results that show it, whatever else is still loading.
      if (selectedRef.current && !loaded.some(row => row.internalId === selectedRef.current && !row.held)) {
        setSelectedId(null);
      }
      setMoreDeposits(lastPage === DEPOSITS_PAGE);
      setLoadedPages(pageCount);
      setDepositsError(false);
    } catch {
      if (run === depositsRun.current) setDepositsError(true);
    } finally {
      if (depositsBusy.current === run) depositsBusy.current = null;
      if (run === depositsRun.current) setDepositsLoading(false);
      const queued = depositsQueued.current;
      if (queued && queued.gen === depositsRun.current && depositsBusy.current === null) {
        depositsQueued.current = null;
        loadDeposits(queued.pages);
      }
    }
  }, [apollo, localAccountId]);
  const depositPagesRef = useRef(depositPages);
  depositPagesRef.current = depositPages;
  useEffect(() => {
    loadDeposits(depositPages);
    const timer = setInterval(() => loadDeposits(depositPagesRef.current), 15000);
    return () => clearInterval(timer);
  }, [loadDeposits, depositPages]);
  const deposits: LocalDeposit[] = depositRows || [];

  // Back from another screen (a document verified, a conversion made): the
  // account, rails and deposits may have changed. A ref keeps the focus effect
  // from depending on query objects.
  const refreshOnFocus = useRef(() => {});
  refreshOnFocus.current = () => {
    accountQuery.refetch().catch(() => {});
    methodsQuery.refetch().catch(() => {});
    if (active) limitsQuery.refetch().catch(() => {}); // e.g. back from an approved limit increase
    loadDeposits(depositPagesRef.current);
  };
  useFocusEffect(useCallback(() => { refreshOnFocus.current(); }, []));

  const [selectedId, setSelectedId] = useState<string | null>(null);
  selectedRef.current = selectedId;
  const aliveRef = useRef(true);
  useEffect(() => () => { aliveRef.current = false; }, []);
  const [quote, setQuote] = useState<LocalDepositQuote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // One request id per deposit: a retry after a lost response returns the
  // same journey instead of opening a second one.
  const requestIds = useRef<Record<string, string>>({});

  const flag = account ? countryFlag(account.country) : '';
  const place = account ? countryName(account.country) : '';
  const currency = account ? currencyName(account.asset) : 'moneda local';


  useEffect(() => {
    setQuote(null);
    setQuoteError('');
    if (!selectedId) return;
    let cancelled = false;
    setQuoteLoading(true);
    fetchDepositQuote(selectedId)
      .then(next => { if (!cancelled) setQuote(next); })
      .catch((error: any) => { if (!cancelled) setQuoteError(error?.message || 'No pudimos cotizar este depósito.'); })
      .finally(() => { if (!cancelled) setQuoteLoading(false); });
    return () => { cancelled = true; };
  }, [selectedId]);

  const shareMessage = account
    ? [`${copy.label}: ${accountValue}`, account.holderName ? `Titular: ${account.holderName}` : '',
      account.institution ? `Banco: ${account.institution}` : ''].filter(Boolean).join('\n')
    : '';

  const handleConvert = async () => {
    if (!quote || !selectedId || !account?.localAccountId || !account.cryptoAccountId || submitting) return;
    // Everything below belongs to this deposit and this quote: captured now,
    // the form locked before authentication, and checked again after it.
    const creditId = selectedId;
    const chosen = quote;
    const localAccountId = account.localAccountId;
    const cryptoAccountId = account.cryptoAccountId;
    setSubmitting(true);
    try {
      const authenticated = await requestRampCriticalAuth({
        amount: Number(chosen.minimumWalletOutput), assetUnit: USD_UNIT, actionLabel: 'conversión',
      });
      if (!authenticated || !aliveRef.current || selectedRef.current !== creditId) return;
      requestIds.current[creditId] ||= bridgeRequestId();
      // Direct mode: the provider pays straight into the bridge to the user's
      // wallet. Both minimums are the user's one authorization; nothing is
      // signed later.
      const journey = await createInfiniaJourney({
        direction: 'to_wallet',
        requestId: requestIds.current[creditId],
        localAccountId,
        cryptoAccountId,
        minimumFxOutput: chosen.minimumFxOutput,
        minimumWalletOutput: chosen.minimumWalletOutput,
        creditId,
      });
      // The conversion exists: wherever the person is now, the Transfer tab's
      // history link must show it (it may have refreshed before this landed).
      apollo.refetchQueries({ include: ['PaymentBridgeAvailability'] }).catch(() => {});
      // The person may have left while the request ran: nothing lands, nothing opens.
      // The selection is deliberately not re-checked here: the conversion now
      // exists, and a poll that dropped the deposit meanwhile only saw it spent
      // by this journey (rows cannot be reselected while submitting).
      if (!aliveRef.current) return;
      // Done with this deposit: returning here must not show its old summary.
      setSelectedId(null);
      setQuote(null);
      await loadDeposits(depositPagesRef.current); // the converted deposit drops out
      // Opened only from this screen: if the person moved to another one
      // meanwhile, the conversion waits in their history instead of covering it.
      if (!aliveRef.current || !navigation.isFocused()) return;
      navigation.navigate('LocalTransferStatus', { journeyId: journey.internalId });
    } catch (error: any) {
      Alert.alert('No pudimos convertir', error?.message || 'Revisa el estado antes de volver a intentar.');
    } finally {
      if (aliveRef.current) setSubmitting(false);
    }
  };

  const capabilityLine = account?.receiveThirdParty === 'enabled'
    ? 'Puedes recibir de cualquier persona o empresa.'
    : account?.receiveSameName === 'enabled'
      ? 'Por ahora recibe solo desde cuentas a tu nombre.'
      : 'Los depósitos aún no están disponibles en esta cuenta. Contacta a soporte antes de recibir un pago.';

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <RampReveal delay={0}>
          <RampHero
            eyebrow="Recibir"
            title={copy.hero}
            subtitle={`Recibe ${currency} por ${copy.rail} y confirma la conversión para acreditarlos en tu saldo en dólares.`}
            onBack={() => navigation.goBack()}
            compact={isCompact}
          />
        </RampReveal>

        {!account && (accountQuery.loading || accountRetrying) ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} size="small" />
            <Text style={styles.loadingText}>Cargando…</Text>
          </View>
        ) : !account ? (
          <View style={styles.loadingCard}>
            <Text style={styles.loadingText}>No pudimos cargar tu cuenta local.</Text>
            <TouchableOpacity onPress={() => {
              setAccountRetrying(true);
              accountQuery.refetch().catch(() => {}).finally(() => {
                if (aliveRef.current) setAccountRetrying(false);
              });
            }}>
              <Text style={styles.warningLink}>Intentar de nuevo</Text>
            </TouchableOpacity>
          </View>
        ) : !active && receiveMethod?.status === 'needs_document' ? (
          <View style={styles.emptyStateCard}>
            <View style={styles.emptyStateIconWrap}>
              <Icon name="file-text" size={22} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyStateTitle}>Necesitamos otro documento</Text>
            <Text style={styles.emptyStateText}>
              Para abrir {copy.label.replace('Tu ', 'tu ')} en {place} necesitamos un documento distinto al que ya
              verificaste. Tu verificación actual no cambia.
            </Text>
            <TouchableOpacity style={styles.primaryActionButton} onPress={() => navigation.navigate('AdditionalDocument', {
              idCountry: receiveMethod.documentCountry, documentTypes: receiveMethod.documentTypes,
              reason: `Para recibir en ${place} necesitamos un documento distinto al que ya verificaste.`,
            })}>
              <Text style={styles.primaryActionButtonText}>Verificar documento</Text>
            </TouchableOpacity>
          </View>
        ) : account.status === 'active' && !accountValue && brebKeyScreen ? (
          <View style={styles.emptyStateCard}>
            <View style={styles.emptyStateIconWrap}>
              <Icon name="map-pin" size={22} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyStateTitle}>Confirma tu ubicación</Text>
            <Text style={styles.emptyStateText}>Para ver tu llave Bre-B confirmamos que está disponible donde estás.</Text>
            <TouchableOpacity style={styles.primaryActionButton} onPress={revealKey}>
              <Text style={styles.primaryActionButtonText}>Confirmar y ver mi llave</Text>
            </TouchableOpacity>
          </View>
        ) : !active ? (
          <RampReveal delay={80}>
            <View style={styles.section}>
              <RampStepHeader
                number={1}
                title={`Activa ${copy.label.replace('Tu ', 'tu ')}`}
                meta={`${flag ? `${flag} ` : ''}${place} · ${account.asset}`}
                accentColor={colors.primaryDark}
                accentBackground={colors.primaryLight}
                titleColor={colors.dark}
                metaColor={colors.textSecondary}
              />
              <View style={styles.inputCard}>
                {account.status === 'provisioning' ? (
                  <View style={styles.emptyQuote}>
                    <ActivityIndicator color={colors.primary} />
                    <Text style={styles.emptyText}>
                      Estamos creando {copy.label.replace('Tu ', 'tu ')}. Normalmente tarda unos minutos. Puedes volver aquí para continuar.
                    </Text>
                  </View>
                ) : (
                  <>
                    {[
                      ['repeat', 'Siempre la misma', 'Compártela las veces que quieras.'],
                      ['zap', `Llega por ${copy.rail}`, 'Desde cualquier banco o billetera, normalmente en minutos.'],
                      ['dollar-sign', 'De pagos locales a dólares', 'Cuando llegue un depósito, confirma la conversión para recibir dólares en tu saldo.'],
                    ].map(([icon, title, body]) => (
                      <View key={title} style={[styles.reviewRow, { alignItems: 'center' }]}>
                        <View style={styles.methodIcon}>
                          <Icon name={icon} size={18} color={colors.primary} />
                        </View>
                        <View style={styles.methodCopy}>
                          <Text style={styles.methodTitle}>{title}</Text>
                          <Text style={styles.methodText}>{body}</Text>
                        </View>
                      </View>
                    ))}
                  </>
                )}
              </View>
            </View>
            {account.status === 'none' || account.status === 'provisioning' || account.status === 'awaiting_payment' ? (
              <RampActionBar
                primaryLabel={account.status === 'awaiting_payment' ? 'Completar apertura'
                  : account.status === 'provisioning' ? 'Ver el estado de la apertura'
                    : `Solicitar ${copy.label.replace('Tu ', 'mi ')}`}
                onPrimaryPress={() => navigation.navigate('LocalAccountApplication', { methodId })}
                primaryIconName="chevron-right"
              />
            ) : (
              <Text style={[styles.errorText, { marginHorizontal: 22 }]}>
                Tu cuenta local no está disponible. Escríbenos a soporte.
              </Text>
            )}
          </RampReveal>
        ) : (
          <>
            {/* ─── Step 1: Receiving details ─── */}
            <RampReveal delay={80}>
              <View style={styles.section}>
                <RampStepHeader
                  number={1}
                  title="Tus datos para recibir"
                  meta={`${flag ? `${flag} ` : ''}${place} · ${account.asset}`}
                  accentColor={colors.primaryDark}
                  accentBackground={colors.primaryLight}
                  titleColor={colors.dark}
                  metaColor={colors.textSecondary}
                />
                <View style={styles.inputCard}>
                  <Text style={styles.inputLabel}>{copy.label}</Text>
                  {isPixQr ? (
                    <View style={{ alignItems: 'center', padding: 16, backgroundColor: '#fff' }}>
                      <QRCode value={accountValue} size={Math.min(220, width - 112)} />
                      <Text style={[styles.detailMeta, { marginTop: 12 }]}>
                        Escanea este QR o pega el código en Pix Copia e Cola en tu banco o billetera.
                      </Text>
                    </View>
                  ) : null}
                  <Text style={styles.detailValue} selectable>{accountValue}</Text>
                  {account.holderName ? <Text style={styles.detailMeta}>Titular: {account.holderName}</Text> : null}
                  {account.institution ? <Text style={styles.detailMeta}>Banco: {account.institution}</Text> : null}
                  <View style={styles.buttonRow}>
                    <TouchableOpacity style={styles.smallPrimary} onPress={() => {
                      Clipboard.setString(accountValue);
                      Alert.alert('Copiado', isPixQr ? 'Tu código Pix se copió. Pégalo en Pix Copia e Cola.'
                        : `${copy.label} se copió. Compártela con quien te va a pagar.`);
                    }}>
                      <Icon name="copy" size={16} color={colors.white} />
                      <Text style={styles.smallPrimaryText}>Copiar</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.smallGhost} onPress={() => Share.share({ message: shareMessage })}>
                      <Icon name="share-2" size={16} color={colors.successText} />
                      <Text style={styles.smallGhostText}>Compartir</Text>
                    </TouchableOpacity>
                  </View>
                  <View style={[styles.reviewRow, { marginTop: 8 }]}>
                    <Icon name="user-check" size={16} color={colors.textSecondary} />
                    <Text style={[styles.limitText, { marginTop: 0, flex: 1 }]}>{capabilityLine}</Text>
                  </View>
                  {limits?.known && limits.limit && limits.used ? (
                    <>
                      <Text style={styles.limitText}>
                        Este mes: {formatRampMoney(limits.used, USD_UNIT)} de {formatRampMoney(limits.limit, USD_UNIT)}
                      </Text>
                      <View style={styles.progressTrack}>
                        <View style={[styles.progressFill, {
                          width: `${Math.min(100, (Number(limits.used) / Math.max(Number(limits.limit), 1)) * 100)}%`,
                        }]} />
                      </View>
                      {limits.nearLimit ? (
                        <TouchableOpacity onPress={() => navigation.navigate('LocalLimitIncrease')}>
                          <Text style={[styles.historyPillText, { marginTop: 10 }]}>Aumentar mi límite mensual</Text>
                        </TouchableOpacity>
                      ) : null}
                    </>
                  ) : null}
                </View>
              </View>
            </RampReveal>

            {/* ─── Step 2: Deposits ─── */}
            <RampReveal delay={120}>
              <View style={styles.section}>
                <RampStepHeader
                  number={2}
                  title="Depósitos"
                  meta={deposits.length ? 'Elige uno para convertir' : null}
                  accentColor={colors.primaryDark}
                  accentBackground={colors.primaryLight}
                  titleColor={colors.dark}
                  metaColor={colors.textSecondary}
                />
                {depositRows === null && !depositsError && Boolean(localAccountId) ? (
                  <ActivityIndicator color={colors.primary} />
                ) : depositsError && !deposits.length ? (
                  // A failed request is not "no deposits".
                  <View style={styles.emptyCard}>
                    <Icon name="alert-circle" size={22} color={colors.textSecondary} />
                    <Text style={styles.emptyTitle}>No pudimos cargar tus depósitos</Text>
                    <TouchableOpacity onPress={() => { loadDeposits(depositPagesRef.current); }}>
                      <Text style={styles.warningLink}>Intentar de nuevo</Text>
                    </TouchableOpacity>
                  </View>
                ) : !deposits.length ? (
                  <View style={styles.emptyCard}>
                    <Icon name="inbox" size={22} color={colors.textSecondary} />
                    <Text style={styles.emptyTitle}>Todavía no recibiste depósitos</Text>
                    <Text style={styles.emptyText}>Comparte tus datos y aquí verás cada transferencia que llegue.</Text>
                  </View>
                ) : deposits.map(row => {
                  const selected = selectedId === row.internalId;
                  return (
                    <TouchableOpacity
                      key={row.internalId}
                      style={[styles.savedCard, selected && styles.savedCardSelected]}
                      onPress={() => { if (!row.held && !submitting) setSelectedId(selected ? null : row.internalId); }}
                      activeOpacity={row.held ? 1 : 0.7}
                    >
                      <View style={styles.savedCopy}>
                        <Text style={styles.savedText}>{shortDate(row.occurredAt)}</Text>
                        {row.held ? (
                          <>
                            <Text style={[styles.warningText, { marginTop: 0 }]}>En revisión: {heldReasonCopy(row.heldReason)}</Text>
                            <TouchableOpacity onPress={() => navigation.navigate('HomeMessages', { initialChannelId: 'soporte' })}>
                              <Text style={styles.warningLink}>Escríbenos a soporte</Text>
                            </TouchableOpacity>
                          </>
                        ) : (
                          <Text style={styles.savedText}>Listo para convertir</Text>
                        )}
                      </View>
                      <Text style={[styles.savedTitle, { fontSize: 16 }]}>{formatRampMoney(row.amount, row.asset)}</Text>
                    </TouchableOpacity>
                  );
                })}
                {depositsError && deposits.length ? (
                  // A failed refresh or a failed extra page: retry, never a stuck spinner.
                  <TouchableOpacity onPress={() => { loadDeposits(depositPagesRef.current); }}
                    style={{ paddingVertical: 12, alignItems: 'center' }}>
                    <Text style={styles.warningLink}>
                      {depositPages > loadedPages ? 'No pudimos cargar más depósitos.' : 'No pudimos actualizar tus depósitos.'}
                      {' '}Intentar de nuevo
                    </Text>
                  </TouchableOpacity>
                ) : deposits.length > 0 && (moreDeposits || depositPages > loadedPages) ? (
                  // Older deposits (a convertible one included) stay reachable.
                  // The spinner shows only while a newly requested page is loading;
                  // a requested page that never loaded is retried, not skipped.
                  <TouchableOpacity
                    onPress={() => (depositPages > loadedPages
                      ? loadDeposits(depositPages) : setDepositPages(pages => pages + 1))}
                    disabled={depositPages > loadedPages && depositsLoading}
                    style={{ paddingVertical: 12, alignItems: 'center' }}>
                    {depositPages > loadedPages && depositsLoading ? <ActivityIndicator color={colors.primary} />
                      : <Text style={styles.warningLink}>Ver más depósitos</Text>}
                  </TouchableOpacity>
                ) : null}
              </View>
            </RampReveal>

            {/* ─── Step 3: Conversion summary ─── */}
            {selectedId ? (
              <RampReveal delay={0}>
                <View style={styles.section}>
                  <RampStepHeader
                    number={3}
                    title="Resumen"
                    accentColor={colors.primaryDark}
                    accentBackground={colors.primaryLight}
                    titleColor={colors.dark}
                  />
                  <View style={styles.quoteCard}>
                    {quoteLoading ? (
                      <ActivityIndicator color={colors.primary} />
                    ) : quoteError ? (
                      <View style={styles.emptyQuote}>
                        <Icon name="alert-circle" size={20} color={colors.textSecondary} />
                        <Text style={styles.emptyText}>{quoteError}</Text>
                      </View>
                    ) : quote ? (
                      <>
                        <Text style={styles.quoteEyebrow}>Recibes en tu Confío Dollar</Text>
                        <Text style={[styles.quoteHeadline, isCompact && styles.quoteHeadlineCompact]}>
                          {`≈ ${formatRampMoney(quote.targetAmount, USD_UNIT)}`}
                        </Text>
                        <Text style={styles.quoteRate}>{`1 USD ≈ ${formatRampRate(quote.rate)} ${quote.asset} · todo incluido`}</Text>
                        <View style={styles.quoteDivider} />
                        <View style={styles.quoteRow}>
                          <Text style={styles.quoteLabel}>Conviertes</Text>
                          <Text style={styles.quoteValue}>{formatRampMoney(quote.sourceAmount, quote.asset)}</Text>
                        </View>
                        <View style={styles.quoteFinalDivider} />
                        <View style={styles.quoteFinalRow}>
                          <Text style={styles.quoteFinalLabel}>Recibes al menos</Text>
                          <Text style={styles.quoteFinalValue}>{formatRampMoney(quote.minimumWalletOutput, USD_UNIT)}</Text>
                        </View>
                        <View style={styles.disclaimerPill}>
                          <Icon name="info" size={12} color={colors.primaryDark} />
                          <Text style={styles.quoteNote}>Si la conversión diera menos, no la hacemos y te avisamos.</Text>
                        </View>
                      </>
                    ) : null}
                  </View>
                </View>
                <RampActionBar
                  primaryLabel="Convertir a dólares"
                  onPrimaryPress={handleConvert}
                  primaryLoading={submitting}
                  primaryDisabled={!quote}
                  primaryIconName="chevron-right"
                />
              </RampReveal>
            ) : null}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
