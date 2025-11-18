import { gql } from '@apollo/client';

// Web3Auth and Algorand mutations
export const WEB3AUTH_LOGIN = gql`
  mutation Web3AuthLogin(
    $firebaseIdToken: String!
    $algorandAddress: String
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
      needsOptIn
      optInTransactions
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
  mutation GenerateOptInTransactions($assetIds: [String]) {
    generateOptInTransactions(assetIds: $assetIds) {
      success
      error
      transactions
    }
  }
`;

export const ALGORAND_SPONSORED_SEND = gql`
  mutation AlgorandSponsoredSend(
    $recipientAddress: String
    $recipientUserId: ID
    $recipientPhone: String
    $amount: Float!
    $assetType: String
    $note: String
  ) {
    algorandSponsoredSend(
      recipientAddress: $recipientAddress
      recipientUserId: $recipientUserId
      recipientPhone: $recipientPhone
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
  mutation AlgorandSponsoredOptIn($assetId: String) {
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
        confioPresaleLocked
        usdc
      }
      lastSynced
      success
      errors
    }
  }
`;

export const PREPARE_REFERRAL_REWARD_CLAIM = gql`
  mutation PrepareReferralRewardClaim($eventId: ID!) {
    prepareReferralRewardClaim(eventId: $eventId) {
      success
      error
      claimToken
      unsignedTransaction
      groupId
      amount
      expiresAt
    }
  }
`;

export const SUBMIT_REFERRAL_REWARD_CLAIM = gql`
  mutation SubmitReferralRewardClaim($claimToken: String!, $signedTransaction: String!) {
    submitReferralRewardClaim(claimToken: $claimToken, signedTransaction: $signedTransaction) {
      success
      error
      txId
    }
  }
`;

// SEND_TOKENS removed - all sends now go through CREATE_SEND_TRANSACTION

/* Removed: use ws/convert_session */
/* export const CONVERT_USDC_TO_CUSD = gql`
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
        fromTransactionHash
        toTransactionHash
      }
      success
      errors
      transactionsToSign
      sponsorTransactions
      groupId
      requiresAppOptin
      appId
    }
  }
`; */

/* Removed: use ws/convert_session */
/* export const CONVERT_CUSD_TO_USDC = gql`
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
        fromTransactionHash
        toTransactionHash
      }
      success
      errors
      transactionsToSign
      sponsorTransactions
      groupId
      requiresAppOptin
      appId
    }
  }
`; */

// Invite & Send — prepare invite for phone
export const PREPARE_INVITE_FOR_PHONE = gql`
  mutation PrepareInviteForPhone(
    $phone: String!,
    $phoneCountry: String,
    $amount: Float!,
    $assetType: String,
    $message: String
  ) {
    prepareInviteForPhone(
      phone: $phone,
      phoneCountry: $phoneCountry,
      amount: $amount,
      assetType: $assetType,
      message: $message
    ) {
      success
      error
      userTransaction { txn groupId first last gh gen }
      sponsorTransactions { txn index }
      groupId
      invitationId
    }
  }
`;

// KYC presigned uploads + submit
export const REQUEST_IDENTITY_UPLOAD = gql`
  mutation RequestIdentityUpload($part: String!, $filename: String, $contentType: String, $sha256: String) {
    requestIdentityUpload(part: $part, filename: $filename, contentType: $contentType, sha256: $sha256) {
      success
      error
      upload { url key method headers fields expiresIn }
    }
  }
`;

export const SUBMIT_IDENTITY_VERIFICATION_S3 = gql`
  mutation SubmitIdentityVerificationS3(
    $frontKey: String!,
    $selfieKey: String!,
    $backKey: String,
    $payoutMethodLabel: String,
    $payoutProofKey: String,
    $verifiedDateOfBirth: Date
    $businessKey: String
  ) {
    submitIdentityVerificationS3(
      frontKey: $frontKey,
      selfieKey: $selfieKey,
      backKey: $backKey,
      payoutMethodLabel: $payoutMethodLabel,
      payoutProofKey: $payoutProofKey,
      verifiedDateOfBirth: $verifiedDateOfBirth,
      businessKey: $businessKey
    ) {
      success
      error
      verification { id status }
    }
  }
`;

// Request upgrade to Trader Premium (verification level 2)
export const REQUEST_PREMIUM_UPGRADE = gql`
  mutation RequestPremiumUpgrade($reason: String) {
    requestPremiumUpgrade(reason: $reason) {
      success
      error
      verificationLevel
    }
  }
`;

// Invite & Send — submit invite group
export const SUBMIT_INVITE_FOR_PHONE = gql`
  mutation SubmitInviteForPhone(
    $signedUserTxn: String!,
    $sponsorTransactions: [JSONString!]!,
    $invitationId: String!,
    $message: String
  ) {
    submitInviteForPhone(
      signedUserTxn: $signedUserTxn,
      sponsorTransactions: $sponsorTransactions,
      invitationId: $invitationId,
      message: $message
    ) {
      success
      error
      txid
    }
  }
`;

