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

export const VERIFY_ZKLOGIN_PROOF = gql`
  mutation VerifyZkLoginProof($proofData: String!) {
    verifyZkLoginProof(proofData: $proofData) {
      id
      isVerified
      createdAt
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