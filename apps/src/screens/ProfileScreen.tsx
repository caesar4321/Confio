import { reportGuideTap, useGuideAnchor, useScrollToGuidePointer } from '../assistant/guidePointer';
import React from 'react';
import { View, StyleSheet, TouchableOpacity, ScrollView, Platform, Linking, Image, Alert, AppState, AppStateStatus } from 'react-native';
import { Text } from '../components/common/AppText';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { useAuth, useAuthReady } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { ReferralInputModal } from '../components/ReferralInputModal';
import { BackupConsentModal } from '../components/BackupConsentModal';
import { DriveStorageFullModal } from '../components/DriveStorageFullModal';
import { useQuery } from '@apollo/client';
import { GET_MY_PROFILE_PICTURE } from '../apollo/queries';
import { biometricAuthService } from '../services/biometricAuthService';
import authService from '../services/authService';
import { AnalyticsService } from '../services/analyticsService';
import { StatusTierBadge } from '../components/StatusTierBadge';
import { colors } from '../config/theme';
import { CONVERSATION_HOME_ENABLED } from '../config/features';
import DeviceInfo from 'react-native-device-info';
import { Button } from '../components/common/Button';
import { profileDisplayInfo } from './profileDisplayInfo';
import { useFloatingPrimaryInset } from '../home/useFloatingPrimaryInset';

// Utility function to format phone number with country code

