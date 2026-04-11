import React, { useEffect, useState } from 'react';
import { ActivityIndicator, BackHandler, Platform, StyleSheet, Text, View } from 'react-native';
import { useLazyQuery, useMutation, useQuery } from '@apollo/client';

import { MessageInboxList } from './MessageInboxList';
import { MessageChannelThread } from './MessageChannelThread';
import { Channel, ScreenState } from './MessageInboxShared';
import { GET_MESSAGE_CHANNEL_THREAD, GET_MESSAGE_INBOX, GET_MESSAGE_INBOX_UNREAD_COUNT } from '../apollo/queries';
import {
  MARK_MESSAGE_CHANNEL_SEEN,
  REACT_TO_MESSAGE_CONTENT,
  SEND_SUPPORT_MESSAGE,
  UPDATE_MESSAGE_CHANNEL_MUTE,
} from '../apollo/mutations';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';

type MessageInboxContentProps = {
  onScreenStateChange?: (state: ScreenState) => void;
  initialChannelId?: Channel['id'];
};

const SUPPORT_POLL_INTERVAL_MS = 5000;

type InboxMessageDto = {
  id: string;
  type: string;
  isPinned?: boolean | null;
  occurredAt?: string | null;
  tag?: string | null;
  title?: string | null;
  body?: string | null;
  text?: string | null;
  time: string;
  link?: string | null;
  platforms?: string[] | null;
  platformLinks?: Array<{
    platform: 'TikTok' | 'Instagram' | 'YouTube';
    url: string;
  }> | null;
  imageUrl?: string | null;
  reactionSummary?: Array<{
    emoji: string;
    count: number;
  }> | null;
  viewerReaction?: string | null;
  canReact?: boolean | null;
  senderType?: 'USER' | 'AGENT' | 'SYSTEM' | null;
  senderName?: string | null;
};

type InboxChannelDto = {
  id: string;
  name: string;
  subtitle: string;
  preview: string;
  time: string;
  unreadCount: number;
  isMuted: boolean;
  messages: InboxMessageDto[];
};

function normalizeChannelId(id: string): Channel['id'] {
  if (id === 'confio-news') {
    return 'confio';
  }
  if (id === 'julian' || id === 'soporte' || id === 'confio') {
    return id;
  }
  throw new Error(`Unsupported message channel id: ${id}`);
}

function toServerChannelId(channel: Pick<Channel, 'id' | 'serverId'>): string {
  if (channel.serverId) {
    return channel.serverId;
  }
  if (channel.id === 'confio') {
    return 'confio-news';
  }
  return channel.id;
}

function getMessagePreview(message: InboxMessageDto): string {
  if (message.type === 'video') {
    return message.title || '';
  }
  if (message.type === 'news') {
    return message.title || message.body || '';
  }
  return message.text || message.body || '';
}

function mapInboxMessage(message: InboxMessageDto) {
  if (message.type === 'video') {
    return {
      id: Number(message.id),
      type: 'video' as const,
      isPinned: message.isPinned ?? false,
      occurredAt: message.occurredAt || '',
      platform: (message.platforms?.[0] || 'TikTok') as string,
      platforms: (message.platforms || []) as Array<'TikTok' | 'Instagram' | 'YouTube'>,
      platformLinks: (message.platformLinks || []).filter((item) => item.url),
      reactionSummary: message.reactionSummary || [],
      viewerReaction: message.viewerReaction,
      canReact: message.canReact ?? true,
      title: message.title || '',
      time: message.time,
      imageUrl: message.imageUrl || '',
    };
  }

  if (message.type === 'news') {
    return {
      id: Number(message.id),
      type: 'news' as const,
      isPinned: message.isPinned ?? false,
      occurredAt: message.occurredAt || '',
      reactionSummary: message.reactionSummary || [],
      viewerReaction: message.viewerReaction,
      canReact: message.canReact ?? true,
      tag: message.tag || '',
      title: message.title || '',
      body: message.body || '',
      time: message.time,
      imageUrl: message.imageUrl || '',
    };
  }

  if (message.type === 'support') {
    return {
      id: Number(message.id),
      type: 'support' as const,
      isPinned: false,
      occurredAt: message.occurredAt || '',
      reactionSummary: message.reactionSummary || [],
      viewerReaction: message.viewerReaction,
      canReact: message.canReact ?? false,
      senderType: message.senderType,
      senderName: message.senderName,
      text: message.text || message.body || '',
      time: message.time,
    };
  }

  return {
    id: Number(message.id),
    type: 'text' as const,
    isPinned: message.isPinned ?? false,
    occurredAt: message.occurredAt || '',
    tag: message.tag || '',
    reactionSummary: message.reactionSummary || [],
    viewerReaction: message.viewerReaction,
    canReact: message.canReact ?? true,
    text: message.text || message.body || '',
    time: message.time,
    imageUrl: message.imageUrl || '',
  };
}

