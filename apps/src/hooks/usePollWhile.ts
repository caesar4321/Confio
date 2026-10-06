import { useEffect, useState } from 'react';
import { useIsFocused } from '@react-navigation/native';

/**
 * Polls an Apollo query while `active` holds, only while the screen is
 * focused, and never longer than `maxMs` for one stretch of activity. The
 * deadline is its own timer, so it fires even when every poll returns the
 * same data (Apollo then re-renders nothing). A new `resetKey` (e.g. a new
 * submission) starts a fresh deadline even while still active.
 */
export function usePollWhile(
  active: boolean,
  startPolling: (intervalMs: number) => void,
  stopPolling: () => void,
  intervalMs: number,
  maxMs: number,
  resetKey: string = '',
) {
  const focused = useIsFocused();
  const [expired, setExpired] = useState(false);

  // A new stretch of activity, or a new submission, gets a fresh deadline.
  useEffect(() => {
    setExpired(false);
    if (!active) return undefined;
    const timer = setTimeout(() => setExpired(true), maxMs);
    return () => clearTimeout(timer);
  }, [active, maxMs, resetKey]);

  useEffect(() => {
    if (active && focused && !expired) {
      startPolling(intervalMs);
      return () => stopPolling();
    }
    stopPolling();
    return undefined;
  }, [active, focused, expired, intervalMs, startPolling, stopPolling]);
}
