import React from 'react';
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Header } from '../navigation/Header';
import { REACT_TO_MESSAGE_CONTENT } from '../apollo/mutations';
import { GET_DISCOVER_POST } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { ResponsiveImage } from '../components/ResponsiveImage';
import { trackContentPlatformClick } from '../services/contentClickTrackingService';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'DiscoverPostDetail'>['route'];

type DiscoverPostDto = {
  id: string;
  type: 'product' | 'video' | 'news';
  tag: string;
  tagColor: string;
  title: string;
  body: string;
  time: string;
  thumbnail: boolean;
  platformLinks?: Array<{ platform: 'TikTok' | 'Instagram' | 'YouTube'; url: string }> | null;
  imageUrl?: string | null;
  blocks?: Array<
    | { id?: string; type: 'paragraph'; text?: string }
    | { id?: string; type: 'image'; image?: { url?: string; width?: number; height?: number } }
  > | string | null;
  reactionSummary?: Array<{ emoji: string; count: number }> | null;
  viewerReaction?: string | null;
  canReact?: boolean | null;
};

const tagIcons = {
  product: '🚀',
  video: '▶',
  news: '📊',
} as const;

const emojiOptions = ['🔥', '🙌', '😍', '🤯', '💡', '😎', '💪', '👀', '😢', '❤️'];
const platformButtonStyles: Record<'TikTok' | 'Instagram' | 'YouTube', { bg: string; fg: string }> = {
  TikTok: { bg: '#111111', fg: '#FFFFFF' },
  Instagram: { bg: '#C13584', fg: '#FFFFFF' },
  YouTube: { bg: '#DC2626', fg: '#FFFFFF' },
};
const platformOrder: Array<'TikTok' | 'Instagram' | 'YouTube'> = ['TikTok', 'Instagram', 'YouTube'];

function normalizeDetailBlocks(
  blocks: DiscoverPostDto['blocks'],
  fallbackBody: string,
  fallbackImageUrl?: string | null
): Array<
  | { id?: string; type: 'paragraph'; text?: string }
  | { id?: string; type: 'image'; image?: { url?: string; width?: number; height?: number } }
> {
  if (Array.isArray(blocks)) {
    return blocks;
  }
  if (typeof blocks === 'string') {
    try {
      const parsedBlocks = JSON.parse(blocks);
      if (Array.isArray(parsedBlocks)) {
        return parsedBlocks;
      }
    } catch (error) {
      console.warn('Failed to parse discover detail blocks', error);
    }
  }
  const fallbackBlocks: Array<
    | { id?: string; type: 'paragraph'; text?: string }
    | { id?: string; type: 'image'; image?: { url?: string; width?: number; height?: number } }
  > = [{ id: 'fallback-body', type: 'paragraph', text: fallbackBody }];
  if (fallbackImageUrl) {
    fallbackBlocks.push({
      id: 'fallback-image',
      type: 'image',
      image: { url: fallbackImageUrl },
    });
  }
  return fallbackBlocks;
}

function renderParagraphWithLinks(text: string, onOpenLink: (url: string) => void) {
  const parts: Array<{ type: 'text' | 'link'; value: string; url?: string }> = [];
  const pattern = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let lastIndex = 0;
  let match = pattern.exec(text);

  while (match) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', value: text.slice(lastIndex, match.index) });
    }
    parts.push({ type: 'link', value: match[1], url: match[2] });
    lastIndex = match.index + match[0].length;
    match = pattern.exec(text);
  }

  if (lastIndex < text.length) {
    parts.push({ type: 'text', value: text.slice(lastIndex) });
  }

  if (parts.length === 0) {
    parts.push({ type: 'text', value: text });
  }

  return (
    <Text style={styles.body}>
      {parts.map((part, index) => {
        if (part.type === 'link' && part.url) {
          return (
            <Text
              key={`${part.value}-${index}`}
              style={styles.inlineLink}
              onPress={() => {
                void onOpenLink(part.url!);
              }}
            >
              {part.value}
            </Text>
          );
        }
        return <Text key={`${part.value}-${index}`}>{part.value}</Text>;
      })}
    </Text>
  );
}

