import { useMemo } from 'react';
import { useCountry } from '../contexts/CountryContext';
import { 
  getCurrencyByCountry, 
  formatCurrencyAmount, 
  parseCurrencyAmount,
  formatExchangeRate,
  convertCurrency,
  Currency,
  currencies 
} from '../utils/currencies';

/**
 * Hook for currency operations based on selected country
 */
export const useCurrency = () => {
  const { selectedCountry, userCountry } = useCountry();
  
  // Get currency for selected country or fallback to user's country
  const currency = useMemo(() => {
    const countryToUse = selectedCountry || userCountry;
    if (!countryToUse) {
      // Default to Venezuelan Bolívar for Venezuela-focused app
      return currencies.VES;
    }
    
    const countryCurrency = getCurrencyByCountry(countryToUse[2]); // Use ISO code
    return countryCurrency || currencies.VES; // Fallback to VES
  }, [selectedCountry, userCountry]);
  
  // Currency formatting functions
  const formatAmount = useMemo(() => ({
    /**
     * Format amount with currency symbol
     */
    withSymbol: (amount: number | string) => 
      formatCurrencyAmount(amount, currency, { showSymbol: true }),
    
    /**
     * Format amount with currency code (clear and unambiguous)
     */
    withCode: (amount: number | string) => 
      formatCurrencyAmount(amount, currency, { showSymbol: true, preferCode: true }),
    
    /**
     * Format amount with both symbol and code
     */
    full: (amount: number | string) => 
      formatCurrencyAmount(amount, currency, { showSymbol: true, showCode: true }),
    
    /**
     * Format amount without currency indicators
     */
    plain: (amount: number | string) => 
      formatCurrencyAmount(amount, currency, { showSymbol: false, showCode: false }),
  }), [currency]);
  
  // Exchange rate operations for P2P trading
  const exchangeRate = useMemo(() => ({
    /**
     * Format exchange rate for display (e.g., "1 cUSD = 35.50 Bs.")
     */
    format: (rate: number, fromCurrencyCode: string) => {
      const fromCurrency = currencies[fromCurrencyCode as keyof typeof currencies];
      if (!fromCurrency) return `${rate} ${currency.symbol}`;
      return formatExchangeRate(rate, fromCurrency, currency);
    },
    
    /**
     * Convert crypto amount to local currency
     */
    convert: (cryptoAmount: number, rate: number, fromCurrencyCode: string) => {
      const fromCurrency = currencies[fromCurrencyCode as keyof typeof currencies];
      if (!fromCurrency) return formatAmount.withSymbol(cryptoAmount * rate);
      return convertCurrency(cryptoAmount, rate, fromCurrency, currency);
    },
  }), [currency, formatAmount]);
  
  // Parse currency input
  const parseAmount = useMemo(() => (amountString: string): number => {
    return parseCurrencyAmount(amountString, currency);
  }, [currency]);
  
  // Input formatting helpers for forms
  const inputFormatting = useMemo(() => ({
    /**
     * Format input value for display (with proper separators)
     */
    formatInput: (value: string): string => {
      const numValue = parseFloat(value.replace(/[^\d.-]/g, ''));
      if (isNaN(numValue)) return '';
      return formatAmount.plain(numValue);
    },
    
    /**
     * Clean input value for API submission
     */
    cleanInput: (value: string): number => {
      return parseAmount(value);
    },
    
    /**
     * Get placeholder text for amount inputs
     */
    getPlaceholder: (defaultAmount?: number): string => {
      const amount = defaultAmount || 100;
      return formatAmount.plain(amount);
    },
  }), [formatAmount, parseAmount]);
  
  // Validation helpers
  const validation = useMemo(() => ({
    /**
     * Check if amount string is valid for this currency
     */
    isValidAmount: (amountString: string): boolean => {
      try {
        const parsed = parseAmount(amountString);
        return !isNaN(parsed) && parsed > 0;
      } catch {
        return false;
      }
    },
    
    /**
     * Get minimum tradeable amount
     */
    getMinAmount: (): number => {
      return 1 / currency.minorUnit;
    },
    
    /**
     * Format validation error message
     */
    getAmountError: (amountString: string): string | null => {
      if (!amountString.trim()) return 'El monto es requerido';
      
      const parsed = parseAmount(amountString);
      if (isNaN(parsed)) return 'Formato de monto inválido';
      if (parsed <= 0) return 'El monto debe ser mayor a cero';
      if (parsed < validation.getMinAmount()) {
        return `El monto mínimo es ${formatAmount.withSymbol(validation.getMinAmount())}`;
      }
      
      return null;
    },
  }), [currency, parseAmount, formatAmount]);
  
  return {
    // Current currency info
    currency,
    currencyCode: currency.code,
    currencySymbol: currency.symbol,
    currencyName: currency.name,
    
    // Formatting functions
    formatAmount,
    parseAmount,
    exchangeRate,
    inputFormatting,
    validation,
    
    // Direct access to currency for advanced use cases
    getCurrencyInfo: () => currency,
  };
};

/**
 * Hook for working with specific currencies (not based on country)
 */
export const useCurrencyByCode = (currencyCode: string) => {
  const currency = useMemo(() => {
    return currencies[currencyCode as keyof typeof currencies] || currencies.USD;
  }, [currencyCode]);
  
  const formatAmount = useMemo(() => ({
    withSymbol: (amount: number | string) => 
      formatCurrencyAmount(amount, currency, { showSymbol: true }),
    withCode: (amount: number | string) => 
      formatCurrencyAmount(amount, currency, { showCode: true }),
    full: (amount: number | string) => 
      formatCurrencyAmount(amount, currency, { showSymbol: true, showCode: true }),
    plain: (amount: number | string) => 
      formatCurrencyAmount(amount, currency, { showSymbol: false, showCode: false }),
  }), [currency]);
  
  return {
    currency,
    formatAmount,
    parseAmount: (amountString: string) => parseCurrencyAmount(amountString, currency),
  };
};