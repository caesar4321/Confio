// Cuenta inteligente: the client half of the frozen GraphQL contract
// (smart_account_api.graphql, 2026-11-20; spec docs/designs/cuenta-inteligente-spec.md).
//
// Rules this file exists to keep:
//  - Every query is its OWN document with its own try/catch. GraphQL validates
//    a whole operation at once, so one field an older server does not know
//    would fail everything bundled with it. A failed read is reported as
//    `{ ok: false }`, never as "no data": a screen must be able to tell
//    "you have no account" from "we could not ask".
//  - No account id, and no address, is ever sent as authority. The JWT names
//    the viewer; `designationId` / `inheritedAccountId` / `payoutMethodId` are
//    opaque ids the server issued and re-checks.
//  - Money is decimal strings end to end. Nothing here does float math on it.
//  - Every prepare* mutation returns the exact calls to sign. This client can
//    sign them or not; it cannot substitute calldata. They are signed with the
//    user's PERSONAL (personal_0) key, also when the active context is the
//    Cuenta inteligente, and relayed through the existing sponsored path.

import { gql } from '@apollo/client';
import type { DocumentNode } from 'graphql';
import type { BatchCall } from './evmWallet';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';
import { FACE_STEP_UP_MESSAGE } from './faceStepUp';

// ---------------------------------------------------------------- types

export type SmartPlanKey = 'annual' | 'monthly';
export type SmartFrequency = 'daily' | 'weekly' | 'biweekly' | 'monthly';
export type SmartRuleKind = 'send' | 'payout' | 'buy';
export type SmartMoveDirection = 'in' | 'out';
export type InheritedDestination = 'wallet' | 'smart_account';

export interface SmartAccountCall {
  to: string;
  valueWei: string;
  data: string;
}

export interface SmartAccountPreparedBatch {
  success: boolean;
  errorCode: string | null;
  errorMessage: string | null;
  requestId: string | null;
  calls: SmartAccountCall[] | null;
  notAfter: number | null;
  summary: string[] | null;
}

export interface SmartAccountPlan {
  key: string;
  priceUsd: string;
  periodDays: number;
  nextPriceUsd: string | null;
  nextPriceEffectiveAt: string | null;
  isDefault: boolean;
}

export interface SmartAccountBenefit {
  key: string;
  title: string;
  body: string;
}

export interface SmartAccountOffer {
  available: boolean;
  canSubscribe: boolean;
  blockedReason: string | null;
  plans: SmartAccountPlan[];
  headline: string;
  benefits: SmartAccountBenefit[];
  disclosures: string[];
  beneficiaryEnabled: boolean;
  investingCryptoEnabled: boolean;
  payoutRails: string[];
  dollar: string;
  minFirstDepositUsd: string;
}

export interface SmartAccountAsset {
  key: string;
  kind: string;
  symbol: string;
  name: string;
  address: string;
  units: string;
  decimals: number;
  valueUsd: string | null;
  canPayFee: boolean;
}

export interface SmartAccountRule {
  id: string;
  onchainId: string | null;
  kind: string;
  frequency: string;
  amountUsd: string;
  active: boolean;
  nextRunAt: string | null;
  lastRunAt: string | null;
  lastRunStatus: string | null;
  lastRunMessage: string | null;
  payeeName: string | null;
  payeeHandle: string | null;
  payoutMethodId: string | null;
  payoutLabel: string | null;
  payoutRail: string | null;
  assetKey: string | null;
  assetSymbol: string | null;
  assetName: string | null;
}

export interface SmartAccountCharge {
  id: string;
  chargedAt: string;
  periodStart: string;
  periodEnd: string;
  plan: string;
  feeUsd: string;
  paidWith: string;
  txHash: string | null;
}

export interface SmartAccountClaim {
  state: string;
  initiatedAt: string;
  executableAt: string;
  cancelledAt: string | null;
  executedAt: string | null;
}

export interface SmartAccountBeneficiary {
  designationId: string;
  state: string;
  name: string;
  handle: string | null;
  windowDays: number;
  designatedAt: string;
  acceptedAt: string | null;
  expiresAt: string | null;
  cooldownUntil: string | null;
  claim: SmartAccountClaim | null;
}

export interface SmartAccountBilling {
  status: string;
  plan: string;
  nextPlan: string | null;
  feeUsd: string;
  paidUntil: string | null;
  cancelRequested: boolean;
  returnsAt: string | null;
  shortfallUsd: string | null;
  noticeStartedAt: string | null;
  saleAllowedAt: string | null;
  saleCandidates: string[] | null;
}

