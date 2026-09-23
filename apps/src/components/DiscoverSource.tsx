import React from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';

const OFFICIAL_EXPLAINER =
  'Esta fuente es un canal de Confío o una organización cuya identidad legal y ' +
  'titularidad de la cuenta verificó Confío. Si esa verificación deja de estar vigente, ' +
  'la insignia desaparece.';

type Props = {
  name?: string;
  isOfficial?: boolean;
  size?: 'card' | 'detail';
};

/** Who published a Descubrir post, with the Oficial badge when verified. */
export function DiscoverSource({ name, isOfficial = false, size = 'card' }: Props) {
  if (!name) return null;
  return (
    <View style={styles.row}>
      <Text style={[styles.name, size === 'detail' && styles.nameDetail]} numberOfLines={1}>
        {name}
      </Text>
      {isOfficial && (
        <Pressable
          onPress={() => Alert.alert('Fuente oficial', OFFICIAL_EXPLAINER)}
          style={styles.badge}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel="Fuente oficial verificada por Confío. Toca para saber más."
        >
          <Icon name="check-circle" size={11} color={colors.primaryDeep} />
          <Text style={styles.badgeText}>Oficial</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 8,
  },
  name: {
    flexShrink: 1,
    fontSize: 13,
    fontWeight: '700',
    color: colors.dark,
  },
  nameDetail: {
    fontSize: 14,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    borderRadius: 999,
    paddingHorizontal: 7,
    paddingVertical: 2,
    backgroundColor: colors.primarySoft,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.primaryDeep,
  },
});
