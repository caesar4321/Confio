import { NavigatorScreenParams } from '@react-navigation/native';

// Auth Stack - Handles authentication flow
export type AuthStackParamList = {
  Login: undefined;
  PhoneVerification: undefined;
  Registration: undefined;
};

// Bottom Tab Navigator - Main app tabs
export type BottomTabParamList = {
  Home: undefined;
  Contacts: undefined;
  Scan: undefined;
  Exchange: undefined;
  Profile: undefined;
};

// Main Stack - Handles main app navigation including modals
export type MainStackParamList = {
  BottomTabs: NavigatorScreenParams<BottomTabParamList>;
  LegalDocument: { docType: 'terms' | 'privacy' | 'deletion' };
  Verification: undefined;
  ConfioAddress: undefined;
  AccountDetail: {
    accountType: 'cusd' | 'confio';
    accountName: string;
    accountSymbol: string;
    accountBalance: string;
  };
  USDCDeposit: undefined;
};

// Root Stack - Top level navigation
export type RootStackParamList = {
  Auth: NavigatorScreenParams<AuthStackParamList>;
  Main: NavigatorScreenParams<MainStackParamList>;
  AccountDetail: {
    accountType: 'cusd' | 'confio';
    accountName: string;
    accountSymbol: string;
    accountBalance: string;
  };
}; 