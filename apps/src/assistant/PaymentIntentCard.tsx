// A prepared payment in the conversation, and the sheet where the person
// reviews it (docs/designs/ai-assistant-first-redesign.md, "Option C").
//
// Both are drawn from the server's row for this message and from nothing
// else: the assistant's words never reach them. The card shows who is paid,
// how far that name is vouched for, what they receive and what it costs; the
// sheet repeats it in full, and its one button is the approval.
//
// Approving closes the sheet FIRST and then runs on the card (checking that
// nothing changed, Confío Face, signing): iOS shows one modal at a time, so
// Confío Face could never open over the sheet, and a sheet waiting on it
// could never be closed. For the same reason a card inside the floating box
// (itself a modal) does not approve there: it takes the person to Inicio,
// where the same card is in the conversation.
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text } from '../components/common/AppText';
import { navigationRef } from '../navigation/RootNavigation';
import {
  GET_MESSAGE_PAYMENT_INTENT, PaymentIntentError, approvePaymentIntent, cancelPaymentIntent, intentState,
  payeeLevelLine, requotePaymentIntent, timeLeft, trackPaymentIntent, type PaymentIntent,
} from '../services/paymentIntent';
import { formatDecimal } from '../utils/numberLocale';
import { exactSurplusNote } from './paymentIntentNotes';

const EMERALD = '#047857';
const INK = '#111827';
const MUTED = '#4B5563';
const AMBER = '#B45309';

// Every cent, always: "Recibe exactamente 150,50 BRL" must not read "150,5".
const amount = (value: string) => formatDecimal(value, { decimals: 2 });
const usd = (value: string) => `US$${amount(value)}`;
const local = (intent: PaymentIntent, value = intent.amountLocal) => `${amount(value)} ${intent.currency}`;
const STAGES = { checking: 'Revisando que nada cambió…', face: 'Confirma con tu rostro', signing: 'Firmando el pago…' } as const;
// The sheet's own slide-out, before anything else may present.
const SHEET_CLOSES_MS = 400;
// After an approval, how long the card asks the server about it often.
const WATCH_MS = 3 * 60 * 1000;
// Past that, while the server still says money is moving, it keeps asking, less often: a payment that takes
// longer than the watch (a SPEI paid at 3 min 2 s, 2026-11-24) is never left saying "Pagando…".
const SLOW_POLL_MS = 20 * 1000;

/** Re-renders once a second while `until` is ahead, for the countdown. */
function useCountdown(until: string | undefined, running: boolean) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!running || !until || Date.parse(until) <= Date.now()) {
      return undefined;
    }
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [until, running]);
}

function PayeeLevel({ intent }: { intent: PaymentIntent }) {
  const level = payeeLevelLine(intent);
  return (
    <View style={styles.level}>
      <Icon name={level.verified ? 'check-circle' : 'alert-triangle'} size={14} color={level.verified ? EMERALD : AMBER} />
      <Text style={[styles.levelText, !level.verified && styles.levelTextWarn]}>{level.text}</Text>
    </View>
  );
}

function Line({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <View style={styles.line}>
      <Text style={styles.lineLabel}>{label}</Text>
      <Text style={[styles.lineValue, strong && styles.lineValueStrong]}>{value}</Text>
    </View>
  );
}

