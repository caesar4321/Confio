// Connect, choose, review and revoke the phone's calendar for Confío IA, on the shared setup screen.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Linking, Pressable, StyleSheet, View } from 'react-native';
import { useMutation } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import CalendarMark from '../../components/svg/CalendarMark';
import { Text } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import SetupScreen, { Action, Alert, Danger, Details, Fine, Notes, Points, Secondary, setupStyles, type Hero } from '../connections/SetupScreen';
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
import { calendarColor, calendarName, groupByAccount, groupByDay, timeLabel } from './display';
import { cleanTitle, MAX_SENT, reminderTime, upcoming, WINDOW_DAYS } from './events';
import { cancelAllReminders, cancelReminder, pruneReminders, scheduleReminder } from './reminders';

type Step = 'loading' | 'intro' | 'calendars' | 'events';
type Props = { userId: string; onClose: () => void };

const INTRO_POINTS = [
  { icon: 'calendar', text: 'Veo lo que viene en los calendarios que elijas (Apple, Google y otros de este teléfono).' },
  { icon: 'bell', text: 'Te aviso antes de lo importante, con avisos en este teléfono.' },
  { icon: 'zap', text: 'Si quieres, Confío IA te dice qué parece un pago, un viaje o un vencimiento.' },
];
const INTRO_DATA = 'La lectura ocurre en este teléfono. Solo salen de él los títulos que tú marques, hacia Confío y '
  + 'OpenAI (Estados Unidos), y no se guardan.';
const INTRO_RISK = 'Confío IA puede equivocarse y nunca paga por ti.';
// The full consent: every rule the screen keeps.
const INTRO_DETAILS = [
  'Confío lee solo los calendarios de este teléfono que tú elijas (iCloud, Google u otros). La lectura ocurre en tu teléfono.',
  'Confío no crea, cambia ni borra eventos.',
  `Te muestro tus próximos ${WINDOW_DAYS} días, con los números y enlaces de los títulos ocultos.`,
  'Si me lo pides, te aviso con una notificación de este teléfono. El aviso no muestra tu evento.',
  `Nada sale del teléfono hasta que marques títulos y toques Enviar. Solo envío esos títulos (hasta ${MAX_SENT}), tal como los ves, a Confío y a OpenAI (Estados Unidos).`,
  'No enviamos fechas, lugares ni invitados.',
  'Confío no guarda los títulos que envías.',
  'Puedes desconectar cuando quieras: borro tu elección y los avisos. El permiso se quita en los ajustes del teléfono.',
  'Confío IA puede equivocarse y nunca paga por ti.',
];
const SEND_DISCLOSURE = 'Al tocar el botón, aceptas enviar a Confío y a OpenAI (Estados Unidos) solo los títulos '
  + 'marcados, tal como los ves arriba. No enviamos fechas, lugares ni invitados. Confío no los guarda. Confío IA '
  + 'puede equivocarse y nunca paga por ti.';

const countCalendars = (count: number) => `${count} ${count === 1 ? 'calendario' : 'calendarios'}`;

function Checkbox({ checked, partial = false }: { checked: boolean; partial?: boolean }) {
  return (
    <View style={[styles.box, (checked || partial) && styles.boxOn]}>
      {checked || partial ? <Icon name={checked ? 'check' : 'minus'} size={15} color={colors.white} /> : null}
    </View>
  );
}

