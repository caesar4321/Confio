import { gql } from '@apollo/client';

// Own documents, all named *AssistantMail*: an older server rejects only these,
// and both request logs redact on the name.
// 2: reads beyond bills, keeps a one-line summary, and reads Google Calendar.
export const MAIL_CONSENT_VERSION = 2;

export type MailNeed = {
  id: string;
  kind: string;
  dueDate: string | null;
  amount: string | null;
  currency: string | null;
  summary: string | null;
};
export type MailEvent = { title: string; day: string; startsAt: string | null; allDay: boolean };
export type MailSource = { handle: string; sender: string; subject: string; sentAt: string };
export type MailDraft = {
  id: string | null;
  sender: string | null;
  to: string;
  subject: string;
  body: string;
  isReply: boolean;
  replyToDiffers: boolean;
  canSend: boolean;
  displayHash: string;
};
export type MailState = {
  available: boolean;
  connected: boolean;
  needsReconnect: boolean;
  canSend: boolean;
  canCalendar: boolean;
  consentOutdated: boolean;
  email: string | null;
  needs: MailNeed[];
};

// Copy is written here, never by the model.
export const NEED_LABELS: Record<string, string> = {
  payment: 'Parece un pago pendiente',
  ticket: 'Parece un pasaje o una entrada',
  trip: 'Parece un viaje',
  deadline: 'Parece un vencimiento',
  reply: 'Parece que esperan tu respuesta',
  appointment: 'Parece una cita o una reunión',
  delivery: 'Parece una entrega',
  money: 'Parece dinero que recibiste o vas a recibir',
};

const DRAFT = 'id sender to subject body isReply replyToDiffers canSend displayHash';
const SOURCE = 'handle sender subject sentAt';

export const GET_MAIL = gql`
  query GetAssistantMail {
    assistantMail {
      available connected needsReconnect canSend canCalendar consentOutdated email
      needs { id kind dueDate amount currency summary }
    }
  }
`;

export const START_CONNECT = gql`
  mutation StartAssistantMailConnect($consentVersion: Int!) {
    startAssistantMailConnect(consentVersion: $consentVersion) { success error authUrl verifier }
  }
`;

export const COMPLETE_CONNECT = gql`
  mutation CompleteAssistantMailConnect($code: String!, $state: String!, $verifier: String!) {
    completeAssistantMailConnect(code: $code, state: $state, verifier: $verifier) { success error canSend }
  }
`;

export const DISCONNECT = gql`
  mutation DisconnectAssistantMail {
    disconnectAssistantMail { success error revoked }
  }
`;

export const ASK = gql`
  mutation AskAssistantMail($question: String!) {
    askAssistantMail(question: $question) { success error errorCode answer sources { ${SOURCE} } }
  }
`;

export const SHOW_NEED = gql`
  mutation ShowAssistantMailNeed($id: ID!) {
    showAssistantMailNeed(id: $id) { success error errorCode source { ${SOURCE} } }
  }
`;

// Read from Google for this one answer: the server keeps nothing from the calendar.
export const SHOW_AGENDA = gql`
  mutation ShowAssistantMailAgenda {
    showAssistantMailAgenda { success errorCode events { title day startsAt allDay } }
  }
`;

export const DISMISS_NEED = gql`
  mutation DismissAssistantMailNeed($id: ID!) {
    dismissAssistantMailNeed(id: $id) { success error }
  }
`;

export const DRAFT_MAIL = gql`
  mutation DraftAssistantMail($instructions: String!, $to: String, $source: String) {
    draftAssistantMail(instructions: $instructions, to: $to, source: $source) { success error errorCode draft { ${DRAFT} } }
  }
`;

export const UPDATE_DRAFT = gql`
  mutation UpdateAssistantMailDraft($id: ID!, $to: String!, $subject: String!, $body: String!) {
    updateAssistantMailDraft(id: $id, to: $to, subject: $subject, body: $body) { success error errorCode draft { ${DRAFT} } }
  }
`;

export const SEND_DRAFT = gql`
  mutation SendAssistantMailDraft($id: ID!, $displayHash: String!) {
    sendAssistantMailDraft(id: $id, displayHash: $displayHash) { success error errorCode }
  }
`;
