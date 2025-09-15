import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Modal,
  Image,
  ScrollView,
  Dimensions,
  Platform,
  KeyboardAvoidingView,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

const { width: screenWidth } = Dimensions.get('window');

const GradientBackground: React.FC<{
  width: number;
  height: number;
  borderRadius?: number;
  children?: React.ReactNode;
}> = ({ width, height, borderRadius = 0, children }) => (
  <View style={{ width, height, borderRadius, overflow: 'hidden' }}>
    <Svg width={width} height={height} style={{ position: 'absolute' }}>
      <Defs>
        <LinearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="0%">
          <Stop offset="0%" stopColor="#34d399" />
          <Stop offset="100%" stopColor="#10b981" />
        </LinearGradient>
      </Defs>
      <Rect x="0" y="0" width={width} height={height} fill="url(#grad)" rx={borderRadius} />
    </Svg>
    {children && (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        {children}
      </View>
    )}
  </View>
);

interface ContactPermissionModalProps {
  visible: boolean;
  onAllow: () => void;
  // onDeny and onClose kept for backward compatibility but intentionally unused to comply with iOS guidelines
  onDeny?: () => void;
  onClose?: () => void;
}

export const ContactPermissionModal: React.FC<ContactPermissionModalProps> = ({
  visible,
  onAllow,
}) => {
  const insets = useSafeAreaInsets();
  
  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      // Prevent dismissing the explainer without proceeding to the system prompt
      onRequestClose={() => {}}
    >
      <View style={styles.modalOverlay}>
        <View style={styles.backdrop} />
        <View style={[styles.modalContent, { paddingBottom: insets.bottom || 20 }]}> 
          <ScrollView 
            showsVerticalScrollIndicator={false}
            contentContainerStyle={styles.scrollContent}
            bounces={true}
            overScrollMode="always"
          >
            {/* Icon */}
            <View style={styles.iconContainer}>
              <GradientBackground width={96} height={96} borderRadius={48}>
                <Icon name="users" size={48} color="#fff" />
              </GradientBackground>
            </View>

            {/* Title */}
            <Text style={styles.title}>Conecta con tus amigos</Text>
            <Text style={styles.subtitle}>
              Permite el acceso a tus contactos para una experiencia más personalizada
            </Text>

            {/* Benefits */}
            <View style={styles.benefitsContainer}>
              <BenefitItem
                icon="user-check"
                title="Nombres familiares"
                description="Ve los nombres de tus contactos en lugar de números de teléfono"
              />
              <BenefitItem
                icon="shield"
                title="Privacidad primero"
                description="Con tu consentimiento, subimos solo los números para verificar quién usa Confío — nunca nombres ni otros datos"
              />
              <BenefitItem
                icon="zap"
                title="Envíos rápidos"
                description="Encuentra y envía dinero a tus amigos más rápidamente"
              />
              <BenefitItem
                icon="gift"
                title="Invita amigos"
                description="Identifica quiénes de tus contactos aún no usan Confío"
              />
            </View>

            {/* Privacy / Data Use Notice */}
            <View style={styles.privacyNotice}>
              <Icon name="lock" size={16} color="#10b981" style={styles.privacyIcon} />
              <Text style={styles.privacyText}>
                Tu privacidad es nuestra prioridad. Para identificar qué contactos usan Confío, si aceptas, subimos
                únicamente los números de teléfono a nuestros servidores para realizar la comprobación. Nunca
                subimos nombres ni otra información de tus contactos, y no compartimos estos datos con terceros.
              </Text>
            </View>

            {/* How it works */}
            <View style={styles.howItWorksContainer}>
              <Text style={styles.sectionTitle}>¿Cómo funciona?</Text>
              
              <View style={styles.step}>
                <View style={styles.stepNumber}>
                  <Text style={styles.stepNumberText}>1</Text>
                </View>
                <View style={styles.stepContent}>
                  <Text style={styles.stepTitle}>Sincronización local</Text>
                  <Text style={styles.stepDescription}>
                    Tus contactos se leen y procesan únicamente en tu dispositivo
                  </Text>
                </View>
              </View>

              <View style={styles.step}>
                <View style={styles.stepNumber}>
                  <Text style={styles.stepNumberText}>2</Text>
                </View>
                <View style={styles.stepContent}>
                  <Text style={styles.stepTitle}>Almacenamiento seguro</Text>
                  <Text style={styles.stepDescription}>
                    Los datos se guardan encriptados en el almacenamiento seguro de tu teléfono
                  </Text>
                </View>
              </View>

              <View style={styles.step}>
                <View style={styles.stepNumber}>
                  <Text style={styles.stepNumberText}>3</Text>
                </View>
                <View style={styles.stepContent}>
                  <Text style={styles.stepTitle}>Coincidencia</Text>
                  <Text style={styles.stepDescription}>
                    Con tu consentimiento, subimos únicamente los números de tus contactos para comprobar quién usa
                    Confío y mostrar nombres en tus transacciones. Nunca subimos nombres ni otra información.
                  </Text>
                </View>
              </View>
            </View>

            {/* Buttons */}
            <View style={styles.buttonContainer}>
              <TouchableOpacity
                style={styles.allowButton}
                onPress={onAllow}
                activeOpacity={0.8}
              >
                <GradientBackground width={screenWidth - 48} height={52} borderRadius={12}>
                  <View style={styles.allowButtonContent}>
                    <Icon name="arrow-right" size={20} color="#fff" style={{ marginRight: 8 }} />
                    <Text style={styles.allowButtonText}>Continuar</Text>
                  </View>
                </GradientBackground>
              </TouchableOpacity>
            </View>

            {/* Footer note */}
            <Text style={styles.footerNote}>
              Puedes cambiar esto en cualquier momento desde la configuración
            </Text>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
};

