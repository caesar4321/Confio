import { gql } from '@apollo/client';

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