export interface SmartAccount {
  status: string;
  contractAddress: string | null;
  totalUsd: string | null;
  dollarsUsd: string | null;
  billing: SmartAccountBilling | null;
  assets: SmartAccountAsset[];
  rules: SmartAccountRule[];
  beneficiary: SmartAccountBeneficiary | null;
  pendingBeneficiary: SmartAccountBeneficiary | null;
  windowOptionsDays: number[];
  defaultWindowDays: number;
  assistantPlus: boolean;
}

export interface InheritedAccount {
  inheritedAccountId: string;
  contractAddress: string;
  fromName: string;
  inheritedAt: string;
  totalUsd: string | null;
  assets: SmartAccountAsset[];
  canMoveToSmartAccount: boolean;
  /** The JWT account_index of this inherited context (smart_N, N >= 1).
   *  Absent on an older server: callers fall back to the received order. */
  accountIndex?: number;
}

export interface BeneficiaryDesignation {
  designationId: string;
  state: string;
  ownerName: string;
  ownerHandle: string | null;
  windowDays: number;
  designatedAt: string;
  acceptedAt: string | null;
  expiresAt: string | null;
  contractAddress: string | null;
  chainName: string | null;
  cooldownUntil: string | null;
  claim: SmartAccountClaim | null;
  canClaim: boolean;
  canExecute: boolean;
}

export interface SmartAccountClaimAlert {
  beneficiaryName: string;
  initiatedAt: string;
  executableAt: string;
}

export interface SmartAccountMoveAsset {
  key: string;
  symbol: string;
  name: string;
  units: string;
  decimals: number;
  valueUsd: string | null;
  included: boolean;
  reason: string | null;
}

export interface SmartAccountMovePreview {
  direction: string;
  assets: SmartAccountMoveAsset[];
  totalUsd: string | null;
  batches: number;
}

export interface SmartAccountPayoutMethod {
  payoutMethodId: string;
  rail: string;
  label: string;
  holderName: string;
  available: boolean;
}

export interface SmartAccountBuyableAsset {
  assetKey: string;
  kind: string;
  symbol: string;
  name: string;
}

export interface SmartPage<T> {
  items: T[];
  hasNextPage: boolean;
  endCursor: string | null;
}

export interface SmartAccountDepositInput {
  assetKey: string;
  /** Token base units as a decimal string, or "max" for the whole balance. */
  units: string;
}

export interface SmartAccountSimpleResult {
  success: boolean;
  errorCode: string | null;
  errorMessage: string | null;
}

/** A read either answered (`data` may legitimately be null) or it did not. */
export type SmartRead<T> = { ok: true; data: T } | { ok: false };

// ------------------------------------------------------------ fragments
// Plain strings, interpolated: each document stays self-contained.

const CLAIM_FIELDS = `
  state
  initiatedAt
  executableAt
  cancelledAt
  executedAt
`;

const ASSET_FIELDS = `
  key
  kind
  symbol
  name
  address
  units
  decimals
  valueUsd
  canPayFee
`;

const BENEFICIARY_FIELDS = `
  designationId
  state
  name
  handle
  windowDays
  designatedAt
  acceptedAt
  expiresAt
  cooldownUntil
  claim { ${CLAIM_FIELDS} }
`;

const PREPARED_FIELDS = `
  success
  errorCode
  errorMessage
  requestId
  calls { to valueWei data }
  notAfter
  summary
`;

// -------------------------------------------------------------- queries

export const SMART_ACCOUNT_OFFER = gql`
  query SmartAccountOffer {
    smartAccountOffer {
      available
      canSubscribe
      blockedReason
      plans { key priceUsd periodDays nextPriceUsd nextPriceEffectiveAt isDefault }
      headline
      benefits { key title body }
      disclosures
      beneficiaryEnabled
      investingCryptoEnabled
      payoutRails
      dollar
      minFirstDepositUsd
    }
  }
`;

export const SMART_ACCOUNT = gql`
  query SmartAccount {
    smartAccount {
      status
      contractAddress
      totalUsd
      dollarsUsd
      billing {
        status
        plan
        nextPlan
        feeUsd
        paidUntil
        cancelRequested
        returnsAt
        shortfallUsd
        noticeStartedAt
        saleAllowedAt
        saleCandidates
      }
      assets { ${ASSET_FIELDS} }
      rules {
        id
        onchainId
        kind
        frequency
        amountUsd
        active
        nextRunAt
        lastRunAt
        lastRunStatus
        lastRunMessage
        payeeName
        payeeHandle
        payoutMethodId
        payoutLabel
        payoutRail
        assetKey
        assetSymbol
        assetName
      }
      beneficiary { ${BENEFICIARY_FIELDS} }
      pendingBeneficiary { ${BENEFICIARY_FIELDS} }
      windowOptionsDays
      defaultWindowDays
      assistantPlus
    }
  }
`;

