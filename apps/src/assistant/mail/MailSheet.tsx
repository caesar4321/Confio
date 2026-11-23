// Gmail pilot: consent, what needs attention, ask, and write. Kept out of the
// support thread, which staff read and the assistant replays to a model with tools.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Linking, Modal, Platform, Pressable, ScrollView, View } from 'react-native';
import { useApolloClient, type DocumentNode } from '@apollo/client';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';

import { Text, TextInput } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import {
  ASK,
  DISCONNECT,
  DISMISS_NEED,
  DRAFT_MAIL,
  GET_MAIL,
  MAIL_CONSENT_VERSION,
  NEED_LABELS,
  SHOW_AGENDA,
  SHOW_NEED,
  START_CONNECT,
  type MailDraft,
  type MailEvent,
  type MailNeed,
  type MailSource,
  type MailState,
} from './api';
import { finishMailConnect } from './connectFlow';
import { onMailConnectResult } from './connectLink';
import MailDraftView from './MailDraftView';
import { Action, Link, styles } from './ui';
import { mailSession } from './session';
import { saveVerifier } from './verifier';

const FAILED = 'No pude completar eso con tu correo. Inténtalo de nuevo.';
const GOOGLE_AUTH = 'https://accounts.google.com/';
const PRIVACY_URL = 'https://confio.lat/privacy';

const day = (value: string) => {
  // A date has no time: noon keeps it on the same day in every LATAM timezone.
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  return date.toLocaleDateString('es', { day: 'numeric', month: 'short' });
};

const hour = (value: string) => new Date(value).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });

type Props = { userId: string; onClose: () => void };

