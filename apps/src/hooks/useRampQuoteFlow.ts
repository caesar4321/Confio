import { useMemo } from 'react';
import { useQuery } from '@apollo/client';

import { GET_RAMP_QUOTE } from '../apollo/queries';
import { formatRampMoney } from '../utils/rampFormat';

type UseRampQuoteFlowParams = {
  direction: 'ON_RAMP' | 'OFF_RAMP';
  amount: string;
  countryCode?: string | null;
  fiatCurrency: string;
  paymentMethodCode?: string | null;
  enabled: boolean;
  minAmount?: number;
  maxAmount?: number;
  // The unit the user spends on an off-ramp — `US$` on the savings rail.
  assetUnit?: string;
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
  assetUnit = 'cUSD',
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
  const spendUnit = direction === 'ON_RAMP' ? fiatCurrency : assetUnit;
  const amountError = isBelowMin
    ? `El mínimo por operación es ${formatRampMoney(minAmount, spendUnit)}.`
    : isAboveMax
      ? `El máximo permitido es ${formatRampMoney(maxAmount, spendUnit)}.`
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
