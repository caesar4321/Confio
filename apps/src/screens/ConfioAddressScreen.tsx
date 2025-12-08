import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Share,
  Alert,
  Clipboard,
  Linking,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, NavigationProp } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { Header } from '../navigation/Header';
import { ReferralInputModal } from '../components/ReferralInputModal';

const colors = {
  background: '#F3F4F6',
  surface: '#FFFFFF',
  primary: '#10B981',
  primaryDark: '#047857',
  primaryLight: '#ECFDF5',
  text: '#111827',
  textMuted: '#6B7280',
};

export const ConfioAddressScreen: React.FC = () => {
  const navigation = useNavigation<NavigationProp<RootStackParamList>>();
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

  const shareMessage = React.useMemo(() => {
    // Generate clean, uppercase username for the link
    const rawName = (username || 'tuUsuario').replace('@', '');
    const cleanUsername = rawName.toUpperCase();
    const inviteLink = `https://confio.lat/invite/${cleanUsername}`;

    return [
      'Únete a Confío y gana US$5 en $CONFIO conmigo.',
      '',
      `📲 Descarga la App aquí: ${inviteLink}`,
      '',
      `Mi código de invitado es: ${cleanUsername}`,
      '',
      'Completa tu primera operación válida (recarga, depósito o P2P) y ambos recibiremos US$5 en $CONFIO.',
    ].join('\n');
  }, [username]);

  const handleCopy = React.useCallback(() => {
    if (!username) {
      Alert.alert('Configura tu usuario', 'Edita tu perfil para crear un @usuario y poder compartirlo.');
      return;
    }
    Clipboard.setString(username);
    Alert.alert('Usuario copiado', 'Comparte tu @usuario para que tus amigos lo ingresen al registrarse.');
  }, [username]);

  const handleShare = React.useCallback(async () => {
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
  }, [shareMessage]);

  const steps = [
    'Copia tu @usuario de Confío y envíalo por WhatsApp, SMS o redes.',
    'Tu amigo abre Confío y, en "¿Quién te invitó?", escribe tu @usuario exacto.',
    'Acompáñalo hasta completar su primera operación válida. Cuando se confirme, ambos reciben el equivalente a US$5 en $CONFIO.',
  ];

  const friendTips = [
    'Tu @usuario siempre empieza con "@" y no distingue mayúsculas.',
    'La recompensa se libera cuando tu amigo completa su primera operación válida en Confío.',
    'Puedes invitar a todos los amigos que quieras. No hay límite de recompensas.',
  ];

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title="Comparte tu usuario Confío"
        backgroundColor={colors.primary}
        isLight={true}
        showBackButton={true}
      />

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.content}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>Programa de referidos</Text>
          <Text style={styles.heroTitle}>Invita y ganen US$5 en $CONFIO</Text>
          <Text style={styles.heroSubtitle}>
            Solo necesitas compartir tu @usuario. Pide a tus amigos escribirlo cuando Confío les pregunte "¿Quién te
            invitó?" y acompáñalos hasta completar la primera operación válida para que ambos reciban US$5 en $CONFIO.
          </Text>
        </View>

        <View style={styles.usernameCard}>
          <Text style={styles.usernameLabel}>Tu usuario Confío</Text>
          <Text style={styles.usernameValue}>{username || 'Configura tu @usuario'}</Text>
          {needsFriendlyUsername && (
            <TouchableOpacity style={styles.updateUsernameButton} onPress={() => navigation.navigate('UpdateUsername')}>
              <Icon name="edit-3" size={16} color={colors.primaryDark} />
              <Text style={styles.updateUsernameText}>Actualizar mi usuario</Text>
              <Icon name="chevron-right" size={16} color={colors.primaryDark} />
            </TouchableOpacity>
          )}
          <View style={styles.usernameActions}>
            <TouchableOpacity style={styles.copyButton} onPress={handleCopy}>
              <Icon name="copy" size={16} color={colors.primaryDark} />
              <Text style={styles.copyButtonText}>Copiar</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.shareButton} onPress={handleShare}>
              <Icon name="share-2" size={16} color="#FFFFFF" />
              <Text style={styles.shareButtonText}>Compartir por WhatsApp</Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Cómo reclamar la recompensa</Text>
          {steps.map((step, index) => (
            <View key={step} style={styles.stepRow}>
              <View style={styles.stepNumber}>
                <Text style={styles.stepNumberText}>{index + 1}</Text>
              </View>
              <Text style={styles.stepText}>{step}</Text>
            </View>
          ))}
        </View>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Tips para tus invitados</Text>
          {friendTips.map((tip) => (
            <View key={tip} style={styles.tipRow}>
              <Icon name="check-circle" size={18} color={colors.primaryDark} />
              <Text style={styles.tipText}>{tip}</Text>
            </View>
          ))}
        </View>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Operaciones que activan el bono</Text>
          <Text style={styles.reasonText}>Tu invitado debe completar una de estas acciones para liberar el bono:</Text>
          <View style={styles.criteriaList}>
            <Text style={styles.criteriaItem}>• Primera recarga de dólares digitales mayor a US$20</Text>
            <Text style={styles.criteriaItem}>• Primer depósito de USDC convertido a cUSD (≥ US$20)</Text>
            <Text style={styles.criteriaItem}>• Primer envío dentro de Confío</Text>
            <Text style={styles.criteriaItem}>• Primer pago a comercio con Confío</Text>
            <Text style={styles.criteriaItem}>• Primer trade P2P completado</Text>
          </View>
          <Text style={styles.criteriaNote}>El bono se acredita en $CONFIO al tipo equivalente a US$5.</Text>
        </View>

        <TouchableOpacity style={styles.referralButton} onPress={() => setShowReferralModal(true)}>
          <Icon name="user-plus" size={18} color={colors.primaryDark} />
          <Text style={styles.referralButtonText}>Registrar quién te invitó</Text>
          <Icon name="chevron-right" size={16} color={colors.primaryDark} />
        </TouchableOpacity>
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
    padding: 20,
    paddingBottom: 32,
    gap: 16,
  },
  heroCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 24,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.08,
    shadowRadius: 16,
    elevation: 3,
  },
  heroEyebrow: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.primaryDark,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 8,
  },
  heroTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 12,
  },
  heroSubtitle: {
    fontSize: 14,
    color: colors.textMuted,
    lineHeight: 20,
  },
  usernameCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 20,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.06,
    shadowRadius: 12,
    elevation: 2,
    gap: 16,
  },
  usernameLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.primaryDark,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  usernameValue: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
  },
  usernameActions: {
    flexDirection: 'row',
    gap: 12,
  },
  updateUsernameButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 8,
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
  copyButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    paddingVertical: 12,
    backgroundColor: colors.primaryLight,
    gap: 8,
  },
  copyButtonText: {
    color: colors.primaryDark,
    fontWeight: '600',
    fontSize: 14,
  },
  shareButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    paddingVertical: 12,
    backgroundColor: colors.primaryDark,
    gap: 8,
  },
  shareButtonText: {
    color: '#FFFFFF',
    fontWeight: '600',
    fontSize: 14,
  },
  sectionCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 20,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 14,
    elevation: 2,
    gap: 14,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  stepNumber: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepNumberText: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  stepText: {
    flex: 1,
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 19,
  },
  tipRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  tipText: {
    flex: 1,
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 19,
  },
  reasonText: {
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 20,
  },
  criteriaList: {
    gap: 6,
  },
  criteriaItem: {
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 18,
  },
  criteriaNote: {
    marginTop: 8,
    fontSize: 12,
    color: colors.primaryDark,
  },
  referralButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 12,
    backgroundColor: '#ECFDF5',
  },
  referralButtonText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
});

export default ConfioAddressScreen;
