import { useCallback, useEffect, useRef, useState } from 'react';
import type { SmartRead } from '../../services/smartAccount';

export interface SmartReadState<T> {
  /** undefined until the first answer; the server's value (possibly null) after. */
  data: T | undefined;
  loading: boolean;
  /** The last attempt failed. `data` keeps the previous answer, if any. */
  failed: boolean;
  reload: () => Promise<void>;
}

/**
 * One isolated read per call. A failure never clears what was already shown
 * (a balance must not blink away on a bad connection) and never reads as
 * "nothing there": screens branch on `failed`.
 */
export function useSmartRead<T>(
  fetcher: () => Promise<SmartRead<T>>,
  options: { skip?: boolean } = {},
): SmartReadState<T> {
  const { skip = false } = options;
  const [data, setData] = useState<T | undefined>(undefined);
  const [loading, setLoading] = useState(!skip);
  const [failed, setFailed] = useState(false);
  const mounted = useRef(true);
  const seq = useRef(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    let result: SmartRead<T>;
    try {
      result = await fetcherRef.current();
    } catch {
      result = { ok: false };
    }
    // A slower, older request must not overwrite a newer answer.
    if (!mounted.current || mine !== seq.current) {
      return;
    }
    // Anything but a well-formed answer is "could not ask", never "nothing".
    if (result && result.ok === true) {
      setData(result.data);
      setFailed(false);
    } else {
      setFailed(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!skip) {
      void reload();
    }
  }, [skip, reload]);

  return { data, loading, failed, reload };
}
