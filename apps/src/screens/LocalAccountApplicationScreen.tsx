import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, SafeAreaView, ScrollView, Share, StatusBar, Text, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Clipboard from '@react-native-clipboard/clipboard';
import { useFocusEffect, useNavigation, usePreventRemove, useRoute } from '@react-navigation/native';
import { useQuery } from '@apollo/client';

import { GET_MY_RAMP_ADDRESS } from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';
import { colors } from '../config/theme';
import { LoadingOverlay } from '../components/LoadingOverlay';
import { countryFlag, countryName } from '../config/localRails';
import { useBrebLocationScope } from '../components/breb/BrebLocationGate';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { RampStepHeader } from '../components/ramps/RampStepHeader';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
import { useLocalPaymentAccounts } from '../hooks/useLocalPaymentAccounts';
import {
  applyCobreBreb, brebLocationPassRemainingMs, brebLocationPassValid, onBrebLocationPassChange,
} from '../services/brebLocation';
import {
  activateLocalMoney,
  currencyName,
  LOCAL_MONEY_METHODS,
  LocalMethod,
  LocalPairStatus,
  payLocalActivation,
  quoteLocalActivation,
} from '../services/localMoney';

// One application screen for every country's local account. It replaces the
// fee alerts: what you get, what you still need, what it costs (quoted by the
// server, never hardcoded) and one action. Bre-B (either provider) is usable
// from anywhere except Venezuela, so its applications add a location step to
// the requirements.

const RAIL: Record<string, string> = { CO: 'Bre-B', MX: 'SPEI', BR: 'Pix', AR: 'transferencia' };

// "Tu propia/tu propio", never "a tu nombre" (copy rule on RECEIVE_RAILS).
const RECEIVE_COPY: Record<string, { title: string; item: string }> = {
  co_breb_receive: { title: 'Solicita tu llave Bre-B', item: 'Tu propia llave Bre-B' },
  cobre_co_breb_receive: { title: 'Solicita tu llave Bre-B', item: 'Tu propia llave Bre-B' },
  mx_clabe_receive: { title: 'Solicita tu CLABE', item: 'Tu propia CLABE' },
  br_pix_receive: { title: 'Solicita tu cuenta Pix', item: 'Tus datos Pix para recibir' },
  ar_cvu_receive: { title: 'Solicita tu CVU', item: 'Tu propio CVU' },
};

type Row = [icon: string, title: string, body: string];
type Requirement = {
  key: string;
  ok: boolean;
  title: string;
  body: string;
  action?: { label: string; onPress: () => void };
};

const isBrebMethod = (methodId: string) => methodId.startsWith('co_') || methodId.startsWith('cobre_co_');
const sameAmount = (a: string, b: string) => Number.isFinite(Number(a)) && Number(a) === Number(b);

export default function LocalAccountApplicationScreen() {
  const methodId: string = (useRoute<any>().params?.methodId as string) || '';
  const locationScope = useBrebLocationScope();
  // Issued keys, displayed fees and in-flight responses belong to this
  // account and method only, including when navigation reuses the screen.
  return <Application key={`${locationScope}:${methodId}`} methodId={methodId} />;
}

