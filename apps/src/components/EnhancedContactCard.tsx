import React, { useRef, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Animated,
  Platform,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';

interface EnhancedContactCardProps {
  contact: {
    id: string;
    name: string;
    avatar: string;
    phone: string;
    isOnConfio?: boolean;
    lastInteraction?: Date;
  };
  onPress: () => void;
  onSendPress: () => void;
  onInvitePress: () => void;
  isRecent?: boolean;
}

export const EnhancedContactCard: React.FC<EnhancedContactCardProps> = React.memo(({
  contact,
  onPress,
  onSendPress,
  onInvitePress,
  isRecent = false,
}) => {
  const scaleAnim = useRef(new Animated.Value(1)).current;
  const checkmarkScale = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (contact.isOnConfio) {
      // Animate checkmark badge appearance
      Animated.spring(checkmarkScale, {
        toValue: 1,
        tension: 50,
        friction: 7,
        useNativeDriver: true,
      }).start();
    }
  }, [contact.isOnConfio]);

  const handlePressIn = () => {
    Animated.spring(scaleAnim, {
      toValue: 0.95,
      useNativeDriver: true,
    }).start();
  };

  const handlePressOut = () => {
    Animated.spring(scaleAnim, {
      toValue: 1,
      friction: 3,
      tension: 40,
      useNativeDriver: true,
    }).start();
  };

  return (
    <Animated.View style={[styles.container, { transform: [{ scale: scaleAnim }] }]}>
      <TouchableOpacity
        style={styles.card}
        onPress={onPress}
        onPressIn={handlePressIn}
        onPressOut={handlePressOut}
        activeOpacity={0.7}
      >
        <View style={styles.contentContainer}>
          {/* Avatar with badge */}
          <View style={styles.avatarSection}>
            {contact.isOnConfio ? (
              <View style={styles.avatarGradient}>
                <Svg height="100%" width="100%" style={StyleSheet.absoluteFillObject}>
                  <Defs>
                    <LinearGradient id={`avatar-${contact.id}`} x1="0" y1="0" x2="0" y2="1">
                      <Stop offset="0" stopColor="#34D399" />
                      <Stop offset="1" stopColor="#10B981" />
                    </LinearGradient>
                  </Defs>
                  <Rect width="100%" height="100%" fill={`url(#avatar-${contact.id})`} rx="24" />
                </Svg>
                <Text style={styles.avatarTextWhite}>{contact.avatar}</Text>
              </View>
            ) : (
              <View style={styles.avatarDefault}>
                <Text style={styles.avatarText}>{contact.avatar}</Text>
              </View>
            )}
            
            {/* Animated checkmark badge */}
            {contact.isOnConfio && (
              <Animated.View
                style={[
                  styles.badge,
                  {
                    transform: [{ scale: checkmarkScale }],
                  },
                ]}
              >
                <Icon name="check" size={10} color="#fff" />
              </Animated.View>
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
              contact.isOnConfio ? onSendPress() : onInvitePress();
            }}
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
    </Animated.View>
  );
});

EnhancedContactCard.displayName = 'EnhancedContactCard';

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    paddingVertical: 4,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.05,
        shadowRadius: 8,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  contentContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
  },
  avatarSection: {
    position: 'relative',
    marginRight: 12,
  },
  avatarGradient: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
  },
  avatarDefault: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#F3F4F6',
    justifyContent: 'center',
    alignItems: 'center',
  },
  avatarText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#6B7280',
  },
  avatarTextWhite: {
    fontSize: 18,
    fontWeight: '600',
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