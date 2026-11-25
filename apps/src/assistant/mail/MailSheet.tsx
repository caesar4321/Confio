// Gmail, in WhatsApp's design: consent, connect, and the connection. What needs the person is told in the
// Confío IA conversation and answered there (assistant/gmail/chat.py): this screen only manages the connection.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert as NativeAlert, Linking, StyleSheet, View } from 'react-native';
import { useApolloClient, type DocumentNode } from '@apollo/client';

import { Text } from '../../components/common/AppText';
import GmailLogo from '../../components/svg/GmailLogo';
import { colors } from '../../config/theme';
import SetupScreen, { Action, Danger, Details, Fine, Notes, Points, Secondary, setupStyles, type Hero } from '../connections/SetupScreen';
import { DISCONNECT, GET_MAIL, MAIL_CONSENT_VERSION, START_CONNECT, type MailState } from './api';
import { finishMailConnect } from './connectFlow';
import { onMailConnectResult } from './connectLink';
import { CONSENT_DATA, CONSENT_POINTS, CONSENT_RISK, LINKED_POINTS, consentText } from './rules';
import { mailSession } from './session';
import { saveVerifier } from './verifier';

const FAILED = 'No pude completar eso con tu correo. Inténtalo de nuevo.';
const GOOGLE_AUTH = 'https://accounts.google.com/';
const PRIVACY_URL = 'https://confio.lat/privacy';

type Props = { userId: string; onClose: () => void };

