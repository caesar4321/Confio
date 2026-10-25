import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, Modal, SafeAreaView, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { ApolloClient, useApolloClient } from '@apollo/client';

import { Text, TextInput } from '../common/AppText';
import { colors } from '../../config/theme';
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
  return (
    <>
      <TouchableOpacity accessibilityRole="button" accessibilityLabel="Elegir de mi Agenda" disabled={disabled}
        onPress={() => setOpen(true)} style={styles.trigger}>
        <Icon name="book-open" size={16} color={colors.primaryDark} />
        <Text style={styles.triggerText}>Elegir de mi Agenda</Text>
      </TouchableOpacity>
      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <SafeAreaView style={styles.modal}>
          <View style={styles.header}>
            <Text style={styles.title}>Mi Agenda</Text>
            <TouchableOpacity accessibilityRole="button" accessibilityLabel="Cerrar" onPress={() => setOpen(false)}>
              <Icon name="x" size={24} color={colors.dark} />
            </TouchableOpacity>
          </View>
          <FlatList
            data={entries}
            keyExtractor={item => item.id}
            initialNumToRender={20}
            maxToRenderPerBatch={10}
            windowSize={21}
            getItemLayout={(_, index) => ({ length: ROW, offset: ROW * index, index })}
            renderItem={({ item }) => (
              <TouchableOpacity accessibilityRole="button" style={styles.row}
                onPress={() => { setOpen(false); onPick(item); }}>
                <View style={styles.flex}>
                  <Text style={styles.rowTitle} numberOfLines={1}>{item.label}</Text>
                  <Text style={styles.rowSubtitle} numberOfLines={1}>
                    {`${item.relationship === 'own' ? 'Mía' : item.holderName} · ${item.subtitle}`}
                  </Text>
                </View>
                <Icon name="chevron-right" size={18} color={colors.textSecondary} />
              </TouchableOpacity>
            )}
          />
        </SafeAreaView>
      </Modal>
    </>
  );
}

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

const ROW = 64;

const styles = StyleSheet.create({
  flex: { flex: 1 },
  trigger: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start', paddingVertical: 8, marginBottom: 6 },
  triggerText: { fontSize: 15, fontWeight: '600', color: colors.primaryDark },
  modal: { flex: 1, backgroundColor: colors.white },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 20 },
  title: { fontSize: 20, fontWeight: '700', color: colors.dark },
  row: {
    height: ROW, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', gap: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  rowTitle: { fontSize: 16, fontWeight: '600', color: colors.dark },
  rowSubtitle: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
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
