import React, { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Switch, View } from 'react-native';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useApolloClient, useMutation } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { BylineAvatar } from '../components/PostByline';
import { EmptyState } from '../components/EmptyState';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { SET_DIRECT_MESSAGES_ENABLED } from '../apollo/mutations';
import { GET_DIRECT_CONVERSATIONS, GET_DIRECT_UNREAD_SUMMARY } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { DirectConversation, chatTime, previewOf } from '../utils/directMessages';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'DirectInbox'>['route'];
type Folder = 'inbox' | 'requests';

const PAGE = 30;

/** Mensajes: your conversations, and Solicitudes from people you don't follow. */
export const DirectInboxScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const client = useApolloClient();
  const [folder, setFolder] = useState<Folder>(route.params?.folder ?? 'inbox');
  const [items, setItems] = useState<DirectConversation[] | null>(null);
  const [requests, setRequests] = useState(0);
  const [dmsEnabled, setDmsEnabled] = useState<boolean | null>(null);
  const [failed, setFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const generation = useRef(0);
  const [setEnabled, { loading: switching }] = useMutation(SET_DIRECT_MESSAGES_ENABLED);

  const load = useCallback(async (which: Folder) => {
    generation.current += 1;
    const requested = generation.current;
    try {
      const [list, summary] = await Promise.all([
        client.query({
          query: GET_DIRECT_CONVERSATIONS,
          variables: { folder: which, offset: 0, limit: PAGE },
          fetchPolicy: 'network-only',
        }),
        client.query({ query: GET_DIRECT_UNREAD_SUMMARY, fetchPolicy: 'network-only' }),
      ]);
      if (generation.current !== requested) return;
      const page: DirectConversation[] = list.data?.directConversations ?? [];
      setItems(page);
      setHasMore(page.length === PAGE);
      setRequests(summary.data?.directUnreadSummary?.requests ?? 0);
      setDmsEnabled(summary.data?.directUnreadSummary?.dmsEnabled ?? null);
      setFailed(false);
    } catch {
      if (generation.current === requested) setFailed(true);
    }
  }, [client]);

  useFocusEffect(
    useCallback(() => {
      void load(folder);
    }, [load, folder]),
  );

  const loadMore = async () => {
    if (!hasMore || loadingMore || !items) return;
    const requested = generation.current;
    setLoadingMore(true);
    try {
      const { data } = await client.query({
        query: GET_DIRECT_CONVERSATIONS,
        variables: { folder, offset: items.length, limit: PAGE },
        fetchPolicy: 'network-only',
      });
      if (generation.current !== requested) return;
      const page: DirectConversation[] = data?.directConversations ?? [];
      setItems((current) => {
        const seen = new Set((current ?? []).map((c) => c.id));
        return [...(current ?? []), ...page.filter((c) => !seen.has(c.id))];
      });
      setHasMore(page.length === PAGE);
    } catch {
      // Reaching the end again retries.
    } finally {
      setLoadingMore(false);
    }
  };

  const switchFolder = (next: Folder) => {
    if (next === folder) return;
    setItems(null);
    setFolder(next);
  };

  const toggleEnabled = async (value: boolean) => {
    setDmsEnabled(value);
    try {
      const { data } = await setEnabled({ variables: { enabled: value } });
      setDmsEnabled(Boolean(data?.setDirectMessagesEnabled?.enabled));
    } catch {
      setDmsEnabled(!value);
    }
  };

  const renderItem = ({ item }: { item: DirectConversation }) => (
    <Pressable
      onPress={() => navigation.navigate('DirectChat', { conversationId: item.id, username: item.other.username })}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
      accessibilityRole="button"
    >
      <BylineAvatar name={item.other.username} avatarUrl={item.other.avatarUrl} size={48} />
      <View style={styles.rowBody}>
        <View style={styles.rowTop}>
          <Text style={[styles.name, item.unreadCount > 0 && styles.unread]} numberOfLines={1}>
            {item.other.username}
          </Text>
          {item.lastMessage ? <Text style={styles.time}>{chatTime(item.lastMessage.createdAt)}</Text> : null}
        </View>
        <View style={styles.rowTop}>
          <Text style={[styles.preview, item.unreadCount > 0 && styles.unread]} numberOfLines={1}>
            {previewOf(item.lastMessage) || (item.status === 'request' && !item.isIncomingRequest ? 'Solicitud enviada' : '')}
          </Text>
          {item.unreadCount > 0 ? (
            <View style={styles.badge}><Text style={styles.badgeText}>{item.unreadCount}</Text></View>
          ) : null}
        </View>
      </View>
    </Pressable>
  );

  return (
    <View style={styles.container}>
      <Header title="Mensajes" navigation={navigation as any} onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background} isLight={false} />
      <View style={styles.tabs} accessibilityRole="tablist">
        {(['inbox', 'requests'] as Folder[]).map((key) => {
          const selected = key === folder;
          const label = key === 'inbox' ? 'Mensajes' : `Solicitudes${requests > 0 ? ` (${requests})` : ''}`;
          return (
            <Pressable key={key} onPress={() => switchFolder(key)} style={[styles.tab, selected && styles.tabSelected]}
              accessibilityRole="tab" accessibilityState={{ selected }}>
              <Text style={[styles.tabText, selected && styles.tabTextSelected]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
      <FlatList
        data={items ?? []}
        keyExtractor={(c) => c.id}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
        initialNumToRender={15}
        maxToRenderPerBatch={15}
        windowSize={11}
        onEndReachedThreshold={0.4}
        onEndReached={() => { void loadMore(); }}
        ListFooterComponent={loadingMore ? <ActivityIndicator style={styles.loading} color={colors.primary} /> : null}
        refreshControl={
          <RefreshControl refreshing={refreshing} tintColor={colors.primary}
            onRefresh={async () => { setRefreshing(true); await load(folder); setRefreshing(false); }} />
        }
        ListHeaderComponent={folder === 'inbox' && dmsEnabled !== null ? (
          <View style={styles.setting}>
            <View style={styles.settingText}>
              <Text style={styles.settingTitle}>Recibir mensajes nuevos</Text>
              <Text style={styles.settingHint}>Si lo apagas, nadie nuevo podrá escribirte. Tus conversaciones siguen.</Text>
            </View>
            <Switch value={dmsEnabled} onValueChange={(v) => { void toggleEnabled(v); }} disabled={switching}
              trackColor={{ true: colors.primary, false: colors.border }} />
          </View>
        ) : null}
        ListEmptyComponent={items === null ? (
          <ActivityIndicator style={styles.loading} color={colors.primary} />
        ) : failed ? (
          <EmptyState icon="wifi-off" title="No pudimos cargar tus mensajes" actionLabel="Reintentar"
            onAction={() => { void load(folder); }} />
        ) : folder === 'requests' ? (
          <EmptyState icon="inbox" title="No tienes solicitudes"
            subtitle="Aquí llegan los mensajes de personas que no sigues." />
        ) : (
          <EmptyState icon="message-circle" title="Aún no tienes mensajes"
            subtitle="Escríbele a un inversor desde su perfil. Revisamos cada mensaje antes de entregarlo." />
        )}
      />
    </View>
  );
};

export default DirectInboxScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  tabs: { flexDirection: 'row', gap: 8, paddingHorizontal: 16, paddingVertical: 10, backgroundColor: colors.background },
  tab: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 16, backgroundColor: colors.neutral },
  tabSelected: { backgroundColor: colors.dark },
  tabText: { fontSize: 14, fontWeight: '600', color: colors.textSecondary },
  tabTextSelected: { color: colors.white },
  list: { paddingBottom: 24, flexGrow: 1 },
  loading: { marginTop: 32 },
  setting: {
    flexDirection: 'row', alignItems: 'center', gap: 12, padding: 16, marginBottom: 4,
    backgroundColor: colors.background, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  settingText: { flex: 1 },
  settingTitle: { fontSize: 15, fontWeight: '600', color: colors.dark },
  settingHint: { marginTop: 2, fontSize: 12, color: colors.textSecondary },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.background, borderBottomWidth: 1, borderBottomColor: colors.borderLight,
  },
  pressed: { opacity: 0.7 },
  rowBody: { flex: 1 },
  rowTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  name: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.dark },
  time: { fontSize: 12, color: colors.textSecondary },
  preview: { flex: 1, marginTop: 2, fontSize: 14, color: colors.textSecondary },
  unread: { color: colors.dark, fontWeight: '700' },
  badge: { minWidth: 20, height: 20, paddingHorizontal: 6, borderRadius: 10, backgroundColor: colors.primaryDark,
    alignItems: 'center', justifyContent: 'center' },
  badgeText: { fontSize: 11, fontWeight: '700', color: colors.white },
});
