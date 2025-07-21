/**
 * Mapping from country data to currency codes
 * Based on the countries data structure: [name, phone_code, iso_code, flag]
 */

// Country ISO code to currency mapping
const COUNTRY_TO_CURRENCY: { [key: string]: string } = {
  // Latin America (Primary focus)
  'VE': 'VES',  // Venezuela - Bolívar
  'AR': 'ARS',  // Argentina - Peso
  'CO': 'COP',  // Colombia - Peso
  'PE': 'PEN',  // Peru - Sol
  'CL': 'CLP',  // Chile - Peso
  'BO': 'BOB',  // Bolivia - Boliviano
  'UY': 'UYU',  // Uruguay - Peso
  'PY': 'PYG',  // Paraguay - Guaraní
  'BR': 'BRL',  // Brazil - Real
  'MX': 'MXN',  // Mexico - Peso
  'EC': 'USD',  // Ecuador - US Dollar (dollarized)
  'PA': 'USD',  // Panama - US Dollar (dollarized)
  'GT': 'GTQ',  // Guatemala - Quetzal
  'HN': 'HNL',  // Honduras - Lempira
  'SV': 'USD',  // El Salvador - US Dollar (dollarized)
  'NI': 'NIO',  // Nicaragua - Córdoba
  'CR': 'CRC',  // Costa Rica - Colón
  'DO': 'DOP',  // Dominican Republic - Peso
  'CU': 'CUP',  // Cuba - Peso
  'JM': 'JMD',  // Jamaica - Dollar
  'TT': 'TTD',  // Trinidad and Tobago - Dollar
  
  // North America
  'US': 'USD',  // United States - Dollar
  'CA': 'CAD',  // Canada - Dollar
  
  // Europe
  'GB': 'GBP',  // United Kingdom - Pound
  'DE': 'EUR',  // Germany - Euro
  'FR': 'EUR',  // France - Euro
  'ES': 'EUR',  // Spain - Euro
  'IT': 'EUR',  // Italy - Euro
  'PT': 'EUR',  // Portugal - Euro
  'NL': 'EUR',  // Netherlands - Euro
  'BE': 'EUR',  // Belgium - Euro
  'AT': 'EUR',  // Austria - Euro
  'IE': 'EUR',  // Ireland - Euro
  'FI': 'EUR',  // Finland - Euro
  'GR': 'EUR',  // Greece - Euro
  'CH': 'CHF',  // Switzerland - Franc
  'NO': 'NOK',  // Norway - Krone
  'SE': 'SEK',  // Sweden - Krona
  'DK': 'DKK',  // Denmark - Krone
  'PL': 'PLN',  // Poland - Złoty
  'CZ': 'CZK',  // Czech Republic - Koruna
  'HU': 'HUF',  // Hungary - Forint
  'RO': 'RON',  // Romania - Leu
  'BG': 'BGN',  // Bulgaria - Lev
  'HR': 'EUR',  // Croatia - Euro
  'RS': 'RSD',  // Serbia - Dinar
  'TR': 'TRY',  // Turkey - Lira
  'RU': 'RUB',  // Russia - Ruble
  'UA': 'UAH',  // Ukraine - Hryvnia
  
  // Asia Pacific
  'JP': 'JPY',  // Japan - Yen
  'CN': 'CNY',  // China - Yuan
  'KR': 'KRW',  // South Korea - Won
  'IN': 'INR',  // India - Rupee
  'SG': 'SGD',  // Singapore - Dollar
  'HK': 'HKD',  // Hong Kong - Dollar
  'TW': 'TWD',  // Taiwan - Dollar
  'TH': 'THB',  // Thailand - Baht
  'PH': 'PHP',  // Philippines - Peso
  'MY': 'MYR',  // Malaysia - Ringgit
  'ID': 'IDR',  // Indonesia - Rupiah
  'VN': 'VND',  // Vietnam - Dong
  'AU': 'AUD',  // Australia - Dollar
  'NZ': 'NZD',  // New Zealand - Dollar
  
  // Middle East & Africa
  'AE': 'AED',  // UAE - Dirham
  'SA': 'SAR',  // Saudi Arabia - Riyal
  'IL': 'ILS',  // Israel - Shekel
  'EG': 'EGP',  // Egypt - Pound
  'ZA': 'ZAR',  // South Africa - Rand
  'NG': 'NGN',  // Nigeria - Naira
  'KE': 'KES',  // Kenya - Shilling
  'GH': 'GHS',  // Ghana - Cedi
  'MA': 'MAD',  // Morocco - Dirham
  'TN': 'TND',  // Tunisia - Dinar
};

// Currency symbols
const CURRENCY_SYMBOLS: { [key: string]: string } = {
  'USD': '$',
  'VES': 'Bs.',
  'ARS': '$',
  'COP': '$',
  'PEN': 'S/',
  'CLP': '$',
  'BOB': 'Bs.',
  'UYU': '$U',
  'PYG': '₲',
  'BRL': 'R$',
  'MXN': '$',
  'EUR': '€',
  'GBP': '£',
  'CAD': 'C$',
  'JPY': '¥',
  'CNY': '¥',
  'KRW': '₩',
  'INR': '₹',
  'SGD': 'S$',
  'AUD': 'A$',
  'CHF': 'CHF',
  'THB': '฿',
  'PHP': '₱',
  'MYR': 'RM',
  'IDR': 'Rp',
  'VND': '₫',
  'TRY': '₺',
  'ZAR': 'R',
  'AED': 'د.إ',
  'SAR': '﷼',
};

export type Country = [string, string, string, string]; // [name, phone_code, iso_code, flag]

/**
 * Get currency code for a country
 * @param country Country array [name, phone_code, iso_code, flag] or null
 * @returns Currency code (e.g., 'VES', 'USD', 'EUR')
 */
export function getCurrencyForCountry(country: Country | null): string {
  if (!country) return 'USD'; // Default fallback
  
  const countryCode = country[2]; // ISO code is at index 2
  return COUNTRY_TO_CURRENCY[countryCode] || 'USD';
}

/**
 * Get currency symbol for a currency code
 * @param currencyCode Currency code (e.g., 'VES', 'USD')
 * @returns Currency symbol (e.g., 'Bs.', '$')
 */
export function getCurrencySymbol(currencyCode: string): string {
  return CURRENCY_SYMBOLS[currencyCode] || currencyCode;
}

/**
 * Check if we have exchange rate data for this currency
 * @param currencyCode Currency code to check
 * @returns True if supported
 */
export function isCurrencySupported(currencyCode: string): boolean {
  return currencyCode in CURRENCY_SYMBOLS;
}

/**
 * Get display name for currency with country context
 * @param country Country data
 * @returns Display string like "Venezuelan Bolívar (VES)" or "US Dollar (USD)"
 */
export function getCurrencyDisplayName(country: Country | null): string {
  if (!country) return 'US Dollar (USD)';
  
  const currencyCode = getCurrencyForCountry(country);
  const countryName = country[0]; // Country name is at index 0
  
  // Special cases for common currencies
  if (currencyCode === 'USD') return 'US Dollar (USD)';
  if (currencyCode === 'EUR') return 'Euro (EUR)';
  
  return `${countryName} Currency (${currencyCode})`;
}