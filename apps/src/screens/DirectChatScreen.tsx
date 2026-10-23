import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useApolloClient, useMutation } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../components/common/AppText';
import { BylineAvatar } from '../components/PostByline';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import {
  ACCEPT_DIRECT_REQUEST,
  BLOCK_COMMUNITY_MEMBER,
  DELETE_DIRECT_CONVERSATION,
  MARK_DIRECT_CONVERSATION_READ,
  REPORT_DIRECT_MESSAGE,
  SEND_DIRECT_MESSAGE,
} from '../apollo/mutations';
import { GET_DIRECT_CONVERSATION, GET_DIRECT_CONVERSATION_WITH, GET_DIRECT_MESSAGES } from '../apollo/queries';
import { notifyMemberBlocked } from '../services/communityEvents';
import { MainStackParamList } from '../types/navigation';
import {
  DirectConversation,
  DirectMessage,
  chatTime,
  mergeMessages,
  newClientKey,
} from '../utils/directMessages';
import { formatUsd } from '../utils/portfolioFormat';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'DirectChat'>['route'];

const MAX_CHARS = 1000;
const PAGE = 30;
// While open: new messages, and the review state of your own.
const POLL_MS = 3000;

/**
 * One conversation (Mensajes). Every message is reviewed before the other
 * person sees it: yours show "Revisando…" until then, and the reason if it
 * wasn't sent. Opened from a profile (userId, maybe no conversation yet),
 * the inbox or a push (conversationId).
 */
