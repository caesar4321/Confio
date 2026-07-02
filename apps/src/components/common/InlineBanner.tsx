import React, { useEffect, useRef } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Animated } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors, spacing, radius, fontSize } from '../../config/theme';

export type BannerVariant = 'error' | 'success' | 'warning' | 'info';

interface InlineBannerProps {
  message: string;
  variant?: BannerVariant;
  /** Called when the user dismisses, or after autoHideMs elapses. */
  onDismiss?: () => void;
  /** Auto-dismiss after this many ms (typical for success feedback). */
  autoHideMs?: number;
  style?: object;
}

/**
 * Inline feedback banner — use instead of Alert.alert for non-blocking
 * errors and confirmations so failures feel designed, not like crashes.
 * Reserve Alert for destructive confirmations.
 */
export const InlineBanner: React.FC<InlineBannerProps> = ({
  message,
  variant = 'error',
  onDismiss,
  autoHideMs,
  style,
}) => {
  const opacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(opacity, { toValue: 1, duration: 180, useNativeDriver: true }).start();
    if (autoHideMs && onDismiss) {
      const t = setTimeout(onDismiss, autoHideMs);
      return () => clearTimeout(t);
    }
  }, [message, autoHideMs, onDismiss, opacity]);

  const v = variantStyles[variant];

  return (
    <Animated.View
      style={[styles.container, { backgroundColor: v.bg, borderColor: v.border }, { opacity }, style]}
      accessibilityRole="alert"
    >
      <Icon name={v.icon} size={18} color={v.iconColor} />
      <Text style={[styles.message, { color: v.text }]}>{message}</Text>
      {onDismiss && (
        <TouchableOpacity
          onPress={onDismiss}
          hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
          accessibilityRole="button"
          accessibilityLabel="Cerrar aviso"
        >
          <Icon name="x" size={16} color={v.iconColor} />
        </TouchableOpacity>
      )}
    </Animated.View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    marginBottom: spacing.md,
  },
  message: {
    flex: 1,
    fontSize: fontSize.small,
    lineHeight: 20,
  },
});

const variantStyles: Record<
  BannerVariant,
  { bg: string; border: string; text: string; iconColor: string; icon: string }
> = {
  error: {
    bg: colors.error.background,
    border: colors.error.border,
    text: colors.error.text,
    iconColor: colors.error.icon,
    icon: 'alert-circle',
  },
  success: {
    bg: colors.successLight,
    border: colors.primaryMuted,
    text: colors.successText,
    iconColor: colors.successText,
    icon: 'check-circle',
  },
  warning: {
    bg: colors.warning.background,
    border: colors.warning.border,
    text: colors.warning.text,
    iconColor: colors.warning.icon,
    icon: 'alert-triangle',
  },
  info: {
    bg: colors.infoLight,
    border: colors.accentSoft,
    text: colors.accent,
    iconColor: colors.accent,
    icon: 'info',
  },
};
