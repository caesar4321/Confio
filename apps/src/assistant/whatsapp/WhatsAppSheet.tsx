// The person's own WhatsApp: consent, the pairing code, what matters, and replies they approve one by one.
// Every message leaves only from "Enviar" on a card that shows the exact text and where it goes.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, KeyboardAvoidingView, Linking, Modal, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useApolloClient, type DocumentNode } from '@apollo/client';
import Clipboard from '@react-native-clipboard/clipboard';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';

import { Text, TextInput } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import {
  ACCEPT_WHATSAPP_CONSENT,
  CREATE_WHATSAPP_DRAFT,
  DISMISS_WHATSAPP_NOTICE,
  GET_WHATSAPP_DRAFT,
  REFRESH_WHATSAPP,
  SEND_WHATSAPP_DRAFT,
  START_WHATSAPP_LINK,
  UNLINK_WHATSAPP,
  WHATSAPP_CONSENT_VERSION,
  type WhatsAppDraft,
  type WhatsAppNotice,
} from './api';
import {
  CONSENT_DATA, CONSENT_POINTS, CONSENT_RISK, NOTICE_LABELS, PAIRING_STEPS, codeForCopy, consentText, draftView, mergeDraft,
  validPhone,
} from './rules';
import { SEND_TIMEOUT_MS, SENT_GRACE_MS, forgetWhatsAppSession, whatsAppSession } from './session';
import { useWhatsApp } from './useWhatsApp';

const FAILED = 'No pude completar eso con tu WhatsApp. Inténtalo de nuevo.';

type Props = { userId: string; onClose: () => void };