// Colors from the design
type ProfileScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const ProfileScreen = () => {
  // Room for the floating Pagar button at the end of the list (conversation home).
  const floatingInset = useFloatingPrimaryInset();
  const verificationAnchor = useGuideAnchor('profile_verification');
  const inviteAnchor = useGuideAnchor('profile_invite');
  const scrollRef = React.useRef<ScrollView>(null);
  const onGuideScroll = useScrollToGuidePointer(scrollRef);
  const { signOut, userProfile, isUserProfileLoading } = useAuth();
  const { activeAccount, accounts, isLoading: accountsLoading, refreshAccounts } = useAccount();
  const navigation = useNavigation<ProfileScreenNavigationProp>();
  const rawUsername = userProfile?.username || '';
  const username = rawUsername ? `@${rawUsername}` : '';
  const normalizedCountryIso = React.useMemo(() => {
    const iso =
      (userProfile as any)?.phone_country ||
      (userProfile as any)?.phoneCountry ||
      '';
    return iso ? String(iso).toUpperCase() : null;
  }, [userProfile]);
  const canManageBankAccounts = !activeAccount?.isEmployee || Boolean((activeAccount as any)?.employeePermissions?.manageBankAccounts);
  const [showReferralModal, setShowReferralModal] = React.useState(false);
  // Measured size of the header field. Its height changes after mount (name,
  // tier badge, phone load async) and an absoluteFill Svg with percentage
  // sizes doesn't repaint on parent growth — the stale gradient leaves a flat
  // light band at the bottom. Explicit dimensions force a redraw.
  const [fieldSize, setFieldSize] = React.useState({ width: 0, height: 0 });
  const [showBackupModal, setShowBackupModal] = React.useState(false);
  const [showDriveStorageFull, setShowDriveStorageFull] = React.useState(false);
  const [driveBackupEnabled, setDriveBackupEnabled] = React.useState(false);
  const [biometricAvailable, setBiometricAvailable] = React.useState(false);
  const [biometricEnabled, setBiometricEnabled] = React.useState(false);
  const [biometricLoading, setBiometricLoading] = React.useState(true);
  const [biometricActionLoading, setBiometricActionLoading] = React.useState(false);
  const [biometricError, setBiometricError] = React.useState<string | null>(null);
  const appState = React.useRef(AppState.currentState);

  // Debug active account changes to ensure real-time updates
  React.useEffect(() => {
  }, [activeAccount, accountsLoading]);

  // Track if user has manually enabled backup during this session
  const driveBackupManuallyEnabled = React.useRef(false);

  // Initialize Google Drive backup switch from user profile
  // Only set to true on initial load, don't reset after user manually enables
  React.useEffect(() => {
    const backupProvider = (userProfile as any)?.backupProvider?.toLowerCase();

    // Show as active if ANY backup is enabled (iCloud OR Google Drive)
    if (backupProvider === 'google_drive' || backupProvider === 'icloud') {
      setDriveBackupEnabled(true);
    } else if (!driveBackupManuallyEnabled.current) {
      // Only set to false if user hasn't manually enabled this session
      // This prevents userProfile refetch from resetting the switch
      setDriveBackupEnabled(false);
    }
  }, [userProfile]);

  // Helper function to check biometric support
  const checkBiometricSupport = React.useCallback(async () => {
    try {
      biometricAuthService.invalidateCache();
      const supported = await biometricAuthService.isSupported();
      setBiometricAvailable(supported);
      if (supported) {
        const enabled = await biometricAuthService.isEnabled();
        setBiometricEnabled(enabled);
      } else {
        setBiometricEnabled(false);
      }
      setBiometricError(null);
    } catch (error) {
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

      // App has come to the foreground
      if (appState.current.match(/inactive|background/) && nextAppState === 'active') {
        setBiometricLoading(true);
        checkBiometricSupport();
      }

      appState.current = nextAppState;
    });

    return () => {
      subscription.remove();
    };
  }, [checkBiometricSupport]);

  // Handle Backup Press with Biometric Check
  const handleBackupPress = async () => {
    // Require biometric authentication if available and enabled
    if (biometricAvailable && biometricEnabled) {
      const bioSuccess = await biometricAuthService.authenticate('Autoriza el respaldo en Google Drive');
      if (!bioSuccess) return;
    }
    setShowBackupModal(true);
  };

  const runDriveBackup = async () => {
    try {
      // Logic to enable drive: trigger sign-in with scope
      AnalyticsService.logBackupAttempt('google_drive');
      const result = await authService.enableDriveBackup();

      if (result.success) {
        driveBackupManuallyEnabled.current = true;
        setDriveBackupEnabled(true);
        Alert.alert('Respaldo Activado', 'Tu copia de seguridad en Google Drive está activa y sincronizada.');
      } else if (result.storageFull) {
        setShowDriveStorageFull(true);
      } else if (result.error) {
        Alert.alert('Error', result.error);
      }
    } catch (e) {
      console.warn('[ProfileScreen] Drive backup failed:', e);
    }
  };

  const handleBiometricUpdate = React.useCallback(async () => {
    if (biometricLoading || biometricActionLoading) return;
    setBiometricError(null);
    setBiometricActionLoading(true);
    try {
      if (!biometricAvailable) {
        setBiometricError('Este dispositivo no soporta biometría.');
        return;
      }

      // A working enrollment is only confirmed, never switched off first: a
      // cancelled prompt must not leave the app unprotected. Re-register only
      // when the key is permanently invalidated (e.g. fingerprints changed).
      if (biometricEnabled) {
        const stillValid = await biometricAuthService.authenticate('Confirma tu biometría', true, true);
        if (stillValid) return;
        if (!biometricAuthService.isPermanentInvalidation()) {
          setBiometricError('No pudimos confirmar tu biometría. Inténtalo nuevamente.');
          return;
        }
        await biometricAuthService.disable();
      }
      const enabled = await biometricAuthService.enable();
      setBiometricEnabled(enabled);
      if (!enabled) {
        setBiometricError('No pudimos activar la biometría. Inténtalo nuevamente.');
      }
    } catch (error) {
      setBiometricError('Ocurrió un problema al actualizar la biometría.');
    } finally {
      setBiometricActionLoading(false);
      setBiometricLoading(false);
    }
  }, [biometricAvailable, biometricEnabled, biometricActionLoading, biometricLoading]);

  // Force refresh when screen comes into focus to ensure latest state
  useFocusEffect(
    React.useCallback(() => {
      refreshAccounts();

      // Re-check biometric availability when screen comes into focus
      setBiometricLoading(true);
      checkBiometricSupport();

      // 3. Removed local check to strictly enforce backend status
      // const backupProvider = (userProfile as any)?.backupProvider?.toLowerCase();
      // const hasAnyBackup = backupProvider === 'google_drive' || backupProvider === 'icloud';
      // if (!driveBackupManuallyEnabled.current && !hasAnyBackup) {
      //   authService.checkDriveBackupEnabled().then(enabled => {
      //     if (!driveBackupManuallyEnabled.current) {
      //       setDriveBackupEnabled(enabled);
      //     }
      //   });
      // }

      return undefined;
    }, [refreshAccounts, checkBiometricSupport])
  );

  const handleTelegramPress = async () => {
    const telegramUrl = 'tg://resolve?domain=confio4world';
    const webUrl = 'https://t.me/confio4world';
    try {
      const canOpen = await Linking.canOpenURL(telegramUrl);
      await Linking.openURL(canOpen ? telegramUrl : webUrl);
    } catch {
      try {
        await Linking.openURL(webUrl);
      } catch {}
    }
  };

  const handleLegalDocumentPress = (docType: 'terms' | 'privacy' | 'deletion') => {
    navigation.navigate('LegalDocument', { docType });
  };

  // Get display information based on active account
  const getDisplayInfo = () => profileDisplayInfo({
    activeAccount, userProfile, username, accountsLoading, isUserProfileLoading,
  });

  const displayInfo = getDisplayInfo();
  const authReady = useAuthReady();
  const personalAccount = activeAccount?.type.toLowerCase() === 'personal';
  // Own query: on a server without profile pictures it errors and the
  // initial stays.
  const isBusinessAccount = activeAccount?.type?.toLowerCase() === 'business';
  const { data: pictureData } = useQuery(GET_MY_PROFILE_PICTURE, {
    skip: isBusinessAccount,
    fetchPolicy: 'cache-and-network',
  });
  const profilePictureUrl: string | null = isBusinessAccount ? null : pictureData?.myProfilePicture?.url || null;

  return (
    <>
      <ScrollView ref={scrollRef} onScroll={onGuideScroll} scrollEventThrottle={32} style={styles.container} contentContainerStyle={[styles.scrollContent, { paddingBottom: floatingInset }]}>
        {/* Header Section — brand field: same vertical gradient + coin ring
            family as Home; top edge is exactly colors.heroField so it meets the
            flat nav header without a seam. Padding lives on headerInner (Yoga
            insets absolute children by the parent's padding). */}
        <View
          style={styles.header}
          onLayout={(e) => {
            const { width, height } = e.nativeEvent.layout;
            setFieldSize((prev) =>
              prev.width === width && prev.height === height ? prev : { width, height }
            );
          }}
        >
          <Svg
            key={`profileField-${fieldSize.width}x${fieldSize.height}`}
            width={fieldSize.width || '100%'}
            height={fieldSize.height || '100%'}
            style={StyleSheet.absoluteFill}
          >
            <Defs>
              <SvgLinearGradient id="profileField" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={colors.heroField} />
                <Stop offset="1" stopColor={colors.heroFieldDark} />
              </SvgLinearGradient>
            </Defs>
            <Rect width="100%" height="100%" fill="url(#profileField)" />
            <Circle cx="104%" cy="26%" r="90" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
          </Svg>
          <View style={styles.headerInner}>
          <View style={styles.profileInfo}>
            <TouchableOpacity
              style={[
                styles.avatarContainer,
                userProfile?.statusTier === 'embajador' && styles.avatarEmbajador,
              ]}
              onPress={() => {
                const isBusiness = activeAccount?.type.toLowerCase() === 'business';
                if (isBusiness) {
                  navigation.navigate('EditBusiness');
                } else {
                  navigation.navigate('EditProfile');
                }
              }}
            >
              {profilePictureUrl ? (
                <Image source={{ uri: profilePictureUrl }} style={styles.avatarImage} />
              ) : (
                <Text style={styles.avatarText}>
                  {activeAccount?.avatar || (userProfile?.firstName?.charAt(0) || userProfile?.username?.charAt(0) || 'U')}
                </Text>
              )}
              <View style={styles.editIconContainer}>
                <Icon name="edit-2" size={12} color={colors.white} />
              </View>
            </TouchableOpacity>
            <View style={styles.profileNameRow}>
              {(() => {
                const name = displayInfo.name;
                const isPersonal = activeAccount?.type.toLowerCase() !== 'business';
                const verified = isPersonal && userProfile?.isReferralVerified;
                if (!verified) {
                  return <Text style={styles.name}>{name}</Text>;
                }
                const words = name.trim().split(' ').filter(Boolean);
                return words.map((word, i) => {
                  const isLast = i === words.length - 1;
                  if (!isLast) {
                    return <Text key={i} style={styles.name}>{word}{' '}</Text>;
                  }
                  return (
                    <View key={i} style={styles.profileLastWordBadgeGroup}>
                      <Text style={styles.name}>{word}</Text>
                      <View style={styles.profileInlineVerifiedBadge}>
                        <Icon name="check" size={12} color={colors.white} />
                      </View>
                    </View>
                  );
                });
              })()}
            </View>
            {activeAccount?.type.toLowerCase() !== 'business' && userProfile?.statusTier && userProfile.statusTier !== 'member' && (
              <StatusTierBadge tier={userProfile.statusTier} style={{ marginTop: 2, marginBottom: 4 }} />
            )}
            {displayInfo.showAccountType && (
              <Text style={styles.accountType}>{displayInfo.accountType}</Text>
            )}
            {displayInfo.subtitle && (
              <Text style={styles.subtitle}>{displayInfo.subtitle}</Text>
            )}
          </View>
          </View>
        </View>

        {/* Invitar y ganar has its own screen (and its own row in the menu):
            here, one line that opens it. */}
        {activeAccount?.type.toLowerCase() !== 'business' && (
          <TouchableOpacity
            ref={inviteAnchor}
            style={styles.inviteDoor}
            onPress={() => {
              reportGuideTap('profile_invite');
              navigation.navigate('Invite');
            }}
            accessibilityRole="button"
            accessibilityLabel="Invitar y ganar"
          >
            <View style={styles.inviteDoorBadge}>
              <Icon name="gift" size={20} color={colors.white} />
            </View>
            <View style={styles.inviteDoorText}>
              <Text style={styles.inviteDoorTitle}>Invitar y ganar</Text>
              <Text style={styles.inviteDoorSub} numberOfLines={2}>
                Cuando tus invitados mueven su dinero, tú ganas en dólares.
              </Text>
            </View>
            <Icon name="chevron-right" size={20} color={colors.primaryDark} />
          </TouchableOpacity>
        )}

        {/* Account Management Card */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Icon name="user" size={20} color={colors.text.secondary} />
              <Text style={styles.cardTitle}>Cuenta</Text>
            </View>
          </View>
          <View style={styles.cardOptions}>
            {activeAccount?.type.toLowerCase() === 'business' && (
              <TouchableOpacity style={styles.cardOption} accessibilityRole="button" onPress={() => navigation.navigate('Employees')}>
                <Icon name="users" size={18} color={colors.text.secondary} />
                <Text style={styles.cardOptionText}>Empleados</Text>
                <Icon name="chevron-right" size={16} color={colors.text.light} />
              </TouchableOpacity>
            )}
            <TouchableOpacity
              ref={verificationAnchor}
              style={styles.cardOption}
              onPress={() => {
                reportGuideTap('profile_verification');
                navigation.navigate('Verification');
              }}
            >
              <Icon name="user-check" size={18} color={colors.text.secondary} />
              <Text style={styles.cardOptionText}>Verificación</Text>
              <Icon name="chevron-right" size={16} color={colors.text.light} />
            </TouchableOpacity>
            {activeAccount?.type.toLowerCase() === 'personal' && (
              <TouchableOpacity
                style={styles.cardOption}
                onPress={() => navigation.navigate('UpdateUsername')}
              >
                <Icon name="edit-3" size={18} color={colors.text.secondary} />
                <Text style={styles.cardOptionText}>Editar usuario Confío</Text>
                <Icon name="chevron-right" size={16} color={colors.text.light} />
              </TouchableOpacity>
            )}

            {/* Payment methods menu: allow VE users; iOS only in debug */}
            {activeAccount?.type.toLowerCase() === 'personal' && (
              <TouchableOpacity
                style={styles.cardOption}
                onPress={() => navigation.navigate('ConfioAddress')}
              >
                <Icon name="at-sign" size={18} color={colors.text.secondary} />
                <Text style={styles.cardOptionText}>Compartir mi usuario</Text>
                <Icon name="chevron-right" size={16} color={colors.text.light} />
              </TouchableOpacity>
            )}

            {/* Payment methods menu */}
            {activeAccount?.type.toLowerCase() === 'personal' &&
              canManageBankAccounts && (
                <TouchableOpacity
                  style={styles.cardOption}
                  onPress={() => navigation.navigate('RampAddress')}
                >
                  <Icon name="map-pin" size={18} color={colors.text.secondary} />
                  <Text style={styles.cardOptionText}>Dirección y teléfono</Text>
                  <Icon name="chevron-right" size={16} color={colors.text.light} />
                </TouchableOpacity>
              )}

            {activeAccount?.type.toLowerCase() === 'personal' &&
              canManageBankAccounts && (
                <TouchableOpacity
                  style={styles.cardOption}
                  onPress={() => navigation.navigate('Agenda')}
                >
                  <Icon name="book-open" size={18} color={colors.text.secondary} />
                  <Text style={styles.cardOptionText}>Agenda</Text>
                  <Icon name="chevron-right" size={16} color={colors.text.light} />
                </TouchableOpacity>
              )}

            {/* Always present for personal accounts, but last in the cluster:
                an unlinked member cannot discover institution linking otherwise,
                and it sits below Verificacion because KYC is a prerequisite for
                applying to an institution. Home stays conditional on a real bill. */}
            {authReady && personalAccount && (
              <TouchableOpacity
                style={styles.cardOption}
                onPress={() => navigation.navigate('Memberships')}
                accessibilityRole="button"
              >
                <Icon name="award" size={18} color={colors.text.secondary} />
                <Text style={styles.cardOptionText}>Mis instituciones</Text>
                <Icon name="chevron-right" size={16} color={colors.text.light} />
              </TouchableOpacity>
            )}

            {/* Notification settings entry is currently hidden.
          <TouchableOpacity 
            style={styles.cardOption}
            onPress={() => navigation.navigate('NotificationSettings')}
          >
            <Icon name="bell" size={18} color={colors.text.secondary} />
            <Text style={styles.cardOptionText}>Notificaciones</Text>
            <Icon name="chevron-right" size={16} color={colors.text.light} />
          </TouchableOpacity>
          */}
          </View>
        </View>

        {/* Security Card */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Icon name="shield" size={20} color={colors.text.secondary} />
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
              <Icon name="smartphone" size={18} color={biometricAvailable ? colors.primaryDark : colors.text.light} />
              <View style={styles.biometricTextContainer}>
                <Text style={styles.biometricTitle}>Biometría / PIN</Text>
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
                <Icon name="chevron-right" size={16} color={colors.text.light} />
              )}
            </TouchableOpacity>

            {/* Google Drive Backup Option */}
            <TouchableOpacity
              style={styles.cardOption}
              onPress={handleBackupPress}
            >
              <Icon name="cloud" size={18} color={driveBackupEnabled ? colors.primaryDark : colors.text.secondary} />
              <View style={styles.biometricTextContainer}>
                <Text style={styles.biometricTitle}>Respaldo en la Nube</Text>
                {driveBackupEnabled ? (
                  <Text style={styles.biometricStatusActive}>Activa</Text>
                ) : (
                  <Text style={styles.biometricStatusText}>Toca para activar</Text>
                )}
              </View>
              <Icon name="chevron-right" size={16} color={colors.text.light} />
            </TouchableOpacity>

            {/* Emergency exit explainer. While Confío beats it only explains
                the safeguard and how to prepare; the exit itself opens on the
                on-chain heartbeat (docs/plans/salida-de-emergencia-design.md
                § Phase 3). Recovery surfaces (lock, loading, suspension) show
                it only when open. */}
            <TouchableOpacity
              style={styles.cardOption}
              onPress={() => navigation.navigate('EmergencyExit' as never)}
            >
              <Icon name="life-buoy" size={18} color={colors.primaryDark} />
              <View style={styles.biometricTextContainer}>
                <Text style={styles.biometricTitle}>Salida de emergencia</Text>
                <Text style={styles.biometricStatusText}>Tu respaldo si Confío deja de operar.</Text>
              </View>
              <Icon name="chevron-right" size={16} color={colors.text.light} />
            </TouchableOpacity>
          </View>
        </View>

        {/* Community & Support */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Icon name="message-circle" size={20} color={colors.text.secondary} />
              <Text style={styles.cardTitle}>Comunidad y soporte</Text>
            </View>
          </View>
          <View style={styles.cardOptions}>
            {userProfile?.id ? (
              <TouchableOpacity
                style={styles.cardOption}
                onPress={() => navigation.navigate('CommunityMemberProfile', { userId: String(userProfile.id) })}
                accessibilityRole="button"
                accessibilityLabel="Mi perfil en Comunidad"
              >
                <Icon name="user" size={18} color={colors.text.secondary} />
                <View style={styles.biometricTextContainer}>
                  <Text style={styles.biometricTitle}>Mi perfil en Comunidad</Text>
                  <Text style={styles.biometricStatusText}>Cómo te ven los demás y tu perfil de inversor</Text>
                </View>
                <Icon name="chevron-right" size={16} color={colors.text.light} />
              </TouchableOpacity>
            ) : null}
            <TouchableOpacity
              style={styles.cardOption}
              onPress={handleTelegramPress}
              accessibilityRole="link"
              accessibilityLabel="Abrir el grupo de Telegram de Confío"
            >
              <Icon name="send" size={18} color={colors.text.secondary} />
              <View style={styles.biometricTextContainer}>
                <Text style={styles.biometricTitle}>Grupo de Telegram</Text>
                <Text style={styles.biometricStatusText}>Comunidad oficial · t.me/confio4world</Text>
              </View>
              <Icon name="chevron-right" size={16} color={colors.text.light} />
            </TouchableOpacity>
          </View>
        </View>

        {/* The founder has a screen of his own, under "Invitar y ganar" in the
            menu. Where there is no menu (the five-tab app), one line opens it. */}
        {!CONVERSATION_HOME_ENABLED ? (
          <TouchableOpacity
            style={styles.inviteDoor}
            onPress={() => navigation.navigate('Founder')}
            accessibilityRole="button"
            accessibilityLabel="El fundador"
          >
            <View style={styles.inviteDoorBadge}>
              <Icon name="star" size={20} color={colors.white} />
            </View>
            <View style={styles.inviteDoorText}>
              <Text style={styles.inviteDoorTitle}>El fundador</Text>
              <Text style={styles.inviteDoorSub} numberOfLines={2}>Julian Moon y dónde seguirlo.</Text>
            </View>
            <Icon name="chevron-right" size={20} color={colors.primaryDark} />
          </TouchableOpacity>
        ) : null}

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
        <Button
          title="Cerrar Sesión"
          variant="ghost"
          onPress={signOut}
          accessibilityLabel="Cerrar sesión"
          style={{ marginTop: 16, marginBottom: 8 }}
          textStyle={{ color: colors.danger, fontWeight: '500' }}
        />

        {/* For support: the same version/build the app reports to the server. */}
        <Text style={styles.appVersion} selectable accessibilityLabel={`Versión de Confío ${DeviceInfo.getVersion()}`}>
          Confío {DeviceInfo.getVersion()} ({DeviceInfo.getBuildNumber()})
        </Text>
      </ScrollView>
      <ReferralInputModal
        visible={showReferralModal}
        onClose={() => setShowReferralModal(false)}
        onSuccess={() => setShowReferralModal(false)}
      />
      {/* Google Drive Backup Modal */}
      <BackupConsentModal
        visible={showBackupModal}
        onContinue={() => {
          setShowBackupModal(false);
          runDriveBackup();
        }}
        onCancel={() => setShowBackupModal(false)}
      />
      <DriveStorageFullModal
        visible={showDriveStorageFull}
        onRetry={() => {
          setShowDriveStorageFull(false);
          runDriveBackup();
        }}
        onClose={() => setShowDriveStorageFull(false)}
      />
    </>
  );
};

