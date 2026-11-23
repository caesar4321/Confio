// Details the person types right in the conversation (assistant/here.py,
// `ask_details`): a short form under the answer. What they type goes
// straight from this phone to the app's own mutation, the same one the
// screen uses; the assistant never sees the fields and never fills them in.
//
// An action arrives as { type: 'form', target: '<key>', label }.
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { useApolloClient } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { Text, TextInput } from '../components/common/AppText';
import { UPDATE_INVESTOR_BIO } from '../apollo/mutations';
import { UPDATE_USER_PROFILE } from '../apollo/queries';
import { useAuth } from '../contexts/AuthContext';
import { SAVE_VE_AGENDA_ENTRY } from '../services/agenda';
import { PaymentIntentError, prepareRequestInChat } from '../services/paymentIntent';
import { VE_BANKS } from '../services/vePagoMovilTopUp';

const EMERALD = '#047857';
const INK = '#111827';
const MUTED = '#4B5563';

type Bank = { code: string; name: string };
type Field = {
  key: string;
  label: string;
  placeholder?: string;
  keyboard?: 'default' | 'number-pad' | 'decimal-pad' | 'phone-pad';
  /** Chosen from the list of Venezuelan banks. */
  bank?: boolean;
  /** A sentence: more than one line, with a limit that is counted. */
  max?: number;
};
export const BIO_MAX = 140;

export const HERE_FORMS: Record<string, { fields: Field[]; submit: string }> = {
  profile_name: {
    fields: [{ key: 'firstName', label: 'Nombre' }, { key: 'lastName', label: 'Apellido' }],
    submit: 'Guardar',
  },
  investor_bio: {
    fields: [{ key: 'bio', label: 'Tu descripción', placeholder: 'Ahorro en dólares y compro un poco cada mes', max: BIO_MAX }],
    submit: 'Guardar',
  },
  agenda_pagomovil: {
    fields: [
      { key: 'label', label: 'Nombre para reconocerlo', placeholder: 'Mamá' },
      { key: 'holderName', label: 'Titular de la cuenta', placeholder: 'Como aparece en su banco' },
      { key: 'phone', label: 'Teléfono', placeholder: '04141234567', keyboard: 'phone-pad' },
      { key: 'cedula', label: 'Cédula', placeholder: 'V12345678' },
      { key: 'bank', label: 'Banco', placeholder: 'Escribe el nombre', bank: true },
    ],
    submit: 'Guardar en mi Agenda',
  },
  pagomovil_payment: {
    fields: [
      { key: 'label', label: 'Nombre para reconocerlo', placeholder: 'Mamá' },
      { key: 'holderName', label: 'Titular de la cuenta', placeholder: 'Como aparece en su banco' },
      { key: 'phone', label: 'Teléfono', placeholder: '04141234567', keyboard: 'phone-pad' },
      { key: 'cedula', label: 'Cédula', placeholder: 'V12345678' },
      { key: 'bank', label: 'Banco', placeholder: 'Escribe el nombre', bank: true },
      { key: 'amountUsd', label: 'Cuántos dólares envías', placeholder: '20', keyboard: 'decimal-pad' },
    ],
    submit: 'Preparar el pago',
  },
};

/** The form this build knows; null for anything else. */
export function resolveForm(a: { type: string; target?: string | null; label?: string | null }): { key: string; label: string } | null {
  return a.type === 'form' && a.target && a.label && Object.prototype.hasOwnProperty.call(HERE_FORMS, a.target)
    ? { key: a.target, label: a.label } : null;
}

const digits = (value: string) => value.replace(/\D/g, '');

