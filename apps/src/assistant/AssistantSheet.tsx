// The Confio Assistant chat: typed text or voice notes in, answers plus screen
// actions out. The same thread the team answers in after a handoff.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  AppState,
  Easing,
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StatusBar,
  StyleSheet,
  View,
  useWindowDimensions,
} from 'react-native';
import { useApolloClient, useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text, TextInput } from '../components/common/AppText';
import { useAccount } from '../contexts/AccountContext';
import { navigationRef } from '../navigation/RootNavigation';
import { MARK_MESSAGE_CHANNEL_SEEN } from '../apollo/mutations';
import { GET_MESSAGE_INBOX, GET_MESSAGE_INBOX_UNREAD_COUNT } from '../apollo/queries';
import { MessageInboxContent } from '../components/MessageInboxContent';
import { ChannelAvatar } from '../components/MessageInboxShared';
import {
  ANSWER_ASSISTANT_PROBE,
  ASK_ASSISTANT,
  GET_ASSISTANT_PLAN,
  GET_ASSISTANT_SUGGESTIONS,
  GET_ASSISTANT_THREAD,
  RETURN_TO_ASSISTANT,
  type AssistantAction,
  type AssistantMessage,
  type AssistantProbe,
  type AssistantProfile,
  type AssistantSuggestion,
} from './api';
import AssistantMascot, { type MascotMood } from './AssistantMascot';
import { useAssistant, type BoxChannel } from './AssistantContext';
import { openDestination, resolveNavigate } from './destinations';
import MascotPicker from './MascotPicker';
import AssistantPlusPanel from './AssistantPlusPanel';
import VoiceCallPanel from './VoiceCallPanel';
import { clearCallError, startCall, useCall } from './callStore';
import {
  MAX_VOICE_NOTE_MS,
  cancelVoiceNote,
  isVoiceNoteAvailable,
  startVoiceNote,
  stopVoiceNote,
} from './voiceNote';

const EMERALD = '#047857';
const EMERALD_DARK = '#065F46';
const PAGE_SIZE = 30;

const STARTERS = [
  '¿En qué gasté más este mes?',
  'Abre QR para pagar',
  '¿Cómo recargo desde mi banco?',
  '¿Cómo invierto en acciones?',
];

// Wake-word recordings stop after this and are discarded unless sent by tap.
const WAKE_RECORDING_MS = 15_000;

function deviceTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
}

function formatClock(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

type OpenTarget = { key: string; ticker?: string; label: string };

function ActionChips({ actions, onPress }: { actions: AssistantAction[]; onPress: (target: OpenTarget) => void }) {
  const known = actions
    .filter((a) => a.type === 'navigate')
    .map(resolveNavigate)
    .filter((t): t is OpenTarget => t !== null);
  if (!known.length) {
    return null;
  }
  return (
    <View style={styles.chipsRow}>
      {known.map((t) => (
        <Pressable
          key={`${t.key}:${t.ticker ?? ''}`}
          onPress={() => onPress(t)}
          style={styles.actionChip}
          accessibilityRole="button"
        >
          <Text style={styles.actionChipText}>{t.label}</Text>
          <Icon name="arrow-up-right" size={14} color={EMERALD} />
        </Pressable>
      ))}
    </View>
  );
}

type PetFace = { mascot?: string; customPetUrl?: string | null; mascotColor?: string } | null;

// Three dots that hop while Confio Assistant thinks.
function TypingDots() {
  const dots = useRef([0, 1, 2].map(() => new Animated.Value(0))).current;
  useEffect(() => {
    const loops = dots.map((v, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(i * 140),
          Animated.timing(v, { toValue: 1, duration: 260, easing: Easing.out(Easing.quad), useNativeDriver: true }),
          Animated.timing(v, { toValue: 0, duration: 260, easing: Easing.in(Easing.quad), useNativeDriver: true }),
          Animated.delay((2 - i) * 140 + 200),
        ]),
      ),
    );
    loops.forEach((l) => l.start());
    return () => loops.forEach((l) => l.stop());
  }, [dots]);
  return (
    <View style={styles.dots}>
      {dots.map((v, i) => (
        <Animated.View
          key={i}
          style={[styles.dot, { transform: [{ translateY: v.interpolate({ inputRange: [0, 1], outputRange: [0, -5] }) }] }]}
        />
      ))}
    </View>
  );
}

function Bubble({ message, onAction, pet }: { message: AssistantMessage; onAction: (target: OpenTarget) => void; pet: PetFace }) {
  const mine = message.role === 'user';
  const team = message.role === 'team';
  const ai = message.role === 'assistant';
  return (
    <View style={[styles.messageRow, mine && styles.messageRowMine]}>
      {ai ? (
        <View style={styles.msgAvatar}>
          <AssistantMascot kind={pet?.mascot} imageUrl={pet?.customPetUrl} color={pet?.mascotColor} size={26} animated={false} />
        </View>
      ) : null}
    <View style={[styles.row, mine ? styles.rowMine : styles.rowTheirs]}>
      <View style={[styles.bubble, mine ? styles.bubbleMine : team ? styles.bubbleTeam : styles.bubbleTheirs]}>
        {team ? <Text style={styles.teamName}>{message.senderName}</Text> : null}
        {mine && message.modality === 'VOICE_NOTE' ? (
          <View style={styles.voiceTag}>
            <Icon name="mic" size={12} color="#D1FAE5" />
            <Text style={styles.voiceTagText}>Audio</Text>
          </View>
        ) : null}
        <Text style={[styles.bubbleText, mine && styles.bubbleTextMine]} selectable>
          {message.body}
        </Text>
        {message.pending ? <ActivityIndicator size="small" color="#D1FAE5" style={styles.pending} /> : null}
      </View>
      {!mine ? <ActionChips actions={message.actions} onPress={onAction} /> : null}
    </View>
    </View>
  );
}

