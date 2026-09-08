import React, { useRef, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useQuery } from '@apollo/client';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { useNavigation } from '@react-navigation/native';
import { BRIDGE_AVAILABILITY, BRIDGE_HISTORY, BridgeTransfer, authorizePaymentBridge, bridgeRequestId, preparePaymentBridge } from '../services/paymentBridge';

export function bridgeAmount(units: string, decimals: number): string {
  const n = BigInt(units || '0'), base = 10n ** BigInt(decimals);
  return `${n / base}.${((n % base) * 1000000n / base).toString().padStart(6, '0')}`;
}

export function bridgeStatus(t: BridgeTransfer): string {
  if (t.providerCredited) return 'Acreditado en tu cuenta local';
  if (t.status === 'delivered') return t.sourceTokenId === 'BSC:USDT'
    ? 'Entregado. Pendiente de acreditación en tu cuenta local.' : 'Dólares recibidos en tu billetera.';
  return ({ prepared: 'Listo para confirmar', submitted: 'Envío en proceso', bridging: 'Envío en proceso',
    expired: 'Cotización vencida', failed: 'El envío no se completó', refunded: 'Fondos devueltos',
    needs_review: 'Estamos revisando el envío. No lo repitas.' } as Record<string, string>)[t.status] || 'Consultando estado';
}

