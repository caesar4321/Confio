import { ContentPoll, ContentPollData } from '../components/ContentPoll';
import React from 'react';
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleProp,
  StyleSheet,
  Text,
  TextStyle,
  View,
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';

import { Header } from '../navigation/Header';
import { REACT_TO_MESSAGE_CONTENT } from '../apollo/mutations';
import { GET_DISCOVER_POST, GET_DISCOVER_POST_BYLINE, GET_DISCOVER_POST_SOURCE } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { ResponsiveImage } from '../components/ResponsiveImage';
import { EmptyState } from '../components/EmptyState';
import { PostByline } from '../components/PostByline';
import { ReactionBar } from '../components/ReactionBar';
import { formatLocalDate } from '../utils/dateUtils';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';
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
    | { id?: string; type: 'title'; text?: string }
    | { id?: string; type: 'quote'; text?: string }
    | { id?: string; type: 'image'; image?: { url?: string; width?: number; height?: number } }
  > | string | null;
  reactionSummary?: Array<{ emoji: string; count: number }> | null;
  viewerReaction?: string | null;
  poll?: ContentPollData | null;
  canReact?: boolean | null;
};

const WORDS_PER_MINUTE = 200;

/** "2 min de lectura" from the post's text, never under a minute. */
export function readingTimeLabel(blocks: Array<{ type: string; text?: string }>): string {
  const words = blocks
    .map((block) => (block.type === 'image' ? '' : block.text || ''))
    .join(' ')
    .split(/\s+/)
    .filter(Boolean).length;
  return `${Math.max(1, Math.round(words / WORDS_PER_MINUTE))} min de lectura`;
}

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
  | { id?: string; type: 'title'; text?: string }
  | { id?: string; type: 'quote'; text?: string }
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
    }
  }
  const fallbackBlocks: Array<
    | { id?: string; type: 'paragraph'; text?: string }
    | { id?: string; type: 'title'; text?: string }
    | { id?: string; type: 'quote'; text?: string }
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
  return renderTextBlockWithLinks(text, onOpenLink, styles.body);
}

function renderTextBlockWithLinks(
  text: string,
  onOpenLink: (url: string) => void,
  textStyle: StyleProp<TextStyle>,
  useQuoteLinkStyle = false
) {
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
    <Text style={textStyle}>
      {parts.map((part, index) => {
        if (part.type === 'link' && part.url) {
          return (
            <Text
              key={`${part.value}-${index}`}
              style={[styles.inlineLink, useQuoteLinkStyle ? styles.quoteInlineLink : null]}
              onPress={() => {
                void onOpenLink(part.url!);
              }}
            >
              {part.value}
            </Text>
          );
        }
        const lines = part.value.split('\n');
        return (
          <Text key={`${part.value}-${index}`}>
            {lines.map((line, lineIndex) => (
              <React.Fragment key={`${part.value}-${index}-${lineIndex}`}>
                {line}
                {lineIndex < lines.length - 1 ? '\n\n' : ''}
              </React.Fragment>
            ))}
          </Text>
        );
      })}
    </Text>
  );
}

