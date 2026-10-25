import React, { useCallback, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  SectionList,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useApolloClient } from '@apollo/client';
import { useFocusEffect, useNavigation } from '@react-navigation/native';

import { Text, TextInput } from '../components/common/AppText';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';
import { CountryFlag } from '../components/CountryFlag';
import { VE_BANKS } from '../services/vePagoMovilTopUp';
import {
  AGENDA_ENTRIES,
  AGENDA_RECENTS,
  AgendaEntry,
  AgendaRecent,
  AgendaRelationship,
  BANK_INFO_RAIL,
  DELETE_AGENDA_ENTRY,
  RAIL_NAMES,
  SAVE_DESTINATION_TO_AGENDA,
  SAVE_VE_AGENDA_ENTRY,
  UPDATE_AGENDA_ENTRY,
  VE_PAGOMOVIL_RAIL,
  localVePhone,
  useAgendaAccountKey,
} from '../services/agenda';

const GENERIC = 'No pudimos conectar. Intenta de nuevo en unos segundos.';
const COUNTRY_NAMES: Record<string, string> = {
  VE: 'Venezuela', CO: 'Colombia', MX: 'México', AR: 'Argentina', BR: 'Brasil', PE: 'Perú', BO: 'Bolivia',
  CL: 'Chile', EC: 'Ecuador', US: 'Estados Unidos',
};

type Bank = { code: string; name: string };
type Row = { kind: 'entry'; entry: AgendaEntry } | { kind: 'recent'; recent: AgendaRecent };
type Section = { key: string; title: string; data: Row[] };

interface VeForm {
  id?: string;
  label: string;
  relationship: AgendaRelationship;
  holderName: string;
  cedula: string;
  phone: string;
  bank: Bank | null;
}

const emptyVeForm = (): VeForm =>
  ({ label: '', relationship: 'third_party', holderName: '', cedula: '', phone: '', bank: null });

const byCountry = (a: AgendaEntry, b: AgendaEntry) =>
  (a.country || 'ZZ').localeCompare(b.country || 'ZZ') || Number(b.isDefault) - Number(a.isDefault)
  || a.label.localeCompare(b.label);

/**
 * Agenda: the person's saved accounts. "Mis cuentas" are theirs (including the
 * Koywe Retiro accounts, still managed in Mis cuentas); "Otras personas" may be
 * saved where the rail allows it (Venezuelan Pago Móvil, local sends);
 * "Recientes" are past local-send recipients one tap away from being saved.
 */