/** The review. Its button only says "yes, these figures": the card does the rest. */
function ReviewSheet({ intent, onClose, onApprove }: {
  intent: PaymentIntent;
  onClose: () => void;
  onApprove: () => void;
}) {
  const insets = useSafeAreaInsets();
  useCountdown(intent.expiresAt, true);
  const left = timeLeft(intent.expiresAt);
  const expired = !left;
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetScrim}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose}
          accessibilityRole="button" accessibilityLabel="Cerrar sin pagar" />
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 16) }]} accessibilityViewIsModal>
          <View style={styles.sheetGrip} />
          <ScrollView contentContainerStyle={styles.sheetBody} showsVerticalScrollIndicator={false}>
            <Text style={styles.sheetTitle}>Revisa antes de pagar</Text>

            <Text style={styles.sheetLabel}>Le pagas a</Text>
            <Text style={styles.sheetPayee}>{intent.payeeName}</Text>
            <PayeeLevel intent={intent} />
            {intent.payeeAccount ? <Text style={styles.sheetDetail}>{intent.payeeAccount}</Text> : null}
            {intent.payeeDocument ? <Text style={styles.sheetDetail}>Documento {intent.payeeDocument}</Text> : null}

            <View style={styles.rule} />
            <Line label={intent.amountExact ? 'Recibe exactamente' : 'Recibe aproximadamente'} value={local(intent)} />
            {!intent.amountExact && intent.minimumLocal ? (
              <Line label="Como mínimo" value={local(intent, intent.minimumLocal)} />
            ) : null}
            {Number(intent.feeUsd) > 0 ? <Line label="Comisión incluida" value={usd(intent.feeUsd)} /> : null}
            <Line label="Sale de tu cuenta personal" value={usd(intent.totalUsd)} strong />
            {exactSurplusNote(intent) ? <Text style={styles.sheetNote}>{exactSurplusNote(intent)}</Text> : null}

            {!expired ? (
              <Text style={styles.sheetNote}>
                Este precio vale {left} más. Confío te pide tu rostro y nada se paga antes de eso.
              </Text>
            ) : null}
          </ScrollView>

          <Pressable
            onPress={onApprove}
            disabled={expired}
            style={({ pressed }) => [styles.approve, expired && styles.approveOff, pressed && styles.approvePressed]}
            accessibilityRole="button"
            accessibilityState={{ disabled: expired }}
            accessibilityLabel={expired ? 'La cotización venció' : `Aprobar y pagar ${usd(intent.totalUsd)}`}
          >
            <Text style={styles.approveText}>{expired ? 'La cotización venció' : `Aprobar y pagar ${usd(intent.totalUsd)}`}</Text>
          </Pressable>
          <Pressable onPress={onClose} style={styles.notNow} accessibilityRole="button"
            accessibilityLabel={expired ? 'Cerrar' : 'Ahora no'}>
            <Text style={styles.notNowText}>{expired ? 'Cerrar' : 'Ahora no'}</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