export const DiscoverPostDetailScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const { contentItemId } = route.params;
  const [showEmojiPicker, setShowEmojiPicker] = React.useState(false);
  const [reactToMessageContent] = useMutation(REACT_TO_MESSAGE_CONTENT);

  const { data, loading, refetch } = useQuery(GET_DISCOVER_POST, {
    variables: { contentItemId: String(contentItemId) },
    fetchPolicy: 'network-only',
  });

  const post = data?.discoverPost as DiscoverPostDto | undefined;

  const handleOpenLink = async (
    url: string,
    platform?: 'TikTok' | 'Instagram' | 'YouTube'
  ) => {
    if (!url) {
      return;
    }
    try {
      if (platform) {
        await trackContentPlatformClick({
          contentItemId,
          surface: 'DISCOVER',
          platform: platform.toUpperCase() as 'TIKTOK' | 'INSTAGRAM' | 'YOUTUBE',
          url,
        });
      }
      await Linking.openURL(url);
    } catch (error) {
      console.warn('Failed to open discover platform link', error);
    }
  };

  const handleReact = async (emoji: string) => {
    await reactToMessageContent({
      variables: {
        contentItemId: String(contentItemId),
        emoji,
      },
    });
    setShowEmojiPicker(false);
    await refetch();
  };

  if (loading && !post) {
    return (
      <View style={styles.container}>
        <Header
          title="Detalle"
          navigation={navigation as any}
          onBackPress={() => navigation.goBack()}
          backgroundColor="#FFFFFF"
          isLight={false}
        />
        <View style={styles.stateWrap}>
          <ActivityIndicator size="small" color="#34d399" />
          <Text style={styles.stateText}>Cargando detalle...</Text>
        </View>
      </View>
    );
  }

  if (!post) {
    return (
      <View style={styles.container}>
        <Header
          title="Detalle"
          navigation={navigation as any}
          onBackPress={() => navigation.goBack()}
          backgroundColor="#FFFFFF"
          isLight={false}
        />
        <View style={styles.stateWrap}>
          <Text style={styles.stateTitle}>No se encontró la publicación</Text>
        </View>
      </View>
    );
  }

  const topReactions = (post.reactionSummary || []).slice(0, 3);
  const detailBlocks = normalizeDetailBlocks(post.blocks, post.body, post.imageUrl);
  const availablePlatformLinks = platformOrder
    .map((platform) => post.platformLinks?.find((item) => item.platform === platform))
    .filter((item): item is NonNullable<typeof item> => Boolean(item?.url));

  return (
    <View style={styles.container}>
      <Header
        title="Detalle"
        navigation={navigation as any}
        onBackPress={() => navigation.goBack()}
        backgroundColor="#FFFFFF"
        isLight={false}
      />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <View style={styles.headerRow}>
            <View style={[styles.tagPill, { backgroundColor: `${post.tagColor}18` }]}>
              <Text style={[styles.tagText, { color: post.tagColor }]}>
                {tagIcons[post.type]} {post.tag}
              </Text>
            </View>
            <Text style={styles.timeText}>{post.time}</Text>
          </View>

          <Text style={styles.title}>{post.title}</Text>
          <View style={styles.blocksWrap}>
            {detailBlocks.map((block, index) => {
              if (block.type === 'image' && block.image?.url) {
                return (
                  <ResponsiveImage
                    key={block.id || `image-${index}`}
                    uri={block.image.url}
                    style={styles.postImage}
                  />
                );
              }
              return (
                <View key={block.id || `paragraph-${index}`}>
                  {renderParagraphWithLinks(block.text || '', handleOpenLink)}
                </View>
              );
            })}
          </View>

          {post.thumbnail && (
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
                  <Icon name="play" size={18} color="#111827" />
                </View>
              </View>
              <View style={styles.videoPanelBottomRow}>
                <Text style={styles.videoPanelLabel}>Disponible en</Text>
                <Text style={styles.videoPanelSubLabel}>Abrir en una plataforma</Text>
              </View>
            </View>
          )}
          {availablePlatformLinks.length > 0 && (
            <View style={styles.videoPlatformsRow}>
              {availablePlatformLinks.map(({ platform, url }) => (
                <Pressable
                  key={platform}
                  onPress={() => {
                    void handleOpenLink(url, platform);
                  }}
                  style={[
                    styles.videoPlatformButton,
                    { backgroundColor: platformButtonStyles[platform].bg },
                  ]}
                >
                  <View style={styles.videoPlatformButtonInner}>
                    <Text
                      style={[
                        styles.videoPlatformButtonText,
                        { color: platformButtonStyles[platform].fg },
                      ]}
                    >
                      {platform}
                    </Text>
                    <Icon name="external-link" size={12} color={platformButtonStyles[platform].fg} />
                  </View>
                </Pressable>
              ))}
            </View>
          )}

          <View style={styles.reactionRow}>
            {topReactions.map(({ emoji, count }) => {
              const active = post.viewerReaction === emoji;
              return (
                <Pressable
                  key={emoji}
                  onPress={() => {
                    void handleReact(emoji);
                  }}
                  style={[styles.reactionButton, active && styles.reactionButtonActive]}
                >
                  <Text style={styles.reactionEmoji}>{emoji}</Text>
                  <Text style={styles.reactionCount}>{count}</Text>
                </Pressable>
              );
            })}
            {post.canReact !== false && (
              <Pressable
                onPress={() => setShowEmojiPicker((current) => !current)}
                style={styles.addReactionButton}
              >
                <Text style={styles.addReactionText}>+ 😊</Text>
              </Pressable>
            )}
          </View>

          {showEmojiPicker && post.canReact !== false && (
            <View style={styles.emojiPicker}>
              {emojiOptions.map((emoji) => {
                const active = post.viewerReaction === emoji;
                return (
                  <Pressable
                    key={emoji}
                    onPress={() => {
                      void handleReact(emoji);
                    }}
                    style={[styles.emojiOption, active && styles.emojiOptionActive]}
                  >
                    <Text style={styles.emojiOptionText}>{emoji}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        </View>
      </ScrollView>
    </View>
  );
};

export default DiscoverPostDetailScreen;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F4F6F8',
  },
  content: {
    padding: 14,
    paddingBottom: 28,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 18,
    padding: 16,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 1,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
    gap: 12,
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
    color: '#AAAAAA',
  },
  title: {
    fontSize: 20,
    lineHeight: 26,
    fontWeight: '700',
    color: '#111111',
    marginBottom: 10,
  },
  body: {
    fontSize: 15,
    lineHeight: 24,
    color: '#475467',
    marginBottom: 14,
  },
  inlineLink: {
    color: '#2563EB',
    fontWeight: '600',
  },
  blocksWrap: {
    marginTop: 2,
  },
  videoPanel: {
    height: 180,
    borderRadius: 16,
    marginTop: 16,
    overflow: 'hidden',
    backgroundColor: '#111827',
    position: 'relative',
  },
  videoPanelGlowOne: {
    position: 'absolute',
    top: -34,
    right: -14,
    width: 132,
    height: 132,
    borderRadius: 66,
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  videoPanelGlowTwo: {
    position: 'absolute',
    bottom: -42,
    left: -26,
    width: 152,
    height: 152,
    borderRadius: 76,
    backgroundColor: 'rgba(29,181,135,0.18)',
  },
  videoPanelTopRow: {
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  videoPanelBadge: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
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
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: 'rgba(255,255,255,0.96)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  videoPanelBottomRow: {
    paddingHorizontal: 16,
    paddingBottom: 14,
  },
  videoPanelLabel: {
    marginBottom: 4,
    fontSize: 10,
    fontWeight: '600',
    color: 'rgba(255,255,255,0.68)',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  videoPanelSubLabel: {
    fontSize: 13,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  postImage: {
    width: '100%',
    borderRadius: 14,
    marginTop: 16,
    backgroundColor: '#E5E7EB',
  },
  videoPlatformsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 14,
  },
  videoPlatformButton: {
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  videoPlatformButtonInner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  videoPlatformButtonText: {
    fontSize: 12,
    fontWeight: '700',
  },
  reactionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    flexWrap: 'wrap',
    marginTop: 16,
  },
  reactionButton: {
    backgroundColor: '#F4F6F8',
    borderRadius: 20,
    paddingHorizontal: 9,
    paddingVertical: 4,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
  },
  reactionButtonActive: {
    backgroundColor: '#E8F8F2',
    borderWidth: 1,
    borderColor: '#1DB587',
  },
  reactionEmoji: {
    fontSize: 13,
  },
  reactionCount: {
    fontSize: 11,
    fontWeight: '600',
    color: '#666666',
  },
  addReactionButton: {
    backgroundColor: '#F4F6F8',
    borderRadius: 20,
    paddingHorizontal: 9,
    paddingVertical: 4,
  },
  addReactionText: {
    fontSize: 12,
    color: '#888888',
  },
  emojiPicker: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 8,
    borderWidth: 1,
    borderColor: '#EAEAEA',
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
    marginTop: 10,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 16,
    elevation: 2,
  },
  emojiOption: {
    borderRadius: 8,
    width: 34,
    height: 34,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emojiOptionActive: {
    backgroundColor: '#E8F8F2',
  },
  emojiOptionText: {
    fontSize: 17,
  },
  stateWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  stateTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#111827',
  },
  stateText: {
    marginTop: 8,
    fontSize: 13,
    lineHeight: 19,
    color: '#6B7280',
    textAlign: 'center',
  },
});
