// A top-up created right in the conversation ("Recargar ahora" with a local
// bank, where it goes through Koywe).
//
// The person writes the amount in their own currency and picks the method;
// the form shows what they get and creates the order with the same checks,
// in the same order, as the top-up screen (screens/TopUpScreen): the wallet
// backup, the provider's quote and limits, identity for that country, the
// address, the bank's e-mail where it is asked for, and Confío Face. The
// order's own instructions then stay under it (TopUpOrderCard). The server
// enforces every one of these again.
//
// In the floating chat (a modal) Confío Face cannot open: there the form
// hands over to the top-up screen with the amount already written.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { gql, useMutation, useQuery } from '@apollo/client';
import { selectCreateRampOrderMutation } from '../apollo/mutations';
import {
  GET_ME, GET_MY_IDENTITY_STATUS, GET_MY_PERSONAL_KYC_STATUS, GET_MY_RAMP_ADDRESS, GET_RAMP_AVAILABILITY,
  GET_RAMP_TEST_IDENTITY,
} from '../apollo/queries';
import { Text, TextInput } from '../components/common/AppText';
import { isKoyweRoutingEnabledForCountry } from '../config/env';
import { useAuth } from '../contexts/AuthContext';
import { useBackupEnforcement } from '../hooks/useBackupEnforcement';
import { useKoyweReplaced } from '../hooks/useKoyweReplaced';
import { useRampCountry } from '../hooks/useRampCountry';
import { useRampQuoteFlow, validateRampContinue } from '../hooks/useRampQuoteFlow';
import { navigationRef } from '../navigation/RootNavigation';
import { AnalyticsService } from '../services/analyticsService';
import { FaceCheckError, isFaceStepUpRequired, withFaceStepUp } from '../services/faceStepUp';
import { hasKoyweTestIdentity } from '../utils/koyweTestIdentity';
import { sanitizeAmountInput, toAmountInput } from '../utils/numberLocale';
import { getFriendlyRampError } from '../utils/rampErrors';
import { requestRampCriticalAuth } from '../utils/rampFlow';
import { USD_UNIT, formatRampMoney } from '../utils/rampFormat';
import { hasRampIdentity, needsCountryDocument } from '../utils/rampIdentity';
import { AddressForm } from './AddressForm';
import { TopUpOrderCard, type TopUpOrder } from './TopUpOrderCard';

const EMERALD = '#047857';
const INK = '#111827';
const MUTED = '#4B5563';
const PREFILL = /^([A-Z]{3})=(\d{1,9}(?:\.\d{1,2})?)$/;
const RELAY = /@privaterelay\.appleid\.com$/i;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// The bank asks for a deliverable e-mail on these (Colombia).
const EMAIL_METHODS = ['PSE', 'NEQUI', 'BANCOLOMBIA'];

// The order this message's form created, kept by the server with the message:
// after a restart the conversation shows that order, never the form again.
// Each its own operation: a server without it refuses only that one.
export const GET_MESSAGE_TOP_UP = gql`
  query AssistantTopUp($messageId: ID!) {
    assistantTopUp(messageId: $messageId) {
      status orderId countryCode fiatCurrency fiatAmount paymentMethodCode paymentMethodDisplay
    }
  }
`;
export const ATTACH_TOP_UP = gql`
  mutation AttachAssistantTopUp($messageId: ID!, $orderId: String!, $paymentMethodCode: String, $paymentMethodDisplay: String) {
    attachAssistantTopUp(
      messageId: $messageId, orderId: $orderId, paymentMethodCode: $paymentMethodCode,
      paymentMethodDisplay: $paymentMethodDisplay
    ) { success }
  }
`;

/** 'BOB=500' from the assistant's action → what to fill in; null for anything else. */
export function topUpPrefill(arg?: string | null): { currency: string; amount: string } | null {
  const parts = PREFILL.exec(arg || '');
  return parts ? { currency: parts[1], amount: parts[2] } : null;
}

