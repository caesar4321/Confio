import React, { useState, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform, StatusBar, Modal, Image, TextInput, ActivityIndicator, Alert } from 'react-native';
import { Camera, useCameraDevice } from 'react-native-vision-camera';
import { useNavigation } from '@react-navigation/native';
import { useFocusEffect } from '@react-navigation/native';
import { RootStackNavigationProp } from '../types/navigation';
import Icon from 'react-native-vector-icons/Feather';
import { Header } from '../navigation/Header';
import { useMutation, useQuery, useApolloClient } from '@apollo/client';
import { REQUEST_IDENTITY_UPLOAD, SUBMIT_IDENTITY_VERIFICATION_S3, REQUEST_PREMIUM_UPGRADE } from '../apollo/mutations';
// Gallery access now uses Android Photo Picker via a small native module
import { pickImageUri } from '../native/MediaPicker';
import { uploadFileToPresigned, uploadFileToPresignedForm } from '../services/uploadService';
import { GET_ME, GET_USER_ACCOUNTS, GET_MY_PERSONAL_KYC_STATUS, GET_BUSINESS_KYC_STATUS, GET_MY_KYC_STATUS } from '../apollo/queries';
import { useAccountManager } from '../hooks/useAccountManager';

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
  const [frontImageUri, setFrontImageUri] = useState<string | null>(null);
  const [backImageUri, setBackImageUri] = useState<string | null>(null);
  const [selfieImageUri, setSelfieImageUri] = useState<string | null>(null);
  const [payoutProofUri, setPayoutProofUri] = useState<string | null>(null);
  const [businessCertUri, setBusinessCertUri] = useState<string | null>(null);
  const [frontKey, setFrontKey] = useState<string | null>(null);
  const [backKey, setBackKey] = useState<string | null>(null);
  const [selfieKey, setSelfieKey] = useState<string | null>(null);
  const [payoutKey, setPayoutKey] = useState<string | null>(null);
  const [payoutLabel, setPayoutLabel] = useState<string>('');
  const [verifiedDob, setVerifiedDob] = useState<string>('');

  const [requestIdentityUpload] = useMutation(REQUEST_IDENTITY_UPLOAD);
  const [requestPremiumUpgrade] = useMutation(REQUEST_PREMIUM_UPGRADE);
  const [submitIdentityVerificationS3, { loading: submitting } ] = useMutation(SUBMIT_IDENTITY_VERIFICATION_S3);
  const backDevice = useCameraDevice('back');
  const frontDevice = useCameraDevice('front');
  const cameraRef = useRef<Camera | null>(null);
  const [showCamera, setShowCamera] = useState(false);
  const [cameraPurpose, setCameraPurpose] = useState<'front'|'selfie'|'payout'|'business'>('front');
  // Removed custom gallery; we use system picker on Android
  const [previewUri, setPreviewUri] = useState<string | null>(null);
  const [previewPurpose, setPreviewPurpose] = useState<'front'|'back'|'selfie'|'payout'|'business'>('front');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [requestingPremium, setRequestingPremium] = useState(false);
  const apolloClient = useApolloClient();
  const normalizeStatus = (s?: any): 'unverified'|'pending'|'verified'|'rejected' => {
    const v = (s ?? '').toString().trim().toLowerCase();
    if (['pending', 'submitted', 'in_review', 'en revisión', 'en revision'].includes(v)) return 'pending';
    if (['verified', 'approved'].includes(v)) return 'verified';
    if (['rejected', 'denied', 'failed'].includes(v)) return 'rejected';
    return 'unverified';
  };
  const isValidDob = (dob: string) => /^\d{4}-\d{2}-\d{2}$/.test((dob || '').trim());
  const isValidDobStrict = (dob: string) => {
    try {
      const s = (dob || '').trim();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
      const [yStr, mStr, dStr] = s.split('-');
      const y = Number(yStr), m = Number(mStr), d = Number(dStr);
      if (y < 1900 || y > 2100) return false;
      if (m < 1 || m > 12) return false;
      const daysInMonth = new Date(y, m, 0).getDate();
      if (d < 1 || d > daysInMonth) return false;
      // Optional: date should not be in the future
      const input = new Date(y, m - 1, d).getTime();
      const now = Date.now();
      if (isNaN(input) || input > now) return false;
      return true;
    } catch {
      return false;
    }
  };
  const formatDob = (input: string) => {
    const digits = (input || '').replace(/\D/g, '').slice(0, 8);
    if (digits.length <= 4) return digits;
    if (digits.length <= 6) return `${digits.slice(0, 4)}-${digits.slice(4)}`;
    return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6)}`;
  };

  const pickFromGallery = async (purpose: 'front' | 'selfie' | 'payout') => {
    try {
      const uri = await pickImageUri();
      if (!uri) return;
      setPreviewPurpose(purpose);
      setPreviewUri(uri);
    } catch (e: any) {
      console.error('[Verification] Upload failed:', e?.message || e);
    }
  };

  const handleSubmitVerification = async () => {
    try {
      if (!isValidDobStrict(verifiedDob)) {
        Alert.alert('Fecha inválida', 'Ingresa una fecha de nacimiento válida (AAAA-MM-DD).');
        return;
      }
      if (!frontKey || !selfieKey) {
        console.warn('[Verification] Missing required files: front/selfie');
        return;
      }
      const { data } = await submitIdentityVerificationS3({
        variables: {
          frontKey,
          selfieKey,
          payoutMethodLabel: payoutLabel || null,
          payoutProofKey: payoutKey || null,
          verifiedDateOfBirth: verifiedDob || null,
        }
      });
      const res = data?.submitIdentityVerificationS3;
      if (!res?.success) throw new Error(res?.error || 'No se pudo enviar la verificación');
      setUploadStep(5);
    } catch (e: any) {
      console.error('[Verification] Submit failed:', e?.message || e);
    }
  };

  const openCamera = async (purpose: 'front'|'back'|'selfie'|'payout'|'business') => {
    try {
      const perm = await Camera.requestCameraPermission();
      if (perm !== 'granted') {
        console.warn('[Verification] Camera permission not granted');
        return;
      }
      setCameraPurpose(purpose);
      setShowCamera(true);
    } catch (e) {
      console.error('[Verification] openCamera error:', e);
    }
  };

  const handleCapture = async () => {
    try {
      const device = cameraPurpose === 'selfie' ? frontDevice : backDevice;
      if (!device || !cameraRef.current) {
        console.warn('[Verification] Camera device or ref not ready');
        return;
      }
      const photo = await cameraRef.current.takePhoto({ flash: 'off' });
      const path = photo?.path || '';
      const uri = path.startsWith('file://') ? path : `file://${path}`;
      const purpose = cameraPurpose;
      // Show preview instead of immediate upload
      setPreviewPurpose(purpose);
      setPreviewUri(uri);
      setShowCamera(false);
    } catch (e) {
      console.error('[Verification] handleCapture error:', e);
    }
  };

  const handleRequestPremium = async () => {
    try {
      setRequestingPremium(true);
      const { data } = await requestPremiumUpgrade({ variables: { reason: 'User requested Trader Premium' } });
      const res = data?.requestPremiumUpgrade;
      if (!res?.success) {
        console.warn('[Verification] Premium request failed:', res?.error);
        Alert.alert('Solicitud fallida', res?.error || 'No se pudo solicitar Premium.');
      } else {
        console.log('[Verification] Premium upgrade requested. Level:', res.verificationLevel);
        Alert.alert('Solicitud enviada', 'Revisaremos tu solicitud de Trader Premium.');
      }
    } catch (e: any) {
      console.error('[Verification] Premium request error:', e?.message || e);
      Alert.alert('Error', 'Ocurrió un error al solicitar Premium.');
    } finally {
      setRequestingPremium(false);
    }
  };

  const verificationLevels: VerificationLevel[] = [
    {
      level: 0,
      title: "Usuario Básico",
      subtitle: "Solo teléfono verificado",
      features: [
        "Enviar y recibir sin límites",
        "Pagar sin límites",
        "Comprar P2P sin límites",
        "Ideal para uso diario (no traders)"
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

  // Fetch current verification status to gate resubmission
  const { data: meData, refetch: refetchMe } = useQuery(GET_ME, { fetchPolicy: 'network-only' });
  const { data: personalKycData, refetch: refetchPersonalKyc } = useQuery(GET_MY_PERSONAL_KYC_STATUS, { fetchPolicy: 'network-only' });
  const { data: anyKycData, refetch: refetchAnyKyc } = useQuery(GET_MY_KYC_STATUS, { fetchPolicy: 'network-only' });
  const personalStatus = normalizeStatus(personalKycData?.myPersonalKycStatus?.status || meData?.me?.verificationStatus);
  const anyStatus = normalizeStatus(anyKycData?.myKycStatus?.status);
  const verificationStatus = personalStatus !== 'unverified' ? personalStatus : (anyStatus === 'pending' ? 'pending' : 'unverified');
  const isPersonalVerified = Boolean(meData?.me?.isIdentityVerified || verificationStatus === 'verified');
  const { activeAccount } = useAccountManager();
  const isBusinessAccount = (activeAccount?.type || '').toLowerCase() === 'business';
  // Fetch accounts to determine business verification status when in business context
  const { data: accountsData } = useQuery(GET_USER_ACCOUNTS, { fetchPolicy: 'cache-and-network' });
  const { isBusinessVerified, businessVerificationStatus } = React.useMemo(() => {
    if (!isBusinessAccount) return { isBusinessVerified: false, businessVerificationStatus: 'unverified' } as const;
    const list = accountsData?.userAccounts || [];
    const currentBizId = activeAccount?.business?.id;
    const match = list.find((acc: any) => acc.business?.id === currentBizId);
    return {
      isBusinessVerified: !!match?.business?.isVerified,
      businessVerificationStatus: (match?.business?.verificationStatus || 'unverified').toLowerCase()
    } as const;
  }, [accountsData, isBusinessAccount, activeAccount?.business?.id]) as any;
  // For business, also query latest KYC status by businessId to include pending state accurately
  const { data: bizKycData, refetch: refetchBizKyc } = useQuery(
    GET_BUSINESS_KYC_STATUS,
    {
      variables: { businessId: activeAccount?.business?.id || '' },
      skip: !isBusinessAccount || !activeAccount?.business?.id,
      fetchPolicy: 'network-only'
    }
  );
  const businessVerificationStatusEffective = normalizeStatus(bizKycData?.businessKycStatus?.status || businessVerificationStatus);

  // Sync currentLevel from server verification status
  const inferredLevel = (isBusinessAccount ? (isBusinessVerified ? 1 : 0) : (isPersonalVerified ? 1 : 0));
  if (currentLevel !== inferredLevel) {
    setTimeout(() => setCurrentLevel(inferredLevel), 0);
  }

  // Refresh statuses whenever the screen gains focus
  useFocusEffect(
    React.useCallback(() => {
      (async () => {
        try {
          await Promise.all([
            refetchMe(),
            personalKycData ? (refetchPersonalKyc?.() as any) : Promise.resolve(),
            isBusinessAccount ? (refetchBizKyc?.() as any || Promise.resolve()) : Promise.resolve(),
            refetchAnyKyc?.() as any,
          ]);
        } catch (e) {
          console.warn('[Verification] Refetch on focus failed:', (e as any)?.message || e);
        }
      })();
    }, [isBusinessAccount, activeAccount?.business?.id])
  );

  // no-op

  // Debug log to help verify state in dev
  React.useEffect(() => {
    try {
      console.log('[Verification] context:', {
        accountType: isBusinessAccount ? 'business' : 'personal',
        personalStatus,
        anyStatus,
        effectivePersonalStatus: verificationStatus,
        businessStatusEffective: businessVerificationStatusEffective,
        isBusinessVerified,
        meVerificationStatus: meData?.me?.verificationStatus,
      });
    } catch {}
  }, [isBusinessAccount, personalStatus, anyStatus, verificationStatus, businessVerificationStatusEffective, isBusinessVerified, meData?.me?.verificationStatus]);

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
          levelInfo.level === 2 ? (
            <TouchableOpacity
              style={[
                styles.verifyButton,
                {
                  backgroundColor: ((isBusinessAccount ? isBusinessVerified : (verificationStatus === 'verified')) ? colors.secondary : '#D1D5DB'),
                  opacity: requestingPremium ? 0.7 : 1,
                }
              ]}
              disabled={requestingPremium || !(isBusinessAccount ? isBusinessVerified : (verificationStatus === 'verified'))}
              onPress={handleRequestPremium}
            >
              <Text style={styles.verifyButtonText}>{requestingPremium ? 'Solicitando…' : 'Solicitar Premium'}</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity 
              style={[styles.verifyButton, { backgroundColor: (
                isBusinessAccount
                  ? ((businessVerificationStatusEffective === 'pending' || isBusinessVerified) ? '#D1D5DB' : colors.primary)
                  : ((verificationStatus === 'pending' || verificationStatus === 'verified') ? '#D1D5DB' : colors.primary)
              ) }]}
              disabled={isBusinessAccount ? (businessVerificationStatusEffective === 'pending' || isBusinessVerified) : (verificationStatus === 'pending' || verificationStatus === 'verified')}
              onPress={() => setShowUploadFlow(true)}
            >
              <Text style={styles.verifyButtonText}>
                {isBusinessAccount
                  ? (isBusinessVerified ? 'Verificado' : (businessVerificationStatusEffective === 'pending' ? 'En revisión' : 'Verificar Ahora'))
                  : (verificationStatus === 'pending' ? 'En revisión' : verificationStatus === 'verified' ? 'Verificado' : 'Verificar Ahora')}
              </Text>
            </TouchableOpacity>
          )
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
            <Text style={styles.uploadTitle}>Documento - Frente</Text>
            <Text style={styles.uploadSubtitle}>
              Toma una foto del documento con la cámara de la app. No se aceptan imágenes desde la galería.
            </Text>
            <Text style={styles.stepCounter}>Paso {uploadStep} de {isBusinessAccount ? 6 : 5}</Text>
          </View>

          <View style={styles.infoBox}>
            <Icon name="info" size={16} color={colors.info} style={styles.infoIcon} />
            <View>
              <Text style={styles.infoTitle}>Documentos aceptados:</Text>
              <Text style={styles.infoText}>• Cédula de identidad</Text>
              <Text style={styles.infoText}>• Pasaporte</Text>
              <Text style={styles.infoText}>• Licencia de conducir</Text>
              <Text style={[styles.infoText, { marginTop: 4 }]}>• Consejo: usa buena iluminación y evita reflejos</Text>
            </View>
          </View>

          <View style={styles.uploadOptions}>
            <TouchableOpacity style={styles.uploadOption} onPress={() => openCamera('front')}>
              <Icon name="camera" size={24} color="#6B7280" />
              <Text style={styles.uploadOptionText}>Tomar foto del documento</Text>
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
              style={[styles.primaryButton, { backgroundColor: frontImageUri ? colors.primary : '#D1D5DB' }]}
              onPress={() => frontImageUri ? setUploadStep(2) : console.warn('[Verification] Debes tomar foto del documento para continuar')}
              disabled={!frontImageUri}
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
            <Text style={styles.uploadTitle}>Documento - Reverso</Text>
            <Text style={styles.uploadSubtitle}>
              Toma una foto clara del reverso del documento. Evita reflejos.
            </Text>
            <Text style={styles.stepCounter}>Paso {uploadStep} de {isBusinessAccount ? 6 : 5}</Text>
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

          <TouchableOpacity style={styles.cameraPreview} onPress={() => openCamera('back')}>
            <Icon name="camera" size={48} color="#9CA3AF" />
            <Text style={styles.cameraPreviewText}>{backImageUri ? 'Reverso listo. Toca para repetir' : 'Toca para tomar la foto del reverso'}</Text>
          </TouchableOpacity>

          {/* Removed back and selfie buttons to encourage immediate capture via camera icon */}
          <View style={styles.buttonRow}>
            <TouchableOpacity 
              style={[styles.primaryButton, { backgroundColor: backImageUri ? colors.primary : '#D1D5DB' }]}
              onPress={() => backImageUri ? setUploadStep(3) : console.warn('[Verification] Debes tomar el reverso para continuar')}
              disabled={!backImageUri}
            >
              <Text style={styles.primaryButtonText}>Continuar</Text>
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
              <Icon name="upload" size={24} color="white" />
            </View>
            <Text style={styles.uploadTitle}>Toma un Selfie</Text>
            <Text style={styles.uploadSubtitle}>
              Asegúrate que tu rostro sea visible, bien iluminado y sin obstrucciones.
            </Text>
            <Text style={styles.stepCounter}>Paso {uploadStep} de {isBusinessAccount ? 6 : 5}</Text>
          </View>
          <TouchableOpacity style={styles.cameraPreview} onPress={() => openCamera('selfie')}>
            <Icon name="camera" size={48} color="#9CA3AF" />
            <Text style={styles.cameraPreviewText}>{selfieImageUri ? 'Selfie lista. Toca para repetir' : 'Toca para tomar tu selfie'}</Text>
          </TouchableOpacity>

          {/* Payment method name moved to Step 4 */}

          <TouchableOpacity 
            style={[styles.primaryButton, { backgroundColor: (selfieImageUri ? colors.primary : '#D1D5DB') }]}
            onPress={() => selfieImageUri ? setUploadStep(4) : console.warn('[Verification] Debes tomar tu selfie para continuar')}
            disabled={!selfieImageUri}
          >
            <Text style={styles.primaryButtonText}>Continuar</Text>
          </TouchableOpacity>
        </View>
      );
    }

    // New step 4: Upload payout method proof (screenshot)
    if (uploadStep === 4) {
      return (
        <View style={styles.uploadContainer}>
          <View style={styles.uploadHeader}>
            <View style={[styles.uploadIconContainer, { backgroundColor: colors.primary }]}>
              <Icon name="credit-card" size={24} color="white" />
            </View>
            <Text style={styles.uploadTitle}>Comprobante de método de pago</Text>
            <Text style={styles.uploadSubtitle}>
              Ingresa el nombre del método y sube una captura que muestre tu nombre. Puedes elegir una imagen de la galería o tomar una foto.
            </Text>
            <Text style={styles.stepCounter}>Paso {uploadStep} de {isBusinessAccount ? 6 : 5}</Text>
          </View>

          <View style={styles.infoBox}>
            <Icon name="info" size={16} color={colors.info} style={styles.infoIcon} />
            <View>
              <Text style={styles.infoTitle}>Requisitos del comprobante:</Text>
              <Text style={styles.infoText}>• Debe verse tu nombre y el método (Nequi, Daviplata, Banco, etc.)</Text>
              <Text style={styles.infoText}>• Evita recortar información clave</Text>
            </View>
          </View>

          <View style={{ marginVertical: 12 }}>
            <Text style={{ fontSize: 14, color: '#374151', marginBottom: 6 }}>Nombre del método (Nequi, Daviplata, Banco...)</Text>
            <TextInput
              placeholder="Ej: Nequi"
              value={payoutLabel}
              onChangeText={setPayoutLabel}
              style={{ borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 8, padding: 10 }}
            />
          </View>

          <View style={styles.uploadOptions}>
            <TouchableOpacity style={styles.uploadOption} onPress={() => pickFromGallery('payout')}>
              <Icon name="image" size={24} color="#6B7280" />
              <Text style={styles.uploadOptionText}>Elegir de la galería</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.uploadOption} onPress={() => openCamera('payout')}>
              <Icon name="camera" size={24} color="#6B7280" />
              <Text style={styles.uploadOptionText}>Usar cámara</Text>
            </TouchableOpacity>
          </View>

          <View style={{ marginVertical: 12 }}>
            <Text style={{ fontSize: 14, color: '#374151', marginBottom: 6 }}>Fecha de nacimiento (AAAA-MM-DD)</Text>
            <TextInput
              placeholder="AAAA-MM-DD"
              keyboardType="number-pad"
              autoCapitalize="none"
              value={verifiedDob}
              onChangeText={(t) => setVerifiedDob(formatDob(t))}
              maxLength={10}
              style={{ borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 8, padding: 10 }}
            />
          </View>

          {!!payoutProofUri && (
            <View style={{ alignItems: 'center', marginBottom: 16 }}>
              <Image source={{ uri: payoutProofUri }} style={{ width: 200, height: 200, borderRadius: 8 }} />
              <Text style={{ marginTop: 8, color: '#374151' }}>Comprobante listo. Puedes continuar.</Text>
            </View>
          )}

          <View style={styles.buttonRow}>
            <TouchableOpacity 
              style={[styles.primaryButton, { backgroundColor: (payoutProofUri && (payoutLabel || '').trim() && isValidDobStrict(verifiedDob)) ? colors.primary : '#D1D5DB' }]}
              onPress={() => {
                if (payoutProofUri && (payoutLabel || '').trim() && isValidDobStrict(verifiedDob)) {
                  setUploadStep(5);
                } else {
                  Alert.alert('Campos incompletos', 'Debes ingresar una fecha de nacimiento válida (AAAA-MM-DD), el nombre del método y subir el comprobante.');
                }
              }}
              disabled={!(payoutProofUri && (payoutLabel || '').trim() && isValidDobStrict(verifiedDob))}
            >
              <Text style={styles.primaryButtonText}>Continuar</Text>
            </TouchableOpacity>
          </View>
        </View>
      );
    }

    // Step 5 (business only): Business certificate
    if (isBusinessAccount && uploadStep === 5) {
      return (
        <View style={styles.uploadContainer}>
          <View style={styles.uploadHeader}>
            <View style={[styles.uploadIconContainer, { backgroundColor: colors.primary }]}>
              <Icon name="briefcase" size={24} color="white" />
            </View>
            <Text style={styles.uploadTitle}>Certificado de Negocio</Text>
            <Text style={styles.uploadSubtitle}>
              Toma una foto del certificado de tu negocio. Solo se permite la cámara.
            </Text>
            <Text style={styles.stepCounter}>Paso {uploadStep} de {isBusinessAccount ? 6 : 5}</Text>
          </View>
          <TouchableOpacity style={styles.cameraPreview} onPress={() => openCamera('business')}>
            <Icon name="camera" size={48} color="#9CA3AF" />
            <Text style={styles.cameraPreviewText}>{businessCertUri ? 'Certificado listo. Toca para repetir' : 'Toca para tomar foto del certificado'}</Text>
          </TouchableOpacity>
          <View style={styles.buttonRow}>
            <TouchableOpacity 
              style={[styles.primaryButton, { backgroundColor: businessCertUri ? colors.primary : '#D1D5DB' }]}
              onPress={() => businessCertUri ? setUploadStep(6) : console.warn('[Verification] Debes tomar la foto del certificado')}
              disabled={!businessCertUri}
            >
              <Text style={styles.primaryButtonText}>Continuar</Text>
            </TouchableOpacity>
          </View>
        </View>
      );
    }

    // Final review (step 5 for personal, step 6 for business)
    if ((!isBusinessAccount && uploadStep === 5) || (isBusinessAccount && uploadStep === 6)) {
      return (
        <View style={styles.uploadContainer}>
          <View style={styles.uploadHeader}>
            <View style={[styles.uploadIconContainer, { backgroundColor: colors.primary }]}>
              <Icon name="check-circle" size={24} color="white" />
            </View>
            <Text style={styles.uploadTitle}>Revisión final</Text>
            <Text style={styles.uploadSubtitle}>Verifica que todas las fotos se vean claras y legibles.</Text>
            <Text style={styles.stepCounter}>Paso {uploadStep} de {isBusinessAccount ? 6 : 5}</Text>
          </View>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, justifyContent: 'center', marginBottom: 16 }}>
            {!!frontImageUri && <Image source={{ uri: frontImageUri }} style={{ width: 120, height: 120 }} />}
            {!!backImageUri && <Image source={{ uri: backImageUri }} style={{ width: 120, height: 120 }} />}
            {!!selfieImageUri && <Image source={{ uri: selfieImageUri }} style={{ width: 120, height: 120 }} />}
            {!!payoutProofUri && <Image source={{ uri: payoutProofUri }} style={{ width: 120, height: 120 }} />}
            {isBusinessAccount && !!businessCertUri && <Image source={{ uri: businessCertUri }} style={{ width: 120, height: 120 }} />}
          </View>
          {/* Review details: DOB and payout method */}
          <View style={{ backgroundColor: '#F9FAFB', borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 8, padding: 12, marginBottom: 16 }}>
            <Text style={{ fontSize: 14, color: '#111827', fontWeight: '600', marginBottom: 8 }}>Detalles</Text>
            <Text style={{ fontSize: 14, color: '#374151', marginBottom: 4 }}>Fecha de nacimiento: {verifiedDob}</Text>
            <Text style={{ fontSize: 14, color: '#374151' }}>Método de pago: {payoutLabel}</Text>
          </View>
          <TouchableOpacity 
            style={[styles.primaryButton, { backgroundColor: (frontImageUri && backImageUri && selfieImageUri && payoutProofUri && (!isBusinessAccount || businessCertUri) && (payoutLabel || '').trim() && isValidDob(verifiedDob) ? colors.primary : '#D1D5DB') }]}
            disabled={!(frontImageUri && backImageUri && selfieImageUri && payoutProofUri && (!isBusinessAccount || businessCertUri) && (payoutLabel || '').trim() && isValidDob(verifiedDob))}
            onPress={async () => {
              try {
                setIsSubmitting(true);
                // Upload all staged files now
                const uploadOne = async (part: 'front'|'back'|'selfie'|'payout', uri: string) => {
                  const filename = `${part}-${Date.now()}.jpg`;
                  const contentType = 'image/jpeg';
                  const { data } = await requestIdentityUpload({ variables: { part, filename, contentType } });
                  const res = data?.requestIdentityUpload;
                  if (!res?.success) throw new Error(res?.error || 'Error solicitando URL de subida');
                  const upload = res.upload;
                  const fieldsObj = typeof upload.fields === 'string' ? JSON.parse(upload.fields) : upload.fields;
                  await uploadFileToPresignedForm(upload.url, fieldsObj, uri, filename, contentType);
                  return upload.key as string;
                };
                const fKey = await uploadOne('front', frontImageUri!);
                const bKey = await uploadOne('back', backImageUri!);
                const sKey = await uploadOne('selfie', selfieImageUri!);
                const pKey = await uploadOne('payout', payoutProofUri!);
                setFrontKey(fKey); setBackKey(bKey); setSelfieKey(sKey); setPayoutKey(pKey);
                // Business cert upload
                let bizKey: string | null = null;
                if (isBusinessAccount && businessCertUri) {
                  const filename = `business-${Date.now()}.jpg`;
                  const contentType = 'image/jpeg';
                  const { data } = await requestIdentityUpload({ variables: { part: 'business', filename, contentType } });
                  const res = data?.requestIdentityUpload;
                  if (!res?.success) throw new Error(res?.error || 'Error solicitando URL de subida (empresa)');
                  const upload = res.upload;
                  const fieldsObj = typeof upload.fields === 'string' ? JSON.parse(upload.fields) : upload.fields;
                  await uploadFileToPresignedForm(upload.url, fieldsObj, businessCertUri!, filename, contentType);
                  bizKey = upload.key as string;
                }
                const { data: submitData } = await submitIdentityVerificationS3({ variables: { frontKey: fKey, selfieKey: sKey, backKey: bKey, payoutMethodLabel: (payoutLabel || null), payoutProofKey: pKey, verifiedDateOfBirth: verifiedDob, businessKey: bizKey } });
                if (!submitData?.submitIdentityVerificationS3?.success) {
                  throw new Error(submitData?.submitIdentityVerificationS3?.error || 'Error al enviar verificación');
                }
                setIsSubmitting(false);
                setShowSuccess(true);
                setUploadStep(1);
                // Refresh user status to reflect pending verification
                try {
                  await Promise.all([
                    refetchMe(),
                    refetchPersonalKyc?.(),
                    refetchAnyKyc?.(),
                    isBusinessAccount ? (refetchBizKyc?.() as any || Promise.resolve()) : Promise.resolve(),
                  ])
                } catch {}
              } catch (e:any) {
                setIsSubmitting(false);
                console.error('[Verification] Submit failed:', e?.message || e);
              }
            }}
          >
            <Text style={styles.primaryButtonText}>Enviar verificación</Text>
          </TouchableOpacity>
        </View>
      );
    }
  };

  if (showUploadFlow) {
    const handleBackInFlow = () => {
      // If any modal is open, close it first
      if (showCamera) { setShowCamera(false); return; }
      // No custom gallery now
      if (previewUri) { setPreviewUri(null); return; }
      // Step-wise back navigation
      if (uploadStep > 1) {
        setUploadStep(uploadStep - 1);
        return;
      }
      // If at first step, exit upload flow without leaving the screen
      setShowUploadFlow(false);
    };
    return (
      <View style={styles.container}>
        <Header 
          title="Verificación de Identidad"
          navigation={navigation}
          backgroundColor={colors.primary}
          isLight={true}
          onBackPress={handleBackInFlow}
        />
        <ScrollView style={styles.scrollView}>
          {renderUploadFlow()}
        </ScrollView>
        {/* Success modal after submission */}
        <Modal visible={showSuccess} transparent animationType="fade" onRequestClose={() => setShowSuccess(false)}>
          <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
            <View style={{ backgroundColor: 'white', borderRadius: 12, width: '92%', maxWidth: 520, padding: 20, alignItems: 'center' }}>
              <View style={{ backgroundColor: colors.successLight, borderRadius: 32, width: 64, height: 64, justifyContent: 'center', alignItems: 'center', marginBottom: 12 }}>
                <Icon name="check" size={28} color={colors.success} />
              </View>
              <Text style={{ fontSize: 18, fontWeight: '700', color: '#111827', marginBottom: 6, textAlign: 'center' }}>Verificación enviada</Text>
              <Text style={{ fontSize: 14, color: '#374151', textAlign: 'center', marginBottom: 16 }}>
                Hemos recibido tus documentos. Tu verificación está en revisión. Te notificaremos cuando sea aprobada.
              </Text>
              <TouchableOpacity
                onPress={() => { setShowSuccess(false); setShowUploadFlow(false); }}
                style={{ width: '100%', paddingVertical: 14, borderRadius: 8, alignItems: 'center', backgroundColor: colors.primary }}
                activeOpacity={0.9}
              >
                <Text style={{ fontSize: 16, fontWeight: '500', color: 'white' }}>Entendido</Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>
        <Modal visible={showCamera} transparent animationType="slide" onRequestClose={() => setShowCamera(false)}>
          <View style={{ flex: 1, backgroundColor: '#000' }}>
            {((cameraPurpose === 'selfie') ? frontDevice : backDevice) ? (
              <Camera
                ref={cameraRef}
                style={{ flex: 1 }}
                device={(cameraPurpose === 'selfie') ? frontDevice! : backDevice!}
                isActive={true}
                photo={true}
              />
            ) : (
              <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
                <Text style={{ color: 'white' }}>Camera not available</Text>
              </View>
            )}
            <View style={{ position: 'absolute', bottom: 30, width: '100%', alignItems: 'center', justifyContent: 'center' }}>
              <TouchableOpacity onPress={handleCapture} style={{ width: 72, height: 72, borderRadius: 36, backgroundColor: 'white' }} />
            </View>
            <View style={{ position: 'absolute', top: 50, left: 20 }}>
              <TouchableOpacity onPress={() => setShowCamera(false)}>
                <Icon name="x" size={28} color="#FFFFFF" />
              </TouchableOpacity>
            </View>
          </View>
        </Modal>
        {/* Preview & confirm modal */}
        <Modal visible={!!previewUri} transparent animationType="fade" onRequestClose={() => setPreviewUri(null)}>
          <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.9)', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
            {previewUri && <Image source={{ uri: previewUri }} style={{ width: '90%', height: '60%', resizeMode: 'contain', marginBottom: 16 }} />}
            <Text style={{ color: 'white', marginBottom: 12, textAlign: 'center' }}>¿Se ven claras las letras y detalles? Si no, toma otra foto.</Text>
            <View style={{ flexDirection: 'row', gap: 12 }}>
              <TouchableOpacity onPress={() => setPreviewUri(null)} style={[styles.secondaryButton, { backgroundColor: '#374151' }]}>
                <Text style={[styles.secondaryButtonText, { color: 'white' }]}>Repetir</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => {
                if (previewPurpose === 'front') {
                  setFrontImageUri(previewUri!);
                  if (uploadStep === 1) setUploadStep(2);
                }
                if (previewPurpose === 'back') {
                  setBackImageUri(previewUri!);
                  if (uploadStep === 2) setUploadStep(3);
                }
                if (previewPurpose === 'selfie') {
                  setSelfieImageUri(previewUri!);
                  if (uploadStep === 3) setUploadStep(4);
                }
                if (previewPurpose === 'payout') {
                  setPayoutProofUri(previewUri!);
                }
                if (previewPurpose === 'business') {
                  setBusinessCertUri(previewUri!);
                  if (isBusinessAccount && uploadStep === 5) setUploadStep(6);
                }
                setPreviewUri(null);
              }} style={[styles.primaryButton, { backgroundColor: colors.primary }]}>
                <Text style={styles.primaryButtonText}>Se ve bien</Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>
        {/* Submitting overlay */}
        <Modal visible={isSubmitting} transparent animationType="fade">
          <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'center', alignItems: 'center' }}>
            <ActivityIndicator size="large" color="#fff" />
            <Text style={{ color: 'white', marginTop: 12 }}>Enviando verificación…</Text>
          </View>
        </Modal>
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
  stepCounter: {
    marginTop: 8,
    fontSize: 12,
    color: '#6B7280',
    fontWeight: '500',
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