export default function AssistantSheet() {
  const insets = useSafeAreaInsets();
  const {
    isOpen, close, consumePrompt, consumePicker, consumePlus, consumeCall, consumeChannel, consumeVoiceNote,
    consumeVoiceNoteData, openSeq, route, plan,
    setPlan, available,
    aiEnabled, bubbleAnchor, showNavNote, consumeProbe,
  } = useAssistant();
  // Which chat head is open: Confio Assistant, Julian or Confío News.
  const [channel, setChannel] = useState<BoxChannel>('ia');
  // False until the open request's channel is applied, so nothing acts on
  // the previous visit's channel.
  const [channelReady, setChannelReady] = useState(false);
  const channelRef = useRef<BoxChannel>('ia');
  // The visit a reply belongs to: an answer may only move the app while the
  // box is still open on Confio Assistant in that same opening.
  const isOpenRef = useRef(isOpen);
  isOpenRef.current = isOpen;
  const openSeqRef = useRef(openSeq);
  openSeqRef.current = openSeq;
  const wakeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const call = useCall();
  const callLive = call.state !== 'idle' && call.state !== 'ended';
  const [showPlus, setShowPlus] = useState(false);
  const { activeAccount } = useAccount();
  const isBusiness = (activeAccount?.type || '').toLowerCase() === 'business';
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sentThisOpen, setSentThisOpen] = useState(false);
  // The server's one-time question, asked when this opening was for it (or it's pending).
  const [askOther, setAskOther] = useState(false);
  const [mode, setMode] = useState<'AI' | 'HUMAN'>('AI');
  const [draft, setDraft] = useState('');
  const [thinking, setThinking] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [recordingMs, setRecordingMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [profile, setProfile] = useState<AssistantProfile | null>(null);
  const autoStopTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const client = useApolloClient();
  const accountGen = useRef(0);
  const olderLoaded = useRef(false);
  // Keyed by account: a poll answered for the previous account lands in that
  // account's cache entry, never in this one.
  const contextKey = activeAccount?.id || 'no-account';
  const { data, loading, refetch } = useQuery(GET_ASSISTANT_THREAD, {
    variables: { limit: PAGE_SIZE, contextKey },
    skip: !isOpen,
    fetchPolicy: 'network-only',
    notifyOnNetworkStatusChange: true,
    // Team replies arrive by polling while the sheet is open.
    pollInterval: isOpen ? (mode === 'HUMAN' ? 5000 : 15000) : 0,
  });
  const { data: inboxData } = useQuery(GET_MESSAGE_INBOX, {
    variables: { contextKey: activeAccount?.id || 'no-account' },
    skip: !isOpen,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'ignore',
  });
  const unreadByChannel: Record<string, number> = {};
  for (const c of inboxData?.messageInbox?.channels ?? []) {
    const id = c.id === 'confio-news' ? 'confio' : c.id;
    unreadByChannel[id] = c.unreadCount || 0;
  }
  const { data: planData } = useQuery(GET_ASSISTANT_PLAN, {
    skip: !isOpen,
    fetchPolicy: 'network-only',
    errorPolicy: 'ignore',
  });
  useEffect(() => {
    if (planData?.assistantPlan) {
      setPlan(planData.assistantPlan);
    }
  }, [planData, setPlan]);
  const [ask] = useMutation(ASK_ASSISTANT);
  const [returnToAi] = useMutation(RETURN_TO_ASSISTANT);
  const [markSeen] = useMutation(MARK_MESSAGE_CHANNEL_SEEN, {
    refetchQueries: [GET_MESSAGE_INBOX_UNREAD_COUNT],
  });

  // Reading the chat is reading the support thread: clear its unread badge
  // when it opens and whenever a reply lands while it is open.
  const lastMessageId = messages[messages.length - 1]?.id;
  useEffect(() => {
    // Only while the support chat itself is on screen (not Julian or News).
    if (isOpen && channelReady && channel === 'ia' && lastMessageId && !lastMessageId.startsWith('pending-')) {
      void markSeen({ variables: { channelId: 'soporte' } }).catch(() => {});
    }
  }, [isOpen, channelReady, channel, lastMessageId, markSeen]);

  useEffect(() => {
    const thread = data?.assistantThread;
    if (!thread) {
      return;
    }
    // A poll returns the newest page: keep older pages already loaded and
    // any message still on its way.
    setMessages((prev) => {
      const pending = prev.filter((m) => m.pending);
      const firstId = Number(thread.messages[0]?.id ?? Infinity);
      const polled = new Set(thread.messages.map((m: AssistantMessage) => m.id));
      const older = prev.filter((m) => !m.pending && Number(m.id) < firstId);
      // Messages a mutation added that this poll predates stay, once.
      const newer = prev.filter((m) => !m.pending && Number(m.id) >= firstId && !polled.has(m.id));
      return [...older, ...thread.messages, ...newer, ...pending];
    });
    if (!olderLoaded.current) {
      setHasMore(thread.hasMore);
    }
    setMode(thread.mode === 'HUMAN' ? 'HUMAN' : 'AI');
    setProfile(thread.profile);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  useEffect(() => {
    if (!isOpen) {
      setError(null);
      setPickerOpen(false);
      setShowPlus(false);
      setChannelReady(false);
      // Unconditional: also cancels a recorder still starting and its
      // auto-send timer, so nothing records or sends after closing.
      stopRecordingNow();
      return;
    }
    // Suggestions come back on every opening, not only in an empty thread.
    setSentThisOpen(false);
    setAskOther(false);
    consumeProbe();
    const requested = consumeChannel();
    setChannel(requested ?? 'ia');
    setChannelReady(true);
    if (consumePicker()) {
      setPickerOpen(true);
    }
    if (consumePlus() && plan?.plusSalesEnabled) {
      setShowPlus(true);
    }
    if (consumeCall()) {
      void beginCall();
    }
    if (consumeVoiceNote() && aiEnabled && isVoiceNoteAvailable) {
      // Give the wake-word engine a moment to release the microphone; only
      // record if Confio Assistant is still the visible channel by then.
      wakeTimer.current = setTimeout(() => {
        wakeTimer.current = null;
        if (recordingMs === null && channelRef.current === 'ia') {
          void toggleRecording({ fromWake: true });
        }
      }, 400);
      return () => {
        if (wakeTimer.current) {
          clearTimeout(wakeTimer.current);
          wakeTimer.current = null;
        }
      };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, openSeq]);

  useEffect(() => {
    if (call.error) {
      setError(call.error);
      clearCallError();
    }
  }, [call.error]);

  const beginCall = async () => {
    setError(null);
    if (!plan?.voiceCallsEnabled) {
      return;
    }
    if (!plan?.isPlus) {
      setShowPlus(true);
      return;
    }
    await startCall(client, {
      screen: route,
      timezone: deviceTimezone(),
      isBusiness,
      // "Abre QR para pagar": show the screen; the call keeps going and the
      // bubble shows it's live.
      onNavigate: () => close(),
    });
  };

  // Account switch: each account has its own thread.
  useEffect(() => {
    setMessages([]);
    setHasMore(false);
    olderLoaded.current = false;
    // Anything still in flight belongs to the previous account: drop it,
    // including a voice note being recorded.
    accountGen.current += 1;
    stopRecordingNow();
    queuedVoice.current = null;
  }, [activeAccount?.id]);

  // A post from Julian/News: close the box, then open it in the main stack.
  const openPost = useCallback(
    (contentItemId: number) => {
      close();
      setTimeout(
        () => (navigationRef as any).navigate('Main', { screen: 'DiscoverPostDetail', params: { contentItemId } }),
        250,
      );
    },
    [close],
  );

  const runAction = useCallback(
    ({ key, ticker }: { key: string; ticker?: string }) => {
      if (key === 'messages') {
        // Mensajes lives here: show Julian's channel instead of leaving.
        setChannel('julian');
        return;
      }
      close();
      setTimeout(() => openDestination(key, { isBusiness, ticker }), 250);
    },
    [close, isBusiness],
  );

  const send = useCallback(
    async (input: { body?: string; voice?: { base64: string; mimeType: string; durationMs: number } }) => {
      const body = input.body?.trim();
      if ((!body && !input.voice) || thinking) {
        return;
      }
      setError(null);
      setSentThisOpen(true);
      const visit = openSeqRef.current;
      const tempId = `pending-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        {
          id: tempId,
          role: 'user',
          body: body || 'Escuchando tu audio…',
          createdAt: new Date().toISOString(),
          senderName: 'Tú',
          modality: input.voice ? 'VOICE_NOTE' : 'TEXT',
          actions: [],
          pending: true,
        },
      ]);
      setThinking(true);
      try {
        const gen = accountGen.current;
        const { data: result } = await ask({
          variables: {
            body: body || null,
            audioBase64: input.voice?.base64 ?? null,
            audioMimeType: input.voice?.mimeType ?? null,
            audioDurationMs: input.voice?.durationMs ?? null,
            screen: route ?? null,
            timezone: deviceTimezone() ?? null,
          },
        });
        if (gen !== accountGen.current) {
          return; // the user switched accounts while this was answering
        }
        const payload = result?.askAssistant;
        if (!payload?.success) {
          setMessages((prev) => prev.filter((m) => m.id !== tempId));
          setError(payload?.error || 'No pude enviar tu mensaje.');
          return;
        }
        setMessages((prev) => {
          // A poll may already have brought these in: merge by server id.
          const fresh = [payload.userMessage, payload.reply].filter(Boolean) as AssistantMessage[];
          const known = new Set(prev.map((m) => m.id));
          return [...prev.filter((m) => m.id !== tempId), ...fresh.filter((m) => !known.has(m.id))];
        });
        setMode(payload.mode === 'HUMAN' ? 'HUMAN' : 'AI');
        if (payload.dataChanged) {
          // E.g. it categorized movements: the "Tu mes" screen under the box
          // never lost focus, so refresh its numbers now.
          void client.refetchQueries({ include: ['MonthSummary', 'MonthMovements'] }).catch(() => {});
        }
        if (payload.reply) {
          setSpeaking(true);
          setTimeout(() => setSpeaking(false), 1600);
        }
        // "Confío, abre QR para pagar": the answer moves the app.
        const navigateTo = (payload.actions as AssistantAction[])
          .filter((a) => a.type === 'navigate')
          .map(resolveNavigate)
          .find((t) => t !== null);
        if (navigateTo) {
          setTimeout(() => {
            // Closed, switched channel or reopened since asking: leave the
            // chip in the thread (a tap still works) instead of moving the app.
            if (gen === accountGen.current && isOpenRef.current && channelRef.current === 'ia'
                && openSeqRef.current === visit) {
              runAction(navigateTo);
              const replyText = payload.reply?.body;
              if (typeof replyText === 'string' && replyText.trim() && navigateTo.key !== 'messages') {
                showNavNote(replyText);
              }
            }
          }, 900);
        }
      } catch (e) {
        setMessages((prev) => prev.filter((m) => m.id !== tempId));
        setError('Sin conexión con Confio Assistant. Inténtalo de nuevo.');
      } finally {
        setThinking(false);
      }
    },
    [ask, route, runAction, thinking, showNavNote],
  );

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const prompt = consumePrompt();
    const heldNote = consumeVoiceNoteData();
    if (heldNote && heldNote.accountId === activeAccount?.id) {
      // Recorded by holding the bubble. If an answer is still pending, it
      // waits its turn instead of being dropped.
      if (thinking) {
        queuedVoice.current = heldNote;
      } else {
        void send({ voice: heldNote });
      }
    } else if (prompt) {
      void send({ body: prompt });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, openSeq]);

  const submitDraft = () => {
    const body = draft;
    setDraft('');
    void send({ body });
  };

  const recordGen = useRef(0);
  // Leaving the Confio Assistant channel stops (and never sends) a recording,
  // including one the wake word was about to start.
  useEffect(() => {
    channelRef.current = channel;
    if (channel !== 'ia') {
      if (wakeTimer.current) {
        clearTimeout(wakeTimer.current);
        wakeTimer.current = null;
      }
      stopRecordingNow();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel]);
  const queuedVoice = useRef<{ base64: string; mimeType: string; durationMs: number } | null>(null);
  useEffect(() => {
    if (!thinking && queuedVoice.current) {
      const note = queuedVoice.current;
      queuedVoice.current = null;
      void send({ voice: note });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thinking]);
  // Stop the mic and its auto-send timer without sending anything.
  const stopRecordingNow = () => {
    recordGen.current = -1; // a note still finalizing must not be sent
    if (autoStopTimer.current) {
      clearTimeout(autoStopTimer.current);
      autoStopTimer.current = null;
    }
    setRecordingMs(null);
    void cancelVoiceNote();
  };
  // Going to the background stops (never sends) a recording in progress.
  // Only a running recording: the mic permission prompt itself makes the app
  // inactive (iOS) and must not cancel the start it is asking for.
  const recordingRef = useRef(false);
  recordingRef.current = recordingMs !== null;
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'background' && recordingRef.current) {
        stopRecordingNow();
      }
    });
    return () => sub.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Leaving the signed-in app (sign-out) must never leave the mic on.
  const mountedRef = useRef(true);
  useEffect(() => () => {
    mountedRef.current = false;
    stopRecordingNow();
  }, []);

  const finishRecording = useCallback(async () => {
    if (autoStopTimer.current) {
      clearTimeout(autoStopTimer.current);
      autoStopTimer.current = null;
    }
    setRecordingMs(null);
    try {
      const gen = recordGen.current;
      const note = await stopVoiceNote();
      // Cancelled/closed meanwhile, recorded under another account, or the
      // sheet is gone: never send it.
      if (note && gen === recordGen.current && gen === accountGen.current && mountedRef.current) {
        void send({ voice: note });
      }
    } catch {
      setError('No pude grabar el audio.');
    }
  }, [send]);

  const toggleRecording = async (opts: { fromWake?: boolean } = {}) => {
    if (recordingMs !== null) {
      await finishRecording();
      return;
    }
    setError(null);
    try {
      const genAtStart = accountGen.current;
      const started = await startVoiceNote((ms) => setRecordingMs(ms));
      if (!started) {
        setError('Necesito permiso para usar el micrófono.');
        return;
      }
      recordGen.current = genAtStart;
      setRecordingMs(0);
      autoStopTimer.current = opts.fromWake
        // Nobody tapped anything: a wake-word recording is short and is only
        // sent if the person taps Enviar (a false trigger never uploads).
        ? setTimeout(() => {
          stopRecordingNow();
          setError('Dejé de escuchar. Toca el micrófono para mandarme un audio.');
        }, WAKE_RECORDING_MS)
        : setTimeout(() => void finishRecording(), MAX_VOICE_NOTE_MS);
    } catch {
      setError('No pude usar el micrófono.');
    }
  };

  const cancelRecording = async () => {
    if (autoStopTimer.current) {
      clearTimeout(autoStopTimer.current);
      autoStopTimer.current = null;
    }
    setRecordingMs(null);
    await cancelVoiceNote();
  };

  const loadOlder = async () => {
    if (!hasMore || loadingMore || !messages.length) {
      return;
    }
    const oldest = messages.find((m) => !m.pending);
    if (!oldest) {
      return;
    }
    setLoadingMore(true);
    try {
      // A separate request, not fetchMore: the polled first page must not be
      // overwritten in the cache by an older one.
      const gen = accountGen.current;
      const { data: page } = await client.query({
        query: GET_ASSISTANT_THREAD,
        variables: { limit: PAGE_SIZE, beforeId: oldest.id, contextKey },
        fetchPolicy: 'no-cache',
      });
      if (gen !== accountGen.current) {
        return;
      }
      const thread = page?.assistantThread;
      if (thread) {
        olderLoaded.current = true;
        setMessages((prev) => [...thread.messages.filter((m: AssistantMessage) => !prev.some((p) => p.id === m.id)), ...prev]);
        setHasMore(thread.hasMore);
      }
    } finally {
      setLoadingMore(false);
    }
  };

  const backToAi = async () => {
    await returnToAi();
    setMode('AI');
    void refetch();
  };

  // The box grows out of the bubble and shrinks back into it.
  const { width: screenW, height: screenH } = useWindowDimensions();
  const progress = useRef(new Animated.Value(0)).current;
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (isOpen) {
      setShown(true);
      progress.setValue(0);
      Animated.spring(progress, { toValue: 1, useNativeDriver: true, damping: 16, stiffness: 180, mass: 0.9 }).start();
    } else if (shown) {
      Animated.timing(progress, { toValue: 0, duration: 170, easing: Easing.in(Easing.quad), useNativeDriver: true })
        .start(() => setShown(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Android: with the keyboard up, sit right on top of it. The modal window may
  // already have shrunk (adjustResize) and the bubble may have moved too, so
  // anchoring to the bubble would lift the box twice; measure instead.
  const [modalH, setModalH] = useState(0);
  const [kbTop, setKbTop] = useState<number | null>(null);
  useEffect(() => {
    if (Platform.OS !== 'android') {
      return undefined;
    }
    const show = Keyboard.addListener('keyboardDidShow', (e) => setKbTop(e.endCoordinates.screenY));
    const hide = Keyboard.addListener('keyboardDidHide', () => setKbTop(null));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);
  // The modal is statusBarTranslucent (origin = top of the screen). Below
  // Android 15 the app window is not edge-to-edge: it starts under the status
  // bar, insets.top is 0 and the bubble's anchor is measured from there, so
  // shift it into screen coordinates and keep the card clear of the bar.
  const statusShift = Platform.OS === 'android' && Number(Platform.Version) < 35 ? (StatusBar.currentHeight ?? 0) : 0;
  const topSafe = Math.max(insets.top, statusShift);
  const boxH = modalH || screenH;
  const keyboardArea = Platform.OS === 'android' && kbTop !== null && modalH > 0
    ? { top: topSafe + 12, bottom: Math.max(8, modalH - kbTop + 8) }
    : null;

  const anchor = bubbleAnchor
    ? { ...bubbleAnchor, y: bubbleAnchor.y + statusShift }
    : { x: screenW - 62 - 12, y: boxH - insets.bottom - 62 - 76, size: 62 };
  const below = anchor.y < boxH / 2; // bubble high on screen: open downward
  const gap = 14;
  const area = keyboardArea ?? (below
    ? { top: anchor.y + anchor.size + gap, bottom: Math.max(insets.bottom, 10) + 6 }
    : { top: topSafe + 12, bottom: boxH - anchor.y + gap });
  const tailLeft = Math.min(Math.max(anchor.x + anchor.size / 2 - 9, 28), screenW - 46);
  const tailTop = below ? anchor.y + anchor.size + gap - 9 : anchor.y - gap - 9;
  const lift = progress.interpolate({ inputRange: [0, 1], outputRange: [below ? -28 : 28, 0] });
  const grow = progress.interpolate({ inputRange: [0, 1], outputRange: [0.88, 1] });

  const mood: MascotMood = recordingMs !== null ? 'listening' : thinking ? 'thinking' : speaking ? 'talking' : 'idle';
  const reversed = useMemo(() => [...messages].reverse(), [messages]);
  // Chips and the one-time question, ranked on the server for this person;
  // the built-in STARTERS stay as the fallback (older server, offline).
  const { data: suggestionData, refetch: refetchSuggestions } = useQuery(GET_ASSISTANT_SUGGESTIONS, {
    variables: { screen: route ?? null, contextKey: activeAccount?.id || 'no-account' },
    skip: !isOpen || !aiEnabled,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'ignore',
  });
  const serverStarters: AssistantSuggestion[] | undefined = suggestionData?.assistantSuggestions?.starters
    ?.filter((s: AssistantSuggestion) => s.kind === 'prompt');
  const starters: AssistantSuggestion[] = serverStarters?.length
    ? serverStarters
    : STARTERS.map((text) => ({ id: text, text, prompt: text, kind: 'prompt' }));
  const probe: AssistantProbe | null = suggestionData?.assistantSuggestions?.probe ?? null;
  const [answerProbeMutation] = useMutation(ANSWER_ASSISTANT_PROBE);
  const answeringProbe = useRef(false);
  const answerProbe = async (current: AssistantProbe, key: string) => {
    if (answeringProbe.current) {
      return; // one answer per question, even on a fast double tap
    }
    answeringProbe.current = true;
    const gen = accountGen.current;
    let label: string | null | undefined;
    try {
      const { data } = await answerProbeMutation({ variables: { probeId: current.id, answer: key } });
      label = data?.answerAssistantProbe?.success ? data.answerAssistantProbe.label : null;
    } catch {
      label = null;
    }
    // Always release the guard, whatever happened meanwhile.
    void refetchSuggestions().catch(() => {}).finally(() => {
      answeringProbe.current = false;
    });
    if (gen !== accountGen.current) {
      return; // the account changed: don't send into the new account's chat
    }
    if (key === 'other') {
      setAskOther(true); // the next message they type is the answer
    } else if (label) {
      void send({ body: label }); // the assistant takes it from there
    }
  };

  // AI mode only: in a handed-off thread a chip would send a canned prompt to the team.
  const showStarters = aiEnabled && mode === 'AI' && !thinking && !sentThisOpen && !(loading && !messages.length);
  const petName = profile?.mascotName?.trim();

  // statusBarTranslucent: modal coordinates = screen coordinates, so the
  // keyboard top (screen-absolute) and insets.top line up on Android.
  return (
    <Modal visible={shown} animationType="none" transparent statusBarTranslucent onRequestClose={close}>
      <View style={StyleSheet.absoluteFill} pointerEvents="none" onLayout={(e) => setModalH(e.nativeEvent.layout.height)} />
      <Animated.View style={[styles.scrim, { opacity: progress }]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityLabel="Cerrar mensajes" />
      </Animated.View>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={[styles.floatingArea, area]}
        pointerEvents="box-none"
      >
        <Animated.View
          style={[styles.card, { opacity: progress, transform: [{ translateY: lift }, { scale: grow }] }]}
        >
        <View style={styles.heads}>
          {(['ia', 'julian', 'confio'] as BoxChannel[])
            .map((id) => (
              <Pressable
                key={id}
                onPress={() => setChannel(id)}
                onLongPress={id === 'ia' && aiEnabled ? () => setPickerOpen(true) : undefined}
                style={styles.head}
                accessibilityRole="tab"
                accessibilityState={{ selected: channel === id }}
                accessibilityLabel={id === 'ia' ? (aiEnabled ? 'Confio Assistant' : 'Soporte') : id === 'julian' ? 'Julian Moon' : 'Confío News'}
              >
                <View style={[styles.headCircle, channel === id && styles.headCircleActive]}>
                  {id === 'ia' && !aiEnabled ? (
                    <ChannelAvatar channel={{ id: 'soporte' } as any} large />
                  ) : id === 'ia' ? (
                    <AssistantMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor}
                      size={36} mood={channel === 'ia' ? mood : 'idle'} animated={channel === 'ia'} />
                  ) : (
                    <ChannelAvatar channel={{ id } as any} large />
                  )}
                  {id !== 'ia' && unreadByChannel[id] > 0 && channel !== id ? <View style={styles.headDot} /> : null}
                </View>
                <Text style={[styles.headLabel, channel === id && styles.headLabelActive]} numberOfLines={1}>
                  {id === 'ia' ? (aiEnabled ? petName || 'Confio Assistant' : 'Soporte') : id === 'julian' ? 'Julian' : 'News'}
                </Text>
              </Pressable>
            ))}
          <View style={styles.headsSpacer} />
          <Pressable onPress={close} style={styles.iconButton} accessibilityLabel="Cerrar">
            <Icon name="x" size={22} color="#374151" />
          </Pressable>
        </View>

        {channel !== 'ia' ? (
          <View style={styles.channelBody}>
            <MessageInboxContent embeddedChannelId={channel} onExit={() => setChannel('ia')} onOpenPost={openPost} />
          </View>
        ) : !available ? (
          // No Confio Assistant chat (older server, or it failed to load): the classic
          // support thread, so people can always reach the team from here.
          <View style={styles.channelBody}>
            <MessageInboxContent embeddedChannelId="soporte" onExit={() => setChannel('julian')} />
          </View>
        ) : (
        <>
        <View style={styles.header}>
          <View style={styles.headerText}>
            <Text style={styles.title}>
              {!aiEnabled ? 'Soporte' : petName ? `${petName} · Confio Assistant` : 'Confio Assistant'}
            </Text>
            <Text style={styles.subtitle}>
              {!aiEnabled
                ? 'Equipo Confío · Te respondemos aquí'
                : callLive
                ? 'En llamada'
                : mode === 'HUMAN'
                  ? 'Te atiende el equipo de Confío'
                  : thinking
                    ? 'Pensando…'
                    : 'Tu asistente · Disponible 24/7'}
            </Text>
          </View>
          {aiEnabled ? (
            <Pressable onPress={() => setPickerOpen(true)} style={styles.petChip} accessibilityLabel="Personaliza a tu asistente">
              <Text style={styles.petChipText}>✨ Tu asistente</Text>
            </Pressable>
          ) : null}
          {aiEnabled && plan?.plusSalesEnabled ? (
            <Pressable
              onPress={() => setShowPlus((v) => !v)}
              style={[styles.plusChip, plan.isPlus && styles.plusChipActive]}
              accessibilityLabel="Confio Assistant+"
            >
              <Text style={[styles.plusChipText, plan.isPlus && styles.plusChipTextActive]}>Assistant+</Text>
            </Pressable>
          ) : null}
          {aiEnabled && plan?.voiceCallsEnabled && !callLive && mode === 'AI' ? (
            <Pressable onPress={beginCall} style={styles.iconButton} accessibilityLabel="Llamar a Confio Assistant">
              <Icon name="phone" size={20} color={EMERALD} />
            </Pressable>
          ) : null}
        </View>

        {showPlus && plan?.plusSalesEnabled ? (
          <AssistantPlusPanel
            plan={plan}
            profile={profile}
            onPlan={(next) => {
              setPlan(next);
              setShowPlus(false);
            }}
            onClose={() => setShowPlus(false)}
            onLeave={close}
          />
        ) : callLive ? (
          <VoiceCallPanel profile={profile} />
        ) : (
          <>
          {aiEnabled && mode === 'HUMAN' ? (
            <View style={styles.humanBanner}>
              <Icon name="users" size={14} color={EMERALD_DARK} />
              <Text style={styles.humanBannerText}>El equipo verá tus mensajes y te responderá aquí.</Text>
              <Pressable onPress={backToAi} accessibilityRole="button">
                <Text style={styles.humanBannerLink}>Volver a Confio Assistant</Text>
              </Pressable>
            </View>
          ) : null}

          <FlatList
            data={reversed}
            inverted
            keyExtractor={(m) => m.id}
            renderItem={({ item }) => <Bubble message={item} onAction={runAction} pet={aiEnabled ? profile : null} />}
            contentContainerStyle={styles.list}
            onEndReached={loadOlder}
            onEndReachedThreshold={0.3}
            initialNumToRender={20}
            maxToRenderPerBatch={10}
            windowSize={21}
            keyboardShouldPersistTaps="handled"
            ListHeaderComponent={
              // The chips sit under the last message (the list is inverted)
              // and scroll with it, so they never cover the conversation.
              showStarters ? (
                <View style={styles.starters}>
                  {profile?.mascot !== 'CUSTOM' ? (
                  <Pressable style={[styles.starter, styles.starterPet]} onPress={() => setPickerOpen(true)}>
                    <Text style={styles.starterPetText}>✨ Personaliza a tu asistente</Text>
                  </Pressable>
                ) : null}
                {probe ? (
                  <View style={styles.probe}>
                    <Text style={styles.probeQuestion}>{probe.question}</Text>
                    <View style={styles.probeAnswers}>
                      {probe.answers.map((a) => (
                        <Pressable key={a.key} style={styles.starter} onPress={() => void answerProbe(probe, a.key)}
                          accessibilityRole="button">
                          <Text style={styles.starterText}>{a.label}</Text>
                        </Pressable>
                      ))}
                    </View>
                  </View>
                ) : starters.map((s) => (
                    <Pressable key={s.id} style={styles.starter} onPress={() => void send({ body: s.prompt || s.text })}>
                      <Text style={styles.starterText}>{s.text}</Text>
                    </Pressable>
                  ))}
                </View>
              ) : thinking ? (
                <View style={styles.messageRow}>
                  <View style={styles.msgAvatar}>
                    <AssistantMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor}
                      size={26} mood="thinking" />
                  </View>
                  <View style={[styles.bubble, styles.bubbleTheirs, styles.typing]}>
                    <TypingDots />
                  </View>
                </View>
              ) : null
            }
            ListFooterComponent={
              loading && !messages.length ? <ActivityIndicator style={styles.loader} color={EMERALD} /> : loadingMore ? (
                <ActivityIndicator style={styles.loader} color={EMERALD} />
              ) : null
            }
          />

          {error ? <Text style={styles.error}>{error}</Text> : null}

          {recordingMs !== null ? (
            <View style={styles.composer}>
              <Pressable onPress={cancelRecording} style={styles.iconButton} accessibilityLabel="Cancelar audio">
                <Icon name="trash-2" size={20} color="#DC2626" />
              </Pressable>
              <View style={styles.recording}>
                <View style={styles.recDot} />
                <Text style={styles.recText}>Te escucho… {formatClock(recordingMs)}</Text>
              </View>
              <Pressable onPress={finishRecording} style={styles.sendButton} accessibilityLabel="Enviar audio">
                <Icon name="send" size={18} color="#FFFFFF" />
              </Pressable>
            </View>
          ) : (
            <View style={styles.composer}>
              <TextInput
                style={styles.input}
                value={draft}
                onChangeText={setDraft}
                placeholder={askOther ? 'Cuéntame para qué te gustaría usarlo'
                  : isVoiceNoteAvailable ? 'Escríbeme o mándame un audio' : 'Escríbeme'}
                placeholderTextColor="#9CA3AF"
                multiline
                maxLength={2000}
                editable={!thinking}
              />
              {draft.trim() || !isVoiceNoteAvailable ? (
                <Pressable
                  onPress={submitDraft}
                  style={[styles.sendButton, (!draft.trim() || thinking) && styles.disabled]}
                  disabled={!draft.trim() || thinking}
                  accessibilityLabel="Enviar"
                >
                  <Icon name="send" size={18} color="#FFFFFF" />
                </Pressable>
              ) : (
                <Pressable
                  onPress={() => void toggleRecording()}
                  style={[styles.sendButton, thinking && styles.disabled]}
                  disabled={thinking}
                  accessibilityLabel="Grabar audio"
                >
                  <Icon name="mic" size={20} color="#FFFFFF" />
                </Pressable>
              )}
            </View>
          )}
          <Text style={styles.disclaimer}>
            {aiEnabled
            ? 'Confio Assistant puede equivocarse. No da asesoría de inversión y nunca mueve tu dinero sin tu confirmación.'
            : 'Te responde una persona del equipo de Confío.'}
          </Text>
          </>
        )}
        </>
        )}
        </Animated.View>
      </KeyboardAvoidingView>

      {/* The tail and the bubble itself tie the box to where it came from. */}
      {keyboardArea ? null : (
      <Animated.View
        pointerEvents="none"
        style={[styles.tail, below ? styles.tailUp : styles.tailDown, { left: tailLeft, top: tailTop, opacity: progress }]}
      />
      )}
      {keyboardArea ? null : (
      <Animated.View
        style={[styles.anchor, { left: anchor.x, top: anchor.y, opacity: progress, transform: [{ scale: grow }] }]}
      >
        <Pressable onPress={close} style={styles.anchorButton} accessibilityLabel="Cerrar mensajes">
          {aiEnabled ? (
            <AssistantMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor}
              size={50} mood={mood} />
          ) : (
            <Icon name="message-circle" size={28} color={EMERALD} />
          )}
          <View style={styles.anchorClose}>
            <Icon name="x" size={11} color="#FFFFFF" />
          </View>
        </Pressable>
      </Animated.View>
      )}

      <MascotPicker
        visible={pickerOpen}
        profile={profile}
        onClose={() => setPickerOpen(false)}
        onSaved={(next) => setProfile(next)}
      />
    </Modal>
  );
}

const styles = StyleSheet.create({
  scrim: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(6,78,59,0.22)' },
  tail: {
    position: 'absolute',
    width: 18,
    height: 18,
    backgroundColor: '#FFFFFF',
    transform: [{ rotate: '45deg' }],
    borderRadius: 3,
  },
  tailDown: {},
  tailUp: { backgroundColor: '#F0FDF4' },
  anchor: { position: 'absolute', width: 62, height: 62 },
  anchorButton: {
    width: 62,
    height: 62,
    borderRadius: 31,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#065F46',
    shadowOpacity: 0.25,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 10,
  },
  anchorClose: {
    position: 'absolute',
    top: -2,
    right: -2,
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: '#374151',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  // A floating window, not a sheet: inset from every edge, rounded all round.
  floatingArea: { position: 'absolute', left: 10, right: 10 },
  card: {
    flex: 1,
    backgroundColor: '#FFFFFF',
    borderRadius: 28,
    overflow: 'hidden',
    shadowColor: '#065F46',
    shadowOpacity: 0.2,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 10 },
    elevation: 16,
  },
  heads: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 6,
    paddingHorizontal: 12,
    paddingTop: 12,
    paddingBottom: 8,
    backgroundColor: '#F0FDF4',
  },
  head: { width: 60, alignItems: 'center' },
  headCircle: {
    width: 46,
    height: 46,
    borderRadius: 23,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#FFFFFF',
    borderWidth: 2,
    borderColor: 'transparent',
  },
  headCircleActive: { borderColor: EMERALD },
  headLabel: { fontSize: 11, color: '#6B7280', marginTop: 3 },
  headLabelActive: { color: EMERALD_DARK, fontWeight: '700' },
  headDot: {
    position: 'absolute',
    top: -1,
    right: -1,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#EF4444',
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  headsSpacer: { flex: 1 },
  channelBody: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 4,
    paddingBottom: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#E5E7EB',
    gap: 10,
  },
  headerText: { flex: 1 },
  title: { fontSize: 17, fontWeight: '700', color: '#111827' },
  subtitle: { fontSize: 13, color: '#6B7280', marginTop: 1 },
  iconButton: { padding: 8 },
  plusChip: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: EMERALD,
  },
  plusChipActive: { backgroundColor: EMERALD },
  plusChipText: { fontSize: 12, fontWeight: '700', color: EMERALD },
  plusChipTextActive: { color: '#FFFFFF' },
  humanBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 6,
    backgroundColor: '#ECFDF5',
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  humanBannerText: { fontSize: 13, color: EMERALD_DARK, flexShrink: 1 },
  humanBannerLink: { fontSize: 13, color: EMERALD, fontWeight: '700' },
  list: { paddingHorizontal: 14, paddingVertical: 12 },
  loader: { marginVertical: 16 },
  row: { marginVertical: 4, maxWidth: '86%' },
  rowMine: { alignSelf: 'flex-end', alignItems: 'flex-end' },
  rowTheirs: { alignSelf: 'flex-start', alignItems: 'flex-start' },
  bubble: { borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10 },
  bubbleMine: { backgroundColor: EMERALD, borderBottomRightRadius: 6 },
  bubbleTheirs: { backgroundColor: '#ECFDF5', borderBottomLeftRadius: 6 },
  messageRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 6 },
  messageRowMine: { justifyContent: 'flex-end' },
  msgAvatar: { width: 28, height: 28, marginBottom: 6, alignItems: 'center', justifyContent: 'center' },
  dots: { flexDirection: 'row', gap: 5, paddingVertical: 4 },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#10B981' },
  petButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  petEdit: {
    position: 'absolute',
    right: -2,
    bottom: -2,
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: EMERALD,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  petChip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: '#ECFDF5',
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  petChipText: { fontSize: 12, fontWeight: '700', color: EMERALD },
  starterPet: { borderColor: '#A7F3D0', backgroundColor: '#ECFDF5' },
  starterPetText: { fontSize: 13, color: EMERALD, fontWeight: '600' },
  bubbleTeam: { backgroundColor: '#EEF2FF', borderBottomLeftRadius: 6 },
  bubbleText: { fontSize: 15, lineHeight: 21, color: '#111827' },
  bubbleTextMine: { color: '#FFFFFF' },
  teamName: { fontSize: 12, fontWeight: '700', color: '#4338CA', marginBottom: 2 },
  voiceTag: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 2 },
  voiceTagText: { fontSize: 11, color: '#D1FAE5' },
  pending: { marginTop: 4, alignSelf: 'flex-end' },
  typing: { paddingVertical: 12, paddingHorizontal: 18 },
  chipsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 6 },
  actionChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderWidth: 1,
    borderColor: '#A7F3D0',
    backgroundColor: '#ECFDF5',
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  actionChipText: { fontSize: 13, fontWeight: '600', color: EMERALD },
  starters: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingTop: 4, paddingBottom: 4 },
  starter: {
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  starterText: { fontSize: 13, color: '#374151' },
  probe: { width: '100%', gap: 8 },
  probeQuestion: { fontSize: 15, fontWeight: '600', color: '#111827' },
  probeAnswers: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  error: { color: '#B91C1C', fontSize: 13, paddingHorizontal: 16, paddingBottom: 6 },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
    paddingHorizontal: 12,
    paddingTop: 8,
  },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 120,
    borderRadius: 22,
    backgroundColor: '#F3F4F6',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 12,
    fontSize: 15,
    color: '#111827',
  },
  sendButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: EMERALD,
    alignItems: 'center',
    justifyContent: 'center',
  },
  disabled: { opacity: 0.4 },
  recording: {
    flex: 1,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#FEF2F2',
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    gap: 8,
  },
  recDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#DC2626' },
  recText: { fontSize: 15, color: '#991B1B' },
  disclaimer: { fontSize: 11, color: '#9CA3AF', textAlign: 'center', paddingHorizontal: 24, paddingTop: 8 },
});
