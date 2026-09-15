import {Alert} from 'react-native';
import {gql} from '@apollo/client';

// Local money: Enviar a banco o billetera / Recibir por cuenta local.
//
// These operations are deliberately their OWN documents, never merged into the
// shared account queries: a field an older server does not know fails the whole
// document, and here that failure stays inside the local-money screens.
//
// The user never sees a provider. Every rail below is server-evaluated (flags,
// verified KYC, eligibility policy); phone country only orders rows.

export type LocalMethodStatus = 'live' | 'needs_verification' | 'needs_document' | 'unavailable';
export type LocalPairStatus =
  | 'none'
  | 'active'
  | 'provisioning'
  | 'awaiting_payment'
  | 'rejected'
  | 'suspended'
  | 'closed'
  | 'failed';
export type LocalVerification = 'verified' | 'pending' | 'unverified' | 'not_found';

export interface LocalMethod {
  id: string;
  direction: 'send' | 'receive';
  country: string;
  asset: string;
  title: string;
  subtitle: string;
  status: LocalMethodStatus;
  reason: string;
  accountStatus: LocalPairStatus;
  /** For 'needs_document': ISO3 issuing country ('' = any) and Didit type codes. */
  documentCountry: string;
  documentTypes: string[];
}

export interface LocalDestination {
  id: string;
  methodId: string;
  label: string;
  holderName: string;
  holderDocument: string;
  institution: string;
  verification: LocalVerification;
  country: string;
  asset: string;
}

export interface LocalPayoutQuote {
  sourceAmount: string;
  targetAmount: string;
  minimumTarget: string;
  rate: string;
  asset: string;
  expiresAt: string;
}

export interface LocalDepositQuote {
  sourceAmount: string;
  asset: string;
  targetAmount: string;
  minimumFxOutput: string;
  minimumWalletOutput: string;
  rate: string;
  expiresAt: string;
}

export interface LocalLimits {
  known: boolean;
  hasAccount: boolean;
  limit: string | null;
  used: string | null;
  available: string | null;
  resetsAt: string;
  perTransferMax: string | null; // null: no per-transfer cap
  nearLimit: boolean;
}

export interface LocalReceiveAccount {
  methodId: string;
  status: LocalPairStatus;
  localAccountId: string | null;
  cryptoAccountId: string | null;
  country: string;
  asset: string;
  instructionKind: string;
  value: string;
  holderName: string;
  institution: string;
  receiveSameName: string;
  receiveThirdParty: string;
}

export interface LocalDeposit {
  internalId: string;
  asset: string;
  amount: string;
  occurredAt: string;
  held: boolean;
  heldReason: string;
}

export interface LocalJourney {
  internalId: string;
  direction: 'to_bank' | 'to_wallet';
  stage: string;
  failureCode: string;
  destinationSummary: string;
  localAsset: string;
  payoutAmount: string | null;
  minimumFxOutput: string;
  minimumWalletOutput: string | null;
  bridgeFundingMode: string | null;
  createdAt: string;
}

export const LOCAL_MONEY_METHODS = gql`
  query LocalMoneyMethods($direction: String!) {
    localMoneyMethods(direction: $direction) {
      id
      direction
      country
      asset
      title
      subtitle
      status
      reason
      accountStatus
      documentCountry
      documentTypes
    }
  }
`;

export const LOCAL_MONEY_LIMITS = gql`
  query LocalMoneyLimits {
    localMoneyLimits {
      known
      hasAccount
      limit
      used
      available
      resetsAt
      perTransferMax
      nearLimit
    }
  }
`;

/** Only the dollar account's deposit instruction is read from here. */
export const LOCAL_MONEY_ACCOUNTS = gql`
  query LocalMoneyAccounts {
    myPaymentAccounts {
      internalId
      provider
      asset
      country
      status
      fundingInstructions {
        internalId
        kind
        status
      }
    }
  }
`;

export const LOCAL_SAVED_DESTINATIONS = gql`
  query LocalSavedDestinations($methodId: String!) {
    localSavedDestinations(methodId: $methodId) {
      id
      methodId
      label
      holderName
      holderDocument
      institution
      verification
      country
      asset
    }
  }
`;

