// "Tu mes" (month summary) GraphQL documents.
//
// Kept in their own requests on purpose: one unknown field fails the WHOLE
// shared query against an older server, so these never ride along with the
// app's big shared queries (feedback-isolate-new-graphql-fields).
import { gql } from '@apollo/client';

const TOTALS = `
  incomeUsd
  spendingUsd
  topUpsUsd
  withdrawalsUsd
  savingsNetUsd
  investmentNetUsd
  movementCount
  spendingByCategory {
    category
    amountUsd
  }
`;

export const GET_MONTH_SUMMARY = gql`
  query MonthSummary($year: Int!, $month: Int!, $timezone: String) {
    monthSummary(year: $year, month: $month, timezone: $timezone) {
      year
      month
      timezone
      previousIsPartial
      current { ${TOTALS} }
      previous { ${TOTALS} }
      counterparties {
        key
        name
        receivedUsd
        sentUsd
      }
    }
  }
`;

/** The "Comprar" section: its own request (newer than monthSummary). */
export const GET_MONTH_COMPRAR = gql`
  query MonthComprar($year: Int!, $month: Int!, $timezone: String) {
    monthComprar(year: $year, month: $month, timezone: $timezone) {
      purchasesUsd
      purchaseCount
      salesUsd
      saleCount
    }
  }
`;

export type MonthComprar = {
  purchasesUsd: string;
  purchaseCount: number;
  salesUsd: string;
  saleCount: number;
};

export const GET_MONTH_MOVEMENTS = gql`
  query MonthMovements($year: Int!, $month: Int!, $timezone: String, $filterBy: String!, $value: String) {
    monthMovements(year: $year, month: $month, timezone: $timezone, filterBy: $filterBy, value: $value) {
      id
      kind
      direction
      amountUsd
      category
      counterpartyKey
      counterpartyName
      date
    }
  }
`;

export const GET_CATEGORY_PROMPT = gql`
  query CategoryPrompt($movementId: ID, $internalId: String) {
    categoryPrompt(movementId: $movementId, internalId: $internalId) {
      shouldAsk
      category
      counterpartyName
    }
  }
`;

export const CATEGORIZE_MOVEMENT = gql`
  mutation CategorizeMovement($category: String!, $applyTo: String!, $movementId: ID, $internalId: String) {
    categorizeMovement(category: $category, applyTo: $applyTo, movementId: $movementId, internalId: $internalId) {
      success
      error
      category
    }
  }
`;

export const RECORD_CATEGORY_PROMPT = gql`
  mutation RecordCategoryPrompt($outcome: String!, $movementId: ID, $internalId: String) {
    recordCategoryPrompt(outcome: $outcome, movementId: $movementId, internalId: $internalId) {
      success
    }
  }
`;

export type CategoryKey =
  | 'food' | 'transport' | 'home' | 'bills' | 'family' | 'shopping'
  | 'health' | 'education' | 'leisure' | 'debt' | 'work' | 'other';

export type MonthTotals = {
  incomeUsd: string;
  spendingUsd: string;
  topUpsUsd: string;
  withdrawalsUsd: string;
  savingsNetUsd: string;
  investmentNetUsd: string;
  movementCount: number;
  spendingByCategory: { category: CategoryKey | 'uncategorized'; amountUsd: string }[];
};

export type MonthSummary = {
  year: number;
  month: number;
  timezone: string;
  previousIsPartial: boolean;
  current: MonthTotals;
  previous: MonthTotals;
  counterparties: { key: string; name: string; receivedUsd: string; sentUsd: string }[];
};

export type MonthMovement = {
  id: string;
  kind: string;
  direction: string;
  amountUsd: string;
  category: CategoryKey | null;
  counterpartyKey: string | null;
  counterpartyName: string | null;
  date: string;
};

// ── Tu mes insights (docs/designs/tu-mes-insights.md). Three separate
// queries: each card fails alone, and an older server without a field never
// breaks monthSummary (feedback-isolate-new-graphql-fields).
export const GET_MONTH_INSIGHTS = gql`
  query MonthInsights($year: Int!, $month: Int!, $timezone: String) {
    monthInsights(year: $year, month: $month, timezone: $timezone) {
      previousMonthSpendingUsd
      recurring {
        counterpartyKey
        name
        expectedDay
        expectedAmountUsd
        category
      }
    }
  }
`;

export const GET_SAVINGS_EARNED = gql`
  query SavingsEarned($year: Int!, $month: Int!) {
    savingsEarned(year: $year, month: $month) {
      earnedUsd
      daily {
        date
        usd
      }
    }
  }
`;

