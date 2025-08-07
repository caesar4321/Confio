/**
 * Algorand Wallet Card Component
 * 
 * Drop this into any screen where the user is already authenticated
 * to add Algorand wallet functionality.
 */

import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from 'react-native';
import Icon from 'react-native-vector-icons/MaterialCommunityIcons';
import { useAlgorandWallet } from '../hooks/useAlgorandWallet';

export function AlgorandWalletCard() {
  const {
    walletInfo,
    isLoading,
    error,
    hasWallet,
    refreshBalance,
    isAuthenticated
  } = useAlgorandWallet();

  // Don't show if user is not authenticated
  if (!isAuthenticated) {
    return null;
  }

  const handleCopyAddress = () => {
    if (walletInfo?.address) {
      // In a real app, you'd use Clipboard API here
      Alert.alert('Address Copied', walletInfo.address);
    }
  };

  const handleRefreshBalance = async () => {
    await refreshBalance();
  };

  if (isLoading && !walletInfo) {
    return (
      <View style={styles.card}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="small" color="#4CAF50" />
          <Text style={styles.loadingText}>Setting up Algorand wallet...</Text>
        </View>
      </View>
    );
  }

  if (error && !walletInfo) {
    return (
      <View style={styles.card}>
        <View style={styles.errorContainer}>
          <Icon name="alert-circle" size={20} color="#F44336" />
          <Text style={styles.errorText}>{error}</Text>
        </View>
      </View>
    );
  }

  if (!hasWallet) {
    return null;
  }

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Icon name="wallet" size={24} color="#4CAF50" />
        <Text style={styles.title}>Algorand Wallet</Text>
        {walletInfo?.isNew && (
          <View style={styles.newBadge}>
            <Text style={styles.newBadgeText}>NEW</Text>
          </View>
        )}
      </View>

      <TouchableOpacity style={styles.addressContainer} onPress={handleCopyAddress}>
        <Text style={styles.addressLabel}>Address:</Text>
        <Text style={styles.address}>
          {walletInfo?.address.substring(0, 8)}...{walletInfo?.address.substring(50)}
        </Text>
        <Icon name="content-copy" size={16} color="#666" />
      </TouchableOpacity>

      <View style={styles.balanceContainer}>
        <Text style={styles.balanceLabel}>Balance:</Text>
        <Text style={styles.balance}>
          {walletInfo?.balance?.toFixed(6) || '0.000000'} ALGO
        </Text>
        <TouchableOpacity onPress={handleRefreshBalance}>
          <Icon name="refresh" size={20} color="#4CAF50" />
        </TouchableOpacity>
      </View>

      <View style={styles.actions}>
        <TouchableOpacity style={styles.actionButton}>
          <Icon name="arrow-up" size={20} color="#FFF" />
          <Text style={styles.actionButtonText}>Send</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionButton}>
          <Icon name="arrow-down" size={20} color="#FFF" />
          <Text style={styles.actionButtonText}>Receive</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 16,
    marginHorizontal: 16,
    marginVertical: 8,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    color: '#333',
    marginLeft: 8,
    flex: 1,
  },
  newBadge: {
    backgroundColor: '#4CAF50',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
  },
  newBadgeText: {
    color: '#FFF',
    fontSize: 10,
    fontWeight: 'bold',
  },
  addressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F5F5F5',
    padding: 12,
    borderRadius: 8,
    marginBottom: 12,
  },
  addressLabel: {
    fontSize: 12,
    color: '#666',
    marginRight: 8,
  },
  address: {
    fontSize: 14,
    color: '#333',
    fontFamily: 'monospace',
    flex: 1,
  },
  balanceContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  balanceLabel: {
    fontSize: 14,
    color: '#666',
    marginRight: 8,
  },
  balance: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#333',
    flex: 1,
  },
  actions: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#4CAF50',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 8,
  },
  actionButtonText: {
    color: '#FFF',
    fontSize: 14,
    fontWeight: '600',
    marginLeft: 6,
  },
  loadingContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
  },
  loadingText: {
    marginLeft: 10,
    fontSize: 14,
    color: '#666',
  },
  errorContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
  },
  errorText: {
    marginLeft: 8,
    fontSize: 14,
    color: '#F44336',
    flex: 1,
  },
});