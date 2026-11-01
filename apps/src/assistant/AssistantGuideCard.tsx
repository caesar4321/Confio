// The first-steps guide: the assistant speaks first in a card that leaves the
// screen visible, instead of the half-screen chat. Everything it says and offers
// comes from the server, so new situations need no build. Chips of an unknown
// kind are not drawn. The assistant never moves the app by itself: a tap does.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Animated, Easing, Keyboard, Pressable, StyleSheet, TextInput, View, useWindowDimensions } from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { useAssistant } from './AssistantContext';
import AssistantMascot from './AssistantMascot';
import {
  ASK_ASSISTANT_IN_GUIDE,
  type AssistantAction,
  GET_ASSISTANT_GUIDE,
  GET_ASSISTANT_THREAD,
  RECORD_ASSISTANT_GUIDE_EVENT,
  type AssistantGuide,
  type AssistantGuideChip,
  type AssistantGuideTrailStop,
} from './api';
import { openDestination, resolveNavigate } from './destinations';
import { measureGuideAnchor, setGuidePointer, setGuideTapListener, useGuidePointer } from './guidePointer';
import { TAB_ROUTES } from './suggestions';
import GuideOpening from './GuideOpening';

const HOME_ROUTE = 'Home';
const OPEN_DELAY_MS = 1200;
const NAVIGATION_SETTLE_MS = 700;
const POINTER_CHECK_MS = 2500;
const LAST_TAP = 'asset_confirm';
// A button in the lower part of the screen: the strip moves above it.
const LOWER_SCREEN_RATIO = 0.6;
const CHIP_KINDS = new Set(['navigate', 'probe', 'dismiss']);
const TAB_BAR_HEIGHT = 64;
// Pagar rises above the tab bar: the bubble keeps clear of it.
const PAGAR_CLEARANCE = 14;
const GAP = 8;
const PET_SIZE = 46;
const COLLAPSE_MS = 520;
const NEXT_STEP_LIMIT_MS = 8000;

// A stuck network must never leave the waiting bubble on screen for good.
function withinLimit<T>(work: Promise<T>): Promise<T | null> {
  return Promise.race([
    work,
    new Promise<null>((resolve) => setTimeout(() => resolve(null), NEXT_STEP_LIMIT_MS)),
  ]);
}

type ReplyChip = { key: string; label: string; ticker?: string };
type Trail = { step: string; detail: string; stops: AssistantGuideTrailStop[]; started: boolean };