/** What is still missing before it can be sent, in the person's words; '' when ready. */
export function formProblem(key: string, values: Record<string, string>, bank: Bank | null): string {
  const has = (field: string) => (values[field] || '').trim().length > 0;
  if (key === 'profile_name') {
    // Only the first name is required, as on the profile screen.
    return has('firstName') ? '' : 'Escribe tu nombre.';
  }
  if (key === 'investor_bio') {
    const bio = (values.bio || '').trim();
    if (!bio) return 'Escribe tu descripción.';
    if (bio.length > BIO_MAX) return `Tu descripción supera los ${BIO_MAX} caracteres.`;
    // The server refuses links too: said here, before it is sent for review.
    return /https?:\/\/|www\./i.test(bio) ? 'Tu descripción no puede llevar enlaces.' : '';
  }
  if (!has('label')) return 'Ponle un nombre para reconocerlo.';
  // The server asks for the holder too: said here, before anything is sent.
  if (!has('holderName')) return 'Escribe el nombre del titular de la cuenta.';
  if (digits(values.phone || '').length < 10) return 'Escribe el teléfono completo.';
  if (digits(values.cedula || '').length < 6) return 'Escribe la cédula completa.';
  if (!bank) return 'Elige el banco.';
  if (key === 'pagomovil_payment') {
    const typed = (values.amountUsd || '').trim();
    if (!typed) return 'Escribe cuántos dólares quieres enviar.';
    // "1,500" is a thousand five hundred to some and one and a half to
    // others: only a plain amount is taken.
    if (!/^\d+([.,]\d{1,2})?$/.test(typed) || !(Number(typed.replace(',', '.')) > 0)) {
      return 'Escribe el monto sin puntos de miles, por ejemplo 20 o 20,50.';
    }
  }
  return '';
}