function Dot({ color }: { color: string | null }) {
  return color ? <View style={[styles.dot, { backgroundColor: color }]} /> : null;
}

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
  const [reviewed, setReviewed] = useState<{ count: number; found: { id: string; title: string; label: string }[] } | null>(null);
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
    // Keep an earlier choice; a first choice starts with every calendar, and the person clears what they don't want.
    setAllowed((ids) => {
      const kept = ids.filter((id) => found.some((calendar) => calendar.id === id));
      return kept.length ? kept : found.map((calendar) => calendar.id);
    });
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
    setReviewed(null);
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
    setKinds((all) => ({ ...all, ...next }));
    // The answer shows at the top, where it is seen, and the ticks clear: the footer is free again.
    setReviewed({
      count: sent.length,
      found: sent.filter((event) => KIND_LABELS[next[event.id]])
        .map((event) => ({ id: event.id, title: cleanTitle(event.title), label: String(KIND_LABELS[next[event.id]]) })),
    });
    setPicked([]);
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

  const toggleCalendar = (id: string) => {
    setAllowed((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  };

  const allChosen = calendars.length > 0 && calendars.every((calendar) => allowed.includes(calendar.id));
  const chosenCount = calendars.filter((calendar) => allowed.includes(calendar.id)).length;
  const toggleAll = () => setAllowed(allChosen ? [] : calendars.map((calendar) => calendar.id));

  const pickEvent = (id: string) => {
    setPicked((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : ids.length < MAX_SENT ? [...ids, id] : ids));
  };

  const settingsLink = offerSettings
    ? <Secondary label="Abrir ajustes del teléfono" onPress={() => void Linking.openSettings()} />
    : null;
  const disconnect = connected ? <Danger label="Desconectar y borrar" onPress={revoke} disabled={busy} /> : null;

  let hero: Hero = { title: 'Tu calendario, en Confío' };
  let content: React.ReactNode = <ActivityIndicator style={styles.loading} color={colors.successText} />;
  let footer: React.ReactNode = null;

  if (step === 'intro') {
    hero = { title: 'Tu calendario, en Confío', chip: 'Paso 1 de 2' };
    content = (
      <>
        <Points points={INTRO_POINTS} />
        <Notes data={INTRO_DATA} risk={INTRO_RISK} />
        <Details lines={INTRO_DETAILS} />
        {settingsLink}
        {disconnect}
      </>
    );
    footer = (
      <>
        <Action label="Permitir acceso al calendario" onPress={chooseCalendars} busy={busy} />
        <Fine text="Luego eliges qué calendarios leo. No creo ni cambio eventos." />
      </>
    );
  } else if (step === 'calendars') {
    hero = { title: 'Elige tus calendarios', chip: 'Paso 2 de 2' };
    content = calendars.length ? (
      <>
        <Text style={setupStyles.text}>Elige qué calendarios puede leer Confío en este teléfono.</Text>
        <Pressable
          style={[setupStyles.card, styles.allRow]}
          disabled={busy}
          onPress={toggleAll}
          accessibilityRole="checkbox"
          accessibilityState={{ checked: allChosen ? true : chosenCount ? 'mixed' : false }}
          accessibilityLabel="Todos los calendarios"
        >
          <View style={styles.allIcon}><Icon name="layers" size={18} color={colors.successText} /></View>
          <View style={styles.rowText}>
            <Text style={styles.allTitle}>Todos los calendarios</Text>
            <Text style={setupStyles.hint}>{`${chosenCount} de ${calendars.length} elegidos`}</Text>
          </View>
          <Checkbox checked={allChosen} partial={!allChosen && chosenCount > 0} />
        </Pressable>
        {groupByAccount(calendars).map((group) => (
          <View key={group.account} style={styles.group}>
            <Text style={styles.groupTitle} numberOfLines={1}>{group.account}</Text>
            <View style={setupStyles.card}>
              {group.calendars.map((calendar, index) => {
                const checked = allowed.includes(calendar.id);
                const name = calendarName(calendar.title);
                return (
                  <Pressable
                    key={calendar.id}
                    style={[styles.row, index > 0 && setupStyles.divider]}
                    disabled={busy}
                    onPress={() => toggleCalendar(calendar.id)}
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked }}
                    accessibilityLabel={name}
                  >
                    <Dot color={calendarColor(calendar)} />
                    <Text style={styles.rowTitle} numberOfLines={2}>{name}</Text>
                    <Checkbox checked={checked} />
                  </Pressable>
                );
              })}
            </View>
          </View>
        ))}
        {disconnect}
      </>
    ) : (
      <>
        <Text style={setupStyles.text}>No encontré calendarios en este teléfono.</Text>
        {disconnect}
      </>
    );
    footer = <Action label="Listo" onPress={save} disabled={!allowed.length} busy={busy} />;
  } else if (step === 'events') {
    hero = { title: 'Calendario conectado', chip: `Activo · ${countCalendars(allowed.length)}`, live: true };
    const byId = new Map(calendars.map((calendar) => [calendar.id, calendar]));
    content = (
      <>
        {reviewed ? (
          <View style={styles.result} accessibilityLiveRegion="polite">
            <View style={styles.resultHead}>
              <Icon name="zap" size={16} color={colors.successText} />
              <Text style={styles.resultTitle}>
                {reviewed.found.length
                  ? `Confío IA revisó ${reviewed.count} y encontró ${reviewed.found.length} por atender`
                  : `Confío IA revisó ${reviewed.count}: nada por atender`}
              </Text>
            </View>
            {reviewed.found.map((item) => (
              <Text key={item.id} style={styles.resultLine}>{`${item.label}: ${item.title}`}</Text>
            ))}
            {reviewed.found.length ? <Text style={setupStyles.hint}>Toca «Avísame» en cada uno para que te recuerde. Puede equivocarse.</Text> : null}
          </View>
        ) : null}
        <Text style={setupStyles.text}>
          {`Tus próximos ${WINDOW_DAYS} días, con números y enlaces ocultos. Marca hasta ${MAX_SENT} títulos si quieres que los revise Confío IA.`}
        </Text>
        {events.length ? groupByDay(events).map((day) => (
          <View key={day.key} style={styles.group}>
            <Text style={styles.groupTitle}>{day.label}</Text>
            <View style={setupStyles.card}>
              {day.events.map((event, index) => {
                const checked = picked.includes(event.id);
                const title = cleanTitle(event.title);
                const label = kinds[event.id] ? KIND_LABELS[kinds[event.id]] : null;
                const reminderOn = reminded.includes(event.id);
                const color = event.calendarId ? calendarColor(byId.get(event.calendarId)) : null;
                return (
                  <View key={event.id} style={[styles.eventRow, index > 0 && setupStyles.divider]}>
                    <Pressable
                      style={styles.eventMain}
                      disabled={busy}
                      onPress={() => pickEvent(event.id)}
                      accessibilityRole="checkbox"
                      accessibilityState={{ checked }}
                      accessibilityLabel={title}
                    >
                      <Checkbox checked={checked} />
                      <View style={styles.rowText}>
                        <Text style={styles.eventTitle}>{title}</Text>
                        <View style={styles.meta}>
                          <Dot color={color} />
                          <Text style={setupStyles.hint}>{timeLabel(event)}</Text>
                        </View>
                        {label ? (
                          <View style={styles.kind}>
                            <Icon name="zap" size={12} color={colors.successText} />
                            <Text style={styles.kindText}>{label}</Text>
                          </View>
                        ) : null}
                      </View>
                    </Pressable>
                    {reminderOn || reminderTime(event) ? (
                      <Pressable
                        style={[styles.remind, reminderOn && styles.remindOn]}
                        disabled={busy}
                        onPress={() => toggleReminder(event)}
                        accessibilityRole="button"
                      >
                        <Icon name={reminderOn ? 'bell-off' : 'bell'} size={13} color={colors.successText} />
                        <Text style={styles.remindText}>{reminderOn ? 'Quitar aviso' : 'Avísame'}</Text>
                      </Pressable>
                    ) : null}
                  </View>
                );
              })}
            </View>
          </View>
        )) : <Text style={setupStyles.text}>No hay eventos en estos días.</Text>}
        <Secondary label="Cambiar calendarios" onPress={chooseCalendars} disabled={busy} />
        {settingsLink}
        {disconnect}
      </>
    );
    footer = (
      <>
        {/* By the button: an answer at the end of a long list is never seen. */}
        {message ? <Alert text={message} /> : null}
        {picked.length ? (
          <>
            <Fine text={SEND_DISCLOSURE} />
            <Action label={busy ? 'Revisando…' : `Enviar y revisar (${picked.length}/${MAX_SENT})`} onPress={review} busy={busy} />
          </>
        ) : <Action label="Ir a mi conversación" onPress={onClose} />}
      </>
    );
  }

  return (
    <SetupScreen logo={<CalendarMark size={36} />} hero={hero} onClose={onClose} footer={footer}
      message={step === 'events' ? null : message}>
      {content}
    </SetupScreen>
  );
}

