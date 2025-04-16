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