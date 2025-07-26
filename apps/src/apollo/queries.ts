import { gql } from '@apollo/client';

// User Queries
export const GET_ME = gql`
  query GetMe {
    me {
      id
      username
      email
      firstName
      lastName
      phoneCountry
      phoneNumber
      isIdentityVerified
      lastVerifiedDate
      verificationStatus
    }
  }
`;

// Check users by phone numbers
export const CHECK_USERS_BY_PHONES = gql`
  query CheckUsersByPhones($phoneNumbers: [String!]!) {
    checkUsersByPhones(phoneNumbers: $phoneNumbers) {
      phoneNumber
      userId
      username
      firstName
      lastName
      isOnConfio
      activeAccountId
      activeAccountSuiAddress
    }
  }
`;

// Test mutation to create users (only in DEBUG mode)
export const CREATE_TEST_USERS = gql`
  mutation CreateTestUsers($phoneNumbers: [String!]!) {
    createTestUsers(phoneNumbers: $phoneNumbers) {
      success
      error
      createdCount
      usersCreated {
        phoneNumber
        userId
        username
        firstName
        lastName
        isOnConfio
        activeAccountId
        activeAccountSuiAddress
      }
    }
  }
`;

// Business Profile Query
export const GET_BUSINESS_PROFILE = gql`
  query GetBusinessProfile($businessId: ID!) {
    business(id: $businessId) {
      id
      name
      description
      category
      address
      businessRegistrationNumber
      createdAt
      updatedAt
    }
  }
`;

export const GET_USER_ACCOUNTS = gql`
  query GetUserAccounts {
    userAccounts {
      id
      accountType
      accountIndex
      suiAddress
      lastLoginAt
      displayName
      avatarLetter
      business {
        id
        name
        category
        description
        address
        businessRegistrationNumber
        createdAt
        updatedAt
      }
    }
  }
`;

// Country Codes
export const GET_COUNTRY_CODES = gql`
  query GetCountryCodes {
    countryCodes {
      name
      code
      flag
    }
  }
`;

// Business Categories
export const GET_BUSINESS_CATEGORIES = gql`
  query GetBusinessCategories {
    businessCategories {
      id
      name
    }
  }
`;

// Legal Documents
export const GET_LEGAL_DOCUMENT = gql`
  query GetLegalDocument($docType: String!, $language: String) {
    legalDocument(docType: $docType, language: $language) {
      title
      content
      version
      lastUpdated
      language
      isLegallyBinding
    }
  }
`;

// ZKLogin Mutations
export const INITIALIZE_ZKLOGIN = gql`
  mutation InitializeZkLogin($firebaseToken: String!, $providerToken: String!, $provider: String!) {
    initializeZkLogin(firebaseToken: $firebaseToken, providerToken: $providerToken, provider: $provider) {
      maxEpoch
      randomness
      authAccessToken
      authRefreshToken
    }
  }
`;

export const FINALIZE_ZKLOGIN = gql`
  mutation FinalizeZkLogin($input: FinalizeZkLoginInput!) {
    finalizeZkLogin(input: $input) {
      success
      zkProof {
        a
        b
        c
      }
      suiAddress
      error
      isPhoneVerified
    }
  }
`;

// Telegram Verification
export const INITIATE_TELEGRAM_VERIFICATION = gql`
  mutation InitiateTelegramVerification($phoneNumber: String!, $countryCode: String!) {
    initiateTelegramVerification(phoneNumber: $phoneNumber, countryCode: $countryCode) {
      success
      error
    }
  }
`;

export const VERIFY_TELEGRAM_CODE = gql`
  mutation VerifyTelegramCode($requestId: String!, $code: String!) {
    verifyTelegramCode(requestId: $requestId, code: $code) {
      success
      error
    }
  }
`;

// User Profile Mutations
export const UPDATE_PHONE_NUMBER = gql`
  mutation UpdatePhoneNumber($countryCode: String!, $phoneNumber: String!) {
    updatePhoneNumber(countryCode: $countryCode, phoneNumber: $phoneNumber) {
      success
      error
    }
  }
`;

export const UPDATE_USERNAME = gql`
  mutation UpdateUsername($username: String!) {
    updateUsername(username: $username) {
      success
      error
    }
  }
`;

export const UPDATE_USER_PROFILE = gql`
  mutation UpdateUserProfile($firstName: String!, $lastName: String!) {
    updateUserProfile(firstName: $firstName, lastName: $lastName) {
      success
      error
    }
  }
`;

