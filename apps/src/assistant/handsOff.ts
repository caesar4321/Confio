// Hands-off chat trades by the Cuenta inteligente (server: smart_account/relay_trades.py, assistant/trades.py).
// Its own query and mutations, never fields in the shared thread query: a server without them rejects only these.
import { gql } from '@apollo/client';

import type { SmartAccountPreparedBatch } from '../services/smartAccount';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';
import type { AssistantAction } from './api';

export const GET_RELAY_TRADE = gql`
  query AssistantRelayTrade($trade: UUID!) {
    assistantRelayTrade(trade: $trade) {
      status txHash label errorCode mode choices preselected currentCap moveAmount
    }
  }
`;

export const PREPARE_TRADE_CAP = gql`
  mutation PrepareAssistantTradeCap($trade: UUID!, $amount: String!) {
    prepareAssistantTradeCap(trade: $trade, amount: $amount) {
      success errorCode errorMessage requestId calls { to valueWei data } notAfter summary
    }
  }
`;

export const PREPARE_TRADE_MOVE = gql`
  mutation PrepareAssistantTradeMove($trade: UUID!) {
    prepareAssistantTradeMove(trade: $trade) {
      success errorCode errorMessage requestId calls { to valueWei data } notAfter summary
    }
  }
`;

export const PREPARE_ACCOUNT_MIGRATION = gql`
  mutation PrepareAssistantAccountMigration {
    prepareAssistantAccountMigration {
      success errorCode errorMessage requestId calls { to valueWei data } notAfter summary
    }
  }
`;

export const RESUME_RELAY_TRADE = gql`
  mutation ResumeAssistantRelayTrade($trade: UUID!) {
    resumeAssistantRelayTrade(trade: $trade) { status }
  }
`;

// status: waiting_rule | waiting_move | pending | done | failed | cancelled
export type RelayTrade = {
  status: string; txHash?: string | null; label: string; errorCode?: string | null;
  mode?: string | null; choices?: string[] | null; preselected?: string | null; currentCap?: string | null;
  moveAmount?: string | null;
};

export const HANDS_OFF_TYPES = new Set([
  'relay_trade', 'trade_cap', 'trade_move', 'trade_offer', 'account_migration',
]);

export function handsOffActions(actions: AssistantAction[]): AssistantAction[] {
  return actions.filter((a) => HANDS_OFF_TYPES.has(a.type));
}

/** The words of a cap: the leaky bucket lets up to about twice through in one full week, so an average. */
export function capText(amount: string | null | undefined): string {
  const n = Number(amount);
  if (!amount || !Number.isFinite(n) || n <= 0) {
    return '';
  }
  return `hasta US$${n.toLocaleString('en-US', { maximumFractionDigits: 2 })} por semana, en promedio`;
}

/** A typed amount as the server takes it ("1500" -> "1500.00"), or null. */
export function capAmount(typed: string): string | null {
  const clean = (typed || '').replace(/[^0-9.,]/g, '').replace(',', '.');
  const n = Number(clean);
  if (!clean || !Number.isFinite(n) || n < 1 || n > 10000) {
    return null;
  }
  return n.toFixed(2);
}

/** Bitcoin and gold screens never open where the app ships without them (iOS). */
export function diyScreenAllowed(screen: string | null | undefined, dexEnabled: boolean): boolean {
  if (!screen) {
    return false;
  }
  if (screen === 'BuyCrypto' || screen === 'SellCrypto') {
    return dexEnabled;
  }
  return screen === 'BuyStock' || screen === 'SellStock';
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
    return out ?? failed('no_response', 'No pudimos preparar la operación. No se movió nada. Inténtalo de nuevo.');
  } catch (e) {
    if (isSchemaMismatch(e as any)) {
      return failed('unsupported', 'Esta opción todavía no está disponible. No se movió nada.');
    }
    return failed('network', 'No pudimos preparar la operación. No se movió nada. Inténtalo de nuevo.');
  }
}

export function prepareTradeCap(client: Client, trade: string, amount: string) {
  return prepared(client, PREPARE_TRADE_CAP, { trade, amount }, 'prepareAssistantTradeCap');
}

export function prepareTradeMove(client: Client, trade: string) {
  return prepared(client, PREPARE_TRADE_MOVE, { trade }, 'prepareAssistantTradeMove');
}

export function prepareAccountMigration(client: Client) {
  return prepared(client, PREPARE_ACCOUNT_MIGRATION, {}, 'prepareAssistantAccountMigration');
}
