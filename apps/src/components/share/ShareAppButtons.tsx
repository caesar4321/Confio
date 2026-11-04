// The two small "send straight to" pills: WhatsApp and Instagram.
import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import MaterialCommunityIcons from 'react-native-vector-icons/MaterialCommunityIcons';

import { Text } from '../common/AppText';
import { colors } from '../../config/theme';

export type ShareApp = 'whatsapp' | 'instagram';

const APPS: { app: ShareApp; icon: string; label: string; color: string }[] = [
  { app: 'whatsapp', icon: 'whatsapp', label: 'WhatsApp', color: '#25D366' },
  { app: 'instagram', icon: 'instagram', label: 'Instagram', color: '#E1306C' },
];

export function ShareAppButtons({ onPress, busy, disabled, label = 'O envíalo a', testIDPrefix }: {
  onPress: (app: ShareApp) => void;
  /** The app being prepared, or any other in-progress action (all wait). */
  busy: string | null;
  disabled?: boolean;
  label?: string;
  testIDPrefix: string;
}) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>{label}</Text>
      {APPS.map(({ app, icon, label: name, color }) => (
        <Pressable
          key={app}
          onPress={() => onPress(app)}
          disabled={disabled || busy !== null}
          style={({ pressed }) => [styles.button, (pressed || busy === app) && styles.pressed,
            (disabled || (busy !== null && busy !== app)) && styles.disabled]}
          accessibilityRole="button"
          accessibilityLabel={`Compartir en ${name}`}
          testID={`${testIDPrefix}-${app}`}
        >
          {busy === app
            ? <ActivityIndicator size="small" color={color} />
            : <MaterialCommunityIcons name={icon} size={20} color={color} />}
          <Text style={styles.buttonText}>{name}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  label: { fontSize: 13, color: colors.text.secondary },
  button: {
    flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 7,
    borderRadius: 999, borderWidth: 1, borderColor: colors.borderMedium, backgroundColor: colors.white,
  },
  buttonText: { fontSize: 13, fontWeight: '600', color: colors.dark },
  pressed: { backgroundColor: colors.surface },
  disabled: { opacity: 0.5 },
});
