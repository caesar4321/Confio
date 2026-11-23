// Cuenta inteligente: save a Mexican CLABE for a bank payment rule, from the
// rule's own destination picker. It lands in the owner's saved recipients
// (the same ones Enviar uses); the same CLABE saved again is the same one.
// The name is optional and is the owner's words: the bank does not verify
// it while its lookup is off. Saving moves no money; the rule itself is still
// signed (with Face) afterwards.
import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { Text, TextInput } from '../common/AppText';
import { ActionButton } from './kit';
import { SA } from './tokens';
import {
  clabeDigits, clabeValid, saveSmartAccountClabeDestination, type SmartAccountPayoutMethod,
} from '../../services/smartAccount';

/** Light check before the server's (which stays authoritative). '' = fine. */
export function clabeFieldError(value: string): string {
  const digits = clabeDigits(value);
  if (!/^\d{18}$/.test(digits)) {
    return 'La CLABE tiene 18 dígitos.';
  }
  return clabeValid(digits) ? '' : 'Esa CLABE no es válida: revisa los 18 dígitos.';
}

export function ClabeDestinationForm({ onSaved, onCancel }: {
  onSaved: (method: SmartAccountPayoutMethod) => void;
  onCancel: () => void;
}) {
  const [clabe, setClabe] = useState('');
  const [holderName, setHolderName] = useState('');
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState('');
  const alive = useRef(true);
  const busy = useRef(false);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const error = clabeFieldError(clabe);

  const save = async () => {
    setTouched(true);
    setServerError('');
    if (error || busy.current) {
      return;
    }
    busy.current = true;
    setSaving(true);
    const out = await saveSmartAccountClabeDestination({ clabe, holderName: holderName.trim() });
    busy.current = false;
    if (!alive.current) {
      return;
    }
    setSaving(false);
    if (out.success && out.payoutMethod) {
      onSaved(out.payoutMethod);
      return;
    }
    setServerError(out.errorMessage || 'No pudimos guardar la CLABE. Inténtalo de nuevo.');
  };

  return (
    <View testID="clabe-form">
      <Text style={styles.lead}>
        La CLABE de quien recibe. Guardarla no mueve dinero: después eliges el monto y firmas la regla.
      </Text>
      <View style={styles.field}>
        <Text style={styles.label}>CLABE</Text>
        <TextInput
          value={clabe}
          onChangeText={setClabe}
          placeholder="18 dígitos"
          placeholderTextColor={SA.faint}
          keyboardType="number-pad"
          autoCorrect={false}
          maxLength={24}
          style={[styles.input, touched && error ? styles.inputError : null]}
          accessibilityLabel="CLABE"
          testID="clabe-number"
        />
        {touched && error ? (
          <Text style={styles.error} accessibilityLiveRegion="polite" testID="clabe-number-error">{error}</Text>
        ) : null}
      </View>
      <View style={styles.field}>
        <Text style={styles.label}>Nombre de quien recibe (opcional)</Text>
        <TextInput
          value={holderName}
          onChangeText={setHolderName}
          placeholder="Nombre y apellido"
          placeholderTextColor={SA.faint}
          autoCapitalize="words"
          autoCorrect={false}
          style={styles.input}
          accessibilityLabel="Nombre de quien recibe, opcional"
          testID="clabe-name"
        />
        <Text style={styles.hint}>El banco no verifica este nombre: revisa bien la CLABE.</Text>
      </View>
      {serverError ? (
        <Text style={styles.error} accessibilityLiveRegion="polite" testID="clabe-error">{serverError}</Text>
      ) : null}
      <ActionButton label="Guardar CLABE" onPress={() => { void save(); }} busy={saving} style={styles.gapLarge}
        testID="clabe-save" />
      <ActionButton label="Cancelar" variant="quiet" onPress={onCancel} disabled={saving} style={styles.gap}
        testID="clabe-cancel" />
    </View>
  );
}

const styles = StyleSheet.create({
  lead: { fontSize: 15, lineHeight: 22, color: SA.muted, marginBottom: 12 },
  field: { marginTop: 16 },
  label: { fontSize: 14, fontWeight: '600', color: SA.muted, marginBottom: 8 },
  input: {
    minHeight: 52, borderRadius: 14, borderWidth: 1.5, borderColor: SA.line, backgroundColor: SA.card,
    paddingHorizontal: 14, fontSize: 17, color: SA.text,
  },
  inputError: { borderColor: SA.noticeText },
  error: { fontSize: 13, lineHeight: 19, color: SA.noticeText, marginTop: 8 },
  hint: { fontSize: 13, lineHeight: 19, color: SA.muted, marginTop: 8 },
  gap: { marginTop: 8 },
  gapLarge: { marginTop: 24 },
});
