// Cloud-browser shopping tasks (server: agent_tasks/schema.py). Kept apart
// from the shared query files: a server without agent_tasks rejects only these.
import { gql } from '@apollo/client';

const TASK_FIELDS = `
  id
  goal
  site
  status
  reason
  message
  waitUntil
  checkoutHanded
  paymentIntentId
  createdAt
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

export const RESUME_AGENT_TASK = gql`
  mutation ResumeAgentTask($id: UUID!, $view: String) {
    resumeAgentTask(id: $id, view: $view) { success errors errorCode task { ${TASK_FIELDS} } }
  }
`;

export const CANCEL_AGENT_TASK = gql`
  mutation CancelAgentTask($id: UUID!) {
    cancelAgentTask(id: $id) { success errors errorCode task { ${TASK_FIELDS} } }
  }
`;

// A mutation on purpose: the URL controls the remote browser. Never cache,
// log or share it, and ask again each time the screen opens.
export const OPEN_AGENT_LIVE_VIEW = gql`
  mutation OpenAgentLiveView($id: UUID!) {
    openAgentLiveView(id: $id) { success errors errorCode url expiresIn site host pageHost view }
  }
`;

export const FORGET_AGENT_STORE = gql`
  mutation ForgetAgentStore($site: String!) {
    forgetAgentStore(site: $site) { success errors errorCode }
  }
`;

export type AgentTaskStatus =
  | 'queued' | 'working' | 'needs_person' | 'awaiting_code' | 'payment_ready' | 'stopped' | 'cancelled';

export type AgentTask = {
  id: string;
  goal: string;
  site: string;
  status: AgentTaskStatus | string;
  reason: string;
  message: string;
  waitUntil?: string | null;
  checkoutHanded: boolean;
  paymentIntentId?: string | null;
  createdAt: string;
};

export type LiveView = {
  success: boolean;
  errors: string[];
  errorCode?: string | null;
  url?: string | null;
  expiresIn?: number | null;
  site?: string | null;
  host?: string | null;
  pageHost?: string | null;
  /** Names the tab this screen shows: sent back with "Ya terminé", so that tab is the one read. */
  view?: string | null;
};

export {
  ACTIVE, FINISHED, BACK_TO_AGENT, PASTE_REASONS, pastesInChat, taskIdOf, agentTaskNotificationRoute, allowedInLiveView,
  allowedSubframe, timeLeft,
}
  from './helpers';
