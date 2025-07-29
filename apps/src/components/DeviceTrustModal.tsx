/**
 * Device Trust Verification Modal
 * Shows when a new device needs to be trusted for security purposes
 */

import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TouchableOpacity,
  TextInput,
  Alert,
  ActivityIndicator,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { EnhancedAuthService } from '../services/enhancedAuthService';

interface DeviceTrustModalProps {
  visible: boolean;
  onClose: () => void;
  onTrustVerified: () => void;
}

const colors = {
  primary: '#72D9BC',
  secondary: '#8B5CF6',
  background: '#FFFFFF',
  text: '#1F2937',
  textSecondary: '#6B7280',
  error: '#EF4444',
  success: '#10B981',
  border: '#E5E7EB',
};

export const DeviceTrustModal: React.FC<DeviceTrustModalProps> = ({
  visible,
  onClose,
  onTrustVerified,
}) => {
  const [step, setStep] = useState<'info' | 'request' | 'verify'>('info');
  const [verificationCode, setVerificationCode] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [method, setMethod] = useState<'email' | 'sms'>('email');

  const enhancedAuthService = EnhancedAuthService.getInstance();

  const handleRequestCode = async () => {
    setIsLoading(true);
    try {
      const result = await enhancedAuthService.requestDeviceTrust(method);
      
      if (result.success) {
        setStep('verify');
        Alert.alert(
          'Código enviado',
          result.message || `Código de verificación enviado a tu ${method === 'email' ? 'correo' : 'teléfono'}`
        );
      } else {
        Alert.alert('Error', result.error || 'No se pudo enviar el código de verificación');
      }
    } catch (error) {
      console.error('Error requesting device trust:', error);
      Alert.alert('Error', 'Error al solicitar verificación del dispositivo');
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerifyCode = async () => {
    if (!verificationCode || verificationCode.length !== 6) {
      Alert.alert('Error', 'Por favor ingresa un código de 6 dígitos válido');
      return;
    }

    setIsLoading(true);
    try {
      const result = await enhancedAuthService.verifyDeviceTrust(verificationCode);
      
      if (result.success) {
        Alert.alert(
          'Dispositivo verificado',
          'Tu dispositivo ha sido marcado como confiable',
          [
            {
              text: 'OK',
              onPress: () => {
                onTrustVerified();
                onClose();
              },
            },
          ]
        );
      } else {
        Alert.alert('Error', result.error || 'Código de verificación inválido');
        setVerificationCode('');
      }
    } catch (error) {
      console.error('Error verifying device trust:', error);
      Alert.alert('Error', 'Error al verificar el dispositivo');
    } finally {
      setIsLoading(false);
    }
  };

  const renderInfoStep = () => (
    <View style={styles.stepContainer}>
      <View style={styles.iconContainer}>
        <Icon name="shield" size={48} color={colors.secondary} />
      </View>
      
      <Text style={styles.title}>Nuevo Dispositivo Detectado</Text>
      <Text style={styles.description}>
        Por tu seguridad, necesitamos verificar que eres tú quien está usando este dispositivo.
        Esto es un proceso único que ayuda a proteger tu cuenta.
      </Text>

      <View style={styles.benefitsList}>
        <View style={styles.benefitItem}>
          <Icon name="check-circle" size={20} color={colors.success} />
          <Text style={styles.benefitText}>Protección contra accesos no autorizados</Text>
        </View>
        <View style={styles.benefitItem}>
          <Icon name="check-circle" size={20} color={colors.success} />
          <Text style={styles.benefitText}>Verificación única por dispositivo</Text>
        </View>
        <View style={styles.benefitItem}>
          <Icon name="check-circle" size={20} color={colors.success} />
          <Text style={styles.benefitText}>Mayor seguridad para tus transacciones</Text>
        </View>
      </View>

      <TouchableOpacity
        style={styles.primaryButton}
        onPress={() => setStep('request')}
      >
        <Text style={styles.primaryButtonText}>Verificar Dispositivo</Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.secondaryButton}
        onPress={onClose}
      >
        <Text style={styles.secondaryButtonText}>Omitir por ahora</Text>
      </TouchableOpacity>
    </View>
  );

  const renderRequestStep = () => (
    <View style={styles.stepContainer}>
      <View style={styles.iconContainer}>
        <Icon name="mail" size={48} color={colors.primary} />
      </View>
      
      <Text style={styles.title}>Elegir Método de Verificación</Text>
      <Text style={styles.description}>
        ¿Cómo prefieres recibir tu código de verificación?
      </Text>

      <View style={styles.methodContainer}>
        <TouchableOpacity
          style={[
            styles.methodButton,
            method === 'email' && styles.methodButtonActive,
          ]}
          onPress={() => setMethod('email')}
        >
          <Icon
            name="mail"
            size={24}
            color={method === 'email' ? colors.primary : colors.textSecondary}
          />
          <Text
            style={[
              styles.methodButtonText,
              method === 'email' && styles.methodButtonTextActive,
            ]}
          >
            Correo Electrónico
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[
            styles.methodButton,
            method === 'sms' && styles.methodButtonActive,
          ]}
          onPress={() => setMethod('sms')}
        >
          <Icon
            name="message-circle"
            size={24}
            color={method === 'sms' ? colors.primary : colors.textSecondary}
          />
          <Text
            style={[
              styles.methodButtonText,
              method === 'sms' && styles.methodButtonTextActive,
            ]}
          >
            SMS
          </Text>
        </TouchableOpacity>
      </View>

      <TouchableOpacity
        style={[styles.primaryButton, isLoading && styles.buttonDisabled]}
        onPress={handleRequestCode}
        disabled={isLoading}
      >
        {isLoading ? (
          <ActivityIndicator color={colors.background} />
        ) : (
          <Text style={styles.primaryButtonText}>Enviar Código</Text>
        )}
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.secondaryButton}
        onPress={() => setStep('info')}
      >
        <Text style={styles.secondaryButtonText}>Atrás</Text>
      </TouchableOpacity>
    </View>
  );

  const renderVerifyStep = () => (
    <View style={styles.stepContainer}>
      <View style={styles.iconContainer}>
        <Icon name="key" size={48} color={colors.success} />
      </View>
      
      <Text style={styles.title}>Ingresa el Código</Text>
      <Text style={styles.description}>
        Hemos enviado un código de 6 dígitos a tu {method === 'email' ? 'correo electrónico' : 'teléfono'}.
      </Text>

      <TextInput
        style={styles.codeInput}
        value={verificationCode}
        onChangeText={setVerificationCode}
        placeholder="000000"
        keyboardType="numeric"
        maxLength={6}
        autoFocus
        textAlign="center"
      />

      <TouchableOpacity
        style={[styles.primaryButton, isLoading && styles.buttonDisabled]}
        onPress={handleVerifyCode}
        disabled={isLoading || verificationCode.length !== 6}
      >
        {isLoading ? (
          <ActivityIndicator color={colors.background} />
        ) : (
          <Text style={styles.primaryButtonText}>Verificar</Text>
        )}
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.secondaryButton}
        onPress={handleRequestCode}
        disabled={isLoading}
      >
        <Text style={styles.secondaryButtonText}>Reenviar Código</Text>
      </TouchableOpacity>
    </View>
  );

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity style={styles.closeButton} onPress={onClose}>
            <Icon name="x" size={24} color={colors.text} />
          </TouchableOpacity>
        </View>

        <View style={styles.content}>
          {step === 'info' && renderInfoStep()}
          {step === 'request' && renderRequestStep()}
          {step === 'verify' && renderVerifyStep()}
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    paddingHorizontal: 20,
    paddingTop: 50,
    paddingBottom: 10,
  },
  closeButton: {
    padding: 8,
  },
  content: {
    flex: 1,
    paddingHorizontal: 20,
  },
  stepContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingBottom: 40,
  },
  iconContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 24,
    shadowColor: colors.text,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
    elevation: 4,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.text,
    textAlign: 'center',
    marginBottom: 16,
  },
  description: {
    fontSize: 16,
    color: colors.textSecondary,
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: 32,
    paddingHorizontal: 20,
  },
  benefitsList: {
    alignSelf: 'stretch',
    marginBottom: 32,
  },
  benefitItem: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
    paddingHorizontal: 20,
  },
  benefitText: {
    fontSize: 16,
    color: colors.text,
    marginLeft: 12,
    flex: 1,
  },
  methodContainer: {
    flexDirection: 'row',
    marginBottom: 32,
    gap: 16,
  },
  methodButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.background,
  },
  methodButtonActive: {
    borderColor: colors.primary,
    backgroundColor: colors.primary + '10',
  },
  methodButtonText: {
    fontSize: 16,
    color: colors.textSecondary,
    marginLeft: 8,
    fontWeight: '500',
  },
  methodButtonTextActive: {
    color: colors.primary,
  },
  codeInput: {
    width: '100%',
    height: 60,
    borderWidth: 2,
    borderColor: colors.border,
    borderRadius: 12,
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.text,
    marginBottom: 32,
    letterSpacing: 8,
  },
  primaryButton: {
    width: '100%',
    height: 56,
    backgroundColor: colors.primary,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  primaryButtonText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.background,
  },
  secondaryButton: {
    width: '100%',
    height: 56,
    backgroundColor: 'transparent',
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.textSecondary,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
});

export default DeviceTrustModal;