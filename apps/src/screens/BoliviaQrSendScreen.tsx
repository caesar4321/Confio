import React, {useCallback, useEffect, useRef, useState} from 'react';
import { ActivityIndicator, SafeAreaView, ScrollView, StyleSheet, TouchableOpacity, View } from 'react-native';
import { Text, TextInput } from '../components/common/AppText';
import {useApolloClient} from '@apollo/client';
import {useIsFocused} from '@react-navigation/native';
import {PaymentQrScannerModal} from '../components/PaymentQrScannerModal';
import {colors} from '../config/theme';
import {requestRampCriticalAuth} from '../utils/rampFlow';
import {STEREUM_QR_AVAILABILITY, DECODE_STEREUM_QR, PAY_STEREUM_QR, STEREUM_QR_PAYMENT,
  QrPreview, QrPayment, qrRequestId, readPendingQr, savePendingQr, clearPendingQr, validBobAmount} from '../services/stereumQr';

export default function BoliviaQrSendScreen({accountId, initialQr, onBack}: {accountId: string; initialQr?: string; onBack: () => void}) {
  const client = useApolloClient();
  const focused = useIsFocused();
  const active = useRef(true);
  const isFocused = useRef(focused); isFocused.current = focused;
  const run = useRef(0);
  const busy = useRef(false);
  const [loading, setLoading] = useState(true);
  const [availability, setAvailability] = useState<{enabled: boolean; canPay: boolean} | null>(null);
  const [scanner, setScanner] = useState(false);
  const [preview, setPreview] = useState<QrPreview | null>(null);
  const [amount, setAmount] = useState('');
  const [review, setReview] = useState(false);
  const [payment, setPayment] = useState<QrPayment | null>(null);
  const [finalCleared, setFinalCleared] = useState(false);
  const [error, setError] = useState('');
  const handedOff = useRef(false);
  useEffect(() => {handedOff.current = false;}, [initialQr]);
  useEffect(() => {active.current = true; return () => {active.current = false; run.current += 1;};}, []);

  const boot = useCallback(async () => {
    setLoading(true); setError('');
    try {
      // Storage errors fail closed; absence and an unreadable journal differ.
      const [saved, response] = await Promise.all([readPendingQr(accountId),
        client.query({query: STEREUM_QR_AVAILABILITY, fetchPolicy: 'network-only'})]);
      if (!active.current) return;
      const capability = response.data?.stereumQrAvailability;
      if (!capability) throw new Error('No pudimos consultar la disponibilidad.');
      setAvailability(capability);
      const pending = saved || capability.pendingRequestId;
      if (pending) setPayment({requestId: pending, status: 'unknown'});
    } catch {
      if (active.current) {setAvailability(null); setError('No pudimos recuperar el estado de tus pagos. Intenta de nuevo.');}
    } finally {if (active.current) setLoading(false);}
  }, [accountId, client]);
  useEffect(() => {void boot();}, [boot]);

  const decode = useCallback(async (payload: string) => {
    if (busy.current || payment || !availability?.enabled) return;
    busy.current = true;
    const attempt = ++run.current;
    setLoading(true); setError(''); setPreview(null); setReview(false); setAmount('');
    try {
      const response = await client.mutate({mutation: DECODE_STEREUM_QR,
        variables: {requestId: qrRequestId(), payload}, fetchPolicy: 'no-cache'});
      if (!active.current || !isFocused.current || attempt !== run.current) return;
      const recipient: QrPreview = response.data?.decodeStereumQr;
      if (!recipient) throw new Error('QR no válido');
      setPreview(recipient); setAmount(recipient.fixedAmount ? recipient.amount : '');
    } catch {
      if (active.current && attempt === run.current) setError('No pudimos leer este QR. Revisa que sea un QR bancario vigente de Bolivia.');
    } finally {
      if (active.current && attempt === run.current) {busy.current = false; setLoading(false);}
    }
  }, [availability?.enabled, client, payment]);
  useEffect(() => {
    if (!loading && availability?.enabled && initialQr && !handedOff.current && !payment && focused) {
      handedOff.current = true; void decode(initialQr);
    }
  }, [availability?.enabled, decode, focused, initialQr, loading, payment]);

  const acceptPayment = async (result: QrPayment) => {
    if (!active.current) return;
    setPayment(result);
    if (['succeeded', 'failed'].includes(result.status)) {
      await clearPendingQr(accountId);
      if (active.current) setFinalCleared(true);
    }
  };
  const checkStatus = async () => {
    if (!payment || busy.current) return;
    busy.current = true; setLoading(true); setError('');
    try {
      const response = await client.query({query: STEREUM_QR_PAYMENT,
        variables: {requestId: payment.requestId}, fetchPolicy: 'network-only'});
      if (response.data?.stereumQrPayment) await acceptPayment(response.data.stereumQrPayment);
      else if (active.current) setError('Aún no encontramos el resultado. No repitas el pago; consulta de nuevo o contacta soporte con la referencia.');
    } catch {if (active.current) setError('No pudimos actualizar el estado. No repitas el pago.');}
    finally {busy.current = false; if (active.current) setLoading(false);}
  };
  const submit = async () => {
    if (busy.current || payment || !review || !preview || !availability?.canPay || !validBobAmount(amount)) return;
    busy.current = true; setLoading(true); setError('');
    let sent = false;
    try {
      const allowed = await requestRampCriticalAuth({amount: Number(amount.replace(',', '.')), assetUnit: 'BOB', actionLabel: 'envío'});
      if (!allowed || !active.current || !isFocused.current) return;
      const id = qrRequestId();
      await savePendingQr(accountId, id); // Must succeed before sending anything.
      if (!active.current || !isFocused.current) {
        await clearPendingQr(accountId); // Definitely not submitted.
        return;
      }
      setPayment({requestId: id, status: 'unknown'});
      sent = true;
      const response = await client.mutate({mutation: PAY_STEREUM_QR,
        variables: {requestId: id, decodeRequestId: preview.requestId, amount: amount.replace(',', '.')}, fetchPolicy: 'no-cache'});
      if (!response.data?.payStereumQr) throw new Error('Respuesta incompleta');
      await acceptPayment(response.data.payStereumQr);
    } catch {if (active.current) setError(sent
      ? 'No pudimos confirmar el resultado. Consulta el estado antes de intentar otro pago.'
      : 'No pudimos preparar la solicitud. No se envió el pago. Intenta de nuevo.');}
    finally {busy.current = false; if (active.current) setLoading(false);}
  };
  const button = (title: string, onPress: () => void, disabled = false) => (
    <TouchableOpacity accessibilityRole="button" accessibilityState={{disabled}} disabled={disabled}
      onPress={onPress} style={[styles.button, disabled && styles.disabled]}><Text style={styles.buttonText}>{title}</Text></TouchableOpacity>
  );
  return <SafeAreaView style={styles.root}><ScrollView contentContainerStyle={styles.content}>
    {button('Volver', onBack)}
    <Text style={styles.title}>Paga con QR en Bolivia</Text>
    <Text style={styles.notice}>Modo de prueba. Se usa la cuenta de prueba; no se descuenta de tu saldo Confío.</Text>
    {loading && <ActivityIndicator accessibilityLabel="Procesando QR" />}
    {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    {payment ? <View style={styles.card}>
      <Text style={styles.heading}>{payment.status === 'succeeded' ? 'Pago de prueba completado'
        : payment.status === 'failed' ? 'Pago de prueba rechazado' : 'Pago de prueba en revisión'}</Text>
      <Text selectable>Referencia: {payment.requestId}</Text>
      {!['succeeded', 'failed'].includes(payment.status) && <Text>No repitas el pago mientras verificamos el resultado.</Text>}
      {button('Consultar estado', () => {void checkStatus();}, loading)}
      {finalCleared && button('Escanear otro QR', () => {setPayment(null); setPreview(null); setReview(false); setFinalCleared(false); setError(''); setAmount(''); setScanner(true);})}
    </View> : !availability?.enabled ? <View>
      {!loading && <Text>QR Bolivia no está habilitado para esta cuenta.</Text>}
      {button('Volver a consultar', () => {void boot();}, loading)}
    </View> : <>
      {!review && button(preview ? 'Cambiar QR' : 'Escanear o importar QR', () => setScanner(true), loading)}
      {preview && <View style={styles.card}>
        <Text style={styles.heading}>{review ? 'Revisa antes de confirmar' : 'Datos del QR'}</Text>
        <Text style={styles.recipient}>{preview.recipientName}</Text>
        {preview.bankName ? <Text>{preview.bankName}</Text> : null}
        <Text>Cuenta terminada en {preview.accountLast4}</Text>
        <Text>Vigente hasta {preview.expiresOn}</Text>
        <Text style={styles.note}>Estos datos vienen del QR. No constituyen una verificación independiente del titular.</Text>
        <Text style={styles.heading}>Monto en bolivianos (BOB)</Text>
        {review || preview.fixedAmount ? <Text style={styles.recipient}>{amount} BOB</Text> :
          <TextInput accessibilityLabel="Monto en bolivianos" value={amount} keyboardType="decimal-pad" editable={!loading}
            onChangeText={setAmount} placeholder="0,00" style={styles.input} />}
        {preview.fixedAmount && <Text>El QR tiene un monto fijo.</Text>}
        {!availability.canPay && <Text style={styles.note}>Puedes revisar el QR. Para el pago de prueba faltan configuración o verificación de identidad.</Text>}
        {review ? <>
          {button('Confirmar pago de prueba', () => {void submit();}, loading || !availability.canPay || !validBobAmount(amount))}
          {button('Editar monto', () => setReview(false), loading)}
        </> : button('Revisar pago', () => setReview(true), loading || !availability.canPay || !validBobAmount(amount))}
      </View>}
    </>}
  </ScrollView>
  <PaymentQrScannerModal visible={scanner && focused} onClose={() => setScanner(false)} onScanned={payload => {void decode(payload);}}
    hint="Escanea o importa el QR bancario de Bolivia" />
  </SafeAreaView>;
}
const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.background}, content: {padding: 20, gap: 16},
  title: {fontSize: 24, fontWeight: '700', color: colors.dark}, notice: {padding: 12, backgroundColor: colors.primaryLight, borderRadius: 12},
  card: {padding: 20, gap: 12, backgroundColor: colors.white, borderRadius: 16},
  heading: {fontSize: 16, fontWeight: '600', color: colors.dark}, recipient: {fontSize: 20, fontWeight: '600', color: colors.dark},
  note: {fontSize: 13, color: colors.text.secondary}, error: {color: colors.danger},
  input: {borderWidth: 1, borderColor: colors.border, borderRadius: 10, padding: 12, fontSize: 22, color: colors.dark},
  button: {padding: 15, borderRadius: 12, backgroundColor: colors.primaryLight, alignItems: 'center'},
  buttonText: {fontWeight: '600', color: colors.primaryDark}, disabled: {opacity: 0.45},
});
