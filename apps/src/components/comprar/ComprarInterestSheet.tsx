import React, { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useMutation } from '@apollo/client';
import { Text, TextInput } from '../common/AppText';
import { colors } from '../../config/theme';
import { SUBMIT_MARKETPLACE_INTEREST, comprarError } from '../../services/comprar';
import { CategoryPicker, MarketCategory } from './CategoryPicker';

type Role = 'buyer' | 'seller' | 'both';

const ROLES: { key: Role; label: string }[] = [
  { key: 'buyer', label: 'Comprar' },
  { key: 'seller', label: 'Vender' },
  { key: 'both', label: 'Ambos' },
];
// US dollars, so cities compare across inflationary currencies.
const PRICES = [
  { key: 'lt10', label: 'Menos de US$10' },
  { key: '10_30', label: 'US$10–30' },
  { key: '30_100', label: 'US$30–100' },
  { key: '100_300', label: 'US$100–300' },
  { key: 'gt300', label: 'Más de US$300' },
];
const SALES = [
  { key: 'none', label: 'Aún no vendo' },
  { key: 'lt200', label: 'Menos de US$200' },
  { key: '200_1000', label: 'US$200–1.000' },
  { key: '1000_5000', label: 'US$1.000–5.000' },
  { key: 'gt5000', label: 'Más de US$5.000' },
];
const CHANNELS = [
  { key: 'instagram', label: 'Instagram' },
  { key: 'whatsapp', label: 'WhatsApp' },
  { key: 'facebook', label: 'Facebook' },
  { key: 'tiktok', label: 'TikTok' },
  { key: 'feria', label: 'Ferias' },
  { key: 'local', label: 'Local propio' },
  { key: 'delivery_app', label: 'Apps de delivery' },
  { key: 'other', label: 'Otro' },
];

type Props = {
  visible: boolean;
  countryCode: string;
  city: string;
  categories: MarketCategory[];
  onClose: () => void;
  onDone: (notify: boolean) => void;
};

/**
 * The fake door's probe for a city Comprar has not opened yet: buy or sell,
 * what, at what price, and — for sellers — how much they sell today and
 * where. One short screen; every answer is optional except the role.
 */
