import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  Image,
  ScrollView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RootStackParamList } from '../types/navigation';
import authServiceWeb3 from '../services/authServiceWeb3';
import Icon from 'react-native-vector-icons/MaterialCommunityIcons';

type AuthScreenNavigationProp = NativeStackNavigationProp<RootStackParamList, 'Auth'>;

export default function AuthScreenWeb3() {
  const navigation = useNavigation<AuthScreenNavigationProp>();
  const [isLoading, setIsLoading] = useState(false);
  const [authMode, setAuthMode] = useState<'web3' | 'legacy'>('web3');

  useEffect(() => {
    checkExistingAuth();
  }, []);

  const checkExistingAuth = async () => {
    try {
      if (authServiceWeb3.isSignedIn()) {
        navigation.replace('MainTabs');
      }
    } catch (error) {
      console.error('Error checking auth status:', error);
    }
  };

  const handleGoogleSignIn = async () => {
    if (isLoading) return;
    
    setIsLoading(true);
    try {
      const userInfo = await authServiceWeb3.signInWithGoogle();
      
      if (userInfo) {
        Alert.alert(
          'Welcome to Web3!',
          `Your Algorand address: ${userInfo.algorandAddress?.substring(0, 8)}...${userInfo.algorandAddress?.substring(50)}`,
          [
            {
              text: 'Continue',
              onPress: () => navigation.replace('MainTabs'),
            },
          ]
        );
      }
    } catch (error: any) {
      console.error('Google Sign-In Error:', error);
      Alert.alert(
        'Sign In Failed',
        error.message || 'Failed to sign in with Google. Please try again.'
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleAppleSignIn = async () => {
    if (Platform.OS !== 'ios') {
      Alert.alert('Not Available', 'Apple Sign In is only available on iOS devices');
      return;
    }
    
    if (isLoading) return;
    
    setIsLoading(true);
    try {
      const userInfo = await authServiceWeb3.signInWithApple();
      
      if (userInfo) {
        Alert.alert(
          'Welcome to Web3!',
          `Your Algorand address: ${userInfo.algorandAddress?.substring(0, 8)}...${userInfo.algorandAddress?.substring(50)}`,
          [
            {
              text: 'Continue',
              onPress: () => navigation.replace('MainTabs'),
            },
          ]
        );
      }
    } catch (error: any) {
      console.error('Apple Sign-In Error:', error);
      Alert.alert(
        'Sign In Failed',
        error.message || 'Failed to sign in with Apple. Please try again.'
      );
    } finally {
      setIsLoading(false);
    }
  };

  const toggleAuthMode = () => {
    setAuthMode(authMode === 'web3' ? 'legacy' : 'web3');
    if (authMode === 'web3') {
      // Switch to legacy auth screen
      navigation.replace('Auth');
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <View style={styles.header}>
          <Image 
            source={require('../assets/logo.png')} 
            style={styles.logo}
            resizeMode="contain"
          />
          <Text style={styles.title}>Welcome to Confio</Text>
          <Text style={styles.subtitle}>
            {authMode === 'web3' 
              ? 'Sign in with Web3Auth and get your Algorand wallet'
              : 'Sign in with traditional authentication'}
          </Text>
        </View>

        <View style={styles.authContainer}>
          {isLoading ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color="#4CAF50" />
              <Text style={styles.loadingText}>Connecting to Web3...</Text>
            </View>
          ) : (
            <>
              <TouchableOpacity 
                style={[styles.authButton, styles.googleButton]}
                onPress={handleGoogleSignIn}
                disabled={isLoading}
              >
                <Icon name="google" size={24} color="#FFFFFF" />
                <Text style={styles.authButtonText}>Continue with Google</Text>
              </TouchableOpacity>

              {Platform.OS === 'ios' && (
                <TouchableOpacity 
                  style={[styles.authButton, styles.appleButton]}
                  onPress={handleAppleSignIn}
                  disabled={isLoading}
                >
                  <Icon name="apple" size={24} color="#FFFFFF" />
                  <Text style={styles.authButtonText}>Continue with Apple</Text>
                </TouchableOpacity>
              )}

              <View style={styles.divider}>
                <View style={styles.dividerLine} />
                <Text style={styles.dividerText}>Web3 Features</Text>
                <View style={styles.dividerLine} />
              </View>

              <View style={styles.featureContainer}>
                <View style={styles.featureItem}>
                  <Icon name="wallet" size={20} color="#4CAF50" />
                  <Text style={styles.featureText}>Algorand Wallet</Text>
                </View>
                <View style={styles.featureItem}>
                  <Icon name="shield-check" size={20} color="#4CAF50" />
                  <Text style={styles.featureText}>Self-Custody</Text>
                </View>
                <View style={styles.featureItem}>
                  <Icon name="lock" size={20} color="#4CAF50" />
                  <Text style={styles.featureText}>Secure & Private</Text>
                </View>
                <View style={styles.featureItem}>
                  <Icon name="flash" size={20} color="#4CAF50" />
                  <Text style={styles.featureText}>Instant Transactions</Text>
                </View>
              </View>

              <TouchableOpacity 
                style={styles.switchModeButton}
                onPress={toggleAuthMode}
              >
                <Text style={styles.switchModeText}>
                  Use Legacy Authentication
                </Text>
              </TouchableOpacity>
            </>
          )}
        </View>

        <View style={styles.footer}>
          <Text style={styles.footerText}>
            By continuing, you agree to our Terms of Service and Privacy Policy
          </Text>
          <Text style={styles.poweredByText}>
            Powered by Web3Auth & Algorand
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  scrollContent: {
    flexGrow: 1,
    justifyContent: 'space-between',
  },
  header: {
    alignItems: 'center',
    paddingTop: 60,
    paddingHorizontal: 20,
  },
  logo: {
    width: 100,
    height: 100,
    marginBottom: 20,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#333333',
    marginBottom: 10,
  },
  subtitle: {
    fontSize: 16,
    color: '#666666',
    textAlign: 'center',
    marginBottom: 30,
  },
  authContainer: {
    paddingHorizontal: 30,
    paddingVertical: 20,
  },
  loadingContainer: {
    alignItems: 'center',
    paddingVertical: 50,
  },
  loadingText: {
    marginTop: 15,
    fontSize: 16,
    color: '#666666',
  },
  authButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 15,
    paddingHorizontal: 20,
    borderRadius: 10,
    marginVertical: 10,
  },
  googleButton: {
    backgroundColor: '#4285F4',
  },
  appleButton: {
    backgroundColor: '#000000',
  },
  authButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
    marginLeft: 10,
  },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginVertical: 30,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: '#E0E0E0',
  },
  dividerText: {
    marginHorizontal: 15,
    fontSize: 14,
    color: '#999999',
  },
  featureContainer: {
    backgroundColor: '#F5F5F5',
    borderRadius: 10,
    padding: 20,
    marginBottom: 20,
  },
  featureItem: {
    flexDirection: 'row',
    alignItems: 'center',
    marginVertical: 8,
  },
  featureText: {
    marginLeft: 15,
    fontSize: 14,
    color: '#333333',
  },
  switchModeButton: {
    alignItems: 'center',
    paddingVertical: 10,
  },
  switchModeText: {
    fontSize: 14,
    color: '#4CAF50',
    textDecorationLine: 'underline',
  },
  footer: {
    paddingHorizontal: 30,
    paddingBottom: 30,
    alignItems: 'center',
  },
  footerText: {
    fontSize: 12,
    color: '#999999',
    textAlign: 'center',
    marginBottom: 10,
  },
  poweredByText: {
    fontSize: 11,
    color: '#BBBBBB',
    fontStyle: 'italic',
  },
});
