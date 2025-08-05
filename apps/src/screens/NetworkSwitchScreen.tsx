import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  ScrollView,
  SafeAreaView,
} from 'react-native';
import { useBlockchainAuth } from '../contexts/BlockchainAuthContext';
import { theme } from '../config/theme';

export const NetworkSwitchScreen: React.FC = () => {
  const {
    currentNetwork,
    setCurrentNetwork,
    isAuthenticated,
    isLoading,
    suiAccount,
    suiBalance,
    aptosAccount,
    aptosBalance,
    signInWithGoogle,
    signInWithApple,
    signOut,
    refreshBalances,
  } = useBlockchainAuth();

  const handleNetworkSwitch = async (network: 'sui' | 'aptos') => {
    try {
      await setCurrentNetwork(network);
    } catch (error) {
      Alert.alert('Error', 'Failed to switch network');
    }
  };

  const handleSignIn = async (provider: 'google' | 'apple') => {
    try {
      if (provider === 'google') {
        await signInWithGoogle();
      } else {
        await signInWithApple();
      }
      Alert.alert('Success', `Signed in with ${provider} on ${currentNetwork.toUpperCase()}`);
    } catch (error: any) {
      Alert.alert('Sign In Error', error.message || 'Failed to sign in');
    }
  };

  const handleSignOut = async () => {
    try {
      await signOut();
      Alert.alert('Success', 'Signed out successfully');
    } catch (error) {
      Alert.alert('Error', 'Failed to sign out');
    }
  };

  const renderNetworkInfo = () => {
    if (!isAuthenticated) {
      return (
        <View style={styles.infoContainer}>
          <Text style={styles.infoText}>Not authenticated</Text>
        </View>
      );
    }

    const account = currentNetwork === 'sui' ? suiAccount : aptosAccount;
    const balance = currentNetwork === 'sui' ? suiBalance : aptosBalance;
    const address = currentNetwork === 'sui' 
      ? suiAccount?.aptosAddress 
      : aptosAccount?.address;

    return (
      <View style={styles.infoContainer}>
        <Text style={styles.label}>Address:</Text>
        <Text style={styles.addressText} numberOfLines={1} ellipsizeMode="middle">
          {address || 'N/A'}
        </Text>
        
        <Text style={styles.label}>Balance:</Text>
        <Text style={styles.balanceText}>
          {balance || '0'} {currentNetwork === 'sui' ? 'SUI' : 'APT'}
        </Text>
        
        <TouchableOpacity style={styles.refreshButton} onPress={refreshBalances}>
          <Text style={styles.refreshButtonText}>Refresh Balance</Text>
        </TouchableOpacity>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <Text style={styles.title}>Blockchain Network</Text>

        {/* Network Selection */}
        <View style={styles.networkContainer}>
          <TouchableOpacity
            style={[
              styles.networkButton,
              currentNetwork === 'sui' && styles.networkButtonActive,
            ]}
            onPress={() => handleNetworkSwitch('sui')}
            disabled={isLoading}
          >
            <Text
              style={[
                styles.networkButtonText,
                currentNetwork === 'sui' && styles.networkButtonTextActive,
              ]}
            >
              Sui (zkLogin)
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[
              styles.networkButton,
              currentNetwork === 'aptos' && styles.networkButtonActive,
            ]}
            onPress={() => handleNetworkSwitch('aptos')}
            disabled={isLoading}
          >
            <Text
              style={[
                styles.networkButtonText,
                currentNetwork === 'aptos' && styles.networkButtonTextActive,
              ]}
            >
              Aptos (Keyless)
            </Text>
          </TouchableOpacity>
        </View>

        {/* Current Network Status */}
        <View style={styles.statusContainer}>
          <Text style={styles.statusText}>
            Current Network: <Text style={styles.networkName}>{currentNetwork.toUpperCase()}</Text>
          </Text>
        </View>

        {/* Account Info */}
        {renderNetworkInfo()}

        {/* Auth Buttons */}
        {isLoading ? (
          <ActivityIndicator size="large" color={theme.primaryColor} style={styles.loader} />
        ) : (
          <View style={styles.authContainer}>
            {!isAuthenticated ? (
              <>
                <TouchableOpacity
                  style={styles.authButton}
                  onPress={() => handleSignIn('google')}
                >
                  <Text style={styles.authButtonText}>Sign in with Google</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={[styles.authButton, styles.appleButton]}
                  onPress={() => handleSignIn('apple')}
                >
                  <Text style={styles.authButtonText}>Sign in with Apple</Text>
                </TouchableOpacity>
              </>
            ) : (
              <TouchableOpacity
                style={[styles.authButton, styles.signOutButton]}
                onPress={handleSignOut}
              >
                <Text style={styles.authButtonText}>Sign Out</Text>
              </TouchableOpacity>
            )}
          </View>
        )}

        {/* Info Section */}
        <View style={styles.infoSection}>
          <Text style={styles.infoTitle}>About Networks</Text>
          <Text style={styles.infoDescription}>
            <Text style={styles.bold}>Sui Network:</Text> Uses zkLogin for authentication with zero-knowledge proofs.
          </Text>
          <Text style={styles.infoDescription}>
            <Text style={styles.bold}>Aptos Network:</Text> Uses Keyless Accounts for seamless Web2 authentication.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  scrollContent: {
    padding: 20,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 30,
    color: '#333',
  },
  networkContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 20,
  },
  networkButton: {
    flex: 1,
    padding: 15,
    marginHorizontal: 5,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: '#ddd',
    backgroundColor: '#fff',
  },
  networkButtonActive: {
    borderColor: theme.primaryColor,
    backgroundColor: theme.primaryColor,
  },
  networkButtonText: {
    textAlign: 'center',
    fontSize: 16,
    fontWeight: '600',
    color: '#666',
  },
  networkButtonTextActive: {
    color: '#fff',
  },
  statusContainer: {
    padding: 15,
    backgroundColor: '#fff',
    borderRadius: 10,
    marginBottom: 20,
  },
  statusText: {
    fontSize: 16,
    color: '#666',
  },
  networkName: {
    fontWeight: 'bold',
    color: theme.primaryColor,
  },
  infoContainer: {
    padding: 20,
    backgroundColor: '#fff',
    borderRadius: 10,
    marginBottom: 20,
  },
  infoText: {
    textAlign: 'center',
    color: '#666',
    fontSize: 16,
  },
  label: {
    fontSize: 14,
    color: '#666',
    marginBottom: 5,
  },
  addressText: {
    fontSize: 14,
    color: '#333',
    marginBottom: 15,
    fontFamily: 'monospace',
  },
  balanceText: {
    fontSize: 20,
    fontWeight: 'bold',
    color: theme.primaryColor,
    marginBottom: 15,
  },
  refreshButton: {
    padding: 10,
    backgroundColor: '#f0f0f0',
    borderRadius: 5,
    alignSelf: 'center',
  },
  refreshButtonText: {
    color: theme.primaryColor,
    fontWeight: '600',
  },
  authContainer: {
    marginBottom: 30,
  },
  authButton: {
    backgroundColor: theme.primaryColor,
    padding: 15,
    borderRadius: 10,
    marginBottom: 10,
  },
  appleButton: {
    backgroundColor: '#000',
  },
  signOutButton: {
    backgroundColor: '#ff4444',
  },
  authButtonText: {
    color: '#fff',
    textAlign: 'center',
    fontSize: 16,
    fontWeight: '600',
  },
  loader: {
    marginVertical: 20,
  },
  infoSection: {
    backgroundColor: '#fff',
    padding: 20,
    borderRadius: 10,
  },
  infoTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 10,
    color: '#333',
  },
  infoDescription: {
    fontSize: 14,
    color: '#666',
    marginBottom: 10,
    lineHeight: 20,
  },
  bold: {
    fontWeight: 'bold',
  },
});