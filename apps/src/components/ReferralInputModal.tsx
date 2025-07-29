import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  Modal,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import { gql } from '@apollo/client';

const CHECK_REFERRAL_STATUS = gql`
  mutation CheckReferralStatus {
    checkReferralStatus {
      canSetReferrer
      timeRemainingHours
      existingReferrer
    }
  }
`;

const SET_REFERRER = gql`
  mutation SetReferrer($referrerIdentifier: String!) {
    setReferrer(referrerIdentifier: $referrerIdentifier) {
      success
      error
      referralType
      message
    }
  }
`;

interface ReferralInputModalProps {
  visible: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export const ReferralInputModal: React.FC<ReferralInputModalProps> = ({
  visible,
  onClose,
  onSuccess,
}) => {
  const [referrerInput, setReferrerInput] = useState('');
  const [inputType, setInputType] = useState<'influencer' | 'friend'>('influencer');
  const [showSuccess, setShowSuccess] = useState(false);
  
  const [checkStatus] = useMutation(CHECK_REFERRAL_STATUS);
  const [setReferrer, { loading }] = useMutation(SET_REFERRER);
  
  const [canSetReferrer, setCanSetReferrer] = useState(true);
  const [timeRemaining, setTimeRemaining] = useState<number | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (visible) {
      checkStatus().then(({ data }) => {
        if (data?.checkReferralStatus) {
          setCanSetReferrer(data.checkReferralStatus.canSetReferrer);
          setTimeRemaining(data.checkReferralStatus.timeRemainingHours);
          if (data.checkReferralStatus.existingReferrer) {
            setError(`Ya tienes registrado a: ${data.checkReferralStatus.existingReferrer}`);
          }
        }
      });
    }
  }, [visible]);

  const handleSubmit = async () => {
    if (!referrerInput.trim()) {
      setError('Por favor ingresa un código o username');
      return;
    }

    try {
      const { data } = await setReferrer({
        variables: {
          referrerIdentifier: referrerInput.trim(),
        },
      });

      if (data?.setReferrer?.success) {
        setShowSuccess(true);
        setTimeout(() => {
          onSuccess?.();
          onClose();
        }, 2000);
      } else {
        setError(data?.setReferrer?.error || 'Error al registrar referidor');
      }
    } catch (err) {
      setError('Error de conexión. Intenta de nuevo.');
    }
  };

  if (showSuccess) {
    return (
      <Modal visible={visible} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={styles.successCard}>
            <Text style={styles.successEmoji}>🎉</Text>
            <Text style={styles.successTitle}>¡Referidor Registrado!</Text>
            <Text style={styles.successMessage}>
              Cuando completes tu primera transacción, ambos recibirán 4 CONFIO
            </Text>
          </View>
        </View>
      </Modal>
    );
  }

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.modalOverlay}
      >
        <View style={styles.modalContent}>
          <View style={styles.header}>
            <Text style={styles.title}>¿Quién te invitó a Confío?</Text>
            <TouchableOpacity style={styles.closeButton} onPress={onClose}>
              <Text style={styles.closeButtonText}>✕</Text>
            </TouchableOpacity>
          </View>

          {canSetReferrer ? (
            <>
              <Text style={styles.subtitle}>
                Ingresa el código de tu amigo o el @username del influencer
              </Text>

              {timeRemaining !== null && timeRemaining < 24 && (
                <View style={styles.warningBox}>
                  <Text style={styles.warningText}>
                    ⏰ Te quedan {timeRemaining} horas para registrar un referidor
                  </Text>
                </View>
              )}

              <View style={styles.inputTypeSelector}>
                <TouchableOpacity
                  style={[
                    styles.typeButton,
                    inputType === 'influencer' && styles.typeButtonActive,
                  ]}
                  onPress={() => setInputType('influencer')}
                >
                  <Text
                    style={[
                      styles.typeButtonText,
                      inputType === 'influencer' && styles.typeButtonTextActive,
                    ]}
                  >
                    Influencer TikTok
                  </Text>
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={[
                    styles.typeButton,
                    inputType === 'friend' && styles.typeButtonActive,
                  ]}
                  onPress={() => setInputType('friend')}
                >
                  <Text
                    style={[
                      styles.typeButtonText,
                      inputType === 'friend' && styles.typeButtonTextActive,
                    ]}
                  >
                    Amigo/Familiar
                  </Text>
                </TouchableOpacity>
              </View>

              <TextInput
                style={styles.input}
                value={referrerInput}
                onChangeText={(text) => {
                  setReferrerInput(text);
                  setError('');
                }}
                placeholder={
                  inputType === 'influencer'
                    ? '@username del TikTok'
                    : 'Código o teléfono de tu amigo'
                }
                placeholderTextColor="#9CA3AF"
                autoCapitalize="none"
                autoCorrect={false}
              />

              {error ? (
                <Text style={styles.errorText}>{error}</Text>
              ) : null}

              <View style={styles.infoBox}>
                <Text style={styles.infoText}>
                  💡 Ambos recibirán 4 CONFIO ($1) cuando completes tu primera transacción
                </Text>
              </View>

              <View style={styles.buttonRow}>
                <TouchableOpacity
                  style={styles.skipButton}
                  onPress={onClose}
                >
                  <Text style={styles.skipButtonText}>Saltar</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={[styles.submitButton, loading && styles.submitButtonDisabled]}
                  onPress={handleSubmit}
                  disabled={loading}
                >
                  {loading ? (
                    <ActivityIndicator color="white" size="small" />
                  ) : (
                    <Text style={styles.submitButtonText}>Registrar</Text>
                  )}
                </TouchableOpacity>
              </View>
            </>
          ) : (
            <View style={styles.cannotSetContainer}>
              <Text style={styles.cannotSetText}>
                {error || 'El período para registrar un referidor ha expirado'}
              </Text>
              <TouchableOpacity style={styles.closeOnlyButton} onPress={onClose}>
                <Text style={styles.closeOnlyButtonText}>Cerrar</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContent: {
    backgroundColor: 'white',
    borderRadius: 20,
    width: '100%',
    maxWidth: 400,
    padding: 24,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#1F2937',
    flex: 1,
  },
  closeButton: {
    width: 32,
    height: 32,
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeButtonText: {
    fontSize: 24,
    color: '#6B7280',
  },
  subtitle: {
    fontSize: 16,
    color: '#6B7280',
    marginBottom: 20,
    lineHeight: 22,
  },
  warningBox: {
    backgroundColor: '#FEF3C7',
    padding: 12,
    borderRadius: 8,
    marginBottom: 16,
  },
  warningText: {
    fontSize: 14,
    color: '#92400E',
    textAlign: 'center',
  },
  inputTypeSelector: {
    flexDirection: 'row',
    marginBottom: 16,
    gap: 8,
  },
  typeButton: {
    flex: 1,
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    alignItems: 'center',
  },
  typeButtonActive: {
    backgroundColor: '#00BFA5',
    borderColor: '#00BFA5',
  },
  typeButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280',
  },
  typeButtonTextActive: {
    color: 'white',
  },
  input: {
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 8,
    padding: 16,
    fontSize: 16,
    marginBottom: 12,
  },
  errorText: {
    color: '#EF4444',
    fontSize: 14,
    marginBottom: 12,
  },
  infoBox: {
    backgroundColor: '#F0FDF4',
    padding: 12,
    borderRadius: 8,
    marginBottom: 20,
  },
  infoText: {
    fontSize: 14,
    color: '#166534',
    lineHeight: 20,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 12,
  },
  skipButton: {
    flex: 1,
    padding: 16,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    alignItems: 'center',
  },
  skipButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#6B7280',
  },
  submitButton: {
    flex: 1,
    padding: 16,
    borderRadius: 8,
    backgroundColor: '#00BFA5',
    alignItems: 'center',
  },
  submitButtonDisabled: {
    opacity: 0.7,
  },
  submitButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: 'white',
  },
  successCard: {
    backgroundColor: 'white',
    borderRadius: 16,
    padding: 32,
    alignItems: 'center',
    margin: 20,
  },
  successEmoji: {
    fontSize: 60,
    marginBottom: 16,
  },
  successTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: '#10B981',
    marginBottom: 8,
  },
  successMessage: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    lineHeight: 22,
  },
  cannotSetContainer: {
    alignItems: 'center',
    paddingVertical: 20,
  },
  cannotSetText: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    marginBottom: 20,
  },
  closeOnlyButton: {
    paddingHorizontal: 32,
    paddingVertical: 12,
    backgroundColor: '#F3F4F6',
    borderRadius: 8,
  },
  closeOnlyButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#374151',
  },
});