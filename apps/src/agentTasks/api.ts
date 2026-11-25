// Purchases the assistant makes in a cloud browser (server: agent_tasks/schema.py).
// Kept apart from the shared query files: a server without agent_tasks rejects only these.
import { gql } from '@apollo/client';

import type { SmartAccountPreparedBatch } from '../services/smartAccount';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';
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
  notify
  options { title price image cap unit rating reviews }
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

// Sí, avísame / Solo miraba on a purchase stopped because its country's stores cannot be paid yet (no_rail).
export const ANSWER_AGENT_NOTIFY = gql`
  mutation AnswerAgentNotify($id: UUID!, $yes: Boolean!) {
    answerAgentNotify(id: $id, yes: $yes) { ${RESULT} }
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

// A purchase waiting for the person's Cuenta inteligente (reason 'account_wait', spec decisions 38 to 40):
// read only for that card, in its own query, so a server without it fails this one alone.
export const GET_AGENT_ACCOUNT_WAIT = gql`
  query GetAgentAccountWait($id: UUID!) {
    agentAccountWait(id: $id) { code amountUsd until }
  }
`;

// "Ya lo hice: pagar": the account is asked again; nothing is ever paid from the personal wallet.
export const RESUME_AGENT_PAYMENT = gql`
  mutation ResumeAgentPayment($id: UUID!) {
    resumeAgentPayment(id: $id) { ${RESULT} }
  }
`;

// The owner-signed batch the waiting purchase needs (switch purchases on, raise the cap, move money in).
// Its amount is the server's, from the task: never sent from here.
export const PREPARE_AGENT_ACCOUNT_WAIT = gql`
  mutation PrepareAgentAccountWait($id: UUID!) {
    prepareAgentAccountWait(id: $id) { success errorCode errorMessage requestId calls { to valueWei data } notAfter summary }
  }
`;

// code: no_rule | move | cap | topup | renew. amountUsd: what the one action is for ("200.00" cap, "65.00" to move).
export type AgentAccountWait = { code: string; amountUsd?: string | null; until?: string | null };

// A search across stores (server: agent_tasks/offers.py), read only by its own card: a server without it
// fails that card alone, never agentTask.
export const GET_AGENT_OFFERS = gql`
  query GetAgentOffers($id: UUID!) {
    agentOffers(id: $id) { query picked offers { title price image rating reviews store site pay payText } }
  }
`;

// "Comprar aquí": the purchase starts at that offer's store; its own card follows in the chat.
export const BUY_AGENT_OFFER = gql`
  mutation BuyAgentOffer($id: UUID!, $index: Int!) {
    buyAgentOffer(id: $id, index: $index) { success errors errorCode task { id site } }
  }
`;

// `pay`: confio (Confío pays it) | manual (the person pays the store's data) | reference (Venezuela: only when
// the store asks just the reference) | none (Confío does not pay this store yet). `payText` says it in words.
export type AgentOffer = {
  title: string; price: string; image: string; rating: string; reviews: string; store: string; site: string;
  pay: string; payText: string;
};
export type AgentOffers = { query: string; picked?: number | null; offers: AgentOffer[] };

export const FORGET_AGENT_STORE = gql`
  mutation ForgetAgentStore($site: String!) {
    forgetAgentStore(site: $site) { success errors errorCode }
  }
`;

// `cap`: the most it may cost with shipping and taxes; choosing it approves up to that (spec decision 42).
// `unit`: its price as a plain number, from which the top total of several chosen products is worked out.
export type AgentOption = {
  title: string; price: string; image: string; cap?: string | null; unit?: string | null;
  // Stars out of 5 and the review count, as the store writes them; empty when it shows none.
  rating?: string | null; reviews?: string | null;
};
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
  // With reason 'no_rail': '' unanswered, 'yes' (Sí, avísame) or 'no' (Solo miraba).
  notify?: string | null;
  options: AgentOption[];
  // How the top total of the chosen products is worked out (while choosing).
  capRule?: CapRule | null;
  order?: AgentOrder | null;
};

export type AgentAnswer = { success?: boolean; errors?: string[]; errorCode?: string | null; task?: AgentTask | null };

/** prepareAgentAccountWait for the shared signing flow (useSignFlow). Nothing is signed here, so a failure is
 *  definite; a server that predates it says so instead of "check your connection". */
export async function prepareAgentAccountWait(client: { mutate: (options: any) => Promise<any> }, id: string):
Promise<SmartAccountPreparedBatch> {
  const failed = (errorCode: string, errorMessage: string): SmartAccountPreparedBatch => ({
    success: false, errorCode, errorMessage, requestId: null, calls: null, notAfter: null, summary: null,
  });
  try {
    const { data } = await client.mutate({ mutation: PREPARE_AGENT_ACCOUNT_WAIT, variables: { id },
      fetchPolicy: 'no-cache' });
    const out = data?.prepareAgentAccountWait as SmartAccountPreparedBatch | null | undefined;
    if (!out) {
      return failed('no_response', 'No pudimos preparar la operación. No se movió nada. Inténtalo de nuevo.');
    }
    return out;
  } catch (e) {
    if (isSchemaMismatch(e as any)) {
      return failed('unsupported', 'Esta opción todavía no está disponible. No se movió nada.');
    }
    return failed('network', 'No pudimos preparar la operación. No se movió nada. Inténtalo de nuevo.');
  }
}

export { ACTIVE, FINISHED, taskIdOf, agentTaskNotificationRoute, taskActions, latestCardFor, showCard, cartTop } from './helpers';