export default function AgendaScreen() {
  const client = useApolloClient();
  const navigation = useNavigation<any>();
  // Another account's entries must never linger after a switch.
  const accountKey = useAgendaAccountKey();
  const seq = useRef(0);
  const [entries, setEntries] = useState<AgendaEntry[]>([]);
  const [recents, setRecents] = useState<AgendaRecent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState<VeForm | null>(null);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [bankPicker, setBankPicker] = useState(false);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setError('');
    setEntries([]);
    setRecents([]);
    if (!accountKey) return;
    try {
      const [list, recent] = await Promise.all([
        client.query({ query: AGENDA_ENTRIES, fetchPolicy: 'network-only' }),
        client.query({ query: AGENDA_RECENTS, fetchPolicy: 'network-only' }).catch(() => null),
      ]);
      if (mine !== seq.current) return;
      setEntries(list.data?.agendaEntries || []);
      setRecents(recent?.data?.agendaRecents || []);
    } catch {
      if (mine === seq.current) setError(GENERIC);
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [client, accountKey]);

  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const sections = useMemo<Section[]>(() => {
    const own = entries.filter(e => e.relationship === 'own').sort(byCountry);
    const others = entries.filter(e => e.relationship !== 'own').sort(byCountry);
    const result: Section[] = [
      { key: 'own', title: 'Mis cuentas', data: own.map(entry => ({ kind: 'entry', entry }) as Row) },
      { key: 'others', title: 'Otras personas', data: others.map(entry => ({ kind: 'entry', entry }) as Row) },
    ];
    if (recents.length) {
      result.push({ key: 'recents', title: 'Recientes', data: recents.map(recent => ({ kind: 'recent', recent }) as Row) });
    }
    return result;
  }, [entries, recents]);

  const mutate = async (run: () => Promise<any>, field: string) => {
    try {
      const { data } = await run();
      const result = data?.[field];
      if (!result?.success) {
        Alert.alert('No pudimos guardar el cambio', result?.errors?.[0] || GENERIC);
        return false;
      }
      await load();
      return true;
    } catch {
      Alert.alert('No pudimos guardar el cambio', GENERIC);
      return false;
    }
  };

  const remove = (entry: AgendaEntry) => Alert.alert('Eliminar de tu Agenda', entry.label, [
    { text: 'Cancelar', style: 'cancel' },
    {
      text: 'Eliminar', style: 'destructive',
      onPress: () => { void mutate(() => client.mutate({ mutation: DELETE_AGENDA_ENTRY, variables: { id: entry.id } }), 'deleteAgendaEntry'); },
    },
  ]);

  const switchRelationship = (entry: AgendaEntry) => {
    const relationship: AgendaRelationship = entry.relationship === 'own' ? 'third_party' : 'own';
    void mutate(() => client.mutate({
      mutation: UPDATE_AGENDA_ENTRY, variables: { id: entry.id, label: entry.label, relationship },
    }), 'updateAgendaEntry');
  };

  const openVeForm = async (entry?: AgendaEntry) => {
    setFormError('');
    if (!banks.length) {
      try {
        const { data } = await client.query({ query: VE_BANKS, fetchPolicy: 'cache-first' });
        setBanks(data?.vePagomovilBanks || []);
        const found = (data?.vePagomovilBanks || []).find((b: Bank) => b.code === entry?.bankCode) || null;
        setForm(entry ? veFormFrom(entry, found) : emptyVeForm());
        return;
      } catch {
        // The bank list is ours; a failure only means the picker retries.
      }
    }
    setForm(entry ? veFormFrom(entry, banks.find(b => b.code === entry.bankCode) || null) : emptyVeForm());
  };

  const reloadBanks = async () => {
    try {
      const { data } = await client.query({ query: VE_BANKS, fetchPolicy: 'network-only' });
      setBanks(data?.vePagomovilBanks || []);
    } catch {
      // The empty picker keeps its retry button.
    }
  };

  const openBankPicker = () => {
    setBankPicker(true);
    if (!banks.length) void reloadBanks();
  };

  const onEntry = (entry: AgendaEntry) => {
    if (entry.rail === BANK_INFO_RAIL) {
      navigation.navigate('PayoutMethods');
      return;
    }
    if (entry.rail === VE_PAGOMOVIL_RAIL) {
      Alert.alert(entry.label, entry.subtitle, [
        { text: 'Cancelar', style: 'cancel' },
        { text: 'Editar', onPress: () => { void openVeForm(entry); } },
        { text: 'Eliminar', style: 'destructive', onPress: () => remove(entry) },
      ]);
      return;
    }
    // Android shows at most three buttons (Cancelar included): Enviar first,
    // then the rest one level down.
    const manage = () => Alert.alert(entry.label, entry.subtitle, [
      { text: 'Cancelar', style: 'cancel' },
      { text: entry.relationship === 'own' ? 'Es de otra persona' : 'Es mía', onPress: () => switchRelationship(entry) },
      { text: 'Eliminar', style: 'destructive', onPress: () => remove(entry) },
    ]);
    if (!entry.destinationId) {
      manage();
      return;
    }
    Alert.alert(entry.label, entry.subtitle, [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Enviar', onPress: () => navigation.navigate('LocalSend', { methodId: entry.rail, destinationId: entry.destinationId }),
      },
      { text: 'Más opciones', onPress: manage },
    ]);
  };

  const saveRecent = (recent: AgendaRecent) => Alert.alert('Guardar en mi Agenda', '¿De quién es esta cuenta?', [
    { text: 'Cancelar', style: 'cancel' },
    ...(['own', 'third_party'] as AgendaRelationship[]).map(relationship => ({
      text: relationship === 'own' ? 'Es mía' : 'De otra persona',
      onPress: () => {
        void mutate(() => client.mutate({
          mutation: SAVE_DESTINATION_TO_AGENDA, variables: { destinationId: recent.destinationId, relationship },
        }), 'saveDestinationToAgenda');
      },
    })),
  ]);

  const submitVe = async () => {
    if (!form || saving) return;
    if (!form.bank) {
      setFormError('Elige el banco.');
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      const { data } = await client.mutate({
        mutation: SAVE_VE_AGENDA_ENTRY,
        variables: {
          id: form.id, label: form.label.trim(), relationship: form.relationship,
          holderName: form.holderName.trim(), cedula: form.cedula.trim(), phone: form.phone.trim(),
          bankCode: form.bank.code,
        },
        fetchPolicy: 'no-cache',
      });
      const result = data?.saveVePagomovilAgendaEntry;
      if (!result?.success) {
        setFormError(result?.errors?.[0] || GENERIC);
        return;
      }
      setForm(null);
      await load();
    } catch {
      setFormError(GENERIC);
    } finally {
      setSaving(false);
    }
  };

  const addAccount = () => Alert.alert('Agregar a tu Agenda', undefined, [
    { text: 'Cancelar', style: 'cancel' },
    { text: 'Pago Móvil (Venezuela)', onPress: () => { void openVeForm(); } },
    { text: 'Cuenta para retiros', onPress: () => navigation.navigate('PayoutMethods') },
  ]);

  const renderRow = ({ item, index, section }: { item: Row; index: number; section: Section }) => {
    if (item.kind === 'recent') {
      const { recent } = item;
      return (
        <View style={styles.row}>
          <CountryFlag iso={recent.country} size={22} />
          <View style={styles.flex}>
            <Text style={styles.rowTitle} numberOfLines={1}>{recent.holderName || recent.label}</Text>
            <Text style={styles.rowSubtitle} numberOfLines={1}>
              {[RAIL_NAMES[recent.rail], recent.holderName ? recent.label : ''].filter(Boolean).join(' · ')}
            </Text>
          </View>
          <TouchableOpacity accessibilityRole="button" accessibilityLabel={`Guardar ${recent.label}`}
            onPress={() => saveRecent(recent)} style={styles.saveButton}>
            <Icon name="bookmark" size={14} color={colors.primaryDark} />
            <Text style={styles.saveButtonText}>Guardar</Text>
          </TouchableOpacity>
        </View>
      );
    }
    const { entry } = item;
    const previous = section.data[index - 1];
    const firstOfCountry = !previous || previous.kind !== 'entry' || previous.entry.country !== entry.country;
    return (
      <>
        {firstOfCountry ? (
          <Text style={styles.countryHeader}>{COUNTRY_NAMES[entry.country] || entry.country || 'Otros'}</Text>
        ) : null}
        <TouchableOpacity accessibilityRole="button" style={styles.row} onPress={() => onEntry(entry)}>
          <CountryFlag iso={entry.country} size={22} />
          <View style={styles.flex}>
            <Text style={styles.rowTitle} numberOfLines={1}>{entry.label}</Text>
            <Text style={styles.rowSubtitle} numberOfLines={1}>
              {[RAIL_NAMES[entry.rail] || entry.rail, entry.relationship === 'own' ? '' : entry.holderName, entry.subtitle]
                .filter(Boolean).join(' · ')}
            </Text>
          </View>
          {entry.isDefault ? <Text style={styles.defaultPill}>Principal</Text> : null}
          <Icon name="chevron-right" size={18} color={colors.textSecondary} />
        </TouchableOpacity>
      </>
    );
  };

  return (
    // Header pads for the status bar itself (a SafeAreaView here doubles it).
    <View style={styles.container}>
      <Header navigation={navigation} title="Agenda" backgroundColor={colors.heroField} isLight showBackButton />
      {loading ? (
        <ActivityIndicator style={styles.loader} color={colors.primary} />
      ) : (
        <SectionList
          sections={sections}
          keyExtractor={item => (item.kind === 'entry' ? item.entry.id : `recent-${item.recent.destinationId}`)}
          renderItem={renderRow}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          stickySectionHeadersEnabled={false}
          refreshControl={<RefreshControl refreshing={false} onRefresh={() => { void load(); }} />}
          ListHeaderComponent={(
            <View style={styles.intro}>
              <Text style={styles.introText}>
                Tus cuentas y las de las personas a quienes envías, listas para usar en recargas, retiros y envíos.
              </Text>
              {error ? <Text style={styles.error}>{error}</Text> : null}
            </View>
          )}
          renderSectionHeader={({ section }) => (
            <Text style={styles.sectionTitle}>{section.title}</Text>
          )}
          renderSectionFooter={({ section }) => (section.data.length ? null : (
            <Text style={styles.empty}>
              {section.key === 'own' ? 'Aún no guardas cuentas tuyas.' : 'Aún no guardas cuentas de otras personas.'}
            </Text>
          ))}
          ListFooterComponent={(
            <TouchableOpacity accessibilityRole="button" style={styles.addButton} onPress={addAccount}>
              <Icon name="plus" size={18} color={colors.white} />
              <Text style={styles.addButtonText}>Agregar cuenta</Text>
            </TouchableOpacity>
          )}
          contentContainerStyle={styles.content}
        />
      )}

      {/* Not closable mid-save: the answer would close whatever form is open next. */}
      <Modal visible={!!form} animationType="slide" onRequestClose={() => { if (!saving) setForm(null); }}>
        <SafeAreaView style={styles.container}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>{form?.id ? 'Editar Pago Móvil' : 'Nuevo Pago Móvil'}</Text>
            <TouchableOpacity accessibilityRole="button" accessibilityLabel="Cerrar" disabled={saving}
              onPress={() => setForm(null)}>
              <Icon name="x" size={24} color={colors.dark} />
            </TouchableOpacity>
          </View>
          {form ? (
            <ScrollView contentContainerStyle={styles.formContent} keyboardShouldPersistTaps="handled">
              <View style={styles.segment}>
                {(['own', 'third_party'] as AgendaRelationship[]).map(option => (
                  <TouchableOpacity key={option} accessibilityRole="button"
                    accessibilityState={{ selected: form.relationship === option }}
                    onPress={() => setForm({ ...form, relationship: option })}
                    style={[styles.segmentItem, form.relationship === option && styles.segmentActive]}>
                    <Text style={[styles.segmentText, form.relationship === option && styles.segmentTextActive]}>
                      {option === 'own' ? 'Es mía' : 'De otra persona'}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
              {form.relationship === 'third_party' ? (
                <>
                  <Text style={styles.label}>Nombre de la persona</Text>
                  <TextInput value={form.holderName} onChangeText={holderName => setForm({ ...form, holderName })}
                    placeholder="María Pérez" placeholderTextColor={colors.textTertiary} style={styles.input} />
                </>
              ) : null}
              <Text style={styles.label}>Cédula</Text>
              <TextInput value={form.cedula} onChangeText={cedula => setForm({ ...form, cedula })}
                autoCapitalize="characters" placeholder="V12345678" placeholderTextColor={colors.textTertiary}
                style={styles.input} />
              <Text style={styles.label}>Teléfono del Pago Móvil</Text>
              <TextInput value={form.phone} onChangeText={phone => setForm({ ...form, phone })} keyboardType="phone-pad"
                placeholder="0414 1234567" placeholderTextColor={colors.textTertiary} style={styles.input} />
              <Text style={styles.label}>Banco</Text>
              <TouchableOpacity accessibilityRole="button" style={[styles.input, styles.picker]}
                onPress={openBankPicker}>
                <Text style={form.bank ? styles.pickerValue : styles.pickerPlaceholder} numberOfLines={1}>
                  {form.bank ? form.bank.name : 'Elige el banco'}
                </Text>
                <Icon name="chevron-down" size={18} color={colors.textSecondary} />
              </TouchableOpacity>
              <Text style={styles.label}>Nombre en tu Agenda (opcional)</Text>
              <TextInput value={form.label} onChangeText={label => setForm({ ...form, label })}
                placeholder="Mamá, Mi Banesco…" placeholderTextColor={colors.textTertiary} style={styles.input} />
              {formError ? <Text style={styles.error}>{formError}</Text> : null}
              <TouchableOpacity accessibilityRole="button" style={[styles.addButton, saving && styles.disabled]}
                onPress={() => { void submitVe(); }} disabled={saving}>
                {saving ? <ActivityIndicator color={colors.white} /> : <Text style={styles.addButtonText}>Guardar</Text>}
              </TouchableOpacity>
            </ScrollView>
          ) : null}
        </SafeAreaView>
        <Modal visible={bankPicker} animationType="slide" onRequestClose={() => setBankPicker(false)}>
          <SafeAreaView style={styles.container}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Elige el banco</Text>
              <TouchableOpacity accessibilityRole="button" accessibilityLabel="Cerrar" onPress={() => setBankPicker(false)}>
                <Icon name="x" size={24} color={colors.dark} />
              </TouchableOpacity>
            </View>
            <FlatList
              data={banks}
              keyExtractor={item => item.code}
              initialNumToRender={20}
              maxToRenderPerBatch={10}
              windowSize={21}
              getItemLayout={(_, index) => ({ length: BANK_ROW, offset: BANK_ROW * index, index })}
              ListEmptyComponent={(
                <View style={styles.intro}>
                  <Text style={styles.introText}>No pudimos cargar los bancos.</Text>
                  <TouchableOpacity accessibilityRole="button" style={styles.addButton} onPress={() => { void reloadBanks(); }}>
                    <Text style={styles.addButtonText}>Reintentar</Text>
                  </TouchableOpacity>
                </View>
              )}
              renderItem={({ item }) => (
                <TouchableOpacity accessibilityRole="button" style={styles.bankRow}
                  onPress={() => { if (form) setForm({ ...form, bank: item }); setBankPicker(false); }}>
                  <Text style={styles.pickerValue} numberOfLines={1}>{item.name}</Text>
                  {form?.bank?.code === item.code ? <Icon name="check" size={18} color={colors.primaryDark} /> : null}
                </TouchableOpacity>
              )}
            />
          </SafeAreaView>
        </Modal>
      </Modal>
    </View>
  );
}

const veFormFrom = (entry: AgendaEntry, bank: Bank | null): VeForm => ({
  id: entry.id,
  label: entry.label,
  relationship: entry.relationship,
  holderName: entry.holderName,
  cedula: entry.cedula || '',
  phone: localVePhone(entry.phone),
  bank,
});

const BANK_ROW = 56;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.white },
  flex: { flex: 1 },
  loader: { marginTop: 40 },
  content: { paddingBottom: 40 },
  intro: { paddingHorizontal: 20, paddingTop: 16 },
  introText: { fontSize: 14, color: colors.textSecondary, lineHeight: 20 },
  error: { fontSize: 14, color: colors.error?.text || '#B91C1C', marginTop: 10 },
  sectionTitle: { fontSize: 17, fontWeight: '700', color: colors.dark, paddingHorizontal: 20, marginTop: 24, marginBottom: 4 },
  countryHeader: {
    fontSize: 12, fontWeight: '700', color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: 0.5,
    paddingHorizontal: 20, marginTop: 12, marginBottom: 2,
  },
  empty: { fontSize: 14, color: colors.textTertiary, paddingHorizontal: 20, paddingVertical: 8 },
  row: {
    minHeight: 64, paddingHorizontal: 20, paddingVertical: 10, flexDirection: 'row', alignItems: 'center', gap: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  rowTitle: { fontSize: 16, fontWeight: '600', color: colors.dark },
  rowSubtitle: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
  defaultPill: {
    fontSize: 11, fontWeight: '700', color: colors.primaryDark, backgroundColor: colors.primaryLight,
    borderRadius: 8, paddingHorizontal: 8, paddingVertical: 3, overflow: 'hidden',
  },
  saveButton: {
    flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderColor: colors.primaryDark,
    borderRadius: 10, paddingHorizontal: 10, paddingVertical: 6,
  },
  saveButtonText: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },
  addButton: {
    marginHorizontal: 20, marginTop: 24, minHeight: 52, borderRadius: 14, backgroundColor: colors.primaryDark,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
  },
  addButtonText: { fontSize: 16, fontWeight: '700', color: colors.white },
  disabled: { opacity: 0.6 },
  modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 20 },
  modalTitle: { fontSize: 20, fontWeight: '700', color: colors.dark },
  formContent: { paddingHorizontal: 20, paddingBottom: 40 },
  label: { fontSize: 14, fontWeight: '600', color: colors.textSecondary, marginTop: 16, marginBottom: 6 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, minHeight: 48,
    fontSize: 16, color: colors.dark, backgroundColor: colors.white,
  },
  picker: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  pickerValue: { fontSize: 16, fontWeight: '600', color: colors.dark, flexShrink: 1 },
  pickerPlaceholder: { fontSize: 16, color: colors.textTertiary },
  segment: { flexDirection: 'row', gap: 8 },
  segmentItem: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingVertical: 10, alignItems: 'center',
  },
  segmentActive: { borderColor: colors.primaryDark, backgroundColor: colors.primaryLight },
  segmentText: { fontSize: 14, fontWeight: '600', color: colors.textSecondary },
  segmentTextActive: { color: colors.primaryDark },
  bankRow: {
    height: BANK_ROW, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
});