export const GET_PROTECTION_VALUE = gql`
  query ProtectionValue($timezone: String) {
    protectionValue(timezone: $timezone, includeStable: true) {
      currency
      basis
      state
      source
      protectedUsd
      paidLocal
      todayLocal
      gainLocal
      avgRate
      todayRate
      quotedAt
      startDate
    }
  }
`;

export type RecurringPayment = {
  counterpartyKey: string;
  name: string;
  expectedDay: number;
  expectedAmountUsd: string;
  category: CategoryKey | null;
};

export type MonthInsights = {
  previousMonthSpendingUsd: string;
  recurring: RecurringPayment[];
};

export type SavingsEarned = {
  earnedUsd: string;
  daily: { date: string; usd: string }[];
};

export type ProtectionValue = {
  currency: string;
  /** 'purchase': paid in Confío (BO, AR) · 'month_start': value on the 1st (VE) */
  basis: 'purchase' | 'month_start';
  /** 'gained' (≥ US$1) | 'stable' (less, or the local currency strengthened: never a loss) */
  state: 'gained' | 'stable';
  source: string;
  protectedUsd: string;
  paidLocal: string;
  todayLocal: string;
  gainLocal: string;
  avgRate: string;
  todayRate: string;
  quotedAt: string;
  /** month_start: the baseline day (ISO date), usually the 1st */
  startDate?: string | null;
};

// "Tus acciones" (U.S. stocks) for the viewed month. Own query, like the three above.
export const GET_STOCK_MONTH = gql`
  query StockMonth($year: Int!, $month: Int!, $timezone: String) {
    stockMonth(year: $year, month: $month, timezone: $timezone) {
      state
      canBuy
      valueUsd
      valueStartUsd
      boughtUsd
      soldUsd
      gainUsd
      gainPct
      holdings
      topMover {
        ticker
        name
        changePct
      }
    }
  }
`;

export type StockMonth = {
  /** 'gain': the month's result is exact · 'value_only': history incomplete,
   *  so only today's value · 'settling': a trade not final yet (today's value;
   *  ask again in seconds) · 'none': no stocks this month (invite) */
  state: 'gain' | 'value_only' | 'settling' | 'none';
  canBuy: boolean;
  valueUsd: string;
  valueStartUsd: string | null;
  boughtUsd: string | null;
  soldUsd: string | null;
  /** value − value on the 1st − bought + sold: deposits never read as gains */
  gainUsd: string | null;
  gainPct: string | null;
  holdings: number;
  topMover: { ticker: string; name: string; changePct: string } | null;
};

// "Oro y Bitcoin" (crypto & gold) for the viewed month: the twin of
// stockMonth, in its own query (an older server fails only this request).
export const GET_CRYPTO_MONTH = gql`
  query CryptoMonth($year: Int!, $month: Int!, $timezone: String) {
    cryptoMonth(year: $year, month: $month, timezone: $timezone) {
      state
      valueUsd
      valueStartUsd
      boughtUsd
      soldUsd
      gainUsd
      gainPct
      holdings
      assets {
        symbol
        ticker
        name
        category
        changePct
      }
    }
  }
`;

export const GET_PERPS_MONTH = gql`
  query PerpsMonth($year: Int!, $month: Int!, $timezone: String) {
    perpsMonth(year: $year, month: $month, timezone: $timezone) {
      state
      valueUsd
      valueStartUsd
      marginInUsd
      returnedUsd
      gainUsd
      gainPct
      positions
    }
  }
`;

/** "Futuros" in Tu mes, in the member's own money: margin put in and dollars
 *  back, never the leveraged exposure (a 10x position on US$100 moved US$100). */
export type PerpsMonth = {
  /** 'none' draws nothing; no 'value_only' (the ledger is complete or unknown → null). */
  state: 'gain' | 'settling' | 'none';
  valueUsd: string;
  valueStartUsd: string | null;
  marginInUsd: string | null;
  returnedUsd: string | null;
  /** value − value on the 1st − margin in + dollars back */
  gainUsd: string | null;
  gainPct: string | null;
  positions: number;
};

export type CryptoMonth = {
  /** Same states as StockMonth; 'none' draws nothing (no invitation). */
  state: 'gain' | 'value_only' | 'settling' | 'none';
  valueUsd: string;
  valueStartUsd: string | null;
  boughtUsd: string | null;
  soldUsd: string | null;
  /** value − value on the 1st − bought + sold: deposits never read as gains */
  gainUsd: string | null;
  gainPct: string | null;
  holdings: number;
  /** Held at the end of the month, Bitcoin first; changePct null when unknown. */
  assets: { symbol: string; ticker: string; name: string; category: string; changePct: string | null }[];
};
