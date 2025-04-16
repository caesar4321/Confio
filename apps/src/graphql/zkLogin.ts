import { gql } from '@apollo/client';

export const GENERATE_PROOF = gql`
  mutation GenerateProof($input: GenerateProofInput!) {
    generateProof(input: $input) {
      proof {
        id
        maxEpoch
        firebaseUid
        firebaseProjectId
        createdAt
        isVerified
      }
      success
      errors
    }
  }
`;

export const VERIFY_PROOF = gql`
  mutation VerifyProof($id: ID!) {
    verifyProof(id: $id) {
      success
      errors
    }
  }
`;

export const GET_PROOFS = gql`
  query GetProofs {
    zkLoginProofs {
      id
      maxEpoch
      firebaseUid
      firebaseProjectId
      createdAt
      verifiedAt
      isVerified
    }
  }
`;

export const GET_PROOF = gql`
  query GetProof($id: ID!) {
    zkLoginProof(id: $id) {
      id
      maxEpoch
      firebaseUid
      firebaseProjectId
      createdAt
      verifiedAt
      isVerified
    }
  }
`; 