export function PaymentIntentCard({ messageId, onLeaveBox }: {
  messageId: string;
  /** Set when the card is drawn inside the floating box (a modal): approving
   * and opening a screen happen from Inicio, so this closes the box first. */
  onLeaveBox?: () => void;
}) {
  const [watchUntil, setWatchUntil] = useState(0);
  const [stage, setStage] = useState<keyof typeof STAGES | null>(null);
  const [moving, setMoving] = useState(false);
  const { data, loading, refetch } = useQuery(GET_MESSAGE_PAYMENT_INTENT, {
    variables: { messageId },
    fetchPolicy: 'cache-and-network',
    // Only while money may be moving: a card at rest asks for nothing.
    pollInterval: stage ? 0 : watchUntil > Date.now() ? 5000 : moving ? SLOW_POLL_MS : 0,
  });
  const intent: PaymentIntent | null = data?.assistantPaymentIntent ?? null;
  const state = intent ? intentState(intent) : null;
  const [sheet, setSheet] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; verify?: boolean } | null>(null);
  // Set and read synchronously: two taps must never start two approvals.
  const approving = useRef(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  useCountdown(intent?.expiresAt, state?.key === 'open' && !stage);
  // The server says money is moving: keep watching until it settles, however long that takes.
  useEffect(() => {
    if (state?.key === 'paying') {
      setWatchUntil(Date.now() + WATCH_MS);
    }
    setMoving(state?.key === 'paying');
  }, [state?.key]);
  // Stop asking once the watch runs out, without waiting for another render.
  useEffect(() => {
    if (!watchUntil) return undefined;
    const timer = setTimeout(() => { if (alive.current) setWatchUntil(0); }, Math.max(0, watchUntil - Date.now()));
    return () => clearTimeout(timer);
  }, [watchUntil]);
  // Counted once per card that could be approved.
  const shown = useRef<string | null>(null);
  useEffect(() => {
    if (intent && state?.key === 'open' && shown.current !== intent.id) {
      shown.current = intent.id;
      trackPaymentIntent(intent.id, 'card_shown');
    }
  }, [intent, state?.key]);

  if (!intent || !state) {
    // Nothing to draw it from (still loading, or the row is gone): never a
    // card made of anything else.
    return loading ? (
      <View style={[styles.card, styles.cardLoading]}><ActivityIndicator size="small" color={EMERALD} /></View>
    ) : null;
  }

  const reload = () => { void refetch().catch(() => {}); };
  const goTo = (screen: string, params?: object) => {
    onLeaveBox?.();
    // (The box slides away before the screen opens over where it was.)
    setTimeout(() => (navigationRef as any).navigate('Main', { screen, params }), onLeaveBox ? 250 : 0);
  };
  const toInicio = () => {
    onLeaveBox?.();
    setTimeout(() => (navigationRef as any).navigate('Main', { screen: 'BottomTabs', params: { screen: 'Home' } }), 250);
  };
  // A rail whose funding is still its own screen's (QR Bolivia): reviewed and
  // paid in Pagar, not here.
  const elsewhere = intent.family === 'ramp_order' && intent.methodId !== 've_pagomovil_send';

  /** The person said yes to these figures (or asks to sign what they confirmed). */
  const approve = async () => {
    if (approving.current) {
      return;
    }
    approving.current = true;
    setSheet(false);
    setNote(null);
    setStage('checking');
    try {
      // One modal at a time on iOS: the sheet is gone before Confío Face may open.
      await new Promise((resolve) => setTimeout(resolve, SHEET_CLOSES_MS));
      const result = await approvePaymentIntent(intent, (next) => { if (alive.current) setStage(next); });
      if (alive.current && result.handoff === 'order') {
        setNote({ text: 'Tu pago quedó preparado. Termínalo en Pagar.' });
      }
    } catch (e) {
      const refusal = e instanceof PaymentIntentError ? e : null;
      if (alive.current) {
        setNote({
          text: refusal?.message || 'No pudimos confirmar el pago. Intenta de nuevo.',
          verify: refusal?.code === 'verification',
        });
      }
    } finally {
      approving.current = false;
      if (alive.current) {
        setStage(null);
        setWatchUntil(Date.now() + WATCH_MS);
        reload();
      }
    }
  };
  const open = () => {
    if (onLeaveBox) {
      toInicio();
      return;
    }
    setNote(null);
    trackPaymentIntent(intent.id, 'sheet_opened');
    setSheet(true);
  };
  const requote = async () => {
    setBusy(true);
    setNote(null);
    try {
      await requotePaymentIntent(intent.id);
      await refetch();
    } catch (e: any) {
      if (alive.current) setNote({ text: e?.message || 'No pude cotizar de nuevo.' });
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const drop = () => { void cancelPaymentIntent(intent.id).then(reload).catch(() => {}); };
  const left = timeLeft(intent.expiresAt);

  return (
    <View style={styles.card} accessible={false}>
      <View style={styles.cardTop}>
        <Text style={styles.cardKind}>Pago preparado</Text>
        {state.key === 'open' && left && !stage ? <Text style={styles.cardLeft}>Vale {left}</Text> : null}
      </View>
      <Text style={styles.cardPayee} numberOfLines={2}>{intent.payeeName}</Text>
      <PayeeLevel intent={intent} />
      <View style={styles.rule} />
      <Line label={intent.amountExact ? 'Recibe' : 'Recibe aprox.'} value={local(intent)} />
      <Line label="Tú pagas" value={usd(intent.totalUsd)} strong />

      {stage ? (
        <View style={styles.status} accessible accessibilityLabel={STAGES[stage]} accessibilityState={{ busy: true }}>
          <ActivityIndicator size="small" color={EMERALD} />
          <Text style={styles.statusText}>{STAGES[stage]}</Text>
        </View>
      ) : elsewhere && (state.key === 'open' || state.key === 'unsigned') ? (
        <>
          <Text style={styles.cardNote}>Este pago se revisa y se termina en Pagar.</Text>
          <Pressable onPress={() => goTo('Scan', { mode: 'pagar' })} style={styles.secondary} accessibilityRole="button"
            accessibilityLabel="Abrir Pagar">
            <Text style={styles.secondaryText}>Abrir Pagar</Text>
          </Pressable>
        </>
      ) : state.key === 'open' ? (
        <>
          <Pressable onPress={open} style={({ pressed }) => [styles.primary, pressed && styles.approvePressed]}
            accessibilityRole="button" accessibilityLabel={`Revisar y pagar ${usd(intent.totalUsd)} a ${intent.payeeName}`}>
            <Text style={styles.primaryText}>Revisar y pagar</Text>
          </Pressable>
          <Pressable onPress={drop} style={styles.quiet} accessibilityRole="button" accessibilityLabel="No pagar esto">
            <Text style={styles.quietText}>No pagar</Text>
          </Pressable>
        </>
      ) : state.key === 'unsigned' ? (
        <>
          <Text style={styles.cardNote}>{state.label}</Text>
          <Pressable onPress={onLeaveBox ? toInicio : () => void approve()}
            style={({ pressed }) => [styles.primary, pressed && styles.approvePressed]}
            accessibilityRole="button" accessibilityLabel={`Firmar ahora el pago de ${usd(intent.totalUsd)} a ${intent.payeeName}`}>
            <Text style={styles.primaryText}>Firmar ahora</Text>
          </Pressable>
          <Pressable onPress={drop} style={styles.quiet} accessibilityRole="button" accessibilityLabel="No pagar esto">
            <Text style={styles.quietText}>No pagar</Text>
          </Pressable>
        </>
      ) : state.key === 'expired' ? (
        <Pressable onPress={() => void requote()} disabled={busy} style={styles.secondary} accessibilityRole="button"
          accessibilityLabel="La cotización venció. Cotizar de nuevo">
          {busy ? <ActivityIndicator size="small" color={EMERALD} /> : <Text style={styles.secondaryText}>Cotizar de nuevo</Text>}
        </Pressable>
      ) : (
        <View style={styles.status}>
          {state.key === 'paying' ? <ActivityIndicator size="small" color={EMERALD} />
            : <Icon name={state.key === 'paid' ? 'check-circle' : state.key === 'review' ? 'clock' : 'x-circle'} size={18}
              color={state.key === 'paid' ? EMERALD : state.key === 'review' ? AMBER : MUTED} />}
          <Text style={[styles.statusText, state.key === 'paid' && styles.statusPaid]}>{state.label}</Text>
          {/* Only where there is a screen that shows this very payment. */}
          {state.key !== 'cancelled' && intent.journeyId ? (
            <Pressable onPress={() => goTo('LocalTransferStatus', { journeyId: intent.journeyId })} style={styles.statusLinkTap}
              accessibilityRole="button" accessibilityLabel="Ver el estado del pago">
              <Text style={styles.statusLink}>{state.key === 'paid' ? 'Ver comprobante' : 'Ver estado'}</Text>
            </Pressable>
          ) : null}
        </View>
      )}
      {note && !stage ? (
        <>
          <Text style={styles.cardNote}>{note.text}</Text>
          {note.verify ? (
            <Pressable onPress={() => goTo('Verification')} style={styles.statusLinkTap} accessibilityRole="button"
              accessibilityLabel="Verificar mi identidad">
              <Text style={styles.statusLink}>Verificar mi identidad</Text>
            </Pressable>
          ) : null}
        </>
      ) : null}

      {sheet && !stage ? (
        <ReviewSheet intent={intent} onClose={() => { setSheet(false); reload(); }} onApprove={() => void approve()} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 4,
    marginBottom: 4,
    maxWidth: 340,
    padding: 14,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#A7F3D0',
    backgroundColor: '#FFFFFF',
  },
  cardLoading: { minHeight: 72, alignItems: 'center', justifyContent: 'center' },
  cardTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  cardKind: { fontSize: 13, color: MUTED },
  cardLeft: { fontSize: 13, color: MUTED, fontVariant: ['tabular-nums'] },
  cardPayee: { fontSize: 17, lineHeight: 23, fontWeight: '700', color: INK, marginTop: 2 },
  level: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4 },
  levelText: { flex: 1, fontSize: 13, lineHeight: 18, color: EMERALD, fontWeight: '600' },
  levelTextWarn: { color: AMBER },
  rule: { height: StyleSheet.hairlineWidth, backgroundColor: '#D1D5DB', marginVertical: 10 },
  line: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, minHeight: 26 },
  lineLabel: { flexShrink: 1, fontSize: 14, color: MUTED },
  lineValue: { fontSize: 15, color: INK, fontVariant: ['tabular-nums'] },
  lineValueStrong: { fontSize: 17, fontWeight: '700' },
  primary: {
    marginTop: 12, height: 48, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: EMERALD,
  },
  primaryText: { fontSize: 16, fontWeight: '700', color: '#FFFFFF' },
  quiet: { height: 44, alignItems: 'center', justifyContent: 'center', marginBottom: -8 },
  quietText: { fontSize: 14, fontWeight: '600', color: MUTED },
  secondary: {
    marginTop: 12, height: 48, borderRadius: 14, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: EMERALD,
  },
  secondaryText: { fontSize: 16, fontWeight: '700', color: EMERALD },
  status: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 12, minHeight: 44 },
  statusText: { flex: 1, fontSize: 15, fontWeight: '600', color: INK },
  statusPaid: { color: EMERALD },
  statusLinkTap: { minHeight: 44, justifyContent: 'center' },
  statusLink: { fontSize: 14, fontWeight: '700', color: EMERALD },
  cardNote: { fontSize: 13, lineHeight: 18, color: AMBER, marginTop: 8 },

  sheetScrim: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(17,24,39,0.45)' },
  sheet: {
    maxHeight: '88%', backgroundColor: '#FFFFFF', borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingHorizontal: 20, paddingTop: 8,
  },
  sheetGrip: { alignSelf: 'center', width: 36, height: 4, borderRadius: 2, backgroundColor: '#D1D5DB', marginBottom: 8 },
  sheetBody: { paddingBottom: 12 },
  sheetTitle: { fontSize: 20, fontWeight: '700', color: INK, marginBottom: 14 },
  sheetLabel: { fontSize: 13, color: MUTED },
  sheetPayee: { fontSize: 22, lineHeight: 28, fontWeight: '700', color: INK, marginTop: 2 },
  sheetDetail: { fontSize: 14, color: MUTED, marginTop: 4 },
  sheetNote: { fontSize: 13, lineHeight: 18, color: MUTED, marginTop: 12 },
  approve: {
    minHeight: 54, borderRadius: 16, alignItems: 'center', justifyContent: 'center',
    backgroundColor: EMERALD, paddingHorizontal: 16,
  },
  approveOff: { backgroundColor: '#9CA3AF' },
  approvePressed: { backgroundColor: '#065F46' },
  approveText: { fontSize: 17, fontWeight: '700', color: '#FFFFFF', textAlign: 'center' },
  notNow: { height: 48, alignItems: 'center', justifyContent: 'center' },
  notNowText: { fontSize: 15, fontWeight: '600', color: MUTED },
});