export default function WhatsAppSheet({ userId, onClose }: Props) {
  const client = useApolloClient();
  const { link, refetch } = useWhatsApp(userId, 'network-only', true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  // Typed by the person (sign-up proves no phone); the account's number only fills it in to start with.
  const [phone, setPhone] = useState<string | null>(null);
  const shownPhone = phone ?? link?.suggestedPhone ?? '+';
  // These survive the app lock (session.ts). The last known draft shows at once, then is read back.
  const saved = whatsAppSession(userId);
  const [replyingId, setReplyingIdState] = useState<string | null>(saved.replyingId);
  const [body, setBodyState] = useState(saved.body);
  const [draft, setDraftState] = useState<WhatsAppDraft | null>(saved.draft);
  const setReplyingId = (value: string | null) => { saved.replyingId = value; setReplyingIdState(value); };
  const setBody = (value: string) => { saved.body = value; setBodyState(value); };
  // Written to the session always, also while the lock has the sheet unmounted: what comes back must be true.
  const setDraft = useCallback((value: WhatsAppDraft | null) => {
    saved.draft = value;
    if (value && value.status !== 'draft') {
      saved.body = '';  // on its way or gone: the box never offers it again
    } else if (value && !saved.body) {
      saved.body = value.body;  // back to a draft (nothing was typed): its text to change, if they want
    }
    if (open.current) {
      setDraftState(value);
    }
  }, [saved]);
  const replying = link?.notices.find((notice) => notice.id === replyingId) ?? null;
  const open = useRef(true);
  useEffect(() => () => {
    open.current = false;
  }, []);

  const readDraft = useCallback(async (id: string) => {
    const mine = ++saved.reads;
    try {
      const { data } = await client.query<any>({ query: GET_WHATSAPP_DRAFT, variables: { id }, fetchPolicy: 'no-cache' });
      const now = (data?.whatsAppDraft ?? null) as WhatsAppDraft | null;
      // Only the newest answer counts (a slow "sending" never overwrites a "sent"), and only for the draft
      // still shown: one closed or replaced meanwhile never comes back.
      if (saved.draft?.id !== id) {
        // Changed meanwhile by another mount of this sheet (the lock): show what the session holds now.
        if (open.current) {
          setDraftState(saved.draft);
          setBodyState(saved.body);
        }
        return now;
      }
      if (mine !== saved.reads) {
        return now;
      }
      const tapped = saved.tapped?.id === id
        && (!saved.tapped.settled || Date.now() - saved.tapped.at < SENT_GRACE_MS);
      if (now?.status === 'draft' && tapped) {
        return now;  // read before the send reached the server: it stays on its way
      }
      if (!now && saved.draft?.status === 'sending' && ++saved.missing < 3) {
        return now;  // one empty answer is a hiccup, not "no sé si salió"
      }
      saved.missing = 0;
      setDraft(mergeDraft(saved.draft, now));
      return now;
    } catch {
      return undefined;  // unknown: what is shown (the last known draft) stays
    }
  }, [client, setDraft, saved]);

  // Back from the lock with a draft on its way or done: its true state, from the server.
  useEffect(() => {
    if (saved.draft) {
      void readDraft(saved.draft.id);
    }
    // Once, on mounting.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = useCallback(async (mutation: DocumentNode, field: string, variables?: Record<string, unknown>,
    onRefused?: (code: string) => void, timeoutMs?: number) => {
    setBusy(true);
    setMessage(null);
    // A mutation has no timeout of its own on the phone: one that must settle is given up on after timeoutMs.
    const abort = timeoutMs ? new AbortController() : null;
    const timer = abort ? setTimeout(() => abort.abort(), timeoutMs) : null;
    try {
      const { data } = await client.mutate<any>({
        mutation, variables, fetchPolicy: 'no-cache', context: abort ? { fetchOptions: { signal: abort.signal } } : undefined,
      });
      const result = data?.[field];
      if (result && !result.success && result.errorCode !== 'busy') {
        onRefused?.(String(result.errorCode || ''));  // a real answer, not "already on its way"
      }
      if (!result?.success && open.current) {
        setMessage(result?.error || FAILED);
      }
      return result?.success ? result : null;
    } catch {
      if (open.current) {
        setMessage(FAILED);
      }
      return null;
    } finally {
      if (timer) {
        clearTimeout(timer);
      }
      if (open.current) {
        setBusy(false);
      }
      refetch().catch(() => undefined);
    }
  }, [client, refetch]);

  // Opening asks for a fresh read of the chat list (the server decides if it is due).
  const linked = link?.state === 'linked';
  useEffect(() => {
    if (linked) {
      client.mutate({ mutation: REFRESH_WHATSAPP, fetchPolicy: 'no-cache' }).catch(() => undefined);
    }
  }, [linked, client]);

  // A sent draft is watched until it is no longer on its way.
  useEffect(() => {
    if (draft?.status !== 'sending') {
      return undefined;
    }
    const timer = setInterval(() => void readDraft(draft.id), 3000);
    return () => clearInterval(timer);
  }, [draft?.status, draft?.id, readDraft]);

  const unlinkNow = async () => {
    if (await run(UNLINK_WHATSAPP, 'unlinkWhatsApp')) {
      forgetWhatsAppSession(userId);  // nothing of this WhatsApp is carried into a next one
      if (open.current) {
        setDraftState(null);
        setReplyingIdState(null);
        setBodyState('');
      }
    }
  };
  const startLink = () => void run(START_WHATSAPP_LINK, 'startWhatsAppLink', {
    phone: shownPhone.replace(/[\s\-().]/g, ''), consentVersion: WHATSAPP_CONSENT_VERSION,
  });
  const unlink = () => {
    Alert.alert(
      '¿Desvincular tu WhatsApp?',
      'Cerramos la sesión de Confío en tu WhatsApp y borramos lo que guardamos de él.',
      [
        { text: 'Cancelar', style: 'cancel' },
        { text: 'Desvincular', style: 'destructive', onPress: () => void unlinkNow() },
      ],
    );
  };
  const prepare = async () => {
    if (!replying || !body.trim()) {
      return;
    }
    const result = await run(CREATE_WHATSAPP_DRAFT, 'createWhatsAppDraft', { noticeId: replying.id, body: body.trim() });
    if (result?.draft && open.current) {
      setDraft(result.draft);
    }
  };
  const send = async () => {
    if (!draft) {
      return;
    }
    const tapped = draft;
    // On its way from the tap: until the server says otherwise it is "sending", never a draft to send again.
    // A wrong "sending" only waits for the next read; a wrong "draft" could send it twice.
    saved.tapped = { id: tapped.id, at: Date.now(), settled: false };
    saved.reads += 1;  // a read already asked never lands after this
    saved.missing = 0;
    setDraft({ ...tapped, status: 'sending', reason: null });
    let refusal: string | null = null;
    const result = await run(SEND_WHATSAPP_DRAFT, 'sendWhatsAppDraft', { id: tapped.id, displayHash: tapped.displayHash },
      (code) => { refusal = code; }, SEND_TIMEOUT_MS);
    if (result?.draft) {
      // Accepted: every read from now on sees it on its way.
      saved.tapped = null;
      saved.reads += 1;
      setDraft(mergeDraft(saved.draft, result.draft));
      return;
    }
    if (refusal === 'not_found') {
      // Gone (expired, or replaced by a newer version): never sent. The text stays to write it again.
      saved.tapped = null;
      setBody(tapped.body);
      setDraft(null);
      return;
    }
    if (refusal !== null) {
      saved.tapped = null;  // the server said no: what it has is the truth, a draft included
    } else if (saved.tapped?.id === tapped.id) {
      saved.tapped = { ...saved.tapped, at: Date.now(), settled: true };  // no answer: the grace starts now
      if (open.current) {
        setMessage(null);  // not "inténtalo de nuevo": it may be on its way; the card says how it went
      }
    }
    // Refused, or the answer was lost: what the server has now (it may be on its way already).
    await readDraft(tapped.id);
  };
  const finishReply = () => {
    setReplyingId(null);
    setDraft(null);
    setBody('');
  };
  const sending = draft?.status === 'sending';

  const consent = (label: string, onPress: () => void) => (link && link.consentVersion > WHATSAPP_CONSENT_VERSION ? (
    <Text style={styles.text}>Actualiza la app para ver lo que cambió y seguir usando WhatsApp en Confío.</Text>
  ) : (
    <View style={styles.intro}>
      <View style={styles.hero}>
        <View style={styles.heroIcon}>
          <Icon name="message-circle" size={34} color={colors.successText} />
        </View>
        <Text style={styles.heroTitle} accessibilityRole="header">Tu WhatsApp, en Confío</Text>
      </View>
      <View style={styles.points}>
        {CONSENT_POINTS.map((point) => (
          <View key={point.text} style={styles.point}>
            <View style={styles.pointIcon}>
              <Icon name={point.icon} size={18} color={colors.successText} />
            </View>
            <Text style={styles.pointText}>{point.text}</Text>
          </View>
        ))}
      </View>
      <View style={styles.risk}>
        <Icon name="info" size={16} color={colors.gray600} />
        <Text style={styles.riskText}>{CONSENT_DATA}</Text>
      </View>
      <View style={styles.risk}>
        <Icon name="alert-triangle" size={16} color={colors.gray600} />
        <Text style={styles.riskText}>{CONSENT_RISK}</Text>
      </View>
      <Pressable
        style={styles.more}
        onPress={() => setDetails(!details)}
        accessibilityRole="button"
        accessibilityState={{ expanded: details }}
      >
        <Text style={styles.moreText}>{details ? 'Ocultar detalles' : 'Cómo funciona'}</Text>
        <Icon name={details ? 'chevron-up' : 'chevron-down'} size={16} color={colors.successText} />
      </Pressable>
      {details ? consentText().map((line) => <Text key={line} style={styles.detail}>{line}</Text>) : null}
      {onPress === startLink ? (
        <View style={styles.block}>
          <Text style={styles.label}>Tu número de WhatsApp, con el código de país</Text>
          <TextInput
            style={styles.phone}
            value={shownPhone}
            onChangeText={(value) => setPhone(value.startsWith('+') ? value : `+${value.replace(/^\+*/, '')}`)}
            keyboardType="phone-pad"
            autoComplete="tel"
            textContentType="telephoneNumber"
            maxLength={22}
            accessibilityLabel="Tu número de WhatsApp, con el código de país"
          />
        </View>
      ) : null}
      <Text style={styles.fine}>Al vincular aceptas cómo funciona. Lo desvinculas cuando quieras.</Text>
      <Action label={label} onPress={onPress} disabled={busy || (onPress === startLink && !validPhone(shownPhone))} />
    </View>
  ));

  let content: React.ReactNode = <ActivityIndicator color={colors.successText} />;
  if (link) {
    if (link.state === 'pairing') {
      const code = link.code;
      content = (
        <View style={styles.intro}>
          {code ? (
            <>
              <Text style={styles.heroTitle} accessibilityRole="header">Escribe este código en WhatsApp</Text>
              <View
                style={styles.cells}
                accessible
                accessibilityLabel={`Código ${codeForCopy(code).split('').join(' ')}`}
              >
                {codeForCopy(code).split('').map((char, index) => (
                  <React.Fragment key={`${index}-${char}`}>
                    {index === 4 ? <Text style={styles.dash}>-</Text> : null}
                    <View style={styles.cell}><Text style={styles.cellText} maxFontSizeMultiplier={1.3}>{char}</Text></View>
                  </React.Fragment>
                ))}
              </View>
              <View style={styles.row}>
                <Outline
                  label={copied === code ? 'Copiado' : 'Copiar código'}
                  icon={copied === code ? 'check' : 'copy'}
                  onPress={() => {
                    Clipboard.setString(codeForCopy(code));
                    setCopied(code);  // a new code shows "Copiar código" again
                  }}
                />
                <Outline label="Abrir WhatsApp" icon="external-link" onPress={() => void Linking.openURL('whatsapp://').catch(() => undefined)} />
              </View>
              <View style={styles.steps}>
                {PAIRING_STEPS.map((step, index) => (
                  <View key={step} style={styles.step}>
                    <View style={styles.stepNumber}><Text style={styles.stepNumberText}>{index + 1}</Text></View>
                    <Text style={styles.pointText}>{step}</Text>
                  </View>
                ))}
              </View>
              <View style={styles.waiting}>
                <ActivityIndicator color={colors.successText} />
                <Text style={styles.detail}>Esperando que lo escribas. El código se renueva solo.</Text>
              </View>
            </>
          ) : (
            <View style={styles.hero}>
              <ActivityIndicator size="large" color={colors.successText} />
              <Text style={styles.heroTitle}>Pidiendo tu código</Text>
              <Text style={styles.detail}>Tarda unos 30 segundos.</Text>
            </View>
          )}
          <Secondary label="Cancelar" onPress={() => void unlinkNow()} disabled={busy} />
        </View>
      );
    } else if (link.state === 'linked' && link.consentOutdated) {
      content = consent('Aceptar y seguir', () => void run(ACCEPT_WHATSAPP_CONSENT, 'acceptWhatsAppConsent', {
        consentVersion: WHATSAPP_CONSENT_VERSION,
      }));
    } else if (link.state === 'linked') {
      content = (
        <View style={styles.block}>
          <View style={styles.status}>
            <View style={styles.dot} />
            <Text style={styles.statusText}>
              {link.phoneHint ? `Vinculado · terminado en ${link.phoneHint}` : 'Vinculado'}
            </Text>
          </View>
          {draft && !replying ? (
            // Its notice is gone (dismissed, expired) while this reply is on its way: still shown.
            <Reply
              notice={null}
              body={body}
              setBody={setBody}
              draft={draft}
              busy={busy}
              prepare={() => undefined}
              send={() => void send()}
              edit={() => setDraft(null)}
              close={finishReply}
            />
          ) : null}
          {link.notices.length ? link.notices.map((notice) => (
            <View key={notice.id} style={styles.card}>
              <Text style={styles.kind}>{NOTICE_LABELS[notice.kind] ?? 'Parece importante'}</Text>
              <Text style={styles.chat}>{notice.chat}</Text>
              {notice.summary ? <Text style={styles.text}>{notice.summary}</Text> : null}
              <Text style={styles.preview} numberOfLines={3}>{`«${notice.preview}»`}</Text>
              {replying?.id === notice.id ? (
                <Reply
                  notice={notice}
                  body={body}
                  setBody={setBody}
                  draft={draft}
                  busy={busy}
                  prepare={() => void prepare()}
                  send={() => void send()}
                  edit={() => {
                    if (draft) {
                      setBody(draft.body);  // the text to change, also after a lock emptied the box
                    }
                    setDraft(null);
                  }}
                  close={finishReply}
                />
              ) : (
                <View style={styles.row}>
                  <Secondary
                    label="Responder"
                    a11y={`Responder a ${notice.chat}`}
                    onPress={() => { finishReply(); setReplyingId(notice.id); }}
                    disabled={busy || sending}
                  />
                  <Secondary
                    label="Listo"
                    a11y={`Listo: ${notice.chat}`}
                    onPress={() => void run(DISMISS_WHATSAPP_NOTICE, 'dismissWhatsAppNotice', { id: notice.id })}
                    disabled={busy || sending}
                  />
                </View>
              )}
            </View>
          )) : (
            <View style={styles.hero}>
              <Icon name="inbox" size={30} color={colors.textSecondary} />
              <Text style={styles.text}>Todo tranquilo. Te avisamos cuando llegue algo importante.</Text>
            </View>
          )}
          <Secondary label="Desvincular WhatsApp" onPress={unlink} disabled={busy} />
        </View>
      );
    } else {
      content = (
        <>
          {link.reasonMessage ? (
            <View style={styles.alert}>
              <Icon name="alert-circle" size={16} color={colors.textFlat} />
              <Text style={styles.alertText}>{link.reasonMessage}</Text>
            </View>
          ) : null}
          {consent(link.state === 'none' ? 'Vincular WhatsApp' : 'Vincular otra vez', startLink)}
        </>
      );
    }
  }

  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <SafeAreaProvider>
        <SafeAreaView style={styles.screen}>
          <View style={styles.header}>
            <Text style={styles.title}>{link?.state === 'linked' ? 'WhatsApp' : ''}</Text>
            <Pressable style={styles.close} onPress={onClose} accessibilityRole="button" accessibilityLabel="Cerrar">
              <Icon name="x" size={24} color={colors.textFlat} />
            </Pressable>
          </View>
          <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
            <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
              {content}
              {message ? <Text style={styles.message} accessibilityLiveRegion="polite">{message}</Text> : null}
            </ScrollView>
          </KeyboardAvoidingView>
        </SafeAreaView>
      </SafeAreaProvider>
    </Modal>
  );
}