export default function LocalAccountFundingScreen() {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const availability = useQuery(BRIDGE_AVAILABILITY, { fetchPolicy: 'network-only' });
  const [limit, setLimit] = useState(20);
  const history = useQuery(BRIDGE_HISTORY, { variables: { offset: 0, limit }, fetchPolicy: 'network-only', pollInterval: 5000 });
  const [direction, setDirection] = useState('to_provider');
  const [instruction, setInstruction] = useState('');
  const [amount, setAmount] = useState('');
  const [review, setReview] = useState<BridgeTransfer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<string | null>(null);
  const inFlight = useRef(false);
  const instructions = (availability.data?.paymentBridgeInstructions || []).filter((i: any) => direction === 'to_wallet' || i.canFund);
  const enabled = availability.data?.paymentBridgeAvailability?.[direction === 'to_provider' ? 'toProvider' : 'toWallet'];
  const rows: BridgeTransfer[] = history.data?.myPaymentBridges || [];
  const current = rows.find(t => t.internalId === review?.internalId) || review;
  const button = (label: string, action: () => void, disabled = false) => <TouchableOpacity accessibilityRole="button" disabled={disabled || busy} onPress={action} style={[styles.button, (disabled || busy) && styles.disabled]}><Text style={styles.buttonText}>{label}</Text></TouchableOpacity>;
  const prepare = async () => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    try {
      request.current ||= bridgeRequestId();
      setReview(await preparePaymentBridge(instruction, amount.replace(',', '.'), direction, request.current));
      await history.refetch();
    } catch { setError('No se pudo preparar el envío. Actualiza el historial antes de intentar de nuevo.'); }
    finally { inFlight.current = false; setBusy(false); }
  };
  const confirm = async () => {
    if (!current || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    try { setReview(await authorizePaymentBridge(current)); }
    catch { setError('No pudimos confirmar el resultado. Actualiza el estado de este envío antes de volver a intentar.'); }
    finally { await history.refetch().catch(() => {}); inFlight.current = false; setBusy(false); }
  };
  return <SafeAreaView style={styles.root}><ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
    {button('Volver', () => navigation.goBack())}
    <Text style={styles.title}>Dólares y cuenta local</Text>
    {button('Pagos con cuenta local', () => navigation.navigate('InfiniaPayment'))}
    {button('Pagos en Colombia', () => navigation.navigate('CobrePayment'))}
    <Text style={styles.text}>Consulta tus envíos y mueve dólares entre Confío y tu cuenta local.</Text>
    {busy && <ActivityIndicator accessibilityLabel="Procesando" />}
    {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
    {current ? <View style={styles.card}>
      <Text style={styles.heading}>{bridgeStatus(current)}</Text>
      <Text style={styles.text}>Monto: {bridgeAmount(current.amountUnits, current.sourceTokenId === 'BSC:USDT' ? 18 : 6)} dólares</Text>
      <Text style={styles.text}>Recibirás al menos: {bridgeAmount(current.amountOutMin, current.sourceTokenId === 'BSC:USDT' ? 6 : 18)} dólares</Text>
      {BigInt(current.feeUnits) > 0n && <Text style={styles.text}>Costo de conversión adicional: {bridgeAmount(current.feeUnits, 18)} dólares</Text>}
      {current.sourceTokenId === 'BSC:USDT' && <Text style={styles.text}>El monto recibido ya incluye los costos del envío. La conversión a moneda local y el pago a un banco son pasos separados.</Text>}
      <Text selectable style={styles.reference}>Referencia: {current.internalId}</Text>
      {current.status === 'prepared' && button('Confirmar envío', confirm, !availability.data?.paymentBridgeAvailability?.[current.sourceTokenId === 'BSC:USDT' ? 'toProvider' : 'toWallet'] || BigInt(current.deadline) <= BigInt(Math.floor(Date.now() / 1000) + 30))}
      {current.sourceTxHash && <Text style={styles.text}>Puedes cerrar la app. El envío seguirá en proceso.</Text>}
      {button('Ver historial', () => setReview(null))}
    </View> : <>
      {button(direction === 'to_provider' ? 'Hacia mi cuenta local' : 'Hacia Confío', () => { setDirection(direction === 'to_provider' ? 'to_wallet' : 'to_provider'); setInstruction(''); request.current = null; })}
      {direction === 'to_wallet' && <Text style={styles.text}>Disponible cuando los dólares retirados de tu cuenta local ya llegaron a tu billetera.</Text>}
      {instructions.map((i: any) => button(`${instruction === i.internalId ? '✓ ' : ''}${i.holderName || 'Mi cuenta'} · ${i.country}`, () => { setInstruction(i.internalId); request.current = null; }))}
      {!enabled && <Text style={styles.text}>Este servicio todavía no está disponible para tu cuenta.</Text>}
      <TextInput accessibilityLabel="Monto en dólares" placeholder="Monto en dólares" keyboardType="decimal-pad" value={amount} onChangeText={value => { setAmount(value); request.current = null; }} style={styles.input} editable={!busy} />
      {button('Revisar envío', prepare, !enabled || !instruction || !/^\d+([.,]\d+)?$/.test(amount))}
    </>}
    <Text style={styles.heading}>Historial</Text>
    {button('Actualizar estado', () => { history.refetch().catch(() => setError('No se pudo actualizar el estado.')); })}
    {history.error && <Text style={styles.error}>No se pudo consultar el historial.</Text>}
    {rows.map(t => <TouchableOpacity accessibilityRole="button" key={t.internalId} onPress={() => setReview(t)} style={styles.card}>
      <Text style={styles.heading}>{bridgeStatus(t)}</Text>
      <Text style={styles.text}>{t.sourceTokenId === 'BSC:USDT' ? 'Hacia cuenta local' : 'Hacia Confío'} · {bridgeAmount(t.amountUnits, t.sourceTokenId === 'BSC:USDT' ? 18 : 6)} dólares</Text>
      <Text style={styles.reference}>{t.internalId}</Text>
    </TouchableOpacity>)}
    {rows.length >= limit && limit < 100 && button('Ver más', () => setLimit(Math.min(100, limit + 20)))}
  </ScrollView></SafeAreaView>;
}
const styles = StyleSheet.create({ root: { flex: 1, backgroundColor: '#f8fafc' }, content: { padding: 20, gap: 12 },
  title: { fontSize: 26, fontWeight: '700', color: '#111827' }, heading: { fontSize: 17, fontWeight: '600', color: '#111827' },
  text: { fontSize: 15, lineHeight: 22, color: '#374151' }, reference: { fontSize: 12, color: '#6b7280' },
  card: { padding: 16, borderRadius: 12, backgroundColor: '#fff', gap: 10 }, button: { padding: 14, borderRadius: 10, backgroundColor: '#065f46' },
  buttonText: { color: '#fff', textAlign: 'center', fontWeight: '600' }, disabled: { opacity: 0.4 },
  input: { borderWidth: 1, borderColor: '#9ca3af', borderRadius: 10, padding: 14, color: '#111827', backgroundColor: '#fff' }, error: { color: '#b91c1c' } });
