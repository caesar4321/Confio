import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Image, Animated, Easing, ActivityIndicator, Alert, Platform, ScrollView, StatusBar } from 'react-native';
import LoadingOverlay from '../components/LoadingOverlay';
import { BackupConsentModal } from '../components/BackupConsentModal';
import { GoogleSignin } from '@react-native-google-signin/google-signin';
import { appleAuth } from '@invertase/react-native-apple-authentication';
import authService, { AccountDeactivatedError } from '../services/authService';
import GoogleLogo from '../assets/svg/GoogleLogo.svg';
import AppleLogo from '../assets/svg/AppleLogo.svg';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { AuthStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';

import Svg, { Defs, Stop, RadialGradient, LinearGradient as SvgLinearGradient, Ellipse, Rect } from 'react-native-svg';
import { colors } from '../config/theme';


type NavigationProp = NativeStackNavigationProp<AuthStackParamList, 'Login'>;

export const AuthScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { handleSuccessfulLogin } = useAuth();
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  const [showBackupModal, setShowBackupModal] = useState(false);
  const rotateAnim = useRef(new Animated.Value(0)).current;
  // Single restrained entrance: content fades up once on mount.
  const enterAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(enterAnim, {
      toValue: 1,
      duration: 600,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [enterAnim]);

  // Initialize auth service when component mounts
  useEffect(() => {
    const initializeAuthService = async () => {
      try {
        await authService.initialize();
      } catch (error) {
      }
    };

    initializeAuthService();
  }, []);

  // Rotation animation for loading spinner
  useEffect(() => {
    let animation: Animated.CompositeAnimation | null = null;
    if (isLoading) {
      animation = Animated.loop(
        Animated.timing(rotateAnim, {
          toValue: 1,
          duration: 1500,
          easing: Easing.linear,
          useNativeDriver: true,
        })
      );
      animation.start();
    }
    return () => {
      animation?.stop();
      rotateAnim.stopAnimation();
    };
  }, [isLoading]);

  // Google Sign-In Flow
  // 1. Triggered by button
  const handleGoogleSignInPress = () => {
    // Show Backup Modal for ALL platforms (iOS & Android)
    // allowing users to opt-in to Drive Roaming across ecosystems.
    setShowBackupModal(true);
  };

  // 2. Confirmed or Cancelled from Modal (or called directly on iOS)
  const proceedWithGoogleSignIn = async (enableDrive: boolean) => {
    setShowBackupModal(false);
    try {

      // Don't show loading during Google modal
      const result = await authService.signInWithGoogle((message) => {
        // Only show loading AFTER Google sign-in completes
        if (!isLoading && message) {
          setIsLoading(true);
        }
        setLoadingMessage(message);
      }, enableDrive); // Pass preference to service

      // Ensure loading is shown if not already
      if (!isLoading) {
        setIsLoading(true);
        setLoadingMessage('¡Casi listo! Finalizando configuración...');
      }


      await handleSuccessfulLogin(
        result.walletData?.isPhoneVerified || false,
        result.requiresBackupCompletion || false
      );
    } catch (error) {
      if (error instanceof AccountDeactivatedError) {
        Alert.alert('Cuenta desactivada', error.message);
      } else {
        const fallbackMessage = (error as Error)?.message || 'No pudimos iniciar sesión. Intenta nuevamente en unos minutos.';
        Alert.alert('Error al iniciar sesión', fallbackMessage);
      }
      setIsLoading(false);
    }
  };

  const handleAppleSignIn = async () => {
    try {

      // Don't show loading during Apple modal
      const result = await authService.signInWithApple((message) => {
        // Only show loading AFTER Apple sign-in completes
        if (!isLoading && message) {
          setIsLoading(true);
        }
        setLoadingMessage(message);
      });

      // Ensure loading is shown if not already
      if (!isLoading) {
        setIsLoading(true);
        setLoadingMessage('¡Casi listo! Finalizando configuración...');
      }


      await handleSuccessfulLogin(result.walletData?.isPhoneVerified || false);
    } catch (error) {
      if (error instanceof AccountDeactivatedError) {
        Alert.alert('Cuenta desactivada', error.message);
      } else {
        const fallbackMessage = (error as Error)?.message || 'No pudimos iniciar sesión. Intenta nuevamente en unos minutos.';
        Alert.alert('Error al iniciar sesión', fallbackMessage);
      }
      setIsLoading(false);
    }
  };

  const handleLegalDocumentPress = (docType: 'terms' | 'privacy') => {
    try {
      navigation.navigate('LegalDocument', { docType });
    } catch (e) {
    }
  };

  const spin = rotateAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg']
  });

  return (
    <View style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor={colors.primarySoft} />
      {/* Fresh mint backdrop, all from theme.ts: primarySoft (emerald-50) fading
          into white, plus one soft brand halo anchored to the logo. */}
      <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
        <Defs>
          <SvgLinearGradient id="fresh" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={colors.primarySoft} />
            <Stop offset="0.6" stopColor={colors.background} />
            <Stop offset="1" stopColor={colors.background} />
          </SvgLinearGradient>
          <RadialGradient id="halo" cx="50%" cy="30%" r="55%">
            <Stop offset="0%" stopColor={colors.primary} stopOpacity="0.12" />
            <Stop offset="60%" stopColor={colors.primary} stopOpacity="0.04" />
            <Stop offset="100%" stopColor={colors.primary} stopOpacity="0" />
          </RadialGradient>
        </Defs>
        <Rect width="100%" height="100%" fill="url(#fresh)" />
        <Rect width="100%" height="100%" fill="url(#halo)" />
      </Svg>
      <Animated.View
        style={[
          styles.contentWrapper,
          {
            opacity: enterAnim,
            transform: [{
              translateY: enterAnim.interpolate({ inputRange: [0, 1], outputRange: [16, 0] }),
            }],
          },
        ]}
      >
        {/* Glowing Logo */}
        <View style={[styles.logoWrapper, { width: 160, height: 160, alignItems: 'center', justifyContent: 'center', position: 'relative' }]}>
          <Svg
            height="160"
            width="160"
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              zIndex: 0,
            }}
          >
            <Defs>
              <RadialGradient
                id="glow"
                cx="80"
                cy="80"
                r="80"
                gradientUnits="userSpaceOnUse"
              >
                <Stop offset="0%" stopColor={colors.primary} stopOpacity="0.30" />
                <Stop offset="65%" stopColor={colors.primary} stopOpacity="0.10" />
                <Stop offset="100%" stopColor={colors.primary} stopOpacity="0" />
              </RadialGradient>
            </Defs>
            <Ellipse
              cx="80"
              cy="80"
              rx="80"
              ry="80"
              fill="url(#glow)"
            />
          </Svg>
          <Image
            source={require('../assets/png/CONFIO.png')}
            style={{ width: 96, height: 96, resizeMode: 'contain', zIndex: 1 }}
          />
        </View>

        <Text style={styles.eyebrow}>DÓLARES DIGITALES</Text>
        <Text style={styles.title} accessibilityRole="header">Bienvenido a Confío</Text>

        <Text style={styles.subtitle}>La manera más fácil y segura de enviar, pagar, y ahorrar en dólares digitales</Text>
        <View style={styles.buttonGroup}>
          <TouchableOpacity
            style={styles.googleButton}
            onPress={handleGoogleSignInPress}
            accessibilityRole="button"
            accessibilityLabel="Continuar con Google"
          >
            <GoogleLogo width={24} height={24} style={{ marginRight: 8 }} />
            <Text style={styles.googleButtonText}>Continuar con Google</Text>
          </TouchableOpacity>
          {appleAuth.isSupported && (
            <TouchableOpacity
              style={styles.appleButton}
              onPress={handleAppleSignIn}
              accessibilityRole="button"
              accessibilityLabel="Continuar con Apple"
            >
              <AppleLogo width={24} height={24} style={{ marginRight: 8 }} fill="#fff" />
              <Text style={styles.appleButtonText}>Continuar con Apple</Text>
            </TouchableOpacity>
          )}
        </View>
        <View style={styles.termsWrapper}>
          <Text style={styles.termsText}>Al continuar, aceptas</Text>
          <Text style={styles.termsLinks}>
            <Text style={styles.termsLink} onPress={() => handleLegalDocumentPress('terms')}>Términos de Servicio</Text>
            <Text style={{ color: colors.text.secondary, fontWeight: 'normal' }}> y </Text>
            <Text style={styles.termsLink} onPress={() => handleLegalDocumentPress('privacy')}>Política de Privacidad</Text>
          </Text>
        </View>
      </Animated.View>

      <LoadingOverlay visible={isLoading} message={loadingMessage} />

      <BackupConsentModal
        visible={showBackupModal}
        onContinue={() => proceedWithGoogleSignIn(true)} // Drive Enabled
        onCancel={() => proceedWithGoogleSignIn(false)} // Drive Disabled (Local Only)
      />


    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.primarySoft,
    justifyContent: 'center',
    alignItems: 'center',
  },
  contentWrapper: {
    zIndex: 1,
    alignItems: 'center',
    paddingHorizontal: 24,
    width: '100%',
  },
  logoWrapper: {
    marginBottom: 12,
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  logoGlowGradient: {
    position: 'absolute',
    width: 112,
    height: 112,
    borderRadius: 56,
    opacity: 0.25,
    alignSelf: 'center',
    top: -8,
    left: -8,
    zIndex: 0,
  },
  logoCircle: {
    width: 96,
    height: 96,
    borderRadius: 48,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    // Soft glow/shadow
    shadowColor: colors.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 16,
    elevation: 8, // for Android
  },
  logoText: {
    color: colors.background,
    fontSize: 48,
    fontWeight: 'bold',
  },
  eyebrow: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 3,
    color: colors.primaryDark,
    textAlign: 'center',
    marginBottom: 8,
  },
  title: {
    fontSize: 30,
    fontWeight: 'bold',
    color: colors.dark,
    textAlign: 'center',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 16,
    color: colors.text.secondary,
    textAlign: 'center',
    marginBottom: 36,
    marginTop: 6,
    maxWidth: 320,
    lineHeight: 24,
  },
  buttonGroup: {
    width: '100%',
    marginBottom: 24,
  },
  googleButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.primaryLight,
    borderRadius: 16,
    paddingVertical: 15,
    paddingHorizontal: 16,
    marginBottom: 12,
    shadowColor: colors.primaryDark,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 2,
  },
  googleButtonText: {
    color: colors.dark,
    fontWeight: '500',
    fontSize: 16,
    marginLeft: 8,
  },
  // Apple HIG: standard black style on light surfaces.
  appleButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#000000',
    borderRadius: 16,
    paddingVertical: 15,
    paddingHorizontal: 16,
    marginBottom: 0,
    shadowColor: colors.dark,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.12,
    shadowRadius: 12,
    elevation: 2,
  },
  appleButtonText: {
    color: '#FFFFFF',
    fontWeight: '500',
    fontSize: 16,
    marginLeft: 8,
  },
  termsWrapper: {
    marginTop: 32,
    alignItems: 'center',
  },
  termsText: {
    color: colors.text.secondary,
    fontSize: 14,
    marginBottom: 4,
  },
  termsLinks: {
    fontSize: 14,
    textAlign: 'center',
  },
  termsLink: {
    color: colors.primary,
    fontWeight: '500',
  },
  disabledButton: {
    opacity: 0.6,
  },
  // Loading Overlay Styles
  loadingOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingCard: {
    backgroundColor: colors.background,
    borderRadius: 20,
    padding: 32,
    alignItems: 'center',
    minWidth: 280,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 10,
    },
    shadowOpacity: 0.25,
    shadowRadius: 20,
    elevation: 10,
  },
  loadingLogo: {
    width: 64,
    height: 64,
    resizeMode: 'contain',
    marginBottom: 20,
  },
  loadingText: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.dark,
    marginBottom: 16,
    textAlign: 'center',
  },
  dotsContainer: {
    flexDirection: 'row',
    gap: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
}); 
