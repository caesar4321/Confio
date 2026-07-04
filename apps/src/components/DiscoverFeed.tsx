import React from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { ResponsiveImage } from './ResponsiveImage';
import { EmptyState } from './EmptyState';
import { colors } from '../config/theme';

const emojiOptions = ['🔥', '🙌', '😍', '🤯', '💡', '😎', '💪', '👀', '😢', '❤️'];

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
  canReact?: boolean;
  imageUrl?: string | null;
};

const tagIcons: Record<DiscoverItem['type'], string> = {
  product: '🚀',
  video: '▶',
  news: '📊',
};

const platformOrder: Array<'TikTok' | 'Instagram' | 'YouTube'> = ['TikTok', 'Instagram', 'YouTube'];
const platformStyles: Record<'TikTok' | 'Instagram' | 'YouTube', { bg: string; fg: string }> = {
  TikTok: { bg: '#111111', fg: '#FFFFFF' },
  Instagram: { bg: '#C13584', fg: '#FFFFFF' },
  YouTube: { bg: '#DC2626', fg: '#FFFFFF' },
};

type DiscoverFeedProps = {
  items: DiscoverItem[];
  refreshing: boolean;
  loadingMore?: boolean;
  hasMore?: boolean;
  onOpenItem?: (item: DiscoverItem) => void;
  onRefresh?: () => void;
  onEndReached?: () => void;
  onReact?: (itemId: number, emoji: string) => Promise<void>;
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
}: DiscoverFeedProps) {
  const [showEmojiPicker, setShowEmojiPicker] = React.useState<number | null>(null);

  const renderItem = ({ item }: { item: DiscoverItem }) => {
    const topReactions = (item.reactionSummary || []).slice(0, 3);
    const availablePlatformLinks = platformOrder.filter((platform) =>
      item.platformLinks?.some((entry) => entry.platform === platform && entry.url)
    );

    return (
      <View style={styles.card}>
        <Pressable onPress={() => onOpenItem?.(item)} style={styles.cardPressable}>
          <View style={styles.cardHeader}>
            <View style={[styles.tagPill, { backgroundColor: `${item.tagColor}18` }]}>
              <Text style={[styles.tagText, { color: item.tagColor }]}>
                {tagIcons[item.type]} {item.tag}
              </Text>
            </View>
            <Text style={styles.timeText}>{item.time}</Text>
          </View>

          <Text style={styles.cardTitle}>{item.title}</Text>
          <Text style={styles.cardBody} numberOfLines={3}>
            {item.body}
          </Text>

          {item.thumbnail && (
            <View style={styles.videoPanel}>
              <View style={styles.videoPanelGlowOne} />
              <View style={styles.videoPanelGlowTwo} />
              <View style={styles.videoPanelTopRow}>
                <View style={styles.videoPanelBadge}>
                  <Icon name="play" size={12} color="#FFFFFF" />
                  <Text style={styles.videoPanelBadgeText}>Video</Text>
                </View>
              </View>
              <View style={styles.videoPanelCenter}>
                <View style={styles.videoPanelPlayButton}>
                  <Icon name="play" size={16} color="#111827" />
                </View>
              </View>
              <View style={styles.videoPanelBottomRow}>
                <Text style={styles.videoPanelLabel}>Disponible en</Text>
                <View style={styles.videoPanelPlatforms}>
                {availablePlatformLinks.map((platform) => (
                    <Text key={platform} style={[styles.videoPanelPlatformText, { color: platformStyles[platform].fg }]}>
                      {platform}
                    </Text>
                ))}
                </View>
              </View>
            </View>
          )}

          {item.imageUrl ? (
            <ResponsiveImage uri={item.imageUrl} style={styles.postImage} />
          ) : null}
        </Pressable>

        <View style={styles.reactionRow}>
          {topReactions.map(({ emoji, count }) => {
            const active = item.viewerReaction === emoji;
            return (
              <Pressable
                key={emoji}
                onPress={() => {
                  if (onReact) {
                    void onReact(item.id, emoji);
                  }
                }}
                style={[styles.reactionButton, active && styles.reactionButtonActive]}
                accessibilityRole="button"
                accessibilityLabel={`Reaccionar con ${emoji}, ${count} ${count === 1 ? 'reacción' : 'reacciones'}`}
                accessibilityState={{ selected: active }}
              >
                <Text style={styles.reactionEmoji}>{emoji}</Text>
                <Text style={styles.reactionCount}>{count}</Text>
              </Pressable>
            );
          })}

          {item.canReact !== false && (
            <Pressable
              onPress={() => setShowEmojiPicker(showEmojiPicker === item.id ? null : item.id)}
              style={styles.addReactionButton}
              accessibilityRole="button"
              accessibilityLabel="Agregar una reacción"
            >
              <Text style={styles.addReactionText}>+ 😊</Text>
            </Pressable>
          )}
        </View>

        {showEmojiPicker === item.id && item.canReact !== false && (
          <View style={styles.emojiPicker}>
            {emojiOptions.map((emoji) => {
              const active = item.viewerReaction === emoji;
              return (
                <Pressable
                  key={emoji}
                  onPress={() => {
                    setShowEmojiPicker(null);
                    if (onReact) {
                      void onReact(item.id, emoji);
                    }
                  }}
                  style={[styles.emojiOption, active && styles.emojiOptionActive]}
                  accessibilityRole="button"
                  accessibilityLabel={`Reaccionar con ${emoji}`}
                >
                  <Text style={styles.emojiOptionText}>{emoji}</Text>
                </Pressable>
              );
            })}
          </View>
        )}
      </View>
    );
  };

  return (
    <FlatList
      data={items}
      keyExtractor={(item) => String(item.id)}
      renderItem={renderItem}
      contentContainerStyle={styles.content}
      refreshControl={
        onRefresh ? (
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
        ) : undefined
      }
      ListEmptyComponent={
        <EmptyState
          icon="compass"
          title="Nada por aquí todavía"
          subtitle="Vuelve pronto — aquí publicamos novedades de Confío y la comunidad."
        />
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
    paddingTop: 14,
    paddingBottom: 12,
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
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  tagPill: {
    borderRadius: 20,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  tagText: {
    fontSize: 11,
    fontWeight: '700',
  },
  timeText: {
    fontSize: 11,
    color: colors.text.light,
  },
  cardTitle: {
    marginBottom: 5,
    fontSize: 15,
    fontWeight: '700',
    lineHeight: 21,
    color: colors.dark,
  },
  cardBody: {
    marginBottom: 10,
    fontSize: 14,
    lineHeight: 21,
    color: colors.gray700,
  },
  videoPanel: {
    height: 112,
    borderRadius: 14,
    marginBottom: 10,
    overflow: 'hidden',
    backgroundColor: colors.dark,
    position: 'relative',
  },
  videoPanelGlowOne: {
    position: 'absolute',
    top: -24,
    right: -8,
    width: 92,
    height: 92,
    borderRadius: 46,
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  videoPanelGlowTwo: {
    position: 'absolute',
    bottom: -30,
    left: -18,
    width: 110,
    height: 110,
    borderRadius: 55,
    backgroundColor: 'rgba(52, 211, 153, 0.20)', // colors.primary glow
  },
  videoPanelTopRow: {
    paddingHorizontal: 12,
    paddingTop: 12,
  },
  videoPanelBadge: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderRadius: 999,
    paddingHorizontal: 9,
    paddingVertical: 5,
    backgroundColor: 'rgba(255,255,255,0.12)',
  },
  videoPanelBadgeText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  videoPanelCenter: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  videoPanelPlayButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.96)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  videoPanelBottomRow: {
    paddingHorizontal: 12,
    paddingBottom: 10,
  },
  videoPanelLabel: {
    marginBottom: 5,
    fontSize: 10,
    fontWeight: '600',
    color: 'rgba(255,255,255,0.68)',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  videoPanelPlatforms: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  videoPanelPlatformText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  postImage: {
    width: '100%',
    borderRadius: 12,
    marginTop: 12,
    backgroundColor: colors.border,
  },
  reactionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 5,
  },
  reactionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.neutralDark,
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderWidth: 1.5,
    borderColor: 'transparent',
  },
  reactionButtonActive: {
    backgroundColor: colors.primarySoft,
    borderColor: colors.primary,
  },
  reactionEmoji: {
    fontSize: 13,
  },
  reactionCount: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  addReactionButton: {
    backgroundColor: colors.neutralDark,
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  addReactionText: {
    fontSize: 12,
    color: colors.text.secondary,
  },
  emojiPicker: {
    marginTop: 8,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    padding: 8,
  },
  emojiOption: {
    width: 34,
    height: 34,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emojiOptionActive: {
    backgroundColor: colors.primarySoft,
  },
  emojiOptionText: {
    fontSize: 17,
  },
  footerLoader: {
    paddingVertical: 8,
  },
});
