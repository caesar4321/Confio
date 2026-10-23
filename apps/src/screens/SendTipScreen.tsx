import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { useIsFocused, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useMutation } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { PREPARE_TIP } from '../apollo/mutations';
import { MainStackParamList } from '../types/navigation';
import { newClientKey } from '../utils/directMessages';
import { parseTipAmount, TIP_CHIPS, TIP_MAX, TIP_MIN } from '../utils/tips';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'SendTip'>['route'];

const NOTE_MAX = 140;

/**
 * Propina: an optional gift to another investor. 100% reaches them (Confío
 * takes no commission) and it never buys anything — not a reply, not
 * advice, not content. The note is reviewed before any money moves; then
 * the normal send flow (face check, signature) runs with the server's key.
 */
export const SendTipScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const { userId, username } = route.params;
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [prepareTip, { loading }] = useMutation(PREPARE_TIP);
  // Leaving while the note is reviewed cancels the tip: a late answer must
  // never start a payment the person walked away from.
  const isFocused = useIsFocused();
  const live = useRef(true);
  useEffect(() => () => { live.current = false; }, []);
  const focusedRef = useRef(isFocused);
  focusedRef.current = isFocused;
  const termsRef = useRef('');
  termsRef.current = `${userId}|${parseTipAmount(amount)}|${note.trim()}`;

  const parsed = parseTipAmount(amount);
  // One key per exact tip (recipient, amount, note): a retry of the same
  // tip reuses it, an edited tip gets a new one (the server refuses a key
  // reused for different terms).
  const keys = useRef(new Map<string, string>());
  const keyFor = (terms: string) => {
    if (!keys.current.has(terms)) keys.current.set(terms, newClientKey());
    return keys.current.get(terms) as string;
  };

  const submit = async (allowRepeat = false) => {
    if (!parsed || loading) return;
    setError(null);
    try {
      const trimmed = note.trim();
      const { data } = await prepareTip({
        variables: {
          recipientUserId: userId,
          amount: parsed,
          note: trimmed,
          clientKey: keyFor(`${userId}|${parsed}|${trimmed}|${allowRepeat ? 'again' : ''}`),
          allowRepeat,
        },
      });
      const result = data?.prepareTip;
      if (!live.current || !focusedRef.current) return;
      // The terms on screen are frozen while preparing; still, the answer must
      // be for exactly what is shown now.
      if (termsRef.current !== `${userId}|${parsed}|${trimmed}`) return;
      if (result?.code === 'tip_recent') {
        // The last one may have gone through even if the app said otherwise.
        Alert.alert('¿Enviar otra propina?', `${result.error} Revisa tu historial antes de enviar otra.`, [
          { text: 'Cancelar', style: 'cancel' },
          { text: 'Enviar otra', onPress: () => { void submit(true); } },
        ]);
        return;
      }
      if (!result?.success || !result.sendKey) {
        setError(result?.error || 'No pudimos preparar tu propina.');
        return;
      }
      // Never send an amount other than the one on screen.
      if (parseTipAmount(String(result.amount)) !== parsed) {
        setError('El monto cambió. Revisa tu propina e inténtalo de nuevo.');
        return;
      }
      (navigation as any).replace('TransactionProcessing', {
        transactionData: {
          type: 'sent',
          bscSend: true,
          amount: result.amount,
          currency: 'cUSD',
          recipient: username,
          recipientUserId: userId,
          action: 'Enviando propina',
          isOnConfio: true,
          // The note travels as the chat bubble, never as a payment memo.
          memo: '',
          // The tip's own key: the server refuses it for any other payment.
          idempotencyKey: result.sendKey,
        },
      });
    } catch {
      setError('No pudimos preparar tu propina. Revisa tu conexión.');
    }
  };

  return (
    <View style={styles.container}>
      <Header title="Enviar propina" navigation={navigation as any} onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background} isLight={false} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.to}>{`Para ${username}`}</Text>
          <View style={styles.amountRow}>
            <Text style={styles.currency}>$</Text>
            <TextInput
              value={amount}
              onChangeText={(text) => setAmount(text.replace(',', '.').replace(/[^0-9.]/g, '').slice(0, 7))}
              placeholder="0"
              placeholderTextColor={colors.muted}
              keyboardType="decimal-pad"
              editable={!loading}
              style={styles.amount}
              accessibilityLabel="Monto de la propina"
              autoFocus
            />
          </View>
          <View style={styles.chips}>
            {TIP_CHIPS.map((chip) => (
              <Pressable key={chip} onPress={() => setAmount(String(chip))} disabled={loading}
                style={[styles.chip, parsed === `${chip}.00` && styles.chipSelected]} accessibilityRole="button">
                <Text style={[styles.chipText, parsed === `${chip}.00` && styles.chipTextSelected]}>{`$${chip}`}</Text>
              </Pressable>
            ))}
          </View>
          <Text style={styles.limits}>{`De $${TIP_MIN} a $${TIP_MAX}. Se envía de tu saldo en dólares.`}</Text>
          <TextInput
            value={note}
            onChangeText={(text) => setNote(text.slice(0, NOTE_MAX))}
            placeholder="Nota opcional (ej.: ¡Gracias por tu análisis!)"
            placeholderTextColor={colors.muted}
            style={styles.note}
            multiline
            maxLength={NOTE_MAX}
            editable={!loading}
            accessibilityLabel="Nota"
          />
          <View style={styles.gift}>
            <Text style={styles.giftTitle}>Es un regalo</Text>
            <Text style={styles.giftText}>
              {`El 100% llega a ${username}: Confío no cobra comisión. Una propina no compra nada: ni respuestas, ni consejos, ni contenido.`}
            </Text>
          </View>
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </ScrollView>
        <View style={styles.footer}>
          <Pressable onPress={() => { void submit(false); }} disabled={!parsed || loading}
            style={[styles.button, (!parsed || loading) && styles.disabled]} accessibilityRole="button">
            {loading ? <ActivityIndicator color={colors.white} /> : (
              <Text style={styles.buttonText}>{parsed ? `Enviar propina de $${parsed}` : 'Ingresa un monto'}</Text>
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
};

export default SendTipScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  content: { padding: 20 },
  to: { fontSize: 15, color: colors.textSecondary, textAlign: 'center' },
  amountRow: { marginTop: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
  currency: { fontSize: 40, fontWeight: '700', color: colors.dark },
  amount: { minWidth: 80, fontSize: 48, fontWeight: '700', color: colors.dark, textAlign: 'center' },
  chips: { marginTop: 16, flexDirection: 'row', justifyContent: 'center', gap: 8 },
  chip: { paddingHorizontal: 18, paddingVertical: 9, borderRadius: 18, backgroundColor: colors.neutral },
  chipSelected: { backgroundColor: colors.dark },
  chipText: { fontSize: 15, fontWeight: '700', color: colors.dark },
  chipTextSelected: { color: colors.white },
  limits: { marginTop: 10, fontSize: 12, color: colors.textSecondary, textAlign: 'center' },
  note: {
    marginTop: 20, minHeight: 64, padding: 12, borderRadius: 12, borderWidth: 1, borderColor: colors.border,
    fontSize: 15, color: colors.dark, textAlignVertical: 'top',
  },
  gift: { marginTop: 16, padding: 14, borderRadius: 12, backgroundColor: colors.primaryLight },
  giftTitle: { fontSize: 14, fontWeight: '700', color: colors.primaryDeep },
  giftText: { marginTop: 4, fontSize: 13, lineHeight: 18, color: colors.primaryDeep },
  error: { marginTop: 12, fontSize: 14, color: colors.error.text, textAlign: 'center' },
  footer: { padding: 16, borderTopWidth: 1, borderTopColor: colors.border },
  button: { height: 50, borderRadius: 25, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.dark },
  disabled: { opacity: 0.4 },
  buttonText: { fontSize: 16, fontWeight: '700', color: colors.white },
});