export default function MailSheet({ userId, onClose }: Props) {
  const client = useApolloClient();
  const [mail, setMail] = useState<MailState | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<{ text: string; sources: MailSource[] } | null>(null);
  const [shown, setShown] = useState<Record<string, MailSource>>({});
  // null: not read yet. Never kept past this screen.
  const [events, setEvents] = useState<MailEvent[] | null>(null);
  const [calendarFailed, setCalendarFailed] = useState(false);
  // These four survive the app lock (session.ts).
  const saved = mailSession(userId);
  const [replyTo, setReplyToState] = useState<MailSource | null>(saved.replyTo);
  const [to, setToState] = useState(saved.to);
  const [instructions, setInstructionsState] = useState(saved.instructions);
  const [draft, setDraftState] = useState<MailDraft | null>(saved.draft);
  const setReplyTo = (value: MailSource | null) => { saved.replyTo = value; setReplyToState(value); };
  const setTo = (value: string) => { saved.to = value; setToState(value); };
  const setInstructions = (value: string) => { saved.instructions = value; setInstructionsState(value); };
  const setDraft = (value: MailDraft | null) => { saved.draft = value; setDraftState(value); };
  const open = useRef(true);
  const sending = useRef<MailDraft | null>(null);

  const run = useCallback(async (mutation: DocumentNode, field: string, variables?: Record<string, unknown>) => {
    const { data } = await client.mutate<any>({ mutation, variables, fetchPolicy: 'no-cache' });
    const result = data?.[field];
    if (!result?.success) {
      if (open.current) {
        setMessage(result?.error || FAILED);
        if (result?.errorCode === 'reconnect') {
          // Ended while in use: show the reconnect button now.
          setMail((state) => state && { ...state, needsReconnect: true });
        }
      }
      return null;
    }
    return open.current ? result : null;
  }, [client]);

  const reload = useCallback(async () => {
    try {
      const { data } = await client.query<any>({ query: GET_MAIL, fetchPolicy: 'no-cache' });
      if (open.current) {
        setMail(data?.assistantMail ?? null);
        setFailed(!data?.assistantMail);
      }
    } catch {
      if (open.current) {
        setMail(null);
        setFailed(true);
      }
    } finally {
      if (open.current) {
        setLoading(false);
      }
    }
  }, [client]);

  const attempt = useCallback(async (task: () => Promise<void>) => {
    setBusy(true);
    setMessage(null);
    try {
      await task();
    } catch {
      setMessage(FAILED);
    } finally {
      setBusy(false);
    }
  }, []);

  const finishConnect = useCallback(async () => {
    const work = finishMailConnect(client, userId);
    if (work) {
      setBusy(true);
      await work;
    }
    const session = mailSession(userId);
    if (session.drafting) {
      setBusy(true);
      await session.drafting;
    }
    if (!open.current) {
      return; // the notice waits in the session
    }
    setDraftState(session.draft);
    setBusy(false);
    await reload();
    if (open.current && session.notice) {
      setMessage(session.notice);
      session.notice = null;
    }
  }, [client, reload, userId]);

  useEffect(() => {
    open.current = true;
    void finishConnect();
    const unsubscribe = onMailConnectResult(() => { void finishConnect(); });
    return () => {
      open.current = false;
      unsubscribe();
    };
  }, [finishConnect]);

  const withCalendar = !!mail?.available && !!mail.connected && !mail.needsReconnect && mail.canCalendar;
  useEffect(() => {
    setEvents(null);
    setCalendarFailed(false);
    if (!withCalendar) {
      return undefined;
    }
    // An answer asked before a disconnect or a reconnect belongs to nobody.
    let current = true;
    // Quiet: a calendar that did not load is no reason to cover the mail with an error.
    client.mutate<any>({ mutation: SHOW_AGENDA, fetchPolicy: 'no-cache' })
      .then(({ data }) => {
        const result = data?.showAssistantMailAgenda;
        if (!open.current || !current) {
          return;
        }
        if (result?.errorCode === 'reconnect') {
          setMail((state) => state && { ...state, needsReconnect: true });
        }
        setEvents(result?.success ? result.events ?? [] : null);
        setCalendarFailed(!result?.success);
      })
      .catch(() => {
        if (open.current && current) {
          setCalendarFailed(true);
        }
      });
    return () => { current = false; };
  }, [client, withCalendar]);

  const connect = () => attempt(async () => {
    const result = await run(START_CONNECT, 'startAssistantMailConnect', { consentVersion: MAIL_CONSENT_VERSION });
    if (!result) {
      return;
    }
    if (!String(result.authUrl).startsWith(GOOGLE_AUTH)) {
      setMessage(FAILED);
      return;
    }
    const state = /[?&]state=([^&]+)/.exec(result.authUrl)?.[1];
    if (!state) {
      setMessage(FAILED);
      return;
    }
    await saveVerifier(userId, result.verifier, decodeURIComponent(state));
    // The system browser: Google refuses sign-in inside an app.
    await Linking.openURL(result.authUrl);
  });

  const disconnect = () => attempt(async () => {
    const result = await run(DISCONNECT, 'disconnectAssistantMail');
    if (!result) {
      return;
    }
    setAnswer(null);
    setShown({});
    setEvents(null);
    setReplyTo(null);
    setDraft(null);
    await reload();
    setMessage(result.revoked
      ? 'Gmail desconectado. Borré el acceso, los avisos y los borradores.'
      : 'Borré todo en Confío, pero Google no confirmó. Quita también a Confío en myaccount.google.com/permissions.');
  });

  const ask = () => attempt(async () => {
    const result = await run(ASK, 'askAssistantMail', { question: question.trim() });
    if (result) {
      setAnswer({ text: result.answer, sources: result.sources ?? [] });
    }
  });

  const show = (need: MailNeed) => attempt(async () => {
    const result = await run(SHOW_NEED, 'showAssistantMailNeed', { id: need.id });
    if (result?.source) {
      setShown((all) => ({ ...all, [need.id]: result.source }));
    }
  });

  const dismiss = (need: MailNeed) => attempt(async () => {
    if (await run(DISMISS_NEED, 'dismissAssistantMailNeed', { id: need.id })) {
      setMail((state) => state && { ...state, needs: state.needs.filter((item) => item.id !== need.id) });
    }
  });

  const write = () => attempt(async () => {
    // Saved in the session before anything looks at the screen: the lock may have removed it.
    const work = (async () => {
      try {
        const { data } = await client.mutate<any>({
          mutation: DRAFT_MAIL,
          variables: {
            instructions: instructions.trim(),
            ...(replyTo ? { source: replyTo.handle } : { to: to.trim() }),
          },
          fetchPolicy: 'no-cache',
        });
        const result = data?.draftAssistantMail;
        if (result?.success && result.draft) {
          saved.draft = result.draft;
        } else {
          saved.notice = result?.error || FAILED;
          if (result?.errorCode === 'reconnect' && open.current) {
            setMail((state) => state && { ...state, needsReconnect: true });
          }
        }
      } catch {
        saved.notice = FAILED;
      }
    })();
    saved.drafting = work;
    await work;
    saved.drafting = null;
    if (open.current) {
      setDraftState(saved.draft);
      if (saved.notice) {
        setMessage(saved.notice);
        saved.notice = null;
      }
    }
  });

  const source = (item: MailSource) => (
    <View key={item.handle} style={styles.row}>
      <Text style={styles.rowTitle}>{item.subject || 'Sin asunto'}</Text>
      <Text style={styles.detail}>{item.sender} · {day(item.sentAt)}</Text>
      <Link label="Responder" disabled={busy} onPress={() => setReplyTo(item)} />
    </View>
  );

  const connected = !!mail?.connected;
  const ready = !!mail?.available && connected && !mail.needsReconnect;

  const intro = (
    <>
      <Text style={styles.paragraph}>
        Con tu permiso, Confío IA lee tu Gmail para avisarte de lo que tienes por atender: pagos, vencimientos,
        viajes, citas, entregas, dinero que recibes y correos que esperan tu respuesta. También responde tus
        preguntas y escribe correos. Solo envía un correo cuando tú lo confirmas, y nunca paga por ti.
      </Text>
      <Text style={styles.paragraph}>
        Para avisarte, lee los correos que recibes, salvo la publicidad, las redes sociales, los foros y el spam.
        Cuando le haces una pregunta, busca en todo tu Gmail, salvo el spam y la papelera. Si también das el
        permiso de calendario, cuenta los eventos de hoy de tu Google Calendar para el aviso diario y te muestra
        aquí los de hoy y mañana. Tu calendario no se guarda ni se envía a OpenAI.
      </Text>
      <Text style={styles.paragraph}>
        Te llega una notificación al día y, si después aparece algo que vence hoy, una más. Solo dice cuántas
        cosas hay de cada tipo, por ejemplo «2 pagos y 1 cita», y cuántos eventos tienes hoy: nunca de quién son,
        montos ni títulos. Queda en tu lista de notificaciones hasta que desconectes. Aparte, te aviso si tu
        Gmail se desconecta.
      </Text>
      <Text style={styles.paragraph}>
        Para eso, Confío envía a OpenAI (Estados Unidos) el remitente, el asunto, la fecha y el texto de los correos
        que analiza, además de tus preguntas e instrucciones. OpenAI no entrena modelos con ellos y puede
        conservarlos hasta 30 días para controlar abusos, o más si la ley o la seguridad lo exigen. Antes de enviarlos
        tapamos los códigos que detectamos y descartamos los correos que solo traen un código de acceso o un cambio
        de contraseña, pero esa detección puede fallar.
      </Text>
      <Text style={styles.paragraph}>
        Confío no guarda tus correos. Guarda cifrados tu acceso y tu dirección hasta que desconectes. De cada aviso
        guarda el tipo y la fecha y, cifrados, el monto, un resumen de una línea y el identificador del correo,
        hasta 30 días después de esa fecha (o de detectarlo, si no tiene fecha). Guarda cifrados los borradores sin enviar hasta 24 horas, con un
        margen de una hora.
      </Text>
      <Text style={styles.paragraph}>
        El equipo de Confío no lee tu correo, salvo que lo autorices o lo exijan la seguridad o la ley. El uso de los
        datos de Google sigue la Política de Datos de Usuario de los Servicios API de Google, incluido el uso
        limitado.
      </Text>
      {mail?.consentOutdated ? (
        <Text style={styles.paragraph}>
          Esto cambió desde que conectaste tu Gmail: ahora lee más correos y, si quieres, tu calendario. No leo
          nada hasta que lo aceptes.
        </Text>
      ) : null}
      <Link label="Leer la Política de Privacidad" onPress={() => Linking.openURL(PRIVACY_URL).catch(() => undefined)} />
      <Text style={styles.paragraph}>
        Es una prueba: Google mostrará un aviso de app en pruebas y tendrás que volver a conectar cada 7 días. Elige
        el Gmail que agregamos a la prueba: Google rechaza los demás.
      </Text>
      <Action label="Aceptar y conectar Gmail" onPress={connect} disabled={busy} />
    </>
  );

  const composer = (
    <>
      <Text style={styles.heading}>{replyTo ? 'Responder' : 'Escribir un correo'}</Text>
      {replyTo ? (
        <>
          <Text style={styles.detail}>{replyTo.subject} · {replyTo.sender}</Text>
          <Link label="Escribir uno nuevo" disabled={busy} onPress={() => setReplyTo(null)} />
        </>
      ) : (
        <TextInput
          style={styles.input}
          value={to}
          onChangeText={setTo}
          placeholder="Para: correo@ejemplo.com"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          accessibilityLabel="Para"
        />
      )}
      <TextInput
        style={[styles.input, styles.multiline]}
        value={instructions}
        onChangeText={setInstructions}
        placeholder="¿Qué quieres decir?"
        placeholderTextColor={colors.muted}
        multiline
        maxLength={1000}
        accessibilityLabel="Qué quieres decir"
      />
      <Text style={styles.detail}>Lo que escribas aquí se envía a OpenAI para redactar el correo.</Text>
      <Action label="Crear borrador" onPress={write} disabled={busy || !instructions.trim() || (!replyTo && !to.trim())} />
    </>
  );

  const connectedHome = mail && ready ? (
    <>
      <Text style={styles.detail}>{mail.email}</Text>
      <Text style={styles.heading}>Para atender</Text>
      {mail.needs.length ? null : <Text style={styles.detail}>No hay pendientes. Reviso tu correo cada 15 minutos.</Text>}
      {mail.needs.map((need) => (
        <View key={need.id} style={styles.row}>
          <Text style={styles.rowTitle}>{NEED_LABELS[need.kind] ?? 'Algo por atender'}</Text>
          {need.dueDate || need.amount ? (
            <Text style={styles.detail}>
              {[need.dueDate ? day(need.dueDate) : '', need.amount ? `${need.currency} ${need.amount} según el correo` : '']
                .filter(Boolean).join(' · ')}
            </Text>
          ) : null}
          {need.summary ? <Text style={styles.detail}>Según el correo: {need.summary}</Text> : null}
          {shown[need.id] ? source(shown[need.id]) : null}
          <View style={styles.links}>
            {shown[need.id] ? null : <Link label="Ver de quién es" disabled={busy} onPress={() => show(need)} />}
            <Link label="No me avises de esto" disabled={busy} onPress={() => dismiss(need)} />
          </View>
        </View>
      ))}
      {mail.canCalendar ? (
        <>
          <Text style={styles.heading}>Hoy y mañana en tu calendario</Text>
          {calendarFailed ? <Text style={styles.detail}>No pude leer tu calendario ahora.</Text> : null}
          {events === null && !calendarFailed ? <ActivityIndicator color={colors.successText} /> : null}
          {events && !events.length ? <Text style={styles.detail}>No tienes eventos.</Text> : null}
          {(events ?? []).map((event, index) => (
            <View key={`${event.day}-${event.startsAt ?? 'd'}-${index}`} style={styles.row}>
              <Text style={styles.rowTitle}>{event.title}</Text>
              <Text style={styles.detail}>
                {/* A timed event: day and hour both on this phone's clock, so they cannot disagree. */}
                {event.allDay || !event.startsAt
                  ? `${day(event.day)} · Todo el día`
                  : `${day(event.startsAt)} · ${hour(event.startsAt)}`}
              </Text>
            </View>
          ))}
        </>
      ) : (
        <>
          <Text style={styles.paragraph}>
            No diste permiso para ver tu calendario. El aviso diario cuenta solo tu correo.
          </Text>
          <Link label="Reconectar para incluir tu calendario" disabled={busy} onPress={connect} />
        </>
      )}
      <Text style={styles.heading}>Pregúntale a tu correo</Text>
      <TextInput
        style={styles.input}
        value={question}
        onChangeText={setQuestion}
        placeholder="¿Cuándo vence la luz?"
        placeholderTextColor={colors.muted}
        maxLength={1000}
        accessibilityLabel="Pregunta sobre tu correo"
      />
      <Action label="Preguntar" onPress={ask} disabled={busy || !question.trim()} />
      {answer ? (
        <>
          <Text style={styles.message}>{answer.text}</Text>
          <Text style={styles.detail}>
            Según tus correos. Puede equivocarse, y un correo puede mentir: revisa quién lo envió antes de pagar.
          </Text>
          {answer.sources.map(source)}
        </>
      ) : null}
    </>
  ) : null;

  let home: React.ReactNode;
  if (loading) {
    home = <ActivityIndicator color={colors.successText} />;
  } else if (failed || !mail) {
    // A failed query says nothing about who may use it, and must not hide the way out.
    home = (
      <>
        <Text style={styles.paragraph}>No pude cargar tu correo. Revisa tu conexión e inténtalo de nuevo.</Text>
        <Action label="Reintentar" onPress={() => { void attempt(reload); }} disabled={busy} />
        <Link label="Desconectar Gmail y borrar" disabled={busy} onPress={disconnect} />
      </>
    );
  } else if (!mail.available && !connected) {
    home = <Text style={styles.paragraph}>Tu correo en Confío IA todavía no está disponible para ti.</Text>;
  } else {
    home = (
      <>
        {mail.available && (!connected || mail.consentOutdated) ? intro : null}
        {mail.available && connected && mail.needsReconnect && !mail.consentOutdated ? (
          <>
            <Text style={styles.paragraph}>Tu conexión con Gmail venció. En la prueba pasa cada 7 días.</Text>
            <Action label="Volver a conectar Gmail" onPress={connect} disabled={busy} />
          </>
        ) : null}
        {connectedHome}
        {ready && !mail.canSend ? (
          <>
            <Text style={styles.paragraph}>No diste permiso para enviar. Tus borradores se abren en tu app de correo.</Text>
            <Link label="Reconectar para enviar desde aquí" disabled={busy} onPress={connect} />
          </>
        ) : null}
        {mail.available ? composer : null}
        {connected ? <Link label="Desconectar Gmail y borrar" disabled={busy} onPress={disconnect} /> : null}
      </>
    );
  }

  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <SafeAreaProvider>
        <SafeAreaView style={styles.screen}>
          <View style={styles.header}>
            <Text style={styles.title}>Tu correo</Text>
            <Pressable style={styles.close} onPress={onClose} accessibilityRole="button" accessibilityLabel="Cerrar">
              <Icon name="x" size={24} color={colors.textFlat} />
            </Pressable>
          </View>
          <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
            <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
              {draft ? (
                <MailDraftView
                  key={draft.id ?? draft.displayHash}
                  initial={draft}
                  onBack={() => setDraft(null)}
                  onSending={() => {
                    sending.current = saved.draft;
                    saved.draft = null;
                    saved.notice = 'El envío quedó en curso. Revisa tu carpeta Enviados antes de repetirlo.';
                  }}
                  onNotSent={() => {
                    saved.draft = sending.current;
                    saved.notice = null;
                  }}
                  onEdit={(edit) => {
                    if (saved.draft) {
                      saved.draft = { ...saved.draft, ...edit };
                    }
                  }}
                  onUnknown={(notice) => {
                    // Never offered again, also after a remount.
                    saved.draft = null;
                    saved.notice = notice;
                  }}
                  onSent={() => {
                    setDraft(null);
                    setReplyTo(null);
                    setTo('');
                    setInstructions('');
                    setMessage('Correo enviado.');
                    saved.notice = open.current ? null : 'Correo enviado.';
                  }}
                />
              ) : home}
              {busy ? <ActivityIndicator color={colors.successText} /> : null}
              {message && !draft ? <Text style={styles.message} accessibilityLiveRegion="polite">{message}</Text> : null}
            </ScrollView>
          </KeyboardAvoidingView>
        </SafeAreaView>
      </SafeAreaProvider>
    </Modal>
  );
}
