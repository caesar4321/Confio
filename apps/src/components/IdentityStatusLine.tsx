import React from 'react';
import { StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from './common/AppText';
import { colors } from '../config/theme';

/**
 * Whether Confío checked this person's ID, said in words. Not the rosette
 * (VerifiedBadge): that one marks Confío's own official accounts.
 */
export const IdentityStatusLine = ({ verified, explain = true }: { verified: boolean; explain?: boolean }) => (
  <View style={styles.row} accessibilityLabel={verified ? 'Identidad verificada por Confío' : 'Identidad sin verificar'}>
    <Icon name={verified ? 'shield' : 'shield-off'} size={13} color={verified ? colors.flowIn.textSmall : colors.muted} />
    <Text style={[styles.text, verified ? styles.verified : styles.unverified]}>
      {verified
        ? (explain ? 'Identidad verificada · Confío revisó su documento' : 'Identidad verificada')
        : 'Identidad sin verificar'}
    </Text>
  </View>
);

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 5, maxWidth: '100%' },
  text: { flexShrink: 1, fontSize: 12, lineHeight: 16 },
  verified: { color: colors.flowIn.textSmall, fontWeight: '600' },
  unverified: { color: colors.textSecondary },
});