function Rows({ rows }: { rows: Row[] }) {
  return (
    <>
      {rows.map(([icon, title, body]) => (
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
  );
}

function Application({ methodId }: { methodId: string }) {
  const navigation = useNavigation<any>();
  const direction = methodId.endsWith('_receive') ? 'receive' : 'send';
  const isCobre = methodId.startsWith('cobre_');
  const isBreb = isBrebMethod(methodId);

  const methodsQuery = useQuery(LOCAL_MONEY_METHODS, {
    variables: { direction }, fetchPolicy: 'cache-and-network', errorPolicy: 'all',
  });
  const method: LocalMethod | undefined = (methodsQuery.data?.localMoneyMethods || [])
    .find((row: LocalMethod) => row.id === methodId);
  const { activeAccount } = useAccount();
  const addressQuery = useQuery(GET_MY_RAMP_ADDRESS, { fetchPolicy: 'cache-and-network', errorPolicy: 'all' });
  const addressComplete = activeAccount?.type === 'business' || Boolean(addressQuery.data?.myRampAddress?.isComplete);
  const { accounts, refetch: refetchAccounts } = useLocalPaymentAccounts();
  const locationScope = useBrebLocationScope();
  const [locationOk, setLocationOk] = useState(() => brebLocationPassValid(locationScope));

  const country = method?.country || (isBreb ? 'CO' : '');
  const flag = countryFlag(country);
  const place = countryName(country);
  const currency = method ? currencyName(method.asset) : 'moneda local';
  const rail = RAIL[country] || 'transferencia';
  const copy = direction === 'receive'
    ? (RECEIVE_COPY[methodId] || { title: 'Solicita tu cuenta local', item: 'Tu propia cuenta local' })
    : { title: `Abre tu cuenta en ${place}`, item: `Tu cuenta en ${currency}` };
  const status = (method?.accountStatus || 'none') as LocalPairStatus;
  const identityOk = method?.status === 'live';

  const [issuedKey, setIssuedKey] = useState('');
  const existingKey = isCobre
    ? accounts.filter(row => row.provider === 'cobre').flatMap(row => row.fundingInstructions)
      .find(row => row.kind === 'breb_key' && row.status === 'active' && row.displayValue)?.displayValue || ''
    : '';
  // A key shows only while the location pass lasts: the server withholds it
  // without one, and a key issued on this screen expires with its pass too.
  const hasKey = Boolean(issuedKey) || accounts.some(row => row.provider === 'cobre'
    && row.fundingInstructions.some(item => item.kind === 'breb_key' && item.status === 'active'));
  const brebKey = locationOk ? issuedKey || existingKey : '';
  const hiddenKey = isCobre && !brebKey && hasKey;
  const [copied, setCopied] = useState(false);

  const [fee, setFee] = useState<{ amount: string | null } | null>(null);
  const [feeError, setFeeError] = useState(false);
  const [feeAttempt, setFeeAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [returnToAccount, setReturnToAccount] = useState(false);
  const openingInFlight = useRef(false);
  const [error, setError] = useState('');
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  usePreventRemove(busy, () => {});

  // A document verified or an address completed elsewhere shows up on return.
  const refresh = useRef(() => {});
  refresh.current = () => {
    methodsQuery.refetch().catch(() => {});
    addressQuery.refetch().catch(() => {});
    refetchAccounts().catch(() => {});
    setLocationOk(brebLocationPassValid(locationScope));
  };
  useFocusEffect(useCallback(() => { refresh.current(); }, []));
  // A pass granted, renewed or forgotten anywhere (e.g. a refused conversion)
  // shows or hides the key at once.
  useEffect(() => onBrebLocationPassChange(() => setLocationOk(brebLocationPassValid(locationScope))),
    [locationScope]);
  // The pass lapsing hides the key again, even with the screen open.
  useEffect(() => {
    if (!locationOk) return undefined;
    let timer: ReturnType<typeof setTimeout>;
    const check = () => {
      const valid = brebLocationPassValid(locationScope);
      setLocationOk(valid);
      // Another verification (including account creation) may renew a pass
      // without changing this boolean. Always arm its current deadline again.
      if (valid) timer = setTimeout(check, Math.max(brebLocationPassRemainingMs(locationScope), 0) + 1000);
    };
    timer = setTimeout(check, Math.max(brebLocationPassRemainingMs(locationScope), 0) + 1000);
    return () => clearTimeout(timer);
  }, [locationOk, locationScope]);

  // The fee is the server's consent quote: nothing is created or charged.
  const canQuote = !isCobre && status === 'none' && identityOk && addressComplete && (!isBreb || locationOk);
  useEffect(() => {
    if (!canQuote || fee) return undefined;
    let cancelled = false;
    setFeeError(false);
    quoteLocalActivation(methodId)
      .then(amount => {
        if (cancelled) return;
        if (amount === null) {
          // The opening already started (another device or session): show its
          // real state, and offer a retry if the list still says otherwise.
          methodsQuery.refetch().catch(() => undefined);
          setFeeError(true);
          return;
        }
        setFee({ amount });
      })
      .catch(() => { if (!cancelled) setFeeError(true); });
    return () => { cancelled = true; };
  }, [canQuote, fee, feeAttempt, methodId]);

  const goToAccount = () => {
    if (navigation.canGoBack()) navigation.goBack();
    else navigation.replace(direction === 'receive' ? 'LocalReceive' : 'LocalSend', { methodId });
  };
  // Navigate only after the render that releases native-stack removal.
  useEffect(() => {
    if (returnToAccount && !busy) {
      setReturnToAccount(false);
      goToAccount();
    }
  }, [returnToAccount, busy, navigation, direction, methodId]);

  // Opening: the buttons on this screen are the consent and the payment
  // approval, so the confirmation alerts are replaced by what it shows.
  // Approval covers exactly the amount this screen shows. A server amount that
  // differs, or one not shown yet (returning to pay), is displayed first and
  // needs another tap.
  const shownFee = fee?.amount ?? null;
  const approves = (amount: string) => {
    if (!alive.current) return false;
    if (shownFee !== null && sameAmount(shownFee, amount)) return true;
    if (alive.current) {
      setFee({ amount });
      if (shownFee !== null) setError(`El costo de apertura ahora es US$${amount}. Revísalo y confirma de nuevo.`);
    }
    return false;
  };
  const runOpening = async (payNow: boolean) => {
    if (openingInFlight.current) return;
    openingInFlight.current = true;
    setBusy(true);
    setError('');
    const prompts = {
      confirmFee: async (amount: string) => approves(amount),
      confirmPayment: async (amount: string) => payNow && approves(amount),
    };
    try {
      if (!await payLocalActivation(methodId, prompts) || !alive.current) return;
      for (let attempt = 0; attempt < 10; attempt += 1) {
        const next = await activateLocalMoney(methodId);
        if (!alive.current) return;
        if (next === 'active') {
          // Read-only refreshes must not hold a completed payment behind the
          // modal. The destination screen also refreshes when it gains focus.
          void Promise.allSettled([methodsQuery.refetch(), refetchAccounts()]);
          openingInFlight.current = false;
          if (alive.current) setReturnToAccount(true);
          return;
        }
        if (next === 'awaiting_payment') {
          if (!payNow || !await payLocalActivation(methodId, prompts) || !alive.current) return;
          continue;
        }
        if (next !== 'provisioning') throw new Error('No pudimos abrir tu cuenta. Escríbenos a soporte.');
        await new Promise(resolve => setTimeout(resolve, 5000));
        if (!alive.current) return;
      }
      setError('La apertura está tardando más de lo habitual. Puedes salir y tocar Revisar la apertura para continuar.');
    } catch (failure: any) {
      if (alive.current) setError(failure?.message || 'No pudimos abrir tu cuenta. Intenta de nuevo.');
    } finally {
      openingInFlight.current = false;
      if (alive.current) setBusy(false);
      void methodsQuery.refetch().catch(() => undefined);
    }
  };

  const applyCobre = async () => {
    if (openingInFlight.current) return;
    openingInFlight.current = true;
    setBusy(true);
    setError('');
    try {
      const value = await applyCobreBreb(locationScope);
      if (alive.current) {
        setIssuedKey(value);
        setLocationOk(brebLocationPassValid(locationScope));
      }
    } catch (failure: any) {
      if (alive.current) setError(failure?.message || 'Tu llave aún no está disponible. Vuelve a intentarlo.');
    } finally {
      openingInFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };

  const copyKey = () => {
    Clipboard.setString(brebKey);
    setCopied(true);
  };

  const hero = (
    <RampReveal delay={0}>
      <RampHero
        eyebrow={`${flag ? `${flag} ` : ''}${place || 'Cuenta local'}`}
        title={brebKey || hiddenKey ? 'Tu llave Bre-B' : copy.title}
        subtitle={direction === 'receive'
          ? `${copy.item} para recibir ${currency} por ${rail}, siempre la misma.`
          : `Para enviar ${currency} por ${rail} a cualquier banco o billetera.`}
        onBack={() => navigation.goBack()}
      />
    </RampReveal>
  );

  if (hiddenKey) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
        <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
          {hero}
          <View style={styles.emptyStateCard}>
            <View style={styles.emptyStateIconWrap}>
              <Icon name="map-pin" size={22} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyStateTitle}>Confirma tu ubicación</Text>
            <Text style={styles.emptyStateText}>Para ver tu llave Bre-B confirmamos que está disponible donde estás.</Text>
          </View>
          <RampActionBar
            primaryLabel="Confirmar ubicación"
            onPrimaryPress={() => navigation.navigate('BrebLocationCheck')}
            primaryIconName="map-pin"
          />
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ─── Cobre: the key, once issued ───
  if (brebKey) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
        <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
          {hero}
          <RampReveal delay={80}>
            <View style={styles.section}>
              <RampStepHeader number={1} title="Compártela para que te paguen" meta={`${flag} Colombia · COP`}
                accentColor={colors.primaryDark} accentBackground={colors.primaryLight} titleColor={colors.dark}
                metaColor={colors.textSecondary} />
              <View style={styles.inputCard}>
                <Text style={styles.inputLabel}>Tu llave Bre-B</Text>
                <Text selectable style={styles.detailValue}>{brebKey}</Text>
                <Text style={styles.detailMeta}>
                  Te pueden pagar desde cualquier banco o billetera de Colombia, normalmente en minutos.
                </Text>
                <View style={styles.buttonRow}>
                  <TouchableOpacity style={styles.smallGhost} onPress={copyKey} accessibilityRole="button">
                    <Icon name={copied ? 'check' : 'copy'} size={16} color={colors.successText} />
                    <Text style={styles.smallGhostText}>{copied ? 'Copiada' : 'Copiar'}</Text>
                  </TouchableOpacity>
                  <TouchableOpacity style={styles.smallPrimary} accessibilityRole="button"
                    onPress={() => { Share.share({ message: `Mi llave Bre-B: ${brebKey}` }).catch(() => {}); }}>
                    <Icon name="share-2" size={16} color={colors.white} />
                    <Text style={styles.smallPrimaryText}>Compartir</Text>
                  </TouchableOpacity>
                </View>
              </View>
            </View>
          </RampReveal>
          <RampActionBar
            primaryLabel="Convertir mis pesos a dólares"
            onPrimaryPress={() => navigation.navigate('CobrePayment', { direction: 'to_wallet' })}
            primaryIconName="repeat"
          />
        </ScrollView>
      </SafeAreaView>
    );
  }

  const benefits: Row[] = direction === 'receive'
    ? [
      ['repeat', `${copy.item}, siempre la misma`, 'Compártela las veces que quieras.'],
      ['zap', `Te pagan por ${rail}`, 'Desde cualquier banco o billetera, normalmente en minutos.'],
      ['dollar-sign', 'Tú decides cuándo convertir', `Tus ${currency} esperan hasta que los pases a dólares.`],
    ]
    : [
      ['send', `Envía por ${rail}`, `A cualquier banco o billetera de ${place}.`],
      ['repeat', 'Se abre una sola vez', 'Queda lista para tus próximos envíos.'],
      ['dollar-sign', 'Desde tus dólares', `Conviertes a ${currency} solo cuando envías.`],
    ];

  const requirements: Requirement[] = [
    identityOk
      ? { key: 'identity', ok: true, title: 'Identidad verificada', body: 'Tu documento cumple para esta cuenta.' }
      : method?.status === 'needs_document'
        ? {
          key: 'identity', ok: false, title: 'Verifica otro documento',
          body: 'Esta cuenta pide un documento distinto al que ya verificaste.',
          action: {
            label: 'Verificar',
            onPress: () => navigation.navigate('AdditionalDocument', {
              idCountry: method.documentCountry, documentTypes: method.documentTypes,
              reason: `Para abrir tu cuenta en ${place} necesitamos un documento distinto al que ya verificaste.`,
            }),
          },
        }
        : {
          key: 'identity', ok: false, title: 'Verifica tu identidad',
          body: 'Necesitamos confirmar quién eres antes de abrirla.',
          action: { label: 'Verificar', onPress: () => navigation.navigate('Verification') },
        },
    addressComplete
      ? { key: 'address', ok: true, title: 'Dirección completa', body: 'La misma que usas para Recargar y Retirar.' }
      : {
        key: 'address', ok: false, title: 'Completa tu dirección',
        body: 'El procesador de pagos la pide para abrir la cuenta.',
        action: { label: 'Completar', onPress: () => navigation.navigate('RampAddress') },
      },
    ...(isBreb ? [locationOk
      ? { key: 'location', ok: true, title: 'Ubicación confirmada', body: 'Bre-B está disponible donde estás.' }
      : {
        key: 'location', ok: false, title: 'Confirma tu ubicación',
        body: 'Confirmamos que Bre-B está disponible en tu ubicación.',
        action: { label: 'Confirmar', onPress: () => navigation.navigate('BrebLocationCheck') },
      }] : []),
  ];
  const ready = requirements.every(row => row.ok);

  const costRows: Row[] = isCobre
    ? [
      ['gift', 'Sin costo de apertura', 'Solicitar tu llave es gratis.'],
      ['percent', 'Pagas solo al convertir', 'Antes de cada conversión ves el costo exacto.'],
    ]
    : status === 'awaiting_payment'
      ? [fee?.amount
        ? ['credit-card', `Apertura: US$${fee.amount}`, 'Tu cuenta está lista. Paga con tu saldo Confío para ver tus datos y usarla.']
        : ['credit-card', 'Tu cuenta está lista', 'Toca abajo para ver el monto antes de pagar.']]
      : fee?.amount
        ? [
          ['credit-card', `Apertura: US$${fee.amount}`, 'Un solo pago, con tu saldo Confío.'],
          ['check-circle', 'Pagas cuando esté lista', 'Si no se puede abrir, no se cobra nada.'],
        ]
        : [];

  const unavailable = method?.status === 'unavailable';
  const broken = ['rejected', 'failed', 'suspended', 'closed'].includes(status);
  // The list could not load (e.g. offline on first open): a retry, never "not available".
  const loadFailed = !method && !methodsQuery.loading && Boolean(methodsQuery.error);
  const opening = status === 'provisioning' || (busy && !isCobre);

  let action: { label: string; onPress: () => void; disabled?: boolean; icon?: string };
  if (loadFailed) {
    action = { label: 'Intentar de nuevo', onPress: () => { methodsQuery.refetch().catch(() => {}); }, icon: 'refresh-cw' };
  } else if (unavailable || broken) {
    action = { label: 'Escribir a soporte', onPress: () => navigation.navigate('HomeMessages', { initialChannelId: 'soporte' }) };
  } else if (isCobre) {
    action = { label: 'Solicitar mi llave Bre-B', onPress: applyCobre, disabled: !ready || busy, icon: 'key' };
  } else if (status === 'active') {
    action = { label: 'Ir a mi cuenta', onPress: goToAccount, icon: 'chevron-right' };
  } else if (status === 'awaiting_payment') {
    action = {
      label: fee?.amount ? `Pagar US$${fee.amount} y activar` : 'Ver el monto a pagar',
      onPress: () => runOpening(true), disabled: busy, icon: 'check',
    };
  } else if (status === 'provisioning') {
    action = { label: 'Revisar la apertura', onPress: () => runOpening(false), disabled: busy };
  } else {
    action = {
      label: fee?.amount ? `Aceptar y solicitar · US$${fee.amount}` : 'Solicitar cuenta',
      onPress: () => runOpening(false),
      disabled: !ready || !fee?.amount || busy,
      icon: 'check',
    };
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {hero}

        {!method && methodsQuery.loading ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} />
            <Text style={styles.loadingText}>Cargando…</Text>
          </View>
        ) : loadFailed ? (
          <View style={styles.emptyStateCard}>
            <View style={styles.emptyStateIconWrap}>
              <Icon name="wifi-off" size={22} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyStateTitle}>No pudimos cargar esta cuenta</Text>
            <Text style={styles.emptyStateText}>Revisa tu conexión e intenta de nuevo.</Text>
          </View>
        ) : !method || unavailable ? (
          <View style={styles.emptyStateCard}>
            <View style={styles.emptyStateIconWrap}>
              <Icon name="map-pin" size={22} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyStateTitle}>No disponible por ahora</Text>
            <Text style={styles.emptyStateText}>
              {method?.reason === 'location_restricted'
                ? 'Esta cuenta no se puede solicitar desde tu ubicación actual.'
                : 'Esta cuenta aún no está disponible para ti. Si crees que es un error, escríbenos.'}
            </Text>
          </View>
        ) : (
          <>
            <RampReveal delay={80}>
              <View style={styles.section}>
                <RampStepHeader number={1} title="Qué obtienes" meta={`${flag ? `${flag} ` : ''}${place} · ${method.asset}`}
                  accentColor={colors.primaryDark} accentBackground={colors.primaryLight} titleColor={colors.dark}
                  metaColor={colors.textSecondary} />
                <View style={styles.inputCard}>
                  <Rows rows={benefits} />
                </View>
              </View>
            </RampReveal>

            <RampReveal delay={150}>
              <View style={styles.section}>
                <RampStepHeader number={2} title="Requisitos" meta={ready ? 'Todo listo' : 'Te falta un paso'}
                  accentColor={colors.primaryDark} accentBackground={colors.primaryLight} titleColor={colors.dark}
                  metaColor={colors.textSecondary} />
                <View style={styles.inputCard}>
                  {requirements.map(row => (
                    <View key={row.key} style={[styles.reviewRow, { alignItems: 'center' }]}>
                      <View style={[styles.methodIcon, !row.ok && { backgroundColor: colors.warning.background }]}>
                        <Icon name={row.ok ? 'check' : 'alert-circle'} size={18}
                          color={row.ok ? colors.primary : colors.warning.icon} />
                      </View>
                      <View style={styles.methodCopy}>
                        <Text style={styles.methodTitle}>{row.title}</Text>
                        <Text style={styles.methodText}>{row.body}</Text>
                      </View>
                      {row.action ? (
                        <TouchableOpacity style={styles.addButton} onPress={row.action.onPress} accessibilityRole="button">
                          <Text style={styles.addButtonText}>{row.action.label}</Text>
                        </TouchableOpacity>
                      ) : null}
                    </View>
                  ))}
                </View>
              </View>
            </RampReveal>

            <RampReveal delay={220}>
              <View style={styles.section}>
                <RampStepHeader number={3} title="Costo"
                  accentColor={colors.primaryDark} accentBackground={colors.primaryLight} titleColor={colors.dark} />
                <View style={styles.inputCard}>
                  {opening ? (
                    <View style={styles.emptyQuote}>
                      <ActivityIndicator color={colors.primary} />
                      <Text style={styles.emptyText}>
                        {busy ? 'Estamos abriendo tu cuenta. Mantén la aplicación abierta mientras terminamos.'
                          : 'La apertura sigue en proceso. Toca Revisar la apertura para consultar su estado.'}
                      </Text>
                    </View>
                  ) : status === 'active' ? (
                    <Text style={styles.emptyText}>Tu cuenta está activa. La apertura ya está pagada.</Text>
                  ) : broken ? (
                    <Text style={styles.errorText}>No pudimos abrir tu cuenta. Escríbenos a soporte y lo revisamos.</Text>
                  ) : costRows.length ? (
                    <Rows rows={costRows} />
                  ) : feeError ? (
                    <TouchableOpacity onPress={() => { setFee(null); setFeeAttempt(value => value + 1); }}>
                      <Text style={styles.warningLink}>No pudimos consultar el costo. Intentar de nuevo</Text>
                    </TouchableOpacity>
                  ) : !ready ? (
                    <Text style={styles.emptyText}>Te mostramos el costo cuando completes los requisitos.</Text>
                  ) : (
                    <ActivityIndicator color={colors.primary} />
                  )}
                  {error ? <Text style={styles.errorText}>{error}</Text> : null}
                </View>
              </View>
            </RampReveal>
          </>
        )}

        <RampActionBar
          primaryLabel={action.label}
          onPrimaryPress={action.onPress}
          primaryDisabled={action.disabled}
          primaryLoading={busy}
          primaryIconName={action.icon}
        />
      </ScrollView>
      <LoadingOverlay visible={busy} message={isCobre ? 'Solicitando tu llave Bre-B…' : 'Preparando y activando tu cuenta…'} />
    </SafeAreaView>
  );
}