export const DirectChatScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const client = useApolloClient();
  const [conversationId, setConversationId] = useState<string | null>(route.params.conversationId ?? null);
  const [conversation, setConversation] = useState<DirectConversation | null>(null);
  const [messages, setMessages] = useState<DirectMessage[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const [sendMessage] = useMutation(SEND_DIRECT_MESSAGE);
  const [accept, { loading: accepting }] = useMutation(ACCEPT_DIRECT_REQUEST);
  const [remove] = useMutation(DELETE_DIRECT_CONVERSATION);
  const [markRead] = useMutation(MARK_DIRECT_CONVERSATION_READ);
  const [report] = useMutation(REPORT_DIRECT_MESSAGE);
  const [blockMember] = useMutation(BLOCK_COMMUNITY_MEMBER);

  const otherName = conversation?.other.username ?? route.params.username ?? 'Mensaje';
  const otherId = conversation?.other.userId ?? route.params.userId ?? null;

  const applyCleared = (next: DirectConversation | null) => {
    const cleared = next?.clearedAt ?? null;
    if (clearedSeen.current !== undefined && cleared !== clearedSeen.current) {
      epoch.current += 1;
      setMessages([]);
      cursor.current = null;
      historyBefore.current = null;
    }
    clearedSeen.current = cleared;
  };

  const loadConversation = useCallback(async (): Promise<{ id: string | null; unread: number }> => {
    try {
      if (conversationId) {
        const { data } = await client.query({
          query: GET_DIRECT_CONVERSATION,
          variables: { conversationId },
          fetchPolicy: 'network-only',
        });
        const next = data?.directConversation ?? null;
        if (!mounted.current) return { id: null, unread: 0 };
        if (!next) setUnavailable(true);
        applyCleared(next);
        setConversation(next);
        return { id: next?.id ?? null, unread: next?.unreadCount ?? 0 };
      }
      if (route.params.userId) {
        const { data } = await client.query({
          query: GET_DIRECT_CONVERSATION_WITH,
          variables: { userId: route.params.userId },
          fetchPolicy: 'network-only',
        });
        const next = data?.directConversationWith ?? null;
        if (!mounted.current) return { id: null, unread: 0 };
        applyCleared(next);
        setConversation(next);
        if (next?.id) setConversationId(next.id);
        return { id: next?.id ?? null, unread: next?.unreadCount ?? 0 };
      }
    } catch {
      // The poll tries again.
    }
    return { id: null, unread: 0 };
  }, [client, conversationId, route.params.userId]);

  // The first read takes the latest page; every poll after it asks for what
  // changed since the previous one, so a late approval is never skipped.
  const cursor = useRef<string | null>(null);
  const loadLatest = useCallback(async (id: string | null): Promise<{ messages: DirectMessage[]; at: string | null }> => {
    if (!id) return { messages: [], at: null };
    const started = epoch.current;
    try {
      const { data } = await client.query({
        query: GET_DIRECT_MESSAGES,
        variables: cursor.current
          ? { conversationId: id, changedSince: cursor.current }
          : { conversationId: id, limit: PAGE },
        fetchPolicy: 'network-only',
        context: { queryDeduplication: false },
      });
      const page = data?.directMessages;
      if (!mounted.current || !page || epoch.current !== started) return { messages: [], at: null };
      if (cursor.current && !page.serverTime) {
        // Too much changed while away: start over from the latest page, with
        // nothing old kept (it could hide gaps and stale review states).
        epoch.current += 1;
        cursor.current = null;
        historyBefore.current = null;
        setMessages([]);
        return { messages: [], at: null };
      }
      if (!cursor.current) {
        setHasMore(Boolean(page.hasMore));
        const oldest = page.messages[page.messages.length - 1];
        if (oldest) historyBefore.current = oldest.id;
      }
      cursor.current = page.serverTime;
      setMessages((current) => mergeMessages(current, page.messages));
      return { messages: page.messages as DirectMessage[], at: page.serverTime ?? null };
    } catch {
      // Keep what's shown; the next poll retries.
      return { messages: [], at: null };
    }
  }, [client]);

  // The chat's deletion mark as last seen: when it moves (deleted from
  // another screen), everything shown before it goes.
  const clearedSeen = useRef<string | null | undefined>(undefined);
  // Bumped on every reset: an answer to a request made before it is dropped.
  const epoch = useRef(0);
  // Read receipts only while this chat is on screen.
  const focused = useRef(false);
  // Paging back starts below the oldest message a page (not a poll) brought.
  const historyBefore = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    const found = await loadConversation();
    const id = found.id ?? conversationId;
    const latest = await loadLatest(id);
    if (mounted.current) setLoading(false);
    // The server says what's still unread: a receipt goes out until it's 0,
    // up to the page actually shown (a failed one simply goes again).
    if (id && found.unread > 0 && latest.at && focused.current) {
      markRead({ variables: { conversationId: id, upTo: latest.at } }).catch(() => {});
    }
  }, [loadConversation, loadLatest, conversationId, markRead]);

  useFocusEffect(
    useCallback(() => {
      focused.current = true;
      void refresh();
      const timer = setInterval(() => { void refresh(); }, POLL_MS);
      return () => {
        focused.current = false;
        clearInterval(timer);
      };
    }, [refresh]),
  );

  const loadOlder = async () => {
    const before = historyBefore.current;
    if (!conversationId || !hasMore || loadingOlder || !before) return;
    const started = epoch.current;
    setLoadingOlder(true);
    try {
      const { data } = await client.query({
        query: GET_DIRECT_MESSAGES,
        variables: { conversationId, beforeId: before, limit: PAGE },
        fetchPolicy: 'network-only',
      });
      const page = data?.directMessages;
      if (!mounted.current || !page || epoch.current !== started) return;
      const oldest = page.messages[page.messages.length - 1];
      if (oldest) historyBefore.current = oldest.id;
      setMessages((current) => mergeMessages(current, page.messages));
      setHasMore(Boolean(page.hasMore));
    } catch {
      // Reaching the top again retries.
    } finally {
      if (mounted.current) setLoadingOlder(false);
    }
  };

  const send = async (body: string, clientKey: string) => {
    const local: DirectMessage = {
      id: `local-${clientKey}`,
      body,
      kind: 'text',
      fromMe: true,
      status: 'sending',
      clientKey,
      createdAt: new Date().toISOString(),
    };
    setMessages((current) => mergeMessages(current.filter((m) => m.id !== local.id), [local]));
    setSending(true);
    const started = epoch.current;
    try {
      const { data } = await sendMessage({
        variables: {
          body,
          clientKey,
          conversationId: conversationId ?? undefined,
          recipientUserId: conversationId ? undefined : route.params.userId,
        },
      });
      const result = data?.sendDirectMessage;
      if (!mounted.current) return;
      if (!result?.success || !result.message) {
        setMessages((current) => current.filter((m) => m.id !== local.id));
        setDraft((value) => value || body);
        Alert.alert('No pudimos enviar tu mensaje', result?.error || 'Inténtalo de nuevo.');
        return;
      }
      if (!conversationId && result.conversationId) setConversationId(String(result.conversationId));
      // Deleted meanwhile (here or on another device): the answer stays out.
      if (epoch.current !== started) return;
      setMessages((current) => mergeMessages(current, [result.message]));
    } catch {
      if (!mounted.current) return;
      // Kept with its key: "Reintentar" resends the same message, never a twin.
      setMessages((current) => current.map((m) => (m.id === local.id ? { ...m, status: 'unsent' } : m)));
    } finally {
      if (mounted.current) setSending(false);
    }
  };

  const submit = () => {
    const body = draft.trim();
    if (!body || sending) return;
    setDraft('');
    void send(body, newClientKey());
  };

  const confirmMore = () => {
    if (!otherId) return;
    Alert.alert(otherName, undefined, [
      {
        text: 'Eliminar conversación',
        style: 'destructive',
        onPress: () => { void deleteAndLeave(); },
      },
      {
        text: `Bloquear a ${otherName}`,
        style: 'destructive',
        onPress: async () => {
          try {
            const { data } = await blockMember({ variables: { userId: otherId } });
            if (!data?.blockCommunityMember?.success) {
              Alert.alert('No pudimos bloquear', data?.blockCommunityMember?.error || 'Inténtalo de nuevo.');
              return;
            }
            notifyMemberBlocked();
            if (mounted.current && navigation.canGoBack()) navigation.goBack();
          } catch {
            Alert.alert('No pudimos bloquear', 'Revisa tu conexión e inténtalo de nuevo.');
          }
        },
      },
      { text: 'Cancelar', style: 'cancel' },
    ]);
  };

  const reportMessage = (message: DirectMessage) => {
    if (message.fromMe || message.status !== 'approved') return;
    Alert.alert('¿Reportar este mensaje?', 'Lo revisaremos. Si varias personas reportan a alguien, sus mensajes se pausan.', [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Reportar',
        style: 'destructive',
        onPress: async () => {
          try {
            const { data } = await report({ variables: { messageId: message.id } });
            Alert.alert(data?.reportDirectMessage?.success ? 'Gracias por avisarnos' : 'No pudimos reportar');
          } catch {
            Alert.alert('No pudimos reportar', 'Revisa tu conexión e inténtalo de nuevo.');
          }
        },
      },
    ]);
  };

  const acceptRequest = async () => {
    if (!conversationId) return;
    try {
      await accept({ variables: { conversationId } });
      void refresh();
    } catch {
      Alert.alert('No pudimos aceptar', 'Revisa tu conexión e inténtalo de nuevo.');
    }
  };

  /** Leaves only once the server confirms: a request still deliverable is never shown as deleted. */
  const deleteAndLeave = async () => {
    if (conversationId) {
      try {
        const { data } = await remove({ variables: { conversationId } });
        if (!data?.deleteDirectConversation?.success) throw new Error('not deleted');
      } catch {
        Alert.alert('No pudimos eliminar la conversación', 'Revisa tu conexión e inténtalo de nuevo.');
        return;
      }
    }
    if (mounted.current && navigation.canGoBack()) navigation.goBack();
  };

  const declineRequest = () => { void deleteAndLeave(); };

  const blockReason = conversation?.sendBlock ? conversation.sendBlockMessage : null;
  const incoming = Boolean(conversation?.isIncomingRequest);

  const renderItem = ({ item }: { item: DirectMessage }) => {
    const mine = item.fromMe;
    const tip = item.kind === 'tip';
    const tipLabel = tip ? formatUsd(item.tipAmount) : null;
    return (
      <Pressable
        onLongPress={() => reportMessage(item)}
        style={[styles.row, mine ? styles.rowMine : styles.rowTheirs]}
        accessibilityHint={!mine ? 'Mantén presionado para reportar' : undefined}
      >
        <View
          style={[
            styles.bubble,
            mine ? styles.bubbleMine : styles.bubbleTheirs,
            tip && styles.bubbleTip,
            (item.status === 'pending' || item.status === 'sending') && styles.bubblePending,
          ]}
        >
          {tip ? (
            <Text style={[styles.tipTitle, mine && styles.textMine]}>
              {`🎁 ${mine ? 'Enviaste' : 'Te envió'} una propina${tipLabel ? ` de ${tipLabel}` : ''}`}
            </Text>
          ) : null}
          {item.body ? <Text style={[styles.body, mine && !tip && styles.textMine]}>{item.body}</Text> : null}
        </View>
        <Text style={[styles.meta, mine && styles.metaMine]}>
          {item.status === 'sending' || item.status === 'pending'
            ? 'Revisando…'
            : item.status === 'rejected' || item.status === 'failed'
              ? `No enviado. ${item.reason || ''}`.trim()
              : item.status === 'unsent'
                ? 'Sin conexión.'
                : chatTime(item.createdAt)}
        </Text>
        {item.status === 'unsent' || item.status === 'failed' ? (
          <Pressable
            onPress={() => {
              setMessages((current) => current.filter((m) => m.id !== item.id));
              void send(item.body, item.status === 'unsent' && item.clientKey ? item.clientKey : newClientKey());
            }}
            hitSlop={6}
            accessibilityRole="button"
          >
            <Text style={styles.retry}>Reintentar</Text>
          </Pressable>
        ) : null}
      </Pressable>
    );
  };

  return (
    <View style={styles.container}>
      <Header
        title={otherName}
        navigation={navigation as any}
        onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background}
        isLight={false}
        rightAccessory={otherId ? (
          <Pressable onPress={confirmMore} hitSlop={10} accessibilityRole="button" accessibilityLabel="Más opciones">
            <Icon name="more-horizontal" size={22} color={colors.dark} />
          </Pressable>
        ) : undefined}
      />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        {unavailable ? (
          <View style={styles.center}>
            <Text style={styles.empty}>Esta conversación ya no está disponible.</Text>
          </View>
        ) : (
          <FlatList
            data={messages}
            inverted
            keyExtractor={(m) => m.id}
            renderItem={renderItem}
            contentContainerStyle={styles.list}
            onEndReached={() => { void loadOlder(); }}
            onEndReachedThreshold={0.3}
            initialNumToRender={20}
            maxToRenderPerBatch={20}
            windowSize={15}
            ListFooterComponent={
              loadingOlder ? <ActivityIndicator style={styles.older} size="small" color={colors.primary} /> : (
                otherId ? (
                  <Pressable
                    onPress={() => navigation.navigate('CommunityMemberProfile', { userId: otherId })}
                    style={styles.intro}
                    accessibilityRole="button"
                  >
                    <BylineAvatar name={otherName} avatarUrl={conversation?.other.avatarUrl} size={56} />
                    <Text style={styles.introName}>{otherName}</Text>
                    <Text style={styles.introNote}>
                      Revisamos cada mensaje antes de entregarlo. No compartas teléfonos, enlaces ni otras apps.
                    </Text>
                  </Pressable>
                ) : null
              )
            }
            ListEmptyComponent={loading ? <ActivityIndicator style={styles.older} color={colors.primary} /> : null}
          />
        )}
        {incoming ? (
          <View style={styles.request}>
            <Text style={styles.requestText}>{`${otherName} quiere escribirte. Si respondes, aceptas la conversación.`}</Text>
            <View style={styles.requestActions}>
              <Pressable onPress={() => { void declineRequest(); }} style={[styles.requestButton, styles.decline]}
                accessibilityRole="button">
                <Text style={styles.declineText}>Eliminar</Text>
              </Pressable>
              <Pressable onPress={() => { void acceptRequest(); }} disabled={accepting}
                style={[styles.requestButton, styles.acceptButton]} accessibilityRole="button">
                <Text style={styles.acceptText}>Aceptar</Text>
              </Pressable>
            </View>
          </View>
        ) : null}
        {blockReason && !unavailable ? (
          <Text style={styles.blocked}>{blockReason}</Text>
        ) : !unavailable ? (
          <View style={styles.composer}>
            <TextInput
              value={draft}
              onChangeText={(text) => setDraft(text.slice(0, MAX_CHARS))}
              placeholder="Escribe un mensaje"
              placeholderTextColor={colors.muted}
              style={styles.input}
              multiline
              maxLength={MAX_CHARS}
              accessibilityLabel="Mensaje"
            />
            <Pressable
              onPress={submit}
              disabled={!draft.trim() || sending}
              style={[styles.sendButton, (!draft.trim() || sending) && styles.sendDisabled]}
              accessibilityRole="button"
              accessibilityLabel="Enviar"
            >
              <Icon name="send" size={18} color={colors.white} />
            </Pressable>
          </View>
        ) : null}
      </KeyboardAvoidingView>
    </View>
  );
};

