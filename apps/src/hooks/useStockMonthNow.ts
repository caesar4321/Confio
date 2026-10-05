// This month's "Tus acciones" result for the stocks screens' link to Tu mes.
// Same isolated query as the Tu mes card: null (unknown, older server, or
// stocks not offered) only drops the number, never the link. The stocks
// screen stays mounted under a buy or sell: every refocus re-reads, so the
// number matches Tu mes after a trade.
import { useCallback, useMemo, useRef } from 'react';
import { useQuery } from '@apollo/client';
import { useFocusEffect } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { MainStackParamList } from '../types/navigation';
import { GET_STOCK_MONTH, type StockMonth } from '../apollo/monthSummary';
import { currentYearMonth, deviceTimezone } from '../utils/monthSummary';
import { isBalanceHidden } from '../utils/balanceVisibility';

export function useStockMonthNow(enabled: boolean): StockMonth | null {
  const { year, month } = currentYearMonth();
  const timezone = useMemo(() => deviceTimezone(), []);
  const { data, refetch } = useQuery<{ stockMonth: StockMonth | null }>(GET_STOCK_MONTH, {
    variables: { year, month, timezone },
    skip: !enabled,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
  });
  // Refetch via refs: the effect must run per focus, never per render.
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const focusedOnce = useRef(false);
  useFocusEffect(useCallback(() => {
    if (focusedOnce.current && enabledRef.current) refetchRef.current().catch(() => undefined);
    focusedOnce.current = true;
  }, []));
  return data?.stockMonth ?? null;
}

/** "Este mes: +US$4.20" when the month's result is exact, else null. */
export function stockMonthGain(value: StockMonth | null): number | null {
  if (!value || value.state !== 'gain' || value.gainUsd === null) return null;
  const gain = Number(value.gainUsd);
  return Number.isFinite(gain) ? gain : null;
}

/** The stocks screens' door to this month in Tu mes: back to a Tu mes already
 *  in the stack (pop + merge) instead of stacking copies, and masked like
 *  Home when the user hid their balances (these screens don't pass by Home). */
export async function openTuMesNow(navigation: NativeStackNavigationProp<MainStackParamList>,
  { fromTrade = false }: { fromTrade?: boolean } = {}): Promise<void> {
  // A Tu mes already in the stack may have been opened masked by another
  // screen's own toggle (the account detail's per-account eye): the merge
  // must never unmask it. The LAST one: navigate's pop goes back to the
  // topmost route of that name (StackRouter findLast), not the first.
  const routes = navigation.getState?.()?.routes ?? [];
  const existing = [...routes].reverse().find((r) => r.name === 'MonthSummary');
  const wasMasked = Boolean((existing?.params as MainStackParamList['MonthSummary'])?.masked);
  const masked = wasMasked || await isBalanceHidden();
  navigation.navigate('MonthSummary', { ...currentYearMonth(), masked, fromTrade }, { pop: true, merge: true });
}
