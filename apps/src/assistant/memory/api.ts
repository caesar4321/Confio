import { gql } from '@apollo/client';

// Own documents: an older server rejects only these. The account is the JWT's, never an argument.
export type MemoryState = {
  openedFor: string;
  available: boolean;
  canRemember: boolean;
  canRecall: boolean;
  factsEnabled: boolean;
  recallEnabled: boolean;
  facts: { id: string; text: string }[];
  quotes: { id: string; text: string; saidAt: string }[];
};

const MEMORY = `
  openedFor available canRemember canRecall factsEnabled recallEnabled
  facts { id text }
  quotes { id text saidAt }
`;

export const GET_MEMORY = gql`
  query GetAssistantMemory {
    assistantMemory { ${MEMORY} }
  }
`;

export const SET_MEMORY = gql`
  mutation SetAssistantMemory($openedFor: String!, $factsEnabled: Boolean, $recallEnabled: Boolean) {
    setAssistantMemory(openedFor: $openedFor, factsEnabled: $factsEnabled, recallEnabled: $recallEnabled) { success error memory { ${MEMORY} } }
  }
`;

export const FORGET_MEMORY = gql`
  mutation ForgetAssistantMemory($factId: ID, $quoteId: ID) {
    forgetAssistantMemory(factId: $factId, quoteId: $quoteId) { success error memory { ${MEMORY} } }
  }
`;

export const WIPE_MEMORY = gql`
  mutation WipeAssistantMemory($openedFor: String!) {
    wipeAssistantMemory(openedFor: $openedFor) { success error memory { ${MEMORY} } }
  }
`;
