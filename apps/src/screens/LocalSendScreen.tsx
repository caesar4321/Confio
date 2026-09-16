import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  SafeAreaView,
  ScrollView,
  StatusBar,
  Text,
  TextInput,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Clipboard from '@react-native-clipboard/clipboard';
import { RouteProp, useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { isBrebLocationFailure } from '../services/brebLocation';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';

import { MainStackParamList } from '../types/navigation';
import { GET_MY_RAMP_ADDRESS } from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';
import { colors } from '../config/theme';
import { countryFlag, countryName } from '../config/localRails';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { RampStepHeader } from '../components/ramps/RampStepHeader';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
import { PaymentQrScannerModal } from '../components/PaymentQrScannerModal';
import { formatRampMoney, formatRampRate, USD_UNIT } from '../utils/rampFormat';
import { requestRampCriticalAuth } from '../utils/rampFlow';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { createInfiniaJourney } from '../services/infiniaJourney';
import {
  authorizePaymentBridge,
  BridgeTransfer,
  bridgeRequestId,
  preparePaymentBridge,
} from '../services/paymentBridge';
import { bridgeAmount } from './LocalAccountFundingScreen';
import {
  currencyName,
  fetchLocalDestination,
  fetchPayoutQuote,
  LOCAL_MONEY_ACCOUNTS,
  LOCAL_MONEY_LIMITS,
  LOCAL_MONEY_METHODS,
  LOCAL_SAVED_DESTINATIONS,
  LocalDestination,
  LocalLimits,
  LocalMethod,
  LocalPayoutQuote,
  recheckLocalDestination,
  resolveLocalDestination,
} from '../services/localMoney';

type Nav = NativeStackNavigationProp<MainStackParamList, 'LocalSend'>;
type Route = RouteProp<MainStackParamList, 'LocalSend'>;

// What people call each rail's identifier. The rail is the product; the
// provider behind it never appears in copy.
const COPY: Record<string, {
  hero: string; field: string; placeholder: string; helper: string; keyboard?: 'default' | 'number-pad';
}> = {
  co_breb: {
    hero: 'Envía a una llave Bre-B', field: 'Llave Bre-B de quien recibe',
    placeholder: 'Celular, cédula, correo o alias',
    helper: 'Pídesela a quien vas a pagar. Llega a Nequi, Bancolombia, Daviplata y más.',
  },
  br_pix: {
    hero: 'Envía por Pix', field: 'Chave Pix de quien recibe',
    placeholder: 'CPF, celular, e-mail o clave aleatoria', helper: 'Los celulares llevan +55 al inicio.',
  },
  mx_clabe: {
    hero: 'Envía a una CLABE', field: 'CLABE de quien recibe', placeholder: '18 dígitos',
    helper: 'Llega por SPEI a cualquier banco o billetera.', keyboard: 'number-pad',
  },
  ar_cvu: {
    hero: 'Envía a Argentina', field: 'CVU o CBU de quien recibe', placeholder: '22 dígitos',
    helper: 'Mercado Pago, Ualá, Naranja X o cualquier banco. ¿Tienes un QR? Escanéalo.', keyboard: 'number-pad',
  },
  ar_qr: {
    hero: 'Paga con QR', field: 'Código QR', placeholder: 'Escanea el QR del comercio',
    helper: 'Por ahora solo QR sin monto fijo: tú eliges cuánto pagar.',
  },
};

const AMOUNT_PATTERN = /^\d+([.,]\d{1,2})?$/;

// Same check digits as the server, checked locally before Continue.
const clabeValid = (v: string) => /^\d{18}$/.test(v)
  && (10 - v.slice(0, 17).split('').reduce((sum, d, i) => sum + (Number(d) * [3, 7, 1][i % 3]) % 10, 0) % 10) % 10
    === Number(v[17]);
const cbuBlock = (block: string, weights: number[]) =>
  (10 - block.split('').reduce((sum, d, i) => sum + Number(d) * weights[i], 0) % 10) % 10;
const cbuValid = (v: string) => /^\d{22}$/.test(v)
  && cbuBlock(v.slice(0, 7), [7, 1, 3, 9, 7, 1, 3]) === Number(v[7])
  && cbuBlock(v.slice(8, 21), [3, 9, 7, 1, 3, 9, 7, 1, 3, 9, 7, 1, 3]) === Number(v[21]);
const AUTO_LOOKUP: Record<string, { length: number; valid: (v: string) => boolean; error: string }> = {
  mx_clabe: { length: 18, valid: clabeValid, error: 'Esa CLABE no es válida. Revisa los 18 dígitos.' },
  ar_cvu: { length: 22, valid: cbuValid, error: 'Ese CVU o CBU no es válido. Revisa los 22 dígitos.' },
};

// Bound the entire recipient request, including any location retry.
const LOOKUP_TIMEOUT_MS = 20000;

// Falling back to "unverified" must not keep a holder we can no longer vouch
// for: the review would otherwise show a name the key may no longer have.
const unverifiedCopy = (row: LocalDestination): LocalDestination => ({
  ...row, verification: 'unverified', holderName: '', holderDocument: '', institution: '',
  label: row.methodId === 'ar_qr' ? 'QR' : row.label,
});
function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('No pudimos preparar el destinatario. Intenta de nuevo.')), ms);
    promise.then(
      result => { clearTimeout(timer); resolve(result); },
      error => { clearTimeout(timer); reject(error); },
    );
  });
}
const initialsOf = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]?.toUpperCase()).join('') || '?';