type ReplyProps = {
  notice: WhatsAppNotice | null;
  body: string;
  setBody: (value: string) => void;
  draft: WhatsAppDraft | null;
  busy: boolean;
  prepare: () => void;
  send: () => void;
  edit: () => void;
  close: () => void;
};

function Reply({ notice, body, setBody, draft, busy, prepare, send, edit, close }: ReplyProps) {
  if (!draft && notice) {
    return (
      <View style={styles.block}>
        <TextInput
          style={styles.input}
          value={body}
          onChangeText={setBody}
          multiline
          maxLength={2000}
          placeholder="Escribe tu respuesta"
          accessibilityLabel={`Tu respuesta a ${notice.chat}`}
        />
        <Action label="Revisar antes de enviar" onPress={prepare} disabled={busy || !body.trim()} />
        <Secondary label="Cancelar" onPress={close} disabled={busy} />
      </View>
    );
  }
  if (!draft) {
    return null;
  }
  const view = draftView(draft);
  return (
    <View style={styles.approval}>
      <Text style={styles.label}>{view.heading}</Text>
      <Text style={styles.sent} selectable>{draft.body}</Text>
      {view.status ? <Text style={styles.detail} accessibilityLiveRegion="polite">{view.status}</Text> : null}
      {view.canSend ? (
        <>
          <Action label="Enviar" onPress={send} disabled={busy} />
          {notice
            ? <Secondary label="Cambiar el texto" onPress={edit} disabled={busy} />
            // Its message is gone from the list: no box to change it in, only to let it go.
            : <Secondary label="Descartar" onPress={close} disabled={busy} />}
        </>
      ) : null}
      {view.done ? <Secondary label="Cerrar" onPress={close} /> : null}
    </View>
  );
}

