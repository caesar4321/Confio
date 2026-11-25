// Gmail in the Confío IA conversation, as WhatsApp is (../whatsapp/ChatCards.tsx): "Responder…" under a mail the
// assistant told, and the card a mail waits on until the person taps Enviar. The server wrote both
// (assistant/gmail/chat.py); a mail leaves only from the card, with the hash of exactly what it showed.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { useApolloClient } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Text, TextInput } from '../../components/common/AppText';
import GmailLogo from '../../components/svg/GmailLogo';
import { colors } from '../../config/theme';
import { PREPARE_MAIL_REPLY, SEND_DRAFT, SHOW_MAIL_DRAFT, type MailDraft } from './api';

export type ChatAction = { type: string; target?: string | null; label?: string | null };

const THREAD = ['GetAssistantThread'];
const FAILED = 'No pude preparar ese correo. Inténtalo de nuevo.';
const UNKNOWN = 'No sé si el correo salió. Revisa tu carpeta Enviados antes de repetirlo.';

/** "Responder…": she says what to answer, and the assistant writes the mail on a card for her to confirm. */
export function MailReplyChip({ actions }: { actions: ChatAction[] }) {
  const client = useApolloClient();
  const reply = actions.find((a) => a.type === 'mail_reply' && a.target);
  const [writing, setWriting] = useState(false);
  const [words, setWords] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  if (!reply) {
    return null;
  }
  const prepare = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const { data } = await client.mutate<any>({
        mutation: PREPARE_MAIL_REPLY, fetchPolicy: 'no-cache', refetchQueries: THREAD,
        variables: { needId: String(reply.target), instructions: words.trim() },
      });
      const result = data?.prepareAssistantMailReply;
      if (result?.success) {
        setWriting(false);
        setWords('');
      } else {
        setMessage(result?.error || FAILED);
      }
    } catch {
      setMessage(FAILED);
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={styles.replies}>
      {writing ? (
        <View style={styles.compose}>
          <TextInput
            style={styles.input}
            value={words}
            onChangeText={setWords}
            placeholder="¿Qué le respondo? Por ejemplo: que sí voy el viernes"
            placeholderTextColor={colors.muted}
            multiline
            maxLength={1500}
            autoFocus
            accessibilityLabel="Qué quieres responder"
          />
          <View style={styles.composeRow}>
            <Pressable style={styles.cancel} onPress={() => setWriting(false)} disabled={busy} accessibilityRole="button">
              <Text style={styles.cancelText}>Cancelar</Text>
            </Pressable>
            <Pressable
              style={({ pressed }) => [styles.write, pressed && styles.pressed, (busy || !words.trim()) && styles.disabled]}
              disabled={busy || !words.trim()}
              onPress={() => void prepare()}
              accessibilityRole="button"
            >
              {busy ? <ActivityIndicator size="small" color={colors.white} /> : <Icon name="edit-3" size={14} color={colors.white} />}
              <Text style={styles.writeText}>Escribirlo</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <Pressable
          style={({ pressed }) => [styles.replyChip, pressed && styles.pressed]}
          onPress={() => setWriting(true)}
          accessibilityRole="button"
          accessibilityLabel="Responder este correo"
        >
          <Icon name="corner-up-left" size={14} color={colors.successText} />
          <Text style={styles.replyText}>{reply.label || 'Responder…'}</Text>
        </Pressable>
      )}
      {message ? <Text style={styles.error}>{message}</Text> : null}
    </View>
  );
}

type CardState = 'loading' | 'ready' | 'sending' | 'sent' | 'unknown' | 'gone';