export default function AssistantGuideCard() {
  const insets = useSafeAreaInsets();
  const { height } = useWindowDimensions();
  const { route, isOpen, open, inCall, available, aiEnabled, setGuideShown } = useAssistant();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { activeAccount } = useAccount();
  const contextKey = activeAccount?.id || 'no-account';
  const pointer = useGuidePointer();
  const [guide, setGuide] = useState<AssistantGuide | null>(null);
  const [reply, setReply] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [replyChips, setReplyChips] = useState<ReplyChip[]>([]);
  const [thinking, setThinking] = useState(false);
  const [keyboard, setKeyboard] = useState(0);
  // The full-screen first meeting, kept until the pet has landed.
  const [opening, setOpening] = useState<AssistantGuide | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [pending, setPending] = useState(false);
  const [typing, setTyping] = useState(false);
  const collapse = useRef(new Animated.Value(0)).current;
  // One card per session: what was already shown stays closed until next time.
  const seen = useRef(new Set<string>());
  const pointerRoute = useRef<string | undefined>(undefined);
  const pointerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pointerLogged = useRef(false);
  const trail = useRef<Trail | null>(null);
  const flowRef = useRef(0);
  const [stripOnTop, setStripOnTop] = useState(false);
  const routeRef = useRef(route);
  routeRef.current = route;
  const guideRef = useRef(guide);
  guideRef.current = guide;

  const personal = activeAccount?.type?.toLowerCase() !== 'business';
  const ready = isAuthenticated && !authLoading && available && aiEnabled && personal;
  const { data, refetch } = useQuery(GET_ASSISTANT_GUIDE, {
    variables: { screen: HOME_ROUTE, contextKey },
    skip: !ready || route !== HOME_ROUTE,
    fetchPolicy: 'network-only',
    errorPolicy: 'ignore',
  });
  // Only for the person's own pet and its color.
  const { data: threadData } = useQuery(GET_ASSISTANT_THREAD, {
    variables: { limit: 1, contextKey },
    skip: !ready,
    fetchPolicy: 'cache-first',
    errorPolicy: 'ignore',
  });
  const profile = threadData?.assistantThread?.profile;
  const [recordEvent] = useMutation(RECORD_ASSISTANT_GUIDE_EVENT, { errorPolicy: 'ignore' });
  const [ask] = useMutation(ASK_ASSISTANT_IN_GUIDE);

  const record = useCallback((step: string, event: string, answer?: string, detail?: string) => (
    recordEvent({ variables: { step, event, answer, detail } }).catch(() => undefined)
  ), [recordEvent]);

  useEffect(() => {
    const next: AssistantGuide | null | undefined = data?.assistantGuide;
    if (!next || seen.current.has(next.step) || guide || opening || pending || route !== HOME_ROUTE || isOpen || inCall) {
      return undefined;
    }
    const timer = setTimeout(() => {
      seen.current.add(next.step);
      setReply(null);
      setReplyChips([]);
      setTyping(false);
      if (next.presentation === 'full') {
        collapse.setValue(0);
        setOpening(next);
      } else {
        setGuide(next);
      }
      record(next.step, 'shown');
    }, OPEN_DELAY_MS);
    return () => clearTimeout(timer);
  }, [data, guide, opening, pending, route, isOpen, inCall, record, collapse]);

  const clear = useCallback(() => {
    flowRef.current += 1;
    if (pointerTimer.current) {
      clearTimeout(pointerTimer.current);
      pointerTimer.current = null;
    }
    setGuide(null);
    setOpening(null);
    setLeaving(false);
    setPending(false);
    setTyping(false);
    setReply(null);
    setReplyChips([]);
    trail.current = null;
    setGuidePointer(null);
  }, []);

  // A guide belongs to one personal account: never carried across a switch.
  useEffect(() => clear, [contextKey, clear]);
  useEffect(() => {
    if (!personal) {
      clear();
    }
  }, [personal, clear]);

  // The card lives on Inicio: it must never sit on a payment screen.
  useEffect(() => {
    if (route !== HOME_ROUTE) {
      setGuide(null);
      setOpening(null);
      setPending(false);
    }
  }, [route]);

  useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', (e) => setKeyboard(e.endCoordinates.height));
    const hide = Keyboard.addListener('keyboardDidHide', () => setKeyboard(0));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  // A walk: each screen brings its own sentence and button. Going back works;
  // leaving the walk's screens ends it.
  useEffect(() => {
    const walk = trail.current;
    if (!walk) {
      return;
    }
    const stop = walk.stops.find((s) => s.route === route);
    if (stop) {
      walk.started = true;
      setGuidePointer({ id: stop.pointer, text: stop.text, step: walk.step, detail: walk.detail });
    } else if (walk.started) {
      trail.current = null;
      setGuidePointer(null);
    }
  }, [route]);

  // The person left the screen we pointed at: the lesson is over.
  useEffect(() => {
    if (trail.current) {
      return;
    }
    if (!pointer) {
      pointerRoute.current = undefined;
    } else if (!pointerRoute.current) {
      pointerRoute.current = route;
    } else if (route !== pointerRoute.current) {
      setGuidePointer(null);
    }
  }, [pointer, route]);

  // The funnel: did the pencil appear, and did the person tap what it circled?
  useEffect(() => {
    setGuideTapListener((tapped) => {
      const detail = tapped.detail ? `${tapped.detail}:${tapped.id}` : tapped.id;
      // A quick tap beats the timer below: the pencil was still there to tap.
      if (!pointerLogged.current) {
        pointerLogged.current = true;
        record(tapped.step, 'pointer_shown', undefined, detail);
      }
      record(tapped.step, 'pointer_tapped', undefined, detail);
      if (tapped.id === LAST_TAP) {
        trail.current = null;
      }
    });
    return () => setGuideTapListener(null);
  }, [record]);
  const pointedId = pointer?.id;
  const pointedStep = pointer?.step;
  const pointedDetail = pointer?.detail;
  useEffect(() => {
    setStripOnTop(false);
    if (!pointedId || !pointedStep) {
      return undefined;
    }
    pointerLogged.current = false;
    const detail = pointedDetail ? `${pointedDetail}:${pointedId}` : pointedId;
    const place = setTimeout(() => {
      measureGuideAnchor(pointedId).then((rect) => setStripOnTop(!!rect && rect.y > height * LOWER_SCREEN_RATIO));
    }, NAVIGATION_SETTLE_MS);
    const timer = setTimeout(() => {
      pointerLogged.current = true;
      measureGuideAnchor(pointedId).then((rect) => (
        record(pointedStep, rect ? 'pointer_shown' : 'pointer_missing', undefined, detail)
      ));
    }, POINTER_CHECK_MS);
    return () => {
      clearTimeout(place);
      clearTimeout(timer);
    };
  }, [pointedId, pointedStep, pointedDetail, height, record]);

  const shown = !!guide || !!pointer || !!opening || pending;
  useEffect(() => setGuideShown(shown), [shown, setGuideShown]);

  const close = useCallback(() => {
    const current = opening ?? guide;
    if (current) {
      record(current.step, 'dismissed');
    } else if (pointer) {
      record(pointer.step, 'pointer_closed');
    }
    clear();
  }, [guide, opening, pointer, record, clear]);

  // The pet shrinks into its corner while Inicio appears behind it.
  const land = useCallback((done?: () => void) => {
    setLeaving(true);
    Animated.timing(collapse, {
      toValue: 1,
      duration: COLLAPSE_MS,
      easing: Easing.inOut(Easing.cubic),
      useNativeDriver: true,
    }).start(() => {
      setOpening(null);
      setLeaving(false);
      done?.();
    });
  }, [collapse]);

  const press = useCallback(async (chip: AssistantGuideChip) => {
    // While the pet lands the next step's bubble is already live: it comes first.
    const current = guide ?? opening;
    if (!current) {
      return;
    }
    if (chip.kind === 'dismiss') {
      if (!guide && opening) {
        record(current.step, 'dismissed');
        land();
      } else {
        close();
      }
      return;
    }
    if (chip.kind === 'probe') {
      const flow = flowRef.current;
      setPending(true);
      setGuide(null);
      if (opening) {
        land();
      }
      const next = await withinLimit((async () => {
        await record(current.step, 'accepted', chip.answer);
        const result = await refetch().catch(() => null);
        return result?.data?.assistantGuide as AssistantGuide | null | undefined;
      })());
      if (flow !== flowRef.current) {
        return;  // cleared or another account meanwhile
      }
      setPending(false);
      if (next && !seen.current.has(next.step) && routeRef.current === HOME_ROUTE) {
        seen.current.add(next.step);
        setGuide(next);
        record(next.step, 'shown');
      }
      return;
    }
    if (!guide) {
      return;
    }
    record(guide.step, 'accepted', undefined, chip.answer);
    setGuide(null);
    if (!openDestination(chip.destination, { isBusiness: false })) {
      return;
    }
    record(guide.step, 'opened', undefined, chip.answer);
    if (chip.trail.length) {
      trail.current = { step: guide.step, detail: chip.answer, stops: chip.trail, started: false };
      pointerTimer.current = setTimeout(() => {
        pointerTimer.current = null;
        if (trail.current) {
          const stop = trail.current.stops.find((s) => s.route === routeRef.current);
          if (stop) {
            trail.current.started = true;
            setGuidePointer({ id: stop.pointer, text: stop.text, step: guide.step, detail: chip.answer });
          }
        }
      }, NAVIGATION_SETTLE_MS);
      return;
    }
    if (chip.pointer) {
      const text = guide.pointerText;
      const { step } = guide;
      pointerTimer.current = setTimeout(() => {
        pointerTimer.current = null;
        // Back on Inicio already: there is nothing to point at.
        if (routeRef.current !== HOME_ROUTE) {
          setGuidePointer({ id: chip.pointer, text, step });
        }
      }, NAVIGATION_SETTLE_MS);
    }
  }, [guide, opening, close, land, record, refetch]);

  const send = useCallback(async () => {
    const body = draft.trim();
    if (!body || !guide || thinking) {
      return;
    }
    setDraft('');
    setThinking(true);
    try {
      const { data: answer } = await ask({
        variables: { body, screen: route ?? null, guideStep: guide.step },
        refetchQueries: [GET_ASSISTANT_THREAD],
      });
      if (guideRef.current?.step !== guide.step) {
        return;  // closed or replaced while waiting: the answer stays in the chat
      }
      const message = answer?.askAssistant?.reply;
      const text = message?.body;
      if (typeof text === 'string' && text.trim()) {
        record(guide.step, 'replied');
        setReply(text.trim());
        setReplyChips(((message.actions ?? []) as AssistantAction[])
          .filter((a) => a.type === 'navigate')
          .map(resolveNavigate)
          .filter((t): t is ReplyChip => t !== null));
        // Answered in their own words: the opening question is done.
        if (guide.step === 'opening') {
          await record(guide.step, 'dismissed');
          const next = (await refetch()).data?.assistantGuide as AssistantGuide | null | undefined;
          // Closed, moved or switched account meanwhile: the next visit shows it.
          if (next && guideRef.current?.step === guide.step && routeRef.current === HOME_ROUTE) {
            seen.current.add(next.step);
            setGuide(next);
            record(next.step, 'shown');
          }
        }
      } else {
        // The team owns this thread now: the chat shows what happens next.
        setGuide(null);
        open();
      }
    } catch {
      if (guideRef.current?.step === guide.step) {
        setReply('No pude responder ahora. Inténtalo de nuevo.');
      }
    } finally {
      setThinking(false);
    }
  }, [draft, guide, thinking, ask, route, open, record, refetch]);

  const pressReplyChip = useCallback((chip: ReplyChip) => {
    setGuide(null);
    setReplyChips([]);
    openDestination(chip.key, { isBusiness: false, ticker: chip.ticker });
  }, []);

  if (!shown || isOpen || !personal) {
    return null;
  }
  const onTab = !!route && TAB_ROUTES.has(route);
  const bottom = keyboard
    ? keyboard + GAP
    : insets.bottom + GAP + (onTab ? TAB_BAR_HEIGHT + PAGAR_CLEARANCE : 0);
  const pet = (size: number, hidden = false) => (
    <View style={hidden ? styles.hidden : undefined}>
      <AssistantMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor}
        size={size} mood="talking" />
    </View>
  );

  if (!guide && !opening && !pending) {
    return (
      <View style={[styles.strip, stripOnTop ? { top: insets.top + GAP } : { bottom }]}>
        {pet(28)}
        <Text style={styles.stripText}>{pointer?.text}</Text>
        <Pressable onPress={close} hitSlop={10} accessibilityRole="button" accessibilityLabel="Cerrar">
          <Icon name="x" size={18} color={colors.text.secondary} />
        </Pressable>
      </View>
    );
  }

  const chips = (guide?.chips ?? opening?.chips ?? []).filter((c) => CHIP_KINDS.has(c.kind));
  return (
    <>
      {guide || pending ? (
        <View style={[styles.bubbleRow, { bottom }]}>
          {pet(PET_SIZE, !!opening)}
          <View style={styles.speech}>
            {guide ? (
              <>
                <View style={styles.header}>
                  <Text style={styles.text}>{reply ?? guide.text}</Text>
                  <Pressable onPress={close} hitSlop={10} accessibilityRole="button" accessibilityLabel="Cerrar">
                    <Icon name="x" size={16} color={colors.text.secondary} />
                  </Pressable>
                </View>
                <View style={styles.chips}>
                  {replyChips.map((chip) => (
                    <Pressable key={chip.key} onPress={() => pressReplyChip(chip)} accessibilityRole="button"
                      style={[styles.chip, styles.chipPrimary]}>
                      <Text style={styles.chipText}>{chip.label}</Text>
                    </Pressable>
                  ))}
                  {chips.map((chip) => (
                    <Pressable
                      key={chip.label}
                      onPress={() => press(chip)}
                      accessibilityRole="button"
                      style={[styles.chip, chip.kind === 'navigate' && styles.chipPrimary]}
                    >
                      <Text style={styles.chipText}>{chip.label}</Text>
                    </Pressable>
                  ))}
                  {!typing ? (
                    <Pressable onPress={() => setTyping(true)} hitSlop={8} accessibilityRole="button"
                      accessibilityLabel="Escribir" style={styles.typeButton}>
                      <Icon name="message-circle" size={18} color={colors.text.secondary} />
                    </Pressable>
                  ) : null}
                </View>
                {typing ? (
                  <View style={styles.inputRow}>
                    <TextInput
                      autoFocus
                      value={draft}
                      onChangeText={setDraft}
                      onSubmitEditing={send}
                      placeholder="Escribe o pregúntame"
                      placeholderTextColor={colors.text.light}
                      returnKeyType="send"
                      maxLength={500}
                      style={styles.input}
                    />
                    {thinking ? <ActivityIndicator size="small" color={colors.primaryDark} /> : (
                      <Pressable onPress={() => open()} hitSlop={10} accessibilityRole="button" accessibilityLabel="Abrir el chat">
                        <Icon name="chevron-up" size={20} color={colors.text.secondary} />
                      </Pressable>
                    )}
                  </View>
                ) : null}
              </>
            ) : <ActivityIndicator size="small" color={colors.primaryDark} />}
          </View>
        </View>
      ) : null}
      {opening ? (
        <GuideOpening
          guide={opening}
          profile={profile}
          collapse={collapse}
          leaving={leaving}
          chips={chips}
          onChip={press}
          landing={{ x: GAP + PET_SIZE / 2, y: height - bottom - PET_SIZE / 2, size: PET_SIZE }}
        />
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  hidden: { opacity: 0 },
  strip: {
    position: 'absolute',
    left: 8,
    right: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: colors.white,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  stripText: { flex: 1, fontSize: 14, color: colors.text.primary },
  bubbleRow: { position: 'absolute', left: GAP, right: GAP, flexDirection: 'row', alignItems: 'flex-end', gap: 6 },
  speech: {
    flex: 1,
    padding: 12,
    backgroundColor: colors.white,
    borderRadius: 16,
    borderBottomLeftRadius: 4,
    borderWidth: 1,
    borderColor: colors.border,
  },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  text: { flex: 1, fontSize: 15, lineHeight: 21, color: colors.text.primary },
  chips: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6, marginTop: 10 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipPrimary: { backgroundColor: colors.flowIn.chip, borderColor: colors.primaryDark },
  chipText: { fontSize: 13, color: colors.text.primary },
  typeButton: { padding: 4 },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 10,
    paddingHorizontal: 12,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
  },
  input: { flex: 1, padding: 0, fontSize: 14, color: colors.text.primary },
});
