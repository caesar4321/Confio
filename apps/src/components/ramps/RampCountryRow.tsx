import React, { useState } from 'react';
import { Pressable, StyleProp, StyleSheet, View, ViewStyle } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../common/AppText';
import { CountryFlag } from '../CountryFlag';
import { RampCountrySheet } from '../RampCountrySheet';
import { colors } from '../../config/theme';
import { countryName } from '../../config/localRails';
import { useRampCountry } from '../../hooks/useRampCountry';
import { getCountryByIso } from '../../utils/countries';
import { getCurrencyForCountry } from '../../utils/currencyMapping';

// How a country's money is said, for "Recargar en pesos argentinos" (only
// where ramps operate; anywhere else the phrase is left out).
const CURRENCY_PHRASE: Record<string, string> = {
  AR: 'pesos argentinos', BO: 'bolivianos', BR: 'reales', CL: 'pesos chilenos', CO: 'pesos colombianos',
  MX: 'pesos mexicanos', PE: 'soles', PY: 'guaraníes', UY: 'pesos uruguayos', EC: 'dólares', US: 'dólares',
};
export const currencyPhrase = (iso: string) => CURRENCY_PHRASE[String(iso || '').toUpperCase()] || '';

const currencyCode = (iso: string) => {
  const country = getCountryByIso(iso);
  return country ? getCurrencyForCountry(country as any) : '';
};

/**
 * The country a top-up or withdrawal belongs to, changeable on every
 * Recargar/Retirar screen (Guardarian's included). The pick is the same saved
 * one TopUp uses (useRampCountry), so a Koywe country moves the user onto
 * Koywe's screen. `suggestion`: another country that works for them today
 * (their document's), offered as one tap.
 */
export const RampCountryRow = ({ verb, style, suggestion, onSuggestion }: {
  verb: 'Recargar' | 'Retirar';
  style?: StyleProp<ViewStyle>;
  suggestion?: string | null;
  onSuggestion?: () => void;
}) => {
  const { countryCode, railCountries, setRampCountry } = useRampCountry();
  const [visible, setVisible] = useState(false);
  if (!countryCode) return null;
  const code = currencyCode(countryCode);
  const lead = verb === 'Recargar' ? 'Recargas desde' : 'Retiras en';
  return (
    <View style={[styles.card, style]}>
      <Pressable style={({ pressed }) => [styles.row, pressed && styles.pressed]} onPress={() => setVisible(true)}
        accessibilityRole="button" accessibilityLabel={`${lead} ${countryName(countryCode)}. Cambiar país`}>
        <View style={styles.flagRing}>
          <CountryFlag iso={countryCode} size={30} />
        </View>
        <View style={styles.copy}>
          <Text style={styles.eyebrow}>{lead}</Text>
          <View style={styles.nameRow}>
            <Text style={styles.name} numberOfLines={1}>{countryName(countryCode)}</Text>
            {code && code !== 'USD' ? <Text style={styles.currency}>{code}</Text> : null}
          </View>
        </View>
        <View style={styles.change}>
          <Text style={styles.changeText}>Cambiar</Text>
          <Icon name="chevron-down" size={14} color={colors.successText} />
        </View>
      </Pressable>
      {suggestion && onSuggestion ? (
        <Pressable style={({ pressed }) => [styles.suggestion, pressed && styles.pressed]} onPress={onSuggestion}
          accessibilityRole="button">
          <CountryFlag iso={suggestion} size={20} />
          <View style={styles.copy}>
            <Text style={styles.suggestionTitle}>
              {verb} desde {countryName(suggestion)}
              {currencyPhrase(suggestion) ? ` en ${currencyPhrase(suggestion)}` : ''}
            </Text>
            <Text style={styles.suggestionText}>Tu documento verificado es de {countryName(suggestion)}.</Text>
          </View>
          <Icon name="arrow-right" size={16} color={colors.successText} />
        </Pressable>
      ) : null}
      <RampCountrySheet
        visible={visible}
        current={countryCode}
        railCountries={railCountries}
        onPick={setRampCountry}
        onClose={() => setVisible(false)}
        title={verb === 'Recargar' ? '¿Desde qué país vas a recargar?' : '¿A qué país vas a retirar?'}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    borderRadius: 18, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.primaryMuted,
    shadowColor: colors.primaryDark, shadowOpacity: 0.08, shadowRadius: 12, shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 14, paddingHorizontal: 16 },
  pressed: { opacity: 0.7 },
  flagRing: {
    width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.primarySoft, borderWidth: 1, borderColor: colors.primaryMuted,
  },
  copy: { flex: 1, gap: 1 },
  eyebrow: { fontSize: 12, color: colors.textSecondary },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  name: { flexShrink: 1, fontSize: 18, fontWeight: '700', color: colors.dark },
  currency: {
    fontSize: 11, fontWeight: '700', color: colors.successText, letterSpacing: 0.5,
    paddingHorizontal: 7, paddingVertical: 2, borderRadius: 6, backgroundColor: colors.primaryLight,
    overflow: 'hidden',
  },
  change: {
    flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: 999, backgroundColor: colors.primarySoft, borderWidth: 1, borderColor: colors.primaryMuted,
  },
  changeText: { fontSize: 13, fontWeight: '700', color: colors.successText },
  suggestion: {
    flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12, paddingHorizontal: 16,
    backgroundColor: colors.primarySoft, borderTopWidth: 1, borderTopColor: colors.primaryMuted,
    borderBottomLeftRadius: 17, borderBottomRightRadius: 17,
  },
  suggestionTitle: { fontSize: 14, fontWeight: '700', color: colors.successText },
  suggestionText: { fontSize: 12, color: colors.textSecondary },
});