/** The mail as it will leave: from, to, subject and text, and Enviar. Changes are asked in the conversation. */
export function MailDraftCard({ draftId }: { draftId: string }) {
  const client = useApolloClient();
  const [draft, setDraft] = useState<MailDraft | null>(null);
  const [state, setState] = useState<CardState>('loading');
  const [message, setMessage] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => () => {
    mounted.current = false;
  }, []);

  const read = useCallback(async () => {
    try {
      const { data } = await client.mutate<any>({ mutation: SHOW_MAIL_DRAFT, variables: { id: draftId }, fetchPolicy: 'no-cache' });
      const result = data?.showAssistantMailDraft;
      if (!mounted.current) {
        return;
      }
      if (result?.success && result.draft) {
        setDraft(result.draft);
        setState('ready');
      } else {
        // Sent (it is deleted then), expired or tried: the conversation says how it went.
        setState(result?.errorCode === 'sent_unknown' ? 'unknown' : 'gone');
      }
    } catch {
      if (mounted.current) {
        setState('gone');
      }
    }
  }, [client, draftId]);
  useEffect(() => {
    void read();
  }, [read]);

  const send = async () => {
    if (!draft?.id || state !== 'ready') {
      return;
    }
    setState('sending');
    setMessage(null);
    try {
      const { data } = await client.mutate<any>({
        mutation: SEND_DRAFT, fetchPolicy: 'no-cache', refetchQueries: THREAD,
        variables: { id: draft.id, displayHash: draft.displayHash },
      });
      const result = data?.sendAssistantMailDraft;
      if (!mounted.current) {
        return;
      }
      if (result?.success) {
        setState('sent');
      } else if (result?.errorCode === 'sent_unknown') {
        setState('unknown');
      } else {
        setMessage(result?.error || 'Gmail no aceptó el correo. No se envió.');
        setState('ready');
      }
    } catch {
      // The answer was lost: it may have left. Never offered again.
      if (mounted.current) {
        setState('unknown');
      }
    }
  };

  if (state === 'gone') {
    return null;
  }
  if (state === 'loading' || !draft) {
    return <View style={styles.card}><ActivityIndicator color={colors.successText} /></View>;
  }
  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <GmailLogo size={18} />
        <Text style={styles.heading}>{draft.isReply ? 'Respuesta por Gmail' : 'Correo nuevo por Gmail'}</Text>
      </View>
      <View style={styles.mail}>
        <Line label="Para" value={draft.to} strong />
        {draft.sender ? <Line label="De" value={draft.sender} /> : null}
        <Line label="Asunto" value={draft.subject} />
        <Text style={styles.body} selectable>{draft.body}</Text>
      </View>
      {draft.replyToDiffers ? (
        <View style={styles.warn}>
          <Icon name="alert-triangle" size={14} color={colors.warning.icon} />
          <Text style={styles.warnText}>La respuesta va a una dirección distinta de quien lo envió. Revísala.</Text>
        </View>
      ) : null}
      {state === 'sent' ? (
        <View style={styles.done}>
          <Icon name="check-circle" size={16} color={colors.successText} />
          <Text style={styles.doneText}>Enviado desde tu Gmail</Text>
        </View>
      ) : null}
      {state === 'unknown' ? <Text style={styles.error} accessibilityLiveRegion="polite">{UNKNOWN}</Text> : null}
      {message ? <Text style={styles.error} accessibilityLiveRegion="polite">{message}</Text> : null}
      {(state === 'ready' || state === 'sending') && draft.canSend ? (
        <>
          <Pressable
            style={({ pressed }) => [styles.send, pressed && styles.pressed, state === 'sending' && styles.disabled]}
            disabled={state === 'sending'}
            onPress={() => void send()}
            accessibilityRole="button"
            accessibilityLabel="Enviar por Gmail"
          >
            {state === 'sending' ? <ActivityIndicator size="small" color={colors.white} /> : <Icon name="send" size={16} color={colors.white} />}
            <Text style={styles.sendText}>Enviar</Text>
          </Pressable>
          <Text style={styles.hint}>¿Algo distinto? Escríbeme cómo lo cambio.</Text>
        </>
      ) : null}
    </View>
  );
}

function Line({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <View style={styles.line}>
      <Text style={styles.lineLabel}>{label}</Text>
      <Text style={[styles.lineValue, strong && styles.lineStrong]} numberOfLines={2} selectable>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  replies: { marginTop: 8, gap: 8, alignItems: 'flex-start' },
  replyChip: {
    flexDirection: 'row', alignItems: 'center', gap: 8, maxWidth: '100%', borderRadius: 18, borderWidth: 1.5,
    borderColor: colors.primaryMuted, backgroundColor: colors.background, paddingHorizontal: 14, paddingVertical: 9,
  },
  replyText: { flexShrink: 1, fontSize: 14, fontWeight: '600', color: colors.primaryDeep },
  compose: { alignSelf: 'stretch', gap: 8, borderRadius: 16, borderWidth: 1, borderColor: colors.primaryMuted, padding: 10, backgroundColor: colors.background },
  input: { minHeight: 64, fontSize: 15, color: colors.textFlat, textAlignVertical: 'top', paddingHorizontal: 4 },
  composeRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 12 },
  cancel: { minHeight: 40, justifyContent: 'center', paddingHorizontal: 6 },
  cancelText: { fontSize: 14, fontWeight: '600', color: colors.textSecondary },
  write: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, borderRadius: 12, backgroundColor: colors.successText, paddingHorizontal: 14 },
  writeText: { color: colors.white, fontSize: 14, fontWeight: '700' },
  error: { fontSize: 13, color: colors.error.text },
  pressed: { opacity: 0.8 },
  disabled: { opacity: 0.5 },
  card: {
    marginTop: 8, borderRadius: 18, borderWidth: 1, borderColor: colors.primaryMuted, backgroundColor: colors.surface,
    padding: 12, gap: 10,
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  heading: { flex: 1, fontSize: 13, fontWeight: '700', color: colors.textSecondary },
  mail: { borderRadius: 14, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, padding: 12, gap: 6 },
  line: { flexDirection: 'row', gap: 8 },
  lineLabel: { width: 52, fontSize: 13, color: colors.textSecondary },
  lineValue: { flex: 1, fontSize: 13, color: colors.textFlat },
  lineStrong: { fontWeight: '700' },
  body: { fontSize: 15, color: colors.textFlat, lineHeight: 21, marginTop: 6 },
  warn: { flexDirection: 'row', gap: 6, alignItems: 'flex-start' },
  warnText: { flex: 1, fontSize: 12, color: colors.textSecondary },
  done: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  doneText: { fontSize: 14, fontWeight: '700', color: colors.successText },
  send: {
    flexDirection: 'row', gap: 8, minHeight: 46, borderRadius: 14, backgroundColor: colors.successText,
    alignItems: 'center', justifyContent: 'center',
  },
  sendText: { color: colors.white, fontSize: 15, fontWeight: '800' },
  hint: { fontSize: 12, color: colors.textSecondary },
});
