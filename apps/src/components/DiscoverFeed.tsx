import { ContentPoll, ContentPollData } from './ContentPoll';
import React from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { ResponsiveImage } from './ResponsiveImage';
import { EmptyState } from './EmptyState';
import { PostByline } from './PostByline';
import { ReactionBar } from './ReactionBar';
import { VerifiedBadge } from './VerifiedBadge';
import { colors } from '../config/theme';


export type DiscoverReaction = {
  emoji: string;
  count: number;
};

export type DiscoverItem = {
  id: number;
  type: 'product' | 'video' | 'news';
  tag: string;
  tagColor: string;
  title: string;
  body: string;
  time: string;
  thumbnail?: boolean;
  platformLinks?: Array<{
    platform: 'TikTok' | 'Instagram' | 'YouTube';
    url: string;
  }>;
  reactionSummary?: DiscoverReaction[];
  viewerReaction?: string | null;
  poll?: ContentPollData | null;
  canReact?: boolean;
  imageUrl?: string | null;
  sourceName?: string;
  isOfficial?: boolean;
  sourceAvatarUrl?: string | null;
  sourceAvatarEmoji?: string | null;
};

export type DiscoverSectionKey = 'for_you' | 'official' | 'community';

export type DiscoverSection = {
  key: DiscoverSectionKey;
  label: string;
};

/** Descubrir's feeds: everything, verified sources only, and people. */
export const DISCOVER_SECTIONS: DiscoverSection[] = [
  { key: 'for_you', label: 'Para ti' },
  { key: 'official', label: 'Oficial' },
  { key: 'community', label: 'Comunidad' },
];

const sectionEmptyStates: Record<DiscoverSectionKey, { icon: string; title: string; subtitle: string }> = {
  for_you: {
    icon: 'compass',
    title: 'Nada por aquí todavía',
    subtitle: 'Vuelve pronto — aquí publicamos novedades de Confío y la comunidad.',
  },
  official: {
    icon: 'check-circle',
    title: 'Sin publicaciones oficiales todavía',
    subtitle: 'Aquí verás solo fuentes verificadas: Confío, instituciones y negocios con identidad verificada.',
  },
  community: {
    icon: 'users',
    title: 'Comunidad llega pronto',
    subtitle: 'Aquí podrás leer y publicar con otras personas verificadas en Confío. Mientras tanto, mira Para ti.',
  },
};

const platformOrder: Array<'TikTok' | 'Instagram' | 'YouTube'> = ['TikTok', 'Instagram', 'YouTube'];

/** Topic and time, e.g. "Actualización · hace 2 h". */
export const postMeta = (tag: string | undefined, time: string) =>
  [tag?.trim(), time].filter(Boolean).join(' · ');

type DiscoverFeedProps = {
  items: DiscoverItem[];
  refreshing: boolean;
  loadingMore?: boolean;
  hasMore?: boolean;
  onOpenItem?: (item: DiscoverItem) => void;
  onRefresh?: () => void;
  onEndReached?: () => void;
  onReact?: (itemId: number, emoji: string) => Promise<void>;
  loading?: boolean;
  loadFailed?: boolean;
  onRetry?: () => void;
  sections?: DiscoverSection[];
  activeSection?: DiscoverSectionKey;
  onSelectSection?: (key: DiscoverSectionKey) => void;
};

