import { gql } from '@apollo/client';

export const GENERATE_APP_OPT_IN = gql`
  mutation GenerateAppOptIn($appId: String) {
    generateAppOptInTransaction(appId: $appId) {
      success
      error
      alreadyOptedIn
      userTransaction
      sponsorTransaction
      groupId
      appId
    }
  }
`;

export const SUBMIT_SPONSORED_GROUP = gql`
  mutation SubmitSponsoredGroup($signedUserTxn: String!, $signedSponsorTxn: String) {
    submitSponsoredGroup(signedUserTxn: $signedUserTxn, signedSponsorTxn: $signedSponsorTxn) {
      success
      error
      transactionId
      confirmedRound
      feesSaved
    }
  }
`;

// Legacy mutations (kept for backward compatibility)
export const OPT_IN_TO_CUSD_APP = gql`
  mutation OptInToCUSDApp {
    optInToCusdApp {
      success
      errors
      transactionToSign
    }
  }
`;

export const EXECUTE_CUSD_APP_OPT_IN = gql`
  mutation ExecuteCUSDAppOptIn($signedTransaction: String!) {
    executeCusdAppOptIn(signedTransaction: $signedTransaction) {
      success
      transactionId
      errors
    }
  }
`;