const LOCAL_DESTINATION = gql`
  query LocalDestination($id: UUID!) {
    localDestination(id: $id) {
      id
      methodId
      label
      holderName
      holderDocument
      institution
      verification
      country
      asset
    }
  }
`;

const LOCAL_PAYOUT_QUOTE = gql`
  query LocalPayoutQuote($destinationId: UUID!, $amount: Decimal, $bridgeId: UUID) {
    localPayoutQuote(destinationId: $destinationId, amount: $amount, bridgeId: $bridgeId) {
      sourceAmount
      targetAmount
      minimumTarget
      rate
      asset
      expiresAt
    }
  }
`;

const LOCAL_DEPOSIT_QUOTE = gql`
  query LocalDepositQuote($creditId: UUID!) {
    localDepositQuote(creditId: $creditId) {
      sourceAmount
      asset
      targetAmount
      minimumFxOutput
      minimumWalletOutput
      rate
      expiresAt
    }
  }
`;

export const LOCAL_RECEIVE_ACCOUNT = gql`
  query LocalReceiveAccount($methodId: String!) {
    localReceiveAccount(methodId: $methodId) {
      methodId
      status
      localAccountId
      cryptoAccountId
      country
      asset
      instructionKind
      value
      holderName
      institution
      receiveSameName
      receiveThirdParty
    }
  }
`;

export const LOCAL_DEPOSITS = gql`
  query LocalDeposits($account: UUID!, $offset: Int!) {
    infiniaJourneyDeposits(accountId: $account, offset: $offset) {
      internalId
      asset
      amount
      occurredAt
      held
      heldReason
    }
  }
`;

export const LOCAL_JOURNEY = gql`
  query LocalJourney($id: UUID!) {
    infiniaJourney(internalId: $id) {
      internalId
      direction
      stage
      failureCode
      destinationSummary
      localAsset
      payoutAmount
      minimumFxOutput
      minimumWalletOutput
      bridgeFundingMode
      createdAt
    }
  }
`;

// Its own operation: against an older server only this query fails.
export const LOCAL_JOURNEY_BRIDGE = gql`
  query LocalJourneyBridge($id: UUID!) {
    infiniaJourney(internalId: $id) {
      internalId
      bridgeStatus
    }
  }
`;

export const LOCAL_JOURNEYS = gql`
  query LocalJourneys($offset: Int!, $limit: Int!) {
    myInfiniaJourneys(offset: $offset, limit: $limit) {
      internalId
      direction
      stage
      failureCode
      destinationSummary
      localAsset
      payoutAmount
      minimumFxOutput
      minimumWalletOutput
      bridgeFundingMode
      createdAt
    }
  }
`;

export const LIMIT_INCREASE_REQUEST = gql`
  query LimitIncreaseRequest {
    limitIncreaseRequest {
      id
      status
      incomeType
      userMessage
      submittedAt
    }
  }
`;

export const LIMIT_INCREASE_REQUIREMENTS = gql`
  query LimitIncreaseRequirements($incomeType: String!) {
    limitIncreaseRequirements(incomeType: $incomeType) {
      kind
      title
      detail
    }
  }
`;

const ACTIVATE_LOCAL_MONEY = gql`
  mutation ActivateLocalMoney($methodId: String!) {
    activateLocalMoney(methodId: $methodId) {
      success
      errors
      status
    }
  }
`;

const RESOLVE_LOCAL_DESTINATION = gql`
  mutation ResolveLocalDestination($methodId: String!, $value: String!) {
    resolveLocalDestination(methodId: $methodId, value: $value) {
      success
      errors
      destination {
        id
        methodId
        label
        holderName
        holderDocument
        institution
        verification
        country
        asset
      }
    }
  }
`;

// Its own operation: against an older server only this call fails.
const RECHECK_LOCAL_DESTINATION = gql`
  mutation RecheckLocalDestination($id: UUID!) {
    recheckLocalDestination(id: $id) {
      success
      errors
      destination {
        id
        methodId
        label
        holderName
        holderDocument
        institution
        verification
        country
        asset
      }
    }
  }
`;