const BenefitItem: React.FC<{
  icon: string;
  title: string;
  description: string;
}> = ({ icon, title, description }) => (
  <View style={styles.benefitItem}>
    <View style={styles.benefitIcon}>
      <Icon name={icon} size={24} color="#10b981" />
    </View>
    <View style={styles.benefitContent}>
      <Text style={styles.benefitTitle}>{title}</Text>
      <Text style={styles.benefitDescription}>{description}</Text>
    </View>
  </View>
);

const styles = StyleSheet.create({
  modalOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  modalContent: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: Dimensions.get('window').height * 0.9,
  },
  // Removed close button to prevent dismissing before system prompt
  scrollContent: {
    padding: 24,
    paddingTop: 48,
    paddingBottom: 40, // Extra space at bottom for safe scrolling
  },
  iconContainer: {
    alignItems: 'center',
    marginBottom: 24,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#111827',
    textAlign: 'center',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    marginBottom: 32,
    lineHeight: 24,
  },
  benefitsContainer: {
    marginBottom: 24,
  },
  benefitItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 20,
  },
  benefitIcon: {
    width: 48,
    height: 48,
    borderRadius: 12,
    backgroundColor: '#d1fae5',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  benefitContent: {
    flex: 1,
  },
  benefitTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#111827',
    marginBottom: 4,
  },
  benefitDescription: {
    fontSize: 14,
    color: '#6B7280',
    lineHeight: 20,
  },
  privacyNotice: {
    flexDirection: 'row',
    backgroundColor: '#d1fae5',
    padding: 16,
    borderRadius: 12,
    marginBottom: 32,
  },
  privacyIcon: {
    marginRight: 12,
    marginTop: 2,
  },
  privacyText: {
    flex: 1,
    fontSize: 14,
    color: '#059669',
    lineHeight: 20,
  },
  howItWorksContainer: {
    marginBottom: 32,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#111827',
    marginBottom: 20,
  },
  step: {
    flexDirection: 'row',
    marginBottom: 20,
  },
  stepNumber: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#f3f4f6',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  stepNumberText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#6B7280',
  },
  stepContent: {
    flex: 1,
  },
  stepTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#111827',
    marginBottom: 4,
  },
  stepDescription: {
    fontSize: 14,
    color: '#6B7280',
    lineHeight: 20,
  },
  buttonContainer: {
    marginBottom: 16,
  },
  allowButton: {
    marginBottom: 12,
  },
  allowButtonContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  allowButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#fff',
  },
  footerNote: {
    fontSize: 12,
    color: '#9CA3AF',
    textAlign: 'center',
    lineHeight: 16,
  },
});
