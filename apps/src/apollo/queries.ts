import { gql } from '@apollo/client';

export const GET_USER_PROFILE = gql`
  query GetUserProfile {
    me {
      id
      email
      username
      firstName
      lastName
      phoneNumber
      phoneCountry
      isIdentityVerified
      lastVerifiedDate
      verificationStatus
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

export const UPDATE_USER_PROFILE = gql`
  mutation UpdateUserProfile($firstName: String!, $lastName: String!) {
    updateUserProfile(firstName: $firstName, lastName: $lastName) {
      success
      error
      user {
        id
        email
        username
        firstName
        lastName
        phoneNumber
        phoneCountry
      }
    }
  }
`;

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
      user {
        id
        username
      }
    }
  }
`;



export const GET_USER_VERIFICATIONS = gql`
  query GetUserVerifications($userId: ID) {
    userVerifications(userId: $userId) {
      id
      verifiedFirstName
      verifiedLastName
      verifiedDateOfBirth
      verifiedNationality
      verifiedAddress
      verifiedCity
      verifiedState
      verifiedCountry
      verifiedPostalCode
      documentType
      documentNumber
      documentIssuingCountry
      documentExpiryDate
      status
      verifiedAt
      rejectedReason
      createdAt
    }
  }
`;

export const SUBMIT_IDENTITY_VERIFICATION = gql`
  mutation SubmitIdentityVerification(
    $verifiedFirstName: String!
    $verifiedLastName: String!
    $verifiedDateOfBirth: Date!
    $verifiedNationality: String!
    $verifiedAddress: String!
    $verifiedCity: String!
    $verifiedState: String!
    $verifiedCountry: String!
    $verifiedPostalCode: String
    $documentType: String!
    $documentNumber: String!
    $documentIssuingCountry: String!
    $documentExpiryDate: Date
    $documentFrontImage: String!
    $documentBackImage: String
    $selfieWithDocument: String!
  ) {
    submitIdentityVerification(
      verifiedFirstName: $verifiedFirstName
      verifiedLastName: $verifiedLastName
      verifiedDateOfBirth: $verifiedDateOfBirth
      verifiedNationality: $verifiedNationality
      verifiedAddress: $verifiedAddress
      verifiedCity: $verifiedCity
      verifiedState: $verifiedState
      verifiedCountry: $verifiedCountry
      verifiedPostalCode: $verifiedPostalCode
      documentType: $documentType
      documentNumber: $documentNumber
      documentIssuingCountry: $documentIssuingCountry
      documentExpiryDate: $documentExpiryDate
      documentFrontImage: $documentFrontImage
      documentBackImage: $documentBackImage
      selfieWithDocument: $selfieWithDocument
    ) {
      success
      error
      verification {
        id
        status
        createdAt
      }
    }
  }
`;

export const APPROVE_IDENTITY_VERIFICATION = gql`
  mutation ApproveIdentityVerification($verificationId: ID!) {
    approveIdentityVerification(verificationId: $verificationId) {
      success
      error
      verification {
        id
        status
        verifiedAt
      }
    }
  }
`;

export const REJECT_IDENTITY_VERIFICATION = gql`
  mutation RejectIdentityVerification($verificationId: ID!, $reason: String!) {
    rejectIdentityVerification(verificationId: $verificationId, reason: $reason) {
      success
      error
      verification {
        id
        status
        rejectedReason
      }
    }
  }
`;
