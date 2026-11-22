// Connect, choose, review and revoke the phone's calendar for Confío IA.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Linking, Modal, Pressable, StyleSheet, View } from 'react-native';
import { useMutation } from '@apollo/client';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import { ANALYZE_ASSISTANT_CALENDAR, KIND_LABELS, type CalendarKind } from './api';
import { CALENDAR_CONSENT_VERSION, clearCalendarConsent, readCalendarConsent, saveCalendarConsent } from './consent';
import { forgetCalendar } from './forgetCalendar';
import {
  hasCalendarAccess,
  listDeviceCalendars,
  listDeviceEvents,
  requestCalendarAccess,
  type DeviceCalendar,
  type DeviceEvent,
} from './deviceCalendar';
import { cleanTitle, MAX_SENT, reminderTime, upcoming, WINDOW_DAYS } from './events';
import { cancelAllReminders, cancelReminder, pruneReminders, scheduleReminder } from './reminders';

type Step = 'loading' | 'intro' | 'calendars' | 'events';
type Row = DeviceCalendar | DeviceEvent;
type Props = { userId: string; onClose: () => void };

const when = (event: DeviceEvent) => {
  const date = new Date(event.startsAt);
  const day = date.toLocaleDateString('es', { weekday: 'short', day: 'numeric', month: 'short' });
  return event.allDay ? day : `${day}, ${date.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}`;
};