export const ComprarInterestSheet = ({ visible, countryCode, city, categories, onClose, onDone }: Props) => {
  const [role, setRole] = useState<Role | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [wants, setWants] = useState('');
  const [price, setPrice] = useState<string | null>(null);
  const [sales, setSales] = useState<string | null>(null);
  const [channels, setChannels] = useState<string[]>([]);
  const [notify, setNotify] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const attempt = React.useRef(0);
  // Leaving (unmount, or a re-key for another city) supersedes any pending send.
  React.useEffect(() => () => { attempt.current += 1; }, []);
  const [submit] = useMutation(SUBMIT_MARKETPLACE_INTEREST);
  const selling = role === 'seller' || role === 'both';

  const toggle = (list: string[], key: string, set: (v: string[]) => void) =>
    set(list.includes(key) ? list.filter((k) => k !== key) : [...list, key]);

  const send = async () => {
    if (!role) return;
    setError(null);
    setLoading(true);
    const mine = ++attempt.current;
    // Bounded: a request that never answers must not leave "Enviar" disabled.
    // The answer is idempotent (one row per user and city), so a retry is safe.
    const stop = new Promise<'timeout'>((resolve) => setTimeout(() => resolve('timeout'), 15_000));
    try {
      const res: any = await Promise.race([submit({ variables: {
        countryCode, city, role, categories: picked, wants: wants.trim(), priceRange: price || '',
        monthlySales: selling ? sales || '' : '', channels: selling ? channels : [], notify,
      } }), stop]);
      if (mine !== attempt.current) return;  // superseded
      if (res === 'timeout') {
        setError('No pudimos enviar tus respuestas. Inténtalo de nuevo.');
        return;
      }
      if (!res.data?.submitMarketplaceInterest?.success) {
        setError(comprarError(res.data?.submitMarketplaceInterest?.error));
        return;
      }
      onDone(notify);
    } catch {
      if (mine === attempt.current) setError(comprarError());
    } finally {
      if (mine === attempt.current) setLoading(false);
    }
  };

  const chips = (items: { key: string; label: string }[], isOn: (k: string) => boolean, onPress: (k: string) => void) => (
    <View style={styles.chips}>
      {items.map((i) => (
        <Pressable key={i.key} onPress={() => onPress(i.key)} style={[styles.chip, isOn(i.key) && styles.chipOn]}
          accessibilityRole="button" accessibilityState={{ selected: isOn(i.key) }}>
          <Text style={[styles.chipText, isOn(i.key) && styles.chipTextOn]}>{i.label}</Text>
        </Pressable>
      ))}
    </View>
  );

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.sheet}>
          <View style={styles.headerRow}>
            <Text style={styles.title}>Comprar en {city}</Text>
            <Pressable onPress={onClose} accessibilityLabel="Cerrar"><Icon name="x" size={22} color={colors.text.primary} /></Pressable>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 12, paddingBottom: 12 }}>
            <Text style={styles.lead}>Cuéntanos qué buscas y abriremos primero donde más se necesita.</Text>

            <Text style={styles.q}>¿Qué te gustaría hacer?</Text>
            {chips(ROLES, (k) => role === k, (k) => setRole(k as Role))}

            {role ? (
              <>
                <Text style={styles.q}>{selling ? '¿Qué vendes?' : '¿Qué te gustaría comprar?'}</Text>
                <CategoryPicker categories={categories} selected={picked} multiple max={10}
                  onToggle={(k) => toggle(picked, k, setPicked)} />
                <TextInput style={styles.input} placeholder={selling ? 'Ej.: chompas de alpaca, mermeladas caseras' : 'Ej.: ropa tejida, regalos, comida envasada'}
                  placeholderTextColor={colors.text.light} value={wants} onChangeText={setWants} maxLength={300} />

                <Text style={styles.q}>{selling ? '¿A qué precio vendes cada producto?' : '¿Cuánto pagarías normalmente por producto?'}</Text>
                {chips(PRICES, (k) => price === k, (k) => setPrice(price === k ? null : k))}

                {selling ? (
                  <>
                    <Text style={styles.q}>¿Cuánto vendes al mes hoy?</Text>
                    {chips(SALES, (k) => sales === k, (k) => setSales(sales === k ? null : k))}
                    <Text style={styles.q}>¿Dónde vendes hoy?</Text>
                    {chips(CHANNELS, (k) => channels.includes(k), (k) => toggle(channels, k, setChannels))}
                  </>
                ) : null}

                <View style={styles.notifyRow}>
                  <Text style={styles.notifyText}>Avísame cuando Comprar llegue a {city}</Text>
                  <Switch value={notify} onValueChange={setNotify} />
                </View>
              </>
            ) : null}
            {error ? <Text style={styles.error}>{error}</Text> : null}
          </ScrollView>
          <Pressable style={[styles.primary, (!role || loading) && styles.disabled]} disabled={!role || loading}
            onPress={() => { void send(); }}>
            {loading ? <ActivityIndicator color={colors.white} /> : <Text style={styles.primaryText}>Enviar</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.35)' },
  sheet: { backgroundColor: colors.white, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, paddingBottom: 28, maxHeight: '90%' },
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  title: { fontSize: 18, fontWeight: '700', color: colors.textFlat },
  lead: { fontSize: 14, color: colors.text.secondary, lineHeight: 20 },
  q: { fontSize: 14, fontWeight: '700', color: colors.textFlat, marginTop: 4 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: '#E5E7EB', backgroundColor: colors.white },
  chipOn: { backgroundColor: colors.textFlat, borderColor: colors.textFlat },
  chipText: { fontSize: 13, color: colors.text.primary },
  chipTextOn: { color: colors.white, fontWeight: '600' },
  input: { borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, color: colors.text.primary },
  notifyRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginTop: 4 },
  notifyText: { flex: 1, fontSize: 14, color: colors.text.primary },
  error: { color: colors.error.text, fontSize: 14 },
  primary: { backgroundColor: colors.primaryDark, borderRadius: 14, paddingVertical: 15, alignItems: 'center', marginTop: 8 },
  primaryText: { color: colors.white, fontWeight: '700', fontSize: 16 },
  disabled: { backgroundColor: '#D1D5DB' },
});
