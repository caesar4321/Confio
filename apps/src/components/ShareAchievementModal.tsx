import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Modal,
  TextInput,
  Image,
  Linking,
  Alert,
} from 'react-native';
import { useMutation } from '@apollo/client';
import { gql } from '@apollo/client';
import WhatsAppIcon from '../assets/svg/WhatsApp.svg';

const TRACK_TIKTOK_SHARE = gql`
  mutation TrackTikTokShare($achievementId: ID!, $tiktokUrl: String!) {
    trackTikTokShare(achievementId: $achievementId, tiktokUrl: $tiktokUrl) {
      success
      shareId
      error
    }
  }
`;

interface ShareAchievementModalProps {
  visible: boolean;
  onClose: () => void;
  achievement: {
    id: string;
    name: string;
    description: string;
    confioReward: number;
    category: string;
  };
}

export const ShareAchievementModal: React.FC<ShareAchievementModalProps> = ({
  visible,
  onClose,
  achievement,
}) => {
  const [tiktokUrl, setTiktokUrl] = useState('');
  const [showTikTokForm, setShowTikTokForm] = useState(false);
  const [trackTikTokShare] = useMutation(TRACK_TIKTOK_SHARE);

  const getShareMessage = () => {
    const baseMessage = `🎉 ¡Acabo de ganar ${achievement.confioReward} $CONFIO en la app Confío!`;
    
    const categoryMessages = {
      bienvenida: `${baseMessage}\n\n🚀 Me uní a la app que está cambiando como enviamos dólares en LATAM`,
      verificacion: `${baseMessage}\n\n✅ Mi cuenta está verificada y lista para enviar dólares`,
      trading: `${baseMessage}\n\n💱 Comprando y vendiendo dólares sin comisiones`,
      viral: `${baseMessage}\n\n🌟 Mi contenido sobre Confío está explotando en TikTok`,
      embajador: `${baseMessage}\n\n👑 Soy embajador oficial de Confío`,
    };

    const message = categoryMessages[achievement.category] || baseMessage;
    
    return `${message}\n\n📱 Descarga Confío y empieza a ganar:\nhttps://confio.lat\n\n#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital`;
  };

  const handleWhatsAppShare = () => {
    const message = getShareMessage();
    const url = `whatsapp://send?text=${encodeURIComponent(message)}`;
    
    Linking.openURL(url).catch(() => {
      Alert.alert('Error', 'No se pudo abrir WhatsApp');
    });
    
    onClose();
  };

  const handleTikTokShare = () => {
    setShowTikTokForm(true);
  };

  const handleGetTikTokInfo = () => {
    Alert.alert(
      '🎬 Contenido para TikTok',
      `¡Comparte tu experiencia con Confío!\n\n💡 Ideas para tu video:\n• Tu historia usando Confío\n• Comparar Confío vs bancos tradicionales\n• Mostrar la velocidad de las transacciones\n• Explicar cómo ahorras dinero\n\n🏆 Logro: ${achievement.name}\n💰 Ganaste: ${achievement.confioReward} $CONFIO\n\n📱 Hashtags: #Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital\n\n🔗 Descarga: confio.lat`,
      [
        { text: 'Crear Video', onPress: () => setShowTikTokForm(true) }
      ]
    );
  };


  const submitTikTokUrl = async () => {
    if (!tiktokUrl.trim()) {
      Alert.alert('Error', 'Por favor ingresa el link de tu TikTok');
      return;
    }

    // Basic TikTok URL validation
    const tiktokRegex = /^https?:\/\/(www\.)?(tiktok\.com|vm\.tiktok\.com)/;
    if (!tiktokRegex.test(tiktokUrl)) {
      Alert.alert('Error', 'Por favor ingresa un link válido de TikTok');
      return;
    }

    try {
      const { data } = await trackTikTokShare({
        variables: {
          achievementId: achievement.id,
          tiktokUrl: tiktokUrl.trim(),
        },
      });

      if (data?.trackTikTokShare?.success) {
        Alert.alert(
          '¡Excelente!',
          'Tu video ha sido registrado. Las vistas se actualizarán automáticamente cada hora.',
          [{ text: 'OK', onPress: onClose }]
        );
        setTiktokUrl('');
        setShowTikTokForm(false);
      } else {
        Alert.alert('Error', data?.trackTikTokShare?.error || 'No se pudo registrar tu video');
      }
    } catch (error) {
      Alert.alert('Error', 'Ocurrió un error al registrar tu video');
    }
  };

  const getTikTokHashtags = () => {
    return '#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital';
  };

  if (showTikTokForm) {
    return (
      <Modal
        visible={visible}
        animationType="slide"
        transparent={true}
        onRequestClose={onClose}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Comparte en TikTok</Text>
            
            <View style={styles.instructionsContainer}>
              <Text style={styles.instructionTitle}>🎬 Crea tu TikTok:</Text>
              <Text style={styles.instruction}>1. Cuenta tu historia usando Confío</Text>
              <Text style={styles.instruction}>2. Muestra tu experiencia real</Text>
              <Text style={styles.instruction}>3. Usa estos hashtags:</Text>
              <Text style={styles.hashtags}>{getTikTokHashtags()}</Text>
              <Text style={styles.instruction}>4. Sube el video a TikTok</Text>
              <Text style={styles.instruction}>5. Pega el link del video aquí:</Text>
            </View>

            <TextInput
              style={styles.input}
              placeholder="https://www.tiktok.com/@usuario/video/..."
              value={tiktokUrl}
              onChangeText={setTiktokUrl}
              autoCapitalize="none"
              autoCorrect={false}
            />

            <TouchableOpacity
              style={styles.generateImageButton}
              onPress={handleGetTikTokInfo}
              activeOpacity={0.7}
            >
              <Text style={styles.generateImageButtonText}>
                💡 Ideas para tu Video
              </Text>
            </TouchableOpacity>

            <View style={styles.buttonRow}>
              <TouchableOpacity
                style={[styles.button, styles.cancelButton]}
                onPress={() => {
                  setShowTikTokForm(false);
                  setTiktokUrl('');
                }}
              >
                <Text style={styles.cancelButtonText}>Cancelar</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.button, styles.submitButton]}
                onPress={submitTikTokUrl}
              >
                <Text style={styles.submitButtonText}>Registrar Video</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    );
  }

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent={true}
      onRequestClose={onClose}
    >
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <Text style={styles.modalTitle}>Compartir Logro</Text>
          <Text style={styles.achievementName}>{achievement.name}</Text>
          <Text style={styles.achievementReward}>{achievement.confioReward} $CONFIO</Text>

          <View style={styles.shareOptions}>
            <TouchableOpacity style={styles.shareOption} onPress={handleTikTokShare}>
              <Image source={require('../assets/png/TikTok.png')} style={styles.tiktokIcon} />
              <Text style={styles.shareOptionText}>TikTok</Text>
              <Text style={styles.shareOptionSubtext}>Gana vistas = Más $CONFIO</Text>
            </TouchableOpacity>

            <TouchableOpacity style={styles.shareOption} onPress={handleWhatsAppShare}>
              <WhatsAppIcon width={40} height={40} />
              <Text style={styles.shareOptionText}>WhatsApp</Text>
              <Text style={styles.shareOptionSubtext}>Comparte con amigos</Text>
            </TouchableOpacity>
          </View>

          <TouchableOpacity style={styles.closeButton} onPress={onClose}>
            <Text style={styles.closeButtonText}>Cerrar</Text>
          </TouchableOpacity>
        </View>
      </View>

    </Modal>
  );
};

