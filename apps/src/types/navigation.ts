import { NavigatorScreenParams } from '@react-navigation/native';

// Auth Stack - Handles authentication flow
export type AuthStackParamList = {
  Login: undefined;
  PhoneVerification: undefined;
  Registration: undefined;
  LegalDocument: { docType: 'terms' | 'privacy' | 'deletion' };
};

// Bottom Tab Navigator - Main app tabs
export type BottomTabParamList = {
  Home: undefined;
  Contacts: undefined;
  Scan: { mode?: 'cobrar' | 'pagar' };
  Charge: undefined;
  Exchange: { 
    showMyOffers?: boolean; 
    refreshData?: boolean;
  };
  Profile: undefined;
};

// Main Stack - Handles main app navigation including modals
export type MainStackParamList = {
  BottomTabs: NavigatorScreenParams<BottomTabParamList>;
  LegalDocument: { docType: 'terms' | 'privacy' | 'deletion' };
  Verification: undefined;
  BankInfo: undefined;
  ConfioAddress: undefined;
  Notification: undefined;
  CreateBusiness: undefined;
  EditBusiness: undefined;
  EditProfile: undefined;
  UpdateUsername: undefined;
  PhoneVerification: undefined;
  TraderProfile: {
    offer?: {
      id: string;
      name: string;
      rate: string;
      limit: string;
      available: string;
      paymentMethods: Array<{id: string; name: string; displayName: string; icon?: string}>;
      responseTime: string;
      completedTrades: number;
      successRate: number;
      verified: boolean;
      isOnline: boolean;
      lastSeen: string;
      terms?: string;
      countryCode?: string;
    };
    trader?: {
      id: string;
      name: string;
      completedTrades: number;
      successRate: number;
      responseTime: string;
      isOnline: boolean;
      verified: boolean;
      lastSeen: string;
      avgRating?: number;
      userId?: string;
      businessId?: string;
    };
    crypto?: 'cUSD' | 'CONFIO';
  };
  TradeConfirm: {
    offer: {
      id: string;
      name: string;
      rate: string;
      limit: string;
      available: string;
      paymentMethods: Array<{id: string; name: string; displayName: string; icon?: string}>;
      responseTime: string;
      completedTrades: number;
      successRate: number;
      verified: boolean;
      isOnline: boolean;
      lastSeen: string;
      countryCode?: string;
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
      paymentMethods: Array<{id: string; name: string; displayName: string; icon?: string}>;
      responseTime: string;
      completedTrades: number;
      successRate: number;
      verified: boolean;
      isOnline: boolean;
      lastSeen: string;
      countryCode?: string;
    };
    crypto: 'cUSD' | 'CONFIO';
    amount: string;
    tradeType: 'buy' | 'sell';
    tradeId: string;
    selectedPaymentMethodId?: string;
    tradeCountryCode?: string;
    tradeCurrencyCode?: string;
    initialStep?: number;
    tradeStatus?: string;
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
        completedTrades?: number;
        successRate?: number;
        avgRating?: number;
      };
      amount: string;
      crypto: string;
      totalBs: string;
      paymentMethod: string;
      rate: string;
      step: number;
      timeRemaining: number;
      tradeType: 'buy' | 'sell';
      countryCode?: string;
      currencyCode?: string;
      status?: string;
      hasRating?: boolean;
    };
  };
  AccountDetail: {
    accountType: 'cusd' | 'confio';
    accountName: string;
    accountSymbol: string;
    accountBalance: string;
    accountAddress?: string;
  };
  USDCDeposit: { tokenType?: 'usdc' | 'cusd' | 'confio' };
  USDCManage: undefined;
  USDCWithdraw: undefined;
  USDCHistory: undefined;
  USDCConversion: undefined;
  SendWithAddress: { tokenType: 'cusd' | 'confio' };
  SendToFriend: { 
    friend: { name: string; avatar: string; isOnConfio: boolean; phone: string };
    tokenType?: 'cusd' | 'confio';
  };
  FriendDetail: {
    friendId: string;
    friendName: string;
    friendAvatar: string;
    friendPhone?: string;
    isOnConfio: boolean;
  };
  EmployeeDetail: {
    employeeId: string;
    employeeName: string;
    employeePhone: string;
    employeeRole: string;
    isActive: boolean;
    employeeData: any; // Full employee object from GraphQL
  };
  TransactionDetail: {
    transactionType: 'received' | 'sent' | 'exchange' | 'payment' | 'deposit' | 'withdrawal' | 'conversion';
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
        algorandAddress: string;
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
        algorandAddress: string;
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
        algorandAddress: string;
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
    tradeId: string;
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
  CreateOffer: {
    editMode?: boolean;
    offerId?: string;
    offerData?: {
      exchangeType: 'BUY' | 'SELL';
      tokenType: string;
      rate: number;
      minAmount: number;
      maxAmount: number;
      countryCode: string;
      paymentMethods: Array<{id: string; name: string; displayName: string}>;
      terms?: string;
    };
  } | undefined;
  Achievements: undefined;
  ConfioTokenInfo: undefined;
  ConfioPresale: undefined;
  ConfioPresaleParticipate: undefined;
  ConfioTokenomics: undefined;
  MiProgresoViral: undefined;
  ViralTemplates: undefined;
  ReferralFriendJoined: { friendName?: string };
  ReferralActionPrompt: { event?: string };
  ReferralEventDetail: { event?: string; referralId?: string | number; role?: 'referee' | 'referrer'; friendName?: string };
  // NotificationSettings: undefined; // Hidden: Notifications mandatory
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
    accountAddress?: string;
  };
}; 