export function DiscoverFeed({
  items,
  refreshing,
  loadingMore = false,
  hasMore = false,
  onOpenItem,
  onRefresh,
  onEndReached,
  onReact,
  loading = false,
  loadFailed = false,
  onRetry,
  sections = [],
  activeSection = 'for_you',
  onSelectSection,
}: DiscoverFeedProps) {
  const renderItem = ({ item }: { item: DiscoverItem }) => {
    const platforms = platformOrder.filter((platform) =>
      item.platformLinks?.some((entry) => entry.platform === platform && entry.url)
    );
    const isVideo = item.type === 'video' || Boolean(item.thumbnail);

    return (
      <View style={styles.card}>
        <Pressable
          onPress={() => onOpenItem?.(item)}
          style={({ pressed }) => [styles.cardPressable, pressed && styles.cardPressed]}
          accessibilityRole="button"
          accessibilityHint="Abre la publicación"
        >
          {item.sourceName ? (
            <View style={styles.byline}>
              <PostByline
                name={item.sourceName}
                isOfficial={item.isOfficial}
                avatarUrl={item.sourceAvatarUrl}
                avatarEmoji={item.sourceAvatarEmoji}
                meta={postMeta(item.tag, item.time)}
              />
            </View>
          ) : (
            <Text style={styles.metaOnly}>{postMeta(item.tag, item.time)}</Text>
          )}

          {item.title ? <Text style={styles.cardTitle}>{item.title}</Text> : null}
          {item.body ? (
            <Text style={styles.cardBody} numberOfLines={3}>
              {item.body}
            </Text>
          ) : null}

          {item.imageUrl ? (
            <View style={styles.media}>
              <ResponsiveImage uri={item.imageUrl} style={styles.postImage} />
              {isVideo && (
                <View style={styles.playOverlay} pointerEvents="none">
                  <View style={styles.playButton}>
                    <Icon name="play" size={18} color={colors.dark} />
                  </View>
                </View>
              )}
            </View>
          ) : isVideo ? (
            <View style={styles.videoPlaceholder}>
              <View style={styles.playButton}>
                <Icon name="play" size={18} color={colors.dark} />
              </View>
              {platforms.length ? (
                <Text style={styles.videoPlaceholderText}>Disponible en {platforms.join(' · ')}</Text>
              ) : null}
            </View>
          ) : null}
        </Pressable>

        <ContentPoll poll={item.poll} />
        <View style={styles.reactions}>
          <ReactionBar
            reactions={item.reactionSummary}
            viewerReaction={item.viewerReaction}
            canReact={item.canReact !== false && Boolean(onReact)}
            onReact={(emoji) => {
              void onReact?.(item.id, emoji);
            }}
          />
        </View>
      </View>
    );
  };

  const emptyState = sectionEmptyStates[activeSection];
  const sectionHeader = sections.length ? (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.sectionRow}
      style={styles.sectionScroller}
    >
      {sections.map(({ key, label }) => {
        const selected = key === activeSection;
        return (
          <Pressable
            key={key}
            onPress={() => onSelectSection?.(key)}
            style={[styles.sectionChip, selected && styles.sectionChipActive]}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
          >
            {key === 'official' && (
              <VerifiedBadge
                size={14}
                color={selected ? '#FFFFFF' : colors.primaryDark}
                checkColor={selected ? colors.dark : '#FFFFFF'}
              />
            )}
            <Text style={[styles.sectionChipText, selected && styles.sectionChipTextActive]}>{label}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  ) : null;

  return (
    <FlatList
      data={items}
      ListHeaderComponent={sectionHeader}
      keyExtractor={(item) => String(item.id)}
      renderItem={renderItem}
      contentContainerStyle={styles.content}
      refreshControl={
        onRefresh ? (
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
        ) : undefined
      }
      ListEmptyComponent={
        loading ? (
          <View style={styles.footerLoader}>
            <ActivityIndicator size="small" color={colors.primary} />
          </View>
        ) : loadFailed ? (
          <EmptyState
            icon="wifi-off"
            title="No pudimos cargar Descubrir"
            subtitle="Revisa tu conexión e inténtalo de nuevo."
            actionLabel="Reintentar"
            onAction={onRetry}
          />
        ) : (
          <EmptyState icon={emptyState.icon} title={emptyState.title} subtitle={emptyState.subtitle} />
        )
      }
      onEndReachedThreshold={0.35}
      onEndReached={() => {
        if (hasMore && !loadingMore) {
          onEndReached?.();
        }
      }}
      ListFooterComponent={
        loadingMore ? (
          <View style={styles.footerLoader}>
            <ActivityIndicator size="small" color={colors.primary} />
          </View>
        ) : null
      }
    />
  );
}

const styles = StyleSheet.create({
  content: {
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 28,
    flexGrow: 1,
  },
  card: {
    backgroundColor: colors.background,
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 14,
    marginBottom: 12,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 1,
  },
  cardPressable: {
    marginBottom: 2,
  },
  sectionScroller: {
    marginHorizontal: -16,
    marginBottom: 12,
    flexGrow: 0,
  },
  sectionRow: {
    paddingHorizontal: 16,
    gap: 8,
  },
  sectionChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
  },
  sectionChipActive: {
    backgroundColor: colors.dark,
    borderColor: colors.dark,
  },
  sectionChipText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  sectionChipTextActive: {
    color: '#FFFFFF',
  },
  cardPressed: {
    opacity: 0.85,
  },
  byline: {
    marginBottom: 12,
  },
  metaOnly: {
    marginBottom: 8,
    fontSize: 12,
    color: colors.text.light,
  },
  cardTitle: {
    marginBottom: 4,
    fontSize: 16,
    fontWeight: '700',
    lineHeight: 22,
    color: colors.dark,
  },
  cardBody: {
    fontSize: 14,
    lineHeight: 21,
    color: colors.gray700,
  },
  media: {
    marginTop: 12,
    borderRadius: 12,
    overflow: 'hidden',
  },
  postImage: {
    width: '100%',
    borderRadius: 12,
    backgroundColor: colors.border,
  },
  playOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  playButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.94)',
  },
  videoPlaceholder: {
    marginTop: 12,
    height: 120,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    backgroundColor: colors.dark,
  },
  videoPlaceholderText: {
    fontSize: 12,
    fontWeight: '600',
    color: 'rgba(255,255,255,0.72)',
  },
  reactions: {
    marginTop: 12,
  },
  footerLoader: {
    paddingVertical: 8,
  },
});
