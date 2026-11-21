// Confío IA from a Cuenta inteligente context (own smart_0 or an inherited
// smart_N): the assistant server resolves its viewer from a personal or
// business context only (inbox get_context_models refuses a smart token, and
// the smart-context gate refuses askAssistant and every other assistant
// mutation). Its tools would otherwise act on the personal account or, from
// an inherited account, never as that account's previous owner. So the chat
// is not offered here: one sentence and the way back to the personal account.
import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { Text } from '../components/common/AppText';
import { useReturnToPersonal } from '../components/smartAccount/AccountSwitcherHost';

const EMERALD = '#047857';

/** The active account is a Cuenta inteligente context (own or inherited). */
export const isSmartContext = (account: { type?: string | null } | null | undefined): boolean =>
  (account?.type || '').toLowerCase() === 'smart';

export const SMART_CONTEXT_ASSISTANT_COPY = 'Cambia a tu cuenta personal para hablar con Confío IA';

export function SmartContextAssistantNotice() {
  const { returnToPersonal, switching } = useReturnToPersonal();
  return (
    <View style={styles.box} testID="assistant-smart-context">
      <Text style={styles.title}>{SMART_CONTEXT_ASSISTANT_COPY}</Text>
      <Text style={styles.body}>
        Desde tu Cuenta inteligente, Confío IA no puede leer ni preparar nada. Tus reglas y alertas las ves en la
        Cuenta inteligente.
      </Text>
      <Pressable
        onPress={() => { void returnToPersonal(); }}
        disabled={switching}
        style={({ pressed }) => [styles.button, (pressed || switching) && styles.pressed]}
        accessibilityRole="button"
        accessibilityState={{ busy: switching, disabled: switching }}
        accessibilityLabel="Cambiar a mi cuenta personal"
        testID="assistant-switch-personal"
      >
        {switching
          ? <ActivityIndicator color="#FFFFFF" />
          : <Text style={styles.buttonText}>Cambiar a mi cuenta personal</Text>}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { flex: 1, justifyContent: 'center', paddingHorizontal: 24, paddingVertical: 32 },
  title: { fontSize: 18, lineHeight: 25, fontWeight: '700', color: '#111827', textAlign: 'center' },
  body: { fontSize: 14, lineHeight: 20, color: '#4B5563', textAlign: 'center', marginTop: 8 },
  button: {
    marginTop: 20, minHeight: 48, borderRadius: 14, backgroundColor: EMERALD,
    alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18,
  },
  pressed: { opacity: 0.75 },
  buttonText: { fontSize: 16, fontWeight: '700', color: '#FFFFFF' },
});
