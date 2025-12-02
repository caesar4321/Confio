import { gql } from '@apollo/client';

export const CREATE_PAYROLL_RECIPIENT = gql`
  mutation CreatePayrollRecipient($recipientUserId: ID!, $recipientAccountId: ID!, $displayName: String) {
    createPayrollRecipient(
      recipientUserId: $recipientUserId,
      recipientAccountId: $recipientAccountId,
      displayName: $displayName
    ) {
      success
      errors
      recipient {
        id
        displayName
        recipientUser { id firstName lastName username }
        recipientAccount { id accountType accountIndex }
      }
    }
  }
`;

export const DELETE_PAYROLL_RECIPIENT = gql`
  mutation DeletePayrollRecipient($recipientId: ID!) {
    deletePayrollRecipient(recipientId: $recipientId) {
      success
      errors
    }
  }
`;

export const PREPARE_PAYROLL_ITEM_PAYOUT = gql`
  mutation PreparePayrollItemPayout($payrollItemId: String!, $note: String) {
    preparePayrollItemPayout(payrollItemId: $payrollItemId, note: $note) {
      success
      errors
      transactions
      unsignedTransactionB64
      sponsorTransaction
      item { itemId status }
      run { id status }
    }
  }
`;

export const SUBMIT_PAYROLL_ITEM_PAYOUT = gql`
  mutation SubmitPayrollItemPayout($payrollItemId: String!, $signedTransaction: String!, $sponsorSignature: String) {
    submitPayrollItemPayout(payrollItemId: $payrollItemId, signedTransaction: $signedTransaction, sponsorSignature: $sponsorSignature) {
      success
      errors
      transactionHash
      item { itemId status }
      run { id status }
    }
  }
`;

export const PREPARE_PAYROLL_VAULT_FUNDING = gql`
  mutation PreparePayrollVaultFunding($amount: Float!) {
    preparePayrollVaultFunding(amount: $amount) {
      success
      errors
      unsignedTransactions
      sponsorAppCall
      groupId
      amount
    }
  }
`;

export const SUBMIT_PAYROLL_VAULT_FUNDING = gql`
  mutation SubmitPayrollVaultFunding($signedTransactions: [String!]!, $sponsorAppCall: String) {
    submitPayrollVaultFunding(signedTransactions: $signedTransactions, sponsorAppCall: $sponsorAppCall) {
      success
      errors
      transactionHash
    }
  }
`;

export const SET_BUSINESS_DELEGATES_BY_EMPLOYEE = gql`
  mutation SetBusinessDelegatesByEmployee(
    $businessAccount: String!
    $addEmployeeIds: [ID!]!
    $removeEmployeeIds: [ID!]!
    $signedTransaction: String
  ) {
    setBusinessDelegatesByEmployee(
      businessAccount: $businessAccount
      addEmployeeIds: $addEmployeeIds
      removeEmployeeIds: $removeEmployeeIds
      signedTransaction: $signedTransaction
    ) {
      success
      errors
      unsignedTransactionB64
      transactionHash
    }
  }
`;
