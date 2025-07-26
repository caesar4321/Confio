import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Platform,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

interface SimpleContactCardProps {
  contact: {
    id: string;
    name: string;
    avatar: string;
    phone: string;
    isOnConfio?: boolean;
  };
  onPress: () => void;
  onActionPress: () => void;
  isRecent?: boolean;
}

export const SimpleContactCard = React.memo(({
  contact,
  onPress,
  onActionPress,
  isRecent = false,
}: SimpleContactCardProps) => {
  return (
    <TouchableOpacity
      style={styles.container}
      onPress={onPress}
      activeOpacity={0.7}
    >
      <View style={styles.contentContainer}>
        {/* Avatar */}
        <View style={[
          styles.avatar,
          contact.isOnConfio && styles.avatarConfio
        ]}>
          <Text style={[
            styles.avatarText,
            contact.isOnConfio && styles.avatarTextWhite
          ]}>
            {contact.avatar}
          </Text>
          {contact.isOnConfio && (
            <View style={styles.badge}>
              <Icon name="check" size={10} color="#fff" />
            </View>
          )}
        </View>

        {/* Contact info */}
        <View style={styles.infoSection}>
          <Text style={styles.name} numberOfLines={1}>
            {contact.name}
          </Text>
          <View style={styles.metaRow}>
            <Text style={styles.phone} numberOfLines={1}>
              {contact.phone}
            </Text>
            {isRecent && (
              <View style={styles.recentBadge}>
                <Icon name="clock" size={10} color="#6B7280" />
                <Text style={styles.recentText}>Reciente</Text>
              </View>
            )}
          </View>
        </View>

        {/* Action button */}
        <TouchableOpacity
          style={[
            styles.actionButton,
            contact.isOnConfio ? styles.sendButton : styles.inviteButton,
          ]}
          onPress={(e) => {
            e.stopPropagation();
            onActionPress();
          }}
          hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
        >
          {contact.isOnConfio ? (
            <Icon name="send" size={18} color="#fff" />
          ) : (
            <>
              <Icon name="gift" size={16} color="#fff" />
              <Text style={styles.inviteText}>Invitar</Text>
            </>
          )}
        </TouchableOpacity>
      </View>
    </TouchableOpacity>
  );
});

SimpleContactCard.displayName = 'SimpleContactCard';

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    paddingVertical: 4,
  },
  contentContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 12,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 1 },
        shadowOpacity: 0.05,
        shadowRadius: 3,
      },
      android: {
        elevation: 1,
      },
    }),
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#F3F4F6',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  avatarConfio: {
    backgroundColor: '#34D399',
  },
  avatarText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#6B7280',
  },
  avatarTextWhite: {
    color: '#FFFFFF',
  },
  badge: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: '#10B981',
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  infoSection: {
    flex: 1,
    marginRight: 12,
  },
  name: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 2,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  phone: {
    fontSize: 14,
    color: '#6B7280',
    flex: 1,
  },
  recentBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F3F4F6',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    gap: 4,
  },
  recentText: {
    fontSize: 11,
    color: '#6B7280',
    fontWeight: '500',
  },
  actionButton: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  sendButton: {
    backgroundColor: '#34D399',
  },
  inviteButton: {
    backgroundColor: '#8B5CF6',
  },
  inviteText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
});