const START_LIMIT_INCREASE_VERIFICATION = gql`
  mutation StartLimitIncreaseVerification(
    $incomeType: String!
    $occupation: String!
    $expectedMonthlyUsd: Decimal!
    $sourceOfFunds: String!
  ) {
    startLimitIncreaseVerification(
      incomeType: $incomeType
      occupation: $occupation
      expectedMonthlyUsd: $expectedMonthlyUsd
      sourceOfFunds: $sourceOfFunds
    ) {
      success
      errors
      sessionId
      sessionToken
    }
  }
`;

const SYNC_LIMIT_INCREASE_VERIFICATION = gql`
  mutation SyncLimitIncreaseVerification($sessionId: String!) {
    syncLimitIncreaseVerification(sessionId: $sessionId) {
      success
      errors
      request {
        id
        status
        userMessage
      }
    }
  }
`;

// A second identity document for a rail the primary one does not satisfy.
// Its own document: older servers reject the new arguments, and that failure
// must stay inside this flow instead of breaking the primary verification.
const CREATE_ADDITIONAL_DOCUMENT_SESSION = gql`
  mutation CreateAdditionalDocumentSession($idCountry: String, $documentTypes: [String]) {
    createDiditVerificationSession(purpose: "additional_document", idCountry: $idCountry, documentTypes: $documentTypes) {
      success
      error
      session {
        sessionId
        sessionToken
      }
    }
  }
`;

const SYNC_ADDITIONAL_DOCUMENT = gql`
  mutation SyncAdditionalDocument($sessionId: String!) {
    syncDiditVerificationSession(sessionId: $sessionId) {
      success
      error
      verificationStatus
      statusDetail
      verification {
        id
        status
        rejectedReason
      }
    }
  }
`;

async function client() {
  const {apolloClient} = await import('../apollo/client');
  return apolloClient;
}

function withinTime<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('La revisión tardó demasiado. Intenta de nuevo.')), ms);
    promise.then(
      value => { clearTimeout(timer); resolve(value); },
      error => { clearTimeout(timer); reject(error); },
    );
  });
}

/** timeoutMs bounds each request on its own, never a location check between
 * them (the device check has its own, longer limits). */
async function runMutation(mutation: any, variables: Record<string, unknown>, key: string, fallback: string, timeoutMs = 0) {
  const {withBrebLocationRetry} = await import('./brebLocation');
  const result = await withBrebLocationRetry(async () => {
    const apollo = await client();
    const request = apollo.mutate({mutation, variables});
    const response = await (timeoutMs ? withinTime(request, timeoutMs) : request);
    return response.data?.[key];
  });
  if (!result?.success) {
    throw new Error(result?.errors?.[0] || fallback);
  }
  return result;
}

async function runQuery<T>(query: any, variables: Record<string, unknown>, key: string, fallback: string): Promise<T> {
  const response = await (await client()).query({query, variables, fetchPolicy: 'network-only'});
  const value = response.data?.[key];
  if (!value) {
    throw new Error(response.errors?.[0]?.message || fallback);
  }
  return value as T;
}

const PREPARE_LOCAL_ACTIVATION = gql`
  mutation PrepareLocalActivation($methodId: String!, $acceptedFee: Decimal) {
    prepareLocalActivation(methodId: $methodId, acceptedFee: $acceptedFee) {
      success errors status amount
      payment {
        success error sendId tokenType intentId grossAmount feeAmount netAmount feeBps
        calls { to valueWei data }
      }
    }
  }
`;

/** The opening fee before any commitment (a consent-only quote: nothing is
 * created or charged). null when the account is already being opened. */
export async function quoteLocalActivation(methodId: string): Promise<string | null> {
  const result = await runMutation(PREPARE_LOCAL_ACTIVATION, {methodId}, 'prepareLocalActivation',
    'No pudimos consultar el costo de apertura.');
  return result.status === 'consent_required' ? String(result.amount) : null;
}

