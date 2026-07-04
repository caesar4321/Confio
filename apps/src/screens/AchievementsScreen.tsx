import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Share,
  Linking,
} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import Icon from 'react-native-vector-icons/Feather';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { useNavigation } from '@react-navigation/native';
import { NavigationProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { ReferralInputModal } from '../components/ReferralInputModal';
import { buildReferralShareMessage, normalizeInviteUsername } from '../utils/inviteLinks';
import { AnalyticsService } from '../services/analyticsService';
import { colors } from '../config/theme';
import { InlineBanner } from '../components/common/InlineBanner';
import { Header } from '../navigation/Header';

type Step = {
  title: string;
  description: string;
};

export const AchievementsScreen: React.FC = () => {
  const navigation = useNavigation<NavigationProp<MainStackParamList>>();
  const { userProfile } = useAuth();
  const rawUsername = userProfile?.username || '';
  const username = rawUsername ? `@${rawUsername}` : '';
  const needsFriendlyUsername = useMemo(() => {
    if (!rawUsername) return true;
    if (rawUsername.startsWith('user_')) return true;
    if (/^[a-z0-9]{10,}$/.test(rawUsername)) return true;
    return false;
  }, [rawUsername]);
  const [showReferralModal, setShowReferralModal] = useState(false);
  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);

  const shareMessage = useMemo(() => {
    return buildReferralShareMessage(username || 'tuUsuario');
  }, [username]);

  const steps: Step[] = useMemo(
    () => [
      {
        title: 'Comparte tu link',
        description: 'Toca "Invitar por WhatsApp" y elige a tus amigos. El mensaje incluye tu link y la historia de Julian.',
      },
      {
        title: 'Tu amigo descubre Confío',
        description: 'Al crear su cuenta usando tu enlace, queda asociado a tu invitación.',
      },
      {
        title: 'Tu amigo carga US$20',
        description:
          'Con su primera recarga de al menos US$20 — a su cUSD o directo a su ahorro (cUSD+) — se activan los US$5 en $CONFIO para los dos.',
      },
      {
        title: '¡Ganen sin límites!',
        description: 'No hay límite de invitaciones. Entre más amigos invites, más ganarás.',
      },
    ],
    []
  );

  const handleShare = async () => {
    try {
      AnalyticsService.logFunnelEvent('referral_whatsapp_share_tapped', {
        surface: 'achievements',
        referral_code: normalizeInviteUsername(username || 'tuUsuario'),
      }, {
        sourceType: 'referral_link',
        channel: 'whatsapp',
      });
    } catch (_e) {
      // never block sharing
    }

    const encodedMessage = encodeURIComponent(shareMessage);
    const whatsappSchemeUrl = `whatsapp://send?text=${encodedMessage}`;
    const whatsappWebUrl = `https://wa.me/?text=${encodedMessage}`;
    try {
      const canUseScheme = await Linking.canOpenURL(whatsappSchemeUrl);
      if (canUseScheme) {
        await Linking.openURL(whatsappSchemeUrl);
      } else {
        await Linking.openURL(whatsappWebUrl);
      }
    } catch (error) {
      try {
        await Share.share({
          message: shareMessage,
          title: 'Invitación Confío',
        });
      } catch (fallbackError) {
      }
    }
  };

  const handleCopy = () => {
    if (!username) {
      setBanner({ variant: 'error', message: 'Actualiza tu perfil para crear un @usuario y comienza a invitar.' });
      return;
    }
    Clipboard.setString(username);
    setBanner({ variant: 'success', message: 'Usuario copiado — pégalo en WhatsApp o cualquier app.' });
  };

  return (
    <View style={styles.safeArea}>
      <Header
        navigation={navigation as any}
        title="Programa de referidos"
        backgroundColor={colors.secondary}
        isLight
        showBackButton
      />

      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        {/* Violet brand field: the $CONFIO instrument color, same gradient +
            coin-ring grammar as Home/Profile/Auth. Vertical gradient so the
            top edge meets the flat nav header without a seam; padding lives
            on fieldInner (Yoga insets absolute children by parent padding). */}
        <View style={styles.brandField}>
          <Svg style={StyleSheet.absoluteFill}>
            <Defs>
              <SvgLinearGradient id="referralField" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={colors.secondary} />
                <Stop offset="1" stopColor={colors.secondaryDark} />
              </SvgLinearGradient>
            </Defs>
            <Rect width="100%" height="100%" fill="url(#referralField)" />
            <Circle cx="104%" cy="18%" r="100" stroke={colors.white} strokeWidth="24" strokeOpacity="0.10" fill="none" />
          </Svg>
          <View style={styles.fieldInner}>
            <Text style={styles.fieldEyebrow}>US$5 PARA TI Y TU AMIGO</Text>
            <Text style={styles.fieldTitle}>Invita a tus amigos a la red de confianza</Text>
            <Text style={styles.fieldSubtitle}>
              Comparte la historia de Julian y por qué nació Confío. Cuando tu
              amigo haga su primer depósito, ambos reciben US$5 en $CONFIO.
            </Text>

            <View style={styles.usernameRow}>
              <View style={styles.usernamePill}>
                <Text style={styles.usernameLabel}>Tu usuario</Text>
                <Text style={styles.usernameValue} numberOfLines={1}>
                  {username || 'Configura tu @usuario'}
                </Text>
              </View>
              <TouchableOpacity
                style={styles.copyChip}
                onPress={handleCopy}
                accessibilityRole="button"
                accessibilityLabel="Copiar usuario"
              >
                <Icon name="copy" size={16} color={colors.white} />
              </TouchableOpacity>
            </View>

            <TouchableOpacity
              style={styles.whatsappButton}
              onPress={handleShare}
              activeOpacity={0.85}
              accessibilityRole="button"
              accessibilityLabel="Invitar por WhatsApp"
            >
              <WhatsAppLogo width={20} height={20} />
              <Text style={styles.whatsappButtonText}>Invitar por WhatsApp</Text>
            </TouchableOpacity>

            {needsFriendlyUsername && (
              <TouchableOpacity
                style={styles.updateUsernameLink}
                onPress={() => navigation.navigate('UpdateUsername')}
                accessibilityRole="button"
                accessibilityLabel="Actualizar mi usuario"
              >
                <Icon name="edit-3" size={14} color={colors.violetLight} />
                <Text style={styles.updateUsernameText}>
                  Crea un usuario corto y fácil de recordar
                </Text>
                <Icon name="chevron-right" size={14} color={colors.violetLight} />
              </TouchableOpacity>
            )}
          </View>
        </View>

        {/* White content */}
        <View style={styles.body}>
          {banner && (
            <InlineBanner
              message={banner.message}
              variant={banner.variant}
              onDismiss={dismissBanner}
              autoHideMs={banner.variant === 'success' ? 2500 : undefined}
              style={{ marginBottom: 0 }}
            />
          )}

          {/* Claim entry — tinted promo card, Home promo grammar */}
          <TouchableOpacity
            style={styles.claimCard}
            activeOpacity={0.8}
            onPress={() => navigation.navigate('ReferralRewardClaim')}
            accessibilityRole="button"
            accessibilityLabel="Desbloquear recompensas"
          >
            <View style={styles.claimIconWrap}>
              <Icon name="unlock" size={18} color={colors.secondary} />
            </View>
            <View style={styles.claimCardText}>
              <Text style={styles.claimCardTitle}>Desbloquear recompensas</Text>
              <Text style={styles.claimCardSubtitle}>Revisa si tienes $CONFIO listos para reclamar</Text>
            </View>
            <Icon name="chevron-right" size={18} color={colors.secondary} />
          </TouchableOpacity>

          {/* Invited-by row */}
          <TouchableOpacity
            style={styles.invitedCard}
            onPress={() => setShowReferralModal(true)}
            accessibilityRole="button"
            accessibilityLabel="Registrar quién te invitó"
          >
            <View style={styles.invitedIconWrap}>
              <Icon name="user-plus" size={18} color={colors.secondary} />
            </View>
            <View style={styles.claimCardText}>
              <Text style={styles.claimCardTitle}>¿Te invitó alguien?</Text>
              <Text style={styles.claimCardSubtitle}>Pon su @usuario para que también reciba su regalo</Text>
            </View>
            <Icon name="chevron-right" size={18} color={colors.text.light} />
          </TouchableOpacity>

          {/* How it works */}
          <View style={styles.sectionCard}>
            <Text style={styles.sectionTitle}>Cómo desbloquear los US$5</Text>
            {steps.map((step, index) => (
              <View key={step.title} style={[styles.stepRow, index === steps.length - 1 && { marginBottom: 0 }]}>
                <View style={styles.stepNumberWrap}>
                  <Text style={styles.stepNumber}>{index + 1}</Text>
                </View>
                <View style={styles.stepContent}>
                  <Text style={styles.stepTitle}>{step.title}</Text>
                  <Text style={styles.stepDescription}>{step.description}</Text>
                </View>
              </View>
            ))}
            <View style={styles.criteriaNoteRow}>
              <Icon name="info" size={13} color={colors.text.secondary} />
              <Text style={styles.criteriaNote}>
                Cuenta cualquier primera recarga, depósito o ahorro (cUSD+) de
                al menos US$20. El bono se acredita en $CONFIO automáticamente.
              </Text>
            </View>
          </View>
        </View>

        <ReferralInputModal
          visible={showReferralModal}
          onClose={() => setShowReferralModal(false)}
          onSuccess={() => setShowReferralModal(false)}
        />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  container: {
    flex: 1,
  },
  content: {
    paddingBottom: 32,
  },
  brandField: {
    backgroundColor: colors.secondary,
    overflow: 'hidden',
  },
  fieldInner: {
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 28,
  },
  fieldEyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2,
    color: colors.violetLight,
    marginBottom: 8,
  },
  fieldTitle: {
    fontSize: 24,
    fontWeight: '800',
    color: colors.white,
    lineHeight: 30,
  },
  fieldSubtitle: {
    fontSize: 14,
    lineHeight: 21,
    color: 'rgba(255, 255, 255, 0.85)',
    marginTop: 8,
  },
  usernameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginTop: 18,
  },
  usernamePill: {
    flex: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: 'rgba(255, 255, 255, 0.14)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.25)',
  },
  usernameLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.violetLight,
    marginBottom: 1,
  },
  usernameValue: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.white,
  },
  copyChip: {
    width: 48,
    height: 48,
    borderRadius: 12,
    backgroundColor: 'rgba(255, 255, 255, 0.14)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.25)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  whatsappButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginTop: 14,
    backgroundColor: colors.white,
    borderRadius: 14,
    paddingVertical: 15,
  },
  whatsappButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
  },
  updateUsernameLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginTop: 14,
    paddingVertical: 4,
  },
  updateUsernameText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.violetLight,
  },
  body: {
    padding: 20,
    gap: 14,
  },
  claimCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: colors.violetLight,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#DDD6FE', // violet-200, pairs with violetLight
  },
  claimIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  claimCardText: {
    flex: 1,
  },
  claimCardTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.dark,
  },
  claimCardSubtitle: {
    fontSize: 13,
    color: colors.text.secondary,
    marginTop: 2,
  },
  invitedCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: colors.background,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  invitedIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.violetLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sectionCard: {
    backgroundColor: colors.background,
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: colors.border,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
    marginBottom: 16,
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 16,
  },
  stepNumberWrap: {
    width: 28,
    height: 28,
    borderRadius: 9,
    backgroundColor: colors.violetLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  stepNumber: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.secondary,
  },
  stepContent: {
    flex: 1,
  },
  stepTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.dark,
    marginBottom: 3,
  },
  stepDescription: {
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 19,
  },
  criteriaNoteRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
    marginTop: 16,
    paddingTop: 14,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  criteriaNote: {
    flex: 1,
    fontSize: 12,
    lineHeight: 17,
    color: colors.text.secondary,
  },
});

export default AchievementsScreen;