export const SMART_ACCOUNT_CHARGES = gql`
  query SmartAccountCharges($first: Int, $after: String) {
    smartAccountCharges(first: $first, after: $after) {
      edges {
        cursor
        node { id chargedAt periodStart periodEnd plan feeUsd paidWith txHash }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
`;

export const SMART_ACCOUNT_MOVE_PREVIEW = gql`
  query SmartAccountMovePreview($direction: String!) {
    smartAccountMovePreview(direction: $direction) {
      direction
      assets { key symbol name units decimals valueUsd included reason }
      totalUsd
      batches
    }
  }
`;

export const SMART_ACCOUNT_PAYOUT_METHODS = gql`
  query SmartAccountPayoutMethods {
    smartAccountPayoutMethods { payoutMethodId rail label holderName available }
  }
`;

export const SMART_ACCOUNT_BUYABLE_ASSETS = gql`
  query SmartAccountBuyableAssets($search: String, $first: Int, $after: String) {
    smartAccountBuyableAssets(search: $search, first: $first, after: $after) {
      edges {
        cursor
        node { assetKey kind symbol name }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
`;

export const INHERITED_ACCOUNTS = gql`
  query InheritedAccounts {
    inheritedAccounts {
      inheritedAccountId
      contractAddress
      fromName
      inheritedAt
      totalUsd
      assets { ${ASSET_FIELDS} }
      canMoveToSmartAccount
    }
  }
`;

// SDL additions (2026-11-20). Each is its own document so a server that
// predates the field fails only that read, and the screens fall back.
export const INHERITED_ACCOUNT_INDEXES = gql`
  query InheritedAccountIndexes {
    inheritedAccounts { inheritedAccountId accountIndex }
  }
`;

export const SMART_ACCOUNT_BENEFICIARY_ENABLED = gql`
  query SmartAccountBeneficiaryEnabled {
    smartAccount { beneficiaryEnabled }
  }
`;

export const SMART_ACCOUNT_BENEFICIARY_RISK_DISCLOSURE = gql`
  query SmartAccountBeneficiaryRiskDisclosure {
    smartAccountOffer { beneficiaryRiskDisclosure }
  }
`;

export const BENEFICIARY_DESIGNATIONS = gql`
  query BeneficiaryDesignations {
    beneficiaryDesignations {
      designationId
      state
      ownerName
      ownerHandle
      windowDays
      designatedAt
      acceptedAt
      expiresAt
      contractAddress
      chainName
      cooldownUntil
      claim { ${CLAIM_FIELDS} }
      canClaim
      canExecute
    }
  }
`;

export const SMART_ACCOUNT_CLAIM_ALERT = gql`
  query SmartAccountClaimAlert {
    smartAccountClaimAlert { beneficiaryName initiatedAt executableAt }
  }
`;

// A lighter read for the Home wallet row and the account switcher: status and
// the one number only. Its own document, like every other.
export const SMART_ACCOUNT_ENTRY = gql`
  query SmartAccountEntry {
    smartAccount { status contractAddress totalUsd }
  }
`;

export const SMART_ACCOUNT_OFFER_GATE = gql`
  query SmartAccountOfferGate {
    smartAccountOffer { available canSubscribe }
  }
`;

async function read<T>(
  query: DocumentNode,
  pick: (data: any) => T,
  variables?: Record<string, unknown>,
): Promise<SmartRead<T>> {
  try {
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.query({
      query,
      variables,
      // Money state, and it changes with the account context: never a cache
      // entry written under another token.
      fetchPolicy: 'network-only',
    });
    return { ok: true, data: pick(data) };
  } catch {
    return { ok: false };
  }
}

function page<T>(connection: any): SmartPage<T> {
  const edges: any[] = Array.isArray(connection?.edges) ? connection.edges : [];
  return {
    items: edges.map((e) => e?.node).filter(Boolean) as T[],
    hasNextPage: !!connection?.pageInfo?.hasNextPage,
    endCursor: connection?.pageInfo?.endCursor ?? null,
  };
}

export const fetchSmartAccountOffer = (): Promise<SmartRead<SmartAccountOffer | null>> =>
  read(SMART_ACCOUNT_OFFER, (d) => (d?.smartAccountOffer ?? null) as SmartAccountOffer | null);

export const fetchSmartAccount = (): Promise<SmartRead<SmartAccount | null>> =>
  read(SMART_ACCOUNT, (d) => (d?.smartAccount ?? null) as SmartAccount | null);