/** A screen that already showed the fee and the payment on its own passes
 * these instead of the confirmation alerts. */
export interface ActivationPrompts {
  confirmFee?: (amount: string) => Promise<boolean>;
  confirmPayment?: (amount: string) => Promise<boolean>;
}

export async function payLocalActivation(methodId: string, prompts: ActivationPrompts = {}): Promise<boolean> {
  let result = await runMutation(PREPARE_LOCAL_ACTIVATION, {methodId}, 'prepareLocalActivation',
    'No pudimos preparar la activación.');
  if (result.status === 'consent_required') {
    const accepted = prompts.confirmFee ? await prompts.confirmFee(String(result.amount)) : await new Promise<boolean>(resolve => Alert.alert(
      'Solicitar cuenta local',
      `La apertura cuesta US$${result.amount} una sola vez. Pagarás cuando la cuenta esté lista, antes de recibir sus datos o usarla. Si no se puede abrir, no se cobra.`,
      [{text: 'Ahora no', style: 'cancel', onPress: () => resolve(false)},
       {text: 'Aceptar y solicitar', onPress: () => resolve(true)}],
      {cancelable: true, onDismiss: () => resolve(false)},
    ));
    if (!accepted) return false;
    result = await runMutation(PREPARE_LOCAL_ACTIVATION, {methodId, acceptedFee: result.amount},
      'prepareLocalActivation', 'No pudimos solicitar la cuenta.');
  }
  if (result.status === 'failed') {
    throw new Error('No pudimos abrir esta cuenta. No se realizó ningún cobro.');
  }
  if (result.payment) {
    const approved = prompts.confirmPayment ? await prompts.confirmPayment(String(result.amount)) : await new Promise<boolean>(resolve => Alert.alert(
      'Tu cuenta está lista',
      `Paga US$${result.amount} con tu saldo Confío para ver los datos y empezar a usar esta cuenta. Es un pago único.`,
      [{text: 'Ahora no', style: 'cancel', onPress: () => resolve(false)},
       {text: `Pagar US$${result.amount} y activar`, onPress: () => resolve(true)}],
      {cancelable: true, onDismiss: () => resolve(false)},
    ));
    if (!approved) return false;
    const {submitPreparedBscSend, BSC_SEND_ERRORS} = await import('./bscSend');
    try { await submitPreparedBscSend(result.payment); }
    catch (error: any) { throw new Error(BSC_SEND_ERRORS[error?.message] || error?.message || 'No pudimos confirmar tu pago.'); }
  }
  return true;
}

export async function activateLocalMoney(methodId: string): Promise<LocalPairStatus> {
  const result = await runMutation(ACTIVATE_LOCAL_MONEY, {methodId}, 'activateLocalMoney',
    'No pudimos preparar tu cuenta local. Intenta de nuevo.');
  return result.status as LocalPairStatus;
}

export async function resolveLocalDestination(methodId: string, value: string, timeoutMs = 0): Promise<LocalDestination> {
  const result = await runMutation(RESOLVE_LOCAL_DESTINATION, {methodId, value}, 'resolveLocalDestination',
    'No pudimos revisar esos datos. Intenta de nuevo.', timeoutMs);
  return result.destination as LocalDestination;
}

/** A saved recipient, checked again by the server when its check is old. */
export async function recheckLocalDestination(id: string, timeoutMs = 0): Promise<LocalDestination> {
  const result = await runMutation(RECHECK_LOCAL_DESTINATION, {id}, 'recheckLocalDestination',
    'No pudimos revisar a quien recibe.', timeoutMs);
  return result.destination as LocalDestination;
}

export function fetchLocalDestination(id: string): Promise<LocalDestination> {
  return runQuery(LOCAL_DESTINATION, {id}, 'localDestination', 'Destino no encontrado');
}

export function fetchPayoutQuote(destinationId: string, options: {amount?: string; bridgeId?: string}): Promise<LocalPayoutQuote> {
  return runQuery(LOCAL_PAYOUT_QUOTE, {destinationId, ...options}, 'localPayoutQuote',
    'No pudimos cotizar este envío.');
}

