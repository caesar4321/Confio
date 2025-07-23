/**
 * Comprehensive number formatting utility based on user's country
 * Handles different number formatting conventions across countries
 */

import { useAuth } from '../contexts/AuthContext';

// Country code to locale mapping
const COUNTRY_TO_LOCALE: { [key: string]: string } = {
  // Latin America - Spanish with regional variations
  'AR': 'es-AR',  // Argentina: 1.234,56
  'BO': 'es-BO',  // Bolivia: 1.234,56
  'CL': 'es-CL',  // Chile: 1.234,56
  'CO': 'es-CO',  // Colombia: 1.234,56
  'CR': 'es-CR',  // Costa Rica: 1 234,56
  'CU': 'es-CU',  // Cuba: 1 234,56
  'DO': 'es-DO',  // Dominican Republic: 1,234.56
  'EC': 'es-EC',  // Ecuador: 1.234,56
  'SV': 'es-SV',  // El Salvador: 1,234.56
  'GT': 'es-GT',  // Guatemala: 1,234.56
  'HN': 'es-HN',  // Honduras: 1,234.56
  'MX': 'es-MX',  // Mexico: 1,234.56
  'NI': 'es-NI',  // Nicaragua: 1,234.56
  'PA': 'es-PA',  // Panama: 1,234.56
  'PY': 'es-PY',  // Paraguay: 1.234,56
  'PE': 'es-PE',  // Peru: 1,234.56
  'UY': 'es-UY',  // Uruguay: 1.234,56
  'VE': 'es-VE',  // Venezuela: 1.234,56
  
  // Brazil - Portuguese
  'BR': 'pt-BR',  // Brazil: 1.234,56
  
  // Caribbean
  'JM': 'en-JM',  // Jamaica: 1,234.56
  'TT': 'en-TT',  // Trinidad and Tobago: 1,234.56
  
  // North America
  'US': 'en-US',  // United States: 1,234.56
  'CA': 'en-CA',  // Canada: 1,234.56
  
  // Europe
  'ES': 'es-ES',  // Spain: 1.234,56
  'PT': 'pt-PT',  // Portugal: 1 234,56
  'GB': 'en-GB',  // United Kingdom: 1,234.56
  'DE': 'de-DE',  // Germany: 1.234,56
  'FR': 'fr-FR',  // France: 1 234,56
  'IT': 'it-IT',  // Italy: 1.234,56
  'NL': 'nl-NL',  // Netherlands: 1.234,56
  
  // Africa
  'NG': 'en-NG',  // Nigeria: 1,234.56
  'ZA': 'en-ZA',  // South Africa: 1 234.56
  'KE': 'en-KE',  // Kenya: 1,234.56
  'GH': 'en-GH',  // Ghana: 1,234.56
  
  // Asia
  'JP': 'ja-JP',  // Japan: 1,234.56
  'CN': 'zh-CN',  // China: 1,234.56
  'IN': 'en-IN',  // India: 1,23,456.78 (lakhs/crores system)
  'PH': 'en-PH',  // Philippines: 1,234.56
  'SG': 'en-SG',  // Singapore: 1,234.56
};

// Number formatting styles by region
export type NumberFormatStyle = 'decimal' | 'currency' | 'percent';

export interface NumberFormatOptions {
  style?: NumberFormatStyle;
  minimumFractionDigits?: number;
  maximumFractionDigits?: number;
  currency?: string;
  useGrouping?: boolean;
}

/**
 * Get the appropriate locale for a country code
 */
export function getLocaleForCountry(countryCode: string): string {
  return COUNTRY_TO_LOCALE[countryCode] || 'en-US';
}

/**
 * Format a number based on country conventions
 */
export function formatNumber(
  value: number,
  countryCode: string,
  options: NumberFormatOptions = {}
): string {
  const locale = getLocaleForCountry(countryCode);
  
  const formatOptions: Intl.NumberFormatOptions = {
    style: options.style || 'decimal',
    minimumFractionDigits: options.minimumFractionDigits ?? 2,
    maximumFractionDigits: options.maximumFractionDigits ?? 2,
    useGrouping: options.useGrouping ?? true,
  };
  
  if (options.style === 'currency' && options.currency) {
    formatOptions.currency = options.currency;
  }
  
  try {
    return new Intl.NumberFormat(locale, formatOptions).format(value);
  } catch (error) {
    console.error('Number formatting error:', error);
    // Fallback to basic formatting
    return value.toFixed(options.minimumFractionDigits || 2);
  }
}

