// The floating entry to Confio Assistant and the message box, on every screen.
// It indicates (unread badge, live call), suggests (one hint per screen,
// sparingly) and opens the chat. Drag it to either edge if it covers
// something; it snaps there and remembers the spot.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  Image,
  Keyboard,
  NativeModules,
  PanResponder,
  Pressable,
  StyleSheet,
  View,
  useWindowDimensions,
} from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text } from '../components/common/AppText';
import { GET_MESSAGE_INBOX_UNREAD_COUNT } from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { GET_ASSISTANT_THREAD, UPDATE_ASSISTANT_PROFILE, GET_ASSISTANT_SUGGESTIONS, type AssistantSuggestion } from './api';
import AssistantMascot from './AssistantMascot';
import { useAssistant } from './AssistantContext';
import { DOCK_ROUTES, HIDDEN_ROUTES, TAB_ROUTES, hintFor, type ScreenHint } from './suggestions';
import { MAX_VOICE_NOTE_MS, cancelVoiceNote, isVoiceNoteAvailable, startVoiceNote, stopVoiceNote } from './voiceNote';

// Hold still this long to start talking; moving earlier is a drag.
const HOLD_TO_TALK_MS = 300;

const SIZE = 62;
const EDGE = 12;
const TAB_BAR_HEIGHT = 64;
// Stack screens usually end in a primary button: start above it.
const STACK_BOTTOM_CLEARANCE = 96;
const HINT_DELAY_MS = 1800;
const HINT_VISIBLE_MS = 7000;
const HINT_COOLDOWN_MS = 45_000;
const MAX_HINTS_PER_SESSION = 4;

type Hint = ScreenHint & { kind: 'screen' | 'unread' | 'note' | 'probe' };
// What the chat said when it moved the app ("Abrí Recargar: …").
const NOTE_VISIBLE_MS = 10_000;
// Longest the bubble waits for a custom pet photo before appearing anyway.
const PHOTO_WAIT_MS = 2500;
const NOTE_MAX_CHARS = 180;

