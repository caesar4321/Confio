import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform, StatusBar } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { RootStackNavigationProp } from '../types/navigation';
import Icon from 'react-native-vector-icons/Feather';
import { Header } from '../navigation/Header';

// Define colors directly in the component
const colors = {
  primary: '#34D399', // emerald-400
  primaryText: '#059669', // emerald-600
  primaryLight: '#D1FAE5', // emerald-100
  primaryDark: '#10B981', // emerald-500
  secondary: '#8B5CF6', // violet-500
  secondaryText: '#7C3AED', // violet-600
  accent: '#3B82F6', // blue-500
  accentText: '#2563EB', // blue-600
  neutral: '#F9FAFB', // gray-50
  neutralDark: '#F3F4F6', // gray-100
  dark: '#111827', // gray-900
  warning: '#F59E0B', // amber-500
  warningLight: '#FEF3C7', // amber-100
  info: '#3B82F6', // blue-500
  infoLight: '#DBEAFE', // blue-100
  success: '#10B981', // emerald-500
  successLight: '#D1FAE5', // emerald-100
  background: '#FFFFFF',
  text: '#000000',
};

interface VerificationLevel {
  level: number;
  title: string;
  subtitle: string;
  features: string[];
  color: string;
  textColor: string;
  icon: string;
  required?: string;
}

