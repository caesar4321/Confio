import { gql } from '@apollo/client';

// Generate ephemeral key pair through Django
export const GENERATE_EPHEMERAL_KEY = gql`
  mutation GenerateEphemeralKey($expiryHours: Int!) {
    generateEphemeralKey(expiryHours: $expiryHours) {
      ephemeralKeyPair {
        privateKey
        publicKey
        expiryDate
        nonce
        blinder
      }
      success
      error
    }
  }
`;

// Derive Keyless account through Django
export const DERIVE_KEYLESS_ACCOUNT = gql`
  mutation DeriveKeylessAccount(
    $jwt: String!
    $ephemeralKeyPair: EphemeralKeyPairInput!
    $pepper: String
  ) {
    deriveKeylessAccount(
      jwt: $jwt
      ephemeralKeyPair: $ephemeralKeyPair
      pepper: $pepper
    ) {
      keylessAccount {
        address
        publicKey
        jwt
        pepper
      }
      success
      error
    }
  }
`;

// Sign and submit transaction through Django
export const SIGN_AND_SUBMIT_TRANSACTION = gql`
  mutation SignAndSubmitTransaction(
    $jwt: String!
    $ephemeralKeyPair: EphemeralKeyPairInput!
    $transaction: TransactionInput!
    $pepper: String
  ) {
    signAndSubmitTransaction(
      jwt: $jwt
      ephemeralKeyPair: $ephemeralKeyPair
      transaction: $transaction
      pepper: $pepper
    ) {
      transactionHash
      success
      error
    }
  }
`;

// Get account balance through Django
export const GET_KEYLESS_BALANCE = gql`
  query GetKeylessBalance($address: String!) {
    keylessBalance(address: $address) {
      apt
      success
      error
    }
  }
`;