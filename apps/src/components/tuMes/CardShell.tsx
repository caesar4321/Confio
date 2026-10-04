// Shared chrome for the Tu mes insight cards (tu-mes-insights.md §2, design
// review 13A/14A/18A): white card on colors.surface, hairline border, no
// shadow; title row = bare 18pt glyph + 17pt semibold title.
import React from 'react';
import { StyleSheet, useWindowDimensions, View, type ViewStyle } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../common/AppText';
import { colors } from '../../config/theme';

/** Font growth on Tu mes cards (design review 21A). */
export const CARD_FONT_MULTIPLIER = 1.6;

export function CardShell({ children, style, testID }: { children: React.ReactNode; style?: ViewStyle; testID?: string }) {
  const { width } = useWindowDimensions();
  return (
    <View style={[styles.card, { padding: width < 360 ? 16 : 20 }, style]} testID={testID}>
      {children}
    </View>
  );
}

export function CardTitle({ icon, title }: { icon: string; title: string }) {
  return (
    <View style={styles.titleRow} accessible={false}>
      <Icon name={icon} size={18} color={colors.flowIn.textSmall} importantForAccessibility="no" />
      <Text style={styles.title} maxFontSizeMultiplier={CARD_FONT_MULTIPLIER} accessibilityRole="header">{title}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.white,
    borderRadius: 20,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    marginTop: 12,
  },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 16 },
  title: { fontSize: 17, lineHeight: 22, fontWeight: '600', color: colors.textFlat, flexShrink: 1 },
});
