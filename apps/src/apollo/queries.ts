import { gql } from '@apollo/client';

export const GET_USER_PROFILE = gql`
  query GetUserProfile {
    me {
      id
      email
      username
      phone_number
      phone_country
      zkLoginProofs {
        id
        isVerified
        createdAt
      }
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

// Telegram Verification Mutations
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
