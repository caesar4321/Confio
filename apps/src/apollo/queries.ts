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
      suiAddress
    }
  }
`;

export const VERIFY_TOKEN = gql`
  mutation VerifyToken($firebaseToken: String!, $googleToken: String!) {
    verifyToken(
      firebaseToken: $firebaseToken
      googleToken: $googleToken
    ) {
      success
      error
      details
      firebaseUser {
        uid
        email
        name
        picture
        __typename
      }
      googleTokenData {
        sub
        aud
        iss
        email
        emailVerified
        name
        picture
        __typename
      }
      zkLoginData {
        zkProof
        suiAddress
        ephemeralPublicKey
        maxEpoch
        randomness
        salt
        __typename
      }
      __typename
    }
  }
`;

export const ZKLOGIN = gql`
  mutation ZkLogin($input: ZkLoginInput!) {
    zkLogin(input: $input) {
      zkProof {
        a
        b
        c
        __typename
      }
      suiAddress
      __typename
    }
  }
`; 