function Action({ label, onPress, disabled = false }: { label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable
      style={[styles.button, disabled && styles.disabled]}
      disabled={disabled}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ disabled }}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

function Outline({ label, icon, onPress }: { label: string; icon: string; onPress: () => void }) {
  return (
    <Pressable style={styles.outline} onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <Icon name={icon} size={16} color={colors.successText} />
      <Text style={styles.outlineText}>{label}</Text>
    </Pressable>
  );
}

function Secondary({ label, onPress, disabled = false, a11y }: {
  label: string; onPress: () => void; disabled?: boolean; a11y?: string;
}) {
  return (
    <Pressable
      style={styles.secondary}
      disabled={disabled}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={a11y ?? label}
      accessibilityState={{ disabled }}
    >
      <Text style={styles.secondaryText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 20 },
  title: { flex: 1, fontSize: 20, fontWeight: '700', color: colors.textFlat },
  close: { width: 52, height: 52, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 40, gap: 16 },
  block: { gap: 10 },
  waiting: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  card: { borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: 14, gap: 6 },
  approval: { borderRadius: 12, backgroundColor: colors.mint, padding: 12, gap: 8 },
  row: { flexDirection: 'row', gap: 16 },
  kind: { fontSize: 12, fontWeight: '600', color: colors.textSecondary },
  chat: { fontSize: 16, fontWeight: '700', color: colors.textFlat },
  preview: { fontSize: 14, color: colors.gray600, fontStyle: 'italic' },
  text: { fontSize: 14, color: colors.gray600 },
  label: { fontSize: 13, fontWeight: '600', color: colors.textSecondary },
  detail: { fontSize: 13, color: colors.textSecondary },
  message: { fontSize: 14, color: colors.textFlat },
  code: { fontSize: 36, fontWeight: '700', letterSpacing: 4, color: colors.primaryDeep, textAlign: 'center' },
  sent: { fontSize: 15, color: colors.textFlat },
  input: {
    minHeight: 88, borderRadius: 12, backgroundColor: colors.neutralDark, paddingHorizontal: 14, paddingVertical: 10,
    fontSize: 15, color: colors.textFlat, textAlignVertical: 'top',
  },
  button: { minHeight: 48, borderRadius: 14, backgroundColor: colors.successText, alignItems: 'center', justifyContent: 'center', padding: 12 },
  disabled: { opacity: 0.45 },
  buttonText: { color: colors.white, fontSize: 15, fontWeight: '700' },
  secondary: { minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  secondaryText: { color: colors.successText, fontSize: 14, fontWeight: '600' },
  intro: { gap: 16, paddingTop: 8 },
  hero: { alignItems: 'center', gap: 10, paddingVertical: 8 },
  heroIcon: { width: 72, height: 72, borderRadius: 36, backgroundColor: colors.mint, alignItems: 'center', justifyContent: 'center' },
  heroTitle: { fontSize: 22, fontWeight: '700', color: colors.textFlat, textAlign: 'center' },
  points: { gap: 12 },
  point: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  pointIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.mint, alignItems: 'center', justifyContent: 'center' },
  pointText: { flex: 1, fontSize: 15, color: colors.textFlat },
  risk: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', backgroundColor: colors.neutralDark, borderRadius: 12, padding: 12 },
  riskText: { flex: 1, fontSize: 13, color: colors.gray600 },
  more: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start', minHeight: 44 },
  moreText: { color: colors.successText, fontSize: 14, fontWeight: '600' },
  fine: { fontSize: 12, color: colors.textSecondary, textAlign: 'center' },
  cells: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 4 },
  // Shrinks on small screens (8 cells + a dash must fit 280 dp), never past 30.
  cell: {
    flexShrink: 1, flexBasis: 34, minWidth: 28, maxWidth: 34, height: 46, borderRadius: 10, borderWidth: 1.5, borderColor: colors.primaryMuted, backgroundColor: colors.mint,
    alignItems: 'center', justifyContent: 'center',
  },
  cellText: { fontSize: 22, fontWeight: '700', color: colors.primaryDeep },
  dash: { fontSize: 22, fontWeight: '700', color: colors.textSecondary },
  outline: {
    flex: 1, flexDirection: 'row', gap: 6, minHeight: 46, borderRadius: 14, borderWidth: 1.5, borderColor: colors.successText,
    alignItems: 'center', justifyContent: 'center', paddingHorizontal: 10,
  },
  outlineText: { color: colors.successText, fontSize: 14, fontWeight: '700' },
  steps: { gap: 10, backgroundColor: colors.surface, borderRadius: 14, padding: 14 },
  step: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  stepNumber: { width: 24, height: 24, borderRadius: 12, backgroundColor: colors.successText, alignItems: 'center', justifyContent: 'center' },
  stepNumberText: { color: colors.white, fontSize: 13, fontWeight: '700' },
  status: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start', backgroundColor: colors.mint, borderRadius: 14, paddingHorizontal: 12, paddingVertical: 6 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.successText },
  statusText: { fontSize: 13, fontWeight: '600', color: colors.primaryDeep },
  alert: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', backgroundColor: '#FEE2E2', borderRadius: 12, padding: 12 },
  alertText: { flex: 1, fontSize: 14, color: colors.textFlat },
  phone: {
    minHeight: 52, borderRadius: 14, backgroundColor: colors.neutralDark, paddingHorizontal: 16, fontSize: 20,
    fontWeight: '600', color: colors.textFlat, letterSpacing: 1,
  },
});