export default function AssistantBubble() {
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const { route, isOpen, open, setAvailable, setAiEnabled, inCall, setBubbleAnchor, setMicBusy, navNote, boxShown } = useAssistant();
  const { isAuthenticated, isLoading: authLoading, accountContextTick } = useAuth();
  const { activeAccount } = useAccount();
  const [keyboardUp, setKeyboardUp] = useState(false);
  const [hint, setHint] = useState<Hint | null>(null);
  const hintRef = useRef<Hint | null>(null);
  hintRef.current = hint;
  const [side, setSide] = useState<'left' | 'right'>('right');
  const [heightFraction, setHeightFraction] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [talking, setTalking] = useState(false);
  const seenHints = useRef(new Set<string>());
  const lastHintAt = useRef(0);
  const hintsShown = useRef(0);
  const lastUnreadHinted = useRef(0);
  const positionLoaded = useRef(false);

  const enabled = isAuthenticated && !authLoading;
  const contextKey = activeAccount?.id || 'no-account';
  const { data: unreadData, refetch: refetchUnread } = useQuery(GET_MESSAGE_INBOX_UNREAD_COUNT, {
    variables: { contextKey },
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'cache-first',
    skip: !enabled,
  });
  // Profile only (mascot, color, position). Fails quietly on servers without Confio Assistant.
  const { data: threadData, loading: threadLoading } = useQuery(GET_ASSISTANT_THREAD, {
    variables: { limit: 1, contextKey },
    fetchPolicy: 'cache-and-network',
    skip: !enabled,
    errorPolicy: 'ignore',
  });
  // Hints ranked for this person on the server; the built-in list is the fallback.
  const { data: suggestionData } = useQuery(GET_ASSISTANT_SUGGESTIONS, {
    variables: { screen: route ?? null, contextKey },
    skip: !enabled || !threadData?.assistantThread?.enabled,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'ignore',
  });
  const serverHintsRef = useRef<AssistantSuggestion[] | null>(null);
  serverHintsRef.current = suggestionData?.assistantSuggestions?.hints ?? null;
  const [saveProfile] = useMutation(UPDATE_ASSISTANT_PROFILE);
  const profile = threadData?.assistantThread?.profile;
  // Appear only once we know what to show and where: before the profile
  // arrives the bubble would be the generic icon at the default spot, then
  // jump to the user's pet and saved position. A custom pet's photo is
  // fetched first (at most PHOTO_WAIT_MS) so it never shows an empty circle.
  const settled = !!threadData || !threadLoading;
  const petUrl = profile?.mascot === 'CUSTOM' ? profile?.customPetUrl : null;
  const [photoReady, setPhotoReady] = useState(false);
  useEffect(() => {
    if (!petUrl || photoReady) {
      return undefined;
    }
    let done = false;
    const finish = () => {
      if (!done) {
        done = true;
        setPhotoReady(true);
      }
    };
    const timer = setTimeout(finish, PHOTO_WAIT_MS);
    Image.prefetch(petUrl).then(finish, finish);
    return () => {
      done = true;
      clearTimeout(timer);
    };
  }, [petUrl, photoReady]);
  // The saved side/height land one render after the profile (an effect).
  const [positionApplied, setPositionApplied] = useState(false);
  const ready = settled && (!profile || positionApplied) && (!petUrl || photoReady);
  // The support chat exists (server knows it) / is answered by Confio Assistant.
  const chatAvailable = !!threadData?.assistantThread;
  const iaAvailable = !!threadData?.assistantThread?.enabled;
  const unread = unreadData?.messageInboxUnreadCount || 0;

  useEffect(() => {
    setAvailable(chatAvailable);
    setAiEnabled(iaAvailable);
  }, [chatAvailable, iaAvailable, setAvailable, setAiEnabled]);

  useEffect(() => {
    if (profile && !positionLoaded.current) {
      positionLoaded.current = true;
      setSide(profile.bubbleSide === 'left' ? 'left' : 'right');
      setHeightFraction(Math.min(Math.max(Number(profile.bubbleHeight) || 0, 0), 1));
      setPositionApplied(true);
    }
  }, [profile]);

  useEffect(() => {
    if (enabled) {
      void refetchUnread();
    }
  }, [enabled, accountContextTick, contextKey, refetchUnread, isOpen]);

  useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', () => setKeyboardUp(true));
    const hide = Keyboard.addListener('keyboardDidHide', () => setKeyboardUp(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  // Vertical travel: below the header, above the tab bar (tabs) or the
  // usual bottom button (other screens).
  const onTab = !!route && TAB_ROUTES.has(route);
  const topLimit = insets.top + 72;
  const bottomLimit = height - insets.bottom - SIZE - (onTab ? TAB_BAR_HEIGHT + EDGE : STACK_BOTTOM_CLEARANCE);
  const range = Math.max(bottomLimit - topLimit, 0);
  // On money screens the bubble rests mostly behind the edge (still tappable,
  // draggable and holdable); it comes fully out while dragged or recording.
  const docked = !!route && DOCK_ROUTES.has(route) && !dragging && !talking && hint?.kind !== 'note';
  const peek = SIZE * 0.4;
  const restX = docked
    ? (side === 'right' ? width - peek : peek - SIZE)
    : (side === 'right' ? width - SIZE - EDGE : EDGE);
  const restY = bottomLimit - heightFraction * range;

  useEffect(() => {
    setBubbleAnchor({ x: restX, y: restY, size: SIZE });
  }, [restX, restY, setBubbleAnchor]);

  const pan = useRef(new Animated.ValueXY({ x: restX, y: restY })).current;
  const placed = useRef(false);
  const fade = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!ready) {
      return;
    }
    if (!placed.current) {
      // First appearance: straight at the saved spot, fading in.
      placed.current = true;
      pan.setValue({ x: restX, y: restY });
      Animated.timing(fade, { toValue: 1, duration: 220, useNativeDriver: false }).start();
      return;
    }
    if (!dragging) {
      Animated.spring(pan, { toValue: { x: restX, y: restY }, useNativeDriver: false, friction: 7 }).start();
    }
  }, [ready, restX, restY, dragging, pan, fade]);

  // Hold to talk: press and hold still → record a voice note; release →
  // send it to Confio Assistant; slide away → cancel.
  const talkingRef = useRef(false);
  const cancelledRef = useRef(false);
  const talkAccount = useRef<string | undefined>(undefined);
  const talkTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentAccount = useRef<string | undefined>(undefined);
  currentAccount.current = activeAccount?.id;
  const endTalk = () => {
    talkingRef.current = false;
    setTalking(false);
    setMicBusy(false);
    if (talkTimer.current) {
      clearTimeout(talkTimer.current);
      talkTimer.current = null;
    }
  };
  const pulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!talking) {
      pulse.stopAnimation();
      pulse.setValue(0);
      return undefined;
    }
    const loop = Animated.loop(
      Animated.timing(pulse, { toValue: 1, duration: 900, easing: Easing.out(Easing.quad), useNativeDriver: true }),
    );
    loop.start();
    return () => loop.stop();
  }, [talking, pulse]);

  const cancelTalking = () => {
    if (!talkingRef.current) {
      return;
    }
    cancelledRef.current = true;
    endTalk();
    void cancelVoiceNote();
  };
  // An account switch mid-hold drops the note, and the previous account's
  // post-navigation note goes too.
  useEffect(() => {
    cancelTalking();
    setHint((prev) => (prev?.kind === 'note' ? null : prev));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeAccount?.id]);

  const startTalking = async () => {
    if (!iaAvailable || !isVoiceNoteAvailable) {
      open();
      return;
    }
    cancelledRef.current = false;
    talkingRef.current = true;
    talkAccount.current = currentAccount.current;
    setTalking(true);
    setMicBusy(true); // the wake word lets go of the mic
    setHint(null);
    // Same two-minute limit as the sheet's recorder: send what we have.
    talkTimer.current = setTimeout(() => finishTalking(), MAX_VOICE_NOTE_MS);
    NativeModules.ConfioAudioRoute?.impact?.();
    // The mic permission is asked here, on the first hold, never at launch.
    const started = await startVoiceNote().catch(() => false);
    if (!started) {
      endTalk();
      if (!cancelledRef.current) {
        open(); // e.g. permission declined: the chat still works by text
      }
    }
  };

  const finishTalking = () => {
    // Deferred one tick: a drag that steals the touch cancels first.
    setTimeout(async () => {
      if (!talkingRef.current || cancelledRef.current) {
        return;
      }
      const account = talkAccount.current;
      endTalk();
      const note = await stopVoiceNote().catch(() => null);
      // Recorded under another account (switched while finalizing): drop it.
      if (note && account === currentAccount.current && !cancelledRef.current) {
        open({ channel: 'ia', voiceNoteData: { ...note, accountId: account } });
      } else {
        // Released before the mic was up (or a tap-length hold): also stop a
        // start still in flight, so it never records unattended.
        void cancelVoiceNote();
      }
    }, 0);
  };

  const start = useRef({ x: 0, y: 0 });
  const geometry = useRef({ width, topLimit, bottomLimit, range });
  geometry.current = { width, topLimit, bottomLimit, range };

  const responder = useMemo(
    () =>
      PanResponder.create({
        // Taps stay taps; only a real drag moves the bubble.
        onMoveShouldSetPanResponderCapture: (_e, g) => Math.abs(g.dx) + Math.abs(g.dy) > 6,
        onPanResponderGrant: () => {
          // Sliding while talking cancels the note (and doesn't move the bubble).
          cancelTalking();
          setDragging(true);
          setHint(null);
          start.current = { x: (pan.x as any)._value, y: (pan.y as any)._value };
        },
        onPanResponderMove: (_e, g) => {
          pan.setValue({ x: start.current.x + g.dx, y: start.current.y + g.dy });
        },
        onPanResponderRelease: (_e, g) => {
          const { width: w, topLimit: top, bottomLimit: bottom, range: r } = geometry.current;
          const x = start.current.x + g.dx + SIZE / 2;
          const y = Math.min(Math.max(start.current.y + g.dy, top), bottom);
          const nextSide: 'left' | 'right' = x < w / 2 ? 'left' : 'right';
          const nextFraction = r > 0 ? (bottom - y) / r : 0;
          setSide(nextSide);
          setHeightFraction(nextFraction);
          setDragging(false);
          void saveProfile({
            variables: { bubbleSide: nextSide, bubbleHeight: Math.round(nextFraction * 1000) / 1000 },
          }).catch(() => {});
        },
        onPanResponderTerminate: () => setDragging(false),
      }),
    [pan, saveProfile],
  );

  const visible = enabled && !isOpen && !boxShown && !keyboardUp && !(route && HIDDEN_ROUTES.has(route));

  // The chat just moved the app: say here what it said there. Not a
  // suggestion, so no cooldown or session cap, and it survives the route change.
  useEffect(() => {
    const text = navNote?.text.trim();
    if (!text) {
      return;
    }
    const short = text.length > NOTE_MAX_CHARS ? `${text.slice(0, NOTE_MAX_CHARS - 1).trimEnd()}…` : text;
    setHint({ kind: 'note', hint: short, prompt: '' });
  }, [navNote]);

  // Suggest at most one thing per screen visit, rarely, and never twice.
  useEffect(() => {
    setHint((prev) => (prev?.kind === 'note' ? prev : null));
    if (!visible || inCall || docked || hintsShown.current >= MAX_HINTS_PER_SESSION) {
      return undefined;
    }
    const timer = setTimeout(() => {
      if (Date.now() - lastHintAt.current < HINT_COOLDOWN_MS) {
        return;
      }
      if (hintRef.current?.kind === 'note') {
        return;
      }
      let next: Hint | null = null;
      if (unread > lastUnreadHinted.current) {
        lastUnreadHinted.current = unread;
        next = {
          kind: 'unread',
          hint: unread === 1 ? 'Tienes un mensaje nuevo.' : `Tienes ${unread} mensajes nuevos.`,
          prompt: '',
        };
      } else if (iaAvailable) {
        const fromServer = serverHintsRef.current?.find((h) => !seenHints.current.has(h.text));
        if (fromServer) {
          next = fromServer.kind === 'probe'
            ? { kind: 'probe', hint: fromServer.text, prompt: '' }
            : { kind: 'screen', hint: fromServer.text, prompt: fromServer.kind === 'picker' ? '' : fromServer.prompt };
        } else {
          const screenHint = hintFor(route, seenHints.current);
          next = screenHint ? { ...screenHint, kind: 'screen' } : null;
        }
      }
      if (!next) {
        return;
      }
      seenHints.current.add(next.hint);
      lastHintAt.current = Date.now();
      hintsShown.current += 1;
      setHint(next);
    }, HINT_DELAY_MS);
    return () => clearTimeout(timer);
  }, [route, visible, unread, iaAvailable, inCall, docked]);

  useEffect(() => {
    if (!hint) {
      return undefined;
    }
    const timer = setTimeout(() => setHint(null), hint.kind === 'note' ? NOTE_VISIBLE_MS : HINT_VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [hint]);

  if (!visible || !ready) {
    return null;
  }

  const onPress = () => {
    // Without Confio Assistant the box shows the classic support thread instead.
    open();
  };

  const onHintPress = () => {
    const current = hint;
    setHint(null);
    if (!current) {
      return;
    }
    if (current.kind === 'probe') {
      open({ probe: true });
    } else if (current.kind === 'unread' || current.kind === 'note') {
      // Unread: the box shows a red dot on whichever chat head has news.
      // Note: back to the conversation that moved the app.
      open();
    } else if (current.prompt) {
      open({ prompt: current.prompt });
    } else {
      open({ picker: true });
    }
  };

  const hintAbove = restY - topLimit > 90;

  return (
    <View pointerEvents="box-none" style={StyleSheet.absoluteFill}>
      <Animated.View
        style={[styles.bubbleWrap, { opacity: fade, transform: pan.getTranslateTransform() }]}
        {...responder.panHandlers}
      >
        {hint && !dragging ? (
          <View
            style={[
              styles.hint,
              side === 'right' ? styles.hintRight : styles.hintLeft,
              hintAbove ? styles.hintAbove : styles.hintBelow,
              { maxWidth: Math.min(280, width - 2 * EDGE) },
            ]}
          >
            <Pressable onPress={onHintPress} style={styles.hintBody} accessibilityRole="button">
              <Text style={styles.hintText}>{hint.hint}</Text>
            </Pressable>
            <Pressable onPress={() => setHint(null)} hitSlop={10} accessibilityLabel="Cerrar sugerencia">
              <Icon name="x" size={14} color="#9CA3AF" />
            </Pressable>
          </View>
        ) : null}
        {talking ? (
          <Animated.View
            pointerEvents="none"
            style={[
              styles.talkRing,
              {
                opacity: pulse.interpolate({ inputRange: [0, 1], outputRange: [0.55, 0] }),
                transform: [{ scale: pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.7] }) }],
              },
            ]}
          />
        ) : null}
        <Pressable
          onPress={onPress}
          onLongPress={() => void startTalking()}
          onPressOut={finishTalking}
          delayLongPress={HOLD_TO_TALK_MS}
          style={[styles.button, inCall && styles.buttonInCall, talking && styles.buttonTalking]}
          accessibilityRole="button"
          accessibilityLabel={unread > 0 ? `Confio Assistant y mensajes, ${unread} sin leer` : 'Confio Assistant y mensajes'}
          accessibilityHint="Mantén presionado para hablar. Arrastra para moverlo."
        >
          {iaAvailable ? (
            <AssistantMascot
              kind={profile?.mascot}
              imageUrl={profile?.customPetUrl}
              color={profile?.mascotColor}
              size={50}
              mood={talking ? 'listening' : inCall ? 'talking' : hint ? 'happy' : 'idle'}
            />
          ) : (
            <Icon name="message-circle" size={28} color="#047857" />
          )}
        </Pressable>
        {unread > 0 ? (
          <View style={[styles.badge, docked && side === 'right' && styles.badgeLeft]} pointerEvents="none">
            <Text style={styles.badgeText}>{unread > 9 ? '9+' : unread}</Text>
          </View>
        ) : null}
        {talking ? (
          <View style={styles.micDot} pointerEvents="none">
            <Icon name="mic" size={11} color="#FFFFFF" />
          </View>
        ) : null}
        {inCall ? (
          <View style={styles.callDot} pointerEvents="none">
            <Icon name="phone" size={10} color="#FFFFFF" />
          </View>
        ) : null}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  bubbleWrap: { position: 'absolute', left: 0, top: 0, width: SIZE, height: SIZE },
  button: {
    width: SIZE,
    height: SIZE,
    borderRadius: SIZE / 2,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#065F46',
    shadowOpacity: 0.22,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 8,
  },
  buttonInCall: { borderWidth: 3, borderColor: '#10B981' },
  buttonTalking: { borderWidth: 3, borderColor: '#EF4444' },
  talkRing: {
    position: 'absolute',
    left: 0,
    top: 0,
    width: SIZE,
    height: SIZE,
    borderRadius: SIZE / 2,
    backgroundColor: '#EF4444',
  },
  micDot: {
    position: 'absolute',
    bottom: -2,
    right: -2,
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: '#EF4444',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  badge: {
    position: 'absolute',
    top: -2,
    right: -2,
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    paddingHorizontal: 5,
    backgroundColor: '#EF4444',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  badgeText: { color: '#FFFFFF', fontSize: 11, fontWeight: '700' },
  // Docked on the right edge: keep the badge on the visible side.
  badgeLeft: { right: undefined, left: -2 },
  callDot: {
    position: 'absolute',
    bottom: -2,
    left: -2,
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: '#10B981',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  hint: {
    position: 'absolute',
    width: 240,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    paddingVertical: 10,
    paddingHorizontal: 12,
    shadowColor: '#111827',
    shadowOpacity: 0.12,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  hintRight: { right: 0 },
  hintLeft: { left: 0 },
  hintAbove: { bottom: SIZE + 10 },
  hintBelow: { top: SIZE + 10 },
  hintBody: { flexShrink: 1 },
  hintText: { fontSize: 14, lineHeight: 19, color: '#111827' },
});
