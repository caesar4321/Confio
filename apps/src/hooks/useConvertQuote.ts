// Live cUSD → cUSD+ conversion quote (decision (b), 2026-07-04):
// the CLIENT prices the bridge leg with the ported Allbridge pool math
// (services/allbridgeQuote.ts, validated against the official SDK); the
// SERVER owns only the guard threshold, Confío fee and kill switch.
//
// Guard params come from the server (cusdPlusConvertParams, live on prod
// since 2026-07-04); the DEFAULTS below only cover loading/offline.

import { useEffect, useRef, useState } from 'react';
import { gql, useQuery } from '@apollo/client';
import {
  BridgeDirection,
  getBridgeQuote,
  maxFillUnderThreshold,
} from '../services/allbridgeQuote';

const GET_CONVERT_PARAMS = gql`
  query CusdPlusConvertParams {
    cusdPlusConvertParams {
      spreadThresholdBps
      confioFeeBps
      minAmountUsd
      paused
      vaultAddress
    }
  }
`;

const DEFAULTS = {
  // 1% ceiling: the guard stops catastrophes, not conversions — within it
  // the user sees the quoted cost and decides (offline fallback only;
  // the live value comes from cusdPlusConvertParams)
  spreadThresholdPct: 1.0,
  confioFeeBps: 0, // open pricing decision — server-config, never hardcoded copy
  minAmountUsd: 1,
  paused: false,
};

export type ConvertQuoteStatus =
  | 'idle' // no amount yet
  | 'loading' // debounce or fetch in flight
  | 'ready' // cost under threshold — confirmable
  | 'partial' // only part of the amount fits under the guard right now
  | 'paused' // guard tripped even for the minimum (or server kill switch)
  | 'error'; // network failure — honest retry state, never a fake price

export interface ConvertQuote {
  status: ConvertQuoteStatus;
  costPct: number;
  costUsd: number;
  receiveUsd: number;
  /** legacy convenience for call sites that only ask "can I proceed?" */
  paused: boolean;
  /** when status === 'partial': largest amount currently under the guard */
  partialMaxUsd: number | null;
}

const IDLE: ConvertQuote = {
  status: 'idle',
  costPct: 0,
  costUsd: 0,
  receiveUsd: 0,
  paused: false,
  partialMaxUsd: null,
};

const DEBOUNCE_MS = 350;

export const useConvertQuote = (
  amountUsd: number,
  direction: BridgeDirection = 'alg_to_bsc',
): ConvertQuote => {
  const [quote, setQuote] = useState<ConvertQuote>(IDLE);
  const gen = useRef(0);

  const { data: paramsData } = useQuery(GET_CONVERT_PARAMS, {
    fetchPolicy: 'cache-and-network',
  });
  const server = paramsData?.cusdPlusConvertParams;
  const PARAMS = {
    spreadThresholdPct:
      server?.spreadThresholdBps != null
        ? server.spreadThresholdBps / 100
        : DEFAULTS.spreadThresholdPct,
    confioFeeBps: server?.confioFeeBps ?? DEFAULTS.confioFeeBps,
    minAmountUsd: server?.minAmountUsd ?? DEFAULTS.minAmountUsd,
    // Server kill switch stays authoritative in release builds; dev builds
    // ignore it so the ready-state UI stays reviewable while the rails are
    // still paused server-side (execution is a stub in dev anyway).
    paused: __DEV__ ? false : server?.paused ?? DEFAULTS.paused,
  };

  useEffect(() => {
    const g = ++gen.current;
    if (!(amountUsd > 0)) {
      setQuote(IDLE);
      return;
    }
    setQuote((prev) => ({ ...prev, status: 'loading', paused: false }));
    const timer = setTimeout(async () => {
      try {
        if (PARAMS.paused) {
          if (gen.current === g) {
            setQuote({ ...IDLE, status: 'paused', paused: true });
          }
          return;
        }
        const bridge = await getBridgeQuote(amountUsd, direction);
        const receiveUsd = bridge.receiveUsd * (1 - PARAMS.confioFeeBps / 10_000);
        const costUsd = amountUsd - receiveUsd;
        const costPct = (100 * costUsd) / amountUsd;
        const feePct = PARAMS.confioFeeBps / 100;

        if (costPct > PARAMS.spreadThresholdPct) {
          const fill = await maxFillUnderThreshold(
            amountUsd,
            Math.max(PARAMS.spreadThresholdPct - feePct, 0),
            direction,
          );
          if (gen.current !== g) return;
          if (fill >= PARAMS.minAmountUsd) {
            setQuote({
              status: 'partial',
              costPct,
              costUsd,
              receiveUsd,
              paused: true,
              partialMaxUsd: fill,
            });
          } else {
            setQuote({ ...IDLE, status: 'paused', paused: true });
          }
          return;
        }
        if (gen.current === g) {
          setQuote({
            status: 'ready',
            costPct,
            costUsd,
            receiveUsd,
            paused: false,
            partialMaxUsd: null,
          });
        }
      } catch (e) {
        if (gen.current === g) {
          setQuote({ ...IDLE, status: 'error', paused: true });
        }
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [amountUsd, direction, PARAMS.spreadThresholdPct, PARAMS.confioFeeBps, PARAMS.minAmountUsd, PARAMS.paused]);

  return quote;
};
