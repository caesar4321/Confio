// A share card's stock logo (our S3 mirror, via the GM market payload) and a
// gate that holds the capture until the image for THAT url, mounted now, has
// loaded or failed, so the shared picture never has a blank or half-drawn
// mark. Crypto perps (ZEC, ...) have no logo source: the ticker disc stays,
// as everywhere in the app.
import { useCallback, useRef } from 'react';
import { useQuery } from '@apollo/client';

import { GM_MARKET } from './useGmMarket';

/** Read once from the cache (or one fetch): never polls, nothing for a crypto card. */
export function useStockLogoUrl(ticker?: string | null): string | undefined {
  const want = (ticker || '').toUpperCase();
  const { data } = useQuery(GM_MARKET, { skip: !want, fetchPolicy: 'cache-first' });
  if (!want) return undefined;
  const asset = (data?.gmMarket?.assets || []).find((a: any) => String(a?.ticker || '').toUpperCase() === want);
  return asset?.logoUrl || undefined;
}

export function useLogoGate() {
  // url -> settled? Only an image that is mounted marks itself: its mount
  // (or a url change) marks it pending again, so a closed and reopened
  // sheet waits for its new image.
  const state = useRef(new Map<string, boolean>());
  const waiters = useRef(new Map<string, Array<() => void>>());

  const onPending = useCallback((url: string) => { state.current.set(url, false); }, []);
  const onSettled = useCallback((url: string) => {
    state.current.set(url, true);
    (waiters.current.get(url) || []).splice(0).forEach((resolve) => resolve());
  }, []);

  /** Resolves when the image for `url` is ready, there is no url, or after `ms`. */
  const wait = useCallback((url: string | undefined, ms = 3000) => {
    if (!url || state.current.get(url) === true) return Promise.resolve();
    return new Promise<void>((resolve) => {
      const list = waiters.current.get(url) || [];
      const done = () => { clearTimeout(timer); resolve(); };
      const timer = setTimeout(() => {
        const i = list.indexOf(done);
        if (i >= 0) list.splice(i, 1);
        resolve();
      }, ms);
      list.push(done);
      waiters.current.set(url, list);
    });
  }, []);

  return { onPending, onSettled, wait };
}
