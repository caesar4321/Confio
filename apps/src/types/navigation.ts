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
  Scan: { mode?: 'cobrar' | 'pagar' };
  Charge: undefined;
  Exchange: undefined;
  Profile: undefined;
};

// Main Stack - Handles main app navigation including modals
export type MainStackParamList = {
  BottomTabs: NavigatorScreenParams<BottomTabParamList>;
  LegalDocument: { docType: 'terms' | 'privacy' | 'deletion' };
  Verification: undefined;
  ConfioAddress: undefined;
  Notification: undefined;
  CreateBusiness: undefined;
  EditBusiness: undefined;
  EditProfile: undefined;
  PhoneVerification: undefined;
  TraderProfile: {
    offer: {
      id: string;
      name: string;
      rate: string;
      limit: string;
      available: string;
      paymentMethods: string[];
      responseTime: string;
      completedTrades: number;
      successRate: number;
      verified: boolean;
      isOnline: boolean;
      lastSeen: string;
    };
    crypto: 'cUSD' | 'CONFIO';
  };
  TradeConfirm: {
    offer: {
      id: string;
      name: string;
      rate: string;
      limit: string;
      available: string;
      paymentMethods: string[];
      responseTime: string;
      completedTrades: number;
      successRate: number;
      verified: boolean;
      isOnline: boolean;
      lastSeen: string;
    };
    crypto: 'cUSD' | 'CONFIO';
    tradeType: 'buy' | 'sell';
  };
  TradeChat: {
    offer: {
      id: string;
      name: string;
      rate: string;
      limit: string;
      available: string;
      paymentMethods: string[];
      responseTime: string;
      completedTrades: number;
      successRate: number;
      verified: boolean;
      isOnline: boolean;
      lastSeen: string;
    };
    crypto: 'cUSD' | 'CONFIO';
    amount: string;
    tradeType: 'buy' | 'sell';
  };
  ActiveTrade: {
    trade: {
      id: string;
      trader: {
        name: string;
        isOnline: boolean;
        verified: boolean;
        lastSeen: string;
        responseTime: string;
      };
      amount: string;
      crypto: string;
      totalBs: string;
      paymentMethod: string;
      rate: string;
      step: number;
      timeRemaining: number;
      tradeType: 'buy' | 'sell';
    };
  };
  AccountDetail: {
    accountType: 'cusd' | 'confio';
    accountName: string;
    accountSymbol: string;
    accountBalance: string;
  };
  USDCDeposit: { tokenType?: 'usdc' | 'cusd' | 'confio' };
  USDCManage: undefined;
  SendWithAddress: { tokenType: 'cusd' | 'confio' };
  SendToFriend: { 
    friend: { name: string; avatar: string; isOnConfio: boolean; phone: string };
    tokenType?: 'cusd' | 'confio';
  };
  TransactionDetail: {
    transactionType: 'received' | 'sent' | 'exchange' | 'payment';
    transactionData?: any; // You can make this more specific based on your data structure
  };
  TransactionProcessing: {
    transactionData: {
      type: 'sent' | 'payment';
      amount: string;
      currency: string;
      recipient?: string;
      merchant?: string;
      action: string;
      isOnConfio?: boolean;
      sendTransactionId?: string;
      recipientAddress?: string;
      invoiceId?: string;
    };
  };
  TransactionSuccess: {
    transactionData: {
      type: 'sent' | 'payment';
      amount: string;
      currency: string;
      recipient?: string;
      merchant?: string;
      recipientAddress?: string;
      merchantAddress?: string;
      message?: string;
      location?: string;
      terminal?: string;
      isOnConfio?: boolean;
      sendTransactionId?: string;
      invoiceId?: string;
    };
  };
  PaymentConfirmation: {
    invoiceData: {
      id: string;
      invoiceId: string;
      amount: string;
      tokenType: string;
      description?: string;
      merchantUser: {
        id: string;
        username: string;
        firstName?: string;
        lastName?: string;
      };
      merchantAccount: {
        id: string;
        accountType: string;
        accountIndex: number;
        suiAddress: string;
        business?: {
          id: string;
          name: string;
          category: string;
          address?: string;
        };
      };
      isExpired: boolean;
    };
  };
  PaymentProcessing: {
    transactionData: {
      type: 'payment';
      amount: string;
      currency: string;
      merchant: string;
      action: string;
    };
  };
  PaymentSuccess: {
    transactionData: {
      type: 'payment';
      amount: string;
      currency: string;
      recipient: string;
      merchant: string;
      recipientAddress?: string;
      merchantAddress?: string;
      message?: string;
      transactionHash?: string;
    };
  };
  BusinessPaymentSuccess: {
    paymentData: {
      id: string;
      paymentTransactionId: string;
      amount: string;
      tokenType: string;
      description?: string;
      payerUser: {
        id: string;
        username: string;
        firstName?: string;
        lastName?: string;
      };
      payerAccount?: {
        id: string;
        accountType: string;
        accountIndex: number;
        suiAddress: string;
        business?: {
          id: string;
          name: string;
          category: string;
          address?: string;
        };
      };
      payerAddress: string;
      merchantUser: {
        id: string;
        username: string;
        firstName?: string;
        lastName?: string;
      };
      merchantAccount?: {
        id: string;
        accountType: string;
        accountIndex: number;
        suiAddress: string;
        business?: {
          id: string;
          name: string;
          category: string;
          address?: string;
        };
      };
      merchantAddress: string;
      status: string;
      transactionHash: string;
      createdAt: string;
    };
  };
  Scan: {
    mode?: 'pagar' | 'cobrar';
  };
  TraderRating: {
    trader: {
      name: string;
      verified: boolean;
      completedTrades: number;
      successRate: number;
    };
    tradeDetails: {
      amount: string;
      crypto: string;
      totalPaid: string;
      method: string;
      date: string;
      duration: string;
    };
  };
  CreateOffer: undefined;
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