// Purchases the assistant makes in a cloud browser (server: agent_tasks/schema.py).
// Kept apart from the shared query files: a server without agent_tasks rejects only these.
import { gql } from '@apollo/client';

const TASK_FIELDS = `
  id
  goal
  site
  status
  reason
  message
  waitUntil
  paymentIntentId
  payQr
  options { title price image }
  order { item total image }
`;

export const GET_AGENT_TASK = gql`
  query GetAgentTask($id: UUID!) {
    agentTask(id: $id) { ${TASK_FIELDS} }
  }
`;

export const GET_AGENT_STORES = gql`
  query GetAgentStores {
    agentStores
  }
`;

const RESULT = `success errors errorCode task { ${TASK_FIELDS} }`;

export const CHOOSE_AGENT_OPTION = gql`
  mutation ChooseAgentOption($id: UUID!, $index: Int!) {
    chooseAgentOption(id: $id, index: $index) { ${RESULT} }
  }
`;

// The person's account at the store: its variables are never logged (apollo/client.ts).
export const SIGN_IN_AGENT_STORE = gql`
  mutation SignInAgentStore($id: UUID!, $identifier: String!, $password: String!) {
    signInAgentStore(id: $id, identifier: $identifier, password: $password) { ${RESULT} }
  }
`;

export const GIVE_AGENT_CODE = gql`
  mutation GiveAgentCode($id: UUID!, $code: String!) {
    giveAgentCode(id: $id, code: $code) { ${RESULT} }
  }
`;

export const APPROVE_AGENT_ORDER = gql`
  mutation ApproveAgentOrder($id: UUID!, $total: String) {
    approveAgentOrder(id: $id, total: $total) { ${RESULT} }
  }
`;

export const CANCEL_AGENT_TASK = gql`
  mutation CancelAgentTask($id: UUID!) {
    cancelAgentTask(id: $id) { ${RESULT} }
  }
`;

export const FORGET_AGENT_STORE = gql`
  mutation ForgetAgentStore($site: String!) {
    forgetAgentStore(site: $site) { success errors errorCode }
  }
`;

export type AgentOption = { title: string; price: string; image: string };
export type AgentOrder = { item: string; total: string; image: string };

export type AgentTask = {
  id: string;
  goal: string;
  site: string;
  status: string;
  reason: string;
  message: string;
  waitUntil?: string | null;
  paymentIntentId?: string | null;
  // The store's own QR the person pays from their bank's app (no Confío payment: QR Bolivia off).
  payQr?: string | null;
  options: AgentOption[];
  order?: AgentOrder | null;
};

export type AgentAnswer = { success?: boolean; errors?: string[]; errorCode?: string | null; task?: AgentTask | null };

export { ACTIVE, FINISHED, taskIdOf, agentTaskNotificationRoute, taskActions, latestCardFor, showCard } from './helpers';
