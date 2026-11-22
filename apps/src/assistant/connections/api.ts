import { gql } from '@apollo/client';

export type GmailState =
  | 'soon' | 'request' | 'full' | 'left' | 'waiting' | 'waiting_full' | 'invited' | 'connected' | 'reconnect' | 'paused';

export type Connections = {
  gmail: GmailState;
  gmailAnswered: boolean;
  googleEmail: string | null;
  suggestedEmail: string | null;
  calendar: 'soon' | 'waiting';
  calendarAnswered: boolean;
};

// Own documents: an older server rejects only these, and the card just doesn't show.
export const GET_CONNECTIONS = gql`
  query GetAssistantMailConnections {
    assistantMailConnections { gmail gmailAnswered googleEmail suggestedEmail calendar calendarAnswered }
  }
`;

export const ANSWER_CONNECTION = gql`
  mutation AnswerAssistantMailConnection($feature: String!, $wants: Boolean!, $googleEmail: String) {
    answerAssistantMailConnection(feature: $feature, wants: $wants, googleEmail: $googleEmail) { success error }
  }
`;
