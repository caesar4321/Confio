import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

type InfluencerTier = 'nano' | 'micro' | 'macro' | 'ambassador';

interface InfluencerTierBadgeProps {
  tier: InfluencerTier;
  referralCount: number;
  size?: 'small' | 'medium' | 'large';
}

const tierConfig = {
  nano: {
    name: 'Nano-Influencer',
    emoji: '🌱',
    color: '#22C55E',
    lightColor: '#DCFCE7',
    range: '1-10 referidos',
    perks: ['4 CONFIO por referido']
  },
  micro: {
    name: 'Micro-Influencer',
    emoji: '⭐',
    color: '#3B82F6',
    lightColor: '#DBEAFE',
    range: '11-100 referidos',
    perks: ['6 CONFIO por referido', 'Badge especial', 'Acceso temprano a features']
  },
  macro: {
    name: 'Macro-Influencer',
    emoji: '💫',
    color: '#8B5CF6',
    lightColor: '#E9D5FF',
    range: '101-1000 referidos',
    perks: ['8 CONFIO por referido', 'Perks exclusivos', 'Contacto directo con equipo']
  },
  ambassador: {
    name: 'Embajador Confío',
    emoji: '👑',
    color: '#F59E0B',
    lightColor: '#FEF3C7',
    range: '1000+ referidos',
    perks: ['Partnership personalizado', 'Pagos en efectivo', 'Co-marketing']
  }
};

export const InfluencerTierBadge: React.FC<InfluencerTierBadgeProps> = ({
  tier,
  referralCount,
  size = 'medium'
}) => {
  const config = tierConfig[tier];
  const isSmall = size === 'small';
  const isLarge = size === 'large';

  return (
    <View style={[
      styles.container,
      { backgroundColor: config.lightColor, borderColor: config.color },
      isSmall && styles.containerSmall,
      isLarge && styles.containerLarge
    ]}>
      <View style={styles.header}>
        <Text style={[styles.emoji, isSmall && styles.emojiSmall, isLarge && styles.emojiLarge]}>
          {config.emoji}
        </Text>
        <View style={styles.titleContainer}>
          <Text style={[
            styles.tierName, 
            { color: config.color },
            isSmall && styles.tierNameSmall,
            isLarge && styles.tierNameLarge
          ]}>
            {config.name}
          </Text>
          <Text style={[styles.range, isSmall && styles.rangeSmall]}>
            {config.range}
          </Text>
        </View>
      </View>
      
      {!isSmall && (
        <>
          <Text style={[styles.referralCount, isLarge && styles.referralCountLarge]}>
            {referralCount} referidos
          </Text>
          
          <View style={styles.perksContainer}>
            {config.perks.map((perk, index) => (
              <Text key={index} style={[styles.perk, isLarge && styles.perkLarge]}>
                • {perk}
              </Text>
            ))}
          </View>
        </>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    marginBottom: 8,
  },
  containerSmall: {
    padding: 8,
    borderRadius: 8,
  },
  containerLarge: {
    padding: 16,
    borderRadius: 16,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  emoji: {
    fontSize: 24,
    marginRight: 8,
  },
  emojiSmall: {
    fontSize: 16,
    marginRight: 6,
  },
  emojiLarge: {
    fontSize: 32,
    marginRight: 12,
  },
  titleContainer: {
    flex: 1,
  },
  tierName: {
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 2,
  },
  tierNameSmall: {
    fontSize: 14,
    marginBottom: 0,
  },
  tierNameLarge: {
    fontSize: 20,
    marginBottom: 4,
  },
  range: {
    fontSize: 12,
    color: '#6B7280',
  },
  rangeSmall: {
    fontSize: 10,
  },
  referralCount: {
    fontSize: 18,
    fontWeight: '600',
    color: '#111827',
    marginBottom: 8,
  },
  referralCountLarge: {
    fontSize: 24,
    marginBottom: 12,
  },
  perksContainer: {
    gap: 2,
  },
  perk: {
    fontSize: 12,
    color: '#4B5563',
  },
  perkLarge: {
    fontSize: 14,
  },
});