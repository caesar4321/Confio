import React from 'react';
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
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { useNavigation, NavigationProp } from '@react-navigation/native';
import { MainStackParamList, RootStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { Header } from '../navigation/Header';
import { ReferralInputModal } from '../components/ReferralInputModal';
import { buildReferralShareMessage, normalizeInviteUsername } from '../utils/inviteLinks';
import { AnalyticsService } from '../services/analyticsService';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import { colors } from '../config/theme';
import { InlineBanner } from '../components/common/InlineBanner';

// Focused share utility: ONE job — put your @usuario in a friend's hands.
// The program explainer (steps, rewards) lives on AchievementsScreen; this
// screen links there instead of duplicating it.
export const ConfioAddressScreen: React.FC = () => {
  const rootNavigation = useNavigation<NavigationProp<RootStackParamList>>();
  const navigation = useNavigation<NavigationProp<MainStackParamList>>();
  const { userProfile } = useAuth();
  const rawUsername = userProfile?.username || '';
  const username = rawUsername ? `@${rawUsername}` : '';
  const needsFriendlyUsername = React.useMemo(() => {
    if (!rawUsername) return true;
    if (rawUsername.startsWith('user_')) return true;
    if (/^[a-z0-9]{10,}$/.test(rawUsername)) return true;
    return false;
  }, [rawUsername]);
  const [showReferralModal, setShowReferralModal] = React.useState(false);
  const [banner, setBanner] = React.useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);

  const shareMessage = React.useMemo(() => {
    return buildReferralShareMessage(username || 'tuUsuario');
  }, [username]);

  const handleCopy = React.useCallback(() => {
    if (!username) {
      setBanner({ variant: 'error', message: 'Edita tu perfil para crear un @usuario y poder compartirlo.' });
      return;
    }
    Clipboard.setString(username);
    setBanner({ variant: 'success', message: 'Usuario copiado — compártelo para que tus amigos lo ingresen al registrarse.' });
  }, [username]);

  const handleShare = React.useCallback(async () => {
    try {
      AnalyticsService.logFunnelEvent('referral_whatsapp_share_tapped', {
        surface: 'confio_address',
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
  }, [shareMessage, username]);

  return (
    <View style={styles.container}>
      <Header
        navigation={rootNavigation}
        title="Compartir mi usuario"
        backgroundColor={colors.secondary}
        isLight={true}
        showBackButton={true}
      />

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.content}>
        {/* Violet brand field: referral-suite identity ($CONFIO reward),
            gradient + coin ring, padding on fieldInner (Yoga rule). The
            @usuario IS the hero object. */}
        <View style={styles.brandField}>
          <Svg style={StyleSheet.absoluteFill}>
            <Defs>
              <SvgLinearGradient id="addressField" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={colors.secondary} />
                <Stop offset="1" stopColor={colors.secondaryDark} />
              </SvgLinearGradient>
            </Defs>
            <Rect width="100%" height="100%" fill="url(#addressField)" />
            <Circle cx="106%" cy="14%" r="96" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
          </Svg>
          <View style={styles.fieldInner}>
            <Text style={styles.fieldEyebrow}>PROGRAMA DE REFERIDOS</Text>
            <Text style={styles.fieldUsername} numberOfLines={1} adjustsFontSizeToFit>
              {username || 'Configura tu @usuario'}
            </Text>
            <Text style={styles.fieldHint}>
              Tus amigos lo escriben en "¿Quién te invitó?" al crear su cuenta.
            </Text>

            <View style={styles.fieldActions}>
              <TouchableOpacity
                style={styles.copyButton}
                onPress={handleCopy}
                accessibilityRole="button"
                accessibilityLabel="Copiar usuario"
              >
                <Icon name="copy" size={16} color={colors.white} />
                <Text style={styles.copyButtonText}>Copiar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.whatsappButton}
                onPress={handleShare}
                activeOpacity={0.85}
                accessibilityRole="button"
                accessibilityLabel="Compartir por WhatsApp"
              >
                <WhatsAppLogo width={18} height={18} />
                <Text style={styles.whatsappButtonText}>WhatsApp</Text>
              </TouchableOpacity>
            </View>

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

          {/* Program details live on the Programa screen — link, don't repeat */}
          <TouchableOpacity
            style={styles.rowCard}
            onPress={() => navigation.navigate('Achievements')}
            accessibilityRole="button"
            accessibilityLabel="Ver el programa de referidos"
          >
            <View style={styles.rowIconWrap}>
              <Icon name="gift" size={18} color={colors.secondary} />
            </View>
            <View style={styles.rowText}>
              <Text style={styles.rowTitle}>Ver el programa de referidos</Text>
              <Text style={styles.rowSubtitle}>Cómo ganan US$5 tú y cada amigo</Text>
            </View>
            <Icon name="chevron-right" size={18} color={colors.text.light} />
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.rowCard}
            onPress={() => setShowReferralModal(true)}
            accessibilityRole="button"
            accessibilityLabel="Registrar quién te invitó"
          >
            <View style={styles.rowIconWrap}>
              <Icon name="user-plus" size={18} color={colors.secondary} />
            </View>
            <View style={styles.rowText}>
              <Text style={styles.rowTitle}>¿Te invitó alguien?</Text>
              <Text style={styles.rowSubtitle}>Pon su @usuario para que también reciba su regalo</Text>
            </View>
            <Icon name="chevron-right" size={18} color={colors.text.light} />
          </TouchableOpacity>

          {/* The one piece of detail unique to this surface: what counts */}
          <View style={styles.sectionCard}>
            <Text style={styles.sectionTitle}>Operaciones que activan el bono</Text>
            <View style={styles.criteriaList}>
              <View style={styles.criteriaRow}>
                <Icon name="dollar-sign" size={14} color={colors.secondary} />
                <Text style={styles.criteriaItem}>Primera recarga de dólares digitales (US$20+)</Text>
              </View>
              <View style={styles.criteriaRow}>
                <Icon name="download" size={14} color={colors.secondary} />
                <Text style={styles.criteriaItem}>Primer depósito convertido a cUSD (≥ US$20)</Text>
              </View>
            </View>
            <Text style={styles.criteriaNote}>El bono se acredita en $CONFIO al equivalente a US$5.</Text>
          </View>
        </View>
      </ScrollView>

      <ReferralInputModal
        visible={showReferralModal}
        onClose={() => setShowReferralModal(false)}
        onSuccess={() => setShowReferralModal(false)}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scrollView: {
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
    paddingTop: 24,
    paddingBottom: 26,
    alignItems: 'center',
  },
  fieldEyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2,
    color: colors.violetLight,
    marginBottom: 10,
  },
  fieldUsername: {
    fontSize: 34,
    fontWeight: '800',
    color: colors.white,
    textAlign: 'center',
  },
  fieldHint: {
    fontSize: 13,
    lineHeight: 19,
    color: 'rgba(255, 255, 255, 0.85)',
    textAlign: 'center',
    marginTop: 8,
    maxWidth: 300,
  },
  fieldActions: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 20,
    alignSelf: 'stretch',
  },
  copyButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: 'rgba(255, 255, 255, 0.14)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.25)',
    borderRadius: 14,
    paddingVertical: 14,
  },
  copyButtonText: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.white,
  },
  whatsappButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: colors.white,
    borderRadius: 14,
    paddingVertical: 14,
  },
  whatsappButtonText: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.dark,
  },
  updateUsernameLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginTop: 16,
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
  rowCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: colors.background,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  rowIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.violetLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  rowText: {
    flex: 1,
  },
  rowTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.dark,
  },
  rowSubtitle: {
    fontSize: 13,
    color: colors.text.secondary,
    marginTop: 2,
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
    marginBottom: 14,
  },
  criteriaList: {
    gap: 10,
  },
  criteriaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  criteriaItem: {
    flex: 1,
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 18,
  },
  criteriaNote: {
    marginTop: 14,
    paddingTop: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    fontSize: 12,
    color: colors.text.secondary,
  },
});

export default ConfioAddressScreen;
