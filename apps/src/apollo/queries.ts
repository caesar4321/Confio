import { gql } from '@apollo/client';

export const GET_USER_PROFILE = gql`
  query GetUserProfile {
    me {
      id
      email
      username
      zkLoginProofs {
        id
        isVerified
        createdAt
      }
    }
  }
`;

export const INITIALIZE_ZKLOGIN = gql`
  mutation InitializeZkLogin($firebaseToken: String!, $providerToken: String!, $provider: String!) {
    initializeZkLogin(firebaseToken: $firebaseToken, providerToken: $providerToken, provider: $provider) {
      maxEpoch
      randomness
      salt
    }
  }
`;

export const FINALIZE_ZKLOGIN = gql`
  mutation FinalizeZkLogin($input: FinalizeZkLoginInput!) {
    finalizeZkLogin(input: $input) {
      zkProof {
        a
        b
        c
      }
      headerBase64
      issBase64Details
      suiAddress
    }
  }
`;

