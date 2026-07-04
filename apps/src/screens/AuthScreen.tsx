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

import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
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
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />

      {/* Brand field: the app's own grammar (emerald field + white sheet) at
          full volume. One graphic motif — a giant coin ring cropped off-canvas —
          not confetti. All colors from theme.ts. */}
      <View style={styles.brandField}>
        <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
          <Defs>
            <SvgLinearGradient id="field" x1="0" y1="0" x2="1" y2="1">
              <Stop offset="0" stopColor={colors.primary} />
              <Stop offset="1" stopColor={colors.primaryDark} />
            </SvgLinearGradient>
          </Defs>
          <Rect width="100%" height="100%" fill="url(#field)" />
          {/* Coin ring: money made geometric. Cropped top-right. */}
          <Circle cx="92%" cy="6%" r="150" stroke={colors.white} strokeWidth="34" strokeOpacity="0.10" fill="none" />
          <Circle cx="-4%" cy="102%" r="110" stroke={colors.white} strokeWidth="26" strokeOpacity="0.07" fill="none" />
        </Svg>
        <Animated.View style={[styles.brandContent, { opacity: enterAnim }]}>
          <Image
            source={require('../assets/png/CONFIO.png')}
            style={styles.brandLogo}
          />
          <Text style={styles.wordmark} accessibilityRole="header">Confío</Text>
          <Text style={styles.brandTagline}>CONFIANZA PARA AMÉRICA LATINA</Text>
        </Animated.View>
      </View>

      {/* White sheet rising over the field */}
      <Animated.View
        style={[
          styles.sheet,
          {
            opacity: enterAnim,
            transform: [{
              translateY: enterAnim.interpolate({ inputRange: [0, 1], outputRange: [32, 0] }),
            }],
          },
        ]}
      >
        <Text style={styles.title}>Bienvenido</Text>
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
    backgroundColor: colors.primaryDark,
  },
  // Top: emerald brand field with one cropped coin-ring motif.
  brandField: {
    flex: 1,
    overflow: 'hidden',
  },
  brandContent: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
    paddingBottom: 12,
  },
  brandLogo: {
    width: 84,
    height: 84,
    resizeMode: 'contain',
    marginBottom: 12,
  },
  wordmark: {
    fontSize: 52,
    fontWeight: '800',
    color: colors.white,
    letterSpacing: -1,
    textAlign: 'center',
  },
  brandTagline: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2.5,
    color: colors.primaryLight,
    textAlign: 'center',
    marginTop: 10,
  },
  // White sheet rising over the field, carrying the actions.
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    marginTop: -28,
    paddingHorizontal: 24,
    paddingTop: 32,
    paddingBottom: 40,
    alignItems: 'center',
    shadowColor: colors.dark,
    shadowOffset: { width: 0, height: -8 },
    shadowOpacity: 0.08,
    shadowRadius: 20,
    elevation: 12,
  },
  title: {
    fontSize: 26,
    fontWeight: 'bold',
    color: colors.dark,
    textAlign: 'center',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 15,
    color: colors.text.secondary,
    textAlign: 'center',
    marginBottom: 28,
    marginTop: 6,
    maxWidth: 320,
    lineHeight: 22,
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