export default function LocalSendScreen() {
  const navigation = useNavigation<Nav>();
  const { methodId } = useRoute<Route>().params;
  const { width } = useWindowDimensions();
  const isCompact = width < 380;
  const copy = COPY[methodId] || COPY.co_breb;

  const methodsQuery = useQuery(LOCAL_MONEY_METHODS, {
    variables: { direction: 'send' }, fetchPolicy: 'cache-and-network', errorPolicy: 'all',
  });
  const accountsQuery = useQuery(LOCAL_MONEY_ACCOUNTS, { fetchPolicy: 'network-only', errorPolicy: 'all' });
  const savedQuery = useQuery(LOCAL_SAVED_DESTINATIONS, {
    variables: { methodId }, fetchPolicy: 'cache-and-network', errorPolicy: 'all',
  });
  const limitsQuery = useQuery(LOCAL_MONEY_LIMITS, { fetchPolicy: 'network-only', errorPolicy: 'all' });
  // Back from another screen (a document just verified, an account opened):
  // the rail and account state may have changed. A ref keeps the focus effect
  // from depending on query objects that change on every render.
  const refreshOnFocus = useRef(() => {});
  refreshOnFocus.current = () => {
    methodsQuery.refetch().catch(() => {});
    accountsQuery.refetch().catch(() => {});
    limitsQuery.refetch().catch(() => {}); // e.g. back from an approved limit increase
  };
  useFocusEffect(useCallback(() => { refreshOnFocus.current(); }, []));
  const { savings, cusdBalanceUsd } = useSavingsPortfolio();
  // Same self-declared address the Recarga/Retiro flows use. Many LATAM IDs
  // carry no address, so the account owner's address is the user's own.
  const { activeAccount } = useAccount();
  const isBusiness = activeAccount?.type === 'business';
  const rampAddressQuery = useQuery(GET_MY_RAMP_ADDRESS, { fetchPolicy: 'cache-and-network', errorPolicy: 'all' });
  const addressComplete = isBusiness || Boolean(rampAddressQuery.data?.myRampAddress?.isComplete);

  const method: LocalMethod | undefined = (methodsQuery.data?.localMoneyMethods || [])
    .find((row: LocalMethod) => row.id === methodId);
  // One slot per country: a country's QR rail is an input mode of its main
  // rail (Argentina: type a CVU/CBU or scan a QR), not a separate product.
  const qrMethod: LocalMethod | undefined = methodId.endsWith('_qr') ? undefined
    : (methodsQuery.data?.localMoneyMethods || []).find((row: LocalMethod) =>
      row.country === method?.country && row.id.endsWith('_qr') && row.status === 'live');
  const limits: LocalLimits | undefined = limitsQuery.data?.localMoneyLimits;
  const saved: LocalDestination[] = savedQuery.data?.localSavedDestinations || [];
  const flag = method ? countryFlag(method.country) : '';
  const place = method ? countryName(method.country) : '';

  // Dollar and local accounts are resolved server-side; the app only needs
  // their ids and the dollar account's deposit instruction for the bridge.
  const accounts = (accountsQuery.data?.myPaymentAccounts || []).filter((row: any) => row.provider === 'infinia');
  const crypto = accounts.find((row: any) => row.asset === 'USDC_POL' && row.status === 'active');
  const local = method && accounts.find((row: any) => row.asset === method.asset && row.status === 'active');
  const cryptoInstruction = crypto?.fundingInstructions?.find(
    (row: any) => row.kind === 'crypto_address' && row.status === 'active',
  );
  const pairReady = Boolean(crypto && local && cryptoInstruction);
  const openingRequired = !pairReady && ['none', 'awaiting_payment', 'provisioning'].includes(method?.accountStatus || '');
  const accountStopped = !pairReady && ['rejected', 'failed', 'closed', 'suspended'].includes(method?.accountStatus || '');
  const refreshAccounts = () => Promise.allSettled([methodsQuery.refetch(), accountsQuery.refetch()]);

  const [value, setValue] = useState('');
  const [scannedQr, setScannedQr] = useState<{payload: string; methodId: string} | null>(null);
  const [destination, setDestination] = useState<LocalDestination | null>(null);
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState('');
  const [retryRecipient, setRetryRecipient] = useState<LocalDestination | null>(null);
  // A Bre-B location check failed (e.g. permission denied): offer the location screen.
  const [locationBlocked, setLocationBlocked] = useState(false);
  const [confirmedUnverified, setConfirmedUnverified] = useState(false);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [amount, setAmount] = useState('');
  const [amountFocused, setAmountFocused] = useState(false);
  const [quote, setQuote] = useState<LocalPayoutQuote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState('');
  const [step, setStep] = useState<'form' | 'preparing' | 'review'>('form');
  const [bridge, setBridge] = useState<BridgeTransfer | null>(null);
  const [finalQuote, setFinalQuote] = useState<LocalPayoutQuote | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [flowError, setFlowError] = useState('');
  const [flowLocationBlocked, setFlowLocationBlocked] = useState(false);
  const requestId = useRef<string | null>(null);
  const submittingRef = useRef(false); // readable after an await, unlike state
  // The review is bound to the exact amount and recipient it was prepared for.
  const prepareRun = useRef(0);
  const [reviewedFor, setReviewedFor] = useState<{ amount: string; destinationId: string } | null>(null);
  // A send whose outcome is unknown (the server may have taken it): the form
  // stays locked and only "Ver estado" remains, so it never becomes a second send.
  const [unsettled, setUnsettled] = useState<{ journeyId: string | null } | null>(null);
  const locked = submitting || unsettled !== null;

  // Any edit invalidates the prepared bridge: a new amount or recipient is a
  // new authorization, never a retry of the old one.
  const resetReview = useCallback(() => {
    prepareRun.current += 1; // drops any preparation still in flight
    setReviewedFor(null);
    requestId.current = null;
    setBridge(null);
    setFinalQuote(null);
    setStep('form');
    setFlowError('');
    setFlowLocationBlocked(false);
  }, []);

  const normalizedAmount = amount.replace(',', '.');
  const amountNumber = AMOUNT_PATTERN.test(amount) ? Number(normalizedAmount) : 0;
  const available = limits?.known && limits.available != null ? Number(limits.available) : null;
  const perTransferMax = limits?.perTransferMax ? Number(limits.perTransferMax) : null;
  const spendable = savings.balanceUsd + cusdBalanceUsd;

  const amountError = !amount ? '' : !AMOUNT_PATTERN.test(amount) || amountNumber <= 0
    ? 'Ingresa un monto válido.'
    : perTransferMax && amountNumber > perTransferMax
      ? `El máximo por envío es ${formatRampMoney(perTransferMax, USD_UNIT)}.`
      : '';
  const overMonthlyLimit = available != null && amountNumber > available;

  // Opening the local account has its own screen (requirements, the server's
  // fee quote, the payment): never a surprise alert in the middle of a send.
  const ensureAccounts = useCallback(() => {
    if (!method || method.accountStatus === 'active') return;
    navigation.navigate('LocalAccountApplication', { methodId });
  }, [method, methodId, navigation]);

  // Each lookup gets a number; editing the recipient or leaving the screen
  // makes any lookup still in flight stale, so it can never overwrite a newer one.
  const lookup = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    // Set on every mount: a dev Fast Refresh re-runs this effect, and a lookup
    // in flight must still be able to finish and clear its spinner.
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const isCurrent = (run: number): boolean => mounted.current && run === lookup.current;

  // A different recipient (typed, pasted, even invalid): the checked one, its
  // confirmation, the prepared review and any lookup in flight no longer apply.
  const startNewRecipient = () => {
    setScannedQr(null);
    setRetryRecipient(null);
    setLocationBlocked(false);
    lookup.current += 1;
    resetReview();
    setResolving(false);
    setDestination(null);
    setConfirmedUnverified(false);
  };

  // Some rails answer later: poll until the holder settles, then fall back to
  // an explicit confirmation instead of waiting forever.
  const followUntilSettled = useCallback(async (run: number, first: LocalDestination) => {
    let row = first;
    for (let attempt = 0; row.verification === 'pending' && attempt < 8; attempt += 1) {
      await new Promise(res => setTimeout(res, 2000));
      if (!isCurrent(run)) return;
      try {
        row = await withTimeout(fetchLocalDestination(row.id), LOOKUP_TIMEOUT_MS);
      } catch {
        continue;
      }
      if (!isCurrent(run)) return;
      setDestination(row);
    }
    if (row.verification === 'pending' && isCurrent(run)) {
      setDestination(unverifiedCopy(row));
    }
    // isCurrent only reads refs, so the first render's copy stays correct.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resolve = useCallback(async (raw?: string, via: string = methodId) => {
    const input = (raw ?? value).trim();
    if (!input) return;
    const run = ++lookup.current;
    setRetryRecipient(null);
    setLocationBlocked(false);
    resetReview();
    setResolving(true);
    setResolveError('');
    setDestination(null);
    setConfirmedUnverified(false);
    let row: LocalDestination;
    try {
      row = await withTimeout(resolveLocalDestination(via, input, LOOKUP_TIMEOUT_MS), LOOKUP_TIMEOUT_MS);
    } catch (error: any) {
      if (isCurrent(run)) {
        setResolveError(error?.message || 'No pudimos revisar esos datos.');
        setLocationBlocked(isBrebLocationFailure(error));
        setResolving(false);
      }
      return;
    }
    if (!isCurrent(run)) return;
    // Show the recipient at once; the amount stays editable while the holder
    // name arrives. Review stays locked until it settles (recipientReady).
    setDestination(row);
    setResolving(false);
    savedQuery.refetch().catch(() => {});
    void followUntilSettled(run, row);
    return row;
  }, [value, methodId, resetReview, savedQuery, followUntilSettled]);

  // Pasting only fills the form. The server saves the recipient on Continue.
  const paste = useCallback(async () => {
    if (locked) return; // the reviewed send is being signed
    const text = (await Clipboard.getString().catch(() => '')).trim();
    if (submittingRef.current) return; // Confirm was tapped while the clipboard was read
    if (!text) {
      setResolveError('No hay nada copiado.');
      return;
    }
    const auto = AUTO_LOOKUP[methodId];
    const input = auto ? text.replace(/\D/g, '') : text;
    startNewRecipient();
    setValue(input);
    setResolveError('');
    if (auto && !auto.valid(input)) {
      setResolveError(auto.error);
      return;
    }
  }, [methodId, locked, resetReview]);

  // Live estimate while typing; the authoritative quote is priced again on
  // the prepared bridge at review.
  useEffect(() => {
    setQuote(null);
    setQuoteError('');
    setQuoteLoading(false); // a cancelled estimate cannot clear its own spinner
    if (!destination || destination.verification === 'not_found' || !pairReady || !amountNumber || amountError) {
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      setQuoteLoading(true);
      try {
        const next = await fetchPayoutQuote(destination.id, { amount: normalizedAmount });
        if (!cancelled) setQuote(next);
      } catch (error: any) {
        if (!cancelled) setQuoteError(error?.message || 'No pudimos cotizar este envío.');
      } finally {
        if (!cancelled) setQuoteLoading(false);
      }
    }, 600);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [destination, pairReady, amountNumber, amountError, normalizedAmount]);

  const recipientReady = Boolean(destination) && destination!.verification !== 'not_found'
    && destination!.verification !== 'pending'
    && (destination!.verification === 'verified' || destination!.verification === 'not_checked' || confirmedUnverified);
  const inputCheck = AUTO_LOOKUP[methodId];
  const draftReady = !destination && Boolean(scannedQr || (value.trim()
    && (!inputCheck || inputCheck.valid(value.replace(/[\s.\-/]/g, '')))));
  const canContinue = (recipientReady || draftReady) && !resolving && pairReady && amountNumber > 0 && !amountError;

  const handleContinue = async () => {
    if (!canContinue || !cryptoInstruction) return;
    let recipient = destination;
    if (!recipient) {
      const pending = resolve(scannedQr?.payload, scannedQr?.methodId || methodId);
      const resolutionRun = prepareRun.current;
      recipient = await pending || null;
      if (resolutionRun !== prepareRun.current || !mounted.current || !recipient) return;
      // An enabled lookup may return a pending/failed check. Show that result
      // before allowing review; skipped lookups follow the normal send path.
      if (!['verified', 'not_checked'].includes(recipient.verification)) return;
    }
    // A response for an older form (edited meanwhile) is dropped, never shown or signed.
    const run = ++prepareRun.current;
    const snapshot = { amount: normalizedAmount, destinationId: recipient.id };
    let bridgePrepared = false;
    setStep('preparing');
    setFlowError('');
    setFlowLocationBlocked(false);
    try {
      requestId.current ||= bridgeRequestId();
      const prepared = await preparePaymentBridge(cryptoInstruction.internalId, snapshot.amount, 'to_provider',
        requestId.current);
      bridgePrepared = true;
      if (run !== prepareRun.current) return;
      const priced = await fetchPayoutQuote(snapshot.destinationId, { bridgeId: prepared.internalId });
      if (run !== prepareRun.current) return;
      setBridge(prepared);
      setFinalQuote(priced);
      setReviewedFor(snapshot);
      setStep('review');
    } catch (error: any) {
      if (run !== prepareRun.current) return;
      if (!bridgePrepared && error?.quoteRefreshRequired === true) requestId.current = null;
      setFlowError(error?.message || 'No pudimos preparar el envío. Intenta de nuevo.');
      setStep('form');
    }
  };

  const handleConfirm = async () => {
    if (!recipientReady || !bridge || !finalQuote || !destination || !local || !crypto || !requestId.current
      || locked) return;
    // Never open a journey on a bridge that can no longer be signed: it would
    // sit unfunded until it lands in review.
    if (BigInt(bridge.deadline) <= BigInt(Math.floor(Date.now() / 1000) + 45)) {
      resetReview();
      setFlowError('La cotización venció. Revisa el envío de nuevo.');
      return;
    }
    // Sign only what was reviewed: same amount, same recipient.
    if (!reviewedFor || reviewedFor.amount !== normalizedAmount || reviewedFor.destinationId !== destination.id) {
      resetReview();
      setFlowError('El envío cambió. Revísalo de nuevo.');
      return;
    }
    // Everything below belongs to this review. An edit made while the person
    // authenticates starts a new one, and this continuation must stop.
    const run = prepareRun.current;
    const request = requestId.current;
    setSubmitting(true); // locks the button while authentication is pending
    submittingRef.current = true;
    setFlowError('');
    setFlowLocationBlocked(false);
    let journeyId: string | null = null;
    let requested = false; // the journey request left the device
    let keepLocked = false;
    try {
      const authenticated = await requestRampCriticalAuth({
        amount: Number(reviewedFor.amount), assetUnit: USD_UNIT, actionLabel: 'envío',
      });
      if (!authenticated || run !== prepareRun.current || !mounted.current) return;
      // Authentication can take a while: a bridge past its deadline can no
      // longer be signed, so no journey may be opened for it.
      if (BigInt(bridge.deadline) <= BigInt(Math.floor(Date.now() / 1000) + 45)) {
        resetReview();
        setFlowError('La cotización venció. Revisa el envío de nuevo.');
        return;
      }
      requested = true;
      const journey = await createInfiniaJourney({
        direction: 'to_bank',
        requestId: request,
        localAccountId: local.internalId,
        cryptoAccountId: crypto.internalId,
        minimumFxOutput: finalQuote.minimumTarget,
        bridgeId: bridge.internalId,
        destinationId: destination.id,
      });
      journeyId = journey.internalId;
      // Signing moves the money: never for a review that changed or a screen
      // that is gone. (The form is locked while submitting, so only an
      // unmount can get here.)
      if (run !== prepareRun.current || !mounted.current) return;
      await authorizePaymentBridge(bridge);
      if (mounted.current && navigation.isFocused()) {
        navigation.replace('LocalTransferStatus', { journeyId: journey.internalId });
      } else {
        // The person moved on while signing: the send is done and must not
        // replace where they are now. The review stays locked on it and, back
        // here, offers only its status.
        keepLocked = true;
        if (mounted.current) setUnsettled({ journeyId: journey.internalId });
      }
    } catch (error: any) {
      if (!journeyId && isBrebLocationFailure(error)) {
        // The server refused before creating anything (no current location
        // pass) and the location check then failed: nothing was sent, so the
        // form stays usable and the location screen is offered.
        if (mounted.current) {
          setFlowError(error?.message || 'Confirma tu ubicación para usar Bre-B.');
          setFlowLocationBlocked(true);
        }
      } else if (journeyId || (requested && error?.networkError)) {
        // The server may have taken it even though no answer arrived. The form
        // stays locked: checking the status is the only way forward, so this
        // can never turn into a second send.
        keepLocked = true;
        if (mounted.current) {
          setUnsettled({ journeyId });
          setFlowError('No pudimos confirmar si tu envío salió. Revisa su estado antes de enviar otra vez.');
        }
      } else if (mounted.current) {
        setFlowError(error?.message || 'No pudimos confirmar el envío. Intenta de nuevo.');
      }
    } finally {
      submittingRef.current = keepLocked;
      if (mounted.current) setSubmitting(false);
    }
  };

  const pickSaved = (row: LocalDestination) => {
    if (locked) return; // the reviewed send is being signed
    const run = ++lookup.current; // a lookup still in flight must not replace this choice
    setRetryRecipient(null);
    setLocationBlocked(false);
    setResolving(true);
    resetReview();
    setValue('');
    setScannedQr(null);
    setResolveError('');
    setConfirmedUnverified(false);
    // A saved check can be old (keys get re-registered to someone else): it is
    // not shown as verified until the server confirms or re-checks it.
    setDestination({ ...row, verification: 'pending' });
    withTimeout(recheckLocalDestination(row.id, LOOKUP_TIMEOUT_MS), LOOKUP_TIMEOUT_MS)
      .then(fresh => {
        if (!isCurrent(run)) return undefined;
        setResolving(false);
        setDestination(fresh);
        return followUntilSettled(run, fresh);
      })
      .catch((error: any) => {
        if (!isCurrent(run)) return;
        setResolving(false);
        // A failed request says nothing about the holder. Never turn a
        // transport/auth/schema error into permission to override verification.
        setDestination(null);
        if (isBrebLocationFailure(error)) {
          // Say why, and offer the location screen (it handles Settings and retries).
          setResolveError(error?.message || 'Confirma tu ubicación para usar Bre-B.');
          setLocationBlocked(true);
        } else {
          setResolveError('No pudimos cargar los datos del destinatario. Intenta de nuevo.');
        }
        setRetryRecipient(row);
      });
  };

  const unavailable = methodsQuery.data && (!method || method.status !== 'live');
  const quoteHeadline = quote ? `≈ ${formatRampMoney(quote.targetAmount, quote.asset)}` : '';
  const currency = method ? currencyName(method.asset) : 'moneda local';

  const recipientCard = useMemo(() => {
    if (resolving) {
      return null; // The Continue action owns the bounded preparation spinner.
    }
    if (!destination && scannedQr) return <Text style={styles.helperText}>QR escaneado. Ingresa el monto para continuar.</Text>;
    if (!destination) return null;
    if (destination.verification === 'not_checked') {
      return (
        <View style={styles.recipientCard}>
          <Icon name="user" size={20} color={colors.primary} />
          <View style={styles.savedCopy}>
            <Text style={styles.savedTitle}>{destination.label}</Text>
            <Text style={styles.savedText}>Confirma que estos son los datos que te compartió quien recibe.</Text>
          </View>
        </View>
      );
    }
    if (destination.verification === 'not_found') {
      return <Text style={styles.errorText}>No encontramos esta cuenta. Revisa los datos.</Text>;
    }
    if (destination.verification === 'pending') {
      // The rail answers later; the amount stays editable meanwhile.
      return (
        <View style={styles.verifiedCard}>
          <ActivityIndicator color={colors.primary} />
          <View style={styles.savedCopy}>
            <Text style={styles.savedTitle}>Verificando titular…</Text>
            <Text style={styles.savedText}>{destination.label}</Text>
          </View>
        </View>
      );
    }
    if (destination.verification === 'verified') {
      return (
        <View style={styles.verifiedCard}>
          <View style={styles.initials}>
            <Text style={styles.initialsText}>{initialsOf(destination.holderName)}</Text>
          </View>
          <View style={styles.savedCopy}>
            <Text style={styles.savedTitle}>{destination.holderName}</Text>
            <Text style={styles.savedText}>
              {[destination.institution, destination.holderDocument].filter(Boolean).join(' · ') || destination.label}
            </Text>
            <View style={styles.verifiedPill}>
              <Icon name="check" size={12} color={colors.successText} />
              <Text style={styles.verifiedPillText}>Titular verificado</Text>
            </View>
          </View>
        </View>
      );
    }
    return (
      <>
        <View style={styles.warningCard}>
          <Icon name="alert-triangle" size={18} color={colors.warning.icon} />
          <View style={{ flex: 1 }}>
            <Text style={styles.warningTitle}>No pudimos verificar el titular</Text>
            <Text style={styles.warningText}>
              Revisa los datos con quien te pidió el pago. Si no son de esa persona, puede que no recuperes el dinero.
            </Text>
          </View>
        </View>
        <TouchableOpacity
          style={styles.checkboxRow}
          onPress={() => {
            if (locked) return;
            resetReview(); // a review prepared with the other answer no longer applies
            setConfirmedUnverified(!confirmedUnverified);
          }}
          accessibilityRole="checkbox"
          accessibilityState={{ checked: confirmedUnverified }}
        >
          <View style={[styles.checkbox, confirmedUnverified && styles.checkboxChecked]}>
            {confirmedUnverified ? <Icon name="check" size={14} color={colors.white} /> : null}
          </View>
          <Text style={styles.checkboxText}>Revisé los datos y son correctos</Text>
        </TouchableOpacity>
      </>
    );
  }, [resolving, destination, scannedQr, confirmedUnverified, locked, resetReview]);

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled">
        <RampReveal delay={0}>
          <RampHero
            eyebrow="Enviar"
            title={copy.hero}
            subtitle={`Tus dólares llegan como ${currency} a la cuenta de otra persona o negocio. Revisa el estimado y confirma al final.`}
            onBack={() => navigation.goBack()}
            compact={isCompact}
          />
        </RampReveal>

        <RampReveal delay={60}>
          <View style={styles.bannerCard}>
            <View style={styles.bannerIconWrap}>
              <Icon name="send" size={16} color={colors.primary} />
            </View>
            <View style={styles.bannerCopy}>
              <Text style={styles.bannerTitle}>{flag ? `${flag} ` : ''}Envío a {place || 'otro país'}</Text>
              <Text style={styles.bannerText}>Guardamos a quién le envías para que la próxima vez sea más rápido.</Text>
            </View>
            <TouchableOpacity style={styles.historyPill} onPress={() => navigation.navigate('LocalTransferStatus')}
              activeOpacity={0.8}>
              <Icon name="clock" size={14} color={colors.primary} />
              <Text style={styles.historyPillText}>Ver envíos</Text>
            </TouchableOpacity>
          </View>
        </RampReveal>

        {!methodsQuery.data && methodsQuery.loading ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} size="small" />
            <Text style={styles.loadingText}>Cargando…</Text>
          </View>
        ) : unavailable ? (
          <View style={styles.emptyStateCard}>
            <View style={styles.emptyStateIconWrap}>
              <Icon name="info" size={22} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyStateTitle}>Este medio no está disponible</Text>
            <Text style={styles.emptyStateText}>
              {method?.status === 'needs_verification'
                ? 'Verifica tu identidad para enviar a cuentas locales.'
                : method?.status === 'needs_document'
                  ? `Para enviar a ${place} necesitamos un documento distinto al que ya verificaste.`
                  : 'Todavía no puedes enviar por aquí desde tu cuenta.'}
            </Text>
            {method?.status === 'needs_verification' ? (
              <TouchableOpacity style={styles.primaryActionButton} onPress={() => navigation.navigate('Verification')}>
                <Text style={styles.primaryActionButtonText}>Verificar identidad</Text>
              </TouchableOpacity>
            ) : method?.status === 'needs_document' ? (
              <TouchableOpacity style={styles.primaryActionButton} onPress={() => navigation.navigate('AdditionalDocument', {
                idCountry: method.documentCountry, documentTypes: method.documentTypes,
                reason: `Para enviar a ${place} necesitamos un documento distinto al que ya verificaste.`,
              })}>
                <Text style={styles.primaryActionButtonText}>Verificar documento</Text>
              </TouchableOpacity>
            ) : null}
          </View>
        ) : (
          <>
            {/* ─── Step 1: Recipient ─── */}
            <RampReveal delay={110}>
              <View style={styles.section}>
                <RampStepHeader
                  number={1}
                  title="Destinatario"
                  meta={method ? `${flag ? `${flag} ` : ''}${place} · ${method.asset}` : null}
                  accentColor={colors.primaryDark}
                  accentBackground={colors.primaryLight}
                  titleColor={colors.dark}
                  metaColor={colors.textSecondary}
                />
                {saved.map(row => {
                  const selected = destination?.id === row.id;
                  return (
                    <TouchableOpacity key={row.id} style={[styles.savedCard, selected && styles.savedCardSelected]}
                      onPress={() => pickSaved(row)} activeOpacity={0.7}>
                      <View style={styles.savedCopy}>
                        <Text style={styles.savedTitle}>{row.holderName || row.label}</Text>
                        {row.holderName ? <Text style={styles.savedText}>{row.label}</Text> : null}
                      </View>
                      <View style={[styles.radioOuter, selected && styles.radioOuterChecked]}>
                        {selected ? <View style={styles.radioInner} /> : null}
                      </View>
                    </TouchableOpacity>
                  );
                })}
                <View style={[styles.inputCard, saved.length ? { marginTop: 12 } : null]}>
                  <Text style={styles.inputLabel}>{saved.length ? 'Nuevo destinatario' : copy.field}</Text>
                  {methodId === 'ar_qr' ? (
                    <TouchableOpacity style={styles.smallPrimary} onPress={() => { if (!locked) setScannerOpen(true); }}>
                      <Icon name="maximize" size={18} color={colors.white} />
                      <Text style={styles.smallPrimaryText}>{scannedQr ? 'Escanear otro QR' : 'Escanear QR'}</Text>
                    </TouchableOpacity>
                  ) : (
                    <View style={[styles.amountInputRow, styles.amountInputRowFocused]}>
                      <TextInput
                        style={styles.textInput}
                        value={value}
                        editable={!locked}
                        onChangeText={next => {
                          startNewRecipient();
                          setValue(next);
                          setResolveError('');
                          const auto = AUTO_LOOKUP[methodId];
                          const digits = next.replace(/\D/g, '');
                          if (auto && digits.length === auto.length) {
                            if (!auto.valid(digits)) setResolveError(auto.error);
                          }
                        }}
                        placeholder={copy.placeholder}
                        placeholderTextColor={colors.textSecondary}
                        keyboardType={copy.keyboard || 'default'}
                        autoCapitalize="none"
                        autoCorrect={false}
                        returnKeyType="done"
                      />
                        <TouchableOpacity style={styles.addButton} onPress={paste} disabled={locked}
                          accessibilityLabel="Pegar desde el portapapeles">
                          <Text style={styles.addButtonText}>Pegar</Text>
                        </TouchableOpacity>
                      {qrMethod ? (
                        <TouchableOpacity style={[styles.addButton, { marginLeft: 8 }]} onPress={() => { if (!locked) setScannerOpen(true); }}
                          accessibilityLabel="Escanear QR">
                          <Icon name="maximize" size={18} color={colors.primaryDark} />
                        </TouchableOpacity>
                      ) : null}
                    </View>
                  )}
                  <Text style={styles.helperText}>{copy.helper}</Text>
                  {resolveError ? <Text style={styles.errorText}>{resolveError}</Text> : null}
                  {locationBlocked ? (
                    <TouchableOpacity accessibilityRole="button" onPress={() => navigation.navigate('BrebLocationCheck')}>
                      <Text style={styles.addButtonText}>Confirmar ubicación</Text>
                    </TouchableOpacity>
                  ) : null}
                  {retryRecipient ? (
                    <TouchableOpacity accessibilityRole="button" disabled={locked} onPress={() => pickSaved(retryRecipient)}>
                      <Text style={styles.addButtonText}>Intentar de nuevo</Text>
                    </TouchableOpacity>
                  ) : null}
                  {recipientCard}
                </View>
              </View>
            </RampReveal>

            {/* ─── Step 2: Amount ─── */}
            <RampReveal delay={150}>
              <View style={styles.section}>
                <RampStepHeader
                  number={2}
                  title="Monto"
                  accentColor={colors.primaryDark}
                  accentBackground={colors.primaryLight}
                  titleColor={colors.dark}
                />
                <View style={styles.inputCard}>
                  <Text style={styles.inputLabel}>Envías desde tu Confío Dollar</Text>
                  <View style={[styles.amountInputRow, amountFocused && styles.amountInputRowFocused]}>
                    <TextInput
                      style={styles.amountInput}
                      value={amount}
                      editable={!locked}
                      onChangeText={next => { setAmount(next); resetReview(); }}
                      onFocus={() => setAmountFocused(true)}
                      onBlur={() => setAmountFocused(false)}
                      keyboardType="decimal-pad"
                      placeholder="0"
                      placeholderTextColor={colors.textSecondary}
                    />
                    <View style={styles.currencyBadge}>
                      <Text style={styles.currencyBadgeText}>USD</Text>
                    </View>
                  </View>
                  <Text style={styles.helperText}>Verás cuánto recibe y el tipo de cambio antes de confirmar.</Text>
                  <Text style={styles.limitText}>Saldo disponible: {formatRampMoney(spendable, USD_UNIT)}</Text>
                  {limits?.known && available != null ? (
                    <Text style={styles.limitText}>
                      Disponible este mes: {formatRampMoney(available, USD_UNIT)}
                      {perTransferMax ? ` · Máximo por envío: ${formatRampMoney(perTransferMax, USD_UNIT)}` : ''}
                    </Text>
                  ) : null}
                  {amountError ? <Text style={styles.errorText}>{amountError}</Text> : null}
                  {overMonthlyLimit || limits?.nearLimit ? (
                    <TouchableOpacity onPress={() => navigation.navigate('LocalLimitIncrease')}>
                      <Text style={[styles.historyPillText, { marginTop: 8 }]}>Aumentar mi límite mensual</Text>
                    </TouchableOpacity>
                  ) : null}
                </View>
              </View>
            </RampReveal>

            {/* ─── Step 3: Summary ─── */}
            <RampReveal delay={190}>
              <View style={styles.section}>
                <RampStepHeader
                  number={3}
                  title="Resumen"
                  accentColor={colors.primaryDark}
                  accentBackground={colors.primaryLight}
                  titleColor={colors.dark}
                />
                <View style={styles.quoteCard}>
                  {accountsQuery.error && !pairReady ? (
                    // Without the account data "Continuar" stays off: say why and let them retry.
                    <TouchableOpacity onPress={() => { accountsQuery.refetch().catch(() => {}); }}>
                      <Text style={styles.warningLink}>No pudimos cargar tu cuenta local. Intentar de nuevo</Text>
                    </TouchableOpacity>
                  ) : null}
                  {method?.accountStatus === 'none' ? (
                    <Text style={styles.emptyText}>Primero abre tu cuenta en {currency}. Te mostramos el costo antes de confirmar.</Text>
                  ) : !pairReady ? (
                    <Text style={styles.emptyText}>
                      {method?.accountStatus === 'awaiting_payment' ? 'Completa el pago de apertura para usar tu cuenta.'
                        : method?.accountStatus === 'provisioning' ? 'Tu cuenta sigue en proceso de apertura. Puedes revisar su estado abajo.'
                        : accountStopped ? 'Tu cuenta no está disponible para enviar. Escríbenos a soporte para revisarla.'
                        : method?.accountStatus === 'active'
                          ? 'Tu apertura está pagada. Actualiza los datos de tu cuenta para continuar; no tienes que pagar otra vez.'
                          : 'No pudimos confirmar el estado de tu cuenta. Actualiza sus datos para continuar.'}
                    </Text>
                  ) : null}
                  {!pairReady ? null : quoteLoading ? (
                    <ActivityIndicator color={colors.primary} />
                  ) : quoteError ? (
                    <View style={styles.emptyQuote}>
                      <Icon name="alert-circle" size={20} color={colors.textSecondary} />
                      <Text style={styles.emptyText}>{quoteError}</Text>
                    </View>
                  ) : quote ? (
                    <>
                      <Text style={styles.quoteEyebrow}>Estimado que recibe</Text>
                      <Text style={[styles.quoteHeadline, isCompact && styles.quoteHeadlineCompact]}>{quoteHeadline}</Text>
                      <Text style={styles.quoteRate}>{`1 USD ≈ ${formatRampRate(quote.rate)} ${quote.asset} · estimado neto de conversión`}</Text>
                      <View style={styles.quoteDivider} />
                      <View style={styles.quoteRow}>
                        <Text style={styles.quoteLabel}>Envías</Text>
                        <Text style={styles.quoteValue}>{formatRampMoney(normalizedAmount, USD_UNIT)}</Text>
                      </View>
                      <View style={styles.quoteRow}>
                        <Text style={styles.quoteLabel}>Tipo de cambio</Text>
                        <Text style={styles.quoteValue}>{`${formatRampRate(quote.rate)} ${quote.asset}/USD`}</Text>
                      </View>
                      <View style={styles.quoteFinalDivider} />
                      <View style={styles.quoteFinalRow}>
                        <Text style={styles.quoteFinalLabel}>Recibe al menos</Text>
                        <Text style={styles.quoteFinalValue}>{formatRampMoney(quote.minimumTarget, quote.asset)}</Text>
                      </View>
                      <View style={styles.disclaimerPill}>
                        <Icon name="info" size={12} color={colors.primaryDark} />
                        <Text style={styles.quoteNote}>Si la conversión diera menos, no enviamos el pago y te avisamos.</Text>
                      </View>
                    </>
                  ) : (
                    <View style={styles.emptyQuote}>
                      <Icon name="bar-chart-2" size={20} color={colors.textSecondary} />
                      <Text style={styles.emptyText}>Elige a quién envías e ingresa el monto para ver el estimado.</Text>
                    </View>
                  )}
                </View>
              </View>
            </RampReveal>

            {flowError ? (
              <Text style={[styles.errorText, { marginHorizontal: 22, marginTop: -8, marginBottom: 12 }]}>{flowError}</Text>
            ) : null}
            {flowError && flowLocationBlocked ? (
              <TouchableOpacity accessibilityRole="button" style={{ marginHorizontal: 22, marginBottom: 12 }}
                onPress={() => navigation.navigate('BrebLocationCheck')}>
                <Text style={styles.addButtonText}>Confirmar ubicación</Text>
              </TouchableOpacity>
            ) : null}

            {/* ─── Action ─── */}
            {step === 'review' && bridge && finalQuote && destination ? (
              <RampReveal delay={0}>
                <View style={styles.reviewCard}>
                  <Text style={styles.reviewTitle}>Revisión final</Text>
                  {destination.holderName ? <View style={styles.reviewRow}>
                    <Icon name="user" size={16} color={colors.textSecondary} />
                    <Text style={styles.reviewLabel}>Para</Text>
                    <Text style={styles.reviewValue}>{destination.holderName}</Text>
                  </View> : null}
                  <View style={styles.reviewRow}>
                    <Icon name="credit-card" size={16} color={colors.textSecondary} />
                    <Text style={styles.reviewLabel}>Destino</Text>
                    <Text style={styles.reviewValue}>{destination.label}</Text>
                  </View>
                  <Text style={styles.helperText}>Revisa el destino y el monto antes de confirmar el envío.</Text>
                  <View style={styles.reviewRow}>
                    <Icon name="dollar-sign" size={16} color={colors.textSecondary} />
                    <Text style={styles.reviewLabel}>Envías</Text>
                    <Text style={styles.reviewValue}>{formatRampMoney(normalizedAmount, USD_UNIT)}</Text>
                  </View>
                  {BigInt(bridge.feeUnits || '0') > 0n ? (
                    <View style={styles.reviewRow}>
                      <Icon name="repeat" size={16} color={colors.textSecondary} />
                      <Text style={styles.reviewLabel}>Comisión de Confío (incluida)</Text>
                      <Text style={styles.reviewValue}>{formatRampMoney(bridgeAmount(bridge.feeUnits, 18), USD_UNIT)}</Text>
                    </View>
                  ) : null}
                  <View style={styles.reviewRow}>
                    <Icon name="check-circle" size={16} color={colors.textSecondary} />
                    <Text style={styles.reviewLabel}>Recibe al menos</Text>
                    <Text style={styles.reviewValueHighlight}>{formatRampMoney(finalQuote.minimumTarget, finalQuote.asset)}</Text>
                  </View>
                  <View style={styles.settlementNotice}>
                    <Icon name="clock" size={13} color={colors.textSecondary} />
                    <Text style={styles.settlementNoticeText}>
                      Normalmente llega en minutos. Puedes cerrar la app; te avisaremos.
                    </Text>
                  </View>
                  {unsettled ? (
                    // The outcome is unknown: checking it is the only way forward.
                    <RampActionBar
                      primaryLabel="Ver estado del envío"
                      onPrimaryPress={() => navigation.replace('LocalTransferStatus',
                        unsettled.journeyId ? { journeyId: unsettled.journeyId } : undefined)}
                    />
                  ) : (
                    <RampActionBar
                      primaryLabel="Confirmar envío"
                      onPrimaryPress={handleConfirm}
                      primaryLoading={submitting}
                      secondaryLabel="Editar envío"
                      onSecondaryPress={() => { if (!submittingRef.current) resetReview(); }}
                    />
                  )}
                </View>
              </RampReveal>
            ) : (
              <RampReveal delay={230}>
                <RampActionBar
                  primaryLabel={!pairReady && method?.accountStatus === 'none' ? 'Solicitar cuenta'
                    : !pairReady && method?.accountStatus === 'awaiting_payment' ? 'Completar apertura'
                    : !pairReady && method?.accountStatus === 'provisioning' ? 'Revisar apertura'
                    : accountStopped ? 'Escribir a soporte' : !pairReady ? 'Actualizar cuenta' : 'Continuar'}
                  onPrimaryPress={openingRequired ? ensureAccounts : accountStopped
                    ? () => navigation.navigate('HomeMessages', { initialChannelId: 'soporte' })
                    : !pairReady ? refreshAccounts : handleContinue}
                  primaryDisabled={pairReady ? !canContinue : false}
                  primaryLoading={resolving || step === 'preparing'}
                  primaryIconName="chevron-right"
                />
              </RampReveal>
            )}
          </>
        )}
      </ScrollView>
      <PaymentQrScannerModal
        visible={scannerOpen}
        onClose={() => setScannerOpen(false)}
        hint="Apunta al código QR del comercio"
        onScanned={payload => {
          if (locked) return;
          startNewRecipient();
          setValue('');
          setResolveError('');
          setScannedQr({payload, methodId: qrMethod?.id || methodId});
        }}
      />
    </SafeAreaView>
  );
}