export function fetchDepositQuote(creditId: string): Promise<LocalDepositQuote> {
  return runQuery(LOCAL_DEPOSIT_QUOTE, {creditId}, 'localDepositQuote', 'No pudimos cotizar este depósito.');
}

export async function startLimitIncreaseVerification(variables: {
  incomeType: string;
  occupation: string;
  expectedMonthlyUsd: string;
  sourceOfFunds: string;
}): Promise<{sessionId: string; sessionToken: string}> {
  const result = await runMutation(START_LIMIT_INCREASE_VERIFICATION, variables, 'startLimitIncreaseVerification',
    'No pudimos iniciar la verificación.');
  return {sessionId: result.sessionId, sessionToken: result.sessionToken};
}

export async function syncLimitIncreaseVerification(sessionId: string) {
  const result = await runMutation(SYNC_LIMIT_INCREASE_VERIFICATION, {sessionId}, 'syncLimitIncreaseVerification',
    'No pudimos consultar tu verificación.');
  return result.request as {id: string; status: string; userMessage: string};
}

export async function createAdditionalDocumentSession(idCountry: string, documentTypes: string[]) {
  const response = await (await client()).mutate({
    mutation: CREATE_ADDITIONAL_DOCUMENT_SESSION,
    variables: {idCountry: idCountry || null, documentTypes},
  });
  const result = response.data?.createDiditVerificationSession;
  if (!result?.success || !result?.session?.sessionToken) {
    throw new Error(result?.error || 'No pudimos iniciar la verificación.');
  }
  return result.session as {sessionId: string; sessionToken: string};
}

export async function syncAdditionalDocument(sessionId: string) {
  const response = await (await client()).mutate({mutation: SYNC_ADDITIONAL_DOCUMENT, variables: {sessionId}});
  const result = response.data?.syncDiditVerificationSession;
  if (!result?.success) {
    throw new Error(result?.error || 'No pudimos consultar tu verificación.');
  }
  return {
    status: String(result.verificationStatus || result.verification?.status || 'pending'),
    detail: String(result.verification?.rejectedReason || result.statusDetail || ''),
  };
}

// ------------------------------------------------------------------ copy

const CURRENCY_NAMES: Record<string, string> = {
  COP: 'pesos colombianos',
  MXN: 'pesos mexicanos',
  ARS: 'pesos argentinos',
  BRL: 'reales',
};

export const currencyName = (asset: string) => CURRENCY_NAMES[asset] || asset;
export const currencyShort = (asset: string) => (asset === 'BRL' ? 'reales' : 'pesos');

export interface LocalStep {
  label: string;
}

/** The canonical money-flow states — never the intermediate provider legs. */
export function journeySteps(direction: string, asset: string): string[] {
  return direction === 'to_bank'
    ? ['Preparando fondos', `Convirtiendo a ${currencyShort(asset)}`, 'Enviando', 'Completado']
    : ['Convirtiendo a dólares', 'Enviando a tu Confío Dollar', 'Completado'];
}

export function journeyStepIndex(direction: string, stage: string): number {
  if (stage === 'completed') {
    return direction === 'to_bank' ? 3 : 2;
  }
  if (direction === 'to_bank') {
    return ({awaiting_credit: 0, converting: 1, paying_out: 2} as Record<string, number>)[stage] ?? 0;
  }
  return ({awaiting_credit: 0, converting: 0} as Record<string, number>)[stage] ?? 1;
}

/** PayinAdmission reasons → stable user copy. Raw codes never reach the UI. */
export function heldReasonCopy(reason: string): string {
  if (['sender_identity_missing', 'country_not_enabled', 'rail_not_enabled', 'user_not_enabled',
    'provider_third_party_not_enabled'].includes(reason)) {
    return 'No viene de una cuenta a tu nombre.';
  }
  if (reason === 'identity_not_verified') {
    return 'Necesitamos confirmar tu verificación de identidad.';
  }
  return 'Lo estamos revisando.';
}