// Invite & Send — claim invite for phone
export const CLAIM_INVITE_FOR_PHONE = gql`
  mutation ClaimInviteForPhone($recipientAddress: String!, $invitationId: String, $phone: String, $phoneCountry: String) {
    claimInviteForPhone(recipientAddress: $recipientAddress, invitationId: $invitationId, phone: $phone, phoneCountry: $phoneCountry) {
      success
      error
      txid
    }
  }
`;

// P2P Trade — prepare create (seller deposits escrow)
export const PREPARE_P2P_CREATE_TRADE = gql`
  mutation PrepareP2PCreateTrade($tradeId: String!, $amount: Float!, $assetType: String) {
    prepareP2pCreateTrade(tradeId: $tradeId, amount: $amount, assetType: $assetType) {
      success
      error
      userTransactions
      sponsorTransactions { txn index }
      groupId
      tradeId
    }
  }
`;

export const SUBMIT_P2P_CREATE_TRADE = gql`
  mutation SubmitP2PCreateTrade($signedUserTxns: [String!]!, $sponsorTransactions: [JSONString!]!, $tradeId: String!) {
    submitP2pCreateTrade(signedUserTxns: $signedUserTxns, sponsorTransactions: $sponsorTransactions, tradeId: $tradeId) {
      success
      error
      txid
    }
  }
`;

export const ACCEPT_P2P_TRADE = gql`
  mutation AcceptP2pTrade($tradeId: String!) {
    acceptP2pTrade(tradeId: $tradeId) {
      success
      error
      txid
    }
  }
`;

export const PREPARE_P2P_ACCEPT_TRADE = gql`
  mutation PrepareP2pAcceptTrade($tradeId: String!) {
    prepareP2pAcceptTrade(tradeId: $tradeId) {
      success
      error
      userTransactions
      sponsorTransactions { txn index }
      groupId
      tradeId
    }
  }
`;

export const SUBMIT_P2P_ACCEPT_TRADE = gql`
  mutation SubmitP2pAcceptTrade($tradeId: String!, $signedUserTxn: String!, $sponsorTransactions: [JSONString!]!) {
    submitP2pAcceptTrade(tradeId: $tradeId, signedUserTxn: $signedUserTxn, sponsorTransactions: $sponsorTransactions) {
      success
      error
      txid
    }
  }
`;

export const PREPARE_P2P_MARK_PAID = gql`
  mutation PrepareP2pMarkPaid($tradeId: String!, $paymentRef: String!) {
    prepareP2pMarkPaid(tradeId: $tradeId, paymentRef: $paymentRef) {
      success
      error
      userTransactions
      sponsorTransactions { txn index }
      groupId
      tradeId
    }
  }
`;

export const MARK_P2P_TRADE_PAID = gql`
  mutation MarkP2pTradePaid($tradeId: String!, $signedUserTxn: String!, $sponsorTransactions: [JSONString!]!, $paymentRef: String!) {
    markP2pTradePaid(tradeId: $tradeId, signedUserTxn: $signedUserTxn, sponsorTransactions: $sponsorTransactions, paymentRef: $paymentRef) {
      success
      error
      txid
    }
  }
`;

export const PREPARE_P2P_CONFIRM_RECEIVED = gql`
  mutation PrepareP2pConfirmReceived($tradeId: String!) {
    prepareP2pConfirmReceived(tradeId: $tradeId) {
      success
      error
      userTransactions
      sponsorTransactions { txn index }
      groupId
      tradeId
    }
  }
`;

export const CONFIRM_P2P_TRADE_RECEIVED = gql`
  mutation ConfirmP2pTradeReceived($tradeId: String!, $signedUserTxn: String!, $sponsorTransactions: [JSONString!]!) {
    confirmP2pTradeReceived(tradeId: $tradeId, signedUserTxn: $signedUserTxn, sponsorTransactions: $sponsorTransactions) {
      success
      error
      txid
    }
  }
`;

// Recuperar/cancelar via HTTP GraphQL is disabled. Use WebSocket prepare/submit instead.
// export const PREPARE_P2P_CANCEL = gql`...`;
// export const CANCEL_P2P_TRADE = gql`...`;

// P2P Trade — open dispute (buyer or seller)
export const PREPARE_P2P_OPEN_DISPUTE = gql`
  mutation PrepareP2pOpenDispute($tradeId: String!, $reason: String!) {
    prepareP2pOpenDispute(tradeId: $tradeId, reason: $reason) {
      success
      error
      userTransactions
      sponsorTransactions { txn index }
      groupId
      tradeId
    }
  }
`;

