// Keeps the app-wide number format (utils/numberLocale) on the user's
// country. Sets it DURING render so every screen below formats with the
// right separators in the same pass; subscribers (useNumberLocale) are
// notified after commit (notifying during render would update other
// components mid-render).
import React, { useEffect, useRef, useSyncExternalStore } from 'react';
import { useCountry } from './CountryContext';
import {
  applyNumberLocaleCountry, formatDecimal, formatUsdAmount, getSeparators, notifyNumberLocale,
  parseAmountInput, sanitizeAmountInput, subscribeNumberLocale, toAmountInput,
} from '../utils/numberLocale';

export function NumberLocaleProvider({ children }: { children: React.ReactNode }) {
  const { userCountry } = useCountry();
  const iso = userCountry?.[2] ?? null;
  applyNumberLocaleCountry(iso);
  // Compare with what subscribers last saw (a StrictMode double render
  // would report "unchanged" on its second pass).
  const notified = useRef(getSeparators());
  useEffect(() => {
    const now = getSeparators();
    if (now !== notified.current) {
      notified.current = now;
      notifyNumberLocale();
    }
  });
  return <>{children}</>;
}

/** Re-renders when the separators change; returns the formatters. */
export function useNumberLocale() {
  const separators = useSyncExternalStore(subscribeNumberLocale, getSeparators);
  return {
    separators,
    formatDecimal,
    formatUsd: formatUsdAmount,
    parseAmount: parseAmountInput,
    sanitizeAmount: sanitizeAmountInput,
    toAmountInput,
  };
}