// Business Mutations
export const CREATE_BUSINESS = gql`
  mutation CreateBusiness($name: String!, $description: String, $category: String!, $businessRegistrationNumber: String, $address: String) {
    createBusiness(name: $name, description: $description, category: $category, businessRegistrationNumber: $businessRegistrationNumber, address: $address) {
      business {
        id
        name
        category
        description
        address
        businessRegistrationNumber
        createdAt
        updatedAt
      }
      account {
        id
        accountId
        accountType
        accountIndex
        suiAddress
        business {
          id
          name
          category
        }
      }
      success
      error
    }
  }
`;

export const UPDATE_ACCOUNT_SUI_ADDRESS = gql`
  mutation UpdateAccountSuiAddress($accountId: ID!, $suiAddress: String!) {
    updateAccountSuiAddress(accountId: $accountId, suiAddress: $suiAddress) {
      account {
        id
        accountId
        accountType
        accountIndex
        suiAddress
      }
      success
      error
    }
  }
`;

export const UPDATE_BUSINESS = gql`
  mutation UpdateBusiness($id: ID!, $input: BusinessInput!) {
    updateBusiness(id: $id, input: $input) {
      business {
        id
        name
        category
        description
        address
        businessRegistrationNumber
        createdAt
        updatedAt
      }
      success
      error
    }
  }
`;

// Invoice Mutations
export const CREATE_INVOICE = gql`
  mutation CreateInvoice($input: InvoiceInput!) {
    createInvoice(input: $input) {
      invoice {
        id
        invoiceId
        amount
        tokenType
        description
        status
        expiresAt
        createdAt
        qrCodeData
        isExpired
      }
      success
      errors
    }
  }
`;

export const GET_INVOICE = gql`
  mutation GetInvoice($invoiceId: String!) {
    getInvoice(invoiceId: $invoiceId) {
      invoice {
        id
        invoiceId
        createdByUser {
          id
          username
          firstName
          lastName
        }
        merchantAccount {
          id
          accountType
          accountIndex
          suiAddress
          business {
            id
            name
            category
            address
          }
        }
        amount
        tokenType
        description
        status
        expiresAt
        createdAt
        qrCodeData
        isExpired
      }
      success
      errors
    }
  }
`;

export const PAY_INVOICE = gql`
  mutation PayInvoice($invoiceId: String!, $idempotencyKey: String) {
    payInvoice(invoiceId: $invoiceId, idempotencyKey: $idempotencyKey) {
      invoice {
        id
        invoiceId
        status
        paidAt
      }
      paymentTransaction {
        id
        paymentTransactionId
        amount
        tokenType
        description
        status
        transactionHash
        createdAt
      }
      success
      errors
    }
  }
`;

// Send Transaction Mutations
export const CREATE_SEND_TRANSACTION = gql`
  mutation CreateSendTransaction($input: SendTransactionInput!) {
    createSendTransaction(input: $input) {
      sendTransaction {
        id
        senderUser {
          id
          username
          firstName
          lastName
        }
        recipientUser {
          id
          username
          firstName
          lastName
        }
        senderBusiness {
          id
          name
          category
        }
        recipientBusiness {
          id
          name
          category
        }
        senderType
        recipientType
        senderDisplayName
        recipientDisplayName
        senderAddress
        recipientAddress
        amount
        tokenType
        memo
        status
        transactionHash
        createdAt
      }
      success
      errors
    }
  }
`;

// Queries for send transactions and invoices
export const GET_SEND_TRANSACTIONS = gql`
  query GetSendTransactions {
    sendTransactions {
      id
      senderUser {
        id
        username
        firstName
        lastName
      }
      recipientUser {
        id
        username
        firstName
        lastName
      }
      senderAddress
      recipientAddress
      amount
      tokenType
      memo
      status
      transactionHash
      createdAt
      updatedAt
    }
  }
`;

// NEW: Get send transactions by specific account
export const GET_SEND_TRANSACTIONS_BY_ACCOUNT = gql`
  query GetSendTransactionsByAccount($accountType: String!, $accountIndex: Int!, $limit: Int) {
    sendTransactionsByAccount(accountType: $accountType, accountIndex: $accountIndex, limit: $limit) {
      id
      senderUser {
        id
        username
        firstName
        lastName
      }
      recipientUser {
        id
        username
        firstName
        lastName
      }
      senderBusiness {
        id
        name
        category
      }
      recipientBusiness {
        id
        name
        category
      }
      senderType
      recipientType
      senderDisplayName
      recipientDisplayName
      senderPhone
      recipientPhone
      senderAddress
      recipientAddress
      amount
      tokenType
      memo
      status
      transactionHash
      createdAt
      updatedAt
    }
  }
`;