export const fetchSmartAccountCharges = (
  first = 20,
  after?: string | null,
): Promise<SmartRead<SmartPage<SmartAccountCharge>>> =>
  read(SMART_ACCOUNT_CHARGES, (d) => page<SmartAccountCharge>(d?.smartAccountCharges), {
    first,
    after: after ?? null,
  });

export const fetchSmartAccountMovePreview = (
  direction: SmartMoveDirection,
): Promise<SmartRead<SmartAccountMovePreview | null>> =>
  read(
    SMART_ACCOUNT_MOVE_PREVIEW,
    (d) => (d?.smartAccountMovePreview ?? null) as SmartAccountMovePreview | null,
    { direction },
  );

export const fetchSmartAccountPayoutMethods = (): Promise<SmartRead<SmartAccountPayoutMethod[]>> =>
  read(SMART_ACCOUNT_PAYOUT_METHODS, (d) => (d?.smartAccountPayoutMethods ?? []) as SmartAccountPayoutMethod[]);

export const fetchSmartAccountBuyableAssets = (params: {
  search?: string;
  first?: number;
  after?: string | null;
} = {}): Promise<SmartRead<SmartPage<SmartAccountBuyableAsset>>> =>
  read(SMART_ACCOUNT_BUYABLE_ASSETS, (d) => page<SmartAccountBuyableAsset>(d?.smartAccountBuyableAssets), {
    search: params.search || null,
    first: params.first ?? 30,
    after: params.after ?? null,
  });

const validIndex = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 1;

/**
 * The inherited accounts, each with its server `accountIndex` when the
 * server has the field. The index comes from a second, isolated read: an
 * older server fails only that one, and the list still loads (callers then
 * order by the date received, the old rule).
 */
export const fetchInheritedAccounts = async (): Promise<SmartRead<InheritedAccount[]>> => {
  const [list, indexes] = await Promise.all([
    read(INHERITED_ACCOUNTS, (d) => (d?.inheritedAccounts ?? []) as InheritedAccount[]),
    read(INHERITED_ACCOUNT_INDEXES, (d) => (d?.inheritedAccounts ?? []) as Array<{
      inheritedAccountId: string; accountIndex: unknown;
    }>),
  ]);
  if (!list.ok) {
    return list;
  }
  const byId = new Map<string, number>();
  if (indexes.ok) {
    indexes.data.forEach((row) => {
      if (row && validIndex(row.accountIndex)) {
        byId.set(row.inheritedAccountId, row.accountIndex);
      }
    });
  }
  return {
    ok: true,
    data: list.data.map((a) => {
      const index = byId.get(a.inheritedAccountId) ?? (validIndex(a.accountIndex) ? a.accountIndex : undefined);
      const rest: InheritedAccount = { ...a };
      delete rest.accountIndex;
      return index === undefined ? rest : { ...rest, accountIndex: index };
    }),
  };
};

/** `SmartAccount.beneficiaryEnabled`; null when there is no account. */
export const fetchSmartAccountBeneficiaryEnabled = (): Promise<SmartRead<boolean | null>> =>
  read(SMART_ACCOUNT_BENEFICIARY_ENABLED, (d) => {
    const v = d?.smartAccount?.beneficiaryEnabled;
    return typeof v === 'boolean' ? v : null;
  });

/** `SmartAccountOffer.beneficiaryRiskDisclosure`: Spanish sentences with
 *  {name} and {days}. An empty list means "use the app's own copy". */
export const fetchBeneficiaryRiskDisclosure = (): Promise<SmartRead<string[]>> =>
  read(SMART_ACCOUNT_BENEFICIARY_RISK_DISCLOSURE, (d) => {
    const lines = d?.smartAccountOffer?.beneficiaryRiskDisclosure;
    return Array.isArray(lines) ? lines.filter((l: unknown): l is string => typeof l === 'string' && l.trim().length > 0) : [];
  });

export const fetchBeneficiaryDesignations = (): Promise<SmartRead<BeneficiaryDesignation[]>> =>
  read(BENEFICIARY_DESIGNATIONS, (d) => (d?.beneficiaryDesignations ?? []) as BeneficiaryDesignation[]);

export const fetchSmartAccountClaimAlert = (): Promise<SmartRead<SmartAccountClaimAlert | null>> =>
  read(SMART_ACCOUNT_CLAIM_ALERT, (d) => (d?.smartAccountClaimAlert ?? null) as SmartAccountClaimAlert | null);

export interface SmartAccountEntry {
  status: string;
  contractAddress: string | null;
  totalUsd: string | null;
}

export const fetchSmartAccountEntry = (): Promise<SmartRead<SmartAccountEntry | null>> =>
  read(SMART_ACCOUNT_ENTRY, (d) => (d?.smartAccount ?? null) as SmartAccountEntry | null);

