// Hands-off Comprar purchases from the chat, paid by the Cuenta inteligente
// (server: smart_account/relay_purchases.py, assistant/comprar.py).
// Its own query and mutations, never fields in the shared thread query: a server without them rejects only these.
import { gql } from '@apollo/client';

import type { SmartAccountPreparedBatch } from '../services/smartAccount';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';

export const GET_RELAY_PURCHASE = gql`
  query AssistantRelayPurchase($purchase: UUID!) {
    assistantRelayPurchase(purchase: $purchase) {
      status txHash label errorCode amount order mode choices preselected currentCap moveAmount
    }
  }
`;

export const PREPARE_PURCHASE_CAP = gql`
  mutation PrepareAssistantPurchaseCap($purchase: UUID!, $amount: String!) {
    prepareAssistantPurchaseCap(purchase: $purchase, amount: $amount) {
      success errorCode errorMessage requestId calls { to valueWei data } notAfter summary
    }
  }
`;

export const PREPARE_PURCHASE_MOVE = gql`
  mutation PrepareAssistantPurchaseMove($purchase: UUID!) {
    prepareAssistantPurchaseMove(purchase: $purchase) {
      success errorCode errorMessage requestId calls { to valueWei data } notAfter summary
    }
  }
`;

export const RESUME_RELAY_PURCHASE = gql`
  mutation ResumeAssistantRelayPurchase($purchase: UUID!) {
    resumeAssistantRelayPurchase(purchase: $purchase) { status }
  }
`;

// status: waiting_rule | waiting_move | pending | done | failed | cancelled
export type RelayPurchase = {
  status: string; txHash?: string | null; label: string; errorCode?: string | null; amount?: string | null;
  order?: string | null; mode?: string | null; choices?: string[] | null; preselected?: string | null;
  currentCap?: string | null; moveAmount?: string | null;
};

export const PURCHASE_TYPES = new Set(['relay_purchase', 'purchase_cap', 'purchase_move', 'purchase_offer']);

// Purchase caps stay small (the audit): the choices and the most another amount may be.
export const PURCHASE_CAP_CHOICES = ['50', '150', '300'];
export const PURCHASE_CAP_MAX = 1000;

/** A typed purchase cap as the server takes it ("120" -> "120.00"), or null. */
export function purchaseCapAmount(typed: string): string | null {
  const clean = (typed || '').replace(/[^0-9.,]/g, '').replace(',', '.');
  const n = Number(clean);
  if (!clean || !Number.isFinite(n) || n < 1 || n > PURCHASE_CAP_MAX) {
    return null;
  }
  return n.toFixed(2);
}

type Client = { mutate: (options: any) => Promise<any> };

async function prepared(client: Client, mutation: any, variables: Record<string, unknown>, field: string):
Promise<SmartAccountPreparedBatch> {
  const failed = (errorCode: string, errorMessage: string): SmartAccountPreparedBatch => ({
    success: false, errorCode, errorMessage, requestId: null, calls: null, notAfter: null, summary: null,
  });
  try {
    const { data } = await client.mutate({ mutation, variables, fetchPolicy: 'no-cache' });
    const out = data?.[field] as SmartAccountPreparedBatch | null | undefined;
    return out ?? failed('no_response', 'No pudimos prepararlo. No se movió nada. Inténtalo de nuevo.');
  } catch (e) {
    if (isSchemaMismatch(e as any)) {
      return failed('unsupported', 'Esta opción todavía no está disponible. No se movió nada.');
    }
    return failed('network', 'No pudimos prepararlo. No se movió nada. Inténtalo de nuevo.');
  }
}

export function preparePurchaseCap(client: Client, purchase: string, amount: string) {
  return prepared(client, PREPARE_PURCHASE_CAP, { purchase, amount }, 'prepareAssistantPurchaseCap');
}

export function preparePurchaseMove(client: Client, purchase: string) {
  return prepared(client, PREPARE_PURCHASE_MOVE, { purchase }, 'prepareAssistantPurchaseMove');
}