// NEW: Get send transactions with a specific friend
export const GET_SEND_TRANSACTIONS_WITH_FRIEND = gql`
  query GetSendTransactionsWithFriend($friendUserId: ID!, $limit: Int) {
    sendTransactionsWithFriend(friendUserId: $friendUserId, limit: $limit) {
      id
      senderUser {
        id
        username
        firstName
        lastName
      }
      recipientUser {
        id
        username
        firstName
        lastName
      }
      senderBusiness {
        id
        name
        category
      }
      recipientBusiness {
        id
        name
        category
      }
      senderType
      recipientType
      senderDisplayName
      recipientDisplayName
      senderPhone
      recipientPhone
      senderAddress
      recipientAddress
      amount
      tokenType
      memo
      status
      transactionHash
      createdAt
      updatedAt
    }
  }
`;

// NEW: Get payment transactions by specific account
export const GET_PAYMENT_TRANSACTIONS_BY_ACCOUNT = gql`
  query GetPaymentTransactionsByAccount($accountType: String!, $accountIndex: Int!, $limit: Int) {
    paymentTransactionsByAccount(accountType: $accountType, accountIndex: $accountIndex, limit: $limit) {
      id
      paymentTransactionId
      payerUser {
        id
        username
        firstName
        lastName
      }
      merchantAccountUser {
        id
        username
        firstName
        lastName
      }
      payerBusiness {
        id
        name
        category
      }
      merchantBusiness {
        id
        name
        category
      }
      payerType
      merchantType
      payerDisplayName
      merchantDisplayName
      payerPhone
      payerAddress
      merchantAddress
      amount
      tokenType
      description
      status
      transactionHash
      createdAt
      updatedAt
      invoice {
        id
        invoiceId
        description
      }
    }
  }
`;

// NEW: Get payment transactions with a specific friend
export const GET_PAYMENT_TRANSACTIONS_WITH_FRIEND = gql`
  query GetPaymentTransactionsWithFriend($friendUserId: ID!, $limit: Int) {
    paymentTransactionsWithFriend(friendUserId: $friendUserId, limit: $limit) {
      id
      paymentTransactionId
      payerUser {
        id
        username
        firstName
        lastName
      }
      merchantAccountUser {
        id
        username
        firstName
        lastName
      }
      payerBusiness {
        id
        name
        category
      }
      merchantBusiness {
        id
        name
        category
      }
      payerType
      merchantType
      payerDisplayName
      merchantDisplayName
      payerPhone
      payerAddress
      merchantAddress
      amount
      tokenType
      description
      status
      transactionHash
      createdAt
      updatedAt
      invoice {
        id
        invoiceId
        description
      }
    }
  }
`;

export const GET_ACCOUNT_BALANCE = gql`
  query GetAccountBalance($tokenType: String!) {
    accountBalance(tokenType: $tokenType)
  }
`;

export const GET_INVOICES = gql`
  query GetInvoices {
    invoices {
      id
      invoiceId
      amount
      tokenType
      description
      status
      paidByUser {
        id
        username
        firstName
        lastName
      }
      paidAt
      expiresAt
      createdAt
      updatedAt
      isExpired
      merchantAccountUser {
        id
        username
        firstName
        lastName
      }
      merchantAccount {
        id
        accountType
        accountIndex
        suiAddress
        business {
          id
          name
          category
          address
        }
      }
      paymentTransactions {
        id
        paymentTransactionId
        payerUser {
          id
          username
          firstName
          lastName
        }
        payerAccount {
          id
          accountType
          accountIndex
          suiAddress
          business {
            id
            name
            category
            address
          }
        }
        createdByUser {
          id
          username
          firstName
          lastName
        }
        merchantAccount {
          id
          accountType
          accountIndex
          suiAddress
          business {
            id
            name
            category
            address
          }
        }
        payerAddress
        merchantAddress
        amount
        tokenType
        description
        status
        transactionHash
        createdAt
        updatedAt
      }
    }
  }
`;