function mapChannels(channels?: InboxChannelDto[]): Channel[] {
  if (!channels?.length) {
    return [];
  }

  return channels.flatMap((channel) => {
    try {
      const latestUnpinnedMessage = channel.messages.find((message) => !message.isPinned);
      const preview = latestUnpinnedMessage
        ? getMessagePreview(latestUnpinnedMessage)
        : channel.preview;
      const time = latestUnpinnedMessage?.time || channel.time;

      return {
        id: normalizeChannelId(channel.id),
        serverId: channel.id,
        name: channel.name,
        subtitle: channel.subtitle,
        preview,
        time,
        isMuted: channel.isMuted,
        messages: channel.messages.map(mapInboxMessage),
      };
    } catch (error) {
      return [];
    }
  });
}

export function MessageInboxContent({ onScreenStateChange, initialChannelId }: MessageInboxContentProps) {
  const { isAuthenticated, isLoading: authLoading, accountContextTick } = useAuth();
  const { activeAccount } = useAccount();
  const [screen, setScreen] = useState<ScreenState>('inbox');
  const [activeChannel, setActiveChannel] = useState<Channel | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [unreadCounts, setUnreadCounts] = useState<Record<Channel['id'], number>>({
    julian: 0,
    confio: 0,
    soporte: 0,
  });
  const [isRefreshing, setIsRefreshing] = useState(false);
  const canQuery = isAuthenticated && !authLoading;
  const contextKey = activeAccount?.id || 'no-account';
  const shouldPollInbox =
    canQuery && (
      screen === 'inbox'
      || (screen === 'channel' && activeChannel?.id === 'soporte')
    );

  const { data, loading, refetch } = useQuery(GET_MESSAGE_INBOX, {
    variables: { contextKey },
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'cache-first',
    pollInterval: shouldPollInbox ? SUPPORT_POLL_INTERVAL_MS : 0,
    skip: !canQuery,
  });
  const [markChannelSeen] = useMutation(MARK_MESSAGE_CHANNEL_SEEN, {
    refetchQueries: [{ query: GET_MESSAGE_INBOX_UNREAD_COUNT, variables: { contextKey } }],
  });
  const [reactToMessageContent] = useMutation(REACT_TO_MESSAGE_CONTENT);
  const [updateChannelMute] = useMutation(UPDATE_MESSAGE_CHANNEL_MUTE);
  const [sendSupportMessage] = useMutation(SEND_SUPPORT_MESSAGE);
  const [hasMoreThreadMessages, setHasMoreThreadMessages] = useState(false);
  const [loadThreadPage, { loading: isLoadingMoreThread }] = useLazyQuery(GET_MESSAGE_CHANNEL_THREAD, {
    fetchPolicy: 'network-only',
  });

  const handleRefresh = async () => {
    if (!canQuery) {
      return;
    }
    setIsRefreshing(true);
    try {
      await refetch();
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    onScreenStateChange?.(screen);
  }, [onScreenStateChange, screen]);

  useEffect(() => {
    if (!canQuery) {
      return;
    }
    refetch();
  }, [accountContextTick, canQuery, refetch, contextKey]);

  useEffect(() => {
    const nextChannels = mapChannels(data?.messageInbox?.channels);
    if (!nextChannels.length) {
      return;
    }

    setChannels(nextChannels);
    setUnreadCounts({
      julian: data?.messageInbox?.channels?.find((channel: InboxChannelDto) => normalizeChannelId(channel.id) === 'julian')?.unreadCount || 0,
      confio: data?.messageInbox?.channels?.find((channel: InboxChannelDto) => normalizeChannelId(channel.id) === 'confio')?.unreadCount || 0,
      soporte: data?.messageInbox?.channels?.find((channel: InboxChannelDto) => normalizeChannelId(channel.id) === 'soporte')?.unreadCount || 0,
    });
  }, [data]);

  useEffect(() => {
    if (!activeChannel) {
      return;
    }
    const nextChannel = channels.find((channel) => channel.serverId === activeChannel.serverId);
    if (nextChannel) {
      setActiveChannel(nextChannel);
    }
  }, [channels, activeChannel]);

  useEffect(() => {
    if (!initialChannelId || activeChannel || screen === 'channel' || channels.length === 0) {
      return;
    }
    const channel = channels.find((item) => item.id === initialChannelId);
    if (channel) {
      openChannel(channel);
    }
  }, [initialChannelId, channels, activeChannel, screen]);

  useEffect(() => {
    if (Platform.OS !== 'android' || screen !== 'channel') {
      return;
    }

    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      setActiveChannel(null);
      setScreen('inbox');
      return true;
    });

    return () => subscription.remove();
  }, [screen]);

  const openChannel = (channel: Channel) => {
    setActiveChannel(channel);
    setUnreadCounts((prev) => ({ ...prev, [channel.id]: 0 }));
    setChannels((prev) =>
      prev.map((item) => (item.serverId === channel.serverId ? { ...item, time: channel.time } : item))
    );
    setScreen('channel');
    setHasMoreThreadMessages(channel.messages.length >= getThreadPageSize(channel.id));
    void markChannelSeen({ variables: { channelId: toServerChannelId(channel) } }).catch((error) => {    });
  };

  const closeChannel = () => {
    setActiveChannel(null);
    setScreen('inbox');
    setHasMoreThreadMessages(false);
  };

  const getThreadPageSize = (channelId: Channel['id']) => (channelId === 'soporte' ? 50 : 20);

  const handleReactToMessage = async (messageId: number, emoji: string) => {
    const response = await reactToMessageContent({
      variables: {
        contentItemId: String(messageId),
        emoji,
      },
    });

    const payload = response.data?.reactToMessageContent;
    if (!payload?.success) {
      return;
    }

    setChannels((prev) =>
      prev.map((channel) => ({
        ...channel,
        messages: channel.messages.map((message) =>
          message.id === Number(payload.contentItemId)
            ? {
                ...message,
                reactionSummary: payload.reactionSummary || [],
                viewerReaction: payload.viewerReaction || null,
              }
            : message
        ),
      }))
    );
  };

  const handleToggleChannelMute = async (channel: Channel) => {
    const response = await updateChannelMute({
      variables: {
        channelId: toServerChannelId(channel),
        isMuted: !channel.isMuted,
      },
    });

    const payload = response.data?.updateMessageChannelMute;
    if (!payload?.success) {
      return;
    }

    setChannels((prev) =>
      prev.map((item) =>
        item.serverId === payload.channelId
          ? { ...item, isMuted: payload.isMuted }
          : item
      )
    );
  };

  const handleSendSupportMessage = async (body: string) => {
    const response = await sendSupportMessage({
      variables: { body },
    });

    const payload = response.data?.sendSupportMessage;
    if (!payload?.success) {
      return;
    }

    const nextMessage = payload.message;
    setChannels((prev) =>
      prev.map((channel) =>
        channel.id !== 'soporte'
          ? channel
          : {
              ...channel,
              preview: nextMessage.text || nextMessage.body || '',
              time: nextMessage.time,
              messages: [
                ...channel.messages,
                {
                  id: Number(nextMessage.id),
                  type: 'support' as const,
                  reactionSummary: [],
                  viewerReaction: null,
                  canReact: false,
                  senderType: nextMessage.senderType,
                  senderName: nextMessage.senderName,
                  text: nextMessage.text || nextMessage.body || '',
                  time: nextMessage.time,
                },
              ],
            }
      )
    );
  };

  const handleLoadOlderMessages = async () => {
    if (!activeChannel || isLoadingMoreThread || !hasMoreThreadMessages) {
      return;
    }

    const response = await loadThreadPage({
      variables: {
        channelId: activeChannel.id,
        offset: activeChannel.messages.length,
        limit: getThreadPageSize(activeChannel.id),
        contextKey,
      },
    });

    const page = response.data?.messageChannelThread;
    const nextMessages = (page?.channel?.messages || []).map(mapInboxMessage);
    const shouldPrepend = activeChannel.id === 'soporte';

    setChannels((prev) =>
      prev.map((channel) =>
        channel.serverId !== activeChannel.serverId
          ? channel
          : {
              ...channel,
              messages: shouldPrepend
                ? [...nextMessages, ...channel.messages]
                : [...channel.messages, ...nextMessages],
            }
      )
    );
    setHasMoreThreadMessages(Boolean(page?.hasMore));
  };

  if (screen === 'channel' && activeChannel) {
    return (
      <MessageChannelThread
        channel={activeChannel}
        onBack={closeChannel}
        onReact={handleReactToMessage}
        onToggleMute={handleToggleChannelMute}
        onSendSupportMessage={handleSendSupportMessage}
        hasMore={hasMoreThreadMessages}
        loadingMore={isLoadingMoreThread}
        onLoadMore={() => {
          void handleLoadOlderMessages();
        }}
        loadMorePosition={activeChannel.id === 'soporte' ? 'top' : 'bottom'}
        refreshing={isRefreshing}
        onRefresh={() => {
          void handleRefresh();
        }}
      />
    );
  }

  if (loading && !data?.messageInbox?.channels?.length) {
    return (
      <View style={styles.stateWrap}>
        <ActivityIndicator size="small" color="#34d399" />
        <Text style={styles.stateText}>Cargando mensajes...</Text>
      </View>
    );
  }

  if (canQuery && !loading && channels.length === 0) {
    return (
      <View style={styles.stateWrap}>
        <Text style={styles.stateTitle}>No hay mensajes todavía</Text>
        <Text style={styles.stateText}>Cuando haya novedades, aparecerán aquí.</Text>
      </View>
    );
  }

  return (
    <MessageInboxList
      channels={channels}
      unreadCounts={unreadCounts}
      onOpenChannel={openChannel}
      refreshing={isRefreshing}
      onRefresh={() => {
        void handleRefresh();
      }}
    />
  );
}

const styles = StyleSheet.create({
  stateWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
    paddingVertical: 48,
  },
  stateTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#111827',
    marginBottom: 6,
  },
  stateText: {
    marginTop: 8,
    fontSize: 13,
    lineHeight: 19,
    color: '#6B7280',
    textAlign: 'center',
  },
});

export default MessageInboxContent;
