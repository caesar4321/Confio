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