const styles = StyleSheet.create({
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 20,
  },
  modalContent: {
    backgroundColor: 'white',
    borderRadius: 20,
    padding: 24,
    width: '100%',
    maxWidth: 360,
    alignSelf: 'center',
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.25,
    shadowRadius: 3.84,
    elevation: 5,
  },
  modalTitle: {
    fontSize: 22,
    fontWeight: '700',
    textAlign: 'center',
    marginBottom: 12,
    color: '#1a1a1a',
  },
  achievementName: {
    fontSize: 18,
    textAlign: 'center',
    color: '#495057',
    marginBottom: 8,
    fontWeight: '500',
  },
  achievementReward: {
    fontSize: 24,
    fontWeight: '700',
    textAlign: 'center',
    color: '#00BFA5',
    marginBottom: 28,
  },
  shareOptions: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 24,
    gap: 12,
  },
  shareOption: {
    flex: 1,
    alignItems: 'center',
    padding: 16,
    borderRadius: 16,
    backgroundColor: '#f8f9fa',
    borderWidth: 1,
    borderColor: '#e9ecef',
  },
  tiktokIcon: {
    width: 40,
    height: 40,
    marginBottom: 8,
  },
  shareOptionText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#212529',
    marginBottom: 4,
  },
  shareOptionSubtext: {
    fontSize: 12,
    color: '#6c757d',
    textAlign: 'center',
    lineHeight: 16,
  },
  closeButton: {
    backgroundColor: '#f8f9fa',
    paddingVertical: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e9ecef',
  },
  closeButtonText: {
    textAlign: 'center',
    color: '#495057',
    fontSize: 16,
    fontWeight: '600',
  },
  instructionsContainer: {
    backgroundColor: '#e8f5f3',
    padding: 16,
    borderRadius: 12,
    marginBottom: 20,
    borderWidth: 1,
    borderColor: '#c3e9e2',
  },
  instructionTitle: {
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 12,
    color: '#00BFA5',
  },
  instruction: {
    fontSize: 14,
    color: '#495057',
    marginBottom: 8,
    lineHeight: 20,
  },
  hashtags: {
    fontSize: 13,
    color: '#00BFA5',
    marginLeft: 16,
    marginBottom: 8,
    fontWeight: '600',
  },
  input: {
    borderWidth: 1,
    borderColor: '#ced4da',
    borderRadius: 10,
    padding: 14,
    fontSize: 15,
    marginBottom: 20,
    backgroundColor: '#fff',
  },
  buttonRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  button: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
  },
  cancelButton: {
    backgroundColor: '#f8f9fa',
    borderWidth: 1,
    borderColor: '#e9ecef',
  },
  cancelButtonText: {
    textAlign: 'center',
    color: '#495057',
    fontSize: 16,
    fontWeight: '600',
  },
  submitButton: {
    backgroundColor: '#00BFA5',
    shadowColor: '#00BFA5',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.2,
    shadowRadius: 3,
    elevation: 3,
  },
  submitButtonText: {
    textAlign: 'center',
    color: 'white',
    fontSize: 16,
    fontWeight: '700',
  },
  generateImageButton: {
    backgroundColor: '#8B5CF6',
    paddingVertical: 14,
    borderRadius: 12,
    marginBottom: 16,
    shadowColor: '#8B5CF6',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.2,
    shadowRadius: 3,
    elevation: 3,
  },
  generateImageButtonText: {
    textAlign: 'center',
    color: 'white',
    fontSize: 16,
    fontWeight: '700',
  },
});