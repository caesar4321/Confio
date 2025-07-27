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