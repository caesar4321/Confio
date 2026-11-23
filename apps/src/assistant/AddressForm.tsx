// "Dirección y teléfono" filled in right in the conversation: the address the
// bank asks for before a top-up or a withdrawal.
//
// The same fields, rules and mutation as the address screen
// (screens/RampAddressScreen): street, the colonia where the rail asks for
// it, city, state, postal code (Bolivia has none in everyday use: "0000"),
// the economic activity from the provider's own list, and in Colombia a
// real e-mail when the account's is a hidden one. What is typed goes from
// this phone straight to that mutation; the assistant never sees it.
//
// Kept simple on purpose: the country is the one the address already has (or
// where the person lives) and the phone is left as it is. Changing either,
// or adding a phone that is missing, is done on the screen, which this form
// opens.
import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { GET_MY_RAMP_ADDRESS, GET_RAMP_ADDRESS_REQUIREMENTS, GET_RAMP_PHONE_STATUS, UPSERT_RAMP_USER_ADDRESS } from '../apollo/queries';
import { Text, TextInput } from '../components/common/AppText';
import { toIso2 } from '../config/localRails';
import { useAuth } from '../contexts/AuthContext';
import { AnalyticsService } from '../services/analyticsService';
import { userCountryIso } from '../utils/userCountry';

const EMERALD = '#047857';
const INK = '#111827';
const MUTED = '#4B5563';
const RELAY = /@privaterelay\.appleid\.com$/i;

type Activity = { label: string; value: string };

/** What is still missing, in the person's words; '' when it can be saved. */
export function addressProblem(v: {
  street: string; neighborhood: string; city: string; state: string; zip: string; activity: string; email: string;
}, needs: { neighborhood: boolean; neighborhoodLabel: string; activity: boolean; email: boolean; country: boolean }): string {
  if (!v.street.trim()) return 'Escribe tu dirección.';
  if (needs.neighborhood && !v.neighborhood.trim()) return `Escribe tu ${needs.neighborhoodLabel.toLowerCase()}.`;
  if (!v.city.trim()) return 'Escribe tu ciudad.';
  if (!v.state.trim()) return 'Escribe tu provincia o estado.';
  if (!v.zip.trim()) return 'Escribe tu código postal.';
  if (needs.activity && !v.activity.trim()) return 'Elige tu actividad económica.';
  if (needs.email) {
    const email = v.email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return 'Escribe un correo tuyo que puedas abrir: el banco te escribe ahí.';
    if (RELAY.test(email) || /@koywe-test\.com$/i.test(email)) return 'Usa un correo real, no uno oculto de Apple.';
  }
  if (!needs.country) return 'No pude identificar tu país. Abre la pantalla para elegirlo.';
  return '';
}

