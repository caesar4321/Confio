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

  return (
    <TouchableOpacity style={[styles.card, style]} onPress={onPress} activeOpacity={0.85}>
      <Text style={styles.flag}>{flag}</Text>
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
              {donationCount > 0 ? `  ·  ❤ ${donationCount}` : ''}
            </Text>
          </>
        ) : (
          <Text style={styles.meta} numberOfLines={1}>
            Dona cUSD para familias afectadas{donationCount > 0 ? `  ·  ❤ ${donationCount}` : ''}
          </Text>
        )}
      </View>
      <Icon name="chevron-right" size={18} color="#9CA3AF" />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    paddingVertical: 12,
    paddingHorizontal: 14,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 4,
  },
  flag: { fontSize: 26 },
  body: { flex: 1 },
  title: { fontSize: 15, lineHeight: 20, fontWeight: '800', color: '#0F172A', marginBottom: 7 },
  track: { height: 5, borderRadius: 3, backgroundColor: '#E5E7EB', overflow: 'hidden' },
  fill: { height: '100%', borderRadius: 3, backgroundColor: '#10B981' },
  meta: { fontSize: 12, color: '#64748B', marginTop: 6 },
});
