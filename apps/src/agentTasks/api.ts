// Purchases the assistant makes in a cloud browser (server: agent_tasks/schema.py).
// Kept apart from the shared query files: a server without agent_tasks rejects only these.
import { gql } from '@apollo/client';

import type { CapRule } from './helpers';

const TASK_FIELDS = `
  id
  goal
  site
  status
  reason
  message
  waitUntil
  stage
  kind
  request
  requestButton
  paymentIntentId
  payQr
  payDetails { label value }
  openAccountMethod
  options { title price image cap unit }
  capRule { margin minExtra commaDecimals maxQuantity }
  order { item items { title quantity image } total image address breakdown { label value } }
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

export const ANSWER_AGENT_REQUEST = gql`
  mutation AnswerAgentRequest($id: UUID!, $yes: Boolean!, $what: String) {
    answerAgentRequest(id: $id, yes: $yes, what: $what) { ${RESULT} }
  }
`;

export const ANSWER_AGENT_STEP = gql`
  mutation AnswerAgentStep($id: UUID!, $yes: Boolean!) {
    answerAgentStep(id: $id, yes: $yes) { ${RESULT} }
  }
`;

export const CHOOSE_AGENT_OPTION = gql`
  mutation ChooseAgentOption($id: UUID!, $index: Int!, $cap: String) {
    chooseAgentOption(id: $id, index: $index, cap: $cap) { ${RESULT} }
  }
`;

// One or more products, each with a quantity, confirmed with one tap; `cap` is the top total the button showed.
export const CHOOSE_AGENT_OPTIONS = gql`
  mutation ChooseAgentOptions($id: UUID!, $items: [AgentPickInput!]!, $cap: String) {
    chooseAgentOptions(id: $id, items: $items, cap: $cap) { ${RESULT} }
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

// `cap`: the most it may cost with shipping and taxes; choosing it approves up to that (spec decision 42).
// `unit`: its price as a plain number, from which the top total of several chosen products is worked out.
export type AgentOption = { title: string; price: string; image: string; cap?: string | null; unit?: string | null };
export type AgentOrderItem = { title: string; quantity: number; image: string };
export type AgentOrder = {
  item: string; total: string; image: string; address?: string | null;
  // The products chosen into one cart, with how many of each (empty for one item chosen the older way).
  items?: AgentOrderItem[] | null;
  // What the total is made of (Productos, Envío…): the server checked it adds up to the total.
  breakdown?: { label: string; value: string }[] | null;
};

export type AgentTask = {
  id: string;
  goal: string;
  site: string;
  status: string;
  reason: string;
  message: string;
  waitUntil?: string | null;
  // Where the purchase is, for the card's journey: search | cart | checkout | pay | done.
  stage?: string | null;
  // 'buy' or 'manage' (an order already placed: its state, cancel, return, refund).
  kind?: string | null;
  // The request about an order the person is asked to approve (manage).
  request?: string | null;
  // The store's own button that sends it.
  requestButton?: string | null;
  paymentIntentId?: string | null;
  // The store's own QR the person pays from their bank's app (no Confío payment: QR Bolivia off).
  payQr?: string | null;
  // What the person pays the order with from their bank, as the store's order page writes it.
  payDetails?: { label: string; value: string }[];
  // The local account (LocalAccountApplication methodId) that lets Confío pay the next one.
  openAccountMethod?: string | null;
  options: AgentOption[];
  // How the top total of the chosen products is worked out (while choosing).
  capRule?: CapRule | null;
  order?: AgentOrder | null;
};

export type AgentAnswer = { success?: boolean; errors?: string[]; errorCode?: string | null; task?: AgentTask | null };

export { ACTIVE, FINISHED, taskIdOf, agentTaskNotificationRoute, taskActions, latestCardFor, showCard, cartTop } from './helpers';