export function HereForm({ formKey, label, onPrepared }: {
  formKey: string;
  label: string;
  /** A payment was prepared: its card is now a line of the thread. */
  onPrepared: () => void;
}) {
  const client = useApolloClient();
  const { userProfile, refreshProfile } = useAuth() as any;
  const form = HERE_FORMS[formKey];
  const needsBank = form.fields.some((f) => f.bank);
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    if (formKey === 'profile_name') {
      initial.firstName = userProfile?.firstName || '';
      initial.lastName = userProfile?.lastName || '';
    }
    return initial;
  });
  const [bank, setBank] = useState<Bank | null>(null);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');

  useEffect(() => {
    if (!needsBank) return undefined;
    let alive = true;
    client.query({ query: VE_BANKS, fetchPolicy: 'cache-first' })
      .then(({ data }) => { if (alive) setBanks(data?.vePagomovilBanks || []); })
      .catch(() => {});
    return () => { alive = false; };
  }, [client, needsBank]);

  const set = (key: string, value: string) => {
    setError('');
    setValues((prev) => ({ ...prev, [key]: value }));
    if (key === 'bank') setBank(null);
  };
  const typed = (values.bank || '').trim().toLowerCase();
  const matches = bank || !typed ? [] : banks.filter((b) => b.name.toLowerCase().includes(typed)).slice(0, 4);

  const submit = async () => {
    if (busy || done) return;
    const problem = formProblem(formKey, values, bank);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError('');
    try {
      if (formKey === 'profile_name') {
        const { data } = await client.mutate({
          mutation: UPDATE_USER_PROFILE,
          variables: { firstName: values.firstName.trim(), lastName: (values.lastName || '').trim() },
        });
        if (!data?.updateUserProfile?.success) {
          setError(data?.updateUserProfile?.error || 'No se pudo guardar. Inténtalo de nuevo.');
          return;
        }
        await refreshProfile('personal').catch(() => {});
        setDone('Listo: guardé tu nombre');
        return;
      }
      if (formKey === 'investor_bio') {
        const { data } = await client.mutate({ mutation: UPDATE_INVESTOR_BIO, variables: { bio: values.bio.trim() } });
        const result = data?.updateInvestorBio;
        if (result?.rulesRequired) {
          // Accepting the rules is a consent given on its own screen.
          setError('Primero acepta las normas de la Comunidad: ábrela una vez desde el menú y vuelve aquí.');
          return;
        }
        if (!result?.success) {
          setError(result?.error || 'No se pudo guardar. Inténtalo de nuevo.');
          return;
        }
        setDone('Listo: guardé tu descripción');
        return;
      }
      // Saved by the person themselves first: a Pago Móvil has no payee
      // lookup, so the only recipient a payment card will show is one they
      // entered and kept (payment_accounts.intent_rails.read_pagomovil).
      const saved = await client.mutate({
        mutation: SAVE_VE_AGENDA_ENTRY,
        variables: {
          id: null, label: values.label.trim(), relationship: null, holderName: (values.holderName || '').trim(),
          cedula: values.cedula.trim(), phone: values.phone.trim(), bankCode: bank!.code,
        },
        fetchPolicy: 'no-cache',
      });
      const entry = saved.data?.saveVePagomovilAgendaEntry;
      if (!entry?.success) {
        setError(entry?.errors?.[0] || 'No se pudo guardar. Revisa los datos.');
        return;
      }
      if (formKey === 'agenda_pagomovil') {
        setDone(`Listo: guardé a ${values.label.trim()} en tu Agenda`);
        return;
      }
      await prepareRequestInChat({
        methodId: 've_pagomovil_send', phone: values.phone.trim(), cedula: values.cedula.trim(), bankCode: bank!.code,
        holderName: (values.holderName || '').trim(), amountUsd: values.amountUsd.replace(',', '.').trim(),
      });
      setDone('Listo: revisa el pago en la tarjeta de abajo');
      onPrepared();
    } catch (e) {
      setError(e instanceof PaymentIntentError ? e.message : 'Sin conexión. Inténtalo de nuevo.');
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <View style={[styles.card, styles.done]} accessible accessibilityLabel={done}>
        <Icon name="check-circle" size={18} color={EMERALD} />
        <Text style={styles.doneText}>{done}</Text>
      </View>
    );
  }
  return (
    <View style={styles.card}>
      <Text style={styles.title}>{label}</Text>
      {form.fields.map((field) => (
        <View key={field.key} style={styles.field}>
          <Text style={styles.fieldLabel}>{field.label}</Text>
          <TextInput
            style={styles.input}
            value={field.bank && bank ? bank.name : values[field.key] || ''}
            onChangeText={(value: string) => set(field.key, value)}
            placeholder={field.placeholder}
            placeholderTextColor="#6B7280"
            keyboardType={field.keyboard || 'default'}
            autoCapitalize={field.key === 'cedula' ? 'characters' : field.bank ? 'none' : field.max ? 'sentences' : 'words'}
            autoCorrect={!!field.max}
            multiline={!!field.max}
            maxLength={field.max}
            editable={!busy}
            accessibilityLabel={field.label}
          />
          {field.max ? (
            <Text style={styles.count}>{`${(values[field.key] || '').length}/${field.max}`}</Text>
          ) : null}
          {field.bank && matches.length ? (
            <View style={styles.banks}>
              {matches.map((b) => (
                <Pressable key={b.code} onPress={() => { setBank(b); setError(''); }} style={styles.bank}
                  accessibilityRole="button" accessibilityLabel={`Elegir ${b.name}`}>
                  <Text style={styles.bankText} numberOfLines={1}>{b.name}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
        </View>
      ))}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable onPress={() => void submit()} disabled={busy}
        style={({ pressed }) => [styles.submit, pressed && styles.submitPressed]}
        accessibilityRole="button" accessibilityState={{ busy }} accessibilityLabel={form.submit}>
        {busy ? <ActivityIndicator size="small" color="#FFFFFF" /> : <Text style={styles.submitText}>{form.submit}</Text>}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 4, marginBottom: 4, maxWidth: 340, padding: 14, borderRadius: 16,
    borderWidth: 1, borderColor: '#A7F3D0', backgroundColor: '#FFFFFF',
  },
  title: { fontSize: 15, fontWeight: '700', color: INK, marginBottom: 4 },
  field: { marginTop: 10 },
  fieldLabel: { fontSize: 13, color: MUTED, marginBottom: 4 },
  input: {
    minHeight: 46, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16, color: INK,
    backgroundColor: '#F3F4F6',
  },
  count: { fontSize: 12, color: MUTED, textAlign: 'right', marginTop: 4 },
  banks: { marginTop: 6, gap: 6 },
  bank: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 12, borderRadius: 12, borderWidth: 1, borderColor: '#D1D5DB' },
  bankText: { fontSize: 15, color: INK },
  error: { fontSize: 13, lineHeight: 18, color: '#B91C1C', marginTop: 10 },
  submit: { marginTop: 14, height: 48, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: EMERALD },
  submitPressed: { backgroundColor: '#065F46' },
  submitText: { fontSize: 16, fontWeight: '700', color: '#FFFFFF' },
  done: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  doneText: { flex: 1, fontSize: 15, fontWeight: '600', color: EMERALD },
});