export default DirectChatScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  flex: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  empty: { fontSize: 15, color: colors.textSecondary, textAlign: 'center' },
  list: { paddingHorizontal: 12, paddingVertical: 12 },
  older: { marginVertical: 16 },
  intro: { alignItems: 'center', paddingVertical: 20, paddingHorizontal: 24 },
  introName: { marginTop: 8, fontSize: 17, fontWeight: '700', color: colors.dark },
  introNote: { marginTop: 6, fontSize: 13, color: colors.textSecondary, textAlign: 'center' },
  row: { marginVertical: 3, maxWidth: '82%' },
  rowMine: { alignSelf: 'flex-end', alignItems: 'flex-end' },
  rowTheirs: { alignSelf: 'flex-start', alignItems: 'flex-start' },
  bubble: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: 18 },
  bubbleMine: { backgroundColor: colors.dark, borderBottomRightRadius: 6 },
  bubbleTheirs: { backgroundColor: colors.background, borderBottomLeftRadius: 6, borderWidth: 1, borderColor: colors.border },
  bubbleTip: { backgroundColor: colors.primaryLight, borderWidth: 0 },
  bubblePending: { opacity: 0.6 },
  body: { fontSize: 15, lineHeight: 21, color: colors.dark },
  textMine: { color: colors.white },
  tipTitle: { fontSize: 14, fontWeight: '700', color: colors.primaryDeep, marginBottom: 2 },
  meta: { marginTop: 2, marginHorizontal: 6, fontSize: 11, color: colors.textSecondary },
  metaMine: { textAlign: 'right' },
  retry: { marginHorizontal: 6, fontSize: 12, fontWeight: '700', color: colors.primaryDeep },
  request: { padding: 14, backgroundColor: colors.background, borderTopWidth: 1, borderTopColor: colors.border },
  requestText: { fontSize: 14, color: colors.dark },
  requestActions: { marginTop: 10, flexDirection: 'row', gap: 10 },
  requestButton: { flex: 1, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  decline: { backgroundColor: colors.neutralDark },
  declineText: { fontSize: 15, fontWeight: '600', color: colors.dark },
  acceptButton: { backgroundColor: colors.dark },
  acceptText: { fontSize: 15, fontWeight: '600', color: colors.white },
  blocked: {
    padding: 16,
    fontSize: 14,
    textAlign: 'center',
    color: colors.textSecondary,
    backgroundColor: colors.background,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
    padding: 10,
    backgroundColor: colors.background,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 120,
    paddingHorizontal: 14,
    paddingTop: 10,
    paddingBottom: 10,
    borderRadius: 20,
    backgroundColor: colors.neutral,
    fontSize: 15,
    color: colors.dark,
  },
  sendButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dark,
  },
  sendDisabled: { opacity: 0.4 },
});
