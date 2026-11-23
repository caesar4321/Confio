// useMonthHeroLine returns a new object on every render. Whatever is
// published for the conversation home's header and drawer must only change
// when a figure does: published as is, the month would change the snapshot on
// every render, re-render the home (and the screen that publishes inside
// it), and never settle. One object per state and per summary.
import { useMemo } from 'react';
import type { HeroMonthState } from '../hooks/useMonthHeroLine';

export function useStableHeroMonth(state: HeroMonthState): HeroMonthState {
  const summary = state.kind === 'month' ? state.summary : null;
  return useMemo<HeroMonthState>(
    () => (summary ? { kind: 'month', summary } : { kind: state.kind as 'hidden' | 'loading' | 'invite' }),
    [state.kind, summary],
  );
}
