import { useState, useEffect } from 'react';
import { useQuery } from '@apollo/client';
import { GET_EXCHANGE_RATE_WITH_FALLBACK, GET_CURRENT_EXCHANGE_RATE } from '../apollo/queries';
import { useCountry } from '../contexts/CountryContext';
import { useAuth } from '../contexts/AuthContext';
import { getCurrencyForCountry } from '../utils/currencyMapping';
import { getCountryByIso } from '../utils/countries';

interface ExchangeRateResult {
  rate: number | null;
  loading: boolean;
  error: any;
  refetch: () => void;
  formatRate: (decimals?: number) => string;
}

/**
 * Hook for getting current exchange rate with fallback logic
 * Prioritizes: parallel -> average -> official rates
 */
export const useExchangeRate = (
  sourceCurrency: string = 'VES',
  targetCurrency: string = 'USD'
): ExchangeRateResult => {
  const { data, loading, error, refetch } = useQuery(GET_EXCHANGE_RATE_WITH_FALLBACK, {
    variables: {
      sourceCurrency,
      targetCurrency
    },
    fetchPolicy: 'cache-and-network',
    pollInterval: 15 * 60 * 1000, // Poll every 15 minutes
    notifyOnNetworkStatusChange: false
  });

  const rate = data?.exchangeRateWithFallback ? parseFloat(data.exchangeRateWithFallback) : null;

  const formatRate = (decimals: number = 2): string => {
    if (rate === null) return 'N/A';
    return rate.toFixed(decimals);
  };

  return {
    rate,
    loading,
    error,
    refetch,
    formatRate
  };
};

/**
 * Hook for getting specific exchange rate type
 */
export const useSpecificExchangeRate = (
  sourceCurrency: string = 'VES',
  targetCurrency: string = 'USD',
  rateType: string = 'parallel'
): ExchangeRateResult => {
  const { data, loading, error, refetch } = useQuery(GET_CURRENT_EXCHANGE_RATE, {
    variables: {
      sourceCurrency,
      targetCurrency,
      rateType
    },
    fetchPolicy: 'cache-and-network',
    pollInterval: 15 * 60 * 1000, // Poll every 15 minutes
    notifyOnNetworkStatusChange: false
  });

  const rate = data?.currentExchangeRate ? parseFloat(data.currentExchangeRate) : null;

  const formatRate = (decimals: number = 2): string => {
    if (rate === null) return 'N/A';
    return rate.toFixed(decimals);
  };

  return {
    rate,
    loading,
    error,
    refetch,
    formatRate
  };
};

/**
 * Hook for getting the exchange rate for the currently selected country
 * Shows what the current market rate is so users can set competitive P2P rates
 */
export const useSelectedCountryRate = () => {
  const { selectedCountry, userCountry } = useCountry();
  const { userProfile } = useAuth() as any;
  const profileCountry = userProfile?.phoneCountry ? getCountryByIso(userProfile.phoneCountry) : null;
  const countryToUse = selectedCountry || userCountry || profileCountry;
  const sourceCurrency = countryToUse ? getCurrencyForCountry(countryToUse as any) : 'USD';
  
  return useExchangeRate(sourceCurrency, 'USD');
};

/**
 * Hook for getting VES/USD reference rate (for backward compatibility)
 * @deprecated Use useSelectedCountryRate() instead for multi-currency support
 */
export const useVESUSDRate = () => {
  return useExchangeRate('VES', 'USD');
};

/**
 * Hook for calculating fiat equivalent of crypto amounts
 */
export const useCryptoToFiatCalculator = (
  cryptoSymbol: string = 'cUSD',
  fiatCurrency: string = 'VES'
) => {
  const { rate, loading, error } = useExchangeRate(fiatCurrency, 'USD');

  const calculateFiatAmount = (cryptoAmount: number, exchangeRate?: number): number => {
    // For cUSD, it's 1:1 with USD, so we just need to multiply by VES/USD rate
    // For other cryptos, you'd need their USD rate first
    
    if (cryptoSymbol === 'cUSD') {
      const usdToFiatRate = exchangeRate || rate;
      return usdToFiatRate ? cryptoAmount * usdToFiatRate : 0;
    }
    
    // For other cryptos, implement crypto->USD->fiat conversion
    return 0;
  };

  const formatFiatAmount = (cryptoAmount: number, exchangeRate?: number): string => {
    const fiatAmount = calculateFiatAmount(cryptoAmount, exchangeRate);
    
    if (fiatCurrency === 'VES') {
      // Format Venezuelan bolívars
      return `${fiatAmount.toLocaleString('es-VE', { 
        minimumFractionDigits: 2, 
        maximumFractionDigits: 2 
      })} ${fiatCurrency}`;
    }
    
    return `${fiatAmount.toFixed(2)} ${fiatCurrency}`;
  };

  return {
    rate,
    loading,
    error,
    calculateFiatAmount,
    formatFiatAmount
  };
};