// P2P Exchange Queries
export const GET_P2P_OFFERS = gql`
  query GetP2POffers($exchangeType: String, $tokenType: String, $paymentMethod: String, $countryCode: String, $favoritesOnly: Boolean) {
    p2pOffers(exchangeType: $exchangeType, tokenType: $tokenType, paymentMethod: $paymentMethod, countryCode: $countryCode, favoritesOnly: $favoritesOnly) {
      id
      user {
        id
        username
        firstName
        lastName
      }
      offerUser {
        id
        username
        firstName
        lastName
      }
      offerBusiness {
        id
        name
        category
      }
      exchangeType
      tokenType
      rate
      minAmount
      maxAmount
      availableAmount
      countryCode
      currencyCode
      paymentMethods {
        id
        name
        displayName
        icon
        providerType
        bank {
          id
          name
          country {
            id
            code
            name
            flagEmoji
          }
        }
      }
      terms
      responseTimeMinutes
      status
      userStats {
        totalTrades
        completedTrades
        successRate
        avgResponseTime
        isVerified
        lastSeenOnline
        avgRating
      }
      isFavorite
      createdAt
    }
  }
`;

export const GET_MY_P2P_OFFERS = gql`
  query GetMyP2POffers($accountId: String) {
    myP2pOffers(accountId: $accountId) {
      id
      exchangeType
      tokenType
      rate
      minAmount
      maxAmount
      availableAmount
      countryCode
      currencyCode
      paymentMethods {
        id
        name
        displayName
        icon
        providerType
        bank {
          id
          name
          country {
            id
            code
            name
            flagEmoji
          }
        }
      }
      terms
      responseTimeMinutes
      status
      createdAt
      offerType
      offerDisplayName
      offerUser {
        id
        firstName
        lastName
      }
      offerBusiness {
        id
        name
      }
    }
  }
`;

export const GET_MY_P2P_TRADES = gql`
  query GetMyP2PTrades($accountId: String, $offset: Int, $limit: Int) {
    myP2pTrades(accountId: $accountId, offset: $offset, limit: $limit) {
      trades {
      id
      offer {
        id
        exchangeType
        tokenType
        user {
          id
          username
          firstName
          lastName
        }
        account {
          id
          accountType
          displayName
          business {
            id
            name
            category
          }
        }
        offerUser {
          id
          username
          firstName
          lastName
        }
        offerBusiness {
          id
          name
          category
        }
        userStats {
          totalTrades
          completedTrades
          successRate
          avgResponseTime
          isVerified
          lastSeenOnline
          avgRating
        }
      }
      # NEW: Direct relationship fields
      buyerUser {
        id
        username
        firstName
        lastName
      }
      buyerBusiness {
        id
        name
        category
      }
      sellerUser {
        id
        username
        firstName
        lastName
      }
      sellerBusiness {
        id
        name
        category
      }
      # NEW: Computed helper fields
      buyerType
      sellerType
      buyerDisplayName
      sellerDisplayName
      # OLD: Keep for backward compatibility during transition
      buyer {
        id
        username
        firstName
        lastName
      }
      seller {
        id
        username
        firstName
        lastName
      }
      buyerAccount {
        id
        accountType
        displayName
        business {
          id
          name
          category
        }
      }
      sellerAccount {
        id
        accountType
        displayName
        business {
          id
          name
          category
        }
      }
      cryptoAmount
      fiatAmount
      rateUsed
      paymentMethod {
        id
        name
        displayName
        icon
        isActive
        providerType
        bank {
          id
          name
          country {
            id
            code
            name
            flagEmoji
          }
        }
      }
      status
      expiresAt
      paymentReference
      paymentNotes
      cryptoTransactionHash
      completedAt
      createdAt
      countryCode
      currencyCode
      hasRating
      buyerStats {
        totalTrades
        completedTrades
        successRate
        avgResponseTime
        isVerified
        lastSeenOnline
        avgRating
      }
      sellerStats {
        totalTrades
        completedTrades
        successRate
        avgResponseTime
        isVerified
        lastSeenOnline
        avgRating
      }
      }
      totalCount
      hasMore
      offset
      limit
      activeCount
    }
  }
`;