export const fetchSmartAccountOfferGate = (): Promise<SmartRead<{ available: boolean; canSubscribe: boolean } | null>> =>
  read(SMART_ACCOUNT_OFFER_GATE, (d) => d?.smartAccountOffer ?? null);

// ------------------------------------------------------------ mutations

const PREPARE_GENERIC_ERROR = 'No pudimos preparar la operación. Revisa tu conexión e inténtalo de nuevo.';

function failedPrepare(code: string, message: string = PREPARE_GENERIC_ERROR): SmartAccountPreparedBatch {
  return {
    success: false,
    errorCode: code,
    errorMessage: message,
    requestId: null,
    calls: null,
    notAfter: null,
    summary: null,
  };
}

const UNSUPPORTED_MESSAGE = 'Esta opción todavía no está disponible. No se movió nada.';

/** One prepare* mutation. Nothing is signed here, so any failure is definite. */
async function prepare(
  mutation: DocumentNode,
  field: string,
  variables?: Record<string, unknown>,
): Promise<SmartAccountPreparedBatch> {
  try {
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.mutate({ mutation, variables });
    const out = data?.[field] as SmartAccountPreparedBatch | null | undefined;
    if (!out) {
      return failedPrepare('no_response');
    }
    if (!out.success) {
      return {
        ...failedPrepare(out.errorCode || 'refused', out.errorMessage || PREPARE_GENERIC_ERROR),
        summary: out.summary ?? null,
      };
    }
    return out;
  } catch (e) {
    // A server that predates this mutation: say so, not "check your connection".
    if (isSchemaMismatch(e as any)) {
      return failedPrepare('unsupported', UNSUPPORTED_MESSAGE);
    }
    return failedPrepare('network');
  }
}

