// The account home's Herencia card when nobody is named yet: the picture,
// one warm sentence and a clear way in. The whole card is ONE button.
import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../common/AppText';
import { HerenciaArt } from './HerenciaArt';
import { SA, cardShadow } from './tokens';

export const HERENCIA_INVITE_COPY = {
  title: 'Elige a tu beneficiario',
  body: 'Decide quién recibirá esta cuenta si algún día dejas de usarla. Mientras la uses, sigue siendo solo tuya.',
  action: 'Elegir beneficiario',
} as const;

export function HerenciaInvite({ onPress }: { onPress: () => void }) {
  const c = HERENCIA_INVITE_COPY;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.card, cardShadow, pressed && styles.pressed]}
      accessibilityRole="button"
      accessibilityLabel={`${c.title}. ${c.body}`}
      testID="home-beneficiary"
    >
      <View style={styles.top}>
        <HerenciaArt width={96} variant="onLight" />
        <View style={styles.text}>
          <Text style={styles.title}>{c.title}</Text>
          <Text style={styles.body}>{c.body}</Text>
        </View>
      </View>
      <View style={styles.action}>
        <Text style={styles.actionText}>{c.action}</Text>
        <Icon name="arrow-right" size={18} color={SA.onDeep} style={styles.actionIcon} />
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: SA.mint, borderRadius: 20, borderWidth: 1, borderColor: SA.mintLine, padding: 16,
  },
  pressed: { opacity: 0.85 },
  top: { flexDirection: 'row', alignItems: 'center' },
  text: { flex: 1, marginLeft: 12 },
  title: { fontSize: 17, lineHeight: 23, fontWeight: '700', color: SA.text },
  body: { fontSize: 14, lineHeight: 20, color: SA.muted, marginTop: 4 },
  action: {
    marginTop: 14, minHeight: 48, borderRadius: 14, backgroundColor: SA.deep,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16,
  },
  actionText: { fontSize: 16, fontWeight: '700', color: SA.onDeep },
  actionIcon: { marginLeft: 8 },
});
