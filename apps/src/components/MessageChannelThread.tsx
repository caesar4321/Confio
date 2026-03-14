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
import FAIcon from 'react-native-vector-icons/FontAwesome';

import founderImage from '../assets/png/JulianMoon_Founder.jpeg';
import { Channel, ChannelMessage, ChannelAvatar, channelMeta, messageReactionOptions, tealLight, tealGreen } from './MessageInboxShared';
import { MainStackParamList } from '../types/navigation';

const platformButtonStyles: Record<'TikTok' | 'Instagram' | 'YouTube', { bg: string; fg: string }> = {
  TikTok: { bg: '#111111', fg: '#FFFFFF' },
  Instagram: { bg: '#C13584', fg: '#FFFFFF' },
  YouTube: { bg: '#DC2626', fg: '#FFFFFF' },
};
const platformOrder: Array<'TikTok' | 'Instagram' | 'YouTube'> = ['TikTok', 'Instagram', 'YouTube'];

type MessageChannelThreadProps = {
  channel: Channel;
  onBack: () => void;
  onReact: (messageId: number, emoji: string) => Promise<void>;
  onToggleMute: (channel: Channel) => Promise<void>;
  onSendSupportMessage: (body: string) => Promise<void>;
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

function renderMessageContent(
  channel: Channel,
  message: ChannelMessage,
  openLink: (link: string) => Promise<void>,
  onReact: (messageId: number, emoji: string) => Promise<void>,
  onOpenDetail: (messageId: number) => void,
  showEmojiPicker: number | null,
  setShowEmojiPicker: React.Dispatch<React.SetStateAction<number | null>>
) {
  const topReactions = (message.reactionSummary || []).slice(0, 3);

  if (message.type === 'video') {
    const availablePlatformLinks = platformOrder
      .map((platform) => message.platformLinks?.find((item) => item.platform === platform))
      .filter((item): item is NonNullable<typeof item> => Boolean(item?.url));

    return (
      <View style={[styles.messageCard, styles.videoMessageCard, message.isPinned && styles.pinnedMessageCard]}>
        <Pressable onPress={() => onOpenDetail(message.id)}>
          <View style={styles.messageMetaRow}>
            <View style={styles.messageMetaTagsRow}>
              {message.isPinned ? (
                <View style={styles.pinnedPill}>
                  <Icon name="bookmark" size={11} color="#B54708" />
                  <Text style={styles.pinnedPillText}>Fijado</Text>
                </View>
              ) : null}
              <View style={[styles.messageTag, styles.videoTag]}>
                <Text style={[styles.messageTagText, styles.videoTagText]}>▶ Video</Text>
              </View>
            </View>
            <Text style={styles.messageTime}>{message.time}</Text>
          </View>
          <Text style={styles.videoTitle} numberOfLines={2}>
            {message.title}
          </Text>
        </Pressable>
        <View style={styles.videoPlatformsRow}>
          {availablePlatformLinks.map(({ platform, url }) => (
            <Pressable
              key={platform}
              onPress={() => {
                void openLink(url);
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
                <Icon
                  name="external-link"
                  size={12}
                  color={platformButtonStyles[platform].fg}
                />
              </View>
            </Pressable>
          ))}
        </View>
        {message.imageUrl ? (
          <Image source={{ uri: message.imageUrl }} style={styles.inlineImage} resizeMode="cover" />
        ) : null}
        <View style={styles.reactionRow}>
          {topReactions.map(({ emoji, count }) => {
            const active = message.viewerReaction === emoji;
            return (
              <Pressable
                key={emoji}
                onPress={() => {
                  void onReact(message.id, emoji);
                }}
                style={[styles.reactionButton, active && styles.reactionButtonActive]}
              >
                <Text style={styles.reactionEmoji}>{emoji}</Text>
                <Text style={styles.reactionCount}>{count}</Text>
              </Pressable>
            );
          })}
          {message.canReact && (
            <Pressable
              onPress={() => setShowEmojiPicker(showEmojiPicker === message.id ? null : message.id)}
              style={styles.addReactionButton}
            >
              <Text style={styles.addReactionText}>+ 😊</Text>
            </Pressable>
          )}
        </View>
        {showEmojiPicker === message.id && message.canReact && (
          <View style={styles.emojiPicker}>
            {messageReactionOptions.map((emoji) => {
              const active = message.viewerReaction === emoji;
              return (
                <Pressable
                  key={emoji}
                  onPress={() => {
                    setShowEmojiPicker(null);
                    void onReact(message.id, emoji);
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
    );
  }

  if (message.type === 'text') {
    const isFounderChannel = channel.id === 'julian';

    return (
      <View style={[styles.messageCard, styles.founderMessageCard, message.isPinned && styles.pinnedMessageCard]}>
        <Pressable onPress={() => onOpenDetail(message.id)}>
          {message.isPinned ? (
            <View style={styles.pinnedRow}>
              <View style={styles.pinnedPill}>
                <Icon name="bookmark" size={11} color="#B54708" />
                <Text style={styles.pinnedPillText}>Fijado</Text>
              </View>
            </View>
          ) : null}
          {isFounderChannel ? (
            <View style={styles.founderAuthorRow}>
              <Image source={founderImage} style={styles.founderAuthorAvatar} />
              <View style={styles.founderAuthorCopy}>
                <Text style={styles.founderAuthorName}>🇰🇷 Julian Moon 🌙</Text>
                <Text style={styles.founderAuthorRole}>Founder</Text>
              </View>
            </View>
          ) : (
            <View style={styles.messageMetaRow}>
              <View style={[styles.messageTag, styles.newsTag]}>
                <Text style={[styles.messageTagText, styles.newsTagText]}>
                  {message.tag || channel.name}
                </Text>
              </View>
              <Text style={styles.messageTime}>{message.time}</Text>
            </View>
          )}
          <View style={styles.founderTextHeader}>
            <Text style={styles.founderTextLabel}>
              {isFounderChannel ? 'Actualización' : 'Publicación'}
            </Text>
            {isFounderChannel ? <Text style={styles.messageTime}>{message.time}</Text> : null}
          </View>
          <Text style={styles.textMessageBody} numberOfLines={4}>
            {message.text}
          </Text>
        </Pressable>
        {message.imageUrl ? (
          <Image source={{ uri: message.imageUrl }} style={styles.inlineImage} resizeMode="cover" />
        ) : null}
        <View style={styles.reactionRow}>
          {topReactions.map(({ emoji, count }) => {
            const active = message.viewerReaction === emoji;
            return (
              <Pressable
                key={emoji}
                onPress={() => {
                  void onReact(message.id, emoji);
                }}
                style={[styles.reactionButton, active && styles.reactionButtonActive]}
              >
                <Text style={styles.reactionEmoji}>{emoji}</Text>
                <Text style={styles.reactionCount}>{count}</Text>
              </Pressable>
            );
          })}
          {message.canReact && (
            <Pressable
              onPress={() => setShowEmojiPicker(showEmojiPicker === message.id ? null : message.id)}
              style={styles.addReactionButton}
            >
              <Text style={styles.addReactionText}>+ 😊</Text>
            </Pressable>
          )}
        </View>
        {showEmojiPicker === message.id && message.canReact && (
          <View style={styles.emojiPicker}>
            {messageReactionOptions.map((emoji) => {
              const active = message.viewerReaction === emoji;
              return (
                <Pressable
                  key={emoji}
                  onPress={() => {
                    setShowEmojiPicker(null);
                    void onReact(message.id, emoji);
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
    );
  }

  if (message.type === 'news') {
    return (
      <View style={[styles.messageCard, styles.newsMessageCard, message.isPinned && styles.pinnedMessageCard]}>
        <Pressable onPress={() => onOpenDetail(message.id)}>
          <View style={styles.messageMetaRow}>
            <View style={styles.messageMetaTagsRow}>
              {message.isPinned ? (
                <View style={styles.pinnedPill}>
                  <Icon name="bookmark" size={11} color="#B54708" />
                  <Text style={styles.pinnedPillText}>Fijado</Text>
                </View>
              ) : null}
              <View style={[styles.messageTag, styles.newsTag]}>
                <Text style={[styles.messageTagText, styles.newsTagText]}>{message.tag}</Text>
              </View>
            </View>
            <Text style={styles.messageTime}>{message.time}</Text>
          </View>
          <Text style={styles.newsTitle} numberOfLines={2}>
            {message.title}
          </Text>
          <Text style={styles.newsBody} numberOfLines={4}>
            {message.body}
          </Text>
        </Pressable>
        {message.imageUrl ? (
          <Image source={{ uri: message.imageUrl }} style={styles.inlineImage} resizeMode="cover" />
        ) : null}
        <View style={styles.reactionRow}>
          {topReactions.map(({ emoji, count }) => {
            const active = message.viewerReaction === emoji;
            return (
              <Pressable
                key={emoji}
                onPress={() => {
                  void onReact(message.id, emoji);
                }}
                style={[styles.reactionButton, active && styles.reactionButtonActive]}
              >
                <Text style={styles.reactionEmoji}>{emoji}</Text>
                <Text style={styles.reactionCount}>{count}</Text>
              </Pressable>
            );
          })}
          {message.canReact && (
            <Pressable
              onPress={() => setShowEmojiPicker(showEmojiPicker === message.id ? null : message.id)}
              style={styles.addReactionButton}
            >
              <Text style={styles.addReactionText}>+ 😊</Text>
            </Pressable>
          )}
        </View>
        {showEmojiPicker === message.id && message.canReact && (
          <View style={styles.emojiPicker}>
            {messageReactionOptions.map((emoji) => {
              const active = message.viewerReaction === emoji;
              return (
                <Pressable
                  key={emoji}
                  onPress={() => {
                    setShowEmojiPicker(null);
                    void onReact(message.id, emoji);
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
          <FAIcon name="headphones" size={15} color="#0F9F74" />
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
  refreshing = false,
  onRefresh,
}: MessageChannelThreadProps) {
  const navigation = useNavigation<Navigation>();
  const [showEmojiPicker, setShowEmojiPicker] = React.useState<number | null>(null);
  const [draftMessage, setDraftMessage] = React.useState('');
  const [isSending, setIsSending] = React.useState(false);
  const scrollViewRef = React.useRef<ScrollView | null>(null);
  const previousMessageCountRef = React.useRef(channel.messages.length);
  const shouldScrollToBottomRef = React.useRef(false);

  React.useEffect(() => {
    const messageCount = channel.messages.length;
    const previousMessageCount = previousMessageCountRef.current;
    if (messageCount > previousMessageCount || previousMessageCount === 0) {
      shouldScrollToBottomRef.current = true;
    }
    previousMessageCountRef.current = messageCount;
  }, [channel.id, channel.messages.length]);

  const openLink = async (link: string) => {
    if (!link || link === '#') {
      return;
    }

    try {
      await Linking.openURL(link);
    } catch (error) {
      console.warn('Failed to open link', error);
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
            <Icon name="arrow-left" size={22} color="#1F2937" />
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
              <Icon name={channel.isMuted ? 'volume-x' : 'bell-off'} size={16} color={channel.isMuted ? '#FFFFFF' : '#667085'} />
            </Pressable>
          )}
        </View>
      </SafeAreaView>

      <ScrollView
        ref={scrollViewRef}
        contentContainerStyle={styles.channelContent}
        onContentSizeChange={() => {
          if (!shouldScrollToBottomRef.current) {
            return;
          }
          shouldScrollToBottomRef.current = false;
          scrollViewRef.current?.scrollToEnd({ animated: true });
        }}
        refreshControl={
          onRefresh ? (
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={tealGreen} />
          ) : undefined
        }
      >
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
                  {renderMessageContent(
                    channel,
                    message,
                    openLink,
                    onReact,
                    openDiscoverDetail,
                    showEmojiPicker,
                    setShowEmojiPicker
                  )}
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
                {renderMessageContent(
                  channel,
                  message,
                  openLink,
                  onReact,
                  openDiscoverDetail,
                  showEmojiPicker,
                  setShowEmojiPicker
                )}
              </View>
            );
          })}
        </View>
      </ScrollView>
      {channel.id === 'soporte' && (
        <View style={styles.composerWrap}>
          <TextInput
            value={draftMessage}
            onChangeText={setDraftMessage}
            placeholder="Escribe tu mensaje..."
            placeholderTextColor="#98A2B3"
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
            <Icon name="send" size={16} color="#FFFFFF" />
          </Pressable>
        </View>
      )}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  channelScreen: {
    flex: 1,
  },
  channelHeaderSafeArea: {
    backgroundColor: '#FFFFFF',
    borderBottomWidth: 1,
    borderBottomColor: '#EAEAEA',
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
    backgroundColor: '#F9FAFB',
  },
  channelHeaderCopy: {
    flex: 1,
  },
  muteButton: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#F4F6F8',
    borderRadius: 18,
    width: 36,
    height: 36,
  },
  muteButtonActive: {
    backgroundColor: '#111827',
  },
  channelHeaderName: {
    fontSize: 15,
    fontWeight: '700',
    color: '#111111',
  },
  channelHeaderSubtitle: {
    marginTop: 2,
    fontSize: 12,
    color: '#98A2B3',
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
    color: '#98A2B3',
  },
  messagesWrap: {
    paddingHorizontal: 14,
    paddingTop: 12,
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
    backgroundColor: '#E5E7EB',
  },
  dateGroupLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: '#98A2B3',
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  messageCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 14,
    marginBottom: 10,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 1,
    borderWidth: 1,
    borderColor: '#EDF2F7',
  },
  pinnedMessageCard: {
    backgroundColor: '#FFFDF7',
    borderColor: '#F7D9A4',
    shadowOpacity: 0.08,
  },
  videoMessageCard: {
    borderColor: '#F2E7E7',
  },
  newsMessageCard: {
    borderColor: '#DDF4EB',
  },
  founderMessageCard: {
    borderColor: '#E6EAF2',
  },
  founderAuthorRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
  },
  founderAuthorAvatar: {
    width: 28,
    height: 28,
    borderRadius: 14,
    marginRight: 10,
  },
  founderAuthorCopy: {
    flex: 1,
  },
  founderAuthorName: {
    fontSize: 12,
    fontWeight: '700',
    color: '#111827',
  },
  founderAuthorRole: {
    marginTop: 1,
    fontSize: 11,
    color: '#98A2B3',
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
  pinnedRow: {
    marginBottom: 8,
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
  messageTag: {
    borderRadius: 20,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  messageTagText: {
    fontSize: 11,
    fontWeight: '700',
  },
  videoTag: {
    backgroundColor: '#FF444418',
  },
  videoTagText: {
    color: '#FF4444',
  },
  newsTag: {
    backgroundColor: tealLight,
  },
  newsTagText: {
    color: tealGreen,
  },
  messageTime: {
    fontSize: 11,
    color: '#AAAAAA',
  },
  videoTitle: {
    marginBottom: 10,
    fontSize: 13,
    fontWeight: '600',
    lineHeight: 18,
    color: '#111111',
  },
  videoPlatformsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 10,
  },
  inlineImage: {
    width: '100%',
    height: 172,
    borderRadius: 12,
    marginBottom: 10,
    backgroundColor: '#E5E7EB',
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
  reactionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexWrap: 'wrap',
    marginTop: 2,
  },
  reactionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#F4F6F8',
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderWidth: 1.5,
    borderColor: 'transparent',
  },
  reactionButtonActive: {
    backgroundColor: '#E8F8F2',
    borderColor: tealGreen,
  },
  reactionEmoji: {
    fontSize: 13,
  },
  reactionCount: {
    fontSize: 11,
    color: '#667085',
    fontWeight: '600',
  },
  addReactionButton: {
    backgroundColor: '#F4F6F8',
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  addReactionText: {
    fontSize: 12,
    color: '#667085',
    fontWeight: '600',
  },
  emojiPicker: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 8,
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#EAEAEA',
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
    backgroundColor: '#E8F8F2',
  },
  emojiOptionText: {
    fontSize: 17,
  },
  founderTextHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  founderTextLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: '#475467',
    letterSpacing: 0.1,
  },
  textMessageBody: {
    flex: 1,
    fontSize: 13,
    lineHeight: 20,
    color: '#333333',
  },
  newsTitle: {
    marginBottom: 5,
    fontSize: 14,
    fontWeight: '700',
    color: '#111111',
  },
  newsBody: {
    fontSize: 13,
    lineHeight: 20,
    color: '#555555',
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
    backgroundColor: '#ECFDF3',
    borderWidth: 1,
    borderColor: '#D1FADF',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 10,
  },
  supportBubble: {
    flex: 1,
    backgroundColor: '#F7F9FC',
    borderTopLeftRadius: 6,
    borderTopRightRadius: 16,
    borderBottomLeftRadius: 16,
    borderBottomRightRadius: 16,
    borderWidth: 1,
    borderColor: '#E5EAF1',
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  supportBubbleOwn: {
    flex: 0,
    maxWidth: '88%',
    backgroundColor: '#0F9F74',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    borderBottomLeftRadius: 16,
    borderBottomRightRadius: 6,
    borderColor: '#0F9F74',
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
    color: '#475467',
  },
  supportSenderLabelOwn: {
    color: '#D1FAE5',
  },
  supportText: {
    fontSize: 13,
    lineHeight: 20,
    color: '#333333',
  },
  supportTextOwn: {
    color: '#FFFFFF',
  },
  supportTime: {
    marginTop: 8,
    fontSize: 11,
    color: '#98A2B3',
  },
  supportTimeOwn: {
    color: '#A7F3D0',
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
    borderTopColor: '#EAEAEA',
    backgroundColor: '#FFFFFF',
  },
  composerInput: {
    flex: 1,
    minHeight: 42,
    maxHeight: 120,
    backgroundColor: '#F7F9FC',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#E5EAF1',
    paddingHorizontal: 14,
    paddingTop: 11,
    paddingBottom: 11,
    fontSize: 14,
    color: '#111827',
  },
  composerSendButton: {
    width: 42,
    height: 42,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#0F9F74',
  },
  composerSendButtonDisabled: {
    backgroundColor: '#A8DCC8',
  },
});
