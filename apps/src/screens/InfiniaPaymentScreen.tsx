import React, {useRef, useState} from 'react';
import {
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ActivityIndicator,
} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import {useNavigation} from '@react-navigation/native';
import {useQuery} from '@apollo/client';
import {
  INFINIA_OPTIONS,
  INFINIA_HISTORY,
  INFINIA_DEPOSITS,
  createInfiniaJourney,
  attachInfiniaBridge,
  infiniaStage,
} from '../services/infiniaJourney';
import {
  BridgeTransfer,
  authorizePaymentBridge,
  bridgeRequestId,
  fetchPaymentBridge,
  journeyReturnBridgeRequestId,
  preparePaymentBridge,
} from '../services/paymentBridge';
import * as cobre from '../services/cobreJourney';
import {bridgeAmount} from './LocalAccountFundingScreen';

export default function InfiniaPaymentScreen({
  provider = 'infinia',
}: {
  provider?: 'infinia' | 'cobre';
}) {
  const isCobre = provider === 'cobre';
  const enabledKey = isCobre
    ? 'cobreJourneysEnabled'
    : 'infiniaJourneysEnabled';
  const historyKey = isCobre ? 'myCobreJourneys' : 'myInfiniaJourneys';
  const depositsKey = isCobre
    ? 'cobreJourneyDeposits'
    : 'infiniaJourneyDeposits';
  const stageLabel = isCobre ? cobre.cobreStage : infiniaStage;
  const navigation = useNavigation();
  const options = useQuery(isCobre ? cobre.COBRE_OPTIONS : INFINIA_OPTIONS, {
    fetchPolicy: 'network-only',
  });
  const [offset, setOffset] = useState(0);
  const [depositOffset, setDepositOffset] = useState(0);
  const history = useQuery(isCobre ? cobre.COBRE_HISTORY : INFINIA_HISTORY, {
    variables: {offset, limit: 20},
    fetchPolicy: 'network-only',
    pollInterval: 5000,
  });
  const [direction, setDirection] = useState('to_bank');
  const [local, setLocal] = useState(''),
    [destination, setDestination] = useState(''),
    [credit, setCredit] = useState('');
  const [amount, setAmount] = useState(''),
    [minimum, setMinimum] = useState('');
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const [review, setReview] = useState<BridgeTransfer | null>(null);
  const [returnJourney, setReturnJourney] = useState<any>(null);
  const working = useRef(false),
    requestId = useRef<string | null>(null);
  const accounts = (options.data?.myPaymentAccounts || []).filter(
    (a: any) =>
      a.provider === provider && String(a.status).toLowerCase() === 'active',
  );
  const crypto = accounts.find(
    (a: any) => a.asset === (isCobre ? 'USD_STABLE' : 'USDC_POL'),
  );
  const copco = accounts.find((a: any) => a.asset === 'COPCO');
  const fiat = accounts.find((a: any) => a.internalId === local);
  const instruction = crypto?.fundingInstructions?.find(
    (i: any) =>
      String(i.kind).toLowerCase() === 'crypto_address' &&
      String(i.status).toLowerCase() === 'active',
  );
  const deposits = useQuery(isCobre ? cobre.COBRE_DEPOSITS : INFINIA_DEPOSITS, {
    variables: {account: local, offset: depositOffset},
    skip: !local || direction !== 'to_wallet',
    fetchPolicy: 'network-only',
  });
  const rows = history.data?.[historyKey] || [];
  const run = async (fn: () => Promise<void>) => {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch {
      setError(
        'No pudimos confirmar el resultado. Actualiza el historial antes de volver a intentar.',
      );
    } finally {
      await history.refetch().catch(() => {});
      working.current = false;
      setBusy(false);
    }
  };
  const button = (label: string, fn: () => void, disabled = false) => (
    <TouchableOpacity
      accessibilityRole="button"
      disabled={disabled || busy}
      onPress={fn}
      style={[styles.button, (disabled || busy) && {opacity: 0.4}]}>
      <Text style={styles.buttonText}>{label}</Text>
    </TouchableOpacity>
  );
  const reset = () => {
    requestId.current = null;
    setReview(null);
  };
  const start = () =>
    run(async () => {
      requestId.current ||= bridgeRequestId();
      if (direction === 'to_bank' && !review) {
        setReview(
          await preparePaymentBridge(
            instruction.internalId,
            amount.replace(',', '.'),
            'to_provider',
            requestId.current,
          ),
        );
        return;
      }
      await (isCobre ? cobre.createCobreJourney : createInfiniaJourney)({
        direction,
        requestId: requestId.current,
        localAccountId: local,
        cryptoAccountId: crypto.internalId,
        ...(isCobre ? {copcoAccountId: copco?.internalId} : {}),
        minimumFxOutput: minimum.replace(',', '.'),
        bridgeId: review?.internalId,
        creditId: direction === 'to_wallet' ? credit : undefined,
        destinationId: direction === 'to_bank' ? destination : undefined,
      });
      if (review) await authorizePaymentBridge(review);
      setReview(null);
      requestId.current = null;
    });
  const resume = (j: any) =>
    run(async () => {
      if (j.bridgeId) {
        // Reload immutable server calls. Resuming never creates another journey.
        const bridge = await fetchPaymentBridge(j.bridgeId);
        if (bridge.status === 'prepared') {
          setReview(bridge);
          setReturnJourney(j);
        }
        return;
      }
      const account = accounts.find(
        (a: any) => a.internalId === j.cryptoAccountId,
      );
      const receiving = account?.fundingInstructions?.find(
        (i: any) =>
          String(i.kind).toLowerCase() === 'crypto_address' &&
          String(i.status).toLowerCase() === 'active',
      );
      if (!receiving || !j.walletArrivalUnits)
        throw new Error('Fondos pendientes');
      const bridge = await preparePaymentBridge(
        receiving.internalId,
        bridgeAmount(j.walletArrivalUnits, 6),
        'to_wallet',
        journeyReturnBridgeRequestId(provider, j.internalId),
      );
      await (isCobre ? cobre.attachCobreBridge : attachInfiniaBridge)(
        j.internalId,
        bridge.internalId,
      );
      setReview(bridge);
      setReturnJourney(j);
    });
  return (
    <SafeAreaView style={styles.root}>
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled">
        {button('Volver', () => navigation.goBack())}
        <Text style={styles.title}>
          {isCobre ? 'Pagos en Colombia' : 'Pagos con cuenta local'}
        </Text>
        {isCobre && (
          <Text>
            Los pagos a una llave Bre-B usan liquidación estándar. La conversión
            a pesos puede esperar una ventana de liquidación.
          </Text>
        )}
        {busy && <ActivityIndicator />}
        {!!error && <Text style={styles.error}>{error}</Text>}
        {returnJourney && review ? (
          <View style={styles.card}>
            <Text>
              {returnJourney.direction === 'to_bank' ? 'Dólares a enviar: ' : 'Dólares a traer a Confío: '}
              {bridgeAmount(review.amountUnits, review.sourceTokenId === 'BSC:USDT' ? 18 : 6)}
            </Text>
            <Text>
              Costo de conversión adicional: {bridgeAmount(review.feeUnits, 18)} dólares.
            </Text>
            {returnJourney.direction === 'to_bank' && (
              <>
                <Text>Destino del pago: {returnJourney.destinationSummary}</Text>
                <Text>
                  Mínimo aceptado en la conversión: {returnJourney.minimumFxOutput} {returnJourney.localAsset}.
                </Text>
                <Text>Los costos del proveedor pueden aplicarse al pago.</Text>
              </>
            )}
            <Text>
              {returnJourney.direction === 'to_bank' ? 'La cuenta local recibirá al menos ' : 'Recibirás en Confío al menos '}
              {bridgeAmount(
                review.amountOutMin,
                review.sourceTokenId === 'BSC:USDT' ? 6 : 18,
              )}{' '}
              dólares{returnJourney.direction === 'to_bank' ? ' antes de convertirlos.' : '.'}
            </Text>
            {button(
              'Confirmar envío pendiente',
              () =>
                run(async () => {
                  await authorizePaymentBridge(review);
                  setReview(null);
                  setReturnJourney(null);
                }),
              !options.data?.[enabledKey],
            )}
          </View>
        ) : (
          <>
            {button(
              direction === 'to_bank' ? 'Hacia un banco' : 'Hacia Confío',
              () => {
                reset();
                setDirection(direction === 'to_bank' ? 'to_wallet' : 'to_bank');
              },
            )}
            {accounts
              .filter((a: any) =>
                isCobre
                  ? a.asset === 'COP' && a.country === 'COL'
                  : a.country !== 'XXX',
              )
              .map((a: any) => (
                <View key={a.internalId}>
                  {button(
                    `${local === a.internalId ? '✓ ' : ''}${a.country} · ${a.asset}`,
                    () => {
                      reset();
                      setLocal(a.internalId);
                      setDepositOffset(0);
                      setDestination('');
                      setCredit('');
                    },
                  )}
                </View>
              ))}
            {direction === 'to_bank' ? (
              <>
                {(options.data?.myPayoutDestinations || [])
                  .filter(
                    (d: any) =>
                      d.provider.toLowerCase() === provider &&
                      d.asset === fiat?.asset &&
                      d.country === fiat?.country,
                  )
                  .map((d: any) => (
                    <View key={d.internalId}>
                      {button(
                        `${destination === d.internalId ? '✓ ' : ''}${d.label} · ${d.holderName}`,
                        () => {
                          reset();
                          setDestination(d.internalId);
                        },
                      )}
                    </View>
                  ))}
                <TextInput
                  style={styles.input}
                  placeholder="Dólares a enviar"
                  keyboardType="decimal-pad"
                  value={amount}
                  onChangeText={v => {
                    reset();
                    setAmount(v);
                  }}
                  editable={!busy}
                />
              </>
            ) : (
              <>
                {(deposits.data?.[depositsKey] || []).map((d: any) => (
                  <View key={d.internalId}>
                    {button(
                      `${credit === d.internalId ? '✓ ' : ''}${d.amount} ${d.asset} · ${new Date(d.occurredAt).toLocaleDateString()}`,
                      () => {
                        reset();
                        setCredit(d.internalId);
                      },
                    )}
                  </View>
                ))}
                {depositOffset > 0 &&
                  button('Depósitos más recientes', () => {
                    setDepositOffset(Math.max(0, depositOffset - 20));
                    setCredit('');
                  })}
                {deposits.data?.[depositsKey]?.length === 20 &&
                  button('Depósitos más antiguos', () => {
                    setDepositOffset(depositOffset + 20);
                    setCredit('');
                  })}
                <Text>
                  Se convertirá el depósito seleccionado y se enviará a tu
                  billetera. Abre la app cuando tus dólares estén listos para
                  confirmar el envío a Confío.
                </Text>
              </>
            )}
            <TextInput
              style={styles.input}
              placeholder={`Mínimo aceptado en la conversión (${direction === 'to_bank' ? fiat?.asset || 'moneda local' : 'dólares'})`}
              keyboardType="decimal-pad"
              value={minimum}
              onChangeText={v => {
                reset();
                setMinimum(v);
              }}
              editable={!busy}
            />
            <Text>
              Autorizas la conversión y el pago al destino elegido. El mínimo
              corresponde a la conversión; los costos del proveedor pueden
              aplicarse al pago.
            </Text>
            {review && (
              <Text>
                Envío: {bridgeAmount(review.amountUnits, 18)} dólares. Costo de
                conversión adicional: {bridgeAmount(review.feeUnits, 18)}{' '}
                dólares. La cuenta recibirá al menos{' '}
                {bridgeAmount(review.amountOutMin, 6)} dólares antes de
                convertirlos.
              </Text>
            )}
            {button(
              review || direction === 'to_wallet'
                ? 'Confirmar conversión y pago'
                : 'Revisar pago',
              start,
              !options.data?.[enabledKey] ||
                !crypto ||
                (isCobre && !copco) ||
                !local ||
                !/^\d+([.,]\d+)?$/.test(minimum) ||
                (direction === 'to_bank'
                  ? !instruction ||
                    !destination ||
                    !/^\d+([.,]\d+)?$/.test(amount)
                  : !credit),
            )}
          </>
        )}
        <Text style={styles.title}>Historial</Text>
        {button('Actualizar estado', () => {
          history.refetch().catch(() => setError('No se pudo actualizar'));
        })}
        {rows.map((j: any) => (
          <View key={j.internalId} style={styles.card}>
            <Text>{stageLabel(j.stage)}</Text>
            <Text selectable>{j.internalId}</Text>
            {[
              'awaiting_credit',
              'awaiting_wallet_authorization',
              'bridging',
            ].includes(j.stage) &&
              button('Revisar envío pendiente', () => resume(j))}
          </View>
        ))}
        {offset > 0 &&
          button('Más recientes', () => setOffset(Math.max(0, offset - 20)))}
        {rows.length === 20 &&
          button('Más antiguos', () => setOffset(offset + 20))}
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: '#f8fafc'},
  content: {padding: 20, gap: 14},
  title: {fontSize: 23, fontWeight: '700', color: '#111827'},
  card: {backgroundColor: '#fff', padding: 16, gap: 10, borderRadius: 12},
  button: {backgroundColor: '#065f46', padding: 14, borderRadius: 10},
  buttonText: {color: '#fff', textAlign: 'center', fontWeight: '600'},
  input: {
    padding: 14,
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#9ca3af',
    borderRadius: 10,
    color: '#111827',
  },
  error: {color: '#b91c1c'},
});
