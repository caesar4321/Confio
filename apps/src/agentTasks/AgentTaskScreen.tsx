// One cloud-browser shopping task (server: agent_tasks/). The agent searches
// the store and fills the cart; the person signs in and presses the store's
// final button themselves, here, in the live view of that browser.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator, Alert, AppState, Keyboard, Platform, StatusBar, StyleSheet, TextInput, View,
} from 'react-native';
import { RouteProp, NavigationProp, useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { useApolloClient, useMutation } from '@apollo/client';
import WebView from 'react-native-webview';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../components/common/AppText';
import { Button } from '../components/common/Button';
import { InlineBanner } from '../components/common/InlineBanner';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { useOptionalAssistant } from '../assistant/AssistantContext';
import {
  ACTIVE, AgentTask, BACK_TO_AGENT, CANCEL_AGENT_TASK, FINISHED, GET_AGENT_TASK, LiveView, OPEN_AGENT_LIVE_VIEW,
  RESUME_AGENT_TASK, allowedInLiveView, allowedSubframe, pastesInChat, taskIdOf, timeLeft,
} from './api';
import { setSecureScreen } from './secureScreen';

type Navigation = NavigationProp<MainStackParamList>;
type Route = RouteProp<MainStackParamList, 'AgentTask'>;

const POLL_MS = 2500;
// The server does not open the screen with less than this left in the turn.
const MIN_SECONDS_TO_OPEN = 60;
// A tap whose answer never comes (a hung connection) stops holding the
// screen after this: refreshes take over. It is not reported as failed, so it
// is not sent twice.
const TAP_DEADLINE_MS = 30_000;
// An open whose answer never comes is given up on after this (mutations have no timeout of their own).
const OPEN_DEADLINE_MS = 25_000;
const WAIT_TEXT = 'Espera un momento: tu respuesta anterior todavía se está enviando.';
// The server never shows a page outside the store before the hand-over.
const LEFT_STORE = 'left_store';
// Tasks live on the person's own personal account: from any other, none is found.
export const NOT_FOUND = 'No encontré esta compra. Las compras con el asistente se hacen desde tu cuenta personal: '
  + 'cámbiate a ella si estás en otra.';

/** When the live view is on screen. Before the hand-over (sign-in, captcha)
 * only while it is the person's turn: the agent works in that browser next.
 * After it, the screen stays put until the task ends, so the page the person
 * left is the one read. */
export function showsLiveView(task: Pick<AgentTask, 'status' | 'checkoutHanded'>): boolean {
  if (FINISHED.has(task.status)) {
    return false;
  }
  if (task.status === 'needs_person') {
    return true;
  }
  return task.checkoutHanded && ACTIVE.has(task.status);
}

// The turns whose screen opened, per task, for as long as the app runs. The
// server reads the tab that open recorded: coming back to the screen late in
// the turn (when it can no longer be opened) still lets the person say done.
const shownTurns = new Map<string, string>();

/** Tests only: start from an app that never showed a screen. */
export function forgetShownTurns(): void {
  shownTurns.clear();
}

/** Each time it becomes the person's turn the screen is asked for again:
 * that call records which tab the server reads. */
function turnKey(task: AgentTask | null | undefined): string | null {
  return task && task.status === 'needs_person' ? `${task.reason}|${task.waitUntil ?? ''}` : null;
}

export const AgentTaskScreen: React.FC = () => {
  const route = useRoute<Route>();
  const taskId = taskIdOf(route.params?.taskId);
  // Another task opened on the same screen starts from nothing.
  return <TaskView key={taskId ?? 'none'} taskId={taskId} />;
};

function TaskView({ taskId }: { taskId: string | null }) {
  const navigation = useNavigation<Navigation>();
  const assistant = useOptionalAssistant();

  // The task as the server last said it. Each tap the server answered starts
  // a new epoch: a refresh that left before it is dropped, never written over
  // the newer state (it would bring back a turn that was already answered).
  const client = useApolloClient();
  const [task, setTask] = useState<AgentTask | null | undefined>(undefined);
  const [loading, setLoading] = useState(!!taskId);
  const [error, setError] = useState(false);
  const epoch = useRef(0);
  const busy = useRef(false);
  // Refreshes may overlap on a slow network: only the newest one started is applied.
  const started = useRef(0);
  const applied = useRef(0);
  // The epoch of a refresh still on its way: the timer waits for it instead of piling more up.
  const pendingEpoch = useRef<number | null>(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const load = useCallback(async () => {
    if (!taskId || !alive.current) {
      return;
    }
    const mine = epoch.current;
    const seq = ++started.current;
    pendingEpoch.current = mine;
    try {
      const result = await client.query({
        query: GET_AGENT_TASK, variables: { id: taskId }, fetchPolicy: 'no-cache',
        // Never joined to a request already on its way: that one may predate the last tap.
        context: { queryDeduplication: false },
      });
      if (epoch.current !== mine || busy.current || seq < applied.current) {
        return;
      }
      applied.current = seq;
      setTask(result.data?.agentTask ?? null);
      setError(false);
    } catch {
      if (epoch.current === mine && seq >= applied.current) {
        setError(true);
      }
    } finally {
      if (seq === started.current) {
        pendingEpoch.current = null;
      }
      setLoading(false);
    }
  }, [client, taskId]);
  useEffect(() => { load(); }, [load]);
  const active = !!task && ACTIVE.has(task.status);
  // Also while the first read has not come back: a flaky connection must not leave a dead screen.
  const polling = active || (task === undefined && !!taskId);
  useEffect(() => {
    if (!polling) {
      return undefined;
    }
    // Refreshes keep going while a tap is answered; what they bring then is not applied.
    const timer = setInterval(() => {
      if (pendingEpoch.current !== epoch.current) {
        load();
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [polling, load]);

  // Nothing of this screen in screenshots, recordings or Recents (Android).
  useFocusEffect(useCallback(() => {
    setSecureScreen(true);
    return () => setSecureScreen(false);
  }, []));

  const [openLiveView] = useMutation(OPEN_AGENT_LIVE_VIEW, { fetchPolicy: 'no-cache' });
  const [resume] = useMutation(RESUME_AGENT_TASK, { fetchPolicy: 'no-cache' });
  const [cancel] = useMutation(CANCEL_AGENT_TASK, { fetchPolicy: 'no-cache' });
  // Which tap is being answered: the spinner follows this screen, not the request (which may hang).
  const [tapping, setTapping] = useState<'done' | 'cancel' | null>(null);

  // The URL lives only in this state: never cached, logged or sent anywhere.
  const [view, setView] = useState<LiveView | null>(null);
  const [viewError, setViewError] = useState<{ text: string; code: string } | null>(null);
  const [opening, setOpening] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  // Bumped to remount the WebView: the same URL after a failed load must load again.
  const [reloads, setReloads] = useState(0);
  const loadFailed = useRef(false);
  // The server reads the tab the last successful open recorded: "Ya terminé"
  // waits for one in this turn, so what is read is what the person sees.
  const [shownTurn, setShownTurnState] = useState<string | null>(() => (taskId && shownTurns.get(taskId)) || null);
  const setShownTurn = useCallback((turn: string | null) => {
    if (taskId && turn) {
      shownTurns.set(taskId, turn);
    }
    setShownTurnState(turn);
  }, [taskId]);
  const forgetShown = useCallback(() => {
    if (taskId) {
      shownTurns.delete(taskId);
    }
    setShownTurnState(null);
  }, [taskId]);
  // Focus moves here and away on "Ya terminé": that closes the keyboard of the
  // store page (Keyboard.dismiss alone only reaches the app's own fields).
  const keyboardSink = useRef<TextInput>(null);
  const lastTurn = useRef<string | null>(null);
  // Each open is numbered: only the newest one's answer (or its deadline) counts.
  const openSeq = useRef(0);
  const handed = !!task?.checkoutHanded;
  const handedRef = useRef(handed);
  handedRef.current = handed;
  const waitUntilRef = useRef(task?.waitUntil);
  waitUntilRef.current = task?.waitUntil;
  // Whether the server would still open the screen in this turn.
  const timeToReopen = () => {
    const until = waitUntilRef.current ? Date.parse(waitUntilRef.current) : NaN;
    return Number.isNaN(until) || (until - Date.now()) / 1000 >= MIN_SECONDS_TO_OPEN;
  };

  const askForScreen = useCallback(async () => {
    if (!taskId) {
      return;
    }
    // The answer counts only for the turn it was asked in, and only for the newest open.
    const turn = lastTurn.current;
    const call = ++openSeq.current;
    const current = () => alive.current && lastTurn.current === turn && openSeq.current === call;
    setOpening(true);
    setViewError(null);
    const failed = (text: string, code: string) => {
      setViewError({ text, code });
      // Before the hand-over a screen that may not be opened again is not
      // left up: the person could type a password into whatever it shows now.
      // Only too little time left (not_open) says nothing about the page.
      if ((!handedRef.current && code !== 'not_open') || code === LEFT_STORE) {
        setView(null);
      }
      // The server may have recorded another tab (the answer was lost, or not
      // taken here): "Ya terminé" waits for an open that is known to have worked.
      // With no time left to open it again, the tab the last good open recorded
      // is still the one on screen: keep it rather than strand "Ya terminé".
      if ((code === 'network' || code === 'refused_here') && timeToReopen()) {
        forgetShown();
      }
    };
    const deadline = setTimeout(() => {
      if (current()) {
        openSeq.current += 1;  // its answer, if it ever comes, no longer counts
        failed('No pude abrir la pantalla de la tienda. Revisa tu conexión.', 'network');
        setOpening(false);
      }
    }, OPEN_DEADLINE_MS);
    try {
      const result = await openLiveView({ variables: { id: taskId } });
      if (!current()) {
        return;
      }
      const answer: LiveView | undefined = result.data?.openAgentLiveView;
      if (answer?.success && !(answer.url && answer.host && allowedInLiveView(answer.url, answer.host))) {
        failed('No pude abrir la pantalla de la tienda.', 'refused_here');
      } else if (answer?.success) {
        // The same URL keeps the page the person was on; only a new one, or one that failed to load, reloads.
        setView((previous) => (previous?.url === answer.url ? { ...previous, ...answer } : answer));
        if (loadFailed.current) {
          loadFailed.current = false;
          setReloads((n) => n + 1);
        }
        setShownTurn(turn);
      } else {
        failed(answer?.errors?.[0] || 'No pude abrir la pantalla de la tienda.', answer?.errorCode || 'error');
      }
    } catch {
      if (current()) {
        failed('No pude abrir la pantalla de la tienda. Revisa tu conexión.', 'network');
      }
    } finally {
      clearTimeout(deadline);
      if (current()) {
        setOpening(false);
      }
    }
  }, [openLiveView, taskId, setShownTurn, forgetShown]);

  // A new turn for the person: ask for the screen again.
  useEffect(() => {
    const key = turnKey(task);
    if (key && key !== lastTurn.current) {
      lastTurn.current = key;
      // A new turn names its own screen: the last turn's token is not sent for it.
      setView((previous) => (previous?.view ? { ...previous, view: null } : previous));
      askForScreen();
    } else if (!key && task) {
      lastTurn.current = null;
      setOpening(false);
      setViewError(null);
      forgetShown();
    }
  }, [task, askForScreen, forgetShown]);

  // The agent took the browser back (after a sign-in or a captcha), or the
  // task ended: the screen closes.
  const visible = !!task && showsLiveView(task);
  useEffect(() => {
    if (!visible) {
      setView(null);
      setViewError(null);
    }
  }, [visible]);

  // A second hand to the countdown.
  const [now, setNow] = useState(() => Date.now());
  const counting = task?.status === 'needs_person' && !!task.waitUntil;
  useEffect(() => {
    if (!counting) {
      return undefined;
    }
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [counting]);

  type Answer = { success?: boolean; errors?: string[]; errorCode?: string | null; task?: AgentTask | null }
    | undefined;
  const act = async (which: 'done' | 'cancel', run: () => Promise<Answer>, failure: string) => {
    if (busy.current) {
      // A second tap while the first is answered.
      setActionError(WAIT_TEXT);
      return;
    }
    busy.current = true;
    setTapping(which);
    setActionError(null);
    let expired = false;
    const deadline = setTimeout(() => {
      if (!alive.current) {
        return;
      }
      // No answer yet: stop holding the screen. Whatever the tap did, the next refresh shows it,
      // and a turn it may have passed through is asked for again (its key may be the same).
      expired = true;
      epoch.current += 1;
      busy.current = false;
      setTapping(null);
      lastTurn.current = null;
      forgetShown();
      load();
    }, TAP_DEADLINE_MS);
    try {
      const answer = await run();
      if (!alive.current) {
        return;
      }
      if (expired) {
        // Refreshes have the screen now; a refusal is still told (it cannot send anything twice).
        if (answer && !answer.success) {
          setActionError(answer.errors?.[0] || `${failure} Inténtalo de nuevo.`);
        }
        return;
      }
      epoch.current += 1;
      if (answer?.task) {
        setTask(answer.task);
      }
      setActionError((shown) => (shown === WAIT_TEXT ? null : shown));
      if (!answer?.success) {
        setActionError(answer?.errors?.[0] || `${failure} Inténtalo de nuevo.`);
      }
    } catch {
      if (expired || !alive.current) {
        return;
      }
      epoch.current += 1;
      setActionError(`${failure} Revisa tu conexión.`);
    } finally {
      clearTimeout(deadline);
      if (!expired && alive.current) {
        busy.current = false;
        setTapping(null);
        load();
      }
    }
  };

  // iOS: the app switcher's snapshot shows a cover, not the store's page.
  const [covered, setCovered] = useState(false);
  useEffect(() => {
    if (Platform.OS !== 'ios') {
      return undefined;
    }
    const subscription = AppState.addEventListener('change', (state) => setCovered(state !== 'active'));
    return () => subscription.remove();
  }, []);

  const onLoadFailed = () => {
    loadFailed.current = true;
    setViewError({ text: 'La pantalla de la tienda se cerró.', code: 'closed' });
  };
  // The person asks for the screen again: it reloads even at the same address
  // (a page that stopped answering raises no error).
  const reopen = () => {
    loadFailed.current = true;
    return askForScreen();
  };

  const onDone = () => {
    // Nothing typed reaches the page while its code is read.
    keyboardSink.current?.focus();
    keyboardSink.current?.blur();
    Keyboard.dismiss();
    // The screen on display names its tab: the server reads that one, whatever a later open recorded.
    const shownView = view?.view ?? null;
    return act('done', async () => {
      const answer = (await resume({ variables: { id: taskId, view: shownView } })).data?.resumeAgentTask;
      if (answer?.errorCode === 'view') {
        // Not recognised (a server key changed): the next try sends none, and the last recorded tab is read.
        setView((previous) => (previous ? { ...previous, view: null } : previous));
      }
      return answer;
    }, 'No pude seguir.');
  };

  const onCancel = () => {
    Alert.alert(
      'Cancelar la compra',
      handed
        ? 'Si ya confirmaste el pedido en la tienda, sigue en tus compras de la tienda.'
        : 'El asistente dejará de buscar.',
      [
        { text: 'Volver', style: 'cancel' },
        {
          text: 'Cancelar la compra',
          style: 'destructive',
          onPress: () => act('cancel',
            async () => (await cancel({ variables: { id: taskId } })).data?.cancelAgentTask, 'No pude cancelarla.'),
        },
      ],
    );
  };

  // The payment card and the pasted code both live in the chat.
  const openChat = () => assistant?.open({ channel: 'ia' });

  const header = (
    <>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
      <Header navigation={navigation as any} title="Compra con el asistente" backgroundColor={colors.heroField}
        isLight showBackButton />
    </>
  );

  if (!taskId || (!loading && !task)) {
    return (
      <View style={styles.screen}>
        {header}
        <View style={styles.center}>
          <Text style={styles.message}>{error ? 'No pude leer la compra. Revisa tu conexión.' : NOT_FOUND}</Text>
          {error ? <Button title="Reintentar" variant="secondary" onPress={load} /> : null}
        </View>
      </View>
    );
  }
  if (!task) {
    return (
      <View style={styles.screen}>
        {header}
        <View style={styles.center}><ActivityIndicator color={colors.primaryDark} /></View>
      </View>
    );
  }

  const myTurn = task.status === 'needs_person';
  const left = counting ? timeLeft(task.waitUntil, now) : null;
  const working = task.status === 'queued' || task.status === 'working' || task.status === 'awaiting_code';
  const afterHandOver = handed && !BACK_TO_AGENT.has(task.reason);
  const leftStore = viewError?.code === LEFT_STORE;
  // Under a minute left the server will not open the screen: no button that can only fail.
  const secondsLeft = task.waitUntil ? (Date.parse(task.waitUntil) - now) / 1000 : Infinity;
  const reopenable = myTurn && !leftStore && !(secondsLeft < MIN_SECONDS_TO_OPEN);
  // Asked for on purpose only while a failed try still leaves time to open it again.
  const reloadable = reopenable && !(secondsLeft < MIN_SECONDS_TO_OPEN + OPEN_DEADLINE_MS / 1000 + 5);

  return (
    <View style={styles.screen}>
      {header}
      <View style={styles.top}>
        <Text style={styles.site} numberOfLines={1}>{task.site}</Text>
        <Text style={styles.goal} numberOfLines={2}>{task.goal}</Text>
        <View style={styles.messageRow}>
          {working ? <ActivityIndicator size="small" color={colors.primaryDark} style={styles.spinner} /> : null}
          {/* The server's words, as they are: they name the right rail for the store's country. */}
          <Text style={styles.message}>{task.message}</Text>
        </View>
        {left ? <Text style={styles.countdown}>Tiempo restante: {left}</Text> : null}
        {actionError ? <InlineBanner message={actionError} onDismiss={() => setActionError(null)} /> : null}
      </View>

      {visible ? (
        <View style={styles.liveView}>
          {view?.url ? (
            <>
              {/* The page that was showing when the screen opened; the vendor's own bar below follows it. */}
              <View style={[styles.hostBar, afterHandOver && styles.hostBarProminent]}>
                <Icon name="lock" size={13} color={afterHandOver ? colors.warning.text : colors.text.secondary} />
                <Text style={[styles.hostText, afterHandOver && styles.hostTextProminent]} numberOfLines={1}>
                  Al abrir: {view.pageHost || view.site || task.site}
                </Text>
              </View>
              {/* While the server reads the code, the page holds still. */}
              <View style={styles.webView} pointerEvents={task.status === 'awaiting_code' ? 'none' : 'auto'}>
                <WebView
                  key={`${view.url}#${reloads}`}
                  source={{ uri: view.url }}
                  // Every address reaches the check below: one refused here would be handed to the phone.
                  originWhitelist={['*']}
                  onShouldStartLoadWithRequest={(request) => (request.isTopFrame === false
                    ? allowedSubframe(request.url) : allowedInLiveView(request.url, view.host))}
                  setSupportMultipleWindows={false}
                  javaScriptCanOpenWindowsAutomatically={false}
                  cacheEnabled={false}
                  incognito
                  allowsLinkPreview={false}
                  allowFileAccess={false}
                  allowsBackForwardNavigationGestures={false}
                  setBuiltInZoomControls={false}
                  keyboardDisplayRequiresUserAction={false}
                  onFileDownload={() => undefined}
                  onError={onLoadFailed}
                  onHttpError={onLoadFailed}
                  // The page's process was killed (in the background, or out of memory): a blank screen.
                  onContentProcessDidTerminate={onLoadFailed}
                  onRenderProcessGone={onLoadFailed}
                  style={styles.webView}
                />
              </View>
            </>
          ) : (
            <View style={styles.center}>
              {opening ? <ActivityIndicator color={colors.primaryDark} /> : null}
            </View>
          )}
          {viewError ? (
            <View style={styles.viewError}>
              <InlineBanner message={viewError.text} />
              {reopenable
                ? <Button title="Abrir de nuevo" variant="secondary" onPress={reopen} loading={opening} />
                : null}
            </View>
          ) : null}
        </View>
      ) : (
        <View style={styles.center}>
          {task.status === 'payment_ready' ? <Icon name="check-circle" size={40} color={colors.primaryDark} /> : null}
        </View>
      )}

      <View style={styles.actions}>
        {myTurn && afterHandOver && view?.url ? (
          <Text style={styles.hint}>
            Antes de tocar «Ya terminé», desliza hasta que se vea completo el QR o los datos de pago.
          </Text>
        ) : null}
        {myTurn && !leftStore
          ? <Button title="Ya terminé" onPress={onDone} loading={tapping === 'done'}
              disabled={opening || !(view?.view || (shownTurn !== null && shownTurn === turnKey(task)))} />
          : null}
        {reloadable && view?.url && !viewError ? (
          <Button title="La pantalla no responde" variant="ghost" onPress={reopen} loading={opening} />
        ) : null}
        {myTurn && pastesInChat(task.site, task.reason) && assistant ? (
          <Button title="Abrir el chat" variant="secondary" onPress={openChat} />
        ) : null}
        {task.status === 'payment_ready' && assistant ? <Button title="Ver el pago" onPress={openChat} /> : null}
        {active ? <Button title="Cancelar" variant="ghost" onPress={onCancel} loading={tapping === 'cancel'} /> : null}
        {!active ? (
          <Button title="Tiendas con tu sesión" variant="ghost" onPress={() => navigation.navigate('AgentStores')} />
        ) : null}
      </View>
      <TextInput ref={keyboardSink} style={styles.keyboardSink} showSoftInputOnFocus={false} caretHidden
        importantForAutofill="no" autoComplete="off" textContentType="none" autoCorrect={false}
        accessibilityElementsHidden importantForAccessibility="no-hide-descendants" />
      {covered ? <View style={styles.cover} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  top: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 8, gap: 6 },
  site: { fontSize: 13, color: colors.text.secondary },
  goal: { fontSize: 17, fontWeight: '600', color: colors.text.primary },
  messageRow: { flexDirection: 'row', alignItems: 'flex-start' },
  spinner: { marginRight: 8, marginTop: 2 },
  message: { flex: 1, fontSize: 15, lineHeight: 21, color: colors.text.primary },
  countdown: { fontSize: 13, color: colors.text.secondary, fontVariant: ['tabular-nums'] },
  liveView: { flex: 1, borderTopWidth: StyleSheet.hairlineWidth, borderColor: '#E5E7EB' },
  hostBar: {
    flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 16, paddingVertical: 6,
    backgroundColor: colors.neutralDark,
  },
  hostBarProminent: { backgroundColor: colors.warning.background, paddingVertical: 8 },
  hostText: { flex: 1, fontSize: 13, color: colors.text.secondary },
  hostTextProminent: { fontSize: 15, fontWeight: '600', color: colors.warning.text },
  webView: { flex: 1 },
  viewError: { padding: 16, gap: 8 },
  actions: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 12, gap: 8 },
  hint: { fontSize: 13, color: colors.text.secondary, textAlign: 'center' },
  cover: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.background },
  keyboardSink: { position: 'absolute', width: 1, height: 1, opacity: 0, left: -10, top: -10 },
});

export default AgentTaskScreen;
