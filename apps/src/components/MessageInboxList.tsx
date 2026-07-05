import React from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';

import { Channel, channelMeta, ChannelAvatar, tealGreen } from './MessageInboxShared';

type MessageInboxListProps = {
  channels: Channel[];
  unreadCounts: Record<Channel['id'], number>;
  onOpenChannel: (channel: Channel) => void;
  refreshing?: boolean;
  onRefresh?: () => void;
};

export function MessageInboxList({
  channels,
  unreadCounts,
  onOpenChannel,
  refreshing = false,
  onRefresh,
}: MessageInboxListProps) {
  return (
    <ScrollView
      contentContainerStyle={styles.inboxContent}
      refreshControl={
        onRefresh ? (
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={tealGreen} />
        ) : undefined
      }
    >
      <View style={styles.section}>
        <View style={styles.sectionIntroRow}>
          <Text style={styles.sectionIntroTitle}>Bandeja principal</Text>
          <Text style={styles.sectionIntroMeta}>{channels.length} canales</Text>
        </View>

        <View style={styles.channelList}>
          {channels.map((channel) => {
            const unread = unreadCounts[channel.id];
            const meta = channelMeta[channel.id];

            return (
              <Pressable
                key={channel.serverId}
                onPress={() => onOpenChannel(channel)}
                style={[styles.channelCard, unread > 0 && styles.channelCardUnread]}
              >
                <ChannelAvatar channel={channel} />

                <View style={styles.channelBody}>
                  <View style={styles.channelTopRow}>
                    <Text style={[styles.channelName, unread > 0 && styles.channelNameUnread]}>
                      {channel.name}
                    </Text>
                    <Text style={[styles.channelTime, unread > 0 && styles.channelTimeUnread]}>
                      {channel.time}
                    </Text>
                  </View>

                  <View style={styles.channelMetaRow}>
                    <View style={[styles.channelBadge, { backgroundColor: meta.badgeBackground }]}>
                      <Text style={[styles.channelBadgeText, { color: meta.badgeColor }]}>
                        {meta.badge}
                      </Text>
                    </View>
                    <Text style={styles.channelSubtitle} numberOfLines={1}>
                      {channel.subtitle}
                    </Text>
                  </View>

                  <Text
                    style={[styles.channelPreview, unread > 0 && styles.channelPreviewUnread]}
                    numberOfLines={1}
                  >
                    {channel.preview}
                  </Text>
                </View>

                <View style={styles.channelTrailing}>
                  {unread > 0 ? (
                    <View style={styles.channelUnreadBadge}>
                      <Text style={styles.channelUnreadText}>{unread}</Text>
                    </View>
                  ) : null}
                  <Icon name="chevron-right" size={16} color={colors.text.light} />
                </View>
              </Pressable>
            );
          })}
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  inboxContent: {
    paddingBottom: 28,
  },
  section: {
    paddingTop: 12,
  },
  sectionIntroRow: {
    marginHorizontal: 14,
    marginBottom: 4,
    paddingHorizontal: 2,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  sectionIntroTitle: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.text.secondary,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  sectionIntroMeta: {
    fontSize: 12,
    color: colors.text.light,
    fontWeight: '600',
  },
  channelList: {
    paddingHorizontal: 14,
    paddingTop: 10,
  },
  channelCard: {
    backgroundColor: colors.white,
    borderRadius: 18,
    paddingHorizontal: 16,
    paddingVertical: 14,
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
    borderWidth: 1,
    borderColor: colors.border,
  },
  channelCardUnread: {
    borderColor: colors.primaryLight,
    backgroundColor: colors.primarySoft,
  },
  channelBody: {
    flex: 1,
  },
  channelTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  channelName: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.text.primary,
  },
  channelNameUnread: {
    color: colors.text.primary,
  },
  channelMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 5,
  },
  channelBadge: {
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  channelBadgeText: {
    fontSize: 10,
    fontWeight: '700',
  },
  channelSubtitle: {
    fontSize: 11,
    color: colors.text.light,
    flex: 1,
  },
  channelTime: {
    fontSize: 11,
    color: colors.text.light,
  },
  channelTimeUnread: {
    color: colors.text.secondary,
    fontWeight: '500',
  },
  channelPreview: {
    fontSize: 12,
    color: colors.text.secondary,
  },
  channelPreviewUnread: {
    color: colors.text.primary,
    fontWeight: '400',
  },
  channelTrailing: {
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 10,
  },
  channelUnreadBadge: {
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: tealGreen,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
    marginLeft: 8,
  },
  channelUnreadText: {
    fontSize: 10,
    fontWeight: '700',
    color: colors.white,
  },
});
