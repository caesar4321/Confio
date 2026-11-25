// WhatsApp in the Confío IA conversation: the replies the assistant offers under a message that arrived, and the
// card a reply waits on until the person taps Enviar. The server wrote both (whatsapp_link/chat.py); a reply
// leaves only from the card, with the hash of exactly what it showed.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { useApolloClient, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import WhatsAppLogo from '../../assets/svg/WhatsApp.svg';
import { Text, TextInput } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import {
  GET_WHATSAPP, GET_WHATSAPP_DRAFT, PREPARE_WHATSAPP_REPLY, SEND_WHATSAPP_DRAFT, type WhatsAppDraft, type WhatsAppNotice,
} from './api';
import { NOTICE_LABELS, draftView, mergeDraft } from './rules';
import { openWhatsAppFromNotification } from '../connections/store';

export type ChatAction = { type: string; target?: string | null; label?: string | null };

const THREAD = ['GetAssistantThread'];
const FAILED = 'No pude preparar esa respuesta. Inténtalo de nuevo.';

const KIND_ICONS: Record<string, string> = {
  payment: 'dollar-sign', order: 'shopping-bag', delivery: 'truck', appointment: 'calendar', reply: 'message-circle',
  urgent: 'alert-circle',
};

/** The notice a Confío IA message tells about (action whatsapp_notice), or null: the message then shows its text. */
export function noticeAction(actions: ChatAction[]): ChatAction | null {
  return actions.find((a) => a.type === 'whatsapp_notice' && a.target) ?? null;
}

/** A WhatsApp message told in the conversation, drawn like one: who wrote and when, their words as an incoming
 * bubble, what it seems to be. Read from the WhatsApp data the app already has; `fallback` (the message's own
 * text) when that notice is gone (dismissed, unlinked). */
export function WhatsAppNoticeCard({ action, fallback }: { action: ChatAction; fallback: string }) {
  const { data } = useQuery<any>(GET_WHATSAPP, { fetchPolicy: 'cache-first', errorPolicy: 'ignore' });
  const notice = ((data?.whatsAppLink?.notices ?? []) as WhatsAppNotice[]).find((n) => n.id === String(action.target));
  if (!notice) {
    return <Text style={styles.fallback}>{fallback}</Text>;
  }
  const followUp = action.label === 'siguió';
  return (
    <View style={styles.notice}>
      <View style={styles.noticeHead}>
        <WhatsAppLogo width={18} height={18} />
        <Text style={styles.noticeFrom} numberOfLines={1}>{notice.chat || 'WhatsApp'}</Text>
        {notice.time ? <Text style={styles.noticeTime}>{notice.time}</Text> : null}
      </View>
      {followUp ? <Text style={styles.noticeNote}>siguió escribiendo</Text> : null}
      <View style={styles.incoming}>
        <Text style={styles.incomingText}>{notice.preview}</Text>
      </View>
      <View style={styles.kindRow}>
        <View style={styles.kindChip}>
          <Icon name={KIND_ICONS[notice.kind] ?? 'star'} size={12} color={colors.primaryDeep} />
          <Text style={styles.kindText}>{NOTICE_LABELS[notice.kind] ?? 'Parece importante'}</Text>
        </View>
      </View>
      {notice.summary ? <Text style={styles.summary}>{notice.summary}</Text> : null}
      <Text style={styles.ask}>¿Qué le respondo?</Text>
    </View>
  );
}

const OTHER = '__other__';

/** The replies offered under a WhatsApp message, and "Otro": one tap puts a reply on a card (nothing is sent yet);
 * "Otro" takes what she wants to say, and the assistant writes the full reply on the card for her to confirm. */
