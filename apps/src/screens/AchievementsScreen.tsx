import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Share,
  Alert,
  Linking,
} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import Icon from 'react-native-vector-icons/Feather';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NavigationProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { ReferralInputModal } from '../components/ReferralInputModal';
import { buildReferralShareMessage, normalizeInviteUsername } from '../utils/inviteLinks';
import { AnalyticsService } from '../services/analyticsService';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
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

  const shareMessage = useMemo(() => {
    return buildReferralShareMessage(username || 'tuUsuario');
  }, [username]);

  const steps: Step[] = useMemo(
    () => [
      {
        title: 'Compartí tu link',
        description: 'Toca "Invitar por WhatsApp" y elige a tus amigos. El mensaje incluye tu link y la historia de Julian.',
      },
      {
        title: 'Tu amigo descubre Confío',
        description: 'Al crear su cuenta usando tu enlace, queda asociado a tu invitación.',
      },
      {
        title: 'Carga 20 cUSD y se activan los US$5 en $CONFIO',
        description:
          'Cuando tu amigo carga al menos 20 cUSD, se activan los US$5 en $CONFIO para los dos.',
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
      Alert.alert('Configura tu usuario', 'Actualiza tu perfil para crear un @usuario y comienza a invitar.');
      return;
    }
    Clipboard.setString(username);
    Alert.alert('Usuario copiado', 'Ya puedes pegar tu @usuario en WhatsApp o cualquier app.');
  };

  return (
    <View style={styles.safeArea}>
      <Header
        navigation={navigation as any}
        title="Programa de referidos"
        backgroundColor={colors.primaryDark}
        isLight
        showBackButton
      />

      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        <View style={styles.heroCard}>
          <View style={styles.heroIconWrap}>
            <Icon name="gift" size={24} color={colors.primaryDark} />
          </View>
          <Text style={styles.heroTitle}>Invitá a tus amigos a la red de confianza</Text>
          <Text style={styles.heroSubtitle}>
            Compartí la historia de Julian y por qué nació Confío.{'\n'}
            Cuando tu amigo haga su primer depósito, ambos reciben US$5 en $CONFIO como bienvenida.
          </Text>

          <View style={styles.usernamePill}>
            <Text style={styles.usernameLabel}>Tu usuario</Text>
            <Text style={styles.usernameValue}>{username || 'Configura tu @usuario'}</Text>
            {needsFriendlyUsername && (
              <Text style={styles.usernameHint}>
                Crea un usuario corto y fácil de recordar antes de compartirlo.
              </Text>
            )}
          </View>

          <View style={styles.heroActions}>
            <Button
              title="Copiar usuario"
              variant="secondary"
              onPress={handleCopy}
              icon={<Icon name="copy" size={18} color={colors.primaryDark} />}
              style={{ backgroundColor: colors.primarySoft, borderWidth: 0 }}
              textStyle={{ color: colors.primaryDark, fontSize: 14 }}
            />
            <Button
              title="Invitar por WhatsApp"
              onPress={handleShare}
              icon={<WhatsAppLogo width={18} height={18} />}
              style={{ backgroundColor: colors.primaryDark, paddingHorizontal: 18 }}
              textStyle={{ fontSize: 14 }}
            />
          </View>
          {needsFriendlyUsername && (
            <TouchableOpacity style={styles.updateUsernameButton} onPress={() => navigation.navigate('UpdateUsername')}>
              <Icon name="edit-3" size={16} color={colors.primaryDark} />
              <Text style={styles.updateUsernameText}>Actualizar mi usuario</Text>
              <Icon name="chevron-right" size={16} color={colors.primaryDark} />
            </TouchableOpacity>
          )}
        </View>

        <View style={styles.referrerCard}>
          <Text style={styles.referrerTitle}>¿Te invitó alguien?</Text>
          <Text style={styles.referrerSubtitle}>
            Poné su @usuario o número así también recibe su regalo.
          </Text>
          <TouchableOpacity style={styles.referrerButton} onPress={() => setShowReferralModal(true)}>
            <Icon name="user-plus" size={18} color={colors.primaryDark} />
            <Text style={styles.referrerButtonText}>Registrar invitador</Text>
            <Icon name="chevron-right" size={16} color={colors.primaryDark} />
          </TouchableOpacity>
        </View>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Cómo desbloquear los US$5</Text>
          {steps.map((step, index) => (
            <View key={step.title} style={styles.stepRow}>
              <View style={styles.stepNumberWrap}>
                <Text style={styles.stepNumber}>{index + 1}</Text>
              </View>
              <View style={styles.stepContent}>
                <Text style={styles.stepTitle}>{step.title}</Text>
                <Text style={styles.stepDescription}>{step.description}</Text>
              </View>
            </View>
          ))}
        </View>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Tips para compartir</Text>
          <View style={styles.tipRow}>
            <Icon name="send" size={18} color={colors.primaryDark} />
            <Text style={styles.tipText}>Usa el botón de WhatsApp para enviar el link con la historia de Julian automáticamente.</Text>
          </View>
          <View style={styles.tipRow}>
            <Icon name="check-circle" size={18} color={colors.primaryDark} />
            <Text style={styles.tipText}>Asegúrate de que tu amigo descargue la App desde tu enlace.</Text>
          </View>
          <View style={styles.tipRow}>
            <Icon name="zap" size={18} color={colors.primaryDark} />
            <Text style={styles.tipText}>Ayúdalo a completar su recarga de 20 cUSD para liberar el bono.</Text>
          </View>
        </View>

        <TouchableOpacity
          style={styles.claimCard}
          activeOpacity={0.8}
          onPress={() => navigation.navigate('ReferralRewardClaim')}
        >
          <View style={styles.claimCardContent}>
            <View style={styles.claimIconWrap}>
              <Icon name="unlock" size={20} color={colors.primaryDark} />
            </View>
            <View style={styles.claimCardText}>
              <Text style={styles.claimCardTitle}>Desbloquear recompensas</Text>
              <Text style={styles.claimCardSubtitle}>Revisa si tienes $CONFIO listos para reclamar</Text>
            </View>
            <Icon name="chevron-right" size={18} color={colors.primaryDark} />
          </View>
        </TouchableOpacity>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Operaciones que activan el bono</Text>
          <View style={styles.criteria}>
            <Text style={styles.criteriaItem}>• Primera recarga de al menos 20 cUSD</Text>
            <Text style={styles.criteriaItem}>• Primer depósito convertido automáticamente a cUSD (≥ 20 cUSD)</Text>
            <Text style={styles.criteriaNote}>El bono se acredita en $CONFIO automáticamente.</Text>
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
    padding: 20,
    paddingBottom: 32,
    gap: 16,
  },
  heroCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 24,
    shadowColor: colors.shadowBase,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 18,
    elevation: 3,
  },
  heroIconWrap: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  heroTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: colors.textFlat,
    marginBottom: 12,
  },
  heroSubtitle: {
    fontSize: 15,
    color: colors.textSecondary,
    lineHeight: 22,
  },
  usernamePill: {
    marginTop: 20,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: colors.primaryMuted,
    alignSelf: 'flex-start',
  },
  usernameLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.primaryDark,
    marginBottom: 2,
  },
  usernameValue: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  usernameHint: {
    marginTop: 6,
    fontSize: 12,
    color: colors.primaryDark,
    lineHeight: 18,
  },

  heroActions: {
    flexDirection: 'row',
    marginTop: 24,
    gap: 12,
    flexWrap: 'wrap',
  },
  claimCard: {
    backgroundColor: colors.primarySoft,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.primaryLight,
  },
  claimCardContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  claimIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  claimCardText: {
    flex: 1,
  },
  claimCardTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  claimCardSubtitle: {
    fontSize: 13,
    color: colors.textSecondary,
    marginTop: 2,
  },
  referrerCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    gap: 12,
    shadowColor: colors.shadowBase,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 14,
    elevation: 2,
  },
  referrerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.textFlat,
  },
  referrerSubtitle: {
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 19,
  },
  referrerButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
    backgroundColor: colors.primarySoft,
  },
  referrerButtonText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  updateUsernameButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 16,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 12,
    backgroundColor: colors.neutralDark,
  },
  updateUsernameText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  sectionCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    shadowColor: colors.shadowBase,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 14,
    elevation: 2,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.textFlat,
    marginBottom: 16,
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 14,
  },
  stepNumberWrap: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  stepNumber: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  stepContent: {
    flex: 1,
  },
  stepTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.textFlat,
    marginBottom: 4,
  },
  stepDescription: {
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 19,
  },
  tipRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    marginBottom: 12,
  },
  tipText: {
    flex: 1,
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 19,
  },
  criteria: {
    marginTop: 16,
    padding: 14,
    backgroundColor: colors.neutral,
    borderRadius: 12,
    gap: 6,
  },
  criteriaTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.gray700,
  },
  criteriaItem: {
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 18,
  },
  criteriaNote: {
    marginTop: 6,
    fontSize: 12,
    color: colors.primaryDark,
  },
});

export default AchievementsScreen;