const VerificationScreen = () => {
  const navigation = useNavigation<RootStackNavigationProp>();
  const [currentLevel, setCurrentLevel] = useState<number>(0);
  const [showUploadFlow, setShowUploadFlow] = useState<boolean>(false);
  const [uploadStep, setUploadStep] = useState<number>(1);

  const verificationLevels: VerificationLevel[] = [
    {
      level: 0,
      title: "Usuario Básico",
      subtitle: "Solo teléfono verificado",
      features: [
        "Enviar hasta US$1,000/día",
        "Recibir sin límites",
        "Comprar P2P hasta US$1,000/operación",
        "Perfecto para uso diario y emergencias"
      ],
      color: colors.neutralDark,
      textColor: '#4B5563', // gray-600
      icon: "user-check"
    },
    {
      level: 1,
      title: "Trader Verificado",
      subtitle: "Identidad confirmada",
      features: [
        "Enviar hasta US$10,000/día",
        "Recibir sin límites",
        "Publicar ofertas P2P hasta US$10,000/día",
        "Insignia de confianza y prioridad"
      ],
      color: colors.primaryLight,
      textColor: colors.primaryText,
      icon: "shield",
      required: "Para publicar ofertas P2P o +US$10,000/mes volumen"
    },
    {
      level: 2,
      title: "Trader Premium",
      subtitle: "Verificación avanzada + historial",
      features: [
        "Enviar y ofertas P2P sin límites",
        "Recibir sin límites",
        "Herramientas avanzadas de trading",
        "Soporte prioritario y funciones beta"
      ],
      color: colors.secondary,
      textColor: "white",
      icon: "star",
      required: "Desbloqueado tras 30 días + US$25,000 volumen + buenas calificaciones"
    }
  ];

  const renderLevelCard = (levelInfo: VerificationLevel) => {
    const isActive = currentLevel >= levelInfo.level;
    const canUpgrade = currentLevel === levelInfo.level - 1;
    
    return (
      <View key={levelInfo.level} style={[
        styles.levelCard,
        isActive && { backgroundColor: levelInfo.color, borderColor: 'transparent' }
      ]}>
        <View style={styles.levelHeader}>
          <View style={styles.levelTitleContainer}>
            <Icon 
              name={levelInfo.icon} 
              size={24} 
              color={levelInfo.level === 0 ? '#4B5563' : 
                     levelInfo.level === 1 ? colors.primaryText :
                     isActive ? 'white' : colors.secondaryText} 
            />
            <View style={styles.levelTitleText}>
              <Text style={[styles.levelTitle, { color: isActive ? levelInfo.textColor : '#1F2937' }]}>
                {levelInfo.title}
              </Text>
              <Text style={[styles.levelSubtitle, { color: isActive ? levelInfo.textColor : '#6B7280' }]}>
                {levelInfo.subtitle}
              </Text>
            </View>
          </View>
          {isActive && (
            <Icon name="check-circle" size={20} color={colors.primaryText} />
          )}
        </View>

        {levelInfo.required && (
          <View style={styles.requiredContainer}>
            <Icon name="info" size={16} color={colors.warning} style={styles.requiredIcon} />
            <Text style={styles.requiredText}>{levelInfo.required}</Text>
          </View>
        )}

        <View style={styles.featuresList}>
          {levelInfo.features.map((feature, index) => (
            <View key={index} style={styles.featureItem}>
              <Icon 
                name="check-circle" 
                size={14} 
                color={levelInfo.level === 0 ? '#4B5563' : 
                       levelInfo.level === 1 ? colors.primaryText :
                       isActive ? 'white' : colors.secondaryText} 
              />
              <Text style={[styles.featureText, { color: isActive ? levelInfo.textColor : '#4B5563' }]}>
                {feature}
              </Text>
            </View>
          ))}
        </View>

        {canUpgrade && (
          <TouchableOpacity 
            style={[styles.verifyButton, { backgroundColor: colors.primary }]}
            onPress={() => setShowUploadFlow(true)}
          >
            <Text style={styles.verifyButtonText}>Verificar Ahora</Text>
          </TouchableOpacity>
        )}
        
        {levelInfo.level > currentLevel + 1 && (
          <View style={styles.lockedButton}>
            <Text style={styles.lockedButtonText}>Requiere nivel anterior</Text>
          </View>
        )}
      </View>
    );
  };

  const renderUploadFlow = () => {
    if (uploadStep === 1) {
      return (
        <View style={styles.uploadContainer}>
          <View style={styles.uploadHeader}>
            <View style={[styles.uploadIconContainer, { backgroundColor: colors.primary }]}>
              <Icon name="upload" size={24} color="white" />
            </View>
            <Text style={styles.uploadTitle}>Sube tu Documento</Text>
            <Text style={styles.uploadSubtitle}>
              Necesitamos verificar tu identidad para permitirte publicar ofertas P2P
            </Text>
          </View>

          <View style={styles.infoBox}>
            <Icon name="info" size={16} color={colors.info} style={styles.infoIcon} />
            <View>
              <Text style={styles.infoTitle}>Documentos aceptados:</Text>
              <Text style={styles.infoText}>• Cédula de identidad</Text>
              <Text style={styles.infoText}>• Pasaporte</Text>
              <Text style={styles.infoText}>• Licencia de conducir</Text>
            </View>
          </View>

          <View style={styles.uploadOptions}>
            <TouchableOpacity style={styles.uploadOption}>
              <Icon name="camera" size={24} color="#6B7280" />
              <Text style={styles.uploadOptionText}>Tomar foto del documento</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.uploadOption}>
              <Icon name="upload" size={24} color="#6B7280" />
              <Text style={styles.uploadOptionText}>Subir desde galería</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.buttonRow}>
            <TouchableOpacity 
              style={styles.secondaryButton}
              onPress={() => setShowUploadFlow(false)}
            >
              <Text style={styles.secondaryButtonText}>Cancelar</Text>
            </TouchableOpacity>
            <TouchableOpacity 
              style={[styles.primaryButton, { backgroundColor: colors.primary }]}
              onPress={() => setUploadStep(2)}
            >
              <Text style={styles.primaryButtonText}>Continuar</Text>
            </TouchableOpacity>
          </View>
        </View>
      );
    }

    if (uploadStep === 2) {
      return (
        <View style={styles.uploadContainer}>
          <View style={styles.uploadHeader}>
            <View style={[styles.uploadIconContainer, { backgroundColor: colors.primary }]}>
              <Icon name="camera" size={24} color="white" />
            </View>
            <Text style={styles.uploadTitle}>Toma un Selfie</Text>
            <Text style={styles.uploadSubtitle}>
              Necesitamos verificar que eres tú quien está registrándose
            </Text>
          </View>

          <View style={styles.warningBox}>
            <Icon name="alert-circle" size={16} color={colors.warning} style={styles.warningIcon} />
            <View>
              <Text style={styles.warningTitle}>Consejos para una buena foto:</Text>
              <Text style={styles.warningText}>• Buena iluminación</Text>
              <Text style={styles.warningText}>• Rostro completamente visible</Text>
              <Text style={styles.warningText}>• Sin lentes oscuros o sombreros</Text>
            </View>
          </View>

          <View style={styles.cameraPreview}>
            <Icon name="camera" size={48} color="#9CA3AF" />
            <Text style={styles.cameraPreviewText}>Cámara frontal activada</Text>
          </View>

          <View style={styles.buttonRow}>
            <TouchableOpacity 
              style={styles.secondaryButton}
              onPress={() => setUploadStep(1)}
            >
              <Text style={styles.secondaryButtonText}>Atrás</Text>
            </TouchableOpacity>
            <TouchableOpacity 
              style={[styles.primaryButton, { backgroundColor: colors.primary }]}
              onPress={() => setUploadStep(3)}
            >
              <Text style={styles.primaryButtonText}>Tomar Foto</Text>
            </TouchableOpacity>
          </View>
        </View>
      );
    }

    if (uploadStep === 3) {
      return (
        <View style={styles.uploadContainer}>
          <View style={styles.uploadHeader}>
            <View style={[styles.uploadIconContainer, { backgroundColor: colors.primary }]}>
              <Icon name="check-circle" size={24} color="white" />
            </View>
            <Text style={styles.uploadTitle}>¡Documentos Enviados!</Text>
            <Text style={styles.uploadSubtitle}>
              Revisaremos tu información en las próximas 24-48 horas
            </Text>
          </View>

          <View style={styles.successBox}>
            <Text style={styles.successTitle}>¿Qué sigue?</Text>
            <View style={styles.successList}>
              <Text style={styles.successText}>• Nuestro equipo revisará manualmente tus documentos</Text>
              <Text style={styles.successText}>• Te notificaremos por la app cuando esté listo</Text>
              <Text style={styles.successText}>• Una vez aprobado, podrás publicar ofertas P2P</Text>
            </View>
          </View>

          <View style={styles.progressContainer}>
            <View style={styles.progressHeader}>
              <Text style={styles.progressLabel}>Progreso de verificación</Text>
              <Text style={styles.progressStatus}>En revisión</Text>
            </View>
            <View style={styles.progressBar}>
              <View style={[styles.progressFill, { backgroundColor: colors.primary, width: '75%' }]} />
            </View>
          </View>

          <TouchableOpacity 
            style={[styles.primaryButton, { backgroundColor: colors.primary }]}
            onPress={() => {
              setShowUploadFlow(false);
              setUploadStep(1);
            }}
          >
            <Text style={styles.primaryButtonText}>Entendido</Text>
          </TouchableOpacity>
        </View>
      );
    }
  };

  if (showUploadFlow) {
    return (
      <View style={styles.container}>
        <Header 
          title="Verificación de Identidad"
          navigation={navigation}
          backgroundColor={colors.primary}
          isLight={true}
        />
        <ScrollView style={styles.scrollView}>
          {renderUploadFlow()}
        </ScrollView>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Header 
        title="Verificación"
        navigation={navigation}
        backgroundColor={colors.primary}
        isLight={true}
      />
      <ScrollView style={styles.scrollView}>
        <View style={styles.content}>
          {/* Current Status */}
          <View style={styles.statusCard}>
            <View style={styles.statusHeader}>
              <View>
                <Text style={styles.statusTitle}>Tu nivel actual</Text>
                <Text style={styles.statusSubtitle}>{verificationLevels[currentLevel].title}</Text>
              </View>
              <View style={[styles.levelBadge, { backgroundColor: verificationLevels[currentLevel].color }]}>
                <Text style={[styles.levelBadgeText, { color: verificationLevels[currentLevel].textColor }]}>
                  Nivel {currentLevel}
                </Text>
              </View>
            </View>
          </View>

          {/* Benefits Info */}
          <View style={styles.benefitsBox}>
            <Icon name="trending-up" size={20} color={colors.info} style={styles.benefitsIcon} />
            <View>
              <Text style={styles.benefitsTitle}>¿Por qué verificarse?</Text>
              <Text style={styles.benefitsText}>
                La verificación solo se requiere para publicar ofertas P2P o volúmenes altos
              </Text>
              <Text style={styles.benefitsTip}>
                💡 Los usuarios básicos pueden usar todas las funciones principales sin verificación
              </Text>
            </View>
          </View>

          {/* Verification Levels */}
          <View style={styles.levelsContainer}>
            {verificationLevels.map(renderLevelCard)}
          </View>

          {/* Footer Info */}
          <View style={styles.footerBox}>
            <Icon name="shield" size={16} color="#6B7280" style={styles.footerIcon} />
            <View>
              <Text style={styles.footerTitle}>Tu privacidad está protegida</Text>
              <Text style={styles.footerText}>
                Solo procesamos manualmente las verificaciones de usuarios que publican ofertas P2P. 
                Los usuarios regulares no necesitan verificación adicional.
              </Text>
            </View>
          </View>
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: 'white',
  },
  header: {
    paddingTop: Platform.OS === 'ios' ? 48 : (StatusBar.currentHeight || 32),
    paddingBottom: 24,
    paddingHorizontal: 16,
  },
  backButton: {
    marginBottom: 16,
  },
  headerContent: {
    flex: 1,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: 'white',
    marginBottom: 8,
  },
  headerSubtitle: {
    fontSize: 14,
    color: 'rgba(255, 255, 255, 0.9)',
  },
  scrollView: {
    flex: 1,
  },
  content: {
    padding: 16,
  },
  statusCard: {
    backgroundColor: 'white',
    borderRadius: 12,
    padding: 16,
    marginBottom: 24,
    borderWidth: 1,
    borderColor: '#F3F4F6', // gray-100
  },
  statusHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  statusTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937', // gray-800
  },
  statusSubtitle: {
    fontSize: 14,
    color: '#6B7280', // gray-500
  },
  levelBadge: {
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 20,
  },
  levelBadgeText: {
    fontSize: 14,
    fontWeight: '500',
  },
  benefitsBox: {
    backgroundColor: '#EFF6FF', // blue-50
    borderWidth: 1,
    borderColor: '#BFDBFE', // blue-200
    borderRadius: 12,
    padding: 16,
    marginBottom: 24,
    flexDirection: 'row',
  },
  benefitsIcon: {
    marginRight: 12,
    marginTop: 2,
  },
  benefitsTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1E40AF', // blue-800
    marginBottom: 4,
  },
  benefitsText: {
    fontSize: 14,
    color: '#1E40AF', // blue-700
    marginBottom: 8,
  },
  benefitsTip: {
    fontSize: 12,
    color: '#2563EB', // blue-600
    fontWeight: '500',
  },
  levelsContainer: {
    gap: 16,
  },
  levelCard: {
    backgroundColor: 'white',
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: '#E5E7EB', // gray-200
  },
  levelHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 12,
  },
  levelTitleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  levelTitleText: {
    marginLeft: 12,
  },
  levelTitle: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  levelSubtitle: {
    fontSize: 14,
  },
  requiredContainer: {
    backgroundColor: '#FEF3C7', // amber-100
    borderWidth: 1,
    borderColor: '#FDE68A', // amber-200
    borderRadius: 8,
    padding: 12,
    marginBottom: 16,
    flexDirection: 'row',
    alignItems: 'center',
  },
  requiredIcon: {
    marginRight: 12,
  },
  requiredTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#92400E', // amber-800
    marginBottom: 8,
    flex: 1,
  },
  requiredText: {
    fontSize: 14,
    color: '#92400E', // amber-800
    marginBottom: 4,
    flex: 1,
  },
  featuresList: {
    gap: 8,
    marginBottom: 16,
  },
  featureItem: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  featureText: {
    fontSize: 14,
    marginLeft: 8,
  },
  verifyButton: {
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  verifyButtonText: {
    color: 'white',
    fontSize: 16,
    fontWeight: '500',
  },
  lockedButton: {
    paddingVertical: 12,
    backgroundColor: '#F3F4F6', // gray-100
    borderRadius: 8,
    alignItems: 'center',
  },
  lockedButtonText: {
    color: '#6B7280', // gray-500
    fontSize: 16,
    fontWeight: '500',
  },
  uploadContainer: {
    padding: 16,
  },
  uploadHeader: {
    alignItems: 'center',
    marginBottom: 24,
  },
  uploadIconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  uploadTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937', // gray-800
    marginBottom: 8,
  },
  uploadSubtitle: {
    fontSize: 14,
    color: '#6B7280', // gray-500
    textAlign: 'center',
  },
  infoBox: {
    backgroundColor: '#EFF6FF', // blue-50
    borderWidth: 1,
    borderColor: '#BFDBFE', // blue-200
    borderRadius: 8,
    padding: 12,
    marginBottom: 24,
    flexDirection: 'row',
  },
  infoIcon: {
    marginRight: 8,
    marginTop: 2,
  },
  infoTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1E40AF', // blue-800
    marginBottom: 4,
  },
  infoText: {
    fontSize: 14,
    color: '#1E40AF', // blue-700
  },
  uploadOptions: {
    gap: 12,
    marginBottom: 24,
  },
  uploadOption: {
    padding: 16,
    borderWidth: 2,
    borderStyle: 'dashed',
    borderColor: '#D1D5DB', // gray-300
    borderRadius: 8,
    alignItems: 'center',
  },
  uploadOptionText: {
    fontSize: 14,
    color: '#6B7280', // gray-500
    marginTop: 8,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 12,
  },
  secondaryButton: {
    flex: 1,
    paddingVertical: 12,
    backgroundColor: '#F3F4F6', // gray-100
    borderRadius: 8,
    alignItems: 'center',
  },
  secondaryButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#4B5563', // gray-600
  },
  primaryButton: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  primaryButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: 'white',
  },
  warningBox: {
    backgroundColor: '#FEF3C7', // amber-100
    borderWidth: 1,
    borderColor: '#FDE68A', // amber-200
    borderRadius: 8,
    padding: 20,
    marginBottom: 24,
    flexDirection: 'row',
  },
  warningIcon: {
    marginRight: 12,
    marginTop: 2,
  },
  warningTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#92400E', // amber-800
    marginBottom: 8,
    flex: 1,
  },
  warningText: {
    fontSize: 14,
    color: '#92400E', // amber-800
    marginBottom: 4,
    flex: 1,
    paddingRight: 8,
  },
  cameraPreview: {
    backgroundColor: '#F3F4F6', // gray-100
    borderRadius: 8,
    padding: 32,
    alignItems: 'center',
    marginBottom: 24,
  },
  cameraPreviewText: {
    fontSize: 14,
    color: '#6B7280', // gray-500
    marginTop: 16,
  },
  successBox: {
    backgroundColor: '#D1FAE5', // emerald-100
    borderWidth: 1,
    borderColor: '#A7F3D0', // emerald-200
    borderRadius: 8,
    padding: 16,
    marginBottom: 24,
  },
  successTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#065F46', // emerald-800
    marginBottom: 8,
  },
  successList: {
    gap: 4,
  },
  successText: {
    fontSize: 14,
    color: '#065F46', // emerald-700
  },
  progressContainer: {
    backgroundColor: '#F9FAFB', // gray-50
    borderRadius: 8,
    padding: 16,
    marginBottom: 24,
  },
  progressHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  progressLabel: {
    fontSize: 14,
    color: '#6B7280', // gray-500
  },
  progressStatus: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937', // gray-800
  },
  progressBar: {
    height: 8,
    backgroundColor: '#E5E7EB', // gray-200
    borderRadius: 4,
  },
  progressFill: {
    height: '100%',
    borderRadius: 4,
  },
  footerBox: {
    backgroundColor: '#F9FAFB', // gray-50
    borderRadius: 12,
    padding: 16,
    marginTop: 24,
    flexDirection: 'row',
  },
  footerIcon: {
    marginRight: 12,
    marginTop: 2,
  },
  footerTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: '#4B5563', // gray-600
    marginBottom: 4,
  },
  footerText: {
    fontSize: 12,
    color: '#6B7280', // gray-500
  },
});

export default VerificationScreen;
