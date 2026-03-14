import React from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

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
                  <Icon name="chevron-right" size={16} color="#C7CDD4" />
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
    color: '#475467',
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  sectionIntroMeta: {
    fontSize: 12,
    color: '#98A2B3',
    fontWeight: '600',
  },
  channelList: {
    paddingHorizontal: 14,
    paddingTop: 10,
  },
  channelCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 18,
    paddingHorizontal: 16,
    paddingVertical: 14,
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 1,
    borderWidth: 1,
    borderColor: '#EEF2F6',
  },
  channelCardUnread: {
    borderColor: '#E1E7EF',
    backgroundColor: '#FCFEFD',
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
    color: '#111111',
  },
  channelNameUnread: {
    color: '#0F172A',
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
    color: '#8A94A6',
    flex: 1,
  },
  channelTime: {
    fontSize: 11,
    color: '#AAAAAA',
  },
  channelTimeUnread: {
    color: '#667085',
    fontWeight: '500',
  },
  channelPreview: {
    fontSize: 12,
    color: '#667085',
  },
  channelPreviewUnread: {
    color: '#344054',
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
    color: '#FFFFFF',
  },
});