export const GET_P2P_TRADE = gql`
  query GetP2PTrade($id: ID!) {
    p2pTrade(id: $id) {
      id
      offer {
        id
        exchangeType
        tokenType
        countryCode
        currencyCode
        rate
        user {
          id
          username
          firstName
          lastName
        }
        offerUser {
          id
          username
          firstName
          lastName
        }
        offerBusiness {
          id
          name
          category
        }
        userStats {
          totalTrades
          completedTrades
          successRate
          avgResponseTime
          isVerified
          lastSeenOnline
          avgRating
        }
      }
      buyer {
        id
        username
        firstName
        lastName
      }
      seller {
        id
        username
        firstName
        lastName
      }
      cryptoAmount
      fiatAmount
      rateUsed
      paymentMethod {
        id
        name
        displayName
        icon
        isActive
        providerType
        bank {
          id
          name
          country {
            id
            code
            name
            flagEmoji
          }
        }
      }
      status
      expiresAt
      paymentReference
      paymentNotes
      cryptoTransactionHash
      completedAt
      createdAt
      countryCode
      currencyCode
      confirmations {
        id
        confirmationType
        confirmerType
        confirmerDisplayName
        reference
        notes
        proofImageUrl
        createdAt
      }
      buyerStats {
        totalTrades
        completedTrades
        successRate
        avgResponseTime
        isVerified
        lastSeenOnline
        avgRating
      }
      sellerStats {
        totalTrades
        completedTrades
        successRate
        avgResponseTime
        isVerified
        lastSeenOnline
        avgRating
      }
      escrow {
        id
        escrowAmount
        tokenType
        isEscrowed
        isReleased
        escrowedAt
        releasedAt
      }
    }
  }
`;

export const GET_P2P_TRADE_MESSAGES = gql`
  query GetP2PTradeMessages($tradeId: ID!) {
    p2pTradeMessages(tradeId: $tradeId) {
      id
      sender {
        id
        username
        firstName
        lastName
      }
      messageType
      content
      attachmentUrl
      attachmentType
      isRead
      readAt
      createdAt
    }
  }
`;

export const GET_P2P_PAYMENT_METHODS = gql`
  query GetP2PPaymentMethods($countryCode: String) {
    p2pPaymentMethods(countryCode: $countryCode) {
      id
      name
      displayName
      providerType
      icon
      requiresPhone
      requiresEmail
      requiresAccountNumber
      isActive
      bank {
        id
        name
        country {
          id
          code
          name
          flagEmoji
          requiresIdentification
          identificationName
          identificationFormat
        }
      }
      country {
        id
        code
        name
        flagEmoji
        requiresIdentification
        identificationName
        identificationFormat
      }
    }
  }
`;

// P2P Exchange Mutations
export const CREATE_P2P_OFFER = gql`
  mutation CreateP2POffer($input: CreateP2POfferInput!) {
    createP2pOffer(input: $input) {
      offer {
        id
        exchangeType
        tokenType
        rate
        minAmount
        maxAmount
        availableAmount
        status
        createdAt
      }
      success
      errors
    }
  }
`;

export const UPDATE_P2P_OFFER = gql`
  mutation UpdateP2POffer(
    $offerId: ID!
    $status: String
    $rate: Float
    $minAmount: Float
    $maxAmount: Float
    $availableAmount: Float
    $paymentMethodIds: [ID]
    $terms: String
  ) {
    updateP2pOffer(
      offerId: $offerId
      status: $status
      rate: $rate
      minAmount: $minAmount
      maxAmount: $maxAmount
      availableAmount: $availableAmount
      paymentMethodIds: $paymentMethodIds
      terms: $terms
    ) {
      offer {
        id
        exchangeType
        tokenType
        rate
        minAmount
        maxAmount
        availableAmount
        status
        terms
        paymentMethods {
          id
          name
          displayName
        }
        createdAt
      }
      success
      errors
    }
  }
`;

export const CREATE_P2P_TRADE = gql`
  mutation CreateP2PTrade($input: CreateP2PTradeInput!) {
    createP2pTrade(input: $input) {
      trade {
        id
        offer {
          id
          exchangeType
          tokenType
          user {
            id
            username
            firstName
            lastName
          }
        }
        buyer {
          id
          username
          firstName
          lastName
        }
        seller {
          id
          username
          firstName
          lastName
        }
        cryptoAmount
        fiatAmount
        rateUsed
        status
        expiresAt
        createdAt
        countryCode
        currencyCode
      }
      success
      errors
    }
  }
`;

export const UPDATE_P2P_TRADE_STATUS = gql`
  mutation UpdateP2PTradeStatus($input: UpdateP2PTradeStatusInput!) {
    updateP2pTradeStatus(input: $input) {
      trade {
        id
        status
        paymentReference
        paymentNotes
        completedAt
      }
      success
      errors
    }
  }
`;