const P_SUBSCRIBE = gql`
  mutation PrepareSmartAccountSubscribe($plan: String!, $deposits: [SmartAccountDepositInput!], $disclosuresAccepted: Boolean!) {
    prepareSmartAccountSubscribe(plan: $plan, deposits: $deposits, disclosuresAccepted: $disclosuresAccepted) { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountSubscribe = (
  plan: SmartPlanKey | string,
  deposits: SmartAccountDepositInput[],
  disclosuresAccepted: boolean,
) => prepare(P_SUBSCRIBE, 'prepareSmartAccountSubscribe', { plan, deposits, disclosuresAccepted });

const P_DEPOSIT = gql`
  mutation PrepareSmartAccountDeposit($deposits: [SmartAccountDepositInput!]!) {
    prepareSmartAccountDeposit(deposits: $deposits) { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountDeposit = (deposits: SmartAccountDepositInput[]) =>
  prepare(P_DEPOSIT, 'prepareSmartAccountDeposit', { deposits });

const P_MOVE_EVERYTHING = gql`
  mutation PrepareSmartAccountMoveEverything($direction: String!, $batchIndex: Int) {
    prepareSmartAccountMoveEverything(direction: $direction, batchIndex: $batchIndex) { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountMoveEverything = (direction: SmartMoveDirection, batchIndex = 0) =>
  prepare(P_MOVE_EVERYTHING, 'prepareSmartAccountMoveEverything', { direction, batchIndex });

const P_WITHDRAW = gql`
  mutation PrepareSmartAccountWithdraw($assetKey: String!, $units: String!) {
    prepareSmartAccountWithdraw(assetKey: $assetKey, units: $units) { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountWithdraw = (assetKey: string, units: string) =>
  prepare(P_WITHDRAW, 'prepareSmartAccountWithdraw', { assetKey, units });

const P_PLAN_CHANGE = gql`
  mutation PrepareSmartAccountPlanChange($plan: String!) {
    prepareSmartAccountPlanChange(plan: $plan) { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountPlanChange = (plan: SmartPlanKey | string) =>
  prepare(P_PLAN_CHANGE, 'prepareSmartAccountPlanChange', { plan });

const P_CANCEL = gql`
  mutation PrepareSmartAccountCancel {
    prepareSmartAccountCancel { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountCancel = () => prepare(P_CANCEL, 'prepareSmartAccountCancel');

const P_UNDO_CANCEL = gql`
  mutation PrepareSmartAccountUndoCancel {
    prepareSmartAccountUndoCancel { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountUndoCancel = () => prepare(P_UNDO_CANCEL, 'prepareSmartAccountUndoCancel');

const P_SEND_RULE = gql`
  mutation PrepareSmartAccountSendRule($ruleId: ID, $payeeHandle: String!, $amountUsd: String!, $frequency: String!) {
    prepareSmartAccountSendRule(ruleId: $ruleId, payeeHandle: $payeeHandle, amountUsd: $amountUsd, frequency: $frequency) { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountSendRule = (params: {
  ruleId?: string | null; payeeHandle: string; amountUsd: string; frequency: SmartFrequency | string;
}) => prepare(P_SEND_RULE, 'prepareSmartAccountSendRule', { ...params, ruleId: params.ruleId ?? null });

const P_PAYOUT_RULE = gql`
  mutation PrepareSmartAccountPayoutRule($ruleId: ID, $payoutMethodId: String!, $amountUsd: String!, $frequency: String!) {
    prepareSmartAccountPayoutRule(ruleId: $ruleId, payoutMethodId: $payoutMethodId, amountUsd: $amountUsd, frequency: $frequency) { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountPayoutRule = (params: {
  ruleId?: string | null; payoutMethodId: string; amountUsd: string; frequency: SmartFrequency | string;
}) => prepare(P_PAYOUT_RULE, 'prepareSmartAccountPayoutRule', { ...params, ruleId: params.ruleId ?? null });

const P_BUY_RULE = gql`
  mutation PrepareSmartAccountBuyRule($ruleId: ID, $assetKey: String!, $amountUsd: String!, $frequency: String!) {
    prepareSmartAccountBuyRule(ruleId: $ruleId, assetKey: $assetKey, amountUsd: $amountUsd, frequency: $frequency) { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountBuyRule = (params: {
  ruleId?: string | null; assetKey: string; amountUsd: string; frequency: SmartFrequency | string;
}) => prepare(P_BUY_RULE, 'prepareSmartAccountBuyRule', { ...params, ruleId: params.ruleId ?? null });

const P_CANCEL_RULE = gql`
  mutation PrepareSmartAccountCancelRule($ruleId: ID!) {
    prepareSmartAccountCancelRule(ruleId: $ruleId) { ${PREPARED_FIELDS} }
  }
`;
export const prepareSmartAccountCancelRule = (ruleId: string) =>
  prepare(P_CANCEL_RULE, 'prepareSmartAccountCancelRule', { ruleId });

const P_BENEFICIARY_DESIGNATION = gql`
  mutation PrepareBeneficiaryDesignation($beneficiaryHandle: String!, $windowDays: Int!, $disclosureAccepted: Boolean!) {
    prepareBeneficiaryDesignation(beneficiaryHandle: $beneficiaryHandle, windowDays: $windowDays, disclosureAccepted: $disclosureAccepted) { ${PREPARED_FIELDS} }
  }
`;
export const prepareBeneficiaryDesignation = (
  beneficiaryHandle: string,
  windowDays: number,
  disclosureAccepted: boolean,
) => prepare(P_BENEFICIARY_DESIGNATION, 'prepareBeneficiaryDesignation', {
  beneficiaryHandle, windowDays, disclosureAccepted,
});

const P_BENEFICIARY_WINDOW_CHANGE = gql`
  mutation PrepareBeneficiaryWindowChange($windowDays: Int!) {
    prepareBeneficiaryWindowChange(windowDays: $windowDays) { ${PREPARED_FIELDS} }
  }
`;
/** Re-name the accepted beneficiary with a new window. They must accept
 *  again; until they do, the current window stays. */
export const prepareBeneficiaryWindowChange = (windowDays: number) =>
  prepare(P_BENEFICIARY_WINDOW_CHANGE, 'prepareBeneficiaryWindowChange', { windowDays });

const P_DESIGNATION_WITHDRAWAL = gql`
  mutation PrepareBeneficiaryDesignationWithdrawal {
    prepareBeneficiaryDesignationWithdrawal { ${PREPARED_FIELDS} }
  }
`;
export const prepareBeneficiaryDesignationWithdrawal = () =>
  prepare(P_DESIGNATION_WITHDRAWAL, 'prepareBeneficiaryDesignationWithdrawal');

const P_BENEFICIARY_REMOVAL = gql`
  mutation PrepareBeneficiaryRemoval {
    prepareBeneficiaryRemoval { ${PREPARED_FIELDS} }
  }
`;
export const prepareBeneficiaryRemoval = () => prepare(P_BENEFICIARY_REMOVAL, 'prepareBeneficiaryRemoval');

const P_CLAIM_CANCEL = gql`
  mutation PrepareClaimCancel {
    prepareClaimCancel { ${PREPARED_FIELDS} }
  }
`;
export const prepareClaimCancel = () => prepare(P_CLAIM_CANCEL, 'prepareClaimCancel');

const P_BENEFICIARY_ACCEPTANCE = gql`
  mutation PrepareBeneficiaryAcceptance($designationId: String!) {
    prepareBeneficiaryAcceptance(designationId: $designationId) { ${PREPARED_FIELDS} }
  }
`;
export const prepareBeneficiaryAcceptance = (designationId: string) =>
  prepare(P_BENEFICIARY_ACCEPTANCE, 'prepareBeneficiaryAcceptance', { designationId });

const DECLINE_BENEFICIARY_DESIGNATION = gql`
  mutation DeclineBeneficiaryDesignation($designationId: String!) {
    declineBeneficiaryDesignation(designationId: $designationId) { success errorCode errorMessage }
  }
`;
export const declineBeneficiaryDesignation = async (designationId: string): Promise<SmartAccountSimpleResult> => {
  const failed: SmartAccountSimpleResult = {
    success: false,
    errorCode: 'network',
    errorMessage: 'No pudimos guardar tu respuesta. Inténtalo de nuevo.',
  };
  try {
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.mutate({
      mutation: DECLINE_BENEFICIARY_DESIGNATION,
      variables: { designationId },
    });
    const out = data?.declineBeneficiaryDesignation as SmartAccountSimpleResult | null | undefined;
    if (!out) {
      return failed;
    }
    return out.success ? out : { ...failed, errorCode: out.errorCode || 'refused', errorMessage: out.errorMessage || failed.errorMessage };
  } catch {
    return failed;
  }
};

const P_BENEFICIARY_CLAIM = gql`
  mutation PrepareBeneficiaryClaim($designationId: String!) {
    prepareBeneficiaryClaim(designationId: $designationId) { ${PREPARED_FIELDS} }
  }
`;
export const prepareBeneficiaryClaim = (designationId: string) =>
  prepare(P_BENEFICIARY_CLAIM, 'prepareBeneficiaryClaim', { designationId });

const P_BENEFICIARY_CLAIM_EXECUTE = gql`
  mutation PrepareBeneficiaryClaimExecute($designationId: String!) {
    prepareBeneficiaryClaimExecute(designationId: $designationId) { ${PREPARED_FIELDS} }
  }
`;
export const prepareBeneficiaryClaimExecute = (designationId: string) =>
  prepare(P_BENEFICIARY_CLAIM_EXECUTE, 'prepareBeneficiaryClaimExecute', { designationId });

const P_INHERITED_WITHDRAW = gql`
  mutation PrepareInheritedWithdraw($inheritedAccountId: String!, $assetKeys: [String!], $destination: String!) {
    prepareInheritedWithdraw(inheritedAccountId: $inheritedAccountId, assetKeys: $assetKeys, destination: $destination) { ${PREPARED_FIELDS} }
  }
`;
/** `assetKeys` null = every asset in the account. */
export const prepareInheritedWithdraw = (
  inheritedAccountId: string,
  assetKeys: string[] | null,
  destination: InheritedDestination,
) => prepare(P_INHERITED_WITHDRAW, 'prepareInheritedWithdraw', { inheritedAccountId, assetKeys, destination });

// ------------------------------------------------------- sign and submit

/**
 * What happened to a prepared batch.
 *  - executed: the chain ran it.
 *  - unknown:  it may have been broadcast and we never saw the verdict. NOT a
 *              failure: the UI must never offer a blind retry on it.
 *  - reverted: it mined and changed nothing. Definite; safe to try again.
 *  - not_sent: refused or failed before any broadcast. Definite.
 */
export type SmartSubmitOutcome =
  | { status: 'executed'; txHash: string }
  | { status: 'unknown'; txHash: string | null }
  | { status: 'reverted'; txHash: string | null }
  | { status: 'not_sent'; code: string };

const HEX_ADDRESS = /^0x[0-9a-fA-F]{40}$/;
const HEX_DATA = /^0x([0-9a-fA-F]{2})*$/;

/** The server's calls, typed for signing. Throws on anything malformed: a
 *  batch we cannot read exactly is a batch we do not sign. */
export function toBatchCalls(calls: SmartAccountCall[]): BatchCall[] {
  return calls.map((c) => {
    if (!HEX_ADDRESS.test(c.to) || !HEX_DATA.test(c.data) || !/^\d+$/.test(c.valueWei)) {
      throw new Error('malformed_batch');
    }
    return { to: c.to, valueWei: BigInt(c.valueWei), data: c.data };
  });
}

/**
 * Sign a server-prepared batch with the PERSONAL (personal_0) key and relay
 * it through the existing sponsored path. The signer is fixed here on
 * purpose: a Cuenta inteligente is a contract whose owner is the personal
 * wallet, so the active account context never chooses the key.
 */
export async function signAndSubmitPrepared(prepared: SmartAccountPreparedBatch): Promise<SmartSubmitOutcome> {
  if (!prepared.success) {
    return { status: 'not_sent', code: prepared.errorCode || 'refused' };
  }
  if (!prepared.requestId || !prepared.calls || prepared.calls.length === 0) {
    return { status: 'not_sent', code: 'empty_batch' };
  }
  let calls: BatchCall[];
  try {
    calls = toBatchCalls(prepared.calls);
  } catch {
    return { status: 'not_sent', code: 'malformed_batch' };
  }

  let mods: [
    typeof import('./bscServerRpc'),
    typeof import('./sponsored7702'),
    typeof import('./secureDeterministicWallet'),
    typeof import('./evmWallet'),
  ];
  try {
    // Nothing is signed yet: a module that fails to load is a plain not_sent.
    mods = await Promise.all([
      import('./bscServerRpc'),
      import('./sponsored7702'),
      import('./secureDeterministicWallet'),
      import('./evmWallet'),
    ]);
  } catch {
    return { status: 'not_sent', code: 'not_sent' };
  }
  const [
    { installBscServerTransport },
    { fetchSponsored7702Params, executeSponsoredBatch, SigningWindowClosedError },
    { getActiveEvmWallet },
    { BscRevertedError, isOutcomeUnknown },
  ] = mods;

  try {
    // Chain reads go through our own server, like every other BSC money flow.
    installBscServerTransport();
    const sponsored = await fetchSponsored7702Params();
    if (!sponsored.enabled || !sponsored.delegateAddress) {
      return { status: 'not_sent', code: 'sponsored_rail_unavailable' };
    }
    const wallet = await getActiveEvmWallet({ type: 'personal', index: 0 });
    const result = await executeSponsoredBatch({
      wallet,
      calls,
      delegateAddress: sponsored.delegateAddress,
      requestId: prepared.requestId,
      notAfter: prepared.notAfter ?? undefined,
      // Server-built Cuenta inteligente batch: the server decides its calls.
      ownClaimCancel: false,
    });
    return { status: 'executed', txHash: result.txHash };
  } catch (e) {
    const txHash = typeof (e as any)?.txHash === 'string' ? (e as any).txHash : null;
    // Order matters: "unknown" wins over everything else. Money may have moved.
    if (isOutcomeUnknown(e)) {
      return { status: 'unknown', txHash };
    }
    if (e instanceof BscRevertedError) {
      return { status: 'reverted', txHash };
    }
    if (e instanceof SigningWindowClosedError) {
      return { status: 'not_sent', code: 'signing_window_closed' };
    }
    const message = e instanceof Error ? e.message : '';
    const rejected = /^sponsored batch (?:rejected|failed): (.+)$/.exec(message);
    return { status: 'not_sent', code: rejected ? sponsorErrorCode(rejected[1]) : 'not_sent' };
  }
}

/** The sponsor's outgoing-identity refusal arrives as its sentence, not a
 *  code (security/identity_reuse.MESSAGE raised as the PolicyError code). */
const IDENTITY_RESTRICTION_TEXT = 'Las salidas de tu cuenta están temporalmente restringidas';
export const IDENTITY_RESTRICTED_CODE = 'identity_restricted';

/**
 * The server's refusal as a stable code for the UI. A snake_case code is kept
 * as is; the identity sentence becomes `identity_restricted`; the Confío Face
 * sentence becomes `face_required`; anything else
 * (a node message, free text) is not shown to the person: `not_sent`.
 */
export function sponsorErrorCode(raw: string): string {
  const value = (raw || '').trim();
  if (value.startsWith(IDENTITY_RESTRICTION_TEXT)) {
    return IDENTITY_RESTRICTED_CODE;
  }
  if (value === FACE_STEP_UP_MESSAGE) {
    // relay_policy.face_refusal: the Confío Face grant for this batch is
    // missing or lapsed (useSignFlow's faceStepUp answers it).
    return 'face_required';
  }
  return /^[a-z][a-z0-9_]{0,63}$/.test(value) ? value : 'not_sent';
}

// ---------------------------------------------------------- small helpers

export const SMART_FREQUENCIES: SmartFrequency[] = ['daily', 'weekly', 'biweekly', 'monthly'];

/**
 * The viewer subscribes to an account that is still open: active, or with a
 * cancellation scheduled. An `expired` account (cancelled or unpaid, its
 * assets returned or being returned) is NOT a subscriber for routing: the
 * offer shows its plans and the Inicio row leads to the offer.
 */
export const isSmartAccountOpen = (status: string | null | undefined): boolean =>
  status === 'active' || status === 'cancel_pending';

/** The viewer has an own account record to show, including an expired one. */
export const hasOwnSmartAccount = (status: string | null | undefined): boolean =>
  isSmartAccountOpen(status) || status === 'expired';
