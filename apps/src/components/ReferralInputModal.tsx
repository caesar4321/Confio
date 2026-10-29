import React, { useState, useEffect } from 'react';
import { ReferralSuccessModal } from './ReferralSuccessModal';
import {
  View,
  Modal,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Alert,
  ScrollView,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text, TextInput } from './common/AppText';
import { useMutation } from '@apollo/client';
import { gql } from '@apollo/client';
import { colors } from '../config/theme';
import { Button } from './common/Button';

const CHECK_REFERRAL_STATUS = gql`
  mutation CheckReferralStatus {
    checkReferralStatus {
      existingReferrer
    }
  }
`;

const SET_REFERRER = gql`
  mutation SetReferrer($referrerIdentifier: String!, $referralType: String) {
    setReferrer(referrerIdentifier: $referrerIdentifier, referralType: $referralType) {
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
  const insets = useSafeAreaInsets();
  const [referrerInput, setReferrerInput] = useState('');
  const [showSuccess, setShowSuccess] = useState(false);
  const [checkStatus] = useMutation(CHECK_REFERRAL_STATUS);
  const [setReferrer, { loading }] = useMutation(SET_REFERRER);

  const [canSetReferrer, setCanSetReferrer] = useState(true);
  const [existingReferrer, setExistingReferrer] = useState<string | null>(null);
  const [error, setError] = useState('');

  const formatErrorMessage = (rawMessage: string | undefined | null) => {
    if (!rawMessage) {
      return 'Error al registrar referidor';
    }

    if (/rate limit/i.test(rawMessage)) {
      const minutesMatch = rawMessage.match(/(\d+)\s*minutes?/i);
      if (minutesMatch) {
        const minutes = minutesMatch[1];
        return `Has intentado demasiadas veces. Por favor espera ${minutes} minuto${minutes === '1' ? '' : 's'} antes de intentar nuevamente.`;
      }
      return 'Has intentado demasiadas veces. Por favor espera unos minutos antes de intentar nuevamente.';
    }

    if (/suspicious/i.test(rawMessage)) {
      return 'Detectamos actividad inusual. Por favor contacta a soporte.';
    }

    return rawMessage;
  };

  useEffect(() => {
    if (visible) {
      checkStatus().then(({ data }) => {
        if (data?.checkReferralStatus) {
          const registered = data.checkReferralStatus.existingReferrer || null;
          setExistingReferrer(registered);
          const allowed = !registered;
          setCanSetReferrer(allowed);
          if (registered) {
            setError(`Ya registraste a: ${registered}`);
          } else {
            setError('');
          }
        }
      }).catch(() => {});
    }
  }, [visible]);

  const handleSubmit = async () => {
    if (!referrerInput.trim()) {
      setError('Escribe el @usuario de quien te invitó');
      return;
    }

    let finalIdentifier = referrerInput.trim();

    // Add @ prefix for usernames if not present
    if (!finalIdentifier.startsWith('@')) {
      finalIdentifier = '@' + finalIdentifier;
    }

    try {
      const { data, errors } = await setReferrer({
        variables: {
          referrerIdentifier: finalIdentifier,
          referralType: 'friend',
        },
      });

      if (errors && errors.length > 0) {
        const friendly = formatErrorMessage(errors[0].message);
        setError(friendly);
        Alert.alert('Aviso', friendly, [{ text: 'Entendido' }]);
        return;
      }

      if (data?.setReferrer?.success) {
        setShowSuccess(true);
        // Let the modal auto-close logic handle it, or the user manually closes
        // Note: ReferralSuccessModal has its own timeout and manual close
      } else {
        const friendly = formatErrorMessage(data?.setReferrer?.error);
        setError(friendly);
        Alert.alert('Aviso', friendly, [{ text: 'Entendido' }]);
      }
    } catch (err: any) {
      // Try to extract a meaningful error message
      const errorMessage = err?.graphQLErrors?.[0]?.message || err?.message;
      if (errorMessage) {
        const friendly = formatErrorMessage(errorMessage);
        setError(friendly);
        Alert.alert("Error", friendly, [{ text: 'Entendido' }]);
      } else {
        setError('Error de conexión. Intenta de nuevo.');
        Alert.alert("Error", "Error de conexión. Intenta de nuevo.", [{ text: 'Entendido' }]);
      }
    }
  };

  if (showSuccess) {
    return (
      <ReferralSuccessModal
        visible={visible}
        onClose={() => {
          onSuccess?.();
          onClose();
        }}
      />
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
        style={[
          styles.modalOverlay,
          { paddingTop: Math.max(insets.top, 20), paddingBottom: Math.max(insets.bottom, 20) },
        ]}
      >
        <View style={styles.modalContent}>
          <View style={styles.header}>
            <Text style={styles.title}>¿Quién te invitó a Confío?</Text>
            <TouchableOpacity style={styles.closeButton} onPress={onClose}>
              <Text style={styles.closeButtonText}>✕</Text>
            </TouchableOpacity>
          </View>

          {/* Large system fonts (or the keyboard) outgrow the card: the body
              scrolls so Registrar/Saltar stay reachable. */}
          <ScrollView style={styles.body} bounces={false} keyboardShouldPersistTaps="handled">
          {canSetReferrer ? (
            <>
              <Text style={styles.subtitle}>
                Escribe el @usuario de la persona que te invitó. Lo encuentras en su perfil de Confío. Puedes registrarlo en cualquier momento.
              </Text>

              <View style={styles.usernameInputContainer}>
                <Text style={styles.atPrefix}>@</Text>
                <TextInput
                  style={styles.usernameInput}
                  value={referrerInput}
                  onChangeText={(text) => {
                    // Remove @ if user types it
                    setReferrerInput(text.replace('@', ''));
                    setError('');
                  }}
                  placeholder="usuario de Confío"
                  placeholderTextColor="#9CA3AF"
                  autoCapitalize="none"
                  autoCorrect={false}
                />
              </View>

              {error ? (
                <Text style={styles.errorText}>{error}</Text>
              ) : null}

              <View style={styles.infoBox}>
                <Text style={styles.infoText}>
                  💡 Ambos recibirán el equivalente a US$5 en $CONFIO cuando completes tu primera recarga o ahorro de al menos US$20.
                </Text>
              </View>

              <View style={styles.buttonRow}>
                <Button
                  title="Saltar"
                  variant="secondary"
                  onPress={onClose}
                  style={{ flex: 1 }}
                />
                <Button
                  title="Registrar"
                  onPress={handleSubmit}
                  loading={loading}
                  accessibilityLabel="Registrar referidor"
                  style={{ flex: 1 }}
                />
              </View>
            </>
          ) : (
            <View style={styles.cannotSetContainer}>
              <Text style={styles.cannotSetText}>
                {error ||
                  (existingReferrer
                    ? `Ya registraste a ${existingReferrer}.`
                    : 'No es posible registrar un referidor en este momento.')}
              </Text>
              <TouchableOpacity style={styles.closeOnlyButton} onPress={onClose}>
                <Text style={styles.closeOnlyButtonText}>Cerrar</Text>
              </TouchableOpacity>
            </View>
          )}
          </ScrollView>
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
    maxHeight: '100%',
    padding: 24,
  },
  body: {
    flexShrink: 1,
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
    backgroundColor: colors.primaryDark,
    borderColor: colors.primaryDark,
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
  phoneInputContainer: {
    flexDirection: 'row',
    marginBottom: 12,
    gap: 8,
  },
  countryCodeButton: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 16,
    gap: 4,
  },
  countryCodeText: {
    fontSize: 16,
    color: '#1F2937',
  },
  phoneInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 8,
    padding: 16,
    fontSize: 16,
  },
  usernameInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 8,
    marginBottom: 12,
  },
  atPrefix: {
    paddingLeft: 16,
    paddingRight: 4,
    fontSize: 16,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  usernameInput: {
    flex: 1,
    padding: 16,
    paddingLeft: 0,
    fontSize: 16,
  },
  pickerOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'flex-end',
  },
  pickerContent: {
    backgroundColor: 'white',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: '80%',
  },
  pickerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  pickerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1F2937',
  },
  pickerCloseButton: {
    padding: 4,
  },
  // Exactly the 65 getItemLayout declares, however long the name or large
  // the system text: the name truncates rather than growing the row.
  countryItem: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 65,
    paddingHorizontal: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
  },
  countryItemSelected: {
    backgroundColor: '#F0FDF4',
  },
  countryFlag: {
    marginRight: 12,
  },
  countryName: {
    flex: 1,
    fontSize: 16,
    color: '#1F2937',
  },
  countryCode: {
    fontSize: 16,
    color: '#6B7280',
    marginRight: 12,
  },
});
