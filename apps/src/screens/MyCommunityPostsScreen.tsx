import React, { useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Image, Pressable, StyleSheet, View } from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { NetworkStatus, useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../components/common/AppText';
import { EmptyState } from '../components/EmptyState';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { DELETE_COMMUNITY_POST } from '../apollo/mutations';
import { GET_MY_COMMUNITY_POSTS } from '../apollo/queries';
import { formatLocalDate } from '../utils/dateUtils';
import { MainStackParamList } from '../types/navigation';
import { usePollWhile } from '../hooks/usePollWhile';

type Navigation = NativeStackNavigationProp<MainStackParamList>;

type MyPost = {
  id: string;
  body: string;
  imageUrl?: string | null;
  hasImage: boolean;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'FAILED' | 'REMOVED';
  reason?: string | null;
  createdAt: string;
  publishedAt?: string | null;
  commentCount: number;
};

const PAGE_SIZE = 20;
const PENDING_POLL_MS = 5000;
const PENDING_POLL_MAX_MS = 5 * 60 * 1000;
// Matches the server's cap for one read.
const MAX_LOADED = 500;

const STATUS: Record<MyPost['status'], { label: string; icon: string; fg: string; bg: string }> = {
  PENDING: { label: 'En revisión', icon: 'clock', fg: colors.warning.text, bg: colors.warning.background },
  APPROVED: { label: 'Publicada', icon: 'check-circle', fg: colors.primaryDeep, bg: colors.primarySoft },
  REJECTED: { label: 'No aprobada', icon: 'x-circle', fg: colors.error.text, bg: colors.errorLight },
  FAILED: { label: 'No se pudo revisar', icon: 'alert-circle', fg: colors.error.text, bg: colors.errorLight },
  REMOVED: { label: 'Retirada', icon: 'slash', fg: colors.textSecondary, bg: colors.neutralDark },
};

export const MyCommunityPostsScreen = () => {
  const navigation = useNavigation<Navigation>();
  // One query for the whole loaded range: scrolling grows the limit, so a
  // poll or a refresh re-reads every loaded post and never drops pages.
  const [limit, setLimit] = useState(PAGE_SIZE);
  const { data: freshData, previousData, loading, error, refetch, networkStatus, startPolling, stopPolling } =
    useQuery(GET_MY_COMMUNITY_POSTS, {
      variables: { offset: 0, limit },
      fetchPolicy: 'cache-and-network',
      notifyOnNetworkStatusChange: true,
    });
  const data = freshData ?? previousData;
  const [deletePost] = useMutation(DELETE_COMMUNITY_POST);

  const posts: MyPost[] = data?.myCommunityPosts || [];
  // A full window means there may be more; the server caps one read at 500.
  const hasMore = posts.length >= limit && limit < MAX_LOADED;
  const loadingMore = loading && limit > PAGE_SIZE && !freshData;

  // Coming back from the composer or a post: show the latest outcome.
  useFocusEffect(
    React.useCallback(() => {
      refetch().catch(() => {});
    }, [refetch]),
  );

  const anyPending = posts.some((post) => post.status === 'PENDING');
  const pendingKey = posts.filter((post) => post.status === 'PENDING').map((post) => post.id).join(',');
  usePollWhile(anyPending, startPolling, stopPolling, PENDING_POLL_MS, PENDING_POLL_MAX_MS, pendingKey);

  const loadMore = () => {
    if (loading || !hasMore) return;
    setLimit((current) => Math.min(current + PAGE_SIZE, MAX_LOADED));
  };

  const confirmDelete = (post: MyPost) => {
    Alert.alert('¿Eliminar publicación?', post.status === 'APPROVED' ? 'Dejará de verse en Comunidad.' : undefined, [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Eliminar',
        style: 'destructive',
        onPress: async () => {
          try {
            await deletePost({ variables: { contentItemId: post.id } });
            await refetch();
          } catch {
            Alert.alert('No pudimos eliminarla', 'Revisa tu conexión e inténtalo de nuevo.');
          }
        },
      },
    ]);
  };

  const renderItem = ({ item }: { item: MyPost }) => {
    const status = STATUS[item.status] || STATUS.PENDING;
    const live = item.status === 'APPROVED';
    const canRetry = item.status === 'REJECTED' || item.status === 'FAILED';
    return (
      <Pressable
        style={({ pressed }) => [styles.card, pressed && live && styles.cardPressed]}
        onPress={() => live && navigation.navigate('DiscoverPostDetail', { contentItemId: Number(item.id) })}
        disabled={!live}
        accessibilityRole={live ? 'button' : undefined}
      >
        <View style={styles.cardHeader}>
          <View style={[styles.badge, { backgroundColor: status.bg }]}>
            <Icon name={status.icon} size={12} color={status.fg} />
            <Text style={[styles.badgeText, { color: status.fg }]}>{status.label}</Text>
          </View>
          <Text style={styles.date}>{formatLocalDate(item.publishedAt || item.createdAt)}</Text>
        </View>
        <Text style={styles.body} numberOfLines={4}>{item.body}</Text>
        {item.imageUrl ? (
          <Image source={{ uri: item.imageUrl }} style={styles.image} resizeMode="cover" />
        ) : item.hasImage ? (
          <View style={styles.imagePlaceholder}>
            <Icon name="image" size={14} color={colors.textTertiary} />
            <Text style={styles.imagePlaceholderText}>Con foto</Text>
          </View>
        ) : null}
        {item.reason && item.status !== 'APPROVED' ? <Text style={styles.reason}>{item.reason}</Text> : null}
        <View style={styles.footer}>
          {live ? (
            <View style={styles.footerStat}>
              <Icon name="message-circle" size={14} color={colors.textSecondary} />
              <Text style={styles.footerText}>{item.commentCount}</Text>
            </View>
          ) : <View />}
          <View style={styles.footerActions}>
            {canRetry ? (
              <Pressable
                onPress={() => navigation.navigate('CommunityCompose', { initialBody: item.body })}
                hitSlop={8}
                accessibilityRole="button"
              >
                <Text style={styles.actionPrimary}>Editar y reenviar</Text>
              </Pressable>
            ) : null}
            {item.status !== 'REMOVED' ? (
              <Pressable onPress={() => confirmDelete(item)} hitSlop={8} accessibilityRole="button">
                <Text style={styles.actionMuted}>Eliminar</Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      </Pressable>
    );
  };

  const header = (
    <Header
      title="Mis publicaciones"
      navigation={navigation as any}
      onBackPress={() => navigation.goBack()}
      backgroundColor={colors.background}
      isLight={false}
      rightAccessory={
        <Pressable
          onPress={() => navigation.navigate('CommunityCompose')}
          hitSlop={10}
          accessibilityRole="button"
          accessibilityLabel="Nueva publicación"
        >
          <Icon name="edit-3" size={20} color={colors.dark} />
        </Pressable>
      }
    />
  );

  if (loading && !data) {
    return (
      <View style={styles.container}>
        {header}
        <ActivityIndicator style={styles.loading} size="small" color={colors.primary} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {header}
      <FlatList
        data={posts}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        contentContainerStyle={posts.length ? styles.list : styles.emptyList}
        onEndReached={loadMore}
        onEndReachedThreshold={0.4}
        initialNumToRender={10}
        maxToRenderPerBatch={10}
        windowSize={11}
        refreshing={networkStatus === NetworkStatus.refetch}
        onRefresh={() => { refetch().catch(() => {}); }}
        ListHeaderComponent={
          <Pressable
            style={styles.blockedLink}
            onPress={() => navigation.navigate('BlockedMembers')}
            accessibilityRole="button"
          >
            <Icon name="slash" size={14} color={colors.textSecondary} />
            <Text style={styles.blockedLinkText}>Personas bloqueadas</Text>
            <Icon name="chevron-right" size={14} color={colors.textSecondary} />
          </Pressable>
        }
        ListFooterComponent={loadingMore ? <ActivityIndicator style={styles.loading} color={colors.primary} /> : null}
        ListEmptyComponent={
          error ? (
            <EmptyState
              icon="wifi-off"
              title="No pudimos cargar tus publicaciones"
              subtitle="Revisa tu conexión e inténtalo de nuevo."
              actionLabel="Reintentar"
              onAction={() => { refetch().catch(() => {}); }}
            />
          ) : (
            <EmptyState
              icon="edit-3"
              title="Aún no has publicado"
              subtitle="Comparte algo con la comunidad. Revisamos cada publicación antes de mostrarla."
              actionLabel="Publicar"
              onAction={() => navigation.navigate('CommunityCompose')}
            />
          )
        }
      />
    </View>
  );
};

export default MyCommunityPostsScreen;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
  loading: {
    marginVertical: 24,
  },
  list: {
    padding: 16,
    gap: 12,
  },
  emptyList: {
    flexGrow: 1,
  },
  blockedLink: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-end',
    gap: 6,
    paddingVertical: 4,
  },
  blockedLinkText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    gap: 10,
  },
  cardPressed: {
    opacity: 0.85,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
  },
  badgeText: {
    fontSize: 12,
    fontWeight: '600',
  },
  date: {
    fontSize: 12,
    color: colors.textTertiary,
  },
  body: {
    fontSize: 15,
    lineHeight: 21,
    color: colors.text.primary,
  },
  image: {
    width: '100%',
    aspectRatio: 16 / 9,
    borderRadius: 10,
    backgroundColor: colors.neutralDark,
  },
  imagePlaceholder: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  imagePlaceholderText: {
    fontSize: 12,
    color: colors.textTertiary,
  },
  reason: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.error.text,
  },
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  footerStat: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  footerText: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  footerActions: {
    flexDirection: 'row',
    gap: 16,
  },
  actionPrimary: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  actionMuted: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
  },
});
