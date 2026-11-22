// What Confío IA keeps about the person in this account: see, delete, switch off, wipe.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Modal, Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';
import { useApolloClient, type DocumentNode } from '@apollo/client';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import { FORGET_MEMORY, GET_MEMORY, SET_MEMORY, WIPE_MEMORY, type MemoryState } from './api';

const LOAD_FAILED = 'No pude cargar tu memoria. Inténtalo de nuevo.';
const CHANGE_FAILED = 'No pude guardar el cambio. Inténtalo de nuevo.';

const day = (value: string) =>
  new Date(value).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' });

export default function MemorySheet({ onClose }: { onClose: () => void }) {
  const client = useApolloClient();
  const [memory, setMemory] = useState<MemoryState | null>(null);
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const open = useRef(true);

  const load = useCallback(async () => {
    setBusy(true);
    setMessage(null);
    try {
      // no-cache: the person's own words never land in the Apollo store.
      const { data } = await client.query<any>({ query: GET_MEMORY, fetchPolicy: 'no-cache' });
      if (open.current) {
        setMemory(data?.assistantMemory ?? null);
        setMessage(data?.assistantMemory ? null : LOAD_FAILED);
      }
    } catch {
      if (open.current) { setMessage(LOAD_FAILED); }
    } finally {
      if (open.current) { setBusy(false); }
    }
  }, [client]);

  useEffect(() => {
    open.current = true;
    void load();
    return () => { open.current = false; };
  }, [load]);

  const change = async (mutation: DocumentNode, field: string, variables?: Record<string, unknown>) => {
    // An alert outlives the sheet. The account may have changed under it, and the server acts on the JWT's.
    if (!open.current) { return; }
    setBusy(true);
    setMessage(null);
    try {
      const { data } = await client.mutate<any>({ mutation, variables, fetchPolicy: 'no-cache' });
      if (!open.current) { return; }
      const result = data?.[field];
      // Never another account's memory on this account's sheet.
      if (result?.memory && result.memory.openedFor === memory?.openedFor) { setMemory(result.memory); }
      if (!result?.success) { setMessage(result?.error || CHANGE_FAILED); }
    } catch {
      if (open.current) { setMessage(CHANGE_FAILED); }
    } finally {
      if (open.current) { setBusy(false); }
    }
  };

  const confirmWipe = () =>
    Alert.alert(
      '¿Borrar toda tu memoria?',
      'Confío IA dejará de usar tus preferencias y lo que hablaron hasta hoy. Los mensajes siguen en el chat.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Borrar',
          style: 'destructive',
          onPress: () => void change(WIPE_MEMORY, 'wipeAssistantMemory', { openedFor: memory?.openedFor }),
        },
      ],
    );

  const confirmForget = (factId: string) =>
    Alert.alert(
      '¿Borrar esta preferencia?',
      'Confío IA también dejará de tener en cuenta lo que hablaron hasta hoy. Los mensajes siguen en el chat.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Borrar',
          style: 'destructive',
          onPress: () => void change(FORGET_MEMORY, 'forgetAssistantMemory', { factId }),
        },
      ],
    );

  const row = (id: string, text: string, remove: () => void, detail?: string) => (
    <View key={id} style={styles.row}>
      <View style={styles.flex}>
        <Text style={styles.value}>{text}</Text>
        {detail ? <Text style={styles.detail}>{detail}</Text> : null}
      </View>
      <Pressable
        style={styles.remove}
        disabled={busy}
        onPress={remove}
        accessibilityRole="button"
        accessibilityLabel={`Borrar: ${text}`}
      >
        <Icon name="trash-2" size={18} color={colors.textSecondary} />
      </Pressable>
    </View>
  );

  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <SafeAreaProvider>
        <SafeAreaView style={styles.screen}>
          <View style={styles.header}>
            <Text style={styles.title}>Memoria</Text>
            <Pressable style={styles.close} onPress={onClose} accessibilityRole="button" accessibilityLabel="Cerrar">
              <Icon name="x" size={22} color={colors.textFlat} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={styles.content}>
            <Text style={styles.paragraph}>
              Cada cuenta tiene su propia memoria. Nunca sirve para decidir un pago: montos y destinatarios salen
              solo de lo que escribes en el momento.
            </Text>
            {busy && !memory ? <ActivityIndicator style={styles.loading} color={colors.successText} /> : null}
            {memory && !memory.available ? (
              <Text style={styles.paragraph}>La memoria todavía no está disponible para ti.</Text>
            ) : null}

            {memory?.available && (memory.canRemember || memory.facts.length) ? (
              <View>
                <View style={styles.switchRow}>
                  <Text style={styles.heading}>Tus preferencias</Text>
                  <Switch
                    value={memory.factsEnabled}
                    disabled={busy || (!memory.canRemember && !memory.factsEnabled)}
                    onValueChange={(on) => void change(SET_MEMORY, 'setAssistantMemory', {
                      openedFor: memory.openedFor, factsEnabled: on,
                    })}
                    accessibilityLabel="Tus preferencias"
                  />
                </View>
                <Text style={styles.paragraph}>
                  Se guardan solo cuando lo pides: escribe «Recuerda que…». Pueden ser tu idioma, cómo prefieres las
                  respuestas, el trato, metas, ocupación, país de tu familia y gustos.
                </Text>
                {memory.facts.map((fact) => row(`fact-${fact.id}`, fact.text, () => confirmForget(fact.id)))}
              </View>
            ) : null}

            {memory?.available && (memory.canRecall || memory.quotes.length) ? (
              <View>
                <View style={styles.switchRow}>
                  <Text style={styles.heading}>Mensajes anteriores</Text>
                  <Switch
                    value={memory.recallEnabled}
                    disabled={busy || (!memory.canRecall && !memory.recallEnabled)}
                    onValueChange={(on) => void change(SET_MEMORY, 'setAssistantMemory', {
                      openedFor: memory.openedFor, recallEnabled: on,
                    })}
                    accessibilityLabel="Mensajes anteriores"
                  />
                </View>
                <Text style={styles.paragraph}>
                  En chats largos, Confío IA puede consultar hasta 12 frases tuyas de antes sobre tus viajes, estudios,
                  proyectos, gustos, mascotas y metas. Estas son:
                </Text>
                {memory.quotes.map((quote) =>
                  row(
                    `quote-${quote.id}`,
                    `«${quote.text}»`,
                    () => void change(FORGET_MEMORY, 'forgetAssistantMemory', { quoteId: quote.id }),
                    day(quote.saidAt),
                  ))}
              </View>
            ) : null}

            {memory?.available ? (
              <Pressable style={styles.wipe} disabled={busy} onPress={confirmWipe} accessibilityRole="button">
                <Text style={styles.wipeText}>Borrar toda mi memoria</Text>
              </Pressable>
            ) : null}
            {message ? <Text style={styles.message}>{message}</Text> : null}
            {!memory && !busy ? (
              <Pressable style={styles.wipe} onPress={() => void load()} accessibilityRole="button">
                <Text style={styles.retry}>Reintentar</Text>
              </Pressable>
            ) : null}
          </ScrollView>
        </SafeAreaView>
      </SafeAreaProvider>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 20 },
  title: { fontSize: 20, fontWeight: '700', color: colors.textFlat },
  close: { width: 52, height: 52, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 40 },
  paragraph: { fontSize: 14, color: colors.textSecondary, marginTop: 8 },
  loading: { marginTop: 32 },
  switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 28 },
  heading: { fontSize: 17, fontWeight: '700', color: colors.textFlat },
  row: { flexDirection: 'row', alignItems: 'center', minHeight: 52, borderBottomWidth: 1, borderBottomColor: colors.borderLight },
  value: { fontSize: 15, color: colors.textFlat },
  detail: { fontSize: 12, color: colors.textSecondary, marginTop: 2 },
  remove: { width: 48, height: 48, alignItems: 'center', justifyContent: 'center' },
  wipe: { minHeight: 48, justifyContent: 'center', marginTop: 24 },
  wipeText: { fontSize: 15, fontWeight: '600', color: colors.warning.text },
  retry: { fontSize: 15, fontWeight: '600', color: colors.successText },
  message: { fontSize: 14, color: colors.textFlat, marginTop: 12 },
});
