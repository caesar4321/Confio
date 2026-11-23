// Pagar (Cobrar for a business) on the screens opened from the drawer, so it
// stays one tap away without a tab bar. Here there is room for its name; on
// Inicio it is the composer's round button with the same icon.
import React from 'react';
import { Pressable, StyleSheet } from 'react-native';
import { Text } from '../components/common/AppText';
import { QrPayIcon, QrShowIcon } from '../components/QrPayIcon';
import { useAppDrawer } from './AppDrawer';
import { FLOATING_BOTTOM } from './useFloatingPrimaryInset';
import { usePrimaryAction } from './usePrimaryAction';
import { logHomeNav } from '../services/homeNavAnalytics';

// The screens opened from the drawer. On Inicio the composer has the button.
const FLOATING_TABS = new Set(['Invest', 'Comprar', 'Profile']);

export function FloatingPrimaryButton({ tab }: { tab: string }) {
  const primary = usePrimaryAction();
  const drawer = useAppDrawer();
  if (!primary || !FLOATING_TABS.has(tab) || drawer.isOpen) {
    return null;
  }
  const pay = primary.kind === 'pay';
  return (
    <Pressable
      onPress={() => { logHomeNav('floating', primary.kind); primary.onPress(); }}
      style={({ pressed }) => [styles.button, pressed && styles.pressed]}
      accessibilityRole="button"
      accessibilityLabel={pay ? 'Pagar con QR' : 'Cobrar'}
    >
      {pay ? <QrPayIcon size={22} color="#FFFFFF" /> : <QrShowIcon size={22} color="#FFFFFF" />}
      <Text style={styles.text}>{pay ? 'Pagar' : 'Cobrar'}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    position: 'absolute',
    bottom: FLOATING_BOTTOM,
    right: 16,
    height: 48,
    borderRadius: 24,
    paddingLeft: 14,
    paddingRight: 18,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#047857',
    shadowColor: '#065F46',
    shadowOpacity: 0.3,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 8,
  },
  pressed: { backgroundColor: '#065F46' },
  text: { fontSize: 16, fontWeight: '700', color: '#FFFFFF' },
});