export const SUBMIT_P2P_OPEN_DISPUTE = gql`
  mutation SubmitP2pOpenDispute($tradeId: String!, $signedUserTxn: String!, $sponsorTransactions: [JSONString!]!, $reason: String) {
    submitP2pOpenDispute(tradeId: $tradeId, signedUserTxn: $signedUserTxn, sponsorTransactions: $sponsorTransactions, reason: $reason) {
      success
      error
      txid
    }
  }
`;

// Dispute evidence: request presigned upload URL (PUT to S3)
export const REQUEST_DISPUTE_EVIDENCE_UPLOAD = gql`
  # Dispute opening via HTTP is removed; use WebSocket for open_dispute.
  # RequestDisputeEvidenceUpload remains available.
  mutation RequestDisputeEvidenceUpload($tradeId: ID!, $filename: String, $contentType: String, $sha256: String) {
    requestDisputeEvidenceUpload(tradeId: $tradeId, filename: $filename, contentType: $contentType, sha256: $sha256) {
      success
      error
      upload {
        url
        key
        method
        headers
        fields
        expiresIn
        confioCode
      }
    }
  }
`;

// Dispute evidence: attach uploaded object key to dispute
export const ATTACH_DISPUTE_EVIDENCE = gql`
  mutation AttachDisputeEvidence($tradeId: ID!, $key: String!, $size: Int, $sha256: String, $etag: String) {
    attachDisputeEvidence(tradeId: $tradeId, key: $key, size: $size, sha256: $sha256, etag: $etag) {
      success
      error
      dispute { id }
    }
  }
`;

export const GET_DISPUTE_EVIDENCE_CODE = gql`
  mutation GetDisputeEvidenceCode($tradeId: ID!) {
    getDisputeEvidenceCode(tradeId: $tradeId) {
      success
      error
      confioCode
      expiresAt
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
      transactionHash
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
      signedAmount
      signedSecondaryAmount
    }
  }
`;

// Removed: USDC withdrawals now use WebSocket ws/withdraw_session (prepare + submit)

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

/* Removed legacy conversion execution */
/* export const EXECUTE_PENDING_CONVERSION = gql`
  mutation ExecutePendingConversion($conversionId: ID!, $signedTransactions: String!) {
    executePendingConversion(conversionId: $conversionId, signedTransactions: $signedTransactions) {
      success
      conversion {
        id
        conversionId
        status
        fromTransactionHash
        toTransactionHash
      }
      transactionId
      errors
    }
  }
`; */

/* Removed legacy conversion tx fetch */
/* export const GET_CONVERSION_TRANSACTIONS = gql`
  mutation GetConversionTransactions($conversionId: ID!) {
    getConversionTransactions(conversionId: $conversionId) {
      success
      transactions
      errors
    }
  }
`; */

// Payment contract mutations for seamless sponsored payments to businesses
// Note: Recipient business is determined from JWT context on server side
export const CREATE_SPONSORED_PAYMENT = gql`
  mutation CreateSponsoredPayment(
    $amount: Float!
    $assetType: String
    $paymentId: String
    $note: String
    $createReceipt: Boolean
  ) {
    createSponsoredPayment(
      amount: $amount
      assetType: $assetType
      paymentId: $paymentId
      note: $note
      createReceipt: $createReceipt
    ) {
      success
      error
      transactions
      userSigningIndexes
      groupId
      grossAmount
      netAmount
      feeAmount
      paymentId
    }
  }
`;

export const SUBMIT_SPONSORED_PAYMENT = gql`
  mutation SubmitSponsoredPayment(
    $signedTransactions: JSONString!
    $paymentId: String
  ) {
    submitSponsoredPayment(
      signedTransactions: $signedTransactions
      paymentId: $paymentId
    ) {
      success
      error
      transactionId
      confirmedRound
      netAmount
      feeAmount
    }
  }
`;

export const CREATE_DIRECT_PAYMENT = gql`
  mutation CreateDirectPayment(
    $recipientAddress: String!
    $amount: Float!
    $assetType: String
    $paymentId: String
    $note: String
    $createReceipt: Boolean
  ) {
    createDirectPayment(
      recipientAddress: $recipientAddress
      amount: $amount
      assetType: $assetType
      paymentId: $paymentId
      note: $note
      createReceipt: $createReceipt
    ) {
      success
      error
      transactions
      userSigningIndexes
      groupId
      grossAmount
      netAmount
      feeAmount
      totalTransactionFee
    }
  }
`;

export const CHECK_BUSINESS_OPT_IN = gql`
  mutation CheckBusinessOptIn {
    checkBusinessOptIn {
      needsOptIn
      assets
      optInTransactions
      error
    }
  }
`;

export const COMPLETE_BUSINESS_OPT_IN = gql`
  mutation CompleteBusinessOptIn($txIds: [String!]!) {
    completeBusinessOptIn(txIds: $txIds) {
      success
      error
    }
  }
`;

export const JOIN_PRESALE_WAITLIST = gql`
  mutation JoinPresaleWaitlist {
    joinPresaleWaitlist {
      success
      message
      alreadyJoined
    }
  }
`;