export const DiscoverPostDetailScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const { contentItemId } = route.params;
  const [reactToMessageContent] = useMutation(REACT_TO_MESSAGE_CONTENT);

  const { data, loading, refetch } = useQuery(GET_DISCOVER_POST, {
    variables: { contentItemId: String(contentItemId) },
    fetchPolicy: 'network-only',
  });

  const post = data?.discoverPost as DiscoverPostDto | undefined;
  // Byline in its own query, stepping down to the name-only one on a server
  // without avatars, so an older server never fails the post itself.
  const [bylineDocument, setBylineDocument] = React.useState(GET_DISCOVER_POST_BYLINE);
  const { data: sourceData, error: sourceError } = useQuery(bylineDocument, {
    variables: { contentItemId: String(contentItemId) },
    fetchPolicy: 'network-only',
  });
  React.useEffect(() => {
    if (bylineDocument === GET_DISCOVER_POST_BYLINE && isSchemaMismatch(sourceError)) {
      setBylineDocument(GET_DISCOVER_POST_SOURCE);
    }
  }, [bylineDocument, sourceError]);
  const source = sourceData?.discoverPost as
    | {
        sourceName?: string;
        isOfficial?: boolean;
        sourceAvatarUrl?: string | null;
        sourceAvatarEmoji?: string | null;
        publishedAt?: string | null;
      }
    | undefined;

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
    }
  };

  const handleReact = async (emoji: string) => {
    await reactToMessageContent({
      variables: {
        contentItemId: String(contentItemId),
        emoji,
      },
    });
    await refetch();
  };

  if (loading && !post) {
    return (
      <View style={styles.container}>
        <Header
          title="Publicación"
          navigation={navigation as any}
          onBackPress={() => navigation.goBack()}
          backgroundColor={colors.background}
          isLight={false}
        />
        <View style={styles.stateWrap}>
          <ActivityIndicator size="small" color={colors.primary} />
          <Text style={styles.stateText}>Cargando publicación…</Text>
        </View>
      </View>
    );
  }

  if (!post) {
    return (
      <View style={styles.container}>
        <Header
          title="Publicación"
          navigation={navigation as any}
          onBackPress={() => navigation.goBack()}
          backgroundColor={colors.background}
          isLight={false}
        />
        <EmptyState
          icon="file-text"
          title="No se encontró la publicación"
          subtitle="Puede que haya sido eliminada o que el enlace ya no exista."
          actionLabel="Volver"
          onAction={() => navigation.goBack()}
        />
      </View>
    );
  }

  const detailBlocks = normalizeDetailBlocks(post.blocks, post.body, post.imageUrl);
  const availablePlatformLinks = platformOrder
    .map((platform) => post.platformLinks?.find((item) => item.platform === platform))
    .filter((item): item is NonNullable<typeof item> => Boolean(item?.url));

  return (
    <View style={styles.container}>
      <Header
        title="Publicación"
        navigation={navigation as any}
        onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background}
        isLight={false}
      />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.card}>
          {post.tag ? <Text style={styles.topic}>{post.tag}</Text> : null}
          <Text style={styles.title}>{post.title}</Text>
          {source?.sourceName ? (
            <View style={styles.byline}>
              <PostByline
                name={source.sourceName}
                isOfficial={source.isOfficial}
                avatarUrl={source.sourceAvatarUrl}
                avatarEmoji={source.sourceAvatarEmoji}
                meta={[
                  source.publishedAt && !Number.isNaN(Date.parse(source.publishedAt))
                    ? formatLocalDate(source.publishedAt)
                    : post.time,
                  readingTimeLabel(detailBlocks),
                ].filter(Boolean).join(' · ')}
                size="detail"
              />
            </View>
          ) : (
            <Text style={styles.metaOnly}>{post.time}</Text>
          )}
          <View style={styles.blocksWrap}>
            {detailBlocks.map((block, index) => {
              if (block.type === 'image') {
                // An image block without a URL renders nothing, not an empty paragraph.
                return block.image?.url ? (
                  <ResponsiveImage
                    key={block.id || `image-${index}`}
                    uri={block.image.url}
                    style={styles.postImage}
                  />
                ) : null;
              }
              if (block.type === 'title') {
                return (
                  <View key={block.id || `title-${index}`}>
                    {renderTextBlockWithLinks(block.text || '', handleOpenLink, styles.sectionTitle)}
                  </View>
                );
              }
              if (block.type === 'quote') {
                return (
                  <View key={block.id || `quote-${index}`} style={styles.quoteBlock}>
                    {renderTextBlockWithLinks(block.text || '', handleOpenLink, styles.quoteText, true)}
                  </View>
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
                  accessibilityRole="link"
                  accessibilityLabel={`Abrir en ${platform}`}
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

          <ContentPoll poll={post.poll} />
          <View style={styles.reactions}>
            <ReactionBar
              reactions={post.reactionSummary || []}
              viewerReaction={post.viewerReaction}
              canReact={post.canReact !== false}
              onReact={(emoji) => {
                void handleReact(emoji);
              }}
            />
          </View>
        </View>
      </ScrollView>
    </View>
  );
};

export default DiscoverPostDetailScreen;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutralDark,
  },
  content: {
    padding: 14,
    paddingBottom: 28,
  },
  card: {
    backgroundColor: colors.background,
    borderRadius: 18,
    padding: 16,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 1,
  },
  topic: {
    marginBottom: 6,
    fontSize: 12,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  byline: {
    marginBottom: 16,
    paddingBottom: 16,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  metaOnly: {
    marginBottom: 16,
    fontSize: 12,
    color: colors.text.light,
  },
  title: {
    fontSize: 22,
    lineHeight: 29,
    fontWeight: '700',
    color: colors.dark,
    marginBottom: 14,
  },
  body: {
    fontSize: 15,
    lineHeight: 24,
    color: colors.gray700,
    marginBottom: 14,
  },
  sectionTitle: {
    fontSize: 17,
    lineHeight: 24,
    fontWeight: '700',
    color: colors.dark,
    marginTop: 8,
    marginBottom: 12,
  },
  inlineLink: {
    color: colors.accent,
    fontWeight: '600',
  },
  quoteBlock: {
    borderLeftWidth: 3,
    borderLeftColor: colors.borderMedium,
    paddingLeft: 14,
    marginBottom: 14,
  },
  quoteText: {
    fontSize: 15,
    lineHeight: 24,
    color: colors.gray700,
    fontStyle: 'italic',
    marginBottom: 0,
  },
  quoteInlineLink: {
    color: colors.accent,
  },
  blocksWrap: {
    marginTop: 2,
  },
  videoPanel: {
    height: 180,
    borderRadius: 16,
    marginTop: 16,
    overflow: 'hidden',
    backgroundColor: colors.dark,
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
    backgroundColor: 'rgba(52, 211, 153, 0.18)', // colors.primary glow
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
    backgroundColor: colors.border,
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
  reactions: {
    marginTop: 16,
  },
  stateWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  stateText: {
    marginTop: 8,
    fontSize: 13,
    lineHeight: 19,
    color: colors.text.secondary,
    textAlign: 'center',
  },
});
