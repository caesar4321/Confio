import React from 'react';
import { View, Text, StyleSheet, ViewStyle } from 'react-native';
import type { StatusTier } from '../contexts/AuthContext';

// ── Tier metadata ──────────────────────────────────────────────
// Kept in one place so ProfileScreen, ContactCards, and transaction
// confirmations all render consistently.

export interface TierMeta {
  slug: StatusTier;
  label: string;
  emoji: string;
  color: string;          // primary accent (badge bg, name tint)
  colorLight: string;     // soft background
  ringColor?: string;     // avatar ring for embajador
  threshold: number;      // referrals to reach this tier
}

export const TIER_CONFIG: Record<StatusTier, TierMeta> = {
  member: {
    slug: 'member',
    label: 'Miembro',
    emoji: '🟢',
    color: '#34D399',
    colorLight: '#ECFDF5',
    threshold: 0,
  },
  early_supporter: {
    slug: 'early_supporter',
    label: 'Early Supporter',
    emoji: '⭐',
    color: '#3B82F6',
    colorLight: '#DBEAFE',
    threshold: 1,
  },
  community_builder: {
    slug: 'community_builder',
    label: 'Community Builder',
    emoji: '🔥',
    color: '#F59E0B',
    colorLight: '#FEF3C7',
    threshold: 3,
  },
  embajador: {
    slug: 'embajador',
    label: 'Embajador Confio',
    emoji: '🏆',
    color: '#8B5CF6',
    colorLight: '#EDE9FE',
    ringColor: '#8B5CF6',
    threshold: 10,
  },
};

// ── Utility helpers ────────────────────────────────────────────

export function getTierMeta(tier?: StatusTier | string | null): TierMeta {
  if (tier && tier in TIER_CONFIG) {
    return TIER_CONFIG[tier as StatusTier];
  }
  return TIER_CONFIG.member;
}

export function getTierNameColor(tier?: StatusTier | string | null): string | undefined {
  const meta = getTierMeta(tier);
  // 'member' tier doesn't tint the name — keep default color.
  if (meta.slug === 'member') return undefined;
  return meta.color;
}

// ── Badge component ────────────────────────────────────────────

interface StatusTierBadgeProps {
  tier?: StatusTier | string | null;
  /** Compact mode: just emoji + label, no background pill */
  compact?: boolean;
  style?: ViewStyle;
}

export const StatusTierBadge: React.FC<StatusTierBadgeProps> = React.memo(({
  tier,
  compact = false,
  style,
}) => {
  const meta = getTierMeta(tier);

  if (compact) {
    return (
      <View style={[styles.compactContainer, style]}>
        <Text style={styles.emoji}>{meta.emoji}</Text>
        <Text style={[styles.compactLabel, { color: meta.color }]}>{meta.label}</Text>
      </View>
    );
  }

  return (
    <View style={[styles.pillContainer, { backgroundColor: meta.colorLight }, style]}>
      <Text style={styles.emoji}>{meta.emoji}</Text>
      <Text style={[styles.pillLabel, { color: meta.color }]}>{meta.label}</Text>
    </View>
  );
});

StatusTierBadge.displayName = 'StatusTierBadge';

// ── Tier progress bar ──────────────────────────────────────────

interface TierProgressProps {
  referralCount: number;
  nextTierName?: string | null;
  nextTierReferralsNeeded?: number | null;
  style?: ViewStyle;
}

export const TierProgress: React.FC<TierProgressProps> = React.memo(({
  referralCount,
  nextTierName,
  nextTierReferralsNeeded,
  style,
}) => {
  // Already at max tier
  if (!nextTierName || nextTierReferralsNeeded == null || nextTierReferralsNeeded <= 0) {
    return (
      <View style={[styles.progressContainer, style]}>
        <Text style={styles.progressText}>🏆 Nivel maximo alcanzado</Text>
      </View>
    );
  }

  const nextMeta = getTierMeta(nextTierName);
  const targetCount = referralCount + nextTierReferralsNeeded;
  const progress = targetCount > 0 ? Math.min(referralCount / targetCount, 1) : 0;

  return (
    <View style={[styles.progressContainer, style]}>
      <View style={styles.progressHeader}>
        <Text style={styles.progressText}>
          {nextMeta.emoji} Siguiente: {nextMeta.label}
        </Text>
        <Text style={styles.progressCount}>
          {referralCount}/{targetCount}
        </Text>
      </View>
      <View style={styles.progressBarBg}>
        <View
          style={[
            styles.progressBarFill,
            { width: `${Math.max(progress * 100, 4)}%`, backgroundColor: nextMeta.color },
          ]}
        />
      </View>
      <Text style={styles.progressHint}>
        {nextTierReferralsNeeded === 1
          ? 'Invita 1 amigo mas para desbloquear'
          : `Invita ${nextTierReferralsNeeded} amigos mas para desbloquear`}
      </Text>
    </View>
  );
});

TierProgress.displayName = 'TierProgress';

// ── Styles ─────────────────────────────────────────────────────

const styles = StyleSheet.create({
  // Pill badge
  pillContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    alignSelf: 'center',
    gap: 4,
  },
  pillLabel: {
    fontSize: 12,
    fontWeight: '700',
  },
  emoji: {
    fontSize: 14,
  },
  // Compact badge
  compactContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  compactLabel: {
    fontSize: 11,
    fontWeight: '600',
  },
  // Progress
  progressContainer: {
    paddingVertical: 8,
  },
  progressHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  progressText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#374151',
  },
  progressCount: {
    fontSize: 12,
    fontWeight: '600',
    color: '#6B7280',
  },
  progressBarBg: {
    height: 6,
    backgroundColor: '#E5E7EB',
    borderRadius: 3,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    borderRadius: 3,
  },
  progressHint: {
    fontSize: 11,
    color: '#9CA3AF',
    marginTop: 4,
  },
});
