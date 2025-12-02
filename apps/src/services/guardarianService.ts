import * as Keychain from 'react-native-keychain';
import { getApiUrl } from '../config/env';
import { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';

export interface GuardarianTransactionParams {
  amount: number;
  fromCurrency: string;
  fromNetwork?: string;
  toCurrency?: string;
  toNetwork?: string;
  email?: string;
  payoutAddress?: string;
  customerCountry?: string;
  locale?: string;
  externalId?: string;
}

export interface GuardarianTransactionResponse {
  id?: number;
  redirect_url?: string;
  deposit_address?: string;
  deposit_extra_id?: string; // Memo/Tag
  preauth_token?: string;
  errors?: Array<{ code?: string; reason?: string }>;
}

export interface GuardarianFiatCurrency {
  ticker: string;
  name: string;
  payment_categories?: Array<{ name?: string; category?: string }>;
  is_available?: boolean;
}

const deriveApiBase = () => {
  const url = getApiUrl();
  // Strip trailing graphql/ or graphql
  return url.replace(/graphql\/?$/i, '');
};

const PROXY_URL = `${deriveApiBase()}api/guardarian/transaction/`;

const buildRedirects = () => ({
  successful: 'https://confio.lat/checkout/success',
  cancelled: 'https://confio.lat/checkout/cancelled',
  failed: 'https://confio.lat/checkout/failed',
});

async function getAuthHeaders(): Promise<Record<string, string>> {
  try {
    const credentials = await Keychain.getGenericPassword({
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME,
    });
    if (!credentials || !credentials.password) return {};
    const parsed = JSON.parse(credentials.password);
    if (!parsed?.accessToken) return {};
    return { Authorization: `JWT ${parsed.accessToken}` };
  } catch (err) {
    console.warn('Guardarian proxy auth header error', err);
    return {};
  }
}

export async function fetchGuardarianFiatCurrencies(): Promise<GuardarianFiatCurrency[]> {
  const headers = {
    ...(await getAuthHeaders()),
  };
  const res = await fetch(`${deriveApiBase()}api/guardarian/fiat/`, {
    method: 'GET',
    headers,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || 'No se pudo cargar monedas fiat de Guardarian');
  }
  const data = await res.json();
  return data as GuardarianFiatCurrency[];
}

export async function createGuardarianTransaction(
  params: GuardarianTransactionParams
): Promise<GuardarianTransactionResponse> {
  const {
    amount,
    fromCurrency,
    fromNetwork,
    toCurrency = 'USDC',
    toNetwork,
    email,
    payoutAddress,
    customerCountry,
    locale,
    externalId,
  } = params;

  const body: any = {
    amount,
    from_amount: amount,
    from_currency: fromCurrency,
    to_currency: toCurrency,
    locale: locale || 'es',
    redirects: buildRedirects(),
  };

  if (fromNetwork) {
    body.from_network = fromNetwork;
  }

  if (toNetwork) {
    body.to_network = toNetwork;
  }

  if (customerCountry) {
    body.customer_country = customerCountry;
  }

  if (externalId) {
    body.external_partner_link_id = externalId;
  }

  if (email) {
    body.customer = {
      contact_info: {
        email,
      },
    };
  }

  if (payoutAddress) {
    body.payout_info = {
      payout_address: payoutAddress,
      skip_choose_payout_address: true,
    };
  }

  const headers = {
    'Content-Type': 'application/json',
    ...(await getAuthHeaders()),
  };

  const res = await fetch(PROXY_URL, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });

  let data: any = null;
  try {
    data = await res.json();
  } catch (parseErr) {
    console.warn('Guardarian create transaction parse error', parseErr);
  }

  if (!res.ok) {
    const apiError =
      data?.errors?.[0]?.reason ||
      data?.message ||
      data?.error ||
      `Guardarian request failed (${res.status})`;
    throw new Error(apiError);
  }

  return data as GuardarianTransactionResponse;
}

export interface GuardarianCryptoCurrency {
  ticker: string;
  name: string;
  network?: string;
  networks?: Array<{ name?: string; network?: string; ticker?: string }>;
}

export async function fetchGuardarianCryptoCurrencies(): Promise<GuardarianCryptoCurrency[]> {
  const CRYPTO_URL = `${deriveApiBase()}api/guardarian/currencies/crypto/`;

  const headers = {
    'Content-Type': 'application/json',
    ...(await getAuthHeaders()),
  };

  const res = await fetch(CRYPTO_URL, {
    method: 'GET',
    headers,
  });

  if (!res.ok) {
    console.warn(`Guardarian crypto currencies fetch failed (${res.status})`);
    return [];
  }

  let data: any = null;
  try {
    data = await res.json();
  } catch (parseErr) {
    console.warn('Guardarian crypto currencies parse error', parseErr);
    return [];
  }

  return (data || []) as GuardarianCryptoCurrency[];
}
