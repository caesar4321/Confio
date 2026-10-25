import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, Modal, Platform, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import MCIcon from 'react-native-vector-icons/MaterialCommunityIcons';
import { ApolloClient, useApolloClient } from '@apollo/client';

import { Text, TextInput } from '../common/AppText';
import { colors } from '../../config/theme';
import { CountryFlag } from '../CountryFlag';
import {
  AGENDA_ENTRIES,
  AgendaEntry,
  AgendaRelationship,
  SAVE_VE_AGENDA_ENTRY,
  VE_PAGOMOVIL_RAIL,
  localVePhone,
  useAgendaAccountKey,
} from '../../services/agenda';

/**
 * "Elegir de mi Agenda" for the Venezuelan Pago Móvil forms. Hidden when
 * the Agenda has no Pago Móvil entries or the server has no Agenda yet.
 * `ownOnly` (Recargar: the payer is the person) lists only their own accounts.
 */
export function VeAgendaPicker({ ownOnly = false, disabled = false, onPick }: {
  ownOnly?: boolean;
  disabled?: boolean;
  onPick: (entry: AgendaEntry) => void;
}) {
  const client = useApolloClient();
  // Reload per account, once a switch has finished: never the previous account's entries.
  const accountKey = useAgendaAccountKey();
  const [entries, setEntries] = useState<AgendaEntry[]>([]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const alive = useRef(true);
  const seq = useRef(0);
  useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setEntries([]);
    if (!accountKey) return;
    try {
      const { data } = await client.query({ query: AGENDA_ENTRIES, fetchPolicy: 'network-only' });
      if (!alive.current || mine !== seq.current) return;
      const rows: AgendaEntry[] = (data?.agendaEntries || []).filter((e: AgendaEntry) =>
        e.rail === VE_PAGOMOVIL_RAIL && (!ownOnly || e.relationship === 'own'));
      setEntries(rows);
    } catch {
      if (alive.current && mine === seq.current) setEntries([]);
    }
  }, [client, ownOnly, accountKey]);

  useEffect(() => { void load(); }, [load]);

  if (!entries.length) return null;
  const filtered = entries.filter(entry => {
    const needle = query.trim().toLowerCase();
    return !needle || [entry.label, entry.holderName, entry.subtitle, entry.cedula]
      .some(text => String(text || '').toLowerCase().includes(needle));
  });
  const rows: PickerRow[] = [];
  (['own', 'third_party'] as AgendaRelationship[]).forEach(relationship => {
    const group = filtered.filter(entry => entry.relationship === relationship);
    if (!group.length) return;
    rows.push({ kind: 'title', key: `t-${relationship}`, title: relationship === 'own' ? 'Tuyas' : 'Otras personas' });
    group.forEach(entry => rows.push({ kind: 'entry', key: entry.id, entry }));
  });

  return (
    <>
      <TouchableOpacity accessibilityRole="button" accessibilityLabel="Elegir de mi Agenda" disabled={disabled}
        onPress={() => { setQuery(''); setOpen(true); }} style={styles.trigger}>
        <View style={styles.triggerIcon}><Icon name="book-open" size={16} color={colors.primaryDark} /></View>
        <View style={styles.flex}>
          <Text style={styles.triggerText}>Elegir de mi Agenda</Text>
          <Text style={styles.triggerHint}>
            {entries.length === 1 ? '1 cuenta guardada' : `${entries.length} cuentas guardadas`}
          </Text>
        </View>
        <Icon name="chevron-right" size={18} color={colors.primaryDark} />
      </TouchableOpacity>
      <Modal visible={open} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => setOpen(false)}>
        <View style={styles.modal}>
          <View style={styles.header}>
            <View style={styles.flex}>
              <Text style={styles.eyebrow}>TU AGENDA</Text>
              <Text style={styles.title}>Elige una cuenta</Text>
              <Text style={styles.subtitle}>Llenamos la cédula, el teléfono y el banco por ti.</Text>
            </View>
            <TouchableOpacity accessibilityRole="button" accessibilityLabel="Cerrar" onPress={() => setOpen(false)}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
              <Icon name="x" size={24} color={colors.dark} />
            </TouchableOpacity>
          </View>
          {entries.length > SEARCH_FROM ? (
            <View style={styles.search}>
              <Icon name="search" size={16} color={colors.textSecondary} />
              <TextInput value={query} onChangeText={setQuery} placeholder="Buscar por nombre, banco o cédula"
                placeholderTextColor={colors.textTertiary} style={styles.searchInput} autoCorrect={false} />
            </View>
          ) : null}
          <FlatList
            data={rows}
            keyExtractor={item => item.key}
            initialNumToRender={20}
            maxToRenderPerBatch={10}
            windowSize={21}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.list}
            ListEmptyComponent={<Text style={styles.empty}>No encontramos cuentas con «{query}».</Text>}
            renderItem={({ item }) => item.kind === 'title' ? (
              <Text style={styles.groupTitle}>{item.title}</Text>
            ) : (
              <TouchableOpacity accessibilityRole="button" style={styles.card}
                onPress={() => { setOpen(false); onPick(item.entry); }}>
                <View style={styles.chip}>
                  <MCIcon name="cellphone" size={20} color={colors.primaryDark} />
                </View>
                <View style={styles.cardInner}>
                  <View style={styles.cardRow}>
                    <CountryFlag iso="VE" size={16} style={styles.flag} />
                    <Text style={styles.cardTitle} numberOfLines={1}>{item.entry.label}</Text>
                  </View>
                  <Text style={styles.cardDetail} numberOfLines={1}>
                    {[item.entry.relationship === 'own' ? 'Tuya' : item.entry.holderName, item.entry.cedula]
                      .filter(Boolean).join('  ·  ')}
                  </Text>
                  <Text style={styles.cardDetail} numberOfLines={1}>{item.entry.subtitle}</Text>
                </View>
                <Icon name="chevron-right" size={18} color={colors.textTertiary} />
              </TouchableOpacity>
            )}
          />
        </View>
      </Modal>
    </>
  );
}

