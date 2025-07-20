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
        merchantUser {
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
  mutation PayInvoice($invoiceId: String!) {
    payInvoice(invoiceId: $invoiceId) {
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
      merchantUser {
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
        merchantUser {
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
