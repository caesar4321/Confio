import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View, ViewStyle } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { countryInfo } from '../utils/humanitarianCountry';

type Campaign = {
  slug: string;
  title?: string | null;
  countryCode?: string | null;
  goalAmount?: string | number | null;
  totalDonated?: string | number | null;
  donationCount?: number | null;
};

function toNumber(value?: string | number | null) {
  const n = typeof value === 'number' ? value : parseFloat(String(value || '0'));
  return Number.isFinite(n) ? n : 0;
}

function fmtWhole(value: number) {
  return value.toLocaleString('es-VE', { maximumFractionDigits: 0 });
}

export function HumanitarianHomeBanner({
  campaign,
  onPress,
  style,
}: {
  campaign: Campaign;
  onPress: () => void;
  style?: ViewStyle;
}) {
  const flag = countryInfo(campaign.countryCode).flag;
  const goal = toNumber(campaign.goalAmount);
  const donated = toNumber(campaign.totalDonated);
  const donationCount = campaign.donationCount || 0;
  const goalReached = goal > 0 && donated >= goal;
  const fillWidth = goal > 0 ? Math.min(100, Math.max((donated / goal) * 100, donated > 0 ? 6 : 0)) : 0;

  const donationsSuffix = donationCount > 0
    ? `  ·  ${donationCount} ${donationCount === 1 ? 'donación' : 'donaciones'}`
    : '';

  return (
    <TouchableOpacity
      style={[styles.card, style]}
      onPress={onPress}
      activeOpacity={0.85}
      accessibilityRole="button"
      accessibilityLabel={`Campaña humanitaria: ${campaign.title || 'Ayuda humanitaria directa'}`}
    >
      <View style={styles.flagWrap}>
        <Text style={styles.flag}>{flag}</Text>
      </View>
      <View style={styles.body}>
        <Text style={styles.title} numberOfLines={2}>
          {campaign.title || 'Ayuda humanitaria directa'}
        </Text>
        {goal > 0 ? (
          <>
            <View style={styles.track}>
              <View style={[styles.fill, { width: `${Math.max(fillWidth, 6)}%` }]} />
            </View>
            <Text style={styles.meta} numberOfLines={1}>
              {goalReached ? '¡Meta superada!' : `${fmtWhole(donated)} / ${fmtWhole(goal)} cUSD`}
              {donationsSuffix}
            </Text>
          </>
        ) : (
          <Text style={styles.meta} numberOfLines={1}>
            Dona cUSD para familias afectadas{donationsSuffix}
          </Text>
        )}
      </View>
      <Icon name="chevron-right" size={18} color="#9CA3AF" />
    </TouchableOpacity>
  );
}

// Styled as a sibling of Home's other promo cards (invite claim, payroll):
// flat tinted fill + 1px border, radius 12, 40px icon square on the left.
// Sky blue is the humanitarian category color (UN/UNICEF convention — calm,
// not alarming; rose was rejected for reading like the app's error state).
// Slot grammar: emerald = your money, violet = payroll, sky = humanitarian.
const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: '#F0F9FF', // sky-50
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: '#BAE6FD', // sky-200
  },
  flagWrap: {
    width: 40,
    height: 40,
    borderRadius: 14,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
  },
  flag: { fontSize: 22 },
  body: { flex: 1 },
  title: { fontSize: 15, lineHeight: 20, fontWeight: '700', color: '#111827', marginBottom: 6 },
  track: { height: 5, borderRadius: 3, backgroundColor: '#E0F2FE', overflow: 'hidden' }, // sky-100
  fill: { height: '100%', borderRadius: 3, backgroundColor: '#0EA5E9' }, // sky-500
  meta: { fontSize: 12, color: '#6B7280', marginTop: 6 },
});