export default function CalendarConnectSheet({ userId, onClose }: Props) {
  const [step, setStep] = useState<Step>('loading');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [offerSettings, setOfferSettings] = useState(false);
  const [calendars, setCalendars] = useState<DeviceCalendar[]>([]);
  const [allowed, setAllowed] = useState<string[]>([]);
  const [events, setEvents] = useState<DeviceEvent[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [kinds, setKinds] = useState<Record<string, CalendarKind>>({});
  const [reminded, setReminded] = useState<string[]>([]);
  // Consent is saved or reminders may remain: revoke must stay reachable.
  const [connected, setConnected] = useState(false);
  // no-cache: titles and answers never land in the Apollo store.
  const [analyze] = useMutation(ANALYZE_ASSISTANT_CALENDAR, { fetchPolicy: 'no-cache' });
  // Closing or revoking drops whatever was still on its way.
  const generation = useRef(0);
  const closed = useRef(false);

  const loadEvents = useCallback(async (calendarIds: string[]) => {
    if (closed.current) {
      return;
    }
    const run = ++generation.current;
    const from = Date.now();
    const found = upcoming(await listDeviceEvents(calendarIds, from, from + WINDOW_DAYS * 86400000));
    if (run !== generation.current) {
      return;
    }
    const scheduled = await pruneReminders(userId, found.map((event) => event.id));
    if (run !== generation.current) {
      return;
    }
    setAllowed(calendarIds);
    setEvents(found);
    setReminded(scheduled);
    setPicked([]);
    setKinds({});
    setStep('events');
  }, [userId]);

  useEffect(() => {
    closed.current = false;
    const run = ++generation.current;
    (async () => {
      const saved = await readCalendarConsent(userId);
      const granted = !!saved && (await hasCalendarAccess());
      if (run !== generation.current) {
        return;
      }
      if (saved && granted) {
        setConnected(true);
        await loadEvents(saved);
        return;
      }
      if (saved) {
        // The permission was removed in the phone's settings: that is a revoke.
        setConnected(true);
        await clearCalendarConsent();
      }
      // No consent means no nudges, including any an interrupted revoke left.
      await cancelAllReminders();
      setConnected(false);
      if (run === generation.current) {
        setStep('intro');
      }
    })().catch(() => {
      // Unknown state: keep revoke on screen.
      setConnected(true);
      setStep('intro');
      setMessage('No pude leer tu agenda. Inténtalo de nuevo.');
    });
    return () => {
      closed.current = true;
      generation.current += 1;
    };
  }, [loadEvents, userId]);

  const attempt = async (task: () => Promise<void>, failure: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await task();
    } catch {
      setMessage(failure);
    } finally {
      setBusy(false);
    }
  };

  const chooseCalendars = () => attempt(async () => {
    if (!(await requestCalendarAccess())) {
      setOfferSettings(true);
      setMessage('No tengo permiso para leer tu calendario. Puedes darlo en los ajustes del teléfono.');
      return;
    }
    setOfferSettings(false);
    const found = await listDeviceCalendars();
    setCalendars(found);
    setAllowed((ids) => ids.filter((id) => found.some((calendar) => calendar.id === id)));
    setStep('calendars');
  }, 'No pude abrir tus calendarios. Inténtalo de nuevo.');

  const save = () => attempt(async () => {
    await saveCalendarConsent(userId, allowed);
    setConnected(true);
    try {
      await loadEvents(allowed);
    } catch {
      setMessage('Guardé tu elección, pero no pude leer los eventos. Inténtalo de nuevo.');
    }
  }, 'No pude guardar tu elección. Inténtalo de nuevo.');

  const revoke = () => attempt(async () => {
    generation.current += 1;
    await forgetCalendar();
    setStep('intro');
    setAllowed([]);
    setEvents([]);
    setPicked([]);
    setKinds({});
    setReminded([]);
    setOfferSettings(true);
    setConnected(false);
    setMessage('Agenda desconectada. Borré tu elección y los avisos. El permiso se quita en los ajustes del teléfono.');
  }, 'No pude completar la desconexión. Inténtalo de nuevo.');

  const review = () => attempt(async () => {
    const sent = events.filter((event) => picked.includes(event.id));
    const run = generation.current;
    const { data } = await analyze({
      variables: { titles: sent.map((event) => cleanTitle(event.title)), consentVersion: CALENDAR_CONSENT_VERSION },
    });
    if (run !== generation.current) {
      return;
    }
    const result = data?.analyzeAssistantCalendar;
    if (!result?.success || result.kinds?.length !== sent.length) {
      setMessage(result?.error || 'No pude revisar tu agenda ahora.');
      return;
    }
    const next: Record<string, CalendarKind> = {};
    sent.forEach((event, index) => {
      next[event.id] = result.kinds[index];
    });
    setKinds(next);
    if (!sent.some((event) => KIND_LABELS[next[event.id]])) {
      setMessage('No encontré nada que atender en lo que elegiste.');
    }
  }, 'No pude revisar tu agenda ahora. Inténtalo de nuevo.');

  const toggleReminder = (event: DeviceEvent) => attempt(async () => {
    if (reminded.includes(event.id)) {
      await cancelReminder(userId, event.id);
      setReminded((ids) => ids.filter((id) => id !== event.id));
      return;
    }
    const at = reminderTime(event);
    const run = generation.current;
    const wanted = () => !closed.current && run === generation.current;
    if (!at) {
      setMessage('Ese evento está muy cerca para programar un aviso.');
    } else if (await scheduleReminder(userId, event.id, at, wanted)) {
      setReminded((ids) => [...ids, event.id]);
    } else if (wanted()) {
      setMessage('Activa las notificaciones del teléfono para que te avise.');
    }
  }, 'No pude cambiar el aviso. Inténtalo de nuevo.');

  const toggle = (id: string) => {
    if (step === 'calendars') {
      setAllowed((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
    } else {
      setPicked((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : ids.length < MAX_SENT ? [...ids, id] : ids));
    }
  };

  const renderRow = ({ item }: { item: Row }) => {
    const event = 'startsAt' in item ? item : null;
    const checked = (event ? picked : allowed).includes(item.id);
    const title = event ? cleanTitle(event.title) : item.title;
    const label = event && kinds[item.id] ? KIND_LABELS[kinds[item.id]] : null;
    const reminderOn = reminded.includes(item.id);
    return (
      <View style={styles.row}>
        <Pressable
          style={styles.rowMain}
          disabled={busy}
          onPress={() => toggle(item.id)}
          accessibilityRole="checkbox"
          accessibilityState={{ checked }}
          accessibilityLabel={title}
        >
          <Icon name={checked ? 'check-square' : 'square'} size={22} color={colors.successText} />
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>{title}</Text>
            <Text style={styles.detail}>{'startsAt' in item ? when(item) : item.account}</Text>
            {label ? <Text style={styles.kind}>{label}</Text> : null}
          </View>
        </Pressable>
        {event && (reminderOn || reminderTime(event)) ? (
          <Pressable style={styles.remind} disabled={busy} onPress={() => toggleReminder(event)} accessibilityRole="button">
            <Text style={styles.link}>{reminderOn ? 'Quitar aviso' : 'Avísame'}</Text>
          </Pressable>
        ) : null}
      </View>
    );
  };

  const button = (label: string, onPress: () => void, disabled = false) => (
    <Pressable
      style={[styles.button, (busy || disabled) && styles.disabled]}
      disabled={busy || disabled}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ disabled: busy || disabled }}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );

  const heading = step === 'calendars'
    ? 'Elige qué calendarios puede leer Confío en este teléfono.'
    : step === 'events'
      ? `Tus próximos ${WINDOW_DAYS} días, con números y enlaces ocultos. Marca solo lo que quieras que revise Confío IA.`
      : 'Confío puede leer los calendarios de este teléfono que tú elijas (iCloud, Google u otros) para mostrarte lo que viene y avisarte si se lo pides. La lectura ocurre en tu teléfono. No crea ni cambia eventos.';

  const rows: Row[] = step === 'calendars' ? calendars : step === 'events' ? events : [];

  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <SafeAreaProvider>
        <SafeAreaView style={styles.screen}>
          <View style={styles.header}>
            <Text style={styles.title}>Tu agenda</Text>
            <Pressable style={styles.close} onPress={onClose} accessibilityRole="button" accessibilityLabel="Cerrar">
              <Icon name="x" size={24} color={colors.textFlat} />
            </Pressable>
          </View>
          {step === 'loading' ? (
            <ActivityIndicator style={styles.loading} color={colors.successText} />
          ) : (
            <FlatList
              data={rows}
              extraData={[allowed, picked, kinds, reminded, busy]}
              keyExtractor={(item) => item.id}
              renderItem={renderRow}
              initialNumToRender={20}
              maxToRenderPerBatch={10}
              windowSize={21}
              contentContainerStyle={styles.content}
              ListHeaderComponent={<Text style={styles.intro}>{heading}</Text>}
              ListEmptyComponent={step === 'intro' ? null : (
                <Text style={styles.detail}>
                  {step === 'calendars' ? 'No encontré calendarios en este teléfono.' : 'No hay eventos en estos días.'}
                </Text>
              )}
              ListFooterComponent={(
                <View style={styles.footer}>
                  {step === 'intro' ? button('Elegir calendarios', chooseCalendars) : null}
                  {step === 'calendars' ? button('Guardar', save, !allowed.length) : null}
                  {step === 'events' && events.length ? (
                    <>
                      <Text style={styles.detail}>
                        Al tocar el botón, aceptas enviar a Confío y a OpenAI (Estados Unidos) solo los títulos
                        marcados, tal como los ves arriba. No enviamos fechas, lugares ni invitados. Confío no los
                        guarda. Confío IA puede equivocarse y nunca paga por ti.
                      </Text>
                      {button(`Enviar y revisar (${picked.length}/${MAX_SENT})`, review, !picked.length)}
                    </>
                  ) : null}
                  {busy ? <ActivityIndicator color={colors.successText} /> : null}
                  {message ? <Text style={styles.message} accessibilityLiveRegion="polite">{message}</Text> : null}
                  {offerSettings ? (
                    <Pressable style={styles.linkButton} onPress={() => Linking.openSettings()} accessibilityRole="button">
                      <Text style={styles.link}>Abrir ajustes del teléfono</Text>
                    </Pressable>
                  ) : null}
                  {connected ? (
                    <View style={styles.manage}>
                      {step === 'events' ? (
                        <Pressable style={styles.linkButton} disabled={busy} onPress={chooseCalendars} accessibilityRole="button">
                          <Text style={styles.link}>Cambiar calendarios</Text>
                        </Pressable>
                      ) : null}
                      <Pressable style={styles.linkButton} disabled={busy} onPress={revoke} accessibilityRole="button">
                        <Text style={styles.revoke}>Desconectar y borrar</Text>
                      </Pressable>
                    </View>
                  ) : null}
                </View>
              )}
            />
          )}
        </SafeAreaView>
      </SafeAreaProvider>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 20 },
  title: { fontSize: 20, fontWeight: '700', color: colors.textFlat },
  close: { width: 52, height: 52, alignItems: 'center', justifyContent: 'center' },
  loading: { marginTop: 40 },
  content: { paddingHorizontal: 20, paddingBottom: 32 },
  intro: { fontSize: 15, color: colors.gray600, marginBottom: 12 },
  row: { flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: colors.borderLight },
  rowMain: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  rowText: { flex: 1 },
  rowTitle: { fontSize: 15, color: colors.textFlat },
  detail: { fontSize: 13, color: colors.textSecondary },
  kind: { fontSize: 13, fontWeight: '600', color: colors.successText },
  remind: { minHeight: 44, justifyContent: 'center', paddingLeft: 12 },
  footer: { gap: 12, marginTop: 20 },
  button: { minHeight: 48, borderRadius: 14, backgroundColor: colors.successText, alignItems: 'center', justifyContent: 'center', padding: 12 },
  disabled: { opacity: 0.45 },
  buttonText: { color: colors.white, fontSize: 15, fontWeight: '700' },
  message: { fontSize: 14, color: colors.textFlat },
  manage: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between' },
  linkButton: { minHeight: 44, justifyContent: 'center' },
  link: { color: colors.successText, fontSize: 14, fontWeight: '600' },
  revoke: { color: colors.error.text, fontSize: 14, fontWeight: '600' },
});