const HERO_INK = CONVERSATION_HOME_ENABLED ? colors.onHeroField : colors.white;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.white,
  },
  appVersion: {
    textAlign: 'center',
    fontSize: 12,
    color: colors.text.light,
    marginBottom: 32,
  },
  scrollContent: {
    flexGrow: 1,
  },
  header: {
    backgroundColor: colors.heroField,
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
    overflow: 'hidden',
  },
  headerInner: {
    paddingBottom: 32,
    paddingHorizontal: 20,
  },
  profileInfo: {
    alignItems: 'center',
  },
  avatarContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.white,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
    position: 'relative',
  },
  avatarEmbajador: {
    borderWidth: 3,
    borderColor: colors.secondary,
  },
  avatarImage: {
    width: 80,
    height: 80,
    borderRadius: 40,
  },
  avatarText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: colors.primary,
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
    borderColor: colors.white,
  },
  // The conversation home draws the header above in the field's dark ink:
  // the hero text is the same ink.
  name: {
    fontSize: 20,
    fontWeight: 'bold',
    color: HERO_INK,
  },
  profileNameRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    marginBottom: 4,
  },
  profileLastWordBadgeGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  profileInlineVerifiedBadge: {
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
  },
  accountType: {
    fontSize: 14,
    fontWeight: CONVERSATION_HOME_ENABLED ? '600' : 'normal',
    color: CONVERSATION_HOME_ENABLED ? colors.onHeroField : 'rgba(255, 255, 255, 0.9)',
    marginBottom: 2,
  },
  subtitle: {
    fontSize: 14,
    fontWeight: CONVERSATION_HOME_ENABLED ? '600' : 'normal',
    color: CONVERSATION_HOME_ENABLED ? colors.onHeroField : 'rgba(255, 255, 255, 0.8)',
  },
  card: {
    backgroundColor: colors.white,
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
    color: colors.text.primary,
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
    color: colors.text.primary,
    marginLeft: 12,
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
    color: colors.text.primary,
  },
  biometricStatusText: {
    fontSize: 13,
    color: colors.text.secondary,
    marginTop: 4,
  },
  biometricStatusActive: {
    fontSize: 13,
    color: colors.primaryDark,
    marginTop: 4,
    fontWeight: '500',
  },
  biometricStatusUnavailable: {
    fontSize: 13,
    color: colors.danger,
    marginTop: 4,
  },
  inviteDoor: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: colors.white,
    borderRadius: 20,
    marginHorizontal: 16,
    marginBottom: 16,
    paddingVertical: 14,
    paddingHorizontal: 16,
    ...Platform.select({
      ios: { shadowColor: '#000', shadowOffset: { width: 0, height: 8 }, shadowOpacity: 0.08, shadowRadius: 12 },
      android: { elevation: 3 },
    }),
  },
  inviteDoorBadge: {
    width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primaryDark,
  },
  inviteDoorText: { flex: 1 },
  inviteDoorTitle: { fontSize: 16, fontWeight: '700', color: colors.dark },
  inviteDoorSub: { fontSize: 13, lineHeight: 18, color: colors.textSecondary, marginTop: 2 },
  separator: {
    height: 1,
    backgroundColor: colors.border,
    marginHorizontal: 16,
    marginVertical: 8,
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
    color: colors.text.secondary,
  },
  legalSeparator: {
    color: colors.border,
    fontSize: 13,
  },
}); 
