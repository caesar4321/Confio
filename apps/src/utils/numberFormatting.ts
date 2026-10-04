/**
 * Comprehensive number formatting utility based on user's country
 * Handles different number formatting conventions across countries
 */

import { useNumberLocale } from '../contexts/NumberLocaleProvider';
import {
  formatDecimal, getNumberLocaleCountry, getSeparators, parseAmountInput, sanitizeAmountInput, separatorsForCountry,
} from './numberLocale';

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
 * Format a number based on country conventions.
 *
 * Deterministic (utils/numberLocale): no Intl, whose output varies by device
 * (Hermes/Android use the phone's locale data) and which does not group
 * 4-digit numbers in some locales.
 */
export function formatNumber(
  value: number,
  countryCode: string,
  options: NumberFormatOptions = {}
): string {
  // Defaults are 2 decimals, but a caller that only caps the maximum (counts:
  // `{ maximumFractionDigits: 0 }`) must not keep the default minimum of 2.
  const minimumFractionDigits =
    options.minimumFractionDigits ?? Math.min(2, options.maximumFractionDigits ?? 2);
  const maximumFractionDigits =
    options.maximumFractionDigits ?? Math.max(2, minimumFractionDigits);
  const text = formatDecimal(value, {
    decimals: maximumFractionDigits,
    minDecimals: minimumFractionDigits,
    grouping: options.useGrouping ?? true,
    separators: separatorsForCountry(countryCode),
  });
  if (options.style === 'currency' && options.currency) {
    const prefix = options.currency === 'USD' ? 'US$' : `${options.currency} `;
    return text.startsWith('-') ? `-${prefix}${text.slice(1)}` : `${prefix}${text}`;
  }
  return text;
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
 * Hook to use number formatting based on the user's country (the app-wide
 * setting kept by NumberLocaleProvider; re-renders when it changes).
 */
export function useNumberFormat() {
  useNumberLocale();
  const userCountryCode = getNumberLocaleCountry() || 'US';
  const separators = getSeparators();

  return {
    /** Format a number using the user's country conventions */
    formatNumber: (value: number, options?: NumberFormatOptions) =>
      formatNumber(value, userCountryCode, options),

    /** Format currency using the user's country conventions */
    formatCurrency: (value: number, currencyCode: string, options?: Omit<NumberFormatOptions, 'style' | 'currency'>) =>
      formatCurrency(value, userCountryCode, currencyCode, options),

    /** Format a number for a specific country (useful for trades) */
    formatNumberForCountry: (value: number, countryCode: string, options?: NumberFormatOptions) =>
      formatNumber(value, countryCode, options),

    getDecimalSeparator: () => separators.decimal,
    getThousandsSeparator: () => separators.group,

    /** Parse what the user typed (either decimal key) back to a number. */
    parseLocalizedNumber: (value: string) => parseAmountInput(value, separators),

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
  const separators = separatorsForCountry(countryCode);
  const formatted = sanitizeAmountInput(value, options.decimals ?? 2, separators);
  if (!formatted) return { formatted: '', raw: 0 };
  const raw = parseAmountInput(formatted, separators);
  return { formatted, raw: Number.isFinite(raw) ? raw : 0 };
}
