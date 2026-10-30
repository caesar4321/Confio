import React, { useState } from 'react';
import { StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text, TextInput } from '../common/AppText';
import { CountryFlag } from '../CountryFlag';
import { RampCountryPicker } from './RampCountryPicker';
import { colors } from '../../config/theme';
import { Country, countries, getCountryByIso } from '../../utils/countries';

const MIN_DIGITS = 6;

// A number can't say which country of a shared code it belongs to: show the
// main one, not the first alphabetically (+1 was Anguila).
const SHARED_CODE_DEFAULT: Record<string, string> = {
  '+1': 'US', '+7': 'RU', '+44': 'GB', '+47': 'NO', '+61': 'AU', '+212': 'MA', '+262': 'RE', '+590': 'GP', '+599': 'CW',
};

const PROMISES = [
  { icon: 'bell-off', text: 'Sin códigos por SMS: no te enviaremos nada para confirmarlo.' },
  { icon: 'eye-off', text: 'Otros usuarios no lo ven y no sirve para encontrarte.' },
  { icon: 'shield', text: 'Solo lo compartimos con el proveedor de tus recargas, retiros o cuenta local.' },
];

/** A trunk 0 ("0412…") is dialled at home, never after a calling code; a
 *  pasted or autofilled "+591…" already carries its own. */
export const internationalPhone = (country: Country | undefined, number: string): string => {
  const typed = number.trim();
  if (typed.startsWith('+')) {
    const full = typed.replace(/\D/g, '');
    return full.length > MIN_DIGITS ? `+${full}` : '';
  }
  const digits = typed.replace(/\D/g, '').replace(/^0+/, '');
  return country && digits.length >= MIN_DIGITS ? `${country[1]}${digits}` : '';
};

/** Splits a saved "+59171234567" back into its country and local digits. */
export const splitPhone = (saved: string, homeIso?: string | null) => {
  const home = homeIso ? getCountryByIso(homeIso) : undefined;
  const matches = countries
    .filter(country => saved.startsWith(String(country[1])))
    .sort((a, b) => String(b[1]).length - String(a[1]).length);
  const longest = matches[0];
  const sharing = matches.filter(country => country[1] === longest?.[1]);
  const country = sharing.find(option => option[2] === home?.[2])
    || sharing.find(option => option[2] === SHARED_CODE_DEFAULT[String(longest?.[1])])
    || longest || home;
  return { country, number: longest ? saved.slice(String(longest[1]).length) : '' };
};

/** The contact number providers get; it never changes a verified phone. */
export const RampPhoneField = ({ country, number, onCountry, onNumber }: {
  country?: Country;
  number: string;
  onCountry: (country: Country) => void;
  onNumber: (number: string) => void;
}) => {
  const [picking, setPicking] = useState(false);
  const international = internationalPhone(country, number);
  return (
    <View>
      <View style={styles.inputRow}>
        <TouchableOpacity
          style={styles.codeChip}
          onPress={() => setPicking(true)}
          accessibilityRole="button"
          accessibilityLabel={`Código de país ${country?.[1] || ''}. Cambiar`}
        >
          {country ? <CountryFlag iso={String(country[2])} size={22} /> : <Icon name="globe" size={18} color={colors.successText} />}
          <Text style={styles.code}>{country?.[1] || 'País'}</Text>
          <Icon name="chevron-down" size={14} color={colors.successText} />
        </TouchableOpacity>
        <TextInput
          style={styles.input}
          value={number}
          onChangeText={onNumber}
          placeholder="Número"
          placeholderTextColor={colors.textSecondary}
          keyboardType="phone-pad"
          textContentType="telephoneNumber"
          autoComplete="tel"
          maxLength={18}
          accessibilityLabel="Tu número de celular"
        />
      </View>
      <Text style={styles.preview}>
        {international ? `Lo guardaremos como ${international}` : 'Escribe un número que uses y que sea tuyo.'}
      </Text>
      <View style={styles.promises}>
        {PROMISES.map(promise => (
          <View key={promise.icon} style={styles.promise}>
            <View style={styles.promiseIcon}>
              <Icon name={promise.icon} size={15} color={colors.successText} />
            </View>
            <Text style={styles.promiseText}>{promise.text}</Text>
          </View>
        ))}
      </View>
      <RampCountryPicker
        visible={picking}
        selected={country ? String(country[2]) : null}
        title="Código de país"
        showCallingCode
        onPick={onCountry}
        onClose={() => setPicking(false)}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  inputRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  codeChip: {
    flexDirection: 'row', alignItems: 'center', gap: 6, height: 52, paddingHorizontal: 12, borderRadius: 14,
    backgroundColor: colors.primarySoft, borderWidth: 1, borderColor: colors.primaryMuted,
  },
  code: { fontSize: 16, fontWeight: '700', color: colors.successText },
  input: {
    flex: 1, height: 52, paddingHorizontal: 14, borderRadius: 14, fontSize: 17, fontWeight: '600', color: colors.dark,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  preview: { marginTop: 8, fontSize: 13, color: colors.textSecondary },
  promises: {
    marginTop: 14, padding: 14, gap: 12, borderRadius: 14, backgroundColor: colors.primarySoft,
    borderWidth: 1, borderColor: colors.primaryMuted,
  },
  promise: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  promiseIcon: {
    width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.background,
  },
  promiseText: { flex: 1, fontSize: 13, lineHeight: 18, color: colors.dark },
});
