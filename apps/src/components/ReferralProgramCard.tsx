// "Invitar y ganar": invite by WhatsApp, the commissions it pays, bonuses
// already earned, the person's code and how the programme works. It lived at
// the top of Perfil; it is a product of its own, so it has its own screen
// (InviteScreen), opened from the menu and from one line in Perfil.
import React from 'react';
import { Platform, StyleSheet, TouchableOpacity, View } from 'react-native';
import { useQuery } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import { GET_MY_REFERRALS } from '../apollo/queries';
import { colors } from '../config/theme';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { DEFAULT_TERMS, commissionPercents, useFeeReferralSummary, windowRule } from '../hooks/useFeeReferralSummary';
import { shareReferralOnWhatsApp } from '../services/referralShare';
import { MainStackParamList } from '../types/navigation';
import { formatDecimal } from '../utils/numberLocale';
import { Text } from './common/AppText';
import { CommissionsEntryRow } from './CommissionsEntryRow';
import { TierProgress } from './StatusTierBadge';

/** `surface`: where it is drawn, for the share-tap count. */
export function ReferralProgramCard({ surface = 'invite' }: { surface?: string }) {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { userProfile } = useAuth();
  const { activeAccount } = useAccount();
  const rawUsername = userProfile?.username || '';
  const needsFriendlyUsername = React.useMemo(() => {
    if (!rawUsername) return true;
    if (rawUsername.startsWith('user_')) return true;
    // Treat long alphanumeric handles without separators as auto-generated
    if (/^[a-z0-9]{10,}$/.test(rawUsername)) return true;
    return false;
  }, [rawUsername]);
  // Referral commission: 50% of an invited friend's fee (the referral program).
  const commission = useFeeReferralSummary(activeAccount?.type?.toLowerCase() === 'business');
  const commissionTerms = commission ?? DEFAULT_TERMS;
  const commissionSharePct = commissionPercents(commissionTerms).sharePct;

  const handleShareReferral = React.useCallback(
    () => shareReferralOnWhatsApp(userProfile?.username, surface),
    [surface, userProfile?.username],
  );

  const { data: referralData } = useQuery(GET_MY_REFERRALS, {
    fetchPolicy: 'cache-and-network',
  });

  const referralStats = React.useMemo(() => {
    if (!referralData?.myReferrals || !userProfile?.id) return { pending: 0, earned: 0, isReferred: false };

    const currentUserId = String(userProfile.id);
    let pending = 0;
    let earned = 0;
    let isReferred = false;

    referralData.myReferrals.forEach((ref: any) => {
      const isReferrer = String(ref.referrerUser?.id) === currentUserId;
      const isReferee = String(ref.referredUser?.id) === currentUserId;

      if (isReferee) isReferred = true;

      const frameworkStatus = isReferrer ? ref.referrerRewardStatus : ref.refereeRewardStatus;
      // The Decimal scalar arrives as a STRING: without Number() these sums
      // concatenate ("5.00" + "5.00" = "5.005.00") instead of adding.
      const amount = Number(
        (isReferrer ? ref.rewardReferrerConfio : ref.rewardRefereeConfio) ?? 0,
      ) || 0;

      // 'pending'/'locked' = the condition isn't met yet. 'eligible' = the
      // bonus is EARNED and held in the account — not withdrawable until
      // $CONFIO launches.
      if (frameworkStatus === 'pending' || frameworkStatus === 'locked') {
        pending += amount;
      } else if (frameworkStatus === 'eligible') {
        earned += amount;
      }
    });

    return { pending, earned, isReferred };
  }, [referralData, userProfile]);

  // A business has no invitations of its own.
  if (activeAccount?.type.toLowerCase() === 'business') {
    return null;
  }

  return (
    <View style={styles.referralCard}>
      <View style={styles.referralHeader}>
        <View style={styles.referralIconBadge}>
          <Icon name="gift" size={20} color={colors.white} />
        </View>
        <View style={styles.referralHeaderText}>
          <Text style={styles.referralTitle}>
            Tu red de confianza ahora te paga
          </Text>
          <Text style={styles.referralSubtitle}>
            <Text style={styles.referralSubtitleAccent}>Invita a quienes confías.</Text>
            {` Cuando mueven su dinero, Confío te comparte el ${commissionSharePct} de su comisión, en dólares y al instante.`}
          </Text>
        </View>
      </View>

      <View style={styles.referralActions}>
        <TouchableOpacity
          style={styles.referralShareButton}
          onPress={handleShareReferral}
          accessibilityRole="button"
          accessibilityLabel="Invitar por WhatsApp"
        >
          <WhatsAppLogo width={20} height={20} style={{ marginRight: 8 }} />
          <Text style={styles.referralShareText}>Invitar por WhatsApp</Text>
        </TouchableOpacity>
      </View>

      {commission && commission.friendCount > 0 && (
        // Existing invitations count from launch: tell dormant
        // referrers their old invites can start paying now.
        <Text style={[styles.referralCriteriaNote, { marginTop: 10 }]}>
          {commission.friendCount === 1 ? 'Ya tienes 1 invitado.' : `Ya tienes ${commission.friendCount} invitados.`}
          {' '}Cuando ambos estén verificados, empiezas a ganar.
        </Text>
      )}

      {commission && !commission.viewerVerified && (
        <TouchableOpacity
          style={[styles.referralUpdateUsername, { marginTop: 10 }]}
          onPress={() => navigation.navigate('Verification' as never)}
        >
          <Icon name="shield" size={16} color={colors.primaryDark} />
          <Text style={styles.referralUpdateUsernameText}>Verifica tu identidad para empezar a ganar</Text>
          <Icon name="chevron-right" size={16} color={colors.primaryDark} />
        </TouchableOpacity>
      )}

      {/* The permanent entry: never waits for the summary to load. */}
      <View style={{ marginTop: 12 }}>
        <CommissionsEntryRow
          summary={commission}
          onPress={() => navigation.navigate('FeeReferralCommissions')}
        />
      </View>

      {/* $CONFIO bonuses ended with the commission launch: the row stays
          only for people holding bonuses they already earned. */}
      {referralStats.earned > 0 && (
      <TouchableOpacity
        style={[
          styles.referralClaimButton,
          // Highlight once there is something earned to show
          referralStats.earned > 0 && { backgroundColor: colors.primarySoft, borderColor: colors.primaryDark, borderLeftWidth: 4 }
        ]}
        onPress={() => navigation.navigate('ReferralRewardClaim')}
      >
        <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
          {referralStats.earned > 0 ? (
            <View style={[styles.referralStatusDot, { backgroundColor: colors.primaryDark }]} />
          ) : referralStats.pending > 0 ? (
            <View style={[styles.referralStatusDot, { backgroundColor: colors.warning.icon }]} />
          ) : (
            <Icon name="gift" size={16} color={colors.primaryDark} style={{ marginRight: 8 }} />
          )}

          <Text style={[
            styles.referralClaimText,
            referralStats.earned > 0 && { color: colors.successText, fontWeight: '700' },
            // pending = waiting on the friend's deposit, not an error
            referralStats.pending > 0 && { color: colors.warning.text },
          ]}>
            {/* Earned, not withdrawable: the bonus is held in the
                account until $CONFIO launches. */}
            {referralStats.earned > 0
              ? `${formatDecimal(referralStats.earned)} $CONFIO ganados`
              : 'Ver mis bonos ($CONFIO)'}
          </Text>
        </View>
        <Icon name="chevron-right" size={16} color={colors.primaryDark} />
      </TouchableOpacity>
      )}

      {/* Tier progress indicator */}
      {activeAccount?.type.toLowerCase() === 'personal' && (
        <View style={{ paddingHorizontal: 12, paddingTop: 8 }}>
          <TierProgress
            referralCount={userProfile?.referralCount ?? 0}
            nextTierName={userProfile?.nextTierName}
            nextTierReferralsNeeded={userProfile?.nextTierReferralsNeeded}
          />
        </View>
      )}

      {needsFriendlyUsername && (
        <TouchableOpacity style={styles.referralUpdateUsername} onPress={() => navigation.navigate('UpdateUsername')}>
          <Icon name="edit-3" size={16} color={colors.primaryDark} />
          <Text style={styles.referralUpdateUsernameText}>Personalizar mi código</Text>
          <Icon name="chevron-right" size={16} color={colors.primaryDark} />
        </TouchableOpacity>
      )}

      {!referralStats.isReferred && (
        <TouchableOpacity
          style={styles.referralUpdateUsername}
          onPress={() => navigation.navigate('Achievements')}
        >
          <Icon name="user-plus" size={16} color={colors.primaryDark} />
          <Text style={styles.referralUpdateUsernameText}>¿Te invitó alguien? Pon su código</Text>
          <Icon name="chevron-right" size={16} color={colors.primaryDark} />
        </TouchableOpacity>
      )}

      <View style={styles.referralCriteria}>
        <Text style={styles.referralCriteriaTitle}>¿Cómo funciona?</Text>
        <Text style={styles.referralCriteriaItem}>1. Comparte tu link por WhatsApp con la historia del fundador.</Text>
        <Text style={styles.referralCriteriaItem}>2. Tu amigo se crea la cuenta y descubre Confío.</Text>
        <Text style={styles.referralCriteriaItem}>3. Cuando ambos verifican su identidad, recibes al instante el {commissionSharePct} de la comisión que tu amigo paga al recargar, retirar, invertir o enviar fuera de Confío, en dólares (cUSD). {windowRule(commissionTerms.windowDays)}.</Text>
      </View>

      {/* Tier ladder in one line; the badge itself still shows next to names. */}
      <View style={styles.referralCriteria}>
        <Text style={styles.referralCriteriaNote}>
          🏅 Tu insignia sube con los amigos que invitas: ⭐ 1, 💎 3 y 🏆 10 amigos verificados con depósito.
        </Text>
      </View>

      <View style={styles.referralCriteria}>
        <TouchableOpacity onPress={() => navigation.navigate('Achievements')}>
          <Text style={[styles.referralCriteriaItem, { color: colors.accent, marginTop: 4, fontWeight: '600' }]}>
            Ver instrucciones completas
          </Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  referralCard: {
    backgroundColor: colors.white,
    borderRadius: 20,
    marginHorizontal: 16,
    marginBottom: 16,
    padding: 20,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 8 },
        shadowOpacity: 0.08,
        shadowRadius: 12,
      },
      android: {
        elevation: 3,
      },
    }),
  },
  referralHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 16,
    marginBottom: 16,
  },
  referralIconBadge: {
    width: 48,
    height: 48,
    borderRadius: 16,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  referralHeaderText: {
    flex: 1,
    gap: 4,
  },
  referralTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text.primary,
  },
  referralSubtitleAccent: {
    fontWeight: '700',
    color: colors.accent,
  },
  referralSubtitle: {
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 18,
  },
  referralUsername: {
    backgroundColor: colors.primarySoft,
    borderRadius: 16,
    paddingVertical: 12,
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  referralUsernameLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.primaryDark,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 4,
  },
  referralUsernameValue: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  referralUsernameHint: {
    marginTop: 8,
    fontSize: 12,
    color: colors.primaryDark,
    lineHeight: 18,
  },
  referralActions: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 18,
  },
  referralCopyButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: colors.primarySoft,
    gap: 8,
  },
  referralCopyText: {
    color: colors.primaryDark,
    fontWeight: '600',
    fontSize: 14,
  },
  referralShareButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: colors.primaryDark,
    gap: 8,
  },
  referralShareText: {
    color: colors.white,
    fontWeight: '600',
    fontSize: 14,
  },
  referralClaimButton: {
    marginBottom: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(16,185,129,0.3)',
    paddingVertical: 12,
    paddingHorizontal: 16,
    backgroundColor: colors.primarySoft,
    gap: 8,
  },
  referralStatusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginRight: 8,
  },
  referralClaimText: {
    flex: 1,
    marginHorizontal: 12,
    color: colors.primaryDark,
    fontWeight: '600',
    fontSize: 14,
  },
  referralUpdateUsername: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 12,
    backgroundColor: colors.neutralDark,
    marginBottom: 18,
  },
  referralUpdateUsernameText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  referralSteps: {
    gap: 12,
    marginBottom: 16,
  },
  referralStep: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  referralStepNumber: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.primarySoft,
    textAlign: 'center',
    lineHeight: 24,
    fontWeight: '700',
    fontSize: 13,
    color: colors.primaryDark,
  },
  referralStepText: {
    flex: 1,
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 19,
  },
  referralCriteria: {
    marginTop: 4,
    marginBottom: 16,
    padding: 14,
    borderRadius: 12,
    backgroundColor: colors.neutral,
    gap: 4,
  },
  referralCriteriaTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 4,
  },
  referralCriteriaItem: {
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 18,
  },
  referralCriteriaNote: {
    marginTop: 8,
    fontSize: 12,
    color: colors.primaryDark,
  },
  referralRegisterButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 12,
    backgroundColor: colors.primarySoft,
    marginBottom: 12,
  },
  referralRegisterButtonText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  referralLink: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  referralLinkText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
});
