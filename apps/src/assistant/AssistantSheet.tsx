// The Confio Assistant chat: typed text or voice notes in, answers plus screen
// actions out. The same thread the team answers in after a handoff.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  AppState,
  ScrollView,
  Easing,
  FlatList,
  Image,
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
import Clipboard from '@react-native-clipboard/clipboard';
import Icon from 'react-native-vector-icons/Feather';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text, TextInput } from '../components/common/AppText';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import { navigationRef } from '../navigation/RootNavigation';
import messagingService from '../services/messagingService';
import { logDoorShown } from '../services/paidOffers';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { fetchSmartAccountEntry, isSmartAccountOpen, isSmartAccountOpening } from '../services/smartAccount';
import CuentaInteligenteMark from '../components/svg/CuentaInteligenteMark';
import { QrPayIcon, QrShowIcon } from '../components/QrPayIcon';
import { MARK_MESSAGE_CHANNEL_SEEN } from '../apollo/mutations';
import { GET_DIRECT_UNREAD_SUMMARY, GET_MESSAGE_INBOX, GET_MESSAGE_INBOX_UNREAD_COUNT } from '../apollo/queries';
import { DirectInboxContent } from '../components/DirectInboxContent';
import { MessageInboxContent } from '../components/MessageInboxContent';
import { ChannelAvatar } from '../components/MessageInboxShared';
import {
  ANSWER_ASSISTANT_PROBE,
  ASK_ASSISTANT,
  ASK_ASSISTANT_WITH_PHOTO,
  PHOTO_ONLY_BODY,
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
import { TAP_ONLY_KEYS, cardFor, openDestination, resolveNavigate } from './destinations';
import { requestGuideWalk } from './guidePointer';
import ConnectionsHost from './connections/ConnectionsHost';
import ConnectionsPrompt from './connections/ConnectionsPrompt';
import MascotPicker from './MascotPicker';
import { HERE_CARDS, resolveHere, runHere, type HereAction } from './hereActions';
import { resolveTrade } from './stockTrade';
import { resolveTopUp, TopUpForm } from './TopUpForm';
import { AddressForm } from './AddressForm';
import { StockTradeCard } from './StockTradeCard';
import { PaymentIntentCard } from './PaymentIntentCard';
import { HereForm, resolveForm } from './HereForm';
import { PaymentIntentError, preparePaymentInChat } from '../services/paymentIntent';
import { paymentCodeInImage } from '../services/qrFromImage';
import { pickFromLibrary } from '../services/systemPicker';
import { useHomeGuide } from './useHomeGuide';
import AssistantPlusPanel from './AssistantPlusPanel';
import VoiceCallPanel from './VoiceCallPanel';
import { PurchaseCards } from '../agentTasks/PurchaseCards';
import { SmartContextAssistantNotice, isSmartContext } from './SmartContextNotice';
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
// On Inicio the Pagar button sits right beside the chips: the second one
// teaches what is not on screen instead (the wallet list behind the menu).
// The last one is not about money: the assistant is a general one (the
// server's ranked chips do the same, personal first and one general).
const HOME_STARTERS = [
  '¿En qué gasté más este mes?',
  'Muéstrame mi dinero',
  '¿Cómo recargo desde mi banco?',
  'Tradúceme un texto',
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

type OpenTarget = { key: string; ticker?: string; label: string; messageId?: string };

// The action that marks a message as carrying a prepared payment
// (assistant.engine.PAYMENT_CHIP): the message draws PaymentIntentCard for it.
const PAYMENT_TARGET = 'payment_intent';

// `roomy`: on Inicio these chips are how the person moves on, so each is a
// full touch target with the same type size as the other chips there.
function WalkChips({ actions, onClose, roomy }: { actions: AssistantAction[]; onClose: () => void; roomy?: boolean }) {
  const walks = actions.filter((a) => a.type === 'walk' && a.target);
  if (!walks.length) {
    return null;
  }
  return (
    <View style={[styles.chipsRow, roomy && styles.homeChipsRow]}>
      {walks.map((a) => (
        <Pressable
          key={a.target}
          onPress={() => {
            onClose();
            requestGuideWalk(a.target as string);
          }}
          style={[styles.actionChip, roomy && styles.guideChip]}
          accessibilityRole="button"
        >
          <Text style={[styles.actionChipText, roomy && styles.homeStarterText]}>{a.label || 'Muéstrame'}</Text>
          <Icon name="edit-2" size={14} color={EMERALD} />
        </Pressable>
      ))}
    </View>
  );
}

function ActionChips({ actions, messageId, onPress, roomy }: {
  actions: AssistantAction[]; messageId?: string; onPress: (target: OpenTarget) => void; roomy?: boolean;
}) {
  // `navigate` moved the app when the answer came; `card` was left here to be
  // tapped. Both stay in the conversation and open the same way.
  const known = actions
    .filter((a) => (a.type === 'navigate' || a.type === 'card') && a.target !== PAYMENT_TARGET)
    .map(resolveNavigate)
    .filter((t): t is OpenTarget => t !== null)
    // A rule proposal is opened from the message that carries it.
    .map((t) => (t.key === 'smart_account_rule' ? { ...t, messageId } : t));
  if (!known.length) {
    return null;
  }
  if (roomy) {
    // On Inicio the chat is how people get everywhere: each screen is a card
    // with its icon, its name and what it is for, the whole card a button.
    return (
      <View style={styles.actionCards}>
        {known.map((t) => {
          const card = cardFor(t.key);
          const title = t.label;
          return (
            <Pressable
              key={`${t.key}:${t.ticker ?? ''}`}
              onPress={() => onPress(t)}
              style={({ pressed }) => [styles.actionCard, pressed && styles.actionCardPressed]}
              accessibilityRole="button"
              accessibilityLabel={card.hint ? `${title}. ${card.hint}` : title}
            >
              <View style={styles.actionCardIcon}>
                {/* Pagar, Cobrar and Cuenta inteligente wear their own marks, as everywhere in the app. */}
                {card.icon === 'qr-pay' ? <QrPayIcon size={22} color={EMERALD} />
                  : card.icon === 'qr-show' ? <QrShowIcon size={22} color={EMERALD} />
                  : card.icon === 'smart-account' ? <CuentaInteligenteMark size={24} />
                  : <Icon name={card.icon} size={20} color={EMERALD} />}
              </View>
              <View style={styles.actionCardText}>
                {/* A long name on a narrow phone takes a second line rather than losing its end. */}
                <Text style={styles.actionCardTitle} numberOfLines={2}>{title}</Text>
                {card.hint ? <Text style={styles.actionCardHint} numberOfLines={1}>{card.hint}</Text> : null}
              </View>
              <Icon name="chevron-right" size={20} color="#6B7280" />
            </Pressable>
          );
        })}
      </View>
    );
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

// Things finished right here: the card is the button. It does it on this
// phone (WhatsApp, the share sheet) or changes it through the app's own
// mutation, and then says so; nothing happens before the tap.
function HereCard({ action, onPet, onReread, onLeave, roomy }: {
  action: HereAction; onPet?: () => void; onReread?: () => void; onLeave?: () => void; roomy?: boolean;
}) {
  const client = useApolloClient();
  const { userProfile, refreshProfile } = useAuth() as any;
  const [state, setState] = useState<{ working?: boolean; done?: string; error?: string }>({});
  const card = HERE_CARDS[action.key];
  const settled = !!state.done;
  const run = async () => {
    if (state.working || settled) {
      return;
    }
    setState({ working: true });
    const result = await runHere(action, {
      username: userProfile?.username,
      client,
      refreshProfile: () => refreshProfile('personal'),
      openPetPicker: onPet,
      onPetChanged: onReread,
      phoneAlerts: {
        enabled: () => messagingService.areNotificationsEnabled(),
        request: () => messagingService.requestPermissions(),
      },
      openScreen: (screen, params) => {
        // As the chips that open a screen: the floating box closes first.
        onLeave?.();
        setTimeout(() => {
          if (navigationRef.isReady()) {
            (navigationRef as any).navigate(screen, params);
          }
        }, roomy ? 0 : 250);
      },
    });
    setState(result ?? {});
  };
  const plain = settled || !!state.error;
  return (
    <Pressable
      onPress={() => void run()}
      disabled={state.working || settled}
      style={({ pressed }) => [styles.actionCard, plain ? null : styles.hereCard, pressed && !plain && styles.hereCardPressed]}
      accessibilityRole="button"
      accessibilityState={{ disabled: settled, busy: !!state.working }}
      accessibilityLabel={state.done || (state.error ? `${action.label}. ${state.error}` : `${action.label}. ${card.hint}`)}
    >
      <View style={[styles.actionCardIcon, !plain && styles.hereCardIcon]}>
        {card.icon === 'whatsapp' ? <WhatsAppLogo width={22} height={22} />
          : <Icon name={settled ? 'check' : card.icon} size={20} color={EMERALD} />}
      </View>
      <View style={styles.actionCardText}>
        <Text style={[styles.actionCardTitle, !plain && styles.hereCardTitle]} numberOfLines={2}>{action.label}</Text>
        <Text style={[styles.actionCardHint, !plain && styles.hereCardHint, !!state.error && styles.hereCardError]} numberOfLines={2}>
          {state.done || state.error || card.hint}
        </Text>
      </View>
      {state.working ? <ActivityIndicator size="small" color="#FFFFFF" style={styles.hereCardBusy} />
        : settled ? null
        : <Icon name={card.changes ? 'chevron-right' : 'arrow-up-right'} size={20} color={plain ? '#6B7280' : '#FFFFFF'} />}
    </Pressable>
  );
}

function HereCards({ actions, messageId, onPet, onReread, onLeave, roomy }: {
  actions: AssistantAction[];
  messageId?: string;
  /** Opens the pet's picker (the conversation owns it). */
  onPet?: () => void;
  /** Something the conversation itself shows changed: read the thread again. */
  onReread?: () => void;
  /** A card that opens a screen: closes the floating box first. */
  onLeave?: () => void;
  roomy?: boolean;
}) {
  const known = actions.map(resolveHere).filter((a): a is HereAction => a !== null);
  if (!known.length) {
    return null;
  }
  return (
    <View style={styles.actionCards}>
      {known.map((a) => (
        <HereCard key={`${messageId ?? ''}:${a.key}:${a.arg ?? ''}`} action={a} onPet={onPet} onReread={onReread}
          onLeave={onLeave} roomy={roomy} />
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

function Bubble({ message, onAction, onWalk, pet, onAvatar, roomy, onPrepared, onPet }: {
  message: AssistantMessage;
  onAction: (target: OpenTarget) => void;
  onWalk: () => void;
  pet: PetFace;
  roomy?: boolean;
  /** The conversation home: the assistant's face opens its settings. */
  onAvatar?: () => void;
  /** A form in this message prepared a payment: the thread has a new line. */
  onPrepared?: () => void;
  /** Opens the pet's picker, for a card that offers it. */
  onPet?: () => void;
}) {
  const mine = message.role === 'user';
  const team = message.role === 'team';
  const ai = message.role === 'assistant';
  const photo = mine && message.modality === 'PHOTO';
  // A photo sent with no words has a stand-in body for older apps: here the
  // photo itself says it.
  const words = photo && message.body === PHOTO_ONLY_BODY ? '' : message.body;
  // A long press copies the whole message (as in any chat app): text selection inside the conversation's list
  // is unreliable on Android, and the drag that opens the menu can take the press away from it.
  const [copied, setCopied] = useState(false);
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (copiedTimer.current) clearTimeout(copiedTimer.current);
  }, []);
  const copy = useCallback(() => {
    if (!words) return;
    Clipboard.setString(words);
    setCopied(true);
    if (copiedTimer.current) clearTimeout(copiedTimer.current);
    copiedTimer.current = setTimeout(() => setCopied(false), 1500);
  }, [words]);
  const extras = mine ? null : (
    <>
      {/* A prepared payment: the card reads its figures from the server by
          this message's id, and its sheet is where the person approves. */}
      {!message.pending && message.actions.some((a) => a.target === PAYMENT_TARGET)
        // (In the floating box, a modal, it sends the person to Inicio to approve.)
        ? <PaymentIntentCard messageId={message.id} onLeaveBox={roomy ? undefined : onWalk} /> : null}
      {/* A stock bought or sold here: one card per answer, approved on the card. */}
      {message.pending ? null : message.actions.map(resolveTrade).filter(Boolean).slice(0, 1).map((trade) => (
        <StockTradeCard key={`${message.id}:trade`} messageId={message.id} action={trade!}
          onLeave={roomy ? undefined : onWalk} />
      ))}
      {/* Details the person types here themselves (one form per answer). A
          top-up is its own form: it creates the order and keeps its
          instructions under it. */}
      {message.actions.map((a) => ({
        topUp: resolveTopUp(a), form: resolveForm(a),
        address: a.type === 'form' && a.target === 'ramp_address' && a.label ? a.label : null,
      })).filter((f) => f.topUp || f.form || f.address).slice(0, 1).map(({ topUp, form, address }) => (topUp ? (
          <TopUpForm key={`${message.id}:topup`} messageId={message.id} label={topUp.label} prefill={topUp.prefill}
            onLeaveBox={roomy ? undefined : onWalk} />
        ) : address ? (
          <AddressForm key={`${message.id}:address`} label={address} onOpenScreen={() => {
            onWalk();
            setTimeout(() => {
              if (navigationRef.isReady()) {
                (navigationRef as any).navigate('RampAddress');
              }
            }, roomy ? 0 : 250);
          }} />
        ) : (
          <HereForm key={`${message.id}:${form!.key}`} formKey={form!.key} label={form!.label} onPrepared={onPrepared ?? noop} />
        )))}
      <HereCards actions={message.actions} messageId={message.id} onPet={onPet} onReread={onPrepared}
        onLeave={onWalk} roomy={roomy} />
      <ActionChips actions={message.actions} messageId={message.id} onPress={onAction} roomy={roomy} />
      <WalkChips actions={message.actions} onClose={onWalk} roomy={roomy} />
      {/* A purchase the assistant is making: its products, sign-in and order, all answered here. */}
      <PurchaseCards actions={message.actions} messageId={message.id} createdAt={message.createdAt} onStores={() => {
        onWalk();
        setTimeout(() => {
          if (navigationRef.isReady()) {
            (navigationRef as any).navigate('AgentStores');
          }
        }, roomy ? 0 : 250);
      }} />
    </>
  );
  return (
    // On Inicio what an answer offers (its cards, "Muéstrame") goes under the
    // message at the conversation's own width, so the assistant's face stays
    // beside its words and the cards are not squeezed into the bubble's column.
    <View>
    <View style={[styles.messageRow, mine && styles.messageRowMine]}>
      {ai && onAvatar ? (
        <Pressable onPress={onAvatar} style={styles.msgAvatar} hitSlop={8} accessibilityRole="button"
          accessibilityLabel="Personaliza a tu asistente">
          <AssistantMascot kind={pet?.mascot} imageUrl={pet?.customPetUrl} color={pet?.mascotColor} size={26} animated={false} />
        </Pressable>
      ) : ai ? (
        <View style={styles.msgAvatar}>
          <AssistantMascot kind={pet?.mascot} imageUrl={pet?.customPetUrl} color={pet?.mascotColor} size={26} animated={false} />
        </View>
      ) : null}
    <View style={[styles.row, mine ? styles.rowMine : styles.rowTheirs]}>
      <Pressable
        onLongPress={words ? copy : undefined}
        delayLongPress={350}
        disabled={!words}
        accessibilityHint={words ? 'Mantén presionado para copiar el mensaje' : undefined}
        style={[styles.bubble, mine ? styles.bubbleMine : team ? styles.bubbleTeam : styles.bubbleTheirs]}
      >
        {team ? <Text style={styles.teamName}>{message.senderName}</Text> : null}
        {mine && message.modality === 'VOICE_NOTE' ? (
          <View style={styles.voiceTag}>
            <Icon name="mic" size={12} color="#D1FAE5" />
            <Text style={styles.voiceTagText}>Audio</Text>
          </View>
        ) : null}
        {photo ? <SentPhoto uri={message.photoUri ?? sentPhotos.get(message.id)} captioned={!!words} /> : null}
        {words ? (
          <Text style={[styles.bubbleText, mine && styles.bubbleTextMine]}>
            {words}
          </Text>
        ) : null}
        {message.pending ? <ActivityIndicator size="small" color="#D1FAE5" style={styles.pending} /> : null}
      </Pressable>
      {copied ? (
        <Text style={[styles.copied, mine && styles.copiedMine]} accessibilityLiveRegion="polite">Copiado</Text>
      ) : null}
      {roomy ? null : extras}
    </View>
    </View>
    {roomy && extras ? <View style={styles.homeExtras}>{extras}</View> : null}
    </View>
  );
}

// Photos are not kept on the server (assistant/photos.py): the bubble shows
// the file still on this phone, for as long as the app stays open.
const sentPhotos = new Map<string, string>();
// What the app sends is resized first; this only stops a file the server
// would refuse anyway (its request limit is 2.5 MB).
const PHOTO_MAX_BASE64 = 2_300_000;
type PickedPhoto = { uri: string; base64: string; type: string };

function SentPhoto({ uri, captioned }: { uri?: string; captioned: boolean }) {
  const [gone, setGone] = useState(false);
  if (!uri || gone) {
    return (
      <View style={styles.voiceTag}>
        <Icon name="image" size={12} color="#D1FAE5" />
        <Text style={styles.voiceTagText}>Foto</Text>
      </View>
    );
  }
  return (
    <Image
      source={{ uri }}
      style={[styles.sentPhoto, captioned && styles.sentPhotoCaptioned]}
      resizeMode="cover"
      onError={() => setGone(true)}
      accessible
      accessibilityLabel="Foto que enviaste"
    />
  );
}

/** The photo waiting to be sent, above the field, with its way out. */
function AttachedPhoto({ uri, onRemove }: { uri: string; onRemove: () => void }) {
  return (
    <View style={styles.attached}>
      <Image source={{ uri }} style={styles.attachedPhoto} resizeMode="cover" accessible accessibilityLabel="Foto para enviar" />
      {/* 44 to the touch, all of it inside the wrapper (Android drops touches
          outside a parent's bounds); the dark disc is what is seen. */}
      <Pressable onPress={onRemove} style={styles.attachedRemove} accessibilityRole="button"
        accessibilityLabel="Quitar foto">
        <View style={styles.attachedRemoveDisc}>
          <Icon name="x" size={14} color="#FFFFFF" />
        </View>
      </Pressable>
    </View>
  );
}

/** The conversation home (docs/designs/ai-assistant-first-redesign.md 7.3):
 * the same chat, drawn inline as Inicio instead of in the floating box. */
export type AssistantHomeProps = {
  /** Inicio is focused and nothing covers the conversation. */
  active: boolean;
  /** First name for the greeting of an empty thread. */
  name?: string;
  /** The round button's job while the field is empty (Pagar, or Cobrar for a
   * business); null when the account can do neither. */
  primary: { kind: 'pay' | 'charge'; onPress: () => void } | null;
  /** Money or a task waiting on the person, one line above the composer. */
  notice: { key: string; icon: string; text: string; onPress: () => void } | null;
};

const noop = () => {};

// The one general thing Inicio says: an open invitation to ask for anything.
// The chips under it are the person's own (see assistant/suggestions.py).
const HOME_ASK = '¿Qué quieres que haga por ti hoy?';
const HOME_ASK_TEAM = 'Escríbenos y el equipo de Confío te responde aquí.';

export default function AssistantSheet({ home }: { home?: AssistantHomeProps } = {}) {
  const insets = useSafeAreaInsets();
  const embedded = !!home;
  const {
    isOpen: boxOpen, close: closeBox, consumePrompt, consumePicker, consumePlus, consumeCall, consumeChannel, consumeDmFolder, consumeVoiceNote,
    consumeVoiceNoteData, openSeq: boxSeq, route, plan,
    setPlan, available,
    aiEnabled, bubbleAnchor, showNavNote, consumeProbe, setBoxShown, homeActive, homeSeq, open: openBox, setMicBusy,
  } = useAssistant();
  // Inicio's recorder shares the microphone with the wake word, exactly as
  // the bubble's hold-to-talk does: it takes it before recording and gives
  // it back after. (The box needs none of this: while it is open the wake
  // word is off.)
  const micHeld = useRef(false);
  const holdMic = useCallback((held: boolean) => {
    if (embedded && micHeld.current !== held) {
      micHeld.current = held;
      setMicBusy(held);
    }
  }, [embedded, setMicBusy]);
  // Inline, "open" means Inicio is on screen, and there is nothing to close:
  // an answer that moves the app simply navigates.
  const isOpen = embedded ? !!home?.active : boxOpen;
  const openSeq = embedded ? homeSeq : boxSeq;
  const close = embedded ? noop : closeBox;
  // Which chat head is open: Confio Assistant, Julian or Confío News.
  const [channel, setChannel] = useState<BoxChannel>('ia');
  const [dmFolder, setDmFolder] = useState<'inbox' | 'requests'>('inbox');
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
  // A Cuenta inteligente context: the assistant has no viewer there (see
  // SmartContextNotice), so no thread read and nothing is ever sent.
  const smartContext = isSmartContext(activeAccount);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sentThisOpen, setSentThisOpen] = useState(false);
  // The server's one-time question, asked when this opening was for it (or it's pending).
  const [askOther, setAskOther] = useState(false);
  const [mode, setMode] = useState<'AI' | 'HUMAN'>('AI');
  const [draft, setDraft] = useState('');
  const [thinking, setThinking] = useState(false);
  // True while «Volver a Confio Assistant» waits for the server (see backToAi).
  const returningRef = useRef(false);
  const [speaking, setSpeaking] = useState(false);
  const [recordingMs, setRecordingMs] = useState<number | null>(null);
  // One photo, picked and waiting to go with the next message.
  const [photo, setPhoto] = useState<PickedPhoto | null>(null);
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
  // Anything but "background" counts as in front: the state can read
  // "unknown" right after launch, and that must not stop the reads.
  const [appActive, setAppActive] = useState(AppState.currentState !== 'background');
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => setAppActive(next !== 'background'));
    return () => sub.remove();
  }, []);
  // The first steps (verify, top up, first action) are said here, in the
  // home conversation, as the assistant's newest message.
  const homeGuide = useHomeGuide(
    embedded && isOpen && available && aiEnabled && !isBusiness && !smartContext && mode === 'AI',
    contextKey,
  );
  const { data, loading, refetch, error: threadError } = useQuery(GET_ASSISTANT_THREAD, {
    variables: { limit: PAGE_SIZE, contextKey },
    skip: !isOpen || smartContext,
    fetchPolicy: 'network-only',
    notifyOnNetworkStatusChange: true,
    // Team replies arrive by polling while the sheet is open. Inicio stays
    // open far longer than the box, so it asks less often and never while
    // the app is in the background.
    pollInterval: !isOpen || (embedded && !appActive) ? 0 : mode === 'HUMAN' ? 5000 : embedded ? 30000 : 15000,
  });
  const { data: inboxData } = useQuery(GET_MESSAGE_INBOX, {
    variables: { contextKey: activeAccount?.id || 'no-account' },
    // The channel heads (and their unread dots) belong to the box.
    skip: !isOpen || embedded,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'ignore',
  });
  // Direct messages between investors: its own query, so an older server only loses the head.
  const { data: dmData } = useQuery(GET_DIRECT_UNREAD_SUMMARY, {
    skip: !isOpen || embedded,
    fetchPolicy: 'network-only',
    errorPolicy: 'ignore',
  });
  const dmSummary = dmData?.directUnreadSummary as { unreadMessages: number; requests: number } | undefined;
  const dmUnread = (dmSummary?.unreadMessages ?? 0) + (dmSummary?.requests ?? 0);
  const heads: BoxChannel[] = dmSummary || channel === 'mensajes' ? ['ia', 'mensajes', 'julian', 'confio'] : ['ia', 'julian', 'confio'];
  const openChat = useCallback(
    (conversationId: string, username: string) => {
      close();
      setTimeout(
        () => (navigationRef as any).navigate('Main', { screen: 'DirectChat', params: { conversationId, username } }),
        250,
      );
    },
    [close],
  );
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
  const [askWithPhoto] = useMutation(ASK_ASSISTANT_WITH_PHOTO);
  // People answer now: they cannot open a photo, so one waiting to go is put down.
  useEffect(() => {
    if (mode === 'HUMAN') {
      setPhoto(null);
    }
  }, [mode]);
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
    // While coming back, the server already says AI but may still be
    // answering; backToAi sets the mode when it is done.
    if (!returningRef.current) {
      setMode(thread.mode === 'HUMAN' ? 'HUMAN' : 'AI');
    }
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
    setDmFolder(consumeDmFolder() ?? 'inbox');
    setChannel(requested ?? 'ia');
    setChannelReady(true);
    if (consumePicker()) {
      setPickerOpen(true);
    }
    // No in-app purchases: the panel is only for people who already have
    // Assistant+ (status, voice minutes, managing it in their store).
    if (consumePlus() && plan?.isPlus) {
      setShowPlus(true);
    }
    if (consumeCall()) {
      void beginCall();
    }
    if (consumeVoiceNote() && aiEnabled && isVoiceNoteAvailable) {
      // Give the wake-word engine a moment to release the microphone; only
      // record if Confio Assistant is still the visible channel by then.
      holdMic(true);
      wakeTimer.current = setTimeout(() => {
        wakeTimer.current = null;
        if (recordingMs === null && channelRef.current === 'ia') {
          void toggleRecording({ fromWake: true });
        } else {
          holdMic(false);
        }
      }, 400);
      return () => {
        if (wakeTimer.current) {
          clearTimeout(wakeTimer.current);
          wakeTimer.current = null;
          holdMic(false);
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
    setPhoto(null);
  }, [activeAccount?.id]);

  // Cuenta inteligente strip: it names the account, not the AI (Confío IA+
  // is one of its benefits, never the headline) and opens the real offer.
  // Personal, non-employee viewers who do not have the account yet; shown
  // only once that is known (a failed read hides it), never by a flag.
  const personalViewer = (activeAccount?.type || '').toLowerCase() === 'personal' && !activeAccount?.isEmployee;
  const smartEntry = useSmartRead(fetchSmartAccountEntry, { skip: !personalViewer || !isOpen || embedded });
  const showSmartAccountStrip = !embedded && personalViewer && !plan?.isPlus && !smartEntry.failed
    && smartEntry.data !== undefined && !isSmartAccountOpen(smartEntry.data?.status)
    && !isSmartAccountOpening(smartEntry.data?.status);
  // Counted only when the pill is actually on screen (Confio Assistant's own
  // header, with the AI on), never for Soporte or Julian's channel.
  useEffect(() => {
    if (isOpen && showSmartAccountStrip && aiEnabled && available && channel === 'ia') {
      logDoorShown('smart_account', 'assistant_header');
    }
  }, [isOpen, showSmartAccountStrip, aiEnabled, available, channel]);
  const openSmartAccount = useCallback(() => {
    close();
    setTimeout(
      () => (navigationRef as any).navigate('Main', {
        screen: 'SmartAccountOffer',
        params: { door: 'assistant_header' },
      }),
      250,
    );
  }, [close]);

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
    ({ key, ticker, messageId }: { key: string; ticker?: string; messageId?: string }) => {
      if (key === 'messages') {
        // Mensajes lives in the box: show Julian's channel instead of leaving.
        if (embedded) {
          openBox({ channel: 'julian' });
        } else {
          setChannel('julian');
        }
        return;
      }
      close();
      setTimeout(() => openDestination(key, { isBusiness, ticker, messageId }), embedded ? 0 : 250);
    },
    [close, isBusiness, embedded, openBox],
  );

  const send = useCallback(
    async (input: {
      body?: string;
      voice?: { base64: string; mimeType: string; durationMs: number };
      photo?: PickedPhoto;
    }) => {
      const body = input.body?.trim();
      if ((!body && !input.voice && !input.photo) || thinking || smartContext) {
        return;
      }
      const gen = accountGen.current;
      // A send that did not go through gives the photo (and its words) back,
      // to the account it was sent from: never to the one switched to since.
      const giveBack = () => {
        if (input.photo && gen === accountGen.current) {
          const lost = input.photo;
          setPhoto((current) => current ?? lost);
          setDraft((current) => current || body || '');
        }
      };
      setError(null);
      setSentThisOpen(true);
      const visit = openSeqRef.current;
      const tempId = `pending-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        {
          id: tempId,
          role: 'user',
          body: body || (input.voice ? 'Escuchando tu audio…' : ''),
          createdAt: new Date().toISOString(),
          senderName: 'Tú',
          modality: input.voice ? 'VOICE_NOTE' : input.photo ? 'PHOTO' : 'TEXT',
          actions: [],
          pending: true,
          photoUri: input.photo?.uri,
        },
      ]);
      setThinking(true);
      // Written while a first step was being said: the answer keeps to it.
      const guideReply = homeGuide.beginReply();
      try {
        const { data: result } = input.photo ? await askWithPhoto({
          variables: {
            body: body || null,
            photoBase64: input.photo.base64,
            photoMimeType: input.photo.type,
            screen: route ?? null,
            timezone: deviceTimezone() ?? null,
            guideStep: guideReply?.step ?? null,
          },
        }) : await ask({
          variables: {
            body: body || null,
            audioBase64: input.voice?.base64 ?? null,
            audioMimeType: input.voice?.mimeType ?? null,
            audioDurationMs: input.voice?.durationMs ?? null,
            screen: route ?? null,
            timezone: deviceTimezone() ?? null,
            guideStep: guideReply?.step ?? null,
          },
        });
        if (gen !== accountGen.current) {
          return; // the user switched accounts while this was answering
        }
        const payload = result?.askAssistant;
        guideReply?.finish(!!payload?.success && !!payload.reply);
        if (!payload?.success) {
          setMessages((prev) => prev.filter((m) => m.id !== tempId));
          setError(payload?.error || 'No pude enviar tu mensaje.');
          giveBack();
          return;
        }
        if (input.photo && payload.userMessage?.id) {
          sentPhotos.set(payload.userMessage.id, input.photo.uri);
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
        // A paid-offer pitch is only ever opened by a tap on its chip.
        const navigateTo = (payload.actions as AssistantAction[])
          // (A prepared payment is approved on its card: it never opens a screen.)
          .filter((a) => a.type === 'navigate' && a.target !== PAYMENT_TARGET)
          .map(resolveNavigate)
          .find((t) => t !== null && !TAP_ONLY_KEYS.has(t.key));
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
        giveBack();
      } finally {
        setThinking(false);
      }
    },
    [ask, askWithPhoto, route, runAction, thinking, showNavNote, smartContext, homeGuide.beginReply],
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
    const attached = photo;
    setDraft('');
    setPhoto(null);
    void send({ body, photo: attached ?? undefined });
  };

  // The phone's own photo picker (no permission to ask for). One photo per
  // message; picking again replaces it.
  const attachPhoto = async () => {
    setError(null);
    let picked;
    try {
      picked = await pickFromLibrary({
        mediaType: 'photo',
        selectionLimit: 1,
        includeBase64: true,
        maxWidth: 1600,
        maxHeight: 1600,
        quality: 0.8,
      });
    } catch {
      setError('No pude abrir tus fotos. Inténtalo de nuevo.');
      return;
    }
    if (picked.didCancel) {
      return;
    }
    const asset = picked.assets?.[0];
    if (picked.errorCode || !asset?.base64 || !asset.uri) {
      setError('No pude abrir esa foto. Prueba con otra.');
      return;
    }
    if (asset.base64.length > PHOTO_MAX_BASE64) {
      setError('Esa foto pesa demasiado. Prueba con otra.');
      return;
    }
    // A payment QR is not a picture for the assistant to look at: the phone
    // reads the code and the server prepares the payment, which arrives in
    // the conversation as a card to review and approve.
    const code = await paymentCodeInImage(asset.uri);
    if (code) {
      setThinking(true);
      try {
        await preparePaymentInChat(code, 'shared_qr');
        // The card is a line of the thread now; if this read fails the next
        // poll brings it, so that is never reported as a QR that failed.
        await refetch().catch(() => {});
        return;
      } catch (e) {
        // Not offered to this account yet: the picture goes to the assistant
        // as any other, which points to Pagar. Any other refusal is said.
        if (!(e instanceof PaymentIntentError) || e.code !== 'unavailable') {
          setError(e instanceof PaymentIntentError ? e.message : 'No pude leer ese QR. Ábrelo en Pagar.');
          return;
        }
      } finally {
        setThinking(false);
      }
    }
    setPhoto({ uri: asset.uri, base64: asset.base64, type: asset.type || 'image/jpeg' });
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
    holdMic(false);
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
    holdMic(false);
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
    holdMic(true); // the wake word lets go of the mic
    try {
      const genAtStart = accountGen.current;
      const started = await startVoiceNote((ms) => setRecordingMs(ms));
      if (!started) {
        holdMic(false);
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
      holdMic(false);
      setError('No pude usar el micrófono.');
    }
  };

  const cancelRecording = async () => {
    if (autoStopTimer.current) {
      clearTimeout(autoStopTimer.current);
      autoStopTimer.current = null;
    }
    setRecordingMs(null);
    holdMic(false);
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

  // Coming back may answer a message left while the team had the thread
  // (server side), so the tap can take a few seconds: show it, and never
  // leave the banner stuck if the request fails.
  const [returning, setReturning] = useState(false);
  const backToAi = async () => {
    if (returningRef.current || thinking) return; // a message still sending: tap again after it
    returningRef.current = true;
    setReturning(true);
    setThinking(true); // nothing new is sent while a pending message is answered
    let failed = false;
    try {
      const { data } = await returnToAi();
      setMode(data?.returnToAssistant?.mode === 'HUMAN' ? 'HUMAN' : 'AI');
    } catch {
      // The request failed but the server may have switched anyway: take the
      // mode from a fresh read (an unchanged result doesn't re-run the effect).
      failed = true;
    } finally {
      returningRef.current = false;
      setReturning(false);
      setThinking(false);
      void refetch()
        .then((result) => {
          const mode = result?.data?.assistantThread?.mode;
          if (failed && mode) setMode(mode === 'HUMAN' ? 'HUMAN' : 'AI');
        })
        .catch(() => {});
    }
  };

  // The box grows out of the bubble and shrinks back into it.
  const { width: screenW, height: screenH } = useWindowDimensions();
  const progress = useRef(new Animated.Value(0)).current;
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (embedded) {
      return;
    }
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
  // The floating bubble waits until this box (and its bubble gliding home)
  // is gone, so two bubbles are never on screen at once.
  useEffect(() => {
    if (!embedded) {
      setBoxShown(shown);
    }
  }, [embedded, shown, setBoxShown]);

  // Android: with the keyboard up, sit right on top of it. The modal window may
  // already have shrunk (adjustResize) and the bubble may have moved too, so
  // anchoring to the bubble would lift the box twice; measure instead.
  const [modalH, setModalH] = useState(0);
  const [kbTop, setKbTop] = useState<number | null>(null);
  // Either platform: with the keyboard up, the box's bubble (often docked at
  // the bottom) would sit under it, so it steps away until the keyboard goes.
  const [kbUp, setKbUp] = useState(false);
  useEffect(() => {
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const show = Keyboard.addListener(showEvent, () => setKbUp(true));
    const hide = Keyboard.addListener(hideEvent, () => setKbUp(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);
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

  // Where the bubble sits on the screen (the user drags it anywhere).
  const rest = bubbleAnchor
    ? { ...bubbleAnchor, y: bubbleAnchor.y + statusShift }
    : { x: screenW - 62 - 12, y: boxH - insets.bottom - 62 - 76, size: 62 };
  const below = rest.y < boxH / 2; // bubble high on screen: open downward
  // While the box is open the bubble glides to the nearer corner (top or
  // bottom, same side), so the box always gets the whole height instead of
  // only the part between the bubble and one edge; it glides back on close.
  const anchor = {
    ...rest,
    y: below ? topSafe + 8 : boxH - Math.max(insets.bottom, 10) - rest.size - 8,
  };
  const dockShift = progress.interpolate({ inputRange: [0, 1], outputRange: [rest.y - anchor.y, 0] });
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
    : (embedded ? HOME_STARTERS : STARTERS).map((text) => ({ id: text, text, prompt: text, kind: 'prompt' }));
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
  // While a first step is being said its chips are the only ones offered.
  const guideStep = embedded && !thinking ? homeGuide.guide : null;
  // Inicio polls for as long as it is on screen, and Apollo reports every
  // poll as loading: there, only a load with no answer yet counts, or an
  // empty thread would lose its greeting and chips every few seconds.
  const firstLoad = loading && !messages.length && !(embedded && data?.assistantThread);
  // ...and until the server has said whether there is one, no greeting or
  // chips either: they would be swapped for the step a moment later.
  const showStarters = aiEnabled && mode === 'AI' && !thinking && !sentThisOpen && !firstLoad
    && !guideStep && !homeGuide.pending && homeGuide.settled;
  // On Inicio the chips are a way forward, not a footnote: a full touch target each.
  const starterStyle = embedded ? [styles.starter, styles.homeStarter] : styles.starter;
  const starterTextStyle = embedded ? [styles.starterText, styles.homeStarterText] : styles.starterText;
  const petName = profile?.mascotName?.trim();


  const guideChipsEl = guideStep?.chips.length ? (
    <View style={[styles.chipsRow, styles.homeChipsRow]}>
      {guideStep.chips.map((chip) => (
        <Pressable
          key={`${chip.kind}:${chip.answer}:${chip.label}`}
          onPress={() => {
            if (chip.kind === 'ask') {
              // "¿Qué es Confío?": sent as the person's own question; the step stays.
              void send({ body: chip.label });
              return;
            }
            if (chip.kind === 'pet') {
              setPickerOpen(true);
            }
            homeGuide.press(chip);
          }}
          style={[styles.actionChip, styles.guideChip, (chip.kind === 'dismiss' || chip.kind === 'skip') && styles.guideChipQuiet]}
          accessibilityRole="button"
        >
          <Text style={[styles.actionChipText, styles.homeStarterText,
            (chip.kind === 'dismiss' || chip.kind === 'skip') && styles.guideChipQuietText]}>
            {chip.label}
          </Text>
        </Pressable>
      ))}
    </View>
  ) : null;
  // In a thread with history: one more message from the assistant, the newest.
  // Once the person has written back, the reply above already answers the
  // step's sentence: only its chips stay, lined up with the assistant's text.
  const guideEl = guideStep && homeGuide.replied ? (
    guideChipsEl ? <View style={styles.guideChipsAlone}>{guideChipsEl}</View> : null
  ) : guideStep ? (
    <View style={styles.messageRow}>
      <View style={styles.msgAvatar}>
        <AssistantMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor}
          size={26} animated={false} />
      </View>
      <View style={[styles.row, styles.rowTheirs]}>
        <View style={[styles.bubble, styles.bubbleTheirs]}>
          <Text style={styles.bubbleText}>{guideStep.text}</Text>
        </View>
        {guideChipsEl}
      </View>
    </View>
  ) : embedded && homeGuide.pending && !thinking ? (
    <View style={styles.messageRow}>
      <View style={styles.msgAvatar}>
        <AssistantMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor}
          size={26} mood="thinking" />
      </View>
      <View style={[styles.bubble, styles.bubbleTheirs, styles.typing]}>
        <TypingDots />
      </View>
    </View>
  ) : null;

  const openPicker = useCallback(() => setPickerOpen(true), []);
  // One settings button, on the assistant's newest message: one on every
  // message would be a button a screen reader meets again and again.
  const newestAssistantId = reversed.find((m) => m.role === 'assistant')?.id;

  const humanBannerEl = aiEnabled && mode === 'HUMAN' ? (
            <View style={styles.humanBanner}>
              <Icon name="users" size={14} color={EMERALD_DARK} />
              <Text style={styles.humanBannerText}>El equipo verá tus mensajes y te responderá aquí.</Text>
              <Pressable onPress={backToAi} disabled={returning || thinking} hitSlop={13} accessibilityRole="button"
                accessibilityState={{ busy: returning, disabled: returning || thinking }}>
                {returning
                  ? <ActivityIndicator size="small" color={EMERALD} />
                  : <Text style={styles.humanBannerLink}>Volver a Confio Assistant</Text>}
              </Pressable>
            </View>
          ) : null;

  const listEl = (
            <FlatList
              data={reversed}
              inverted
              keyExtractor={(m) => m.id}
              renderItem={({ item }) => (
                <Bubble message={item} onAction={runAction} onWalk={close} pet={aiEnabled ? profile : null} roomy={embedded}
                  onAvatar={embedded && aiEnabled && item.id === newestAssistantId ? openPicker : undefined}
                  onPrepared={() => { void refetch(); }} onPet={aiEnabled ? openPicker : undefined} />
              )}
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
                guideEl ? guideEl : showStarters ? (
                  <View style={styles.starters}>
                    {/* The start of a visit on Inicio: the same open question
                        as an empty thread, over this person's own chips. */}
                    {embedded ? <Text style={styles.homeAskInThread}>{HOME_ASK}</Text> : null}
                    <ConnectionsPrompt where={embedded ? 'home' : 'box'} starters />
                    {profile?.mascot !== 'CUSTOM' && !embedded ? (
                    <Pressable style={[starterStyle, styles.starterPet]} accessibilityRole="button" onPress={() => setPickerOpen(true)}>
                      <Text style={[styles.starterPetText, embedded && styles.homeStarterText]}>✨ Personaliza a tu asistente</Text>
                    </Pressable>
                  ) : null}
                  {probe ? (
                    <View style={styles.probe}>
                      <Text style={styles.probeQuestion}>{probe.question}</Text>
                      <View style={styles.probeAnswers}>
                        {probe.answers.map((a) => (
                          <Pressable key={a.key} style={starterStyle} onPress={() => void answerProbe(probe, a.key)}
                            accessibilityRole="button">
                            <Text style={starterTextStyle}>{a.label}</Text>
                          </Pressable>
                        ))}
                      </View>
                    </View>
                  ) : starters.map((s) => (
                      <Pressable key={s.id} style={starterStyle} accessibilityRole="button"
                        onPress={() => void send({ body: s.prompt || s.text })}>
                        <Text style={starterTextStyle}>{s.text}</Text>
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
                ) : aiEnabled && mode === 'AI' ? (
                  <ConnectionsPrompt where={embedded ? 'home' : 'box'} starters={false} messages={sentThisOpen ? messages : undefined} />
                ) : null
              }
              ListFooterComponent={
                loading && !messages.length ? <ActivityIndicator style={styles.loader} color={EMERALD} /> : loadingMore ? (
                  <ActivityIndicator style={styles.loader} color={EMERALD} />
                ) : null
              }
            />
  );

  if (embedded) {
    const primary = home?.primary ?? null;
    const notice = home?.notice ?? null;
    const typed = draft.trim().length > 0;
    // Something to send: words, a photo, or both.
    const ready = typed || !!photo;
    const empty = !firstLoad && !messages.length && !thinking;
    // Whether people or the assistant answer is known once the thread is.
    const answeredByAi = data?.assistantThread ? !!data.assistantThread.enabled : aiEnabled;
    // Photos are for the assistant: the team cannot open them (they are not kept).
    const canAttach = answeredByAi && mode === 'AI';
    return (
      <View style={styles.home}>
        {smartContext ? (
          <View style={styles.channelBody}>
            <SmartContextAssistantNotice />
          </View>
        ) : showPlus && plan?.isPlus ? (
          <AssistantPlusPanel
            plan={plan}
            profile={profile}
            onPlan={(next) => {
              setPlan(next);
              setShowPlus(false);
            }}
            onClose={() => setShowPlus(false)}
            onLeave={() => setShowPlus(false)}
          />
        ) : callLive ? (
          <VoiceCallPanel profile={profile} />
        ) : (
          <>
            {humanBannerEl}
            {firstLoad ? (
              <View style={styles.homeCenter}>
                <ActivityIndicator color={EMERALD} />
              </View>
            ) : empty && threadError ? (
              <View style={styles.homeCenter}>
                <Text style={styles.homeSub}>No pudimos cargar tu conversación.</Text>
                <Pressable onPress={() => void refetch().catch(() => {})} style={starterStyle} accessibilityRole="button">
                  <Text style={starterTextStyle}>Reintentar</Text>
                </Pressable>
              </View>
            ) : empty ? (
              // Scrolls: the opening question with its chips is taller than a
              // small phone, and far taller than what the keyboard leaves.
              <ScrollView
                style={styles.homeEmptyScroll}
                contentContainerStyle={styles.homeEmpty}
                keyboardShouldPersistTaps="handled"
                showsVerticalScrollIndicator={false}
              >
                {answeredByAi ? (
                  <Pressable onPress={() => setPickerOpen(true)} style={styles.homeMascot} accessibilityRole="button"
                    accessibilityLabel="Personaliza a tu asistente">
                    <AssistantMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor}
                      size={56} mood={mood} />
                  </Pressable>
                ) : null}
                {!homeGuide.settled ? null : guideStep ? (
                  // The step already greets by name and asks its own question.
                  <>
                    <Text style={styles.homeGuideText}>{guideStep.text}</Text>
                    {guideChipsEl}
                  </>
                ) : homeGuide.pending ? (
                  <View style={styles.homePending}><TypingDots /></View>
                ) : (
                  <>
                    <Text style={styles.homeHello}>{home?.name ? `Hola, ${home.name}.` : 'Hola.'}</Text>
                    <Text style={styles.homeAsk}>{answeredByAi ? HOME_ASK : HOME_ASK_TEAM}</Text>
                  </>
                )}
                {showStarters ? (
                  <View style={styles.homeStarters}>
                    <ConnectionsPrompt where="home" starters />
                    {probe ? (
                      <View style={styles.probe}>
                        <Text style={styles.probeQuestion}>{probe.question}</Text>
                        <View style={styles.probeAnswers}>
                          {probe.answers.map((a) => (
                            <Pressable key={a.key} style={starterStyle} onPress={() => void answerProbe(probe, a.key)}
                              accessibilityRole="button">
                              <Text style={starterTextStyle}>{a.label}</Text>
                            </Pressable>
                          ))}
                        </View>
                      </View>
                    ) : starters.map((item) => (
                      <Pressable key={item.id} style={starterStyle} accessibilityRole="button"
                        onPress={() => void send({ body: item.prompt || item.text })}>
                        <Text style={starterTextStyle}>{item.text}</Text>
                      </Pressable>
                    ))}
                  </View>
                ) : null}
              </ScrollView>
            ) : (
              listEl
            )}

            {error ? <Text style={styles.error}>{error}</Text> : null}

            {/* While typing, a campaign or a due date gives its room to the
                conversation; money waiting on the person stays. */}
            {notice && !(kbUp && (notice.key === 'humanitarian' || notice.key === 'dues')) ? (
              <Pressable onPress={notice.onPress} style={({ pressed }) => [styles.homeNotice, pressed && styles.smartStripPressed]}
                accessibilityRole="button" accessibilityLabel={notice.text}>
                <Icon name={notice.icon} size={16} color={EMERALD} />
                <Text style={styles.homeNoticeText} numberOfLines={1}>{notice.text}</Text>
                <Icon name="chevron-right" size={18} color={EMERALD_DARK} />
              </Pressable>
            ) : null}

            {photo && recordingMs === null ? <AttachedPhoto uri={photo.uri} onRemove={() => setPhoto(null)} /> : null}

            <View style={styles.homeComposer}>
              {recordingMs !== null ? (
                <>
                  <Pressable onPress={cancelRecording} style={styles.homeIcon} accessibilityRole="button"
                    accessibilityLabel="Cancelar audio">
                    <Icon name="trash-2" size={20} color="#DC2626" />
                  </Pressable>
                  <View style={[styles.recording, styles.homeRecording]}>
                    <View style={styles.recDot} />
                    <Text style={styles.recText}>Te escucho… {formatClock(recordingMs)}</Text>
                  </View>
                  <Pressable onPress={finishRecording} style={styles.homeSend} accessibilityRole="button"
                    accessibilityLabel="Enviar audio">
                    <Icon name="send" size={20} color="#FFFFFF" />
                  </Pressable>
                </>
              ) : (
                <>
                  {answeredByAi && plan?.voiceCallsEnabled && mode === 'AI' ? (
                    <Pressable onPress={beginCall} style={styles.homeIcon} accessibilityRole="button"
                      accessibilityLabel="Llamar a Confio Assistant">
                      <Icon name="phone" size={20} color={EMERALD} />
                    </Pressable>
                  ) : null}
                  <View style={styles.homeField}>
                    {canAttach ? (
                      <Pressable onPress={() => void attachPhoto()} style={[styles.homeAttach, thinking && styles.disabled]}
                        disabled={thinking} accessibilityRole="button"
                        accessibilityLabel={photo ? 'Cambiar la foto' : 'Adjuntar una foto'}>
                        <Icon name="image" size={20} color="#374151" />
                      </Pressable>
                    ) : null}
                    <TextInput
                      style={[styles.homeInput, canAttach && styles.homeInputAfterAttach]}
                      value={draft}
                      onChangeText={setDraft}
                      // Short on purpose: the field shares the row with the main
                      // button, and the mic inside it already says "audio".
                      placeholder={askOther ? '¿Para qué lo usarías?' : photo ? 'Agrega un mensaje' : 'Pídeme lo que quieras'}
                      placeholderTextColor="#4B5563"
                      multiline
                      maxLength={2000}
                      editable={!thinking}
                    />
                    {isVoiceNoteAvailable && !ready ? (
                      <Pressable onPress={() => void toggleRecording()} style={[styles.homeMic, thinking && styles.disabled]}
                        disabled={thinking} accessibilityRole="button" accessibilityLabel="Grabar audio">
                        <Icon name="mic" size={20} color="#374151" />
                      </Pressable>
                    ) : null}
                  </View>
                  {ready || !primary ? (
                    <Pressable onPress={submitDraft} style={[styles.homeSend, (!ready || thinking) && styles.disabled]}
                      disabled={!ready || thinking} accessibilityRole="button" accessibilityLabel="Enviar">
                      <Icon name="send" size={20} color="#FFFFFF" />
                    </Pressable>
                  ) : (
                    // Round, the size of the send button it turns into: the field
                    // never changes width when the person starts typing.
                    <Pressable onPress={primary.onPress} style={({ pressed }) => [styles.homeSend, pressed && styles.homePrimaryPressed]}
                      accessibilityRole="button"
                      accessibilityLabel={primary.kind === 'pay' ? 'Pagar con QR' : 'Cobrar'}>
                      {primary.kind === 'pay' ? <QrPayIcon size={26} color="#FFFFFF" /> : <QrShowIcon size={26} color="#FFFFFF" />}
                    </Pressable>
                  )}
                </>
              )}
            </View>
            {/* With the keyboard up the line gives its room to the conversation. */}
            {kbUp ? <View style={styles.homeKeyboardGap} /> : (
              <Text style={[styles.disclaimer, styles.homeDisclaimer]}>
                {answeredByAi
                  ? 'Confio Assistant puede equivocarse. No da asesoría de inversión y nunca mueve tu dinero sin tu confirmación.'
                  : 'Te responde una persona del equipo de Confío.'}
              </Text>
            )}
          </>
        )}
        <MascotPicker
          visible={pickerOpen}
          profile={profile}
          onClose={() => setPickerOpen(false)}
          onSaved={(next) => setProfile(next)}
        />
        <ConnectionsHost where="home" />
      </View>
    );
  }

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
          {heads
            .map((id) => (
              <Pressable
                key={id}
                onPress={() => (id === 'ia' && homeActive ? close() : setChannel(id))}
                onLongPress={id === 'ia' && aiEnabled && !smartContext ? () => setPickerOpen(true) : undefined}
                style={styles.head}
                accessibilityRole="tab"
                accessibilityState={{ selected: channel === id }}
                accessibilityLabel={id === 'ia' ? (aiEnabled ? 'Confio Assistant' : 'Soporte') : id === 'mensajes' ? 'Mensajes' : id === 'julian' ? 'Julian Moon' : 'Confío News'}
              >
                <View style={[styles.headCircle, channel === id && styles.headCircleActive]}>
                  {id === 'ia' && !aiEnabled ? (
                    <ChannelAvatar channel={{ id: 'soporte' } as any} large />
                  ) : id === 'mensajes' ? (
                    <Icon name="message-circle" size={22} color={EMERALD_DARK} />
                  ) : id === 'ia' ? (
                    <AssistantMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor}
                      size={36} mood={channel === 'ia' ? mood : 'idle'} animated={channel === 'ia'} />
                  ) : (
                    <ChannelAvatar channel={{ id } as any} large />
                  )}
                  {id !== 'ia' && (id === 'mensajes' ? dmUnread : unreadByChannel[id]) > 0 && channel !== id ? <View style={styles.headDot} /> : null}
                </View>
                <Text style={[styles.headLabel, channel === id && styles.headLabelActive]} numberOfLines={1}>
                  {id === 'ia' ? (aiEnabled ? petName || 'Confio Assistant' : 'Soporte') : id === 'mensajes' ? 'Mensajes' : id === 'julian' ? 'Julian' : 'News'}
                </Text>
              </Pressable>
            ))}
          <View style={styles.headsSpacer} />
          <Pressable onPress={close} style={styles.iconButton} accessibilityLabel="Cerrar">
            <Icon name="x" size={22} color="#374151" />
          </Pressable>
        </View>

        {channel === 'mensajes' ? (
          <View style={styles.channelBody}>
            <DirectInboxContent key={dmFolder} initialFolder={dmFolder} onOpenConversation={(c) => openChat(c.id, c.other.username)} />
          </View>
        ) : channel !== 'ia' ? (
          <View style={styles.channelBody}>
            <MessageInboxContent embeddedChannelId={channel} onExit={() => setChannel('ia')} onOpenPost={openPost} />
          </View>
        ) : smartContext ? (
          <View style={styles.channelBody}>
            <SmartContextAssistantNotice />
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
          {aiEnabled && plan?.isPlus ? (
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
        {aiEnabled && showSmartAccountStrip ? (
          // Its own line under the header (a pill inside the header row
          // squeezed the title into a letter-per-line column on phones).
          <Pressable
            onPress={openSmartAccount}
            style={({ pressed }) => [styles.smartStrip, pressed && styles.smartStripPressed]}
            accessibilityRole="button"
            accessibilityLabel="Conoce Cuenta inteligente"
          >
            <View style={styles.smartStripMark}>
              <CuentaInteligenteMark size={34} />
            </View>
            <View style={styles.smartStripText}>
              <Text style={styles.smartStripTitle} numberOfLines={1}>Conoce Cuenta inteligente</Text>
              <Text style={styles.smartStripSub} numberOfLines={1}>Tu dinero se mueve según tus reglas</Text>
            </View>
            <Icon name="chevron-right" size={18} color="#065F46" />
          </Pressable>
        ) : null}

        {showPlus && plan?.isPlus ? (
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
          {humanBannerEl}

          {listEl}

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
            <>
            {photo ? <AttachedPhoto uri={photo.uri} onRemove={() => setPhoto(null)} /> : null}
            <View style={styles.composer}>
              {aiEnabled && mode === 'AI' ? (
                <Pressable onPress={() => void attachPhoto()} style={[styles.iconButton, thinking && styles.disabled]}
                  disabled={thinking} hitSlop={6} accessibilityRole="button"
                  accessibilityLabel={photo ? 'Cambiar la foto' : 'Adjuntar una foto'}>
                  <Icon name="image" size={20} color="#374151" />
                </Pressable>
              ) : null}
              <TextInput
                style={styles.input}
                value={draft}
                onChangeText={setDraft}
                placeholder={askOther ? 'Cuéntame para qué te gustaría usarlo'
                  : photo ? 'Agrega un mensaje'
                  : isVoiceNoteAvailable ? 'Escríbeme o mándame un audio' : 'Escríbeme'}
                placeholderTextColor="#9CA3AF"
                multiline
                maxLength={2000}
                editable={!thinking}
              />
              {draft.trim() || photo || !isVoiceNoteAvailable ? (
                <Pressable
                  onPress={submitDraft}
                  style={[styles.sendButton, ((!draft.trim() && !photo) || thinking) && styles.disabled]}
                  disabled={(!draft.trim() && !photo) || thinking}
                  accessibilityRole="button"
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
            </>
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
      {keyboardArea || kbUp ? null : (
      <Animated.View
        pointerEvents="none"
        style={[styles.tail, below ? styles.tailUp : styles.tailDown, { left: tailLeft, top: tailTop, opacity: progress }]}
      />
      )}
      {keyboardArea || kbUp ? null : (
      <Animated.View
        // No scale: it starts exactly where (and as big as) the floating bubble was.
        style={[styles.anchor, { left: anchor.x, top: anchor.y, transform: [{ translateY: dockShift }] }]}
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
      <ConnectionsHost where="box" />
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
  // Cuenta inteligente probe: a quiet mint strip under the header, never
  // violet (violet reads as an AI unlock, design review 11).
  smartStrip: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: 16,
    marginTop: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 14,
    backgroundColor: '#ECFDF5',
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  smartStripPressed: { backgroundColor: '#D1FAE5' },
  smartStripMark: { marginRight: 10 },
  smartStripText: { flex: 1 },
  smartStripTitle: { fontSize: 14, fontWeight: '700', color: '#065F46' },
  smartStripSub: { fontSize: 12, color: '#047857', marginTop: 1 },
  starterPet: { borderColor: '#A7F3D0', backgroundColor: '#ECFDF5' },
  starterPetText: { fontSize: 13, color: EMERALD, fontWeight: '600' },
  bubbleTeam: { backgroundColor: '#EEF2FF', borderBottomLeftRadius: 6 },
  bubbleText: { fontSize: 15, lineHeight: 21, color: '#111827' },
  bubbleTextMine: { color: '#FFFFFF' },
  copied: { fontSize: 11, color: '#6B7280', marginTop: 2, marginLeft: 4 },
  copiedMine: { alignSelf: 'flex-end', marginLeft: 0, marginRight: 4 },
  teamName: { fontSize: 12, fontWeight: '700', color: '#4338CA', marginBottom: 2 },
  voiceTag: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 2 },
  // In the person's own bubble, inside its padding.
  sentPhoto: { width: 184, height: 184, borderRadius: 10, marginVertical: 2, backgroundColor: '#065F46' },
  sentPhotoCaptioned: { marginBottom: 8 },
  // Waiting above the field, on the field's own left edge.
  attached: { alignSelf: 'flex-start', marginLeft: 12, marginTop: 2, paddingTop: 6, paddingRight: 16 },
  attachedPhoto: { width: 64, height: 64, borderRadius: 12, backgroundColor: '#F3F4F6' },
  attachedRemove: {
    position: 'absolute',
    top: 0,
    right: 0,
    width: 44,
    height: 44,
    alignItems: 'flex-end',
    justifyContent: 'flex-start',
    paddingRight: 6,
  },
  attachedRemoveDisc: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: '#111827',
    borderWidth: 2,
    borderColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
  },
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
  // Cards under an answer on Inicio: as wide as the column allows, one per
  // line, each a full touch target.
  actionCards: { gap: 8, marginTop: 4, marginBottom: 4, maxWidth: 340 },
  // Under the assistant's words: past its face (28) and the row's gap (6).
  homeExtras: { marginLeft: 34 },
  // A card that does the thing when tapped reads as the button it is: filled.
  hereCard: { backgroundColor: EMERALD, borderColor: EMERALD },
  hereCardPressed: { backgroundColor: EMERALD_DARK },
  hereCardIcon: { backgroundColor: '#FFFFFF' },
  hereCardTitle: { color: '#FFFFFF' },
  hereCardHint: { color: '#D1FAE5' },
  hereCardError: { color: '#B91C1C' },
  hereCardBusy: { width: 20 },
  actionCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 60,
    paddingVertical: 10,
    paddingLeft: 12,
    paddingRight: 8,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#A7F3D0',
    backgroundColor: '#FFFFFF',
  },
  actionCardPressed: { backgroundColor: '#ECFDF5' },
  actionCardIcon: {
    width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', backgroundColor: '#ECFDF5',
  },
  actionCardText: { flex: 1 },
  actionCardTitle: { fontSize: 15, fontWeight: '700', color: '#111827' },
  actionCardHint: { fontSize: 13, lineHeight: 18, color: '#4B5563', marginTop: 1 },
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
  // ── The conversation as Inicio ──
  home: { flex: 1, backgroundColor: '#FFFFFF' },
  homeCenter: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, paddingHorizontal: 24 },
  homeEmptyScroll: { flex: 1 },
  homeEmpty: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 24, paddingVertical: 16, gap: 6 },
  homeHello: { fontSize: 17, lineHeight: 24, fontWeight: '600', color: '#4B5563', marginTop: 12 },
  homeSub: { fontSize: 17, lineHeight: 24, color: '#4B5563' },
  // The invitation is the headline of an empty Inicio, not a caption under "Hola".
  homeAsk: { fontSize: 22, lineHeight: 30, fontWeight: '700', color: '#111827' },
  homeAskInThread: { width: '100%', fontSize: 17, lineHeight: 24, fontWeight: '700', color: '#111827', marginTop: 8, marginBottom: 2 },
  homeStarters: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 18 },
  homeGuideText: { fontSize: 20, lineHeight: 28, fontWeight: '600', color: '#111827', marginTop: 12, marginBottom: 8 },
  homePending: { marginTop: 16 },
  // First-step chips are the way forward: a full touch target each.
  guideChip: { minHeight: 44, paddingHorizontal: 14 },
  // Avatar width (28) + the row's gap (6): under the assistant's text.
  guideChipsAlone: { marginLeft: 34 },
  guideChipQuiet: { backgroundColor: '#FFFFFF', borderColor: '#E5E7EB' },
  guideChipQuietText: { color: '#4B5563' },
  homeNotice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 12,
    marginBottom: 2,
    minHeight: 44,
    paddingHorizontal: 14,
    borderRadius: 14,
    backgroundColor: '#ECFDF5',
  },
  homeNoticeText: { flex: 1, fontSize: 14, fontWeight: '600', color: EMERALD_DARK },
  homeComposer: {
    flexDirection: 'row', alignItems: 'flex-end', gap: 8, paddingHorizontal: 12, paddingTop: 8, backgroundColor: '#FFFFFF',
  },
  homeField: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'flex-end',
    minHeight: 48,
    borderRadius: 24,
    backgroundColor: '#F3F4F6',
  },
  homeInput: {
    flex: 1,
    maxHeight: 120,
    paddingLeft: 18,
    paddingRight: 8,
    paddingTop: 13,
    paddingBottom: 13,
    fontSize: 16,
    color: '#111827',
  },
  homeMic: { width: 46, height: 48, alignItems: 'center', justifyContent: 'center' },
  homeAttach: { width: 46, height: 48, alignItems: 'center', justifyContent: 'center' },
  // The photo button already gives the field its left room.
  homeInputAfterAttach: { paddingLeft: 0 },
  homeIcon: { width: 44, height: 48, alignItems: 'center', justifyContent: 'center' },
  homeRecording: { height: 48, borderRadius: 24 },
  homeSend: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: EMERALD,
    alignItems: 'center',
    justifyContent: 'center',
  },
  // Pagar (Cobrar for a business), the one thing Inicio does without the
  // assistant, is the same round button as send.
  homePrimaryPressed: { backgroundColor: EMERALD_DARK },
  // Always on screen here, so it must be readable: gray-500 is 4.8:1 on white.
  // (The app's root already keeps Inicio above the system bar: no inset here.)
  homeDisclaimer: { paddingTop: 6, paddingBottom: 8, color: '#6B7280' },
  homeMascot: { alignSelf: 'flex-start' },
  homeStarter: { minHeight: 44, paddingHorizontal: 14, justifyContent: 'center' },
  homeStarterText: { fontSize: 15 },
  homeChipsRow: { gap: 8 },
  homeKeyboardGap: { height: 8 },
});