export default function MailSheet({ userId, onClose }: Props) {
  const client = useApolloClient();
  const [mail, setMail] = useState<MailState | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const open = useRef(true);

  const run = useCallback(async (mutation: DocumentNode, field: string, variables?: Record<string, unknown>) => {
    const { data } = await client.mutate<any>({ mutation, variables, fetchPolicy: 'no-cache' });
    const result = data?.[field];
    if (!result?.success) {
      if (open.current) {
        setMessage(result?.error || FAILED);
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
    setNote(null);
    try {
      await task();
    } catch {
      setMessage(FAILED);
    } finally {
      if (open.current) {
        setBusy(false);
      }
    }
  }, []);

  const finishConnect = useCallback(async () => {
    const work = finishMailConnect(client, userId);
    if (work) {
      setBusy(true);
      await work;
    }
    if (!open.current) {
      return; // the notice waits in the session
    }
    setBusy(false);
    await reload();
    const session = mailSession(userId);
    if (open.current && session.notice) {
      setNote(session.notice);
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

  const disconnectNow = () => attempt(async () => {
    const result = await run(DISCONNECT, 'disconnectAssistantMail');
    if (!result) {
      return;
    }
    await reload();
    setNote(result.revoked
      ? 'Gmail desconectado. Borré el acceso, los avisos, los borradores y lo que te conté de tu correo.'
      : 'Borré todo en Confío, pero Google no confirmó. Quita también a Confío en myaccount.google.com/permissions.');
  });
  const disconnect = () => NativeAlert.alert(
    '¿Desconectar tu Gmail?',
    'Dejo de leer tu correo y borro el acceso, los avisos, los borradores y lo que te conté de él.',
    [{ text: 'Cancelar', style: 'cancel' }, { text: 'Desconectar', style: 'destructive', onPress: () => void disconnectNow() }],
  );

  const consent = (
    <>
      <Points points={CONSENT_POINTS} />
      <Notes data={CONSENT_DATA} risk={CONSENT_RISK} />
      <Details lines={consentText()} />
      <Secondary label="Leer la Política de Privacidad" onPress={() => void Linking.openURL(PRIVACY_URL).catch(() => undefined)} />
    </>
  );

  const connected = !!mail?.connected;
  // Connected under an older text (2): mail keeps being read, but telling it here needs this build's (3).
  const outdated = !!mail && (mail.consentOutdated || (connected && (mail.consentVersion ?? MAIL_CONSENT_VERSION) < MAIL_CONSENT_VERSION));
  let hero: Hero = { title: 'Gmail' };
  let content: React.ReactNode = <ActivityIndicator color={colors.successText} style={styles.loading} />;
  let footer: React.ReactNode = null;
  if (!loading) {
    if (failed || !mail) {
      // A failed read says nothing about who may use it, and must not hide the way out.
      content = <Text style={setupStyles.text}>No pude cargar tu correo. Revisa tu conexión e inténtalo de nuevo.</Text>;
      footer = (
        <>
          <Action label="Reintentar" onPress={() => { void attempt(reload); }} busy={busy} />
          <Secondary label="Desconectar Gmail y borrar" onPress={() => void disconnectNow()} disabled={busy} />
        </>
      );
    } else if (!mail.available && !connected) {
      hero = { title: 'Tu Gmail, en Confío', chip: 'Sin cupos por ahora' };
      content = (
        <>
          <Points points={CONSENT_POINTS} />
          <Text style={setupStyles.text}>Los cupos de esta prueba se terminaron. Te aviso si se abren más.</Text>
        </>
      );
      footer = <Action label="Ir a mi conversación" onPress={onClose} />;
    } else if (!connected || outdated) {
      hero = connected
        ? { title: 'Revisa lo que cambió', chip: 'En pausa' }
        : { title: 'Tu Gmail, en Confío', chip: 'Prueba · 100 cupos' };
      content = (
        <>
          {connected ? (
            <Text style={setupStyles.text}>
              Ahora te cuento lo importante en nuestra conversación y ahí me pides responder. No leo nada hasta que lo aceptes.
            </Text>
          ) : null}
          {consent}
        </>
      );
      footer = (
        <>
          <Action label={connected ? 'Aceptar y reconectar' : 'Conectar Gmail'} onPress={connect} busy={busy} />
          <Fine text="Al conectar aceptas cómo funciona. Lo desconectas cuando quieras." />
        </>
      );
    } else if (mail.needsReconnect && !outdated) {
      hero = { title: 'Vuelve a conectar Gmail', chip: 'En pausa' };
      content = (
        <>
          <Text style={setupStyles.text}>Google cerró el acceso de Confío a tu Gmail. Reconéctalo para seguir recibiendo avisos.</Text>
          <Danger label="Desconectar Gmail y borrar" onPress={disconnect} disabled={busy} />
        </>
      );
      footer = <Action label="Reconectar Gmail" onPress={connect} busy={busy} />;
    } else {
      hero = { title: 'Gmail conectado', chip: mail.email ? `Activo · ${mail.email}` : 'Activo', live: true };
      content = (
        <>
          <Points points={LINKED_POINTS} />
          <View style={[setupStyles.card, styles.permissions]}>
            <Permission on={mail.canSend} text={mail.canSend ? 'Puedes enviar correos desde Confío' : 'Sin permiso para enviar correos'} />
            <Permission on={mail.canCalendar} text={mail.canCalendar ? 'Cuento tus eventos de hoy de Google Calendar' : 'Sin permiso de calendario'} divider />
          </View>
          {!mail.canSend || !mail.canCalendar ? (
            <Secondary label="Reconectar para dar los permisos" onPress={connect} disabled={busy} />
          ) : null}
          <Text style={setupStyles.hint}>Reviso tu correo cada 15 minutos.</Text>
          <Danger label="Desconectar Gmail" onPress={disconnect} disabled={busy} />
        </>
      );
      footer = <Action label="Ir a mi conversación" onPress={onClose} />;
    }
  }

  return (
    <SetupScreen logo={<GmailLogo size={34} />} hero={hero} onClose={onClose} footer={footer} message={message}>
      {note ? <Text style={styles.note} accessibilityLiveRegion="polite">{note}</Text> : null}
      {content}
    </SetupScreen>
  );
}

function Permission({ on, text, divider = false }: { on: boolean; text: string; divider?: boolean }) {
  return (
    <View style={[styles.permission, divider && setupStyles.divider]}>
      <View style={[styles.dot, on ? styles.dotOn : styles.dotOff]} />
      <Text style={styles.permissionText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  loading: { marginTop: 40 },
  note: { fontSize: 14, fontWeight: '600', color: colors.primaryDeep, backgroundColor: colors.mint, borderRadius: 14, padding: 12 },
  permissions: { paddingVertical: 2 },
  permission: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 12 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  dotOn: { backgroundColor: colors.successText },
  dotOff: { backgroundColor: colors.border },
  permissionText: { flex: 1, fontSize: 14, color: colors.textFlat },
});
