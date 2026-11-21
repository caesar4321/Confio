// Confío IA+ (spec decision 34): open a Cuenta inteligente rule proposal.
//
// The chip only names the assistant message; the steps come from the
// server (assistantRuleProposal) and become the rule screen's prefill.
// They are data, never authority: every field stays editable, the screen's
// own prepare re-validates everything on the server, and nothing changes
// until the owner signs (with Confío Face where the rule pays someone).
// A proposal of several steps (a target split: one buy rule per asset) is
// signed one screen at a time; each screen hands the rest on (`next`).
// Each step carries its proposal tag (the message id and the step's
// stepIndex) to the prepare, so the server can skip steps already signed when
// the chip is opened again; a fully signed plan opens the rules list with the
// server's own sentence instead of an empty form.
import { Alert } from 'react-native';
import { navigationRef } from '../navigation/RootNavigation';
import type { MainStackParamList } from '../types/navigation';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';
import { GET_ASSISTANT_RULE_PROPOSAL, GET_ASSISTANT_RULE_PROPOSAL_LEGACY, type AssistantRuleStep } from './api';

export type RuleEditParams = NonNullable<MainStackParamList['SmartAccountRuleEdit']>;
type Prefill = NonNullable<RuleEditParams['prefill']>;

const KINDS = new Set(['send', 'payout', 'buy']);
const FREQUENCIES = new Set(['daily', 'weekly', 'biweekly', 'monthly']);
const MAX_STEPS = 8;

const str = (v: unknown, max = 128): string | undefined =>
  typeof v === 'string' && v.trim() && v.length <= max ? v.trim() : undefined;

/** The step's proposal tag; none without a message id or a stepIndex (an
 *  older server), so nothing unset is ever sent. */
function tagOf(step: AssistantRuleStep, messageId?: string | null): Pick<RuleEditParams, 'proposalMessageId' | 'proposalStep'> {
  const id = str(messageId ?? undefined, 64);
  const index = step.stepIndex;
  return id && typeof index === 'number' && Number.isInteger(index) && index >= 0
    ? { proposalMessageId: id, proposalStep: index }
    : {};
}

/** One server step as rule-screen params; null when it is not usable. */
export function stepToParams(step: AssistantRuleStep, messageId?: string | null): RuleEditParams | null {
  if (!step) {
    return null;
  }
  // Only the three actions this screen knows; anything else (an unknown or
  // missing action from a newer server) opens the rules list instead.
  if (step.action !== 'create' && step.action !== 'update' && step.action !== 'cancel') {
    return null;
  }
  const ruleId = str(step.ruleId, 64);
  const tag = tagOf(step, messageId);
  if (step.action === 'cancel') {
    // Stopping needs only the rule: any kind, a card rule (decision 35) too.
    return ruleId ? { ruleId, stop: true, proposal: str(step.sentence, 400), ...tag } : null;
  }
  if (!KINDS.has(step.kind)) {
    return null;
  }
  const kind = step.kind as 'send' | 'payout' | 'buy';
  if (step.action === 'update' && !ruleId) {
    return null;
  }
  const amount = str(step.amountUsd, 16);
  const prefill: Prefill = {
    amountUsd: amount && /^\d+(\.\d{1,2})?$/.test(amount) ? amount : undefined,
    frequency: step.frequency && FREQUENCIES.has(step.frequency) ? (step.frequency as Prefill['frequency']) : undefined,
    firstRunAt: str(step.firstRunAt, 40),
    payeeHandle: str(step.payeeHandle, 64),
    payeeName: str(step.payeeName, 80),
    payoutMethodId: str(step.payoutMethodId, 64),
    assetKey: str(step.assetKey, 64),
    assetName: str(step.assetName, 80),
  };
  return {
    ...(ruleId && step.action === 'update' ? { ruleId } : { kind }),
    prefill,
    proposal: str(step.sentence, 400),
    ...tag,
  };
}

/** The steps as a chain of rule-screen params (the first carries the rest). */
export function proposalParams(steps: AssistantRuleStep[], messageId?: string | null): RuleEditParams | null {
  const usable = (steps || []).slice(0, MAX_STEPS).map((step) => stepToParams(step, messageId)).filter((p): p is RuleEditParams => p !== null);
  if (!usable.length) {
    return null;
  }
  const [first, ...rest] = usable;
  return rest.length ? { ...first, next: rest } : first;
}

function goRules() {
  (navigationRef as any).navigate('Main', { screen: 'SmartAccountRules' });
}

/** The proposal, with its progress where the server has it. A server that
 *  predates the progress fields rejects the query's shape: ask the old one. */
async function fetchProposal(messageId: string) {
  const { apolloClient } = await import('../apollo/client');
  const ask = (query: typeof GET_ASSISTANT_RULE_PROPOSAL) => apolloClient.query({
    query, variables: { messageId }, fetchPolicy: 'network-only',
  });
  try {
    return (await ask(GET_ASSISTANT_RULE_PROPOSAL)).data?.assistantRuleProposal;
  } catch (e) {
    if (!isSchemaMismatch(e as any)) {
      throw e;
    }
    return (await ask(GET_ASSISTANT_RULE_PROPOSAL_LEGACY)).data?.assistantRuleProposal;
  }
}

/** Fetch the proposal on `messageId` and open its first step; anything
 *  unreadable (an older server, an expired proposal) opens the rules list. */
export async function openRuleProposal(messageId?: string | null): Promise<boolean> {
  if (!navigationRef.isReady()) {
    return false;
  }
  if (!messageId) {
    goRules();
    return true;
  }
  try {
    const proposal = await fetchProposal(messageId);
    const steps: AssistantRuleStep[] = proposal?.steps ?? [];
    const message = typeof proposal?.message === 'string' ? proposal.message.trim() : '';
    // Every step already signed (or the server could not check which): its
    // sentence, then the rules list, never an empty form.
    if (proposal && !proposal.expired && message && (proposal.done === true || steps.length === 0)) {
      Alert.alert('Tu plan', message);
      goRules();
      return true;
    }
    const params = proposal && !proposal.expired ? proposalParams(steps, messageId) : null;
    if (!params) {
      goRules();
      return true;
    }
    (navigationRef as any).navigate('Main', { screen: 'SmartAccountRuleEdit', params });
  } catch {
    goRules();
  }
  return true;
}
