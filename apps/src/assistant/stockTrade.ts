// A stock or ETF bought or sold from a card in the chat (assistant/trades.py).
//
// The action arrives as { type: 'trade', ticker, target: 'buy:20.00' |
// 'sell:20.00' | 'sell:all', label }. The amount and the asset were read by
// the server from the person's own words; this file only checks the shape.
import { gql } from '@apollo/client';

export type TradeAction = {
  side: 'buy' | 'sell';
  ticker: string;
  /** Dollars; null = everything they hold of it (a sale only). */
  amountUsd: number | null;
  label: string;
};

const TARGET = /^(buy|sell):(\d{1,7}\.\d{2}|all)$/;
const TICKER = /^[A-Za-z0-9.]{1,12}$/;

/** The trade as this build knows it; null for anything else. */
export function resolveTrade(a: { type: string; target?: string | null; ticker?: string | null; label?: string | null }): TradeAction | null {
  if (a.type !== 'trade' || !a.label || !a.ticker || !TICKER.test(a.ticker)) {
    return null;
  }
  const parts = TARGET.exec(a.target || '');
  if (!parts) {
    return null;
  }
  const side = parts[1] as 'buy' | 'sell';
  if (parts[2] === 'all') {
    return side === 'sell' ? { side, ticker: a.ticker, amountUsd: null, label: a.label } : null;
  }
  const amountUsd = Number(parts[2]);
  return amountUsd > 0 ? { side, ticker: a.ticker, amountUsd, label: a.label } : null;
}

// One card, one trade. The phone never invents the request it signs: it asks
// the server for it (assistant/trades.py `claim`), which hands out one at a
// time per card and none once a trade of that card is on record. Each is its
// own operation: a server without it refuses only that one.
export const GET_MESSAGE_STOCK_TRADE = gql`
  query AssistantStockTrade($messageId: ID!) {
    assistantStockTrade(messageId: $messageId) { status txHash }
  }
`;
export const CLAIM_STOCK_TRADE = gql`
  mutation ClaimAssistantStockTrade($messageId: ID!) {
    claimAssistantStockTrade(messageId: $messageId) { requestId status }
  }
`;
export const RELEASE_STOCK_TRADE = gql`
  mutation ReleaseAssistantStockTrade($messageId: ID!, $requestId: String!) {
    releaseAssistantStockTrade(messageId: $messageId, requestId: $requestId) { status }
  }
`;
