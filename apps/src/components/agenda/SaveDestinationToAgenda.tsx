import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, StyleSheet, TouchableOpacity } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useApolloClient } from '@apollo/client';

import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import {
  AGENDA_ENTRIES, AgendaEntry, AgendaRelationship, SAVE_DESTINATION_TO_AGENDA, useAgendaAccountKey,
} from '../../services/agenda';

/**
 * One tap to keep a checked recipient in the Agenda ("Recientes" → saved).
 * Hidden while the server has no Agenda; shows "En tu Agenda" once saved.
 */
export function SaveDestinationToAgenda({ destinationId }: { destinationId: string }) {
  const client = useApolloClient();
  // Reload per account, once a switch has finished.
  const accountKey = useAgendaAccountKey();
  const seq = useRef(0);
  const [state, setState] = useState<'unknown' | 'unsaved' | 'saving' | 'saved'>('unknown');

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setState('unknown');
    if (!accountKey) return;
    try {
      const { data } = await client.query({ query: AGENDA_ENTRIES, fetchPolicy: 'network-only' });
      if (mine !== seq.current) return;
      const rows: AgendaEntry[] = data?.agendaEntries || [];
      setState(rows.some(row => row.destinationId === destinationId) ? 'saved' : 'unsaved');
    } catch {
      if (mine === seq.current) setState('unknown');
    }
  }, [client, destinationId, accountKey]);

  useEffect(() => { void load(); }, [load]);

  const save = async (relationship: AgendaRelationship) => {
    setState('saving');
    try {
      const { data } = await client.mutate({
        mutation: SAVE_DESTINATION_TO_AGENDA,
        variables: { destinationId, relationship },
        fetchPolicy: 'no-cache',
      });
      const result = data?.saveDestinationToAgenda;
      if (!result?.success) {
        setState('unsaved');
        Alert.alert('No pudimos guardarla', result?.errors?.[0] || 'Intenta de nuevo en unos segundos.');
        return;
      }
      setState('saved');
    } catch {
      setState('unsaved');
      Alert.alert('No pudimos guardarla', 'Intenta de nuevo en unos segundos.');
    }
  };

  const ask = () => Alert.alert('Guardar en mi Agenda', '¿De quién es esta cuenta?', [
    { text: 'Cancelar', style: 'cancel' },
    { text: 'Es mía', onPress: () => { void save('own'); } },
    { text: 'De otra persona', onPress: () => { void save('third_party'); } },
  ]);

  if (state === 'unknown') return null;
  if (state === 'saved') {
    return (
      <Text style={styles.saved}>
        <Icon name="bookmark" size={13} color={colors.primaryDark} /> En tu Agenda
      </Text>
    );
  }
  return (
    <TouchableOpacity accessibilityRole="button" onPress={ask} disabled={state === 'saving'} style={styles.button}>
      <Icon name="bookmark" size={14} color={colors.primaryDark} />
      <Text style={styles.buttonText}>{state === 'saving' ? 'Guardando…' : 'Guardar en mi Agenda'}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  button: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8, alignSelf: 'flex-start', paddingVertical: 4 },
  buttonText: { fontSize: 14, fontWeight: '600', color: colors.primaryDark },
  saved: { fontSize: 13, fontWeight: '600', color: colors.primaryDark, marginTop: 8 },
});
