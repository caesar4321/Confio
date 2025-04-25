import React, { useEffect, useRef } from 'react';
import { View, StyleSheet, TouchableOpacity, Image, Animated, Dimensions, Easing } from 'react-native';
import { GoogleSignin } from '@react-native-google-signin/google-signin';
import { appleAuth } from '@invertase/react-native-apple-authentication';
import { AuthService } from '../../services/authService';
import GoogleLogo from '../../assets/svg/GoogleLogo.svg';
import AppleLogo from '../../assets/svg/AppleLogo.svg';
import { Gradient } from '../common/Gradient';
import Svg, { Defs, RadialGradient, Stop, Circle } from 'react-native-svg';

const { width: screenWidth } = Dimensions.get('window');

export const AuthScreen = () => {
  const authService = AuthService.getInstance();
  const logoScale = useRef(new Animated.Value(0.7)).current;
  const logoOpacity = useRef(new Animated.Value(0)).current;
  const glowOpacity = useRef(new Animated.Value(0.5)).current;

  useEffect(() => {
    // Initialize AuthService
    authService.initialize().catch(error => {
      console.error('Failed to initialize AuthService:', error);
    });

    // Logo entrance animation
    Animated.parallel([
      Animated.timing(logoScale, {
        toValue: 1,
        duration: 1000,
        easing: Easing.out(Easing.back(1.2)),
        useNativeDriver: true,
      }),
      Animated.timing(logoOpacity, {
        toValue: 1,
        duration: 800,
        easing: Easing.out(Easing.exp),
        useNativeDriver: true,
      }),
    ]).start();

    // Looping glow animation
    Animated.loop(
      Animated.sequence([
        Animated.timing(glowOpacity, {
          toValue: 0.8,
          duration: 2000,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true,
        }),
        Animated.timing(glowOpacity, {
          toValue: 0.5,
          duration: 2000,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true,
        }),
      ])
    ).start();
  }, []);

  const handleGoogleSignIn = async () => {
    try {
      console.log('Google Sign-In button pressed');
      const result = await authService.signInWithGoogle();
      console.log('Google Sign-In result:', result);
      // Handle successful sign-in
    } catch (error) {
      console.error('Google Sign-In failed:', error);
      // Handle error
    }
  };

  const handleAppleSignIn = async () => {
    try {
      const response = await authService.signInWithApple();
      console.log('Apple Sign-In Success:', response);
      // Handle successful sign-in (e.g., navigate to main app)
    } catch (error) {
      console.error('Apple Sign-In Error:', error);
    }
  };

  return (
    <Gradient
      fromColor="#5AC8A8"
      toColor="#72D9BC"
      style={styles.container}
    >
      <View style={styles.mainContent}>
        <View style={styles.logoWrapper}>
          <Animated.View 
            style={[
              styles.gradientWrapper,
              {
                opacity: glowOpacity
              }
            ]}
          >
            <Svg height="100%" width="100%" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
              <Defs>
                <RadialGradient
                  id="grad"
                  cx="50%"
                  cy="50%"
                  rx="100%"
                  ry="100%"
                  fx="50%"
                  fy="50%"
                  gradientUnits="userSpaceOnUse"
                >
                  <Stop offset="0%" stopColor="white" stopOpacity="1" />
                  <Stop offset="10%" stopColor="rgba(255, 255, 255, 0.9)" stopOpacity="0.9" />
                  <Stop offset="25%" stopColor="rgba(90, 200, 168, 0.7)" stopOpacity="0.7" />
                  <Stop offset="50%" stopColor="rgba(114, 217, 188, 0.4)" stopOpacity="0.4" />
                  <Stop offset="100%" stopColor="rgba(114, 217, 188, 0)" stopOpacity="0" />
                </RadialGradient>
              </Defs>
              <Circle cx="50" cy="50" r="50" fill="url(#grad)" />
            </Svg>
          </Animated.View>
          <Animated.View 
            style={[
              styles.confioLogoContainer,
              { 
                transform: [{ scale: logoScale }],
                opacity: logoOpacity
              }
            ]}
          >
            <Image
              source={require('../../assets/png/CONFIO.png')}
              style={styles.confioLogo}
              resizeMode="contain"
            />
          </Animated.View>
        </View>
        <View style={styles.buttonContainer}>
          <TouchableOpacity
            style={styles.signInButton}
            onPress={handleGoogleSignIn}
          >
            <View style={styles.buttonContent}>
              <GoogleLogo width={30} height={30} />
            </View>
          </TouchableOpacity>

          {appleAuth.isSupported && (
            <TouchableOpacity
              style={styles.signInButton}
              onPress={handleAppleSignIn}
            >
              <View style={styles.buttonContent}>
                <AppleLogo width={30} height={30} />
              </View>
            </TouchableOpacity>
          )}
        </View>
      </View>
    </Gradient>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  mainContent: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  logoWrapper: {
    position: 'relative',
    width: 200,
    height: 200,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 60,
  },
  gradientWrapper: {
    position: 'absolute',
    width: 1200,
    height: 1200,
    top: -500,
    left: -500,
    borderRadius: 600,
    overflow: 'hidden',
    zIndex: 0,
  },
  confioLogoContainer: {
    width: 200,
    height: 200,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 8,
    },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 8,
    zIndex: 1,
  },
  confioLogo: {
    width: '100%',
    height: '100%',
  },
  buttonContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 20,
  },
  signInButton: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: '#FFFFFF',
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 6,
    },
    shadowOpacity: 0.2,
    shadowRadius: 10,
    elevation: 8,
  },
  buttonContent: {
    width: 30,
    height: 30,
    justifyContent: 'center',
    alignItems: 'center',
  },
}); 