// Coinbase Onramp — the US low-cost rail (ACH 0.5%, card 2.5%).
//
// Onramp cannot deliver USDC on Algorand (its catalog only lands native ALGO
// there — probed 2026-07-23), so the corridor is: Onramp delivers native ALGO
// to the user's OWN Algorand address, and the existing ALGO→USDC→cUSD
// auto-swap (BuildAutoSwapTransactions, one atomic Tinyman group) converts
// the arrival. The server owns the session token: it injects the account's
// registered address from the DB — the client never supplies a destination.
import * as Keychain from 'react-native-keychain';
import { getApiUrl } from '../config/env';
import { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';
import appCheckService from './appCheckService';

const deriveApiBase = () => {
  const url = getApiUrl() || '';
  return url.replace(/graphql\/?$/i, '');
};

const SESSION_URL = `${deriveApiBase()}api/coinbase/onramp-session/`;

async function getAuthHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  try {
    const credentials = await Keychain.getGenericPassword({
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME,
    });
    if (credentials && credentials.password) {
      const parsed = JSON.parse(credentials.password);
      if (parsed?.accessToken) {
        headers['Authorization'] = `JWT ${parsed.accessToken}`;
      }
    }
    const appCheckToken = await appCheckService.waitForToken();
    if (appCheckToken) {
      headers['X-Firebase-AppCheck'] = appCheckToken;
    }
  } catch (err) {}
  return headers;
}

export type CoinbasePaymentMethod = 'ACH_BANK_ACCOUNT' | 'CARD' | 'APPLE_PAY';

export async function createCoinbaseOnrampSession(params: {
  amount?: number;
  paymentMethod?: CoinbasePaymentMethod;
}): Promise<{ url: string }> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(SESSION_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders },
    body: JSON.stringify({
      amount: params.amount,
      payment_method: params.paymentMethod || 'ACH_BANK_ACCOUNT',
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.url) {
    throw new Error(data.error || 'No se pudo abrir Coinbase. Intenta más tarde.');
  }
  return { url: data.url };
}

// ── Offramp (US cash-out: cUSD → USDC → ALGO → Coinbase sell → ACH) ────────

const OFFRAMP_SESSION_URL = `${deriveApiBase()}api/coinbase/offramp-session/`;
const OFFRAMP_STATUS_URL = `${deriveApiBase()}api/coinbase/offramp-status/`;

export async function createCoinbaseOfframpSession(params: {
  amount?: number;
}): Promise<{ url: string }> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(OFFRAMP_SESSION_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders },
    body: JSON.stringify({ amount: params.amount }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.url) {
    throw new Error(data.error || 'No se pudo abrir Coinbase. Intenta más tarde.');
  }
  return { url: data.url };
}

export interface CoinbaseOfframpStatus {
  pending: boolean;
  sellAmount?: string; // ALGO the sell expects
  status?: string;
}

export async function getCoinbaseOfframpStatus(): Promise<CoinbaseOfframpStatus> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(OFFRAMP_STATUS_URL, { method: 'GET', headers: authHeaders });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || 'No pudimos consultar tu retiro de Coinbase.');
  }
  return { pending: !!data.pending, sellAmount: data.sell_amount, status: data.status };
}
