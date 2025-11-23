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
      item { itemId status }
      run { id status }
    }
  }
`;

export const SUBMIT_PAYROLL_ITEM_PAYOUT = gql`
  mutation SubmitPayrollItemPayout($payrollItemId: String!, $signedTransaction: String!) {
    submitPayrollItemPayout(payrollItemId: $payrollItemId, signedTransaction: $signedTransaction) {
      success
      errors
      transactionHash
      item { itemId status }
      run { id status }
    }
  }
`;
