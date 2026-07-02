import React from 'react';
import {
  TouchableOpacity,
  Text,
  ActivityIndicator,
  StyleSheet,
  ViewStyle,
  TextStyle,
} from 'react-native';
import { colors, spacing, radius, fontSize, fontWeight } from '../../config/theme';

export type ButtonVariant = 'primary' | 'secondary' | 'danger';

interface ButtonProps {
  title: string;
  onPress: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  loading?: boolean;
  /** Overrides the visible title for screen readers when the title alone lacks context. */
  accessibilityLabel?: string;
  icon?: React.ReactNode;
  style?: ViewStyle;
  textStyle?: TextStyle;
}

/**
 * Shared button primitive. Use instead of per-screen TouchableOpacity buttons
 * so color, radius, disabled/loading states, touch-target size, and
 * accessibility stay consistent app-wide.
 */
export const Button: React.FC<ButtonProps> = ({
  title,
  onPress,
  variant = 'primary',
  disabled = false,
  loading = false,
  accessibilityLabel,
  icon,
  style,
  textStyle,
}) => {
  const isInactive = disabled || loading;
  const variantStyle = variantStyles[variant];

  return (
    <TouchableOpacity
      style={[styles.base, variantStyle.container, isInactive && styles.disabled, style]}
      onPress={onPress}
      disabled={isInactive}
      activeOpacity={0.8}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel || title}
      accessibilityState={{ disabled: isInactive, busy: loading }}
    >
      {loading ? (
        <ActivityIndicator color={variantStyle.spinner} size="small" />
      ) : (
        <>
          {icon}
          <Text style={[styles.text, variantStyle.text, textStyle]}>{title}</Text>
        </>
      )}
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  base: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    gap: spacing.sm,
  },
  text: {
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
  },
  disabled: {
    opacity: 0.6,
  },
});

const variantStyles: Record<
  ButtonVariant,
  { container: ViewStyle; text: TextStyle; spinner: string }
> = {
  primary: {
    container: { backgroundColor: colors.primaryDark },
    text: { color: colors.white },
    spinner: colors.white,
  },
  secondary: {
    container: {
      backgroundColor: colors.background,
      borderWidth: 1,
      borderColor: colors.border,
    },
    text: { color: colors.text.primary },
    spinner: colors.text.primary,
  },
  danger: {
    container: { backgroundColor: colors.danger },
    text: { color: colors.white },
    spinner: colors.white,
  },
};