type PickerRow =
  | { kind: 'title'; key: string; title: string }
  | { kind: 'entry'; key: string; entry: AgendaEntry };

const SEARCH_FROM = 6;

export interface VeAgendaSaveState {
  save: boolean;
  relationship: AgendaRelationship;
  holderName: string;
}

export const initialVeAgendaSave = (relationship: AgendaRelationship): VeAgendaSaveState =>
  ({ save: false, relationship, holderName: '' });

/** "Guardar en mi Agenda", with whose account it is when it may be someone else's. */
export function VeAgendaSaveToggle({ value, onChange, ownOnly = false, disabled = false }: {
  value: VeAgendaSaveState;
  onChange: (next: VeAgendaSaveState) => void;
  ownOnly?: boolean;
  disabled?: boolean;
}) {
  return (
    <View style={styles.saveBox}>
      <TouchableOpacity accessibilityRole="checkbox" accessibilityState={{ checked: value.save }} disabled={disabled}
        onPress={() => onChange({ ...value, save: !value.save })} style={styles.saveRow}>
        <Icon name={value.save ? 'check-square' : 'square'} size={20}
          color={value.save ? colors.primaryDark : colors.textSecondary} />
        <Text style={styles.saveText}>Guardar en mi Agenda</Text>
      </TouchableOpacity>
      {value.save && !ownOnly ? (
        <>
          <View style={styles.segment}>
            {(['own', 'third_party'] as AgendaRelationship[]).map(option => (
              <TouchableOpacity key={option} accessibilityRole="button" disabled={disabled}
                accessibilityState={{ selected: value.relationship === option }}
                onPress={() => onChange({ ...value, relationship: option })}
                style={[styles.segmentItem, value.relationship === option && styles.segmentActive]}>
                <Text style={[styles.segmentText, value.relationship === option && styles.segmentTextActive]}>
                  {option === 'own' ? 'Es mía' : 'De otra persona'}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          {value.relationship === 'third_party' ? (
            <TextInput accessibilityLabel="Nombre de la persona" value={value.holderName} editable={!disabled}
              onChangeText={holderName => onChange({ ...value, holderName })} placeholder="Nombre de la persona"
              placeholderTextColor={colors.textTertiary} style={styles.nameInput} />
          ) : null}
        </>
      ) : null}
    </View>
  );
}

export const veAgendaSaveReady = (value: VeAgendaSaveState) =>
  !value.save || value.relationship === 'own' || value.holderName.trim().length > 1;

/** Best effort: an order already made never fails because its account could not be saved. */
export async function saveVeAgendaEntry(client: ApolloClient<any>, value: VeAgendaSaveState,
  account: { cedula: string; phone: string; bankCode: string }) {
  if (!value.save) return;
  try {
    await client.mutate({
      mutation: SAVE_VE_AGENDA_ENTRY,
      variables: {
        relationship: value.relationship, holderName: value.relationship === 'own' ? '' : value.holderName.trim(),
        cedula: account.cedula, phone: account.phone, bankCode: account.bankCode,
      },
      fetchPolicy: 'no-cache',
    });
  } catch {
    // Saving is a convenience; the person can add it from the Agenda.
  }
}

export const vePickFields = (entry: AgendaEntry) => ({
  cedula: entry.cedula || '',
  phone: localVePhone(entry.phone),
  bankCode: entry.bankCode || '',
});


const styles = StyleSheet.create({
  flex: { flex: 1 },
  trigger: {
    flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 14, padding: 12, borderRadius: 14,
    backgroundColor: colors.primaryLight,
  },
  triggerIcon: {
    width: 32, height: 32, borderRadius: 10, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center',
  },
  triggerText: { fontSize: 15, fontWeight: '700', color: colors.primaryDeep },
  triggerHint: { fontSize: 12, color: colors.primaryDeep, opacity: 0.75, marginTop: 1 },
  modal: { flex: 1, backgroundColor: colors.white },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingHorizontal: 20, paddingTop: 22, paddingBottom: 8 },
  eyebrow: { fontSize: 11, fontWeight: '700', letterSpacing: 2, color: colors.primaryDark, marginBottom: 4 },
  title: { fontSize: 22, fontWeight: '800', color: colors.dark },
  subtitle: { fontSize: 13, color: colors.textSecondary, marginTop: 4 },
  search: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 20, marginTop: 10, paddingHorizontal: 12,
    borderRadius: 12, backgroundColor: colors.neutralDark, minHeight: 44,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.dark, paddingVertical: 8 },
  list: { paddingHorizontal: 16, paddingBottom: 32 },
  groupTitle: {
    fontSize: 11, fontWeight: '700', letterSpacing: 1, color: colors.textTertiary, textTransform: 'uppercase',
    marginTop: 18, marginBottom: 8, marginLeft: 4,
  },
  empty: { fontSize: 14, color: colors.textSecondary, textAlign: 'center', marginTop: 32 },
  card: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: colors.white, borderRadius: 14, marginBottom: 10,
    paddingRight: 14,
    ...Platform.select({
      ios: { shadowColor: colors.primaryDeep, shadowOffset: { width: 0, height: 3 }, shadowOpacity: 0.07, shadowRadius: 8 },
      android: { elevation: 3 },
    }),
  },
  chip: {
    width: 40, height: 40, borderRadius: 12, alignItems: 'center', justifyContent: 'center', marginLeft: 12,
    backgroundColor: colors.primaryLight,
  },
  cardInner: { flex: 1, paddingVertical: 14, paddingHorizontal: 12 },
  cardRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 4 },
  flag: { marginRight: 6 },
  cardTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.dark },
  cardDetail: { fontSize: 12, color: colors.textSecondary, marginTop: 1 },
  saveBox: { marginTop: 14 },
  saveRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 4 },
  saveText: { fontSize: 15, fontWeight: '600', color: colors.dark },
  segment: { flexDirection: 'row', gap: 8, marginTop: 10 },
  segmentItem: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingVertical: 10, alignItems: 'center',
    backgroundColor: colors.white,
  },
  segmentActive: { borderColor: colors.primaryDark, backgroundColor: colors.primaryLight },
  segmentText: { fontSize: 14, fontWeight: '600', color: colors.textSecondary },
  segmentTextActive: { color: colors.primaryDark },
  nameInput: {
    marginTop: 10, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14,
    minHeight: 48, fontSize: 16, color: colors.dark, backgroundColor: colors.white,
  },
});