export const CONFIRM_P2P_TRADE_STEP = gql`
  mutation ConfirmP2PTradeStep($input: ConfirmP2PTradeStepInput!) {
    confirmP2pTradeStep(input: $input) {
      confirmation {
        id
        confirmationType
        reference
        notes
        createdAt
      }
      trade {
        id
        status
        escrow {
          id
          escrowAmount
          tokenType
          isEscrowed
          isReleased
          escrowedAt
          releasedAt
        }
      }
      success
      errors
    }
  }
`;

export const SEND_P2P_MESSAGE = gql`
  mutation SendP2PMessage($input: SendP2PMessageInput!) {
    sendP2pMessage(input: $input) {
      message {
        id
        sender {
          id
          username
          firstName
          lastName
        }
        messageType
        content
        attachmentUrl
        attachmentType
        createdAt
      }
      success
      errors
    }
  }
`;

export const RATE_P2P_TRADE = gql`
  mutation RateP2PTrade($input: RateP2PTradeInput!) {
    rateP2pTrade(input: $input) {
      rating {
        id
        trade {
          id
          status
        }
        overallRating
        communicationRating
        speedRating
        reliabilityRating
        comment
        tags
        ratedAt
      }
      trade {
        id
        status
        hasRating
      }
      success
      errors
    }
  }
`;

export const DISPUTE_P2P_TRADE = gql`
  mutation DisputeP2PTrade($tradeId: ID!, $reason: String!) {
    disputeP2pTrade(tradeId: $tradeId, reason: $reason) {
      trade {
        id
        status
      }
      success
      errors
    }
  }
`;

export const TOGGLE_FAVORITE_TRADER = gql`
  mutation ToggleFavoriteTrader($traderUserId: ID, $traderBusinessId: ID, $note: String) {
    toggleFavoriteTrader(traderUserId: $traderUserId, traderBusinessId: $traderBusinessId, note: $note) {
      success
      isFavorite
      message
    }
  }
`;

// Admin dispute resolution mutations
export const RESOLVE_DISPUTE = gql`
  mutation ResolveDispute($disputeId: ID!, $resolutionType: String!, $resolutionNotes: String, $resolutionAmount: Decimal) {
    resolveDispute(disputeId: $disputeId, resolutionType: $resolutionType, resolutionNotes: $resolutionNotes, resolutionAmount: $resolutionAmount) {
      dispute {
        id
        status
        resolutionType
        resolutionNotes
        resolvedAt
        resolvedBy {
          id
          username
        }
      }
      trade {
        id
        status
        completedAt
      }
      success
      errors
    }
  }
`;

export const ESCALATE_DISPUTE = gql`
  mutation EscalateDispute($disputeId: ID!, $escalationNotes: String) {
    escalateDispute(disputeId: $disputeId, escalationNotes: $escalationNotes) {
      dispute {
        id
        status
        priority
        adminNotes
      }
      success
      errors
    }
  }
`;

export const ADD_DISPUTE_EVIDENCE = gql`
  mutation AddDisputeEvidence($disputeId: ID!, $evidenceType: String!, $content: String!, $evidenceUrls: [String]) {
    addDisputeEvidence(disputeId: $disputeId, evidenceType: $evidenceType, content: $content, evidenceUrls: $evidenceUrls) {
      dispute {
        id
        adminNotes
        evidenceUrls
      }
      success
      errors
    }
  }
`;

// Query to get dispute details for admin
export const GET_DISPUTE_DETAILS = gql`
  query GetDisputeDetails($disputeId: ID!) {
    dispute(id: $disputeId) {
      id
      trade {
        id
        buyerUser {
          id
          username
          firstName
          lastName
        }
        sellerUser {
          id
          username
          firstName
          lastName
        }
        buyerBusiness {
          id
          name
        }
        sellerBusiness {
          id
          name
        }
        cryptoAmount
        fiatAmount
        currencyCode
        status
        createdAt
      }
      initiatorUser {
        id
        username
        firstName
        lastName
      }
      initiatorBusiness {
        id
        name
      }
      reason
      status
      priority
      resolutionType
      resolutionAmount
      resolutionNotes
      adminNotes
      evidenceUrls
      resolvedBy {
        id
        username
      }
      openedAt
      resolvedAt
      lastUpdated
    }
  }
`;