export function AddressForm({ label, onSaved, onOpenScreen, bare }: {
  label: string;
  /** The address is saved: whoever asked for it can go on. */
  onSaved?: () => void;
  /** Opens "Dirección y teléfono" (another country, or a phone to add). */
  onOpenScreen: () => void;
  /** Inside another card (the top-up form): no frame of its own. */
  bare?: boolean;
}) {
  const { userProfile } = useAuth() as any;
  const { data, loading } = useQuery(GET_MY_RAMP_ADDRESS, { fetchPolicy: 'cache-and-network' });
  const { data: phoneData, loading: phoneLoading } = useQuery(GET_RAMP_PHONE_STATUS, { fetchPolicy: 'cache-and-network' });
  const [save] = useMutation(UPSERT_RAMP_USER_ADDRESS);
  const address = data?.myRampAddress;
  const phoneStatus = phoneData?.myRampPhoneStatus;
  const countryIso: string = phoneStatus?.addressCountryIso || toIso2(address?.addressCountry || '') || userCountryIso(userProfile) || '';
  const { data: requirementsData } = useQuery(GET_RAMP_ADDRESS_REQUIREMENTS, {
    variables: { countryCode: countryIso }, skip: !countryIso,
  });
  // A rail in the person's country can need the field even when the address
  // is elsewhere: Mexican orders always ask for the colonia.
  const picked = requirementsData?.rampAddressRequirements;
  const requirements = picked?.requiresAddressNeighborhood || !data?.rampAddressRequirements ? picked : data.rampAddressRequirements;
  const needsNeighborhood = Boolean(requirements?.requiresAddressNeighborhood);
  const neighborhoodLabel: string = requirements?.addressNeighborhoodLabel || 'Colonia o barrio';
  const activities: Activity[] = data?.economicActivities || [];
  const needsActivity = activities.length > 0;
  const accountEmail = String(userProfile?.email || '').trim().toLowerCase();
  const needsEmail = countryIso === 'CO' && RELAY.test(accountEmail);
  // The screen asks for the phone where the provider needs one: a missing one is added there.
  const phoneMissing = Boolean(phoneStatus) && !phoneStatus?.contactPhone;

  const [values, setValues] = useState({ street: '', neighborhood: '', city: '', state: '', zip: '', activity: '', email: '' });
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (loaded || !data) return;
    setLoaded(true);
    setValues({
      street: address?.addressStreet || '', neighborhood: address?.addressNeighborhood || '', city: address?.addressCity || '',
      state: address?.addressState || '',
      // Bolivia has no postal codes in everyday use, but the provider needs the field.
      zip: address?.addressZipCode || (countryIso === 'BO' ? '0000' : ''),
      activity: address?.economicActivity || '', email: address?.authEmail || '',
    });
  }, [loaded, data, address, countryIso]);
  const set = (key: keyof typeof values, value: string) => {
    setError('');
    setValues((prev) => ({ ...prev, [key]: value }));
  };
  const matches = useMemo(() => {
    const query = search.trim().toLowerCase();
    return !query || values.activity ? [] : activities.filter((a) => a.label.toLowerCase().includes(query)).slice(0, 5);
  }, [search, values.activity, activities]);

  const submit = async () => {
    if (busy || done) return;
    const problem = addressProblem(values, {
      neighborhood: needsNeighborhood, neighborhoodLabel, activity: needsActivity, email: needsEmail, country: !!countryIso,
    });
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const { data: response } = await save({
        variables: {
          addressStreet: values.street.trim(),
          addressNeighborhood: needsNeighborhood ? values.neighborhood.trim() : undefined,
          addressCity: values.city.trim(),
          addressState: values.state.trim(),
          addressZipCode: values.zip.trim(),
          economicActivity: needsActivity ? values.activity.trim() : undefined,
          authEmail: needsEmail ? values.email.trim().toLowerCase() : undefined,
          addressCountry: countryIso || undefined,
        },
        refetchQueries: [{ query: GET_MY_RAMP_ADDRESS }, { query: GET_RAMP_PHONE_STATUS }],
        awaitRefetchQueries: true,
      });
      const result = response?.upsertRampUserAddress;
      if (!result?.success) {
        setError(result?.error || 'No se pudo guardar tu dirección.');
        return;
      }
      void AnalyticsService.logEvent('ramp_profile_completed', {
        provider: 'koywe', country: countryIso || '', has_auth_email: needsEmail, surface: 'chat',
      });
      setDone(true);
      onSaved?.();
    } catch (_e) {
      setError('No se pudo guardar tu dirección. Inténtalo de nuevo.');
    } finally {
      setBusy(false);
    }
  };

  const frame = bare ? styles.bare : styles.card;
  if (done) {
    return (
      <View style={[frame, styles.line]} accessible accessibilityLabel="Listo: guardé tu dirección">
        <Icon name="check-circle" size={18} color={EMERALD} />
        <Text style={styles.doneText}>Listo: guardé tu dirección</Text>
      </View>
    );
  }
  if ((loading && !data) || (phoneLoading && !phoneData)) {
    return (
      <View style={[frame, styles.line]}>
        <ActivityIndicator size="small" color={EMERALD} />
        <Text style={styles.lineText}>Preparando…</Text>
      </View>
    );
  }
  if (phoneMissing || !countryIso) {
    return (
      <View style={frame}>
        <Text style={styles.title}>{label}</Text>
        <Text style={styles.body}>
          {phoneMissing ? 'Falta también tu número de celular: se completa junto con la dirección en su pantalla.'
            : 'No pude identificar tu país: elígelo en la pantalla de tu dirección.'}
        </Text>
        <Pressable onPress={onOpenScreen} style={styles.submit} accessibilityRole="button" accessibilityLabel="Abrir Dirección y teléfono">
          <Text style={styles.submitText}>Abrir Dirección y teléfono</Text>
        </Pressable>
      </View>
    );
  }
  const field = (key: keyof typeof values, text: string, placeholder: string, extra: Record<string, unknown> = {}) => (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{text}</Text>
      <TextInput style={styles.input} value={values[key]} onChangeText={(value: string) => set(key, value)}
        placeholder={placeholder} placeholderTextColor="#6B7280" autoCorrect={false} editable={!busy}
        accessibilityLabel={text} {...extra} />
    </View>
  );
  return (
    <View style={frame}>
      <Text style={styles.title}>{label}</Text>
      {field('street', 'Dirección', 'Calle y número')}
      {needsNeighborhood ? field('neighborhood', neighborhoodLabel, requirements?.addressNeighborhoodPlaceholder || neighborhoodLabel) : null}
      {field('city', 'Ciudad', 'Ciudad')}
      {field('state', 'Provincia o estado', 'Provincia o estado')}
      {field('zip', 'Código postal', 'Código postal')}
      {countryIso === 'BO' ? <Text style={styles.hint}>En Bolivia puedes dejar 0000.</Text> : null}
      {needsActivity ? (
        <View style={styles.field}>
          <Text style={styles.fieldLabel}>Actividad económica</Text>
          <TextInput
            style={styles.input}
            value={values.activity || search}
            onChangeText={(value: string) => {
              setError('');
              setSearch(value);
              setValues((prev) => ({ ...prev, activity: '' }));
            }}
            placeholder="Escribe para buscar"
            placeholderTextColor="#6B7280"
            autoCapitalize="none"
            autoCorrect={false}
            editable={!busy}
            accessibilityLabel="Actividad económica"
          />
          {matches.length ? (
            <View style={styles.options}>
              {matches.map((a) => (
                <Pressable key={a.value} onPress={() => { set('activity', a.value); setSearch(a.label); }} style={styles.option}
                  accessibilityRole="button" accessibilityLabel={`Elegir ${a.label}`}>
                  <Text style={styles.optionText} numberOfLines={2}>{a.label}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
        </View>
      ) : null}
      {needsEmail ? field('email', 'Tu correo (el banco te escribe ahí)', 'nombre@correo.com',
        { keyboardType: 'email-address', autoCapitalize: 'none' }) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable onPress={() => void submit()} disabled={busy}
        style={({ pressed }) => [styles.submit, pressed && styles.submitPressed]}
        accessibilityRole="button" accessibilityState={{ busy }} accessibilityLabel="Guardar mi dirección">
        {busy ? <ActivityIndicator size="small" color="#FFFFFF" /> : <Text style={styles.submitText}>Guardar mi dirección</Text>}
      </Pressable>
      <Pressable onPress={onOpenScreen} style={styles.second} accessibilityRole="button" accessibilityLabel="Cambiar país o teléfono">
        <Text style={styles.secondText}>Cambiar país o teléfono</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 4, marginBottom: 4, maxWidth: 340, padding: 14, borderRadius: 16,
    borderWidth: 1, borderColor: '#A7F3D0', backgroundColor: '#FFFFFF',
  },
  bare: { marginTop: 12, paddingTop: 12, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: '#D1D5DB' },
  line: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  lineText: { fontSize: 15, color: INK },
  doneText: { flex: 1, fontSize: 15, fontWeight: '600', color: EMERALD },
  title: { fontSize: 15, fontWeight: '700', color: INK },
  body: { fontSize: 14, lineHeight: 20, color: INK, marginTop: 10 },
  field: { marginTop: 10 },
  fieldLabel: { fontSize: 13, color: MUTED, marginBottom: 4 },
  hint: { fontSize: 12, color: MUTED, marginTop: 4 },
  input: {
    minHeight: 46, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16, color: INK,
    backgroundColor: '#F3F4F6',
  },
  options: { marginTop: 6, gap: 6 },
  option: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 12, paddingVertical: 8, borderRadius: 12, borderWidth: 1, borderColor: '#D1D5DB' },
  optionText: { fontSize: 15, color: INK },
  error: { fontSize: 13, lineHeight: 18, color: '#B91C1C', marginTop: 10 },
  submit: { marginTop: 14, height: 48, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: EMERALD },
  submitPressed: { backgroundColor: '#065F46' },
  submitText: { fontSize: 16, fontWeight: '700', color: '#FFFFFF' },
  second: { marginTop: 6, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  secondText: { fontSize: 15, fontWeight: '600', color: MUTED },
});
