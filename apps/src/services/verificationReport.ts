import { AnalyticsService } from './analyticsService';

/** One attempt in Didit's SDK: "launched" at most once, then one ending. The outcome only. */
export function verificationReport() {
  let launched = false;
  let ended = false;
  const send = (outcome: 'launched' | 'completed' | 'cancelled' | 'failed' | 'not_launched') => {
    void AnalyticsService.logFunnelEvent('verification_sdk_result', { outcome });
  };
  return {
    launched: () => {
      if (launched) return;
      launched = true;
      send('launched');
    },
    end: (outcome: 'completed' | 'cancelled' | 'failed') => {
      if (ended) return;
      ended = true;
      send(outcome === 'failed' && !launched ? 'not_launched' : outcome);
    },
  };
}