/**
 * Format currency based on country conventions
 */
export function formatCurrency(
  value: number,
  countryCode: string,
  currencyCode: string,
  options: Omit<NumberFormatOptions, 'style' | 'currency'> = {}
): string {
  return formatNumber(value, countryCode, {
    ...options,
    style: 'currency',
    currency: currencyCode,
  });
}

/**
 * Hook to use number formatting based on user's country
 */
export function useNumberFormat() {
  const { userProfile } = useAuth();
  const userCountryCode = userProfile?.phoneCountry || 'US';
  
  return {
    /**
     * Format a number using user's country conventions
     */
    formatNumber: (value: number, options?: NumberFormatOptions) => 
      formatNumber(value, userCountryCode, options),
    
    /**
     * Format currency using user's country conventions
     */
    formatCurrency: (value: number, currencyCode: string, options?: Omit<NumberFormatOptions, 'style' | 'currency'>) =>
      formatCurrency(value, userCountryCode, currencyCode, options),
    
    /**
     * Format a number for a specific country (useful for trades)
     */
    formatNumberForCountry: (value: number, countryCode: string, options?: NumberFormatOptions) =>
      formatNumber(value, countryCode, options),
    
    /**
     * Get the decimal separator for user's country
     */
    getDecimalSeparator: () => {
      const formatted = formatNumber(1.1, userCountryCode, { minimumFractionDigits: 1 });
      return formatted.charAt(1);
    },
    
    /**
     * Get the thousands separator for user's country
     */
    getThousandsSeparator: () => {
      const formatted = formatNumber(1000, userCountryCode, { minimumFractionDigits: 0 });
      return formatted.charAt(1);
    },
    
    /**
     * Parse a localized number string back to number
     */
    parseLocalizedNumber: (value: string) => {
      const decimalSeparator = formatNumber(1.1, userCountryCode, { minimumFractionDigits: 1 }).charAt(1);
      const thousandsSeparator = formatNumber(1000, userCountryCode, { minimumFractionDigits: 0 }).charAt(1);
      
      // Remove thousands separators and normalize decimal separator
      let normalized = value.replace(new RegExp(`\\${thousandsSeparator}`, 'g'), '');
      if (decimalSeparator !== '.') {
        normalized = normalized.replace(decimalSeparator, '.');
      }
      
      return parseFloat(normalized);
    },
    
    userCountryCode,
    locale: getLocaleForCountry(userCountryCode),
  };
}

/**
 * Format number for display in input fields
 * This maintains the user's typing while showing proper formatting
 */
export function formatNumberInput(
  value: string,
  countryCode: string,
  options: { decimals?: number } = {}
): { formatted: string; raw: number } {
  const decimalSeparator = formatNumber(1.1, countryCode, { minimumFractionDigits: 1 }).charAt(1);
  const thousandsSeparator = formatNumber(1000, countryCode, { minimumFractionDigits: 0 }).charAt(1);
  
  // Remove all non-numeric characters except decimal separator
  let cleaned = value.replace(new RegExp(`[^0-9\\${decimalSeparator}]`, 'g'), '');
  
  // Ensure only one decimal separator
  const parts = cleaned.split(decimalSeparator);
  if (parts.length > 2) {
    cleaned = parts[0] + decimalSeparator + parts.slice(1).join('');
  }
  
  // Limit decimal places
  if (parts.length === 2 && options.decimals !== undefined) {
    parts[1] = parts[1].slice(0, options.decimals);
    cleaned = parts.join(decimalSeparator);
  }
  
  // Parse to number
  let normalized = cleaned.replace(new RegExp(`\\${thousandsSeparator}`, 'g'), '');
  if (decimalSeparator !== '.') {
    normalized = normalized.replace(decimalSeparator, '.');
  }
  const raw = parseFloat(normalized) || 0;
  
  // Format with thousands separators
  if (cleaned) {
    const [integerPart, decimalPart] = cleaned.split(decimalSeparator);
    const formattedInteger = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, thousandsSeparator);
    const formatted = decimalPart !== undefined 
      ? `${formattedInteger}${decimalSeparator}${decimalPart}`
      : formattedInteger;
    
    return { formatted, raw };
  }
  
  return { formatted: '', raw: 0 };
}