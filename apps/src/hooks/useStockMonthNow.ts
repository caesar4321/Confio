// This month's "Tus acciones" result for the stocks screens' link to Tu mes.
// Same isolated query as the Tu mes card: null (unknown, older server, or
// stocks not offered) only drops the number, never the link.
import { useMemo } from 'react';
import { useQuery } from '@apollo/client';
import { GET_STOCK_MONTH, type StockMonth } from '../apollo/monthSummary';
import { currentYearMonth, deviceTimezone } from '../utils/monthSummary';

export function useStockMonthNow(enabled: boolean): StockMonth | null {
  const { year, month } = currentYearMonth();
  const timezone = useMemo(() => deviceTimezone(), []);
  const { data } = useQuery<{ stockMonth: StockMonth | null }>(GET_STOCK_MONTH, {
    variables: { year, month, timezone },
    skip: !enabled,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
  });
  return data?.stockMonth ?? null;
}

/** "Este mes: +US$4.20" when the month's result is exact, else null. */
export function stockMonthGain(value: StockMonth | null): number | null {
  if (!value || value.state !== 'gain' || value.gainUsd === null) return null;
  const gain = Number(value.gainUsd);
  return Number.isFinite(gain) ? gain : null;
}
