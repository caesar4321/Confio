// Cuenta inteligente: save a Venezuelan Pago Móvil account for a bank
// payment rule, from the rule's own destination picker. The server validates
// with the VE send's rules (bank, phone, cédula, holder name) and answers
// with the saved destination, which the rule then names. Saving moves no
// money; the rule itself is still signed (with Face) afterwards.
import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { Text, TextInput } from '../common/AppText';
import { ActionButton, IconDisc, LoadError, Row, RowsSkeleton } from './kit';
import { SA } from './tokens';
import {
  fetchSmartAccountPagoMovilBanks, saveSmartAccountPagoMovilDestination,
  type SmartAccountPagoMovilBank, type SmartAccountPayoutMethod,
} from '../../services/smartAccount';

/** Light checks before the server's (which stay authoritative). '' = fine. */
export function pagoMovilFieldErrors(input: {
  bank: SmartAccountPagoMovilBank | null; phone: string; idNumber: string; holderName: string;
}): { bank: string; phone: string; idNumber: string; holderName: string } {
  let digits = input.phone.replace(/\D/g, '');
  if (digits.startsWith('58') && digits.length === 12) {
    digits = digits.slice(2);
  } else if (digits.startsWith('0') && digits.length === 11) {
    digits = digits.slice(1);
  }
  const cedula = input.idNumber.toUpperCase().replace(/[^A-Z0-9]/g, '');
  const fullCedula = /^\d/.test(cedula) ? `V${cedula}` : cedula;
  return {
    bank: input.bank ? '' : 'Elige el banco.',
    phone: /^4(12|14|16|22|24|26)\d{7}$/.test(digits) ? '' : 'Escribe un móvil venezolano, por ejemplo 0414 1234567.',
    idNumber: /^[VEJPG]\d{6,9}$/.test(fullCedula) ? '' : 'La cédula debe tener el formato V12345678.',
    holderName: input.holderName.trim().split(/\s+/).join(' ').length >= 2 ? '' : 'Escribe el nombre de quien recibe.',
  };
}

function Field({ label, value, onChange, error, placeholder, keyboardType, autoCapitalize, testID }: {
  label: string; value: string; onChange: (v: string) => void; error: string; placeholder: string;
  keyboardType?: 'phone-pad' | 'default'; autoCapitalize?: 'none' | 'words' | 'characters'; testID: string;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={SA.faint}
        keyboardType={keyboardType ?? 'default'}
        autoCapitalize={autoCapitalize ?? 'none'}
        autoCorrect={false}
        style={[styles.input, error ? styles.inputError : null]}
        accessibilityLabel={label}
        testID={testID}
      />
      {error ? <Text style={styles.error} accessibilityLiveRegion="polite">{error}</Text> : null}
    </View>
  );
}

export function PagoMovilDestinationForm({ onSaved, onCancel }: {
  onSaved: (method: SmartAccountPayoutMethod) => void;
  onCancel: () => void;
}) {
  const [banks, setBanks] = useState<SmartAccountPagoMovilBank[] | null>(null);
  const [banksFailed, setBanksFailed] = useState(false);
  const [choosingBank, setChoosingBank] = useState(false);
  const [bank, setBank] = useState<SmartAccountPagoMovilBank | null>(null);
  const [phone, setPhone] = useState('');
  const [idNumber, setIdNumber] = useState('');
  const [holderName, setHolderName] = useState('');
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState('');
  const alive = useRef(true);
  const busy = useRef(false);

  const loadBanks = async () => {
    setBanksFailed(false);
    const out = await fetchSmartAccountPagoMovilBanks();
    if (!alive.current) {
      return;
    }
    if (out.ok && out.data.length > 0) {
      setBanks(out.data);
    } else {
      setBanksFailed(true);
    }
  };

  useEffect(() => {
    alive.current = true;
    void loadBanks();
    return () => { alive.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const errors = pagoMovilFieldErrors({ bank, phone, idNumber, holderName });
  const invalid = !!(errors.bank || errors.phone || errors.idNumber || errors.holderName);

  const save = async () => {
    setTouched(true);
    setServerError('');
    if (invalid || !bank || busy.current) {
      return;
    }
    busy.current = true;
    setSaving(true);
    const out = await saveSmartAccountPagoMovilDestination({
      phone: phone.trim(), bankCode: bank.code, idNumber: idNumber.trim(), holderName: holderName.trim(),
    });
    busy.current = false;
    if (!alive.current) {
      return;
    }
    setSaving(false);
    if (out.success && out.payoutMethod) {
      onSaved(out.payoutMethod);
      return;
    }
    setServerError(out.errorMessage || 'No pudimos guardar la cuenta. Inténtalo de nuevo.');
  };

  if (choosingBank) {
    return (
      <View testID="pagomovil-banks">
        <Text style={styles.lead}>Elige el banco de quien recibe</Text>
        {banks === null && !banksFailed ? <RowsSkeleton rows={4} /> : banksFailed && !banks ? (
          <LoadError onRetry={() => { void loadBanks(); }} />
        ) : (banks ?? []).map((b, i) => (
          // A fixed list of ~24 Venezuelan banks: plain rows in the sheet's scroll.
          <Row
            key={b.code}
            divider={i > 0}
            title={b.name}
            subtitle={b.code}
            selected={bank?.code === b.code}
            onPress={() => { setBank(b); setChoosingBank(false); }}
            testID={`pagomovil-bank-${b.code}`}
          />
        ))}
        <ActionButton label="Volver" variant="quiet" onPress={() => setChoosingBank(false)} style={styles.gap} />
      </View>
    );
  }

  return (
    <View testID="pagomovil-form">
      <Text style={styles.lead}>
        Los datos de Pago Móvil de quien recibe. Guardarla no mueve dinero: después eliges el monto y firmas la regla.
      </Text>
      <Text style={styles.label}>Banco</Text>
      <Row
        left={<IconDisc icon="home" tone={bank ? 'mint' : 'neutral'} size={36} />}
        title={bank ? bank.name : 'Elegir banco'}
        onPress={() => setChoosingBank(true)}
        chevron
        accessibilityLabel={bank ? `Banco: ${bank.name}. Cambiar` : 'Elegir banco'}
        testID="pagomovil-bank"
      />
      {touched && errors.bank ? <Text style={styles.error}>{errors.bank}</Text> : null}
      <Field label="Teléfono" value={phone} onChange={setPhone} error={touched ? errors.phone : ''}
        placeholder="0414 1234567" keyboardType="phone-pad" testID="pagomovil-phone" />
      <Field label="Cédula" value={idNumber} onChange={setIdNumber} error={touched ? errors.idNumber : ''}
        placeholder="V12345678" autoCapitalize="characters" testID="pagomovil-id" />
      <Field label="Nombre de quien recibe" value={holderName} onChange={setHolderName}
        error={touched ? errors.holderName : ''} placeholder="Nombre y apellido" autoCapitalize="words"
        testID="pagomovil-name" />
      {serverError ? (
        <Text style={styles.error} accessibilityLiveRegion="polite" testID="pagomovil-error">{serverError}</Text>
      ) : null}
      <ActionButton label="Guardar cuenta" onPress={() => { void save(); }} busy={saving} style={styles.gapLarge}
        testID="pagomovil-save" />
      <ActionButton label="Cancelar" variant="quiet" onPress={onCancel} disabled={saving} style={styles.gap}
        testID="pagomovil-cancel" />
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
  gap: { marginTop: 8 },
  gapLarge: { marginTop: 24 },
});