// P2P Exchange Subscriptions
export const TRADE_CHAT_MESSAGE_SUBSCRIPTION = gql`
  subscription TradeChatMessage($tradeId: ID!) {
    tradeChatMessage(tradeId: $tradeId) {
      tradeId
      message {
        id
        sender {
          id
          username
          firstName
          lastName
          type
          businessName
          businessId
        }
        content
        messageType
        createdAt
        isRead
      }
    }
  }
`;

// Exchange Rates Queries
export const GET_CURRENT_EXCHANGE_RATE = gql`
  query GetCurrentExchangeRate($sourceCurrency: String, $targetCurrency: String, $rateType: String) {
    currentExchangeRate(sourceCurrency: $sourceCurrency, targetCurrency: $targetCurrency, rateType: $rateType)
  }
`;

export const GET_EXCHANGE_RATE_WITH_FALLBACK = gql`
  query GetExchangeRateWithFallback($sourceCurrency: String, $targetCurrency: String) {
    exchangeRateWithFallback(sourceCurrency: $sourceCurrency, targetCurrency: $targetCurrency)
  }
`;

export const GET_EXCHANGE_RATES = gql`
  query GetExchangeRates($sourceCurrency: String, $targetCurrency: String, $rateType: String, $limit: Int) {
    exchangeRates(sourceCurrency: $sourceCurrency, targetCurrency: $targetCurrency, rateType: $rateType, limit: $limit) {
      id
      sourceCurrency
      targetCurrency
      rate
      rateType
      source
      fetchedAt
      isActive
    }
  }
`;

export const REFRESH_EXCHANGE_RATES = gql`
  mutation RefreshExchangeRates {
    refreshExchangeRates {
      success
      message
      sources
    }
  }
`;

export const TRADE_STATUS_SUBSCRIPTION = gql`
  subscription TradeStatus($tradeId: ID!) {
    tradeStatusUpdate(tradeId: $tradeId) {
      tradeId
      status
      updatedBy
      trade {
        id
        status
        cryptoAmount
        fiatAmount
        rateUsed
      }
    }
  }
`;

export const TYPING_INDICATOR_SUBSCRIPTION = gql`
  subscription TypingIndicator($tradeId: ID!) {
    typingIndicator(tradeId: $tradeId) {
      tradeId
      userId
      username
      isTyping
    }
  }
`;

// Bank Info Queries
export const GET_COUNTRIES = gql`
  query GetCountries($isActive: Boolean) {
    countries(isActive: $isActive) {
      id
      code
      name
      flagEmoji
      currencyCode
      currencySymbol
      requiresIdentification
      identificationName
      identificationFormat
      accountNumberLength
      supportsPhonePayments
      isActive
      displayOrder
    }
  }
`;

export const GET_BANKS = gql`
  query GetBanks($countryCode: String) {
    banks(countryCode: $countryCode) {
      id
      code
      name
      shortName
      country {
        id
        code
        name
        flagEmoji
      }
      supportsChecking
      supportsSavings
      supportsPayroll
      isActive
      displayOrder
      accountTypeChoices
    }
  }
`;

export const GET_USER_BANK_ACCOUNTS = gql`
  query GetUserBankAccounts($accountId: ID) {
    userBankAccounts(accountId: $accountId) {
      id
      account {
        id
        accountId
        displayName
        accountType
      }
      paymentMethod {
        id
        name
        displayName
        providerType
        icon
        requiresPhone
        requiresEmail
        requiresAccountNumber
        bank {
          id
          name
          shortName
          country {
            id
            code
            name
            flagEmoji
            requiresIdentification
            identificationName
          }
        }
        country {
          id
          code
          name
          flagEmoji
          requiresIdentification
          identificationName
        }
      }
      country {
        id
        code
        name
        flagEmoji
        requiresIdentification
        identificationName
      }
      bank {
        id
        name
        shortName
      }
      accountHolderName
      accountNumber
      maskedAccountNumber
      accountType
      identificationNumber
      phoneNumber
      email
      username
      isDefault
      isPublic
      isVerified
      verifiedAt
      fullBankName
      summaryText
      requiresIdentification
      identificationLabel
      paymentDetails
      createdAt
      updatedAt
    }
  }
`;