const styles = StyleSheet.create({
  loading: { marginTop: 24 },
  result: { borderRadius: 16, backgroundColor: colors.mint, padding: 14, gap: 6 },
  resultHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  resultTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.primaryDeep },
  resultLine: { fontSize: 14, color: colors.textFlat },
  allRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14, minHeight: 64 },
  allIcon: { width: 38, height: 38, borderRadius: 12, backgroundColor: colors.mint, alignItems: 'center', justifyContent: 'center' },
  allTitle: { fontSize: 16, fontWeight: '800', color: colors.textFlat },
  group: { gap: 8 },
  groupTitle: { fontSize: 13, fontWeight: '700', color: colors.textSecondary, paddingHorizontal: 4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 52, paddingVertical: 12 },
  rowText: { flex: 1, gap: 2 },
  rowTitle: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.textFlat },
  eventTitle: { fontSize: 15, fontWeight: '600', color: colors.textFlat },
  dot: { width: 10, height: 10, borderRadius: 5 },
  box: {
    width: 22, height: 22, borderRadius: 7, borderWidth: 2, borderColor: colors.border, alignItems: 'center',
    justifyContent: 'center',
  },
  boxOn: { backgroundColor: colors.successText, borderColor: colors.successText },
  eventRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  eventMain: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12, minHeight: 52 },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  kind: {
    flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start', marginTop: 4, borderRadius: 999,
    backgroundColor: colors.mint, paddingHorizontal: 8, paddingVertical: 2,
  },
  kindText: { fontSize: 12, fontWeight: '700', color: colors.successText },
  remind: {
    flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 44, paddingHorizontal: 10, borderRadius: 999,
    alignSelf: 'center',
  },
  remindOn: { backgroundColor: colors.mint },
  remindText: { fontSize: 13, fontWeight: '700', color: colors.successText },
});
