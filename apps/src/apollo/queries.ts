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
      isOnConfio
      activeAccountId
      activeAccountAlgorandAddress
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
        activeAccountAlgorandAddress
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
      lastLoginAt
      displayName
      avatarLetter
      isEmployee
      employeeRole
      employeePermissions {
        viewBalance
        sendFunds
        acceptPayments
        viewTransactions
        manageEmployees
        viewBusinessAddress
        viewAnalytics
        editBusinessInfo
        manageBankAccounts
        manageP2p
        createInvoices
        manageInvoices
        exportData
      }
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

// zkLogin mutations removed - using Web3Auth mutations from mutations.ts instead

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
  mutation VerifyTelegramCode($phoneNumber: String!, $countryCode: String!, $code: String!) {
    verifyTelegramCode(phoneNumber: $phoneNumber, countryCode: $countryCode, code: $code) {
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

export const UPDATE_ACCOUNT_ALGORAND_ADDRESS = gql`
  mutation UpdateAccountAlgorandAddress($algorandAddress: String!) {
    updateAccountAlgorandAddress(algorandAddress: $algorandAddress) {
      account {
        id
        accountId
        accountType
        accountIndex
      }
      success
      error
      needsOptIn
      optInTransactions
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
        blockchainData
        createdAt
      }
      grossAmount
      netAmount
      feeAmount
      success
      errors
    }
  }
`;

// Note: Send mutations moved to mutations.ts (ALGORAND_SPONSORED_SEND and SUBMIT_SPONSORED_GROUP)
// Old Sui-based mutations have been removed

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


// NEW: Get send transactions with a specific friend
export const GET_SEND_TRANSACTIONS_WITH_FRIEND = gql`
  query GetSendTransactionsWithFriend($friendUserId: ID, $friendPhone: String, $limit: Int) {
    sendTransactionsWithFriend(friendUserId: $friendUserId, friendPhone: $friendPhone, limit: $limit) {
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
      isInvitation
      invitationClaimed
      invitationReverted
      invitationExpiresAt
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
            business {
            id
            name
            category
            address
          }
        }
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
  query GetMyP2POffers {
    myP2pOffers {
      id
      exchangeType
      tokenType
      rate
      minAmount
      maxAmount
      
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
  query GetMyP2PTrades($offset: Int, $limit: Int) {
    myP2pTrades(offset: $offset, limit: $limit) {
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
      buyerType
      sellerType
      buyerDisplayName
      sellerDisplayName
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
      hasRating
    }
  }
`;

// Check on-chain box existence for P2P trade (escrow sanity)
export const GET_P2P_ESCROW_BOX_EXISTS = gql`
  query GetP2PEscrowBoxExists($tradeId: String!) {
    p2pTradeBoxExists(tradeId: $tradeId)
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
    $paymentMethodIds: [ID]
    $terms: String
  ) {
    updateP2pOffer(
      offerId: $offerId
      status: $status
      rate: $rate
      minAmount: $minAmount
      maxAmount: $maxAmount
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
  query GetUserBankAccounts {
    userBankAccounts {
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
      
      # Invitation fields
      isInvitation
      invitationClaimed
      invitationReverted
      invitationExpiresAt
      
      # Conversion-specific fields
      conversionType
      fromAmount
      toAmount
      fromToken
      toToken
      
      # P2P Trade ID for navigation
      p2pTradeId
    }
  }
`;

// Notifications queries
export const GET_NOTIFICATIONS = gql`
  query GetNotifications($first: Int, $after: String, $notificationType: NotificationTypeEnum, $isRead: Boolean) {
    notifications(first: $first, after: $after, notificationType: $notificationType, isRead: $isRead) {
      pageInfo {
        hasNextPage
        endCursor
      }
      totalCount
      unreadCount
      edges {
        node {
          id
          notificationType
          title
          message
          isRead
          createdAt
          data
          relatedObjectType
          relatedObjectId
          actionUrl
          isBroadcast
          broadcastTarget
          account {
            id
            accountType
          }
          business {
            id
            name
          }
          # Optional: Fetch fresh related data if needed
          # Uncomment these fields if you want to fetch fresh data instead of using cached data
          # relatedSendTransaction {
          #   id
          #   amount
          #   tokenType
          #   status
          #   senderDisplayName
          #   recipientDisplayName
          #   createdAt
          # }
          # relatedP2pTrade {
          #   id
          #   cryptoAmount
          #   fiatAmount
          #   status
          # }
        }
      }
    }
  }
`;

export const GET_NOTIFICATION_PREFERENCES = gql`
  query GetNotificationPreferences {
    notificationPreferences {
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
`;

export const GET_UNREAD_NOTIFICATION_COUNT = gql`
  query GetUnreadNotificationCount {
    unreadNotificationCount
  }
`;

export const GET_SEND_TRANSACTION_BY_ID = gql`
  query GetSendTransactionById($id: ID!) {
    sendTransaction(id: $id) {
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
      }
      recipientBusiness {
        id
        name
      }
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
      invitationExpiresAt
    }
  }
`;

// NEW: JWT-context-aware transactions query
export const GET_CURRENT_ACCOUNT_TRANSACTIONS = gql`
  query GetCurrentAccountTransactions($limit: Int, $offset: Int, $tokenTypes: [String]) {
    currentAccountTransactions(limit: $limit, offset: $offset, tokenTypes: $tokenTypes) {
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
      
      # Invitation fields
      isInvitation
      invitationClaimed
      invitationReverted
      invitationExpiresAt
      
      # Conversion-specific fields
      conversionType
      fromAmount
      toAmount
      fromToken
      toToken
      
      # P2P Trade ID for navigation
      p2pTradeId
    }
  }
`;

// Unified transactions with a specific friend
export const GET_UNIFIED_TRANSACTIONS_WITH_FRIEND = gql`
  query GetUnifiedTransactionsWithFriend($friendUserId: ID, $friendPhone: String, $limit: Int, $offset: Int) {
    unifiedTransactionsWithFriend(friendUserId: $friendUserId, friendPhone: $friendPhone, limit: $limit, offset: $offset) {
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
      
      # Invitation fields
      isInvitation
      invitationClaimed
      invitationReverted
      invitationExpiresAt
      
      # Conversion-specific fields
      conversionType
      fromAmount
      toAmount
      fromToken
      toToken
      
      # P2P Trade ID for navigation
      p2pTradeId
    }
  }
`;

// User Query by ID
export const GET_USER_BY_ID = gql`
  query GetUserById($id: ID!) {
    user(id: $id) {
      id
      username
      firstName
      lastName
      phoneNumber
      phoneCountry
      accounts {
        id
        accountType
        accountIndex
        displayName
      }
    }
  }
`;

export const SWITCH_ACCOUNT_TOKEN = gql`
  mutation SwitchAccountToken($accountType: String!, $accountIndex: Int!, $businessId: ID) {
    switchAccountToken(accountType: $accountType, accountIndex: $accountIndex, businessId: $businessId) {
      token
      payload
    }
  }
`;

// Employee queries
export const GET_MY_EMPLOYER_BUSINESSES = gql`
  query GetMyEmployerBusinesses {
    myEmployerBusinesses {
      business {
        id
        name
        category
        description
      }
      employeeRecord {
        id
        role
        isActive
        hiredAt
        shiftStartTime
        shiftEndTime
        dailyTransactionLimit
      }
      role
      permissions
    }
  }
`;

export const GET_BUSINESS_EMPLOYEES = gql`
  query GetBusinessEmployees($businessId: ID!, $includeInactive: Boolean) {
    businessEmployees(businessId: $businessId, includeInactive: $includeInactive) {
      id
      user {
        id
        username
        firstName
        lastName
        phoneNumber
      }
      role
      isActive
      permissions
      effectivePermissions
      isWithinShift
      hiredAt
      shiftStartTime
      shiftEndTime
      dailyTransactionLimit
      notes
    }
  }
`;

export const ADD_BUSINESS_EMPLOYEE = gql`
  mutation AddBusinessEmployee($input: AddBusinessEmployeeInput!) {
    addBusinessEmployee(input: $input) {
      employee {
        id
        user {
          id
          username
          firstName
          lastName
        }
        role
        isActive
        permissions
      }
      success
      errors
    }
  }
`;

export const UPDATE_BUSINESS_EMPLOYEE = gql`
  mutation UpdateBusinessEmployee($input: UpdateBusinessEmployeeInput!) {
    updateBusinessEmployee(input: $input) {
      employee {
        id
        role
        isActive
        permissions
        shiftStartTime
        shiftEndTime
        dailyTransactionLimit
      }
      success
      errors
    }
  }
`;

export const REMOVE_BUSINESS_EMPLOYEE = gql`
  mutation RemoveBusinessEmployee($input: RemoveBusinessEmployeeInput!) {
    removeBusinessEmployee(input: $input) {
      success
      errors
    }
  }
`;

// JWT-context-aware queries for current business (no businessId parameter needed)
export const GET_CURRENT_BUSINESS_EMPLOYEES = gql`
  query GetCurrentBusinessEmployees($includeInactive: Boolean, $first: Int, $after: String) {
    currentBusinessEmployees(includeInactive: $includeInactive, first: $first, after: $after) {
      id
      user {
        id
        username
        firstName
        lastName
        phoneNumber
        phoneCountry
      }
      role
      isActive
      permissions
      effectivePermissions
      isWithinShift
      hiredAt
      shiftStartTime
      shiftEndTime
      dailyTransactionLimit
      notes
    }
  }
`;

export const GET_CURRENT_BUSINESS_INVITATIONS = gql`
  query GetCurrentBusinessInvitations($status: String) {
    currentBusinessInvitations(status: $status) {
      id
      business {
        id
        name
      }
      invitedBy {
        id
        firstName
        lastName
        username
      }
      role
      status
      employeeName
      employeePhone
      employeePhoneCountry
      createdAt
      expiresAt
      invitationCode
    }
  }
`;

export const INVITE_EMPLOYEE = gql`
  mutation InviteEmployee($input: InviteEmployeeInput!) {
    inviteEmployee(input: $input) {
      success
      errors
      invitation {
        id
        invitationCode
        expiresAt
      }
    }
  }
`;

export const CANCEL_INVITATION = gql`
  mutation CancelInvitation($invitationId: ID!) {
    cancelInvitation(invitationId: $invitationId) {
      success
      errors
    }
  }
`;

// Achievement System Queries
export const GET_ACHIEVEMENT_TYPES = gql`
  query GetAchievementTypes($category: String) {
    achievementTypes(category: $category) {
      id
      slug
      name
      description
      category
      iconEmoji
      color
      confioReward
      isRepeatable
      requiresManualReview
      isActive
      displayOrder
      rewardDisplay
      createdAt
      updatedAt
    }
  }
`;

export const GET_USER_ACHIEVEMENTS = gql`
  query GetUserAchievements($status: String) {
    userAchievements(status: $status) {
      id
      user {
        id
        username
        firstName
        lastName
      }
      achievementType {
        id
        slug
        name
        description
        category
        iconEmoji
        color
        confioReward
        rewardDisplay
      }
      status
      earnedAt
      claimedAt
      progressData
      earnedValue
      createdAt
      updatedAt
    }
  }
`;

export const GET_ACHIEVEMENT_LEADERBOARD = gql`
  query GetAchievementLeaderboard($achievementSlug: String) {
    achievementLeaderboard(achievementSlug: $achievementSlug) {
      id
      user {
        id
        username
        firstName
        lastName
      }
      achievementType {
        id
        slug
        name
        description
        iconEmoji
        color
      }
      status
      earnedAt
      earnedValue
    }
  }
`;

export const GET_INFLUENCER_STATS = gql`
  query GetInfluencerStats($referrerIdentifier: String!) {
    influencerStats(referrerIdentifier: $referrerIdentifier) {
      totalReferrals
      activeReferrals
      convertedReferrals
      totalVolume
      totalConfioEarned
      isAmbassadorEligible
    }
  }
`;

export const GET_MY_INFLUENCER_STATS = gql`
  query GetMyInfluencerStats {
    myInfluencerStats {
      totalReferrals
      activeReferrals
      convertedReferrals
      totalVolume
      totalConfioEarned
      isAmbassadorEligible
    }
  }
`;

export const GET_MY_CONFIO_BALANCE = gql`
  query GetMyConfioBalance {
    myConfioBalance {
      id
      totalEarned
      totalLocked
      totalUnlocked
      totalSpent
      nextUnlockDate
      nextUnlockAmount
      createdAt
      updatedAt
    }
  }
`;

export const GET_MY_CONFIO_TRANSACTIONS = gql`
  query GetMyConfioTransactions($limit: Int, $offset: Int) {
    myConfioTransactions(limit: $limit, offset: $offset) {
      id
      transactionType
      amount
      balanceAfter
      source
      description
      createdAt
    }
  }
`;

export const GET_USER_INFLUENCER_REFERRALS = gql`
  query GetUserInfluencerReferrals {
    userInfluencerReferrals {
      id
      referredUser {
        id
        username
        firstName
        lastName
      }
      referrerIdentifier
      influencerUser {
        id
        username
        firstName
        lastName
      }
      status
      firstTransactionAt
      totalTransactionVolume
      referrerConfioAwarded
      refereeConfioAwarded
      rewardClaimedAt
      attributionData
      createdAt
      updatedAt
    }
  }
`;

export const GET_USER_TIKTOK_SHARES = gql`
  query GetUserTikTokShares($status: String) {
    userTiktokShares(status: $status) {
      id
      user {
        id
        username
        firstName
        lastName
      }
      achievement {
        id
        achievementType {
          id
          name
          iconEmoji
        }
        status
      }
      tiktokUrl
      tiktokUsername
      hashtagsUsed
      shareType
      status
      viewCount
      likeCount
      shareCount
      baseConfioReward
      viewBonusConfio
      totalConfioAwarded
      verifiedBy {
        id
        username
      }
      verifiedAt
      verificationNotes
      hasRequiredHashtags
      performanceTier
      createdAt
      updatedAt
    }
  }
`;

// Achievement System Mutations
export const CLAIM_ACHIEVEMENT_REWARD = gql`
  mutation ClaimAchievementReward($achievementId: ID!) {
    claimAchievementReward(achievementId: $achievementId) {
      success
      error
      achievement {
        id
        status
        claimedAt
      }
      confioAwarded
    }
  }
`;

export const CREATE_INFLUENCER_REFERRAL = gql`
  mutation CreateInfluencerReferral($referrerIdentifier: String!, $attributionData: JSONString) {
    createInfluencerReferral(referrerIdentifier: $referrerIdentifier, attributionData: $attributionData) {
      success
      error
      referral {
        id
        referrerIdentifier
        status
        refereeConfioAwarded
        createdAt
      }
    }
  }
`;

export const SUBMIT_TIKTOK_SHARE = gql`
  mutation SubmitTikTokShare(
    $tiktokUrl: String!
    $tiktokUsername: String!
    $hashtagsUsed: [String!]!
    $shareType: String!
    $achievementId: ID
  ) {
    submitTiktokShare(
      tiktokUrl: $tiktokUrl
      tiktokUsername: $tiktokUsername
      hashtagsUsed: $hashtagsUsed
      shareType: $shareType
      achievementId: $achievementId
    ) {
      success
      error
      share {
        id
        tiktokUrl
        status
        shareType
        baseConfioReward
        created_at
      }
    }
  }
`;

export const VERIFY_TIKTOK_SHARE = gql`
  mutation VerifyTikTokShare(
    $shareId: ID!
    $viewCount: Int
    $likeCount: Int
    $shareCount: Int
    $verificationNotes: String
  ) {
    verifyTiktokShare(
      shareId: $shareId
      viewCount: $viewCount
      likeCount: $likeCount
      shareCount: $shareCount
      verificationNotes: $verificationNotes
    ) {
      success
      error
      share {
        id
        status
        viewCount
        likeCount
        shareCount
        totalConfioAwarded
        verifiedAt
      }
      confioAwarded
    }
  }
`;

export const UPDATE_INFLUENCER_STATUS = gql`
  mutation UpdateInfluencerStatus($referrerIdentifier: String!, $newStatus: String!) {
    updateInfluencerStatus(referrerIdentifier: $referrerIdentifier, newStatus: $newStatus) {
      success
      error
      updatedCount
    }
  }
`;

export const CHECK_REFERRAL_STATUS = gql`
  mutation CheckReferralStatus {
    checkReferralStatus {
      canSetReferrer
      timeRemainingHours
      existingReferrer
    }
  }
`;

// Employee invitation queries (from invitee perspective)
export const GET_MY_INVITATIONS = gql`
  query GetMyInvitations {
    myInvitations {
      id
      business {
        id
        name
      }
      invitedBy {
        id
        firstName
        lastName
        username
      }
      role
      status
      message
      invitationCode
      createdAt
      expiresAt
    }
  }
`;

export const ACCEPT_INVITATION = gql`
  mutation AcceptInvitation($invitationCode: String!) {
    acceptInvitation(invitationCode: $invitationCode) {
      success
      errors
      employee {
        id
        business {
          id
          name
        }
        role
        permissions
      }
    }
  }
`;

// Presale Queries
export const GET_PRESALE_STATUS = gql`
  query GetPresaleStatus {
    isPresaleActive
  }
`;

export const GET_ACTIVE_PRESALE = gql`
  query GetActivePresale {
    activePresalePhase {
      phaseNumber
      name
      description
      pricePerToken
      totalRaised
      totalParticipants
      tokensSold
      progressPercentage
      minPurchase
      maxPurchase
      goalAmount
      status
    }
  }
`;

export const GET_ALL_PRESALE_PHASES = gql`
  query GetAllPresalePhases {
    allPresalePhases {
      phaseNumber
      name
      description
      pricePerToken
      totalRaised
      totalParticipants
      tokensSold
      progressPercentage
      minPurchase
      maxPurchase
      goalAmount
      status
      targetAudience
      locationEmoji
      visionPoints
    }
  }
`;

export const PURCHASE_PRESALE_TOKENS = gql`
  mutation PurchasePresaleTokens($cusdAmount: Decimal!) {
    purchasePresaleTokens(cusdAmount: $cusdAmount) {
      success
      message
      purchase {
        id
        confioAmount
        cusdAmount
        status
      }
    }
  }
`;
export const INVITE_RECEIPT_FOR_PHONE = gql`
  query InviteReceiptForPhone($phone: String!, $phoneCountry: String) {
    inviteReceiptForPhone(phone: $phone, phoneCountry: $phoneCountry) {
      exists
      statusCode
      assetId
      amount
      timestamp
    }
  }
`;
