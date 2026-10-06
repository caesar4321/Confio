import { useEffect, useState } from 'react';
import { AppState } from 'react-native';
import { readHeartbeat } from '../services/emergencyExit/heartbeat';

/** How often a visible recovery surface re-reads the heartbeat while closed. */
export const EXIT_RECHECK_MS = 30_000;

/**
 * True only when the on-chain heartbeat says Salida de emergencia is open
 * (Confío stopped beating for silenceRequired). Recovery surfaces — the lock
 * screen, the slow-loading overlay — offer the exit only then; while Confío
 * operates there is no exit to offer.
 *
 * Read from public BSC RPCs, so it works exactly when Confío's servers are
 * gone. It re-reads every EXIT_RECHECK_MS while `active` and whenever the
 * app returns to the foreground — both ways: a failed read (bad data) is
 * "closed" only until the next one, a lock can stay up across the silence
 * boundary, and if Confío beats again the button goes away. Each activation
 * starts closed. A read's result is applied unless a NEWER read already
 * settled (so a slow older read can't overwrite a newer one, yet a read
 * slower than the interval still lands), and the timer never stacks reads:
 * a tick is skipped while one is in flight (a foreground return still
 * starts a fresh one).
 */
export function useEmergencyExitOpen(active: boolean): boolean {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    setOpen(false);
    if (!active) return undefined;
    let current = true;
    let started = 0;
    let applied = 0;
    let inFlight = 0;
    const check = () => {
      const seq = ++started;
      inFlight += 1;
      const settle = (isOpen: boolean) => {
        inFlight -= 1;
        if (current && seq > applied) {
          applied = seq;
          setOpen(isOpen);
        }
      };
      Promise.resolve()
        .then(() => readHeartbeat())
        .then((status) => settle(status?.state === 'open'), () => settle(false));
    };
    check();
    const timer = setInterval(() => { if (inFlight === 0) check(); }, EXIT_RECHECK_MS);
    const sub = AppState.addEventListener('change', (next) => { if (next === 'active') check(); });
    return () => {
      current = false;
      clearInterval(timer);
      sub?.remove?.();
    };
  }, [active]);
  return open;
}