export function WhatsAppReplyChips({ actions }: { actions: ChatAction[] }) {
  const client = useApolloClient();
  const replies = actions.filter((a) => a.type === 'whatsapp_reply' && a.target && a.label);
  const other = actions.find((a) => a.type === 'whatsapp_other' && a.target);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [writing, setWriting] = useState(false);
  const [words, setWords] = useState('');
  if (!replies.length && !other) {
    return null;
  }
  const choose = async (noticeId: string, body: string | null, instructions?: string) => {
    setBusy(instructions ? OTHER : body);
    setMessage(null);
    try {
      const { data } = await client.mutate<any>({
        mutation: PREPARE_WHATSAPP_REPLY, fetchPolicy: 'no-cache', refetchQueries: THREAD,
        variables: instructions ? { noticeId, instructions } : { noticeId, body },
      });
      const result = data?.prepareWhatsAppReply;
      if (!result?.success) {
        setMessage(result?.error || FAILED);
      }
      return !!result?.success;
    } catch {
      setMessage(FAILED);
      return false;
    } finally {
      setBusy(null);
    }
  };
  return (
    <View style={styles.replies}>
      {replies.map((a) => (
        <Pressable
          key={`${a.target}:${a.label}`}
          style={({ pressed }) => [styles.replyChip, pressed && styles.pressed, busy !== null && styles.disabled]}
          disabled={busy !== null}
          onPress={() => void choose(String(a.target), String(a.label))}
          accessibilityRole="button"
          accessibilityLabel={`Responder: ${a.label}`}
        >
          {busy === a.label ? <ActivityIndicator size="small" color={colors.successText} />
            : <Icon name="corner-up-left" size={14} color={colors.successText} />}
          <Text style={styles.replyText}>{a.label}</Text>
        </Pressable>
      ))}
      {other && !writing ? (
        <Pressable
          style={({ pressed }) => [styles.replyChip, styles.otherChip, pressed && styles.pressed, busy !== null && styles.disabled]}
          disabled={busy !== null}
          onPress={() => setWriting(true)}
          accessibilityRole="button"
          accessibilityLabel="Otra respuesta"
        >
          <Icon name="edit-3" size={14} color={colors.successText} />
          <Text style={styles.replyText}>Otro…</Text>
        </Pressable>
      ) : null}
      {other && writing ? (
        <View style={styles.compose}>
          <TextInput
            style={styles.input}
            value={words}
            onChangeText={setWords}
            placeholder="¿Qué le quieres decir? Ej.: que paso mañana en la tarde"
            placeholderTextColor={colors.muted}
            multiline
            maxLength={500}
            autoFocus
            accessibilityLabel="Qué quieres responder"
          />
          <View style={styles.composeRow}>
            <Pressable onPress={() => { setWriting(false); setWords(''); }} style={styles.cancel} accessibilityRole="button">
              <Text style={styles.cancelText}>Cancelar</Text>
            </Pressable>
            <Pressable
              style={({ pressed }) => [styles.write, pressed && styles.pressed, (!words.trim() || busy !== null) && styles.disabled]}
              disabled={!words.trim() || busy !== null}
              onPress={async () => {
                // Kept on a failure: what she wrote is never lost.
                if (await choose(String(other.target), null, words.trim())) {
                  setWriting(false);
                  setWords('');
                }
              }}
              accessibilityRole="button"
              accessibilityLabel="Preparar respuesta"
            >
              {busy === OTHER ? <ActivityIndicator size="small" color={colors.white} />
                : <Icon name="feather" size={15} color={colors.white} />}
              <Text style={styles.writeText}>Preparar respuesta</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
      {message ? <Text style={styles.error}>{message}</Text> : null}
    </View>
  );
}

/** The assistant asked to review a changed WhatsApp text (whatsapp_link/chat.ask_consent): opens that screen. */
export function WhatsAppConsentChip({ actions }: { actions: ChatAction[] }) {
  if (!actions.some((a) => a.type === 'whatsapp_consent')) {
    return null;
  }
  return (
    <Pressable
      style={({ pressed }) => [styles.send, styles.consent, pressed && styles.pressed]}
      onPress={() => openWhatsAppFromNotification()}
      accessibilityRole="button"
      accessibilityLabel="Revisar lo nuevo de WhatsApp"
    >
      <Icon name="file-text" size={16} color={colors.white} />
      <Text style={styles.sendText}>Revisar</Text>
    </Pressable>
  );
}

// Taps on a card, per draft, outside React: a card drawn again (a thread refetch) never offers Enviar twice.
const tapped = new Set<string>();

/** The card of a prepared reply: where it goes, the exact text, and Enviar. */
export function WhatsAppDraftCard({ draftId }: { draftId: string }) {
  const client = useApolloClient();
  const [draft, setDraft] = useState<WhatsAppDraft | null>(null);
  const [gone, setGone] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const known = useRef<WhatsAppDraft | null>(null);
  const mounted = useRef(true);
  useEffect(() => () => {
    mounted.current = false;
  }, []);

  // The latest client without re-reading on every render (a new client object is not a new draft).
  const clientRef = useRef(client);
  clientRef.current = client;
  const read = useCallback(async () => {
    try {
      const { data } = await clientRef.current.query<any>({ query: GET_WHATSAPP_DRAFT, variables: { id: draftId }, fetchPolicy: 'no-cache' });
      const now = (data?.whatsAppDraft ?? null) as WhatsAppDraft | null;
      const merged = mergeDraft(known.current, now);
      known.current = merged;
      if (mounted.current) {
        setDraft(merged);
        setGone(!merged);
      }
    } catch {
      // unknown: what is shown stays
    }
  }, [draftId]);

  useEffect(() => {
    void read();
  }, [read]);

  // On its way: read until it is not.
  useEffect(() => {
    if (draft?.status !== 'sending') {
      return undefined;
    }
    const timer = setInterval(() => void read(), 3000);
    return () => clearInterval(timer);
  }, [draft?.status, read]);

  // Done while this card watched it go: the assistant's line about it appears in the conversation. A card drawn
  // already done (the conversation opened again) asks nothing.
  const watched = useRef(false);
  if (draft?.status === 'sending') {
    watched.current = true;
  }
  const done = !!draft && draft.status !== 'draft' && draft.status !== 'sending';
  useEffect(() => {
    if (done && watched.current) {
      watched.current = false;
      void clientRef.current.refetchQueries({ include: THREAD }).catch(() => undefined);
    }
  }, [done]);

  const send = async () => {
    if (!draft || tapped.has(draft.id)) {
      return;
    }
    tapped.add(draft.id);
    let lost = false;
    setSending(true);
    setMessage(null);
    known.current = { ...draft, status: 'sending', reason: null };
    setDraft(known.current);
    try {
      const { data } = await client.mutate<any>({
        mutation: SEND_WHATSAPP_DRAFT, variables: { id: draft.id, displayHash: draft.displayHash }, fetchPolicy: 'no-cache',
      });
      const result = data?.sendWhatsAppDraft;
      if (result?.draft) {
        known.current = mergeDraft(known.current, result.draft);
      } else if (!result?.success && result?.errorCode !== 'busy') {
        // A plain refusal (changed, limit, not linked): nothing left; it can be tapped again.
        tapped.delete(draft.id);
        known.current = { ...draft };
        if (mounted.current) {
          setMessage(result?.error || null);
        }
      }
      if (mounted.current) {
        setDraft(known.current);
      }
    } catch {
      // The answer was lost: it may be on its way. The read below says how it went; never sent twice.
      lost = true;
    } finally {
      if (mounted.current) {
        setSending(false);
      }
      await read();
      // Lost, and the server still has it as an unsent draft: it never arrived, so it may be tapped again.
      if (lost && known.current?.status === 'draft') {
        tapped.delete(draft.id);
        if (mounted.current) {
          setDraft({ ...known.current });
        }
      }
    }
  };

  if (gone) {
    return null;
  }
  if (!draft) {
    return <View style={styles.card}><ActivityIndicator color={colors.successText} /></View>;
  }
  const view = draftView(draft);
  const canSend = view.canSend && !tapped.has(draft.id);
  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <WhatsAppLogo width={18} height={18} />
        <Text style={styles.heading}>{view.heading}</Text>
      </View>
      <View style={styles.bubble}>
        <Text style={styles.body} selectable>{draft.body}</Text>
        {draft.status === 'sent' ? <Icon name="check" size={14} color={colors.successText} style={styles.tick} /> : null}
      </View>
      {view.status && draft.status !== 'draft' ? <Text style={styles.status} accessibilityLiveRegion="polite">{view.status}</Text> : null}
      {message ? <Text style={styles.error}>{message}</Text> : null}
      {canSend ? (
        <Pressable
          style={({ pressed }) => [styles.send, pressed && styles.pressed, sending && styles.disabled]}
          disabled={sending}
          onPress={() => void send()}
          accessibilityRole="button"
          accessibilityLabel="Enviar por WhatsApp"
        >
          <Icon name="send" size={16} color={colors.white} />
          <Text style={styles.sendText}>Enviar</Text>
        </Pressable>
      ) : null}
      {canSend ? <Text style={styles.hint}>¿Algo distinto? Escríbeme cómo lo cambio.</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  replies: { marginTop: 8, gap: 8, alignItems: 'flex-start' },
  fallback: { fontSize: 16, lineHeight: 23, color: colors.textFlat },
  notice: { gap: 8, minWidth: 220 },
  noticeHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  noticeFrom: { flex: 1, fontSize: 16, fontWeight: '800', color: colors.textFlat },
  noticeTime: { fontSize: 12, color: colors.textSecondary },
  noticeNote: { marginTop: -4, fontSize: 12, fontWeight: '600', color: colors.textSecondary },
  incoming: {
    alignSelf: 'flex-start', maxWidth: '100%', backgroundColor: colors.white, borderRadius: 14, borderTopLeftRadius: 4,
    paddingHorizontal: 12, paddingVertical: 8, shadowColor: '#064E3B', shadowOpacity: 0.06, shadowRadius: 4,
    shadowOffset: { width: 0, height: 1 }, elevation: 1,
  },
  incomingText: { fontSize: 15, lineHeight: 21, color: colors.textFlat },
  kindRow: { flexDirection: 'row' },
  kindChip: {
    flexDirection: 'row', alignItems: 'center', gap: 5, backgroundColor: colors.mint, borderRadius: 999,
    paddingHorizontal: 9, paddingVertical: 4,
  },
  kindText: { fontSize: 12, fontWeight: '700', color: colors.primaryDeep },
  summary: { fontSize: 14, lineHeight: 20, color: colors.gray600 },
  ask: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  replyChip: {
    flexDirection: 'row', alignItems: 'center', gap: 8, maxWidth: '100%', borderRadius: 18, borderWidth: 1.5,
    borderColor: colors.primaryMuted, backgroundColor: colors.background, paddingHorizontal: 14, paddingVertical: 9,
  },
  replyText: { flexShrink: 1, fontSize: 14, fontWeight: '600', color: colors.primaryDeep },
  hint: { fontSize: 12, color: colors.textSecondary },
  otherChip: { borderStyle: 'dashed' },
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
  bubble: {
    alignSelf: 'flex-end', maxWidth: '92%', backgroundColor: '#D9FDD3', borderRadius: 14, borderTopRightRadius: 4,
    paddingHorizontal: 12, paddingVertical: 8, flexDirection: 'row', alignItems: 'flex-end', gap: 6,
  },
  body: { flexShrink: 1, fontSize: 15, color: colors.textFlat, lineHeight: 20 },
  tick: { marginBottom: 2 },
  status: { fontSize: 13, color: colors.textSecondary },
  send: {
    flexDirection: 'row', gap: 8, minHeight: 46, borderRadius: 14, backgroundColor: colors.successText,
    alignItems: 'center', justifyContent: 'center',
  },
  sendText: { color: colors.white, fontSize: 15, fontWeight: '800' },
  consent: { marginTop: 8, alignSelf: 'flex-start', paddingHorizontal: 18 },
});