/** The top-up form of an answer: { type: 'form', target: 'topup' | 'topup:BOB=500', label }. */
export function resolveTopUp(a: { type: string; target?: string | null; label?: string | null }): {
  label: string; prefill: { currency: string; amount: string } | null;
} | null {
  if (a.type !== 'form' || !a.label || !a.target || !(a.target === 'topup' || a.target.startsWith('topup:'))) {
    return null;
  }
  const prefill = a.target === 'topup' ? null : topUpPrefill(a.target.slice('topup:'.length));
  // An argument this build cannot read is no form at all, never an empty one.
  return a.target === 'topup' || prefill ? { label: a.label, prefill } : null;
}

type Missing = { text: string; button: string; screen: string; params?: Record<string, unknown> } | null;

export function TopUpForm({ messageId, label, prefill, onLeaveBox }: {
  /** The assistant's message this form hangs from: its order is kept with it. */
  messageId: string;
  label: string;
  prefill?: { currency: string; amount: string } | null;
  /** In the floating chat: closes it before a screen opens (and Face cannot run there). */
  onLeaveBox?: () => void;
}) {
  const { userProfile } = useAuth() as any;
  const { checkBackupEnforcement, BackupEnforcementModal } = useBackupEnforcement();
  const { countryCode, loading: countryLoading } = useRampCountry();
  const koywe = isKoyweRoutingEnabledForCountry(countryCode);
  const { data: meData } = useQuery(GET_ME);
  const { data: identityData, refetch: refetchIdentity } = useQuery(GET_MY_IDENTITY_STATUS, { fetchPolicy: 'cache-and-network' });
  // Where this form stands on the server: already has its order, too old, or live.
  const { data: keptData, error: keptError } = useQuery(GET_MESSAGE_TOP_UP, {
    variables: { messageId }, fetchPolicy: 'network-only',
  });
  const kept = keptData?.assistantTopUp;
  const live = kept?.status === 'none';
  const [attach] = useMutation(ATTACH_TOP_UP, { errorPolicy: 'ignore' });
  // QR Bolivia took Koywe's place for this person: this form is not their top-up any more.
  const replaced = useKoyweReplaced().topUp;
  const { data: personalKycData } = useQuery(GET_MY_PERSONAL_KYC_STATUS);
  const { data: addressData, loading: addressLoading } = useQuery(GET_MY_RAMP_ADDRESS, {
    fetchPolicy: 'cache-and-network', skip: !koywe,
  });
  const { data: availabilityData, loading: availabilityLoading } = useQuery(GET_RAMP_AVAILABILITY, {
    variables: { countryCode }, fetchPolicy: 'cache-and-network', skip: !koywe,
  });
  const { data: testIdentityData } = useQuery(GET_RAMP_TEST_IDENTITY, {
    variables: { countryCode }, skip: !koywe, fetchPolicy: 'network-only', errorPolicy: 'ignore',
  });
  // New money goes to the person's dollars on BSC (the screen's default rail).
  const [createRampOrder] = useMutation(selectCreateRampOrderMutation(true));
  useEffect(() => {
    // Self-heal the bsc_address registration before the order can need it.
    import('../services/authService').then(({ ensureBscAddressRegistered }) => ensureBscAddressRegistered()).catch(() => {});
  }, []);

  const availability = availabilityData?.rampAvailability;
  const methods: any[] = availability?.onRampMethods || [];
  const fiatCurrency: string = availability?.fiatCurrency || '';
  const mapped = koywe && !replaced && !!availability?.onRampEnabled && methods.length > 0;

  const [amount, setAmount] = useState('');
  const [methodCode, setMethodCode] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [missing, setMissing] = useState<Missing>(null);
  // The address is what is missing: it is filled in right here, under the amount.
  const [needsAddress, setNeedsAddress] = useState(false);
  const [order, setOrder] = useState<TopUpOrder | null>(null);
  const [pending, setPending] = useState<TopUpOrder | null>(null);   // an earlier order still unpaid
  const submitting = useRef(false);

  // The amount the person wrote in the chat, only in the currency they wrote
  // it in. If the form's currency then turns out to be another (their rail
  // country arrives a moment later), what was filled in is taken back: 500
  // bolivianos are never 500 soles.
  const filled = useRef<{ currency: string; text: string } | null>(null);
  useEffect(() => {
    if (!fiatCurrency || !prefill) return;
    if (filled.current && filled.current.currency !== fiatCurrency) {
      const was = filled.current.text;
      filled.current = { currency: fiatCurrency, text: '' };
      setAmount((typed) => (typed === was ? '' : typed));
      return;
    }
    if (filled.current) return;
    const value = Number(prefill.amount);
    const text = prefill.currency === fiatCurrency && Number.isFinite(value) && value > 0 ? toAmountInput(value) : '';
    filled.current = { currency: fiatCurrency, text };
    if (text) {
      setAmount((typed) => typed || text);
    }
  }, [fiatCurrency, prefill]);
  // The title names an amount ("Recargar 500 bolivianos") only where it holds.
  const title = prefill && fiatCurrency && prefill.currency !== fiatCurrency ? 'Recargar' : label;

  const method = useMemo(() => methods.find((m) => m.code === methodCode) || methods[0] || null, [methods, methodCode]);
  const { parsedAmount, amountReady, quote, quoteLoading, quoteError, amountError } = useRampQuoteFlow({
    direction: 'ON_RAMP',
    amount,
    countryCode: availability?.countryCode,
    fiatCurrency,
    paymentMethodCode: method?.code,
    // An old or already used form asks the provider nothing.
    enabled: mapped && live,
    minAmount: Number(method?.onRampMinAmount || 0),
    maxAmount: Number(method?.onRampMaxAmount || 0),
    destination: 'cusd_plus',
  });

  const verified = useMemo(() => (
    (mapped && hasKoyweTestIdentity(meData?.me?.username, countryCode, testIdentityData?.rampAvailability))
    || hasRampIdentity(identityData?.myIdentityStatus, personalKycData?.myPersonalKycStatus?.status, countryCode)
  ), [mapped, meData?.me?.username, countryCode, testIdentityData?.rampAvailability, identityData?.myIdentityStatus,
    personalKycData?.myPersonalKycStatus?.status]);
  const accountEmail = String(meData?.me?.email || userProfile?.email || '').trim();
  const storedEmail = String(addressData?.myRampAddress?.authEmail || '').trim().toLowerCase();
  const storedEmailUsable = !!storedEmail && !RELAY.test(storedEmail) && !/@koywe-test\.com$/i.test(storedEmail);
  const emailMethod = countryCode === 'CO' && EMAIL_METHODS.includes(String(method?.code || '').toUpperCase());
  const needsEmail = emailMethod && RELAY.test(accountEmail) && !storedEmailUsable;

  const go = (screen: string, params?: Record<string, unknown>) => {
    onLeaveBox?.();
    setTimeout(() => {
      if (navigationRef.isReady()) {
        (navigationRef as any).navigate(screen, params);
      }
    }, onLeaveBox ? 250 : 0);
  };
  const instructions = (o: TopUpOrder) => go('RampInstructions', { direction: 'ON_RAMP', ...o });
  const openScreen = () => go('TopUp', parsedAmount > 0 && fiatCurrency
    ? { amount: String(parsedAmount), amountCurrency: fiatCurrency } : undefined);

  const submit = async () => {
    if (submitting.current || !method) return;
    setError('');
    setMissing(null);
    const problem = validateRampContinue({
      hasSelectedMethod: !!method, amountReady, quoteLoading, quoteError, quote, amountError,
    });
    if (problem) {
      setError(problem);
      return;
    }
    if (onLeaveBox) {
      // Confío Face is a screen of its own: it cannot open over this box.
      openScreen();
      return;
    }
    submitting.current = true;
    setBusy(true);
    try {
      if (!(await checkBackupEnforcement('bsc_deposit'))) return;
      let isVerified = verified;
      if (!isVerified) {
        // Just back from verifying: read it again before saying it is missing.
        const fresh = await refetchIdentity().catch(() => null);
        isVerified = hasRampIdentity(fresh?.data?.myIdentityStatus, personalKycData?.myPersonalKycStatus?.status, countryCode);
      }
      if (!isVerified) {
        setMissing(needsCountryDocument(identityData?.myIdentityStatus, countryCode)
          // Verified with another country's document: the screen has the choices for that.
          ? { text: 'Para recargar desde este país hace falta un documento de aquí.', button: 'Abrir Recargar', screen: 'TopUp' }
          : { text: 'Antes de recargar necesitamos validar tu identidad.', button: 'Verificar mi identidad', screen: 'Verification' });
        return;
      }
      if (addressLoading) {
        setError('Estoy revisando tu dirección. Inténtalo de nuevo en un momento.');
        return;
      }
      if (!addressData?.myRampAddress?.isComplete) {
        setNeedsAddress(true);
        return;
      }
      let authEmail: string | undefined = emailMethod && storedEmailUsable ? storedEmail : undefined;
      if (needsEmail) {
        const typed = email.trim().toLowerCase();
        if (!EMAIL.test(typed) || RELAY.test(typed) || /@koywe-test\.com$/i.test(typed)) {
          setError('Escribe un correo tuyo que puedas abrir: el banco te escribe ahí.');
          return;
        }
        authEmail = typed;
      }
      void AnalyticsService.logEvent('begin_checkout', {
        provider: 'koywe', direction: 'ON_RAMP', payment_type: method.code, value: Number(parsedAmount) || 0,
        currency: fiatCurrency, surface: 'chat',
      });
      if (!(await requestRampCriticalAuth({ amount: parsedAmount, assetUnit: USD_UNIT, assetNote: 'ahorro', actionLabel: 'compra' }))) {
        return;
      }
      const place = () => createRampOrder({
        variables: {
          direction: 'ON_RAMP', amount: String(parsedAmount), countryCode: availability?.countryCode, fiatCurrency,
          paymentMethodCode: method.code, authEmail, destination: 'cusd_plus',
        },
      });
      let response;
      try {
        // Each top-up spends its own Confío Face check.
        response = await withFaceStepUp('on_ramp', place, (r: any) => isFaceStepUpRequired(r?.data?.createRampOrder?.nextStep));
      } catch (faceError) {
        if (faceError instanceof FaceCheckError) return;
        throw faceError;
      }
      const result = (response as any)?.data?.createRampOrder;
      if (result?.nextStep === 'resume_order' && result.orderId) {
        // The earlier order as the server describes it (it may be of another method or rail).
        setPending({
          orderId: result.orderId, countryCode: result.countryCode || undefined, fiatCurrency: result.fiatCurrency || undefined,
          paymentMethodCode: result.paymentMethodCode || '', paymentMethodDisplay: result.paymentMethodDisplay || undefined,
          assetUnit: result.destination === 'cusd_plus' ? USD_UNIT : 'cUSD',
        });
        setError(getFriendlyRampError(result.error));
        return;
      }
      if (!result?.success || !result?.orderId) {
        setError(getFriendlyRampError(result?.error));
        return;
      }
      const display = result.paymentMethodDisplay || method.displayName;
      void AnalyticsService.logEvent('add_payment_info', {
        payment_type: method.code, provider: 'koywe', direction: 'ON_RAMP', value: Number(parsedAmount) || 0,
        currency: fiatCurrency, order_id: result.orderId, surface: 'chat',
      });
      // Kept with the message, so this order is what the conversation shows from now on.
      void attach({ variables: { messageId, orderId: result.orderId, paymentMethodCode: method.code, paymentMethodDisplay: display } })
        .catch(() => undefined);
      setOrder({
        orderId: result.orderId, countryCode: availability?.countryCode, paymentMethodCode: method.code,
        paymentMethodDisplay: display, amountIn: amount, amountOut: result.amountOut || undefined,
        fiatCurrency, assetUnit: USD_UNIT, nextActionUrl: result.nextActionUrl || undefined, paymentDetails: result.paymentDetails,
      });
    } catch (e: any) {
      // A lost answer may hide an order the server did create: the next try says so.
      setError(getFriendlyRampError(e?.message));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };

  if (order) {
    return <TopUpOrderCard order={order} onOpen={() => instructions(order)} />;
  }
  if (kept?.status === 'order' && kept.orderId) {
    // After a restart: the order this form created, as the server kept it.
    const again: TopUpOrder = {
      orderId: kept.orderId, countryCode: kept.countryCode || undefined, paymentMethodCode: kept.paymentMethodCode || '',
      paymentMethodDisplay: kept.paymentMethodDisplay || undefined, amountIn: kept.fiatAmount || undefined,
      fiatCurrency: kept.fiatCurrency || undefined, assetUnit: USD_UNIT,
    };
    return <TopUpOrderCard order={again} onOpen={() => instructions(again)} />;
  }
  if (kept?.status === 'expired' || kept?.status === 'gone') {
    return (
      <View style={[styles.card, styles.line]}>
        <Text style={styles.lineText}>
          {kept.status === 'expired' ? 'Este formulario venció. Pídeme la recarga de nuevo.' : 'Este formulario ya no está disponible.'}
        </Text>
      </View>
    );
  }
  if (!kept && keptError) {
    return (
      <View style={[styles.card, styles.line]}>
        <Text style={styles.lineText}>No pude comprobar esta recarga. Revisa tu conexión y vuelve a abrir el chat.</Text>
      </View>
    );
  }
  if (!kept || countryLoading || (koywe && availabilityLoading && !availability)) {
    return (
      <View style={[styles.card, styles.line]}>
        <ActivityIndicator size="small" color={EMERALD} />
        <Text style={styles.lineText}>Preparando…</Text>
        <BackupEnforcementModal />
      </View>
    );
  }
  if (!mapped || !method) {
    // Not this form's rail here (or it is paused): the top-up screen says how.
    return (
      <View style={styles.card}>
        <Text style={styles.title}>{title}</Text>
        <Text style={styles.body}>Desde aquí no puedo crear esta recarga. Ábrela en su pantalla.</Text>
        <Pressable onPress={() => go('Receive')} style={styles.submit} accessibilityRole="button" accessibilityLabel="Abrir Recargar">
          <Text style={styles.submitText}>Abrir Recargar</Text>
        </Pressable>
      </View>
    );
  }
  const shown = amountError || (quoteError && amountReady ? getFriendlyRampError(quoteError.message) : '');
  return (
    <View style={styles.card}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.fieldLabel}>{`Cuánto pagas (${fiatCurrency})`}</Text>
      <TextInput
        style={styles.input}
        value={amount}
        onChangeText={(value: string) => {
          setError('');
          setMissing(null);
          setAmount((prev) => sanitizeAmountInput(value, 2, undefined, prev));
        }}
        placeholder="0"
        placeholderTextColor="#6B7280"
        keyboardType="decimal-pad"
        editable={!busy}
        accessibilityLabel={`Cuánto pagas, en ${fiatCurrency}`}
      />
      {methods.length > 1 ? (
        <>
          <Text style={styles.fieldLabel}>Cómo pagas</Text>
          <View style={styles.methods}>
            {methods.map((m) => {
              const selected = m.code === method.code;
              return (
                <Pressable key={m.code} disabled={busy} onPress={() => { setMethodCode(m.code); setError(''); setMissing(null); }}
                  style={[styles.method, selected && styles.methodSelected]}
                  accessibilityRole="button" accessibilityState={{ selected }} accessibilityLabel={m.displayName}>
                  <Text style={[styles.methodText, selected && styles.methodTextSelected]} numberOfLines={1}>{m.displayName}</Text>
                </Pressable>
              );
            })}
          </View>
        </>
      ) : <Text style={styles.methodOnly}>{`Pagas con ${method.displayName}`}</Text>}
      {needsEmail ? (
        <>
          <Text style={styles.fieldLabel}>Tu correo (el banco te escribe ahí)</Text>
          <TextInput style={styles.input} value={email} onChangeText={(value: string) => { setEmail(value); setError(''); }}
            placeholder="nombre@correo.com" placeholderTextColor="#6B7280" keyboardType="email-address" autoCapitalize="none"
            autoCorrect={false} editable={!busy} accessibilityLabel="Tu correo" />
        </>
      ) : null}
      <View style={styles.quote} accessible>
        <Text style={styles.quoteLabel}>Recibes aprox.</Text>
        <Text style={styles.quoteValue}>
          {quote ? formatRampMoney(quote.amountOut, USD_UNIT) : quoteLoading && amountReady ? '…' : '—'}
        </Text>
      </View>
      {shown ? <Text style={styles.error}>{shown}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {missing ? (
        <>
          <Text style={styles.body}>{missing.text}</Text>
          <Pressable onPress={() => go(missing.screen, missing.params)} style={styles.second} accessibilityRole="button"
            accessibilityLabel={missing.button}>
            <Text style={styles.secondText}>{missing.button}</Text>
          </Pressable>
        </>
      ) : null}
      {needsAddress && !addressData?.myRampAddress?.isComplete ? (
        <AddressForm bare label="Falta tu dirección: el banco la pide para recargas y retiros."
          onSaved={() => setNeedsAddress(false)} onOpenScreen={() => go('RampAddress')} />
      ) : null}
      {pending ? (
        <Pressable onPress={() => instructions(pending)} style={styles.second} accessibilityRole="button"
          accessibilityLabel="Ver recarga pendiente">
          <Text style={styles.secondText}>Ver recarga pendiente</Text>
        </Pressable>
      ) : null}
      <Pressable onPress={() => void submit()} disabled={busy}
        style={({ pressed }) => [styles.submit, pressed && styles.submitPressed]}
        accessibilityRole="button" accessibilityState={{ busy }}
        accessibilityLabel={onLeaveBox ? 'Continuar en Recargar' : 'Crear recarga'}>
        {busy ? <ActivityIndicator size="small" color="#FFFFFF" />
          : <Text style={styles.submitText}>{onLeaveBox ? 'Continuar en Recargar' : 'Crear recarga'}</Text>}
      </Pressable>
      <BackupEnforcementModal />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 4, marginBottom: 4, maxWidth: 340, padding: 14, borderRadius: 16,
    borderWidth: 1, borderColor: '#A7F3D0', backgroundColor: '#FFFFFF',
  },
  line: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  lineText: { fontSize: 15, color: INK },
  title: { fontSize: 15, fontWeight: '700', color: INK },
  body: { fontSize: 14, lineHeight: 20, color: INK, marginTop: 10 },
  fieldLabel: { fontSize: 13, color: MUTED, marginTop: 12, marginBottom: 4 },
  input: {
    minHeight: 46, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16, color: INK,
    backgroundColor: '#F3F4F6',
  },
  methods: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  method: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: '#D1D5DB' },
  methodSelected: { borderColor: EMERALD, backgroundColor: '#ECFDF5' },
  methodText: { fontSize: 15, color: INK },
  methodTextSelected: { fontWeight: '700', color: EMERALD },
  methodOnly: { fontSize: 13, color: MUTED, marginTop: 8 },
  quote: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 14 },
  quoteLabel: { fontSize: 14, color: MUTED },
  quoteValue: { fontSize: 16, fontWeight: '700', color: INK },
  error: { fontSize: 13, lineHeight: 18, color: '#B91C1C', marginTop: 10 },
  submit: { marginTop: 14, height: 48, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: EMERALD },
  submitPressed: { backgroundColor: '#065F46' },
  submitText: { fontSize: 16, fontWeight: '700', color: '#FFFFFF' },
  second: { marginTop: 6, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  secondText: { fontSize: 15, fontWeight: '700', color: EMERALD },
});
