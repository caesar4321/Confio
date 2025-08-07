import { Platform } from 'react-native';

// Debug log to verify config is loaded
console.log('Loading Web3Auth config...');

export const WEB3AUTH_CONFIG = {
  // Web3Auth Client ID for Single Factor Auth
  clientId: 'BKPbVLK-kIWlnwKwgYrcVFtOhkKIt4Sp1dxnF-qIPOdRAHLII_mfoJKpjfWwhOUIMwGYqjEX5n_5uQXtsEEPakE',
  
  // Network configuration
  network: 'sapphire_devnet', // Using devnet for Algorand testnet
  
  // Redirect URLs for OAuth
  redirectUrl: Platform.select({
    ios: 'com.confio://auth',
    android: 'com.confio://auth',
  }),
  
  // WhiteLabel configuration for branding
  whiteLabel: {
    appName: 'Confio',
    appUrl: 'https://confio.com',
    logoLight: 'https://confio.com/logo-light.png',
    logoDark: 'https://confio.com/logo-dark.png',
    defaultLanguage: 'en',
    theme: {
      primary: '#4CAF50',
      onPrimary: '#FFFFFF',
      secondary: '#2196F3',
      onSecondary: '#FFFFFF',
    },
  },
  
  // OpenLogin configuration for Single Factor Auth
  openloginAdapter: {
    adapterSettings: {
      clientId: 'BKPbVLK-kIWlnwKwgYrcVFtOhkKIt4Sp1dxnF-qIPOdRAHLII_mfoJKpjfWwhOUIMwGYqjEX5n_5uQXtsEEPakE',
      network: 'sapphire_mainnet',
      uxMode: 'redirect',
      // For Single Factor Auth with native OAuth providers
      loginConfig: {
        google: {
          verifier: 'google', // Use Web3Auth's built-in Google verifier
          typeOfLogin: 'google',
          clientId: 'BKPbVLK-kIWlnwKwgYrcVFtOhkKIt4Sp1dxnF-qIPOdRAHLII_mfoJKpjfWwhOUIMwGYqjEX5n_5uQXtsEEPakE',
        },
        apple: {
          verifier: 'apple', // Use Web3Auth's built-in Apple verifier
          typeOfLogin: 'apple',
          clientId: 'BKPbVLK-kIWlnwKwgYrcVFtOhkKIt4Sp1dxnF-qIPOdRAHLII_mfoJKpjfWwhOUIMwGYqjEX5n_5uQXtsEEPakE',
        },
      },
    },
  },
  
  // Algorand Network Configuration
  algorand: {
    network: 'testnet', // Using testnet for development
    rpcUrl: 'https://testnet-api.algonode.cloud',
    indexerUrl: 'https://testnet-idx.algonode.cloud',
    port: 443,
  },
};

// Debug log to verify config is created correctly
console.log('Web3Auth config created with clientId:', WEB3AUTH_CONFIG.clientId ? 'present' : 'missing');

// Algorand network configurations
export const ALGORAND_NETWORKS = {
  mainnet: {
    name: 'MainNet',
    rpcUrl: 'https://mainnet-api.algonode.cloud',
    indexerUrl: 'https://mainnet-idx.algonode.cloud',
    port: 443,
  },
  testnet: {
    name: 'TestNet',
    rpcUrl: 'https://testnet-api.algonode.cloud',
    indexerUrl: 'https://testnet-idx.algonode.cloud',
    port: 443,
  },
  betanet: {
    name: 'BetaNet',
    rpcUrl: 'https://betanet-api.algonode.cloud',
    indexerUrl: 'https://betanet-idx.algonode.cloud',
    port: 443,
  },
};