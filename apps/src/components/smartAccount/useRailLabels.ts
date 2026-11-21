// The server's payout rail names (offer.payoutRailOptions), read on their own
// so an older server only loses the names, never the screen. Registered for
// railLabel / railsPhrase; the returned options re-render the caller once
// they arrive.
import { useEffect } from 'react';
import { useSmartRead } from './useSmartRead';
import { registerRailLabels } from './format';
import { fetchSmartAccountPayoutRailOptions, type SmartAccountPayoutRailOption } from '../../services/smartAccount';

export function useRailLabels(): SmartAccountPayoutRailOption[] {
  const read = useSmartRead(fetchSmartAccountPayoutRailOptions);
  const options = read.data ?? [];
  registerRailLabels(options);
  useEffect(() => { registerRailLabels(read.data); }, [read.data]);
  return options;
}
