import { ContentPoll } from './ContentPoll';
import React from 'react';
import {
  Image,
  KeyboardAvoidingView,
  Linking,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  Platform,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';


import { Channel, ChannelMessage, ChannelAvatar, channelMeta, tealLight, tealGreen } from './MessageInboxShared';
import { ReactionBar } from './ReactionBar';
import { MainStackParamList } from '../types/navigation';
import { ResponsiveImage } from './ResponsiveImage';
import { trackContentPlatformClick } from '../services/contentClickTrackingService';
import { describeTypes, logBreadcrumb, recordCrashError } from '../services/crashLog';

const platformButtonStyles: Record<'TikTok' | 'Instagram' | 'YouTube', { bg: string; fg: string }> = {
  TikTok: { bg: colors.text.primary, fg: colors.white },
  Instagram: { bg: '#C13584', fg: colors.white },
  YouTube: { bg: colors.error.icon, fg: colors.white },
};
const platformOrder: Array<'TikTok' | 'Instagram' | 'YouTube'> = ['TikTok', 'Instagram', 'YouTube'];

type MessageChannelThreadProps = {
  channel: Channel;
  onBack: () => void;
  onReact: (messageId: number, emoji: string) => Promise<void>;
  onToggleMute: (channel: Channel) => Promise<void>;
  onSendSupportMessage: (body: string) => Promise<void>;
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
  loadMorePosition?: 'top' | 'bottom';
  refreshing?: boolean;
  onRefresh?: () => void;
};

type Navigation = NativeStackNavigationProp<MainStackParamList>;

function getDateGroupLabel(time: string) {
  const parsed = new Date(time);
  if (!Number.isNaN(parsed.getTime())) {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startOfYesterday = new Date(startOfToday);
    startOfYesterday.setDate(startOfYesterday.getDate() - 1);

    if (parsed >= startOfToday) {
      return 'Hoy';
    }
    if (parsed >= startOfYesterday) {
      return 'Ayer';
    }
    return 'Esta semana';
  }
  return 'Esta semana';
}

function EditorialMessageCard({
  message,
  openLink,
  onReact,
  onOpenDetail,
}: {
  message: Exclude<ChannelMessage, { type: 'support' }>;
  openLink: (messageId: number, platform: 'TikTok' | 'Instagram' | 'YouTube', link: string) => Promise<void>;
  onReact: (messageId: number, emoji: string) => Promise<void>;
  onOpenDetail: (messageId: number) => void;
}) {
  // One layout for every editorial post; the channel header already says who
  // wrote it, so each message carries only its topic and time.
  const topic = message.type === 'video' ? 'Video' : message.tag;
  const title = message.title || '';
  const bodyText = message.type === 'news' ? message.body : message.type === 'text' ? message.text : '';
  const body = bodyText && bodyText !== title ? bodyText : '';
  const platformLinks = message.type === 'video'
    ? platformOrder
      .map((platform) => message.platformLinks?.find((item) => item.platform === platform))
      .filter((item): item is NonNullable<typeof item> => Boolean(item?.url))
    : [];

  return (
    <View style={[styles.messageCard, message.isPinned && styles.pinnedMessageCard]}>
      <Pressable
        onPress={() => onOpenDetail(message.id)}
        style={({ pressed }) => [styles.messageContentPressable, pressed && styles.messagePressed]}
        accessibilityRole="button"
        accessibilityHint="Abre la publicación"
      >
        <View style={styles.messageMetaRow}>
          <View style={styles.messageMetaTagsRow}>
            {message.isPinned ? (
              <View style={styles.pinnedPill}>
                <Icon name="bookmark" size={11} color="#B54708" />
                <Text style={styles.pinnedPillText}>Fijado</Text>
              </View>
            ) : null}
            {topic ? <Text style={styles.messageTopic} numberOfLines={1}>{topic}</Text> : null}
          </View>
          <Text style={styles.messageTime}>{message.time}</Text>
        </View>
        {title ? <Text style={styles.messageTitle} numberOfLines={3}>{title}</Text> : null}
        {body ? <Text style={styles.messageBody} numberOfLines={4}>{body}</Text> : null}
        {message.imageUrl ? (
          <View style={styles.messageMedia}>
            <ResponsiveImage uri={message.imageUrl} style={styles.inlineImage} />
            {message.type === 'video' ? (
              <View style={styles.playOverlay} pointerEvents="none">
                <View style={styles.playButton}>
                  <Icon name="play" size={16} color={colors.dark} />
                </View>
              </View>
            ) : null}
          </View>
        ) : null}
      </Pressable>
      {platformLinks.length ? (
        <View style={styles.videoPlatformsRow}>
          {platformLinks.map(({ platform, url }) => (
            <Pressable
              key={platform}
              onPress={() => {
                void openLink(message.id, platform, url);
              }}
              style={[styles.videoPlatformButton, { backgroundColor: platformButtonStyles[platform].bg }]}
              accessibilityRole="link"
              accessibilityLabel={`Ver en ${platform}`}
            >
              <View style={styles.videoPlatformButtonInner}>
                <Text style={[styles.videoPlatformButtonText, { color: platformButtonStyles[platform].fg }]}>
                  {platform}
                </Text>
                <Icon name="external-link" size={12} color={platformButtonStyles[platform].fg} />
              </View>
            </Pressable>
          ))}
        </View>
      ) : null}
      <ContentPoll poll={message.poll} />
      <View style={styles.messageReactions}>
        <ReactionBar
          reactions={message.reactionSummary}
          viewerReaction={message.viewerReaction}
          canReact={Boolean(message.canReact)}
          onReact={(emoji) => {
            void onReact(message.id, emoji);
          }}
        />
      </View>
    </View>
  );
}

function renderMessageContent(
  message: ChannelMessage,
  openLink: (messageId: number, platform: 'TikTok' | 'Instagram' | 'YouTube', link: string) => Promise<void>,
  onReact: (messageId: number, emoji: string) => Promise<void>,
  onOpenDetail: (messageId: number) => void,
) {
  if (message.type !== 'support') {
    return (
      <EditorialMessageCard message={message} openLink={openLink} onReact={onReact} onOpenDetail={onOpenDetail} />
    );
  }

  if (message.senderType === 'USER') {
    return (
      <View style={[styles.supportMessageWrap, styles.supportMessageWrapOwn]}>
        <View style={[styles.supportRow, styles.supportRowOwn]}>
          <View style={[styles.supportBubble, styles.supportBubbleOwn]}>
            <Text style={[styles.supportSenderLabel, styles.supportSenderLabelOwn]}>
              {message.senderName || 'Tú'}
            </Text>
            <Text style={[styles.supportText, styles.supportTextOwn]}>{message.text}</Text>
            <Text style={[styles.supportTime, styles.supportTimeOwn]}>{message.time}</Text>
          </View>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.supportMessageWrap}>
      <View style={styles.supportRow}>
        <View style={styles.supportAvatar}>
          <Icon name="headphones" size={15} color={colors.primaryDark} />
        </View>
        <View style={styles.supportBubble}>
          <Text style={styles.supportSenderLabel}>{message.senderName || 'Soporte de Confío'}</Text>
          <Text style={styles.supportText}>{message.text}</Text>
          <Text style={styles.supportTime}>{message.time}</Text>
        </View>
      </View>
    </View>
  );
}

export function MessageChannelThread({
  channel,
  onBack,
  onReact,
  onToggleMute,
  onSendSupportMessage,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
  loadMorePosition = 'bottom',
  refreshing = false,
  onRefresh,
}: MessageChannelThreadProps) {
  const navigation = useNavigation<Navigation>();
  const [draftMessage, setDraftMessage] = React.useState('');
  const [isSending, setIsSending] = React.useState(false);
  const scrollViewRef = React.useRef<ScrollView | null>(null);
  const previousMessageCountRef = React.useRef(channel.messages.length);
  const shouldScrollToBottomRef = React.useRef(false);
  const loadMoreRequestedRef = React.useRef(false);
  const contentHeightRef = React.useRef(0);
  const scrollOffsetRef = React.useRef(0);
  const prependAdjustmentRef = React.useRef<{ previousContentHeight: number; previousOffset: number } | null>(null);

  React.useEffect(() => {
    logBreadcrumb(
      `MessageChannelThread.mount | ${describeTypes({
        channelId: channel.id,
      })}`
    );
    // Intentionally only on channel.id — message-count churn would make this noisy.
  }, [channel.id]);

  React.useEffect(() => {
    if (channel.id === 'soporte') {
      shouldScrollToBottomRef.current = true;
    }
  }, [channel.id]);

  React.useEffect(() => {
    const messageCount = channel.messages.length;
    const previousMessageCount = previousMessageCountRef.current;
    if (
      (messageCount > previousMessageCount || previousMessageCount === 0)
      && !prependAdjustmentRef.current
    ) {
      shouldScrollToBottomRef.current = true;
    }
    previousMessageCountRef.current = messageCount;
  }, [channel.id, channel.messages.length]);

  React.useEffect(() => {
    if (!loadingMore) {
      loadMoreRequestedRef.current = false;
    }
  }, [loadingMore]);

  const openLink = async (messageId: number, platform: 'TikTok' | 'Instagram' | 'YouTube', link: string) => {
    if (!link || link === '#') {
      return;
    }

    // Defensive: coerce to string before the bridge call. See ReadableNativeArray.getString
    // crash in Crashlytics — a non-string here would crash during arg extraction.
    const safeLink = typeof link === 'string' ? link : String(link);

    logBreadcrumb(
      `MessageChannelThread.openLink | ${describeTypes({
        messageId,
        platform,
        link: safeLink,
      })}`
    );

    try {
      await trackContentPlatformClick({
        contentItemId: messageId,
        surface: 'CHANNEL',
        platform: platform.toUpperCase() as 'TIKTOK' | 'INSTAGRAM' | 'YOUTUBE',
        channelId: channel.id,
        url: safeLink,
      });
      await Linking.openURL(safeLink);
    } catch (error) {
      recordCrashError(error);
    }
  };

  const submitSupportMessage = async () => {
    const nextBody = draftMessage.trim();
    if (!nextBody || isSending) {
      return;
    }
    setIsSending(true);
    try {
      await onSendSupportMessage(nextBody);
      setDraftMessage('');
    } finally {
      setIsSending(false);
    }
  };

  const openDiscoverDetail = (messageId: number) => {
    navigation.navigate('DiscoverPostDetail', { contentItemId: messageId });
  };

  const pinnedMessages = channel.messages.filter((message) => message.isPinned);
  const regularMessages = channel.messages.filter((message) => !message.isPinned);

  return (
    <KeyboardAvoidingView
      style={styles.channelScreen}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 12 : 0}
    >
      <SafeAreaView edges={['top']} style={styles.channelHeaderSafeArea}>
        <View style={styles.channelHeaderRow}>
          <Pressable onPress={onBack} style={styles.backButton}>
            <Icon name="arrow-left" size={22} color={colors.text.primary} />
          </Pressable>
          <ChannelAvatar channel={channel} large />
          <View style={styles.channelHeaderCopy}>
            <Text style={styles.channelHeaderName}>{channel.name}</Text>
            <Text style={styles.channelHeaderSubtitle}>{channel.subtitle}</Text>
          </View>
          {channel.id !== 'soporte' && (
            <Pressable
              onPress={() => {
                void onToggleMute(channel);
              }}
              style={[styles.muteButton, channel.isMuted && styles.muteButtonActive]}
            >
              <Icon name={channel.isMuted ? 'volume-x' : 'bell-off'} size={16} color={channel.isMuted ? colors.white : colors.text.secondary} />
            </Pressable>
          )}
        </View>
      </SafeAreaView>

      <ScrollView
        ref={scrollViewRef}
        contentContainerStyle={styles.channelContent}
        onContentSizeChange={(_, contentHeight) => {
          const prependAdjustment = prependAdjustmentRef.current;
          if (prependAdjustment) {
            const delta = contentHeight - prependAdjustment.previousContentHeight;
            scrollViewRef.current?.scrollTo({
              y: prependAdjustment.previousOffset + delta,
              animated: false,
            });
            prependAdjustmentRef.current = null;
          }
          contentHeightRef.current = contentHeight;
          if (!shouldScrollToBottomRef.current) {
            return;
          }
          shouldScrollToBottomRef.current = false;
          scrollViewRef.current?.scrollToEnd({ animated: true });
        }}
        onScroll={(event) => {
          scrollOffsetRef.current = event.nativeEvent.contentOffset.y;
          if (!hasMore || loadingMore || !onLoadMore || loadMoreRequestedRef.current) {
            return;
          }

          const offsetY = event.nativeEvent.contentOffset.y;
          const layoutHeight = event.nativeEvent.layoutMeasurement.height;
          const contentHeight = event.nativeEvent.contentSize.height;
          const threshold = 120;
          const reachedTop = offsetY <= threshold;
          const reachedBottom = contentHeight - (offsetY + layoutHeight) <= threshold;
          const shouldLoadMore = loadMorePosition === 'top' ? reachedTop : reachedBottom;
          if (!shouldLoadMore) {
            return;
          }

          loadMoreRequestedRef.current = true;
          if (loadMorePosition === 'top') {
            prependAdjustmentRef.current = {
              previousContentHeight: contentHeightRef.current || contentHeight,
              previousOffset: scrollOffsetRef.current,
            };
          }
          onLoadMore();
        }}
        scrollEventThrottle={16}
        refreshControl={
          onRefresh ? (
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={tealGreen} />
          ) : undefined
        }
      >
        {loadingMore && loadMorePosition === 'top' ? (
          <View style={styles.loadMoreIndicator}>
            <Text style={styles.loadMoreText}>Cargando mensajes anteriores...</Text>
          </View>
        ) : null}
        <View style={styles.channelContextCard}>
          <Text style={styles.channelContextText}>{channelMeta[channel.id].description}</Text>
        </View>

        <View style={styles.messagesWrap}>
          {pinnedMessages.length > 0 && (
            <View style={styles.pinnedSection}>
              <View style={styles.dateGroupRow}>
                <View style={styles.dateGroupLine} />
                <Text style={styles.dateGroupLabel}>Fijados</Text>
                <View style={styles.dateGroupLine} />
              </View>
              {pinnedMessages.map((message) => (
                <View key={message.id}>
                  {renderMessageContent(message, openLink, onReact, openDiscoverDetail)}
                </View>
              ))}
            </View>
          )}
          {regularMessages.map((message, index) => {
            const groupLabel = getDateGroupLabel(message.occurredAt || message.time);
            const previousGroup = index > 0
              ? getDateGroupLabel(regularMessages[index - 1].occurredAt || regularMessages[index - 1].time)
              : null;
            const shouldShowGroup = groupLabel !== previousGroup;

            return (
              <View key={message.id}>
                {shouldShowGroup && (
                  <View style={styles.dateGroupRow}>
                    <View style={styles.dateGroupLine} />
                    <Text style={styles.dateGroupLabel}>{groupLabel}</Text>
                    <View style={styles.dateGroupLine} />
                  </View>
                )}
                {renderMessageContent(message, openLink, onReact, openDiscoverDetail)}
              </View>
            );
          })}
        </View>
        {loadingMore && loadMorePosition === 'bottom' ? (
          <View style={styles.loadMoreIndicator}>
            <Text style={styles.loadMoreText}>Cargando mensajes anteriores...</Text>
          </View>
        ) : null}
      </ScrollView>
      {channel.id === 'soporte' && (
        <View style={styles.composerWrap}>
          <TextInput
            value={draftMessage}
            onChangeText={setDraftMessage}
            placeholder="Escribe tu mensaje..."
            placeholderTextColor={colors.text.light}
            multiline
            style={styles.composerInput}
          />
          <Pressable
            onPress={() => {
              void submitSupportMessage();
            }}
            disabled={!draftMessage.trim() || isSending}
            style={[
              styles.composerSendButton,
              (!draftMessage.trim() || isSending) && styles.composerSendButtonDisabled,
            ]}
          >
            <Icon name="send" size={16} color={colors.white} />
          </Pressable>
        </View>
      )}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  messagePressed: {
    opacity: 0.85,
  },
  messageTopic: {
    flexShrink: 1,
    fontSize: 12,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  messageTitle: {
    marginBottom: 4,
    fontSize: 15,
    fontWeight: '700',
    lineHeight: 21,
    color: colors.dark,
  },
  messageBody: {
    fontSize: 14,
    lineHeight: 21,
    color: colors.gray700,
  },
  messageMedia: {
    marginTop: 10,
    borderRadius: 12,
    overflow: 'hidden',
  },
  playOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  playButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.94)',
  },
  messageReactions: {
    marginTop: 10,
  },
  channelScreen: {
    flex: 1,
  },
  channelHeaderSafeArea: {
    backgroundColor: colors.white,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  channelHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 12,
    minHeight: 88,
  },
  backButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.neutral,
  },
  channelHeaderCopy: {
    flex: 1,
  },
  muteButton: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.neutralDark,
    borderRadius: 18,
    width: 36,
    height: 36,
  },
  muteButtonActive: {
    backgroundColor: colors.text.primary,
  },
  channelHeaderName: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.text.primary,
  },
  channelHeaderSubtitle: {
    marginTop: 2,
    fontSize: 12,
    color: colors.text.light,
  },
  channelContent: {
    paddingBottom: 28,
  },
  channelContextCard: {
    marginHorizontal: 14,
    marginTop: 10,
    marginBottom: 0,
    paddingHorizontal: 2,
    paddingVertical: 0,
  },
  channelContextText: {
    fontSize: 12,
    lineHeight: 17,
    color: colors.text.light,
  },
  messagesWrap: {
    paddingHorizontal: 14,
    paddingTop: 12,
  },
  loadMoreIndicator: {
    paddingHorizontal: 14,
    paddingTop: 12,
    alignItems: 'center',
  },
  loadMoreText: {
    fontSize: 12,
    color: colors.text.light,
    fontWeight: '600',
  },
  pinnedSection: {
    marginBottom: 4,
  },
  dateGroupRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
    gap: 10,
  },
  dateGroupLine: {
    flex: 1,
    height: 1,
    backgroundColor: colors.border,
  },
  dateGroupLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.text.light,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  messageCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 14,
    marginBottom: 10,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 1,
    borderWidth: 1,
    borderColor: colors.border,
  },
  pinnedMessageCard: {
    backgroundColor: '#FFFDF7',
    borderColor: '#F7D9A4',
    shadowOpacity: 0.08,
  },
  messageContentPressable: {
    width: '100%',
  },
  messageMetaRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  messageMetaTagsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexShrink: 1,
  },
  pinnedPill: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 4,
    backgroundColor: '#FFF3D6',
    borderWidth: 1,
    borderColor: '#F5D08A',
  },
  pinnedPillText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#B54708',
  },
  messageTime: {
    fontSize: 11,
    color: colors.text.light,
  },
  videoPlatformsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 10,
  },
  inlineImage: {
    width: '100%',
    borderRadius: 12,
    marginBottom: 10,
    backgroundColor: colors.border,
  },
  videoPlatformButton: {
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  videoPlatformButtonInner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  videoPlatformButtonText: {
    fontSize: 12,
    fontWeight: '600',
  },
  supportRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  supportRowOwn: {
    justifyContent: 'flex-end',
  },
  supportAvatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.primarySoft,
    borderWidth: 1,
    borderColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 10,
  },
  supportBubble: {
    flex: 1,
    backgroundColor: colors.neutral,
    borderTopLeftRadius: 6,
    borderTopRightRadius: 16,
    borderBottomLeftRadius: 16,
    borderBottomRightRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  supportBubbleOwn: {
    flex: 0,
    maxWidth: '88%',
    backgroundColor: colors.primaryDark,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    borderBottomLeftRadius: 16,
    borderBottomRightRadius: 6,
    borderColor: colors.primaryDark,
  },
  supportMessageWrap: {
    marginBottom: 12,
    paddingRight: 28,
  },
  supportMessageWrapOwn: {
    paddingRight: 0,
    paddingLeft: 36,
  },
  supportSenderLabel: {
    marginBottom: 4,
    fontSize: 11,
    fontWeight: '700',
    color: colors.text.secondary,
  },
  supportSenderLabelOwn: {
    color: colors.primaryLight,
  },
  supportText: {
    fontSize: 13,
    lineHeight: 20,
    color: colors.text.primary,
  },
  supportTextOwn: {
    color: colors.white,
  },
  supportTime: {
    marginTop: 8,
    fontSize: 11,
    color: colors.text.light,
  },
  supportTimeOwn: {
    color: colors.primaryLight,
    textAlign: 'right',
  },
  composerWrap: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 10,
    paddingHorizontal: 14,
    paddingTop: 10,
    paddingBottom: 14,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.white,
  },
  composerInput: {
    flex: 1,
    minHeight: 42,
    maxHeight: 120,
    backgroundColor: colors.neutral,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 14,
    paddingTop: 11,
    paddingBottom: 11,
    fontSize: 14,
    color: colors.text.primary,
  },
  composerSendButton: {
    width: 42,
    height: 42,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primaryDark,
  },
  composerSendButtonDisabled: {
    backgroundColor: '#A8DCC8',
  },
});
