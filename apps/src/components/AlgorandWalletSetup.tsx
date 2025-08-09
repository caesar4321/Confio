/**
 * Simple component to setup Algorand wallet for authenticated users
 * Add this to any screen where you want to ensure the user has an Algorand wallet
 */

import React, { useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet, TouchableOpacity, Alert } from 'react-native';
import { algorandExtension } from '../services/algorandExtension';
import { useAccount } from '../contexts/AccountContext';
import Icon from 'react-native-vector-icons/MaterialCommunityIcons';

interface AlgorandWalletSetupProps {
  onWalletCreated?: (address: string) => void;
  showStatus?: boolean;
}

export function AlgorandWalletSetup({ onWalletCreated, showStatus = false }: AlgorandWalletSetupProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { activeAccount, refreshAccounts } = useAccount();

  useEffect(() => {
    console.log('AlgorandWalletSetup - Component mounted');
    console.log('AlgorandWalletSetup - Current address:', activeAccount?.algorandAddress);
    checkAndSetupWallet();
  }, []);

  const checkAndSetupWallet = async () => {
    try {
      // Check if user already has an Algorand wallet (not Aptos)
      // Algorand addresses are 58 characters, Aptos addresses start with "0x"
      const currentAddress = activeAccount?.algorandAddress;
      
      if (currentAddress) {
        console.log('AlgorandWalletSetup - Current address:', currentAddress);
        
        // Check if this is an Aptos address (needs migration to Algorand)
        if (currentAddress.startsWith('0x')) {
          console.log('AlgorandWalletSetup - Found Aptos address, migrating to Algorand...');
          await setupWallet();
          return;
        }
        
        // It's already an Algorand address
        console.log('AlgorandWalletSetup - User already has Algorand wallet:', currentAddress);
        setWalletAddress(currentAddress);
        return;
      }

      // No address at all, setup new wallet
      console.log('AlgorandWalletSetup - No wallet found, creating new one...');
      await setupWallet();
    } catch (error) {
      console.error('AlgorandWalletSetup - Error checking wallet:', error);
    }
  };

  const setupWallet = async () => {
    setIsLoading(true);
    setError(null);

    try {
      console.log('AlgorandWalletSetup - Setting up Algorand wallet...');
      
      const wallet = await algorandExtension.setupAlgorandWallet();
      
      if (wallet) {
        console.log('AlgorandWalletSetup - Wallet created:', wallet.address);
        setWalletAddress(wallet.address);
        
        // Refresh account context to get updated address
        if (refreshAccount) {
          console.log('AlgorandWalletSetup - Refreshing account context...');
          await refreshAccount();
        }
        
        // Notify parent component
        if (onWalletCreated) {
          console.log('AlgorandWalletSetup - Calling onWalletCreated callback...');
          onWalletCreated(wallet.address);
        }
        
        if (wallet.isNew && showStatus) {
          Alert.alert(
            'Wallet Created!',
            `Your Algorand wallet has been created:\n\n${wallet.address.substring(0, 8)}...${wallet.address.substring(50)}`,
            [{ text: 'OK' }]
          );
        }
      } else {
        console.error('AlgorandWalletSetup - Wallet creation returned null');
        setError('Failed to create wallet');
      }
    } catch (err: any) {
      console.error('AlgorandWalletSetup - Error setting up wallet:', err);
      console.error('AlgorandWalletSetup - Error stack:', err.stack);
      setError(err.message || 'Failed to setup wallet');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRetry = () => {
    setupWallet();
  };

  if (!showStatus) {
    // Silent mode - just setup wallet in background
    return null;
  }

  if (isLoading) {
    return (
      <View style={styles.container}>
        <ActivityIndicator size="small" color="#4CAF50" />
        <Text style={styles.loadingText}>Setting up blockchain wallet...</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.container}>
        <View style={styles.errorContainer}>
          <Icon name="alert-circle" size={20} color="#F44336" />
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity onPress={handleRetry} style={styles.retryButton}>
            <Text style={styles.retryText}>Retry</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  if (walletAddress) {
    return (
      <View style={styles.container}>
        <View style={styles.successContainer}>
          <Icon name="check-circle" size={20} color="#4CAF50" />
          <Text style={styles.successText}>Wallet ready</Text>
        </View>
      </View>
    );
  }

  return null;
}

const styles = StyleSheet.create({
  container: {
    padding: 12,
    alignItems: 'center',
  },
  loadingText: {
    marginTop: 8,
    fontSize: 14,
    color: '#666',
  },
  errorContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  errorText: {
    marginLeft: 8,
    fontSize: 14,
    color: '#F44336',
    flex: 1,
  },
  retryButton: {
    marginLeft: 12,
    paddingHorizontal: 12,
    paddingVertical: 4,
    backgroundColor: '#F44336',
    borderRadius: 4,
  },
  retryText: {
    color: '#FFF',
    fontSize: 12,
    fontWeight: '600',
  },
  successContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  successText: {
    marginLeft: 8,
    fontSize: 14,
    color: '#4CAF50',
  },
});