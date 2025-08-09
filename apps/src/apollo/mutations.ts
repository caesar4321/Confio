import { gql } from '@apollo/client';

// Web3Auth and Algorand mutations
export const WEB3AUTH_LOGIN = gql`
  mutation Web3AuthLogin(
    $firebaseIdToken: String!
    $algorandAddress: String!
    $deviceFingerprint: JSONString
  ) {
    web3AuthLogin(
      firebaseIdToken: $firebaseIdToken
      algorandAddress: $algorandAddress
      deviceFingerprint: $deviceFingerprint
    ) {
      success
      error
      accessToken
      refreshToken
      user {
        id
        email
        algorandAddress
        isPhoneVerified
      }
    }
  }
`;

export const ADD_ALGORAND_WALLET = gql`
  mutation AddAlgorandWallet($algorandAddress: String!, $web3authId: String, $provider: String) {
    addAlgorandWallet(
      algorandAddress: $algorandAddress
      web3authId: $web3authId
      provider: $provider
    ) {
      success
      error
      isNewWallet
      optedInAssets
      needsOptIn
      algoBalance
      user {
        id
        email
        algorandAddress
        isPhoneVerified
      }
    }
  }
`;

export const GENERATE_OPT_IN_TRANSACTIONS = gql`
  mutation GenerateOptInTransactions($assetIds: [Int]) {
    generateOptInTransactions(assetIds: $assetIds) {
      success
      error
      transactions
    }
  }
`;

export const ALGORAND_SPONSORED_SEND = gql`
  mutation AlgorandSponsoredSend(
    $recipient: String!
    $amount: Float!
    $assetType: String
    $note: String
  ) {
    algorandSponsoredSend(
      recipient: $recipient
      amount: $amount
      assetType: $assetType
      note: $note
    ) {
      success
      error
      userTransaction
      sponsorTransaction
      groupId
      totalFee
      feeInAlgo
    }
  }
`;

export const ALGORAND_SPONSORED_OPT_IN = gql`
  mutation AlgorandSponsoredOptIn($assetId: Int) {
    algorandSponsoredOptIn(assetId: $assetId) {
      success
      error
      alreadyOptedIn
      requiresUserSignature
      userTransaction
      sponsorTransaction
      groupId
      assetId
      assetName
    }
  }
`;

export const SUBMIT_SPONSORED_GROUP = gql`
  mutation SubmitSponsoredGroup(
    $signedUserTxn: String!
    $signedSponsorTxn: String!
  ) {
    submitSponsoredGroup(
      signedUserTxn: $signedUserTxn
      signedSponsorTxn: $signedSponsorTxn
    ) {
      success
      error
      transactionId
      confirmedRound
      feesSaved
    }
  }
`;

export const REFRESH_ACCOUNT_BALANCE = gql`
  mutation RefreshAccountBalance {
    refreshAccountBalance {
      balances {
        cusd
        confio
        usdc
        sui
      }
      lastSynced
      success
      errors
    }
  }
`;

// SEND_TOKENS removed - all sends now go through CREATE_SEND_TRANSACTION

export const CONVERT_USDC_TO_CUSD = gql`
  mutation ConvertUSDCToCUSD($amount: String!) {
    convertUsdcToCusd(amount: $amount) {
      conversion {
        id
        conversionId
        conversionType
        fromAmount
        toAmount
        exchangeRate
        feeAmount
        status
        createdAt
      }
      success
      errors
    }
  }
`;

export const CONVERT_CUSD_TO_USDC = gql`
  mutation ConvertCUSDToUSDC($amount: String!) {
    convertCusdToUsdc(amount: $amount) {
      conversion {
        id
        conversionId
        conversionType
        fromAmount
        toAmount
        exchangeRate
        feeAmount
        status
        createdAt
      }
      success
      errors
    }
  }
`;

export const GET_CONVERSIONS = gql`
  query GetConversions($limit: Int, $status: String) {
    conversions(limit: $limit, status: $status) {
      id
      conversionId
      conversionType
      fromAmount
      toAmount
      exchangeRate
      feeAmount
      fromToken
      toToken
      status
      createdAt
      completedAt
      actorType
      actorDisplayName
      actorUser {
        id
        username
        email
      }
      actorBusiness {
        id
        name
      }
    }
  }
`;

export const GET_UNIFIED_USDC_TRANSACTIONS = gql`
  query GetUnifiedUSDCTransactions($limit: Int, $offset: Int, $transactionType: String) {
    unifiedUsdcTransactions(limit: $limit, offset: $offset, transactionType: $transactionType) {
      transactionId
      transactionType
      actorType
      actorDisplayName
      actorUser {
        id
        username
        firstName
        lastName
      }
      actorBusiness {
        id
        name
      }
      amount
      currency
      secondaryAmount
      secondaryCurrency
      exchangeRate
      networkFee
      serviceFee
      sourceAddress
      destinationAddress
      network
      status
      errorMessage
      createdAt
      updatedAt
      completedAt
      formattedTitle
      iconName
      iconColor
    }
  }
`;

export const CREATE_USDC_WITHDRAWAL = gql`
  mutation CreateUSDCWithdrawal($input: USDCWithdrawalInput!) {
    createUsdcWithdrawal(input: $input) {
      withdrawal {
        id
        withdrawalId
        amount
        destinationAddress
        serviceFee
        status
        createdAt
      }
      success
      errors
    }
  }
`;

// Notification mutations
export const MARK_NOTIFICATION_READ = gql`
  mutation MarkNotificationRead($notificationId: ID!) {
    markNotificationRead(notificationId: $notificationId) {
      success
      notification {
        id
        isRead
      }
    }
  }
`;

export const MARK_ALL_NOTIFICATIONS_READ = gql`
  mutation MarkAllNotificationsRead {
    markAllNotificationsRead {
      success
      markedCount
    }
  }
`;

export const UPDATE_NOTIFICATION_PREFERENCES = gql`
  mutation UpdateNotificationPreferences(
    $pushEnabled: Boolean
    $pushTransactions: Boolean
    $pushP2p: Boolean
    $pushSecurity: Boolean
    $pushPromotions: Boolean
    $pushAnnouncements: Boolean
    $inAppEnabled: Boolean
    $inAppTransactions: Boolean
    $inAppP2p: Boolean
    $inAppSecurity: Boolean
    $inAppPromotions: Boolean
    $inAppAnnouncements: Boolean
  ) {
    updateNotificationPreferences(
      pushEnabled: $pushEnabled
      pushTransactions: $pushTransactions
      pushP2p: $pushP2p
      pushSecurity: $pushSecurity
      pushPromotions: $pushPromotions
      pushAnnouncements: $pushAnnouncements
      inAppEnabled: $inAppEnabled
      inAppTransactions: $inAppTransactions
      inAppP2p: $inAppP2p
      inAppSecurity: $inAppSecurity
      inAppPromotions: $inAppPromotions
      inAppAnnouncements: $inAppAnnouncements
    ) {
      success
      preferences {
        pushEnabled
        pushTransactions
        pushP2p
        pushSecurity
        pushPromotions
        pushAnnouncements
        inAppEnabled
        inAppTransactions
        inAppP2p
        inAppSecurity
        inAppPromotions
        inAppAnnouncements
      }
    }
  }
`;