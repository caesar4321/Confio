import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform, Linking, Image, Share, Alert, Clipboard, AppState, AppStateStatus } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RootStackParamList, MainStackParamList } from '../types/navigation';
import { getCountryByIso } from '../utils/countries';
import { usePushNotificationPrompt } from '../hooks/usePushNotificationPrompt';
import { PushNotificationModal } from '../components/PushNotificationModal';
import { ReferralInputModal } from '../components/ReferralInputModal';
import { useQuery } from '@apollo/client';
import { GET_MY_REFERRALS } from '../apollo/queries';
import { biometricAuthService } from '../services/biometricAuthService';

// Utility function to format phone number with country code
const formatPhoneNumber = (phoneNumber?: string, phoneCountry?: string): string => {
  if (!phoneNumber) return '';

  // If we have a country code, format it
  if (phoneCountry) {
    const country = getCountryByIso(phoneCountry);
    if (country) {
      const countryCode = country[1]; // country[1] is the phone code (e.g., '+54')
      return `${countryCode} ${phoneNumber}`;
    }
  }

  return phoneNumber;
};

// Colors from the design
const colors = {
  primary: '#34d399', // emerald-400
  primaryText: '#34d399',
  primaryLight: '#d1fae5', // emerald-100
  primaryDark: '#10b981', // emerald-500
  secondary: '#8b5cf6', // violet-500
  secondaryText: '#8b5cf6',
  accent: '#3b82f6', // blue-500
  accentText: '#3b82f6',
  neutral: '#f9fafb', // gray-50
  neutralDark: '#f3f4f6', // gray-100
  dark: '#111827', // gray-900
};

type ProfileScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const ProfileScreen = () => {
  const { signOut, userProfile, isUserProfileLoading } = useAuth();
  const { activeAccount, accounts, isLoading: accountsLoading, refreshAccounts } = useAccount();
  const navigation = useNavigation<ProfileScreenNavigationProp>();
  const { showModal, handleAllow, handleDeny, checkAndShowPrompt, needsSettings } = usePushNotificationPrompt();
  const [hasCheckedThisFocus, setHasCheckedThisFocus] = React.useState(false);
  const rawUsername = userProfile?.username || '';
  const username = rawUsername ? `@${rawUsername}` : '';
  const normalizedCountryIso = React.useMemo(() => {
    const iso =
      (userProfile as any)?.phone_country ||
      (userProfile as any)?.phoneCountry ||
      '';
    return iso ? String(iso).toUpperCase() : null;
  }, [userProfile]);
  const needsFriendlyUsername = React.useMemo(() => {
    if (!rawUsername) return true;
    if (rawUsername.startsWith('user_')) return true;
    // Treat long alphanumeric handles without separators as auto-generated
    if (/^[a-z0-9]{10,}$/.test(rawUsername)) return true;
    return false;
  }, [rawUsername]);
  const [showReferralModal, setShowReferralModal] = React.useState(false);
  const [biometricAvailable, setBiometricAvailable] = React.useState(false);
  const [biometricEnabled, setBiometricEnabled] = React.useState(false);
  const [biometricLoading, setBiometricLoading] = React.useState(true);
  const [biometricActionLoading, setBiometricActionLoading] = React.useState(false);
  const [biometricError, setBiometricError] = React.useState<string | null>(null);
  const appState = React.useRef(AppState.currentState);

  const referralShareMessage = React.useMemo(() => {
    // Generate clean, uppercase username for the link
    const rawName = (userProfile?.username || '').replace('@', '');
    const cleanUsername = rawName.toUpperCase();
    const inviteLink = `https://confio.lat/invite/${cleanUsername}`;

    return [
      'Te envié un regalo de US$5 en $CONFIO 🎁',
      '',
      'Estoy usando Confío para guardar dólares sin bancos y sin restricciones.',
      'Es como una bóveda digital personal 💰✨',
      '',
      '👇 Reclamá tu regalo acá:',
      inviteLink,
      '',
      `Código: ${cleanUsername}`,
      '',
      '(El regalo se activa cuando cargues tus primeros 20 USDC y los pases a cUSD)',
    ].join('\n');
  }, [userProfile?.username]);

  const handleShareReferral = React.useCallback(async () => {
    const encodedMessage = encodeURIComponent(referralShareMessage);
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
      console.error('Error al abrir WhatsApp:', error);
      try {
        await Share.share({
          message: referralShareMessage,
          title: 'Invitación Confío',
        });
      } catch (shareError) {
        console.error('Error al usar el menú compartir:', shareError);
      }
    }
  }, [referralShareMessage]);

  const handleCopyUsername = React.useCallback(() => {
    if (!username) {
      Alert.alert(
        'Configura tu usuario',
        'Edita tu perfil y crea un @usuario para poder invitar amigos y ganar US$5.'
      );
      return;
    }
    Clipboard.setString(username);
    Alert.alert('Usuario copiado', 'Comparte tu @usuario por WhatsApp o redes sociales.');
  }, [username]);
  // Debug active account changes to ensure real-time updates
  React.useEffect(() => {
    console.log('ProfileScreen - activeAccount changed:', {
      activeAccountId: activeAccount?.id,
      activeAccountName: activeAccount?.name,
      activeAccountType: activeAccount?.type,
      isLoading: accountsLoading
    });
  }, [activeAccount, accountsLoading]);

  // Helper function to check biometric support
  const checkBiometricSupport = React.useCallback(async () => {
    try {
      console.log('[ProfileScreen] Checking biometric support...');
      biometricAuthService.invalidateCache();
      const supported = await biometricAuthService.isSupported();
      console.log('[ProfileScreen] Biometric supported:', supported);
      setBiometricAvailable(supported);
      if (supported) {
        const enabled = await biometricAuthService.isEnabled();
        setBiometricEnabled(enabled);
      } else {
        setBiometricEnabled(false);
      }
      setBiometricError(null);
    } catch (error) {
      console.error('[Profile] Failed to load biometric status:', error);
      setBiometricError('No se pudo validar la biometría del dispositivo.');
    } finally {
      setBiometricLoading(false);
    }
  }, []);

  // Load biometric capability + preference on mount
  React.useEffect(() => {
    let alive = true;
    (async () => {
      if (alive) {
        await checkBiometricSupport();
      }
    })();
    return () => { alive = false; };
  }, [checkBiometricSupport]);

  // Listen for app state changes (e.g., returning from Settings)
  React.useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextAppState: AppStateStatus) => {
      console.log('[ProfileScreen] AppState changed:', appState.current, '->', nextAppState);

      // App has come to the foreground
      if (appState.current.match(/inactive|background/) && nextAppState === 'active') {
        console.log('[ProfileScreen] App returned to foreground, re-checking biometrics');
        setBiometricLoading(true);
        checkBiometricSupport();
      }

      appState.current = nextAppState;
    });

    return () => {
      subscription.remove();
    };
  }, [checkBiometricSupport]);

  const handleBiometricUpdate = React.useCallback(async () => {
    if (biometricLoading || biometricActionLoading) return;
    setBiometricError(null);
    setBiometricActionLoading(true);
    try {
      if (!biometricAvailable) {
        setBiometricError('Este dispositivo no soporta biometría.');
        return;
      }

      // Always end with biometría activa; if ya está, re-registra por seguridad
      if (biometricEnabled) {
        await biometricAuthService.disable();
      }
      const enabled = await biometricAuthService.enable();
      setBiometricEnabled(enabled);
      if (!enabled) {
        setBiometricError('No pudimos activar la biometría. Inténtalo nuevamente.');
      }
    } catch (error) {
      console.error('[Profile] Failed to update biometrics:', error);
      setBiometricError('Ocurrió un problema al actualizar la biometría.');
    } finally {
      setBiometricActionLoading(false);
      setBiometricLoading(false);
    }
  }, [biometricAvailable, biometricEnabled, biometricActionLoading, biometricLoading]);

  // Force refresh when screen comes into focus to ensure latest state
  useFocusEffect(
    React.useCallback(() => {
      console.log('ProfileScreen - Screen focused, refreshing accounts and biometric status');
      refreshAccounts();

      // Re-check biometric availability when screen comes into focus
      setBiometricLoading(true);
      checkBiometricSupport();

      // Reset the check flag when screen loses focus
      return () => {
        setHasCheckedThisFocus(false);
      };
    }, [refreshAccounts, checkBiometricSupport])
  );

  // Separate effect for push notification check to avoid infinite loop
  React.useEffect(() => {
    if (!hasCheckedThisFocus && !showModal) {
      console.log('[ProfileScreen] Checking push notification permission...');
      setHasCheckedThisFocus(true);
      checkAndShowPrompt();
    }
  }, [hasCheckedThisFocus, showModal, checkAndShowPrompt]);

  const handleLegalDocumentPress = (docType: 'terms' | 'privacy' | 'deletion') => {
    navigation.navigate('LegalDocument', { docType });
  };

  const handleTelegramPress = async () => {
    const telegramUrl = 'tg://resolve?domain=confio4world';
    const webUrl = 'https://t.me/confio4world';
    try {
      const canOpen = await Linking.canOpenURL(telegramUrl);
      if (canOpen) {
        await Linking.openURL(telegramUrl);
      } else {
        // Fallback to t.me URL
        await Linking.openURL(webUrl);
      }
    } catch (error) {
      console.error('Error opening Telegram link:', error);
      // Fallback to t.me URL
      await Linking.openURL(webUrl);
    }
  };

  const handleSocialMediaPress = async (platform: 'tiktok' | 'instagram' | 'youtube') => {
    let url = '';
    switch (platform) {
      case 'tiktok':
        url = 'https://www.tiktok.com/@julianmoonluna';
        break;
      case 'instagram':
        url = 'https://www.instagram.com/julianmoonluna';
        break;
      case 'youtube':
        url = 'https://www.youtube.com/@julianmoonluna';
        break;
    }

    try {
      await Linking.openURL(url);
    } catch (error) {
      console.error(`Error opening ${platform} link:`, error);
    }
  };

  // Get display information based on active account
  const getDisplayInfo = () => {
    // Only show loading when we have no data yet
    const stillFetching = (accountsLoading && !activeAccount) ||
      (isUserProfileLoading && !userProfile);

    if (stillFetching) {
      return { name: 'Cargando...', subtitle: '', showAccountType: false };
    }

    if (activeAccount) {
      const isPersonal = activeAccount.type.toLowerCase() === 'personal';
      const accountType = isPersonal ? 'Personal' : 'Negocio';

      if (isPersonal) {
        // For personal accounts, show user profile info with phone number (no account type label)
        const displayName = userProfile?.firstName || userProfile?.username || activeAccount.name;
        const phoneNumber = formatPhoneNumber(userProfile?.phoneNumber, userProfile?.phoneCountry);
        return {
          name: displayName,
          subtitle: phoneNumber,
          accountType: '',
          showAccountType: false
        };
      } else {
        // For business accounts, show business info with account type only (no category)
        return {
          name: activeAccount.name,
          subtitle: '',
          accountType,
          showAccountType: true
        };
      }
    }

    // Fallback to user profile with phone number (no account type label)
    const displayName = userProfile?.firstName || userProfile?.username || 'Sin perfil';
    const phoneNumber = formatPhoneNumber(userProfile?.phoneNumber, userProfile?.phoneCountry);
    return {
      name: displayName,
      subtitle: phoneNumber,
      accountType: '',
      showAccountType: false
    };
  };

  const displayInfo = getDisplayInfo();

  const { data: referralData } = useQuery(GET_MY_REFERRALS, {
    fetchPolicy: 'cache-and-network',
  });

  const referralStats = React.useMemo(() => {
    if (!referralData?.myReferrals || !userProfile?.id) return { pending: 0, claimable: 0, isReferred: false };

    const currentUserId = String(userProfile.id);
    let pending = 0;
    let claimable = 0;
    let isReferred = false;

    referralData.myReferrals.forEach((ref: any) => {
      const isReferrer = String(ref.referrerUser?.id) === currentUserId;
      const isReferee = String(ref.referredUser?.id) === currentUserId;

      if (isReferee) isReferred = true;

      const frameworkStatus = isReferrer ? ref.referrerRewardStatus : ref.refereeRewardStatus;
      const amount = isReferrer ? (ref.rewardReferrerConfio || 0) : (ref.rewardRefereeConfio || 0);

      // 'pending' or 'locked' count as pending. 'ready' counts as claimable.
      if (frameworkStatus === 'pending' || frameworkStatus === 'locked') {
        pending += amount;
      } else if (frameworkStatus === 'ready') {
        claimable += amount;
      }
    });

    return { pending, claimable, isReferred };
  }, [referralData, userProfile]);

  return (
    <>
      <ScrollView style={styles.container} contentContainerStyle={styles.scrollContent}>
        {/* Header Section */}
        <View style={styles.header}>
          <View style={styles.profileInfo}>
            <TouchableOpacity
              style={styles.avatarContainer}
              onPress={() => {
                const isBusiness = activeAccount?.type.toLowerCase() === 'business';
                if (isBusiness) {
                  navigation.navigate('EditBusiness');
                } else {
                  navigation.navigate('EditProfile');
                }
              }}
            >
              <Text style={styles.avatarText}>
                {activeAccount?.avatar || (userProfile?.firstName?.charAt(0) || userProfile?.username?.charAt(0) || 'U')}
              </Text>
              <View style={styles.editIconContainer}>
                <Icon name="edit-2" size={12} color="#fff" />
              </View>
            </TouchableOpacity>
            <Text style={styles.name}>{displayInfo.name}</Text>
            {displayInfo.showAccountType && (
              <Text style={styles.accountType}>{displayInfo.accountType}</Text>
            )}
            {displayInfo.subtitle && (
              <Text style={styles.subtitle}>{displayInfo.subtitle}</Text>
            )}
          </View>
        </View>

        {/* Referral Program Card */}
        {activeAccount?.type.toLowerCase() !== 'business' && (
          <View style={styles.referralCard}>
            <View style={styles.referralHeader}>
              <View style={styles.referralIconBadge}>
                <Icon name="lock" size={20} color="#FFFFFF" />
              </View>
              <View style={styles.referralHeaderText}>
                <Text style={styles.referralTitle}>Regalá US$5 en $CONFIO y recibí US$5 vos también</Text>
                <Text style={styles.referralSubtitle}>
                  Tu amigo se crea la cuenta con tu link. Listo: ambos reciben US$5 en $CONFIO (se activan cuando cargan sus primeros 20 USDC y los pasan a cUSD).
                </Text>
              </View>
            </View>

            <View style={styles.referralActions}>
              <TouchableOpacity style={styles.referralShareButton} onPress={handleShareReferral}>
                <WhatsAppLogo width={20} height={20} style={{ marginRight: 8 }} />
                <Text style={styles.referralShareText}>Enviar regalo por WhatsApp</Text>
              </TouchableOpacity>
            </View>

            <TouchableOpacity
              style={[
                styles.referralClaimButton,
                // Change style if claimable
                referralStats.claimable > 0 && { backgroundColor: '#ECFDF5', borderColor: '#10B981', borderLeftWidth: 4 }
              ]}
              onPress={() => navigation.navigate('ReferralRewardClaim' as never)}
            >
              <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
                {referralStats.claimable > 0 ? (
                  <Text style={{ marginRight: 8 }}>🟢</Text>
                ) : referralStats.pending > 0 ? (
                  <Text style={{ marginRight: 8 }}>🔴</Text>
                ) : (
                  <Icon name="unlock" size={16} color="#10b981" style={{ marginRight: 8 }} />
                )}

                <Text style={[
                  styles.referralClaimText,
                  referralStats.claimable > 0 && { color: '#047857', fontWeight: '700' },
                  referralStats.pending > 0 && { color: '#B91C1C' } // dark red
                ]}>
                  {referralStats.claimable > 0
                    ? `${referralStats.claimable} $CONFIO Listos para Desbloquear`
                    : referralStats.pending > 0
                      ? `${referralStats.pending} $CONFIO Pendientes`
                      : 'Ver mis recompensas ($CONFIO)'}
                </Text>
              </View>
              <Icon name="chevron-right" size={16} color={referralStats.claimable > 0 ? '#047857' : '#10b981'} />
            </TouchableOpacity>

            {needsFriendlyUsername && (
              <TouchableOpacity style={styles.referralUpdateUsername} onPress={() => navigation.navigate('UpdateUsername')}>
                <Icon name="edit-3" size={16} color="#047857" />
                <Text style={styles.referralUpdateUsernameText}>Personalizar mi código</Text>
                <Icon name="chevron-right" size={16} color="#047857" />
              </TouchableOpacity>
            )}

            {!referralStats.isReferred && (
              <TouchableOpacity
                style={styles.referralUpdateUsername}
                onPress={() => navigation.navigate('Achievements' as never)}
              >
                <Icon name="user-plus" size={16} color="#047857" />
                <Text style={styles.referralUpdateUsernameText}>¿Te invitó alguien? Poné su código</Text>
                <Icon name="chevron-right" size={16} color="#047857" />
              </TouchableOpacity>
            )}

            <View style={styles.referralCriteria}>
              <Text style={styles.referralCriteriaTitle}>¿Cómo funciona el desbloqueo?</Text>
              <Text style={styles.referralCriteriaItem}>1. Compartí tu link.</Text>
              <Text style={styles.referralCriteriaItem}>2. Tu amigo se crea la cuenta (recibe US$5 en $CONFIO que se activan luego).</Text>
              <Text style={styles.referralCriteriaItem}>3. Carga 20 USDC, pásalos a cUSD y se activan los US$5 en $CONFIO para los dos.</Text>

              <TouchableOpacity onPress={() => navigation.navigate('Achievements' as never)}>
                <Text style={[styles.referralCriteriaItem, { color: '#3B82F6', marginTop: 4, fontWeight: '600' }]}>
                  Ver instrucciones completas
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* Account Management Card */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Icon name="user" size={20} color="#6B7280" />
              <Text style={styles.cardTitle}>Cuenta</Text>
            </View>
          </View>
          <View style={styles.cardOptions}>
            <TouchableOpacity
              style={styles.cardOption}
              onPress={() => navigation.navigate('Verification')}
            >
              <Icon name="user-check" size={18} color="#6B7280" />
              <Text style={styles.cardOptionText}>Verificación</Text>
              <Icon name="chevron-right" size={16} color="#9CA3AF" />
            </TouchableOpacity>
            {activeAccount?.type.toLowerCase() === 'personal' && (
              <TouchableOpacity
                style={styles.cardOption}
                onPress={() => navigation.navigate('UpdateUsername')}
              >
                <Icon name="edit-3" size={18} color="#6B7280" />
                <Text style={styles.cardOptionText}>Editar usuario Confío</Text>
                <Icon name="chevron-right" size={16} color="#9CA3AF" />
              </TouchableOpacity>
            )}

            {/* Payment methods menu: allow VE users; iOS only in debug */}
            {activeAccount?.type.toLowerCase() === 'personal' && (
              <TouchableOpacity
                style={styles.cardOption}
                onPress={() => navigation.navigate('ConfioAddress')}
              >
                <Icon name="at-sign" size={18} color="#6B7280" />
                <Text style={styles.cardOptionText}>Compartir mi usuario</Text>
                <Icon name="chevron-right" size={16} color="#9CA3AF" />
              </TouchableOpacity>
            )}

            {/* Payment methods menu: allow VE users; iOS only in debug */}
            {normalizedCountryIso === 'VE' && (Platform.OS === 'android' || (Platform.OS === 'ios' && __DEV__)) &&
              (!activeAccount?.isEmployee || activeAccount?.employeePermissions?.manageBankAccounts) && (
                <TouchableOpacity
                  style={styles.cardOption}
                  onPress={() => navigation.navigate('BankInfo')}
                >
                  <Icon name="credit-card" size={18} color="#6B7280" />
                  <Text style={styles.cardOptionText}>Métodos de Pago</Text>
                  <Icon name="chevron-right" size={16} color="#9CA3AF" />
                </TouchableOpacity>
              )}

            {/* Hidden: Notifications are mandatory for financial apps
          <TouchableOpacity 
            style={styles.cardOption}
            onPress={() => navigation.navigate('NotificationSettings')}
          >
            <Icon name="bell" size={18} color="#6B7280" />
            <Text style={styles.cardOptionText}>Notificaciones</Text>
            <Icon name="chevron-right" size={16} color="#9CA3AF" />
          </TouchableOpacity>
          */}
          </View>
        </View>

        {/* Security Card */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Icon name="shield" size={20} color="#6B7280" />
              <Text style={styles.cardTitle}>Seguridad</Text>
            </View>
          </View>
          <View style={styles.cardOptions}>
            <TouchableOpacity
              style={[
                styles.cardOption,
                (!biometricAvailable || biometricLoading || biometricActionLoading) && styles.cardOptionDisabled
              ]}
              onPress={handleBiometricUpdate}
              disabled={!biometricAvailable || biometricLoading || biometricActionLoading}
            >
              <Icon name="smartphone" size={18} color={biometricAvailable ? "#10B981" : "#9CA3AF"} />
              <View style={styles.biometricTextContainer}>
                <Text style={styles.biometricTitle}>Biometría</Text>
                {biometricLoading ? (
                  <Text style={styles.biometricStatusText}>Verificando...</Text>
                ) : !biometricAvailable ? (
                  <Text style={styles.biometricStatusUnavailable}>No disponible</Text>
                ) : biometricEnabled ? (
                  <Text style={styles.biometricStatusActive}>Activa</Text>
                ) : (
                  <Text style={styles.biometricStatusText}>Toca para activar</Text>
                )}
              </View>
              {biometricAvailable && !biometricLoading && (
                <Icon name="chevron-right" size={16} color="#9CA3AF" />
              )}
            </TouchableOpacity>
          </View>
        </View>

        {/* Community Card */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Icon name="users" size={20} color="#6B7280" />
              <Text style={styles.cardTitle}>Comunidad & Soporte</Text>
            </View>
          </View>
          <View style={styles.cardOptions}>
            <TouchableOpacity
              style={styles.cardOption}
              onPress={handleTelegramPress}
            >
              <Icon name="message-circle" size={18} color="#6B7280" />
              <Text style={styles.cardOptionText}>Grupo Telegram</Text>
              <Text style={styles.cardOptionSubtext}>@confio4world</Text>
              <Icon name="chevron-right" size={16} color="#9CA3AF" />
            </TouchableOpacity>
          </View>
        </View>

        {/* Follow the Founder Section */}
        <View style={styles.founderSection}>
          <View style={styles.founderHeader}>
            <Icon name="star" size={20} color={colors.primary} />
            <Text style={styles.founderTitle}>Sigue al fundador</Text>
          </View>

          <View style={styles.socialButtonsContainer}>
            <TouchableOpacity
              style={styles.socialImageButton}
              onPress={() => handleSocialMediaPress('tiktok')}
            >
              <Image
                source={require('../assets/png/TikTok.png')}
                style={[styles.socialButtonImage, styles.tiktokImage]}
                resizeMode="contain"
              />
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.socialImageButton}
              onPress={() => handleSocialMediaPress('instagram')}
            >
              <Image
                source={require('../assets/png/Instagram.png')}
                style={styles.socialButtonImage}
                resizeMode="contain"
              />
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.socialImageButton}
              onPress={() => handleSocialMediaPress('youtube')}
            >
              <Image
                source={require('../assets/png/YouTube.png')}
                style={styles.socialButtonImage}
                resizeMode="contain"
              />
            </TouchableOpacity>
          </View>

          <View style={styles.founderStory}>
            <Text style={styles.founderHandle}>@julianmoonluna</Text>
            <Text style={styles.founderTagline}>
              Un coreano que sueña con una nueva Latinoamérica
            </Text>
            <Text style={styles.founderDescription}>
              Descubre por qué un coreano confía en América Latina
            </Text>
          </View>
        </View>

        {/* Legal Links */}
        <View style={styles.legalSection}>
          <TouchableOpacity
            style={styles.legalLink}
            onPress={() => handleLegalDocumentPress('terms')}
          >
            <Text style={styles.legalLinkText}>Términos de Servicio</Text>
          </TouchableOpacity>
          <Text style={styles.legalSeparator}>•</Text>
          <TouchableOpacity
            style={styles.legalLink}
            onPress={() => handleLegalDocumentPress('privacy')}
          >
            <Text style={styles.legalLinkText}>Privacidad</Text>
          </TouchableOpacity>
          <Text style={styles.legalSeparator}>•</Text>
          <TouchableOpacity
            style={styles.legalLink}
            onPress={() => handleLegalDocumentPress('deletion')}
          >
            <Text style={styles.legalLinkText}>Eliminación</Text>
          </TouchableOpacity>
        </View>

        {/* Sign Out Button */}
        <TouchableOpacity style={styles.signOutButton} onPress={signOut}>
          <Text style={styles.signOutText}>Cerrar Sesión</Text>
        </TouchableOpacity>
      </ScrollView>
      <ReferralInputModal
        visible={showReferralModal}
        onClose={() => setShowReferralModal(false)}
        onSuccess={() => setShowReferralModal(false)}
      />

      {/* Push Notification Permission Modal */}
      <PushNotificationModal
        visible={showModal}
        onAllow={handleAllow}
        onDeny={handleDeny}
        needsSettings={needsSettings}
      />
    </>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  scrollContent: {
    flexGrow: 1,
  },
  header: {
    backgroundColor: '#34d399', // emerald-400
    paddingBottom: 32,
    paddingHorizontal: 20,
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
  },
  profileInfo: {
    alignItems: 'center',
  },
  avatarContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#fff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
    position: 'relative',
  },
  avatarText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#34d399',
  },
  editIconContainer: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: '#fff',
  },
  name: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 4,
  },
  accountType: {
    fontSize: 14,
    color: 'rgba(255, 255, 255, 0.9)',
    marginBottom: 2,
  },
  subtitle: {
    fontSize: 14,
    color: 'rgba(255, 255, 255, 0.8)',
  },
  card: {
    backgroundColor: '#fff',
    borderRadius: 16,
    marginHorizontal: 16,
    marginBottom: 12,
    padding: 16,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.05,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  cardTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
  },
  cardOptions: {
    gap: 12,
  },
  cardOption: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
  },
  cardOptionText: {
    flex: 1,
    fontSize: 15,
    color: '#374151',
    marginLeft: 12,
  },
  cardOptionSubtext: {
    fontSize: 13,
    color: '#9CA3AF',
    marginRight: 8,
  },
  cardOptionDisabled: {
    opacity: 0.5,
  },
  biometricTextContainer: {
    flex: 1,
    marginLeft: 12,
    flexDirection: 'column',
  },
  biometricTitle: {
    fontSize: 15,
    color: '#374151',
  },
  biometricStatusText: {
    fontSize: 13,
    color: '#6B7280',
    marginTop: 4,
  },
  biometricStatusActive: {
    fontSize: 13,
    color: '#10B981',
    marginTop: 4,
    fontWeight: '500',
  },
  biometricStatusUnavailable: {
    fontSize: 13,
    color: '#EF4444',
    marginTop: 4,
  },
  referralCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    marginHorizontal: 16,
    marginBottom: 16,
    padding: 20,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 8 },
        shadowOpacity: 0.08,
        shadowRadius: 12,
      },
      android: {
        elevation: 3,
      },
    }),
  },
  referralHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 16,
    marginBottom: 16,
  },
  referralIconBadge: {
    width: 48,
    height: 48,
    borderRadius: 16,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  referralHeaderText: {
    flex: 1,
    gap: 4,
  },
  referralTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111827',
  },
  referralSubtitle: {
    fontSize: 13,
    color: '#6B7280',
    lineHeight: 18,
  },
  referralUsername: {
    backgroundColor: '#ECFDF5',
    borderRadius: 16,
    paddingVertical: 12,
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  referralUsernameLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#047857',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 4,
  },
  referralUsernameValue: {
    fontSize: 16,
    fontWeight: '700',
    color: '#047857',
  },
  referralUsernameHint: {
    marginTop: 8,
    fontSize: 12,
    color: '#047857',
    lineHeight: 18,
  },
  referralActions: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 18,
  },
  referralCopyButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: '#ECFDF5',
    gap: 8,
  },
  referralCopyText: {
    color: '#047857',
    fontWeight: '600',
    fontSize: 14,
  },
  referralShareButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: '#047857',
    gap: 8,
  },
  referralShareText: {
    color: '#FFFFFF',
    fontWeight: '600',
    fontSize: 14,
  },
  referralClaimButton: {
    marginBottom: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(16,185,129,0.3)',
    paddingVertical: 12,
    paddingHorizontal: 16,
    backgroundColor: '#ecfdf5',
    gap: 8,
  },
  referralClaimText: {
    flex: 1,
    marginHorizontal: 12,
    color: '#047857',
    fontWeight: '600',
    fontSize: 14,
  },
  referralUpdateUsername: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 12,
    backgroundColor: '#F3F4F6',
    marginBottom: 18,
  },
  referralUpdateUsernameText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: '#047857',
  },
  referralSteps: {
    gap: 12,
    marginBottom: 16,
  },
  referralStep: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  referralStepNumber: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: '#ECFDF5',
    textAlign: 'center',
    lineHeight: 24,
    fontWeight: '700',
    fontSize: 13,
    color: '#047857',
  },
  referralStepText: {
    flex: 1,
    fontSize: 13,
    color: '#6B7280',
    lineHeight: 19,
  },
  referralCriteria: {
    marginTop: 4,
    marginBottom: 16,
    padding: 14,
    borderRadius: 12,
    backgroundColor: '#F9FAFB',
    gap: 4,
  },
  referralCriteriaTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: '#374151',
    marginBottom: 4,
  },
  referralCriteriaItem: {
    fontSize: 13,
    color: '#6B7280',
    lineHeight: 18,
  },
  referralCriteriaNote: {
    marginTop: 8,
    fontSize: 12,
    color: '#047857',
  },
  referralRegisterButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 12,
    backgroundColor: '#ECFDF5',
    marginBottom: 12,
  },
  referralRegisterButtonText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: '#047857',
  },
  referralLink: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  referralLinkText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#047857',
  },
  founderSection: {
    paddingHorizontal: 16,
    paddingVertical: 20,
    alignItems: 'center',
  },
  separator: {
    height: 1,
    backgroundColor: '#E5E7EB',
    marginHorizontal: 16,
    marginVertical: 8,
  },
  founderHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
    gap: 8,
  },
  founderTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#1F2937',
  },
  socialButtonsContainer: {
    flexDirection: 'row',
    marginVertical: 16,
    justifyContent: 'center',
    alignItems: 'center',
  },
  socialImageButton: {
    width: 69, // Fixed width for all buttons (53 + 16 padding)
    height: 69, // Fixed height for all buttons
    justifyContent: 'center',
    alignItems: 'center',
    marginHorizontal: 10, // Equal spacing between buttons
  },
  socialButtonImage: {
    width: 53, // 2/3 of 80px for Instagram and YouTube
    height: 53,
  },
  tiktokImage: {
    width: 40, // Keep TikTok at original size
    height: 40,
  },
  founderStory: {
    alignItems: 'center',
    gap: 4,
  },
  founderHandle: {
    fontSize: 16,
    color: colors.primary,
    fontWeight: '700',
    marginBottom: 4,
  },
  founderTagline: {
    fontSize: 15,
    color: '#1F2937',
    fontWeight: '600',
    textAlign: 'center',
  },
  founderDescription: {
    fontSize: 13,
    color: '#6B7280',
    textAlign: 'center',
    fontStyle: 'italic',
  },
  legalSection: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 16,
    marginTop: 16,
    marginBottom: 8,
  },
  legalLink: {
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  legalLinkText: {
    fontSize: 13,
    color: '#6B7280',
  },
  legalSeparator: {
    color: '#E5E7EB',
    fontSize: 13,
  },
  signOutButton: {
    marginTop: 16,
    marginBottom: 32,
    paddingVertical: 12,
    alignItems: 'center',
  },
  signOutText: {
    color: '#EF4444',
    fontSize: 16,
    fontWeight: '500',
  },
}); 
