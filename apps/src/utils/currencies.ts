// Comprehensive currency data system for P2P trading
// Maps countries to their local currencies with full metadata

export interface Currency {
  code: string;           // ISO 4217 currency code (e.g., 'USD', 'EUR', 'VES')
  name: string;           // Full currency name
  symbol: string;         // Currency symbol (e.g., '$', '€', 'Bs.')
  symbolPosition: 'before' | 'after'; // Symbol position relative to amount
  decimals: number;       // Number of decimal places
  thousandsSeparator: string; // Thousands separator (',' or '.')
  decimalSeparator: string;   // Decimal separator ('.' or ',')
  minorUnit: number;      // Minor unit (e.g., 100 for cents)
}

// Currency definitions with proper formatting rules
export const currencies: { [key: string]: Currency } = {
  // Major currencies
  USD: {
    code: 'USD',
    name: 'US Dollar',
    symbol: '$',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  EUR: {
    code: 'EUR',
    name: 'Euro',
    symbol: '€',
    symbolPosition: 'after',
    decimals: 2,
    thousandsSeparator: '.',
    decimalSeparator: ',',
    minorUnit: 100,
  },
  GBP: {
    code: 'GBP',
    name: 'British Pound',
    symbol: '£',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  
  // Latin America
  VES: {
    code: 'VES',
    name: 'Venezuelan Bolívar',
    symbol: 'Bs.',
    symbolPosition: 'after',
    decimals: 2,
    thousandsSeparator: '.',
    decimalSeparator: ',',
    minorUnit: 100,
  },
  ARS: {
    code: 'ARS',
    name: 'Argentine Peso',
    symbol: '$',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: '.',
    decimalSeparator: ',',
    minorUnit: 100,
  },
  BRL: {
    code: 'BRL',
    name: 'Brazilian Real',
    symbol: 'R$',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: '.',
    decimalSeparator: ',',
    minorUnit: 100,
  },
  CLP: {
    code: 'CLP',
    name: 'Chilean Peso',
    symbol: '$',
    symbolPosition: 'before',
    decimals: 0,
    thousandsSeparator: '.',
    decimalSeparator: ',',
    minorUnit: 1,
  },
  COP: {
    code: 'COP',
    name: 'Colombian Peso',
    symbol: '$',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: '.',
    decimalSeparator: ',',
    minorUnit: 100,
  },
  MXN: {
    code: 'MXN',
    name: 'Mexican Peso',
    symbol: '$',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  PEN: {
    code: 'PEN',
    name: 'Peruvian Sol',
    symbol: 'S/',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  UYU: {
    code: 'UYU',
    name: 'Uruguayan Peso',
    symbol: '$U',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: '.',
    decimalSeparator: ',',
    minorUnit: 100,
  },
  
  // Asia
  CNY: {
    code: 'CNY',
    name: 'Chinese Yuan',
    symbol: '¥',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  JPY: {
    code: 'JPY',
    name: 'Japanese Yen',
    symbol: '¥',
    symbolPosition: 'before',
    decimals: 0,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 1,
  },
  KRW: {
    code: 'KRW',
    name: 'South Korean Won',
    symbol: '₩',
    symbolPosition: 'before',
    decimals: 0,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 1,
  },
  INR: {
    code: 'INR',
    name: 'Indian Rupee',
    symbol: '₹',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  IDR: {
    code: 'IDR',
    name: 'Indonesian Rupiah',
    symbol: 'Rp',
    symbolPosition: 'before',
    decimals: 0,
    thousandsSeparator: '.',
    decimalSeparator: ',',
    minorUnit: 1,
  },
  THB: {
    code: 'THB',
    name: 'Thai Baht',
    symbol: '฿',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  VND: {
    code: 'VND',
    name: 'Vietnamese Dong',
    symbol: '₫',
    symbolPosition: 'after',
    decimals: 0,
    thousandsSeparator: '.',
    decimalSeparator: ',',
    minorUnit: 1,
  },
  
  // Europe
  RUB: {
    code: 'RUB',
    name: 'Russian Ruble',
    symbol: '₽',
    symbolPosition: 'after',
    decimals: 2,
    thousandsSeparator: ' ',
    decimalSeparator: ',',
    minorUnit: 100,
  },
  PLN: {
    code: 'PLN',
    name: 'Polish Zloty',
    symbol: 'zł',
    symbolPosition: 'after',
    decimals: 2,
    thousandsSeparator: ' ',
    decimalSeparator: ',',
    minorUnit: 100,
  },
  CZK: {
    code: 'CZK',
    name: 'Czech Koruna',
    symbol: 'Kč',
    symbolPosition: 'after',
    decimals: 2,
    thousandsSeparator: ' ',
    decimalSeparator: ',',
    minorUnit: 100,
  },
  
  // Africa
  NGN: {
    code: 'NGN',
    name: 'Nigerian Naira',
    symbol: '₦',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  ZAR: {
    code: 'ZAR',
    name: 'South African Rand',
    symbol: 'R',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ' ',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  EGP: {
    code: 'EGP',
    name: 'Egyptian Pound',
    symbol: 'E£',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  
  // Middle East
  AED: {
    code: 'AED',
    name: 'UAE Dirham',
    symbol: 'د.إ',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  SAR: {
    code: 'SAR',
    name: 'Saudi Riyal',
    symbol: '﷼',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  
  // Other major currencies
  CAD: {
    code: 'CAD',
    name: 'Canadian Dollar',
    symbol: 'C$',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  AUD: {
    code: 'AUD',
    name: 'Australian Dollar',
    symbol: 'A$',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: ',',
    decimalSeparator: '.',
    minorUnit: 100,
  },
  CHF: {
    code: 'CHF',
    name: 'Swiss Franc',
    symbol: 'CHF',
    symbolPosition: 'before',
    decimals: 2,
    thousandsSeparator: "'",
    decimalSeparator: '.',
    minorUnit: 100,
  },
};

// Country ISO code to currency code mapping
export const countryToCurrency: { [countryIso: string]: string } = {
  // North America
  'US': 'USD',
  'CA': 'CAD',
  'MX': 'MXN',
  
  // Europe
  'DE': 'EUR', 'FR': 'EUR', 'IT': 'EUR', 'ES': 'EUR', 'NL': 'EUR',
  'BE': 'EUR', 'AT': 'EUR', 'PT': 'EUR', 'FI': 'EUR', 'IE': 'EUR',
  'LU': 'EUR', 'SI': 'EUR', 'SK': 'EUR', 'EE': 'EUR', 'LV': 'EUR',
  'LT': 'EUR', 'MT': 'EUR', 'CY': 'EUR', 'GR': 'EUR',
  'GB': 'GBP',
  'CH': 'CHF',
  'RU': 'RUB',
  'PL': 'PLN',
  'CZ': 'CZK',
  
  // Latin America
  'VE': 'VES',
  'AR': 'ARS',
  'BR': 'BRL',
  'CL': 'CLP',
  'CO': 'COP',
  'PE': 'PEN',
  'UY': 'UYU',
  
  // Asia
  'CN': 'CNY',
  'JP': 'JPY',
  'KR': 'KRW',
  'IN': 'INR',
  'ID': 'IDR',
  'TH': 'THB',
  'VN': 'VND',
  
  // Africa
  'NG': 'NGN',
  'ZA': 'ZAR',
  'EG': 'EGP',
  
  // Middle East
  'AE': 'AED',
  'SA': 'SAR',
  
  // Oceania
  'AU': 'AUD',
  'NZ': 'NZD',
};

// Helper functions for currency operations

/**
 * Get currency information by country ISO code
 */
export const getCurrencyByCountry = (countryIso: string): Currency | undefined => {
  const currencyCode = countryToCurrency[countryIso];
  return currencyCode ? currencies[currencyCode] : undefined;
};

/**
 * Get currency information by currency code
 */
export const getCurrencyByCode = (currencyCode: string): Currency | undefined => {
  return currencies[currencyCode];
};

/**
 * Format amount according to currency rules
 */
export const formatCurrencyAmount = (
  amount: number | string,
  currency: Currency,
  options: {
    showSymbol?: boolean;
    showCode?: boolean;
    preferCode?: boolean; // Prefer code over symbol for clarity
  } = {}
): string => {
  const { showSymbol = true, showCode = false, preferCode = false } = options;
  
  const numAmount = typeof amount === 'string' ? parseFloat(amount) : amount;
  if (isNaN(numAmount)) return '0';
  
  // Format number with proper decimal places
  const formattedNumber = numAmount.toFixed(currency.decimals);
  
  // Split into integer and decimal parts
  const [integerPart, decimalPart] = formattedNumber.split('.');
  
  // Add thousands separators
  const formattedInteger = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, currency.thousandsSeparator);
  
  // Combine parts
  let result = formattedInteger;
  if (currency.decimals > 0 && decimalPart) {
    result += currency.decimalSeparator + decimalPart;
  }
  
  // Add symbol/code - prefer code for clarity when preferCode is true
  if (preferCode && showSymbol) {
    // Show code instead of symbol for clarity
    result = result + ' ' + currency.code;
  } else if (showSymbol) {
    if (currency.symbolPosition === 'before') {
      result = currency.symbol + result;
    } else {
      result = result + ' ' + currency.symbol;
    }
  }
  
  if (showCode && !preferCode) {
    result = result + ' ' + currency.code;
  }
  
  return result;
};

/**
 * Parse currency amount string to number
 */
export const parseCurrencyAmount = (
  amountString: string,
  currency: Currency
): number => {
  // Remove currency symbol and code
  let cleanString = amountString
    .replace(currency.symbol, '')
    .replace(currency.code, '')
    .trim();
  
  // Handle thousands separators and decimal separators
  if (currency.thousandsSeparator !== currency.decimalSeparator) {
    // Remove thousands separators
    cleanString = cleanString.replace(new RegExp('\\' + currency.thousandsSeparator, 'g'), '');
    // Replace decimal separator with dot
    cleanString = cleanString.replace(currency.decimalSeparator, '.');
  }
  
  return parseFloat(cleanString) || 0;
};

/**
 * Get exchange rate display format for P2P trading
 */
export const formatExchangeRate = (
  rate: number,
  fromCurrency: Currency,
  toCurrency: Currency
): string => {
  const formattedRate = formatCurrencyAmount(rate, toCurrency, { showSymbol: true, preferCode: true });
  return `1 ${fromCurrency.code} = ${formattedRate}`;
};

/**
 * Calculate equivalent amount in different currency
 */
export const convertCurrency = (
  amount: number,
  rate: number,
  fromCurrency: Currency,
  toCurrency: Currency
): string => {
  const convertedAmount = amount * rate;
  return formatCurrencyAmount(convertedAmount, toCurrency, { showSymbol: true, preferCode: true });
};

/**
 * Get list of supported currencies for a region
 */
export const getCurrenciesByRegion = (region: 'americas' | 'europe' | 'asia' | 'africa' | 'oceania'): Currency[] => {
  const regionMappings = {
    americas: ['USD', 'CAD', 'MXN', 'VES', 'ARS', 'BRL', 'CLP', 'COP', 'PEN', 'UYU'],
    europe: ['EUR', 'GBP', 'CHF', 'RUB', 'PLN', 'CZK'],
    asia: ['CNY', 'JPY', 'KRW', 'INR', 'IDR', 'THB', 'VND'],
    africa: ['NGN', 'ZAR', 'EGP'],
    oceania: ['AUD'],
  };
  
  return regionMappings[region].map(code => currencies[code]).filter(Boolean);
};

/**
 * Validate currency amount format
 */
export const isValidCurrencyAmount = (
  amountString: string,
  currency: Currency
): boolean => {
  try {
    const parsed = parseCurrencyAmount(amountString, currency);
    return !isNaN(parsed) && parsed >= 0;
  } catch {
    return false;
  }
};

/**
 * Get minimum tradeable amount for currency (usually 1 unit)
 */
export const getMinimumAmount = (currency: Currency): number => {
  return 1 / currency.minorUnit;
};

// Export types
export type CurrencyCode = keyof typeof currencies;
export type CountryIso = keyof typeof countryToCurrency;