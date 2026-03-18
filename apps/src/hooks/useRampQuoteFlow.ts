import { useMemo } from 'react';
import { useQuery } from '@apollo/client';

import { GET_RAMP_QUOTE } from '../apollo/queries';

type UseRampQuoteFlowParams = {
  direction: 'ON_RAMP' | 'OFF_RAMP';
  amount: string;
  countryCode?: string | null;
  fiatCurrency: string;
  paymentMethodCode?: string | null;
  enabled: boolean;
  minAmount?: number;
  maxAmount?: number;
};

export const formatRampMoney = (value?: string | number | null, code?: string | null) => {
  const parsed = Number(value || 0);
  if (!Number.isFinite(parsed)) {
    return '--';
  }
  const displayCode = ['USDC Polygon', 'USDC Solana', 'USDC-a'].includes(code || '') ? 'cUSD' : code;
  return `${parsed.toLocaleString('es-AR', {
    minimumFractionDigits: parsed >= 100 ? 0 : 2,
    maximumFractionDigits: 2,
  })} ${displayCode || ''}`.trim();
};

export const formatRampRate = (value?: string | number | null, code?: string | null) => {
  const parsed = Number(value || 0);
  if (!Number.isFinite(parsed)) {
    return '--';
  }
  return `${parsed.toLocaleString('es-AR', {
    minimumFractionDigits: parsed >= 100 ? 2 : 4,
    maximumFractionDigits: 4,
  })} ${code || ''}`.trim();
};

export const useRampQuoteFlow = ({
  direction,
  amount,
  countryCode,
  fiatCurrency,
  paymentMethodCode,
  enabled,
  minAmount = 0,
  maxAmount = 0,
}: UseRampQuoteFlowParams) => {
  const parsedAmount = useMemo(() => Number((amount || '').replace(',', '.')), [amount]);
  const amountReady = Number.isFinite(parsedAmount) && parsedAmount > 0 && !!countryCode;
  const quoteReady = enabled && amountReady && (direction === 'OFF_RAMP' || !!paymentMethodCode);

  const { data, loading, error } = useQuery(GET_RAMP_QUOTE, {
    variables: {
      direction,
      amount: String(parsedAmount || ''),
      countryCode,
      fiatCurrency,
      paymentMethodCode,
    },
    skip: !quoteReady,
    fetchPolicy: 'cache-and-network',
  });

  const quote = data?.rampQuote;
  const isBelowMin = amountReady && minAmount > 0 && parsedAmount < minAmount;
  const isAboveMax = amountReady && maxAmount > 0 && parsedAmount > maxAmount;
  const amountError = isBelowMin
    ? `El mínimo por operación es ${formatRampMoney(minAmount, direction === 'ON_RAMP' ? fiatCurrency : 'cUSD')}.`
    : isAboveMax
      ? `El máximo permitido es ${formatRampMoney(maxAmount, direction === 'ON_RAMP' ? fiatCurrency : 'cUSD')}.`
      : null;

  return {
    parsedAmount,
    amountReady,
    quoteReady,
    quote,
    quoteLoading: loading,
    quoteError: error,
    amountError,
  };
};

export const validateRampContinue = ({
  hasSelectedMethod,
  amountReady,
  quoteLoading,
  quoteError,
  quote,
  amountError,
}: {
  hasSelectedMethod: boolean;
  amountReady: boolean;
  quoteLoading: boolean;
  quoteError?: { message?: string | null } | null;
  quote?: unknown;
  amountError?: string | null;
}) => {
  if (!hasSelectedMethod) {
    return 'Selecciona un método';
  }
  if (!amountReady) {
    return 'Monto inválido';
  }
  if (quoteLoading) {
    return 'Cotización en proceso';
  }
  if (quoteError) {
    return quoteError.message || 'No pudimos cotizar';
  }
  if (!quote) {
    return 'Cotización no disponible';
  }
  if (amountError) {
    return amountError;
  }
  return null;
};
