import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Share,
  Alert,
  Clipboard,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NavigationProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { ReferralInputModal } from '../components/ReferralInputModal';

const colors = {
  background: '#F3F4F6',
  surface: '#FFFFFF',
  primary: '#10B981',
  primaryMuted: '#6EE7B7',
  primaryDark: '#047857',
  text: '#111827',
  textMuted: '#6B7280',
  divider: '#E5E7EB',
};

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
    const safeUsername = username || '@tuUsuario';
    return [
      'Únete a Confío y gana US$5 en $CONFIO conmigo.',
      '',
      '1. Descarga Confío: https://confio.lat/wa',
      `2. En el registro, escribe mi usuario ${safeUsername} en "¿Quién te invitó?"`,
      '3. Completa tu primera operación válida:',
      '   • Recarga de dólares digitales (US$20+)',
      '   • Depósito de USDC + conversión a cUSD (US$20+)',
      '   • Enviar, pagar o trade P2P',
      '',
      'Cuando lo hagas, ambos recibimos el equivalente a US$5 en $CONFIO.',
    ].join('\n');
  }, [username]);

  const steps: Step[] = useMemo(
    () => [
      {
        title: 'Comparte tu usuario Confío',
        description: 'Envía tu @usuario a amigos, familia o clientes para que te mencionen al registrarse.',
      },
      {
        title: 'Tu amigo ingresa tu @usuario',
        description: 'Durante el onboarding verán "¿Quién te invitó?". Ahí deben escribir tu @usuario tal cual.',
      },
      {
        title: 'Primera operación completada',
        description:
          'Tu invitado debe completar una operación válida: recarga (US$20+), depósito USDC + conversión a cUSD (US$20+), enviar, pagar o P2P.',
      },
      {
        title: 'US$5 en $CONFIO para ambos',
        description: 'Confío acreditará el equivalente a US$5 en $CONFIO a cada uno automáticamente. Puedes repetirlo todas las veces que quieras.',
      },
    ],
    []
  );

  const handleShare = async () => {
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
      console.error('Error abriendo WhatsApp:', error);
      try {
        await Share.share({
          message: shareMessage,
          title: 'Invitación Confío',
        });
      } catch (fallbackError) {
        console.error('Error compartiendo invitación:', fallbackError);
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
    <SafeAreaView style={styles.safeArea}>
      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
          <Icon name="arrow-left" size={20} color={colors.text} />
        </TouchableOpacity>

        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>Programa de referidos Confío</Text>
          <Text style={styles.heroTitle}>US$5 en $CONFIO para ti y tu amigo</Text>
          <Text style={styles.heroSubtitle}>
            Comparte tu @usuario. Cuando tu invitado completa su primera operación válida, Confío recompensa a ambos con el equivalente a US$5 en $CONFIO.
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
            <TouchableOpacity style={styles.copyButton} onPress={handleCopy}>
              <Icon name="copy" size={18} color={colors.primaryDark} />
              <Text style={styles.copyButtonText}>Copiar usuario</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.shareButton} onPress={handleShare}>
              <Icon name="share-2" size={18} color="#fff" />
              <Text style={styles.shareButtonText}>Compartir por WhatsApp</Text>
            </TouchableOpacity>
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
          <Text style={styles.referrerTitle}>¿Quién te invitó a Confío?</Text>
          <Text style={styles.referrerSubtitle}>
            Si aún no registraste a la persona que te invitó, ingresa su @usuario o número de teléfono para que también reciba el bono.
          </Text>
          <TouchableOpacity style={styles.referrerButton} onPress={() => setShowReferralModal(true)}>
            <Icon name="user-plus" size={18} color={colors.primaryDark} />
            <Text style={styles.referrerButtonText}>Registrar invitador</Text>
            <Icon name="chevron-right" size={16} color={colors.primaryDark} />
          </TouchableOpacity>
        </View>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Cómo reclamar los US$5</Text>
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
            <Text style={styles.tipText}>Incluye tu @usuario en mensajes de WhatsApp, Telegram o redes sociales.</Text>
          </View>
          <View style={styles.tipRow}>
            <Icon name="check-circle" size={18} color={colors.primaryDark} />
            <Text style={styles.tipText}>Recuérdale a tu amigo escribir tu @usuario al registrarse.</Text>
          </View>
          <View style={styles.tipRow}>
            <Icon name="zap" size={18} color={colors.primaryDark} />
            <Text style={styles.tipText}>Ayúdalo a completar su primera compra o envío para activar la recompensa.</Text>
          </View>
        </View>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>¿Qué verás aquí pronto?</Text>
          <Text style={styles.futureText}>
            Estamos simplificando el programa de logros para enfocarlo 100% en invitaciones. Pronto tendrás el resumen
            de invitaciones completadas y tus recompensas en esta pantalla.
          </Text>
          <View style={styles.criteria}>
            <Text style={styles.criteriaTitle}>Operaciones válidas para el bono:</Text>
            <Text style={styles.criteriaItem}>• Primera recarga de dólares digitales mayor a US$20</Text>
            <Text style={styles.criteriaItem}>• Primer depósito de USDC convertido a cUSD (≥ US$20)</Text>
            <Text style={styles.criteriaItem}>• Primer envío dentro de Confío</Text>
            <Text style={styles.criteriaItem}>• Primer pago a comercio con Confío</Text>
            <Text style={styles.criteriaItem}>• Primer trade P2P completado</Text>
            <Text style={styles.criteriaNote}>El bono se acredita en $CONFIO al tipo equivalente a US$5.</Text>
          </View>
        </View>

        <ReferralInputModal
          visible={showReferralModal}
          onClose={() => setShowReferralModal(false)}
          onSuccess={() => setShowReferralModal(false)}
        />

        <View style={styles.bottomSpacer} />
      </ScrollView>
    </SafeAreaView>
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
    paddingHorizontal: 20,
    paddingBottom: 32,
  },
  backButton: {
    alignSelf: 'flex-start',
    paddingVertical: 8,
    marginBottom: 12,
  },
  heroCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 24,
    marginBottom: 24,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 18,
    elevation: 3,
  },
  heroEyebrow: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.primaryDark,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 8,
  },
  heroTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 12,
  },
  heroSubtitle: {
    fontSize: 15,
    color: colors.textMuted,
    lineHeight: 22,
  },
  usernamePill: {
    marginTop: 20,
    borderRadius: 14,
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
  copyButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    backgroundColor: '#ECFDF5',
    gap: 8,
  },
  copyButtonText: {
    color: colors.primaryDark,
    fontWeight: '600',
    fontSize: 14,
  },
  shareButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 18,
    borderRadius: 12,
    backgroundColor: colors.primaryDark,
    gap: 8,
  },
  shareButtonText: {
    color: '#FFFFFF',
    fontWeight: '600',
    fontSize: 14,
  },
  referrerCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 20,
    marginBottom: 20,
    gap: 12,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 14,
    elevation: 2,
  },
  referrerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  referrerSubtitle: {
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 19,
  },
  referrerButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
    backgroundColor: '#ECFDF5',
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
    backgroundColor: '#F3F4F6',
  },
  updateUsernameText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  sectionCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 20,
    marginBottom: 20,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 14,
    elevation: 2,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
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
    backgroundColor: '#ECFDF5',
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
    color: colors.text,
    marginBottom: 4,
  },
  stepDescription: {
    fontSize: 13,
    color: colors.textMuted,
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
    color: colors.textMuted,
    lineHeight: 19,
  },
  criteria: {
    marginTop: 16,
    padding: 14,
    backgroundColor: '#F9FAFB',
    borderRadius: 12,
    gap: 6,
  },
  criteriaTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: '#374151',
  },
  criteriaItem: {
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 18,
  },
  criteriaNote: {
    marginTop: 6,
    fontSize: 12,
    color: colors.primaryDark,
  },
  futureText: {
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 20,
  },
  bottomSpacer: {
    height: 32,
  },
});

export default AchievementsScreen;