export const GET_BANK_INFO = gql`
  query GetBankInfo($id: ID!) {
    bankInfo(id: $id) {
      id
      account {
        id
        accountId
        displayName
        accountType
      }
      country {
        id
        code
        name
        flagEmoji
        requiresIdentification
        identificationName
        identificationFormat
      }
      bank {
        id
        name
        shortName
      }
      accountHolderName
      accountNumber
      maskedAccountNumber
      accountType
      identificationNumber
      phoneNumber
      email
      isDefault
      isPublic
      isVerified
      verifiedAt
      fullBankName
      summaryText
      requiresIdentification
      identificationLabel
      paymentDetails
      createdAt
      updatedAt
    }
  }
`;

// Bank Info Mutations
export const CREATE_BANK_INFO = gql`
  mutation CreateBankInfo(
    $accountId: ID!
    $paymentMethodId: ID!
    $accountHolderName: String!
    $accountNumber: String
    $phoneNumber: String
    $email: String
    $username: String
    $accountType: String
    $identificationNumber: String
    $isDefault: Boolean
  ) {
    createBankInfo(
      accountId: $accountId
      paymentMethodId: $paymentMethodId
      accountHolderName: $accountHolderName
      accountNumber: $accountNumber
      phoneNumber: $phoneNumber
      email: $email
      username: $username
      accountType: $accountType
      identificationNumber: $identificationNumber
      isDefault: $isDefault
    ) {
      success
      error
      bankInfo {
        id
        accountHolderName
        accountNumber
        accountType
        identificationNumber
        isDefault
        bank {
          id
          name
          country {
            id
            code
            name
            flagEmoji
            requiresIdentification
            identificationName
          }
        }
        country {
          id
          code
          name
          flagEmoji
          requiresIdentification
          identificationName
        }
      }
    }
  }
`;

export const UPDATE_BANK_INFO = gql`
  mutation UpdateBankInfo(
    $bankInfoId: ID!
    $paymentMethodId: ID!
    $accountHolderName: String!
    $accountNumber: String
    $phoneNumber: String
    $email: String
    $username: String
    $accountType: String
    $identificationNumber: String
    $isDefault: Boolean
  ) {
    updateBankInfo(
      bankInfoId: $bankInfoId
      paymentMethodId: $paymentMethodId
      accountHolderName: $accountHolderName
      accountNumber: $accountNumber
      phoneNumber: $phoneNumber
      email: $email
      username: $username
      accountType: $accountType
      identificationNumber: $identificationNumber
      isDefault: $isDefault
    ) {
      success
      error
      bankInfo {
        id
        accountHolderName
        accountNumber
        phoneNumber
        email
        username
        accountType
        identificationNumber
        isDefault
        paymentMethod {
          id
          displayName
          providerType
          icon
          requiresPhone
          requiresEmail
          requiresAccountNumber
          bank {
            id
            name
            country {
              id
              code
              name
              flagEmoji
              requiresIdentification
              identificationName
            }
          }
        }
      }
    }
  }
`;

export const DELETE_BANK_INFO = gql`
  mutation DeleteBankInfo($bankInfoId: ID!) {
    deleteBankInfo(bankInfoId: $bankInfoId) {
      success
      error
    }
  }
`;

export const SET_DEFAULT_BANK_INFO = gql`
  mutation SetDefaultBankInfo($bankInfoId: ID!) {
    setDefaultBankInfo(bankInfoId: $bankInfoId) {
      success
      error
      bankInfo {
        id
        isDefault
        summaryText
      }
    }
  }
`;

// NEW: Unified transactions query using database view
export const GET_UNIFIED_TRANSACTIONS = gql`
  query GetUnifiedTransactions($accountType: String!, $accountIndex: Int!, $limit: Int, $offset: Int, $tokenTypes: [String]) {
    unifiedTransactions(accountType: $accountType, accountIndex: $accountIndex, limit: $limit, offset: $offset, tokenTypes: $tokenTypes) {
      id
      transactionType
      createdAt
      updatedAt
      amount
      tokenType
      status
      transactionHash
      errorMessage
      
      # Computed fields from user perspective
      direction
      displayAmount
      displayCounterparty
      displayDescription
      
      # Original transaction data
      senderUser {
        id
        username
        firstName
        lastName
      }
      senderBusiness {
        id
        name
        category
      }
      senderType
      senderDisplayName
      senderPhone
      senderAddress
      
      counterpartyUser {
        id
        username
        firstName
        lastName
      }
      counterpartyBusiness {
        id
        name
        category
      }
      counterpartyType
      counterpartyDisplayName
      counterpartyPhone
      counterpartyAddress
      
      description
      invoiceId
      paymentTransactionId
    }
  }
`;
