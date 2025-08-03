import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Image, Animated, Dimensions, Easing } from 'react-native';
import { GoogleSignin } from '@react-native-google-signin/google-signin';
import { appleAuth } from '@invertase/react-native-apple-authentication';
import { EnhancedAuthService } from '../services/enhancedAuthService';
import GoogleLogo from '../assets/svg/GoogleLogo.svg';
import AppleLogo from '../assets/svg/AppleLogo.svg';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useAuth } from '../contexts/AuthContext';
import Svg, { Defs, LinearGradient as SvgLinearGradient, Stop, Text as SvgText, RadialGradient, Ellipse } from 'react-native-svg';

const { width: screenWidth, height: screenHeight } = Dimensions.get('window');

const colors = {
  confioGreen: '#72D9BC',
  white: '#FFFFFF',
  accentPurple: '#8B5CF6',
  darkGray: '#1F2937',
  lightGray: '#F3F4F6',
};

type RootStackParamList = {
  Auth: undefined;
  Home: undefined;
};

type NavigationProp = NativeStackNavigationProp<RootStackParamList, 'Auth'>;

export const AuthScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const enhancedAuthService = EnhancedAuthService.getInstance();
  const { handleSuccessfulLogin } = useAuth();

  useEffect(() => {
    enhancedAuthService.initialize().catch(error => {
      console.error('Failed to initialize EnhancedAuthService:', error);
    });
  }, []);

  const handleGoogleSignIn = async () => {
    try {
      console.log('AuthScreen - Starting enhanced Google Sign-In...');
      const result = await enhancedAuthService.signInWithGoogle();
      
      // Log security information
      console.log('AuthScreen - Authentication completed with security data:', {
        fingerprintHash: result.securityData.fingerprintHash,
        isNewDevice: result.securityData.securityFlags.isNewDevice,
        isTrustedDevice: result.securityData.securityFlags.isTrustedDevice,
        requiresDeviceTrust: result.securityData.securityFlags.requiresDeviceTrust
      });
      
      // Handle device trust if required
      if (result.securityData.securityFlags.requiresDeviceTrust) {
        console.log('AuthScreen - New device detected, may require additional verification');
        // TODO: Show device trust verification UI
      }
      
      await handleSuccessfulLogin(result.zkLoginData.isPhoneVerified);
    } catch (error) {
      console.error('Google Sign-In failed:', error);
    }
  };

  const handleAppleSignIn = async () => {
    try {
      console.log('AuthScreen - Starting enhanced Apple Sign-In...');
      const result = await enhancedAuthService.signInWithApple();
      
      // Log security information
      console.log('AuthScreen - Authentication completed with security data:', {
        fingerprintHash: result.securityData.fingerprintHash,
        isNewDevice: result.securityData.securityFlags.isNewDevice,
        isTrustedDevice: result.securityData.securityFlags.isTrustedDevice,
        requiresDeviceTrust: result.securityData.securityFlags.requiresDeviceTrust
      });
      
      // Handle device trust if required
      if (result.securityData.securityFlags.requiresDeviceTrust) {
        console.log('AuthScreen - New device detected, may require additional verification');
        // TODO: Show device trust verification UI
      }
      
      await handleSuccessfulLogin(result.zkLoginData.isPhoneVerified);
    } catch (error) {
      console.error('Apple Sign-In Error:', error);
    }
  };

  return (
    <View style={styles.container}>
      {/* Decorative Background Circles and Lines */}
      <View style={styles.decorativeBg} pointerEvents="none">
        <View style={styles.topLeftCircle} />
        <View style={styles.bottomRightCircle} />
        <View style={styles.dot1} />
        <View style={styles.dot2} />
        <View style={styles.dot3} />
        <View style={styles.line1} />
        <View style={styles.line2} />
      </View>
      <View style={styles.contentWrapper}>
        {/* Glowing Logo with Gradient */}
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
                <Stop offset="0%" stopColor="#72D9BC" stopOpacity="0.7" />
                <Stop offset="70%" stopColor="#72D9BC" stopOpacity="0.25" />
                <Stop offset="100%" stopColor="#72D9BC" stopOpacity="0" />
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

        {/* Gradient Title */}
        <View style={{ alignItems: 'center', marginBottom: 4, width: '100%' }}>
          <Svg height="44" width="100%" viewBox="0 0 320 44" style={{ alignSelf: 'center' }}>
            <Defs>
              <SvgLinearGradient id="grad" x1="0" y1="0" x2="1" y2="0">
                <Stop offset="0" stopColor="#72D9BC" />
                <Stop offset="1" stopColor="#8B5CF6" />
              </SvgLinearGradient>
            </Defs>
            <SvgText
              x="160"
              y="32"
              fontSize="28"
              fontWeight="bold"
              fill="url(#grad)"
              textAnchor="middle"
            >
              Bienvenido a Confío
            </SvgText>
          </Svg>
        </View>

        <Text style={styles.subtitle}>La manera más fácil y segura de enviar, pagar, y ahorrar en dólares digitales</Text>
        <View style={styles.buttonGroup}>
          <TouchableOpacity 
            style={styles.googleButton} 
            onPress={handleGoogleSignIn}
          >
            <GoogleLogo width={24} height={24} style={{ marginRight: 8 }} />
            <Text style={styles.googleButtonText}>Continuar con Google</Text>
          </TouchableOpacity>
          {appleAuth.isSupported && (
            <TouchableOpacity 
              style={styles.appleButton} 
              onPress={handleAppleSignIn}
            >
              <AppleLogo width={24} height={24} style={{ marginRight: 8 }} fill="#fff" />
              <Text style={styles.appleButtonText}>Continuar con Apple</Text>
            </TouchableOpacity>
          )}
        </View>
        <View style={styles.termsWrapper}>
          <Text style={styles.termsText}>Al continuar, aceptas</Text>
          <Text style={styles.termsLinks}>
            <Text style={styles.termsLink}>Términos de Servicio</Text>
            <Text style={{ color: '#6B7280', fontWeight: 'normal' }}> y </Text>
            <Text style={styles.termsLink}>Política de Privacidad</Text>
          </Text>
        </View>
      </View>
      
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.white,
    justifyContent: 'center',
    alignItems: 'center',
  },
  decorativeBg: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 0,
  },
  topLeftCircle: {
    position: 'absolute',
    top: -80,
    left: -80,
    width: 220,
    height: 220,
    borderRadius: 110,
    backgroundColor: colors.confioGreen,
    opacity: 0.10,
  },
  bottomRightCircle: {
    position: 'absolute',
    bottom: -120,
    right: -120,
    width: 320,
    height: 320,
    borderRadius: 160,
    backgroundColor: colors.accentPurple,
    opacity: 0.10,
  },
  dot1: {
    position: 'absolute',
    top: screenHeight * 0.25,
    right: 48,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.confioGreen,
  },
  dot2: {
    position: 'absolute',
    top: screenHeight * 0.33,
    left: 40,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.accentPurple,
    opacity: 0.2,
  },
  dot3: {
    position: 'absolute',
    bottom: screenHeight * 0.25,
    left: screenWidth * 0.25,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.confioGreen,
    opacity: 0.3,
  },
  line1: {
    position: 'absolute',
    top: screenHeight * 0.33,
    right: screenWidth * 0.33,
    width: 64,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.darkGray,
    opacity: 0.10,
    transform: [{ rotate: '45deg' }],
  },
  line2: {
    position: 'absolute',
    bottom: screenHeight * 0.33,
    left: screenWidth * 0.33,
    width: 80,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.confioGreen,
    opacity: 0.10,
    transform: [{ rotate: '-45deg' }],
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
    backgroundColor: colors.confioGreen,
    alignItems: 'center',
    justifyContent: 'center',
    // Soft glow/shadow
    shadowColor: colors.confioGreen,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 16,
    elevation: 8, // for Android
  },
  logoText: {
    color: colors.white,
    fontSize: 48,
    fontWeight: 'bold',
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 4,
  },
  titleGradient: {
    fontWeight: 'bold',
  },
  subtitle: {
    fontSize: 16,
    color: colors.darkGray,
    textAlign: 'center',
    marginBottom: 32,
    marginTop: 4,
    maxWidth: 320,
  },
  buttonGroup: {
    width: '100%',
    marginBottom: 24,
  },
  googleButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.white,
    borderColor: '#E5E7EB',
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 14,
    paddingHorizontal: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
  },
  googleButtonText: {
    color: colors.darkGray,
    fontWeight: '500',
    fontSize: 16,
    marginLeft: 8,
  },
  appleButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#000',
    borderRadius: 16,
    paddingVertical: 14,
    paddingHorizontal: 16,
    marginBottom: 0,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 8,
  },
  appleButtonText: {
    color: colors.white,
    fontWeight: '500',
    fontSize: 16,
    marginLeft: 8,
  },
  termsWrapper: {
    marginTop: 32,
    alignItems: 'center',
  },
  termsText: {
    color: '#6B7280',
    fontSize: 14,
    marginBottom: 4,
  },
  termsLinks: {
    fontSize: 14,
    textAlign: 'center',
  },
  termsLink: {
    color: colors.confioGreen,
    fontWeight: '500',
  },
  disabledButton: {
    opacity: 0.6,
  },
}); 