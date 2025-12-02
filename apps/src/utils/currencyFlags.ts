/**
 * Currency to flag mapping
 * Maps currency codes to their primary/most recognizable country flag
 */

export const CURRENCY_TO_FLAG: { [key: string]: string } = {
  // North America
  'USD': '🇺🇸',  // US Dollar
  'CAD': '🇨🇦',  // Canadian Dollar
  'MXN': '🇲🇽',  // Mexican Peso

  // South America
  'BRL': '🇧🇷',  // Brazilian Real
  'ARS': '🇦🇷',  // Argentine Peso
  'COP': '🇨🇴',  // Colombian Peso
  'PEN': '🇵🇪',  // Peruvian Sol
  'CLP': '🇨🇱',  // Chilean Peso
  'UYU': '🇺🇾',  // Uruguayan Peso
  'PYG': '🇵🇾',  // Paraguayan Guaraní
  'BOB': '🇧🇴',  // Bolivian Boliviano
  'VES': '🇻🇪',  // Venezuelan Bolívar
  'VEF': '🇻🇪',  // Venezuelan Bolívar (old)

  // Central America & Caribbean
  'GTQ': '🇬🇹',  // Guatemalan Quetzal
  'HNL': '🇭🇳',  // Honduran Lempira
  'NIO': '🇳🇮',  // Nicaraguan Córdoba
  'CRC': '🇨🇷',  // Costa Rican Colón
  'PAB': '🇵🇦',  // Panamanian Balboa
  'DOP': '🇩🇴',  // Dominican Peso
  'CUP': '🇨🇺',  // Cuban Peso
  'CUC': '🇨🇺',  // Cuban Convertible Peso
  'JMD': '🇯🇲',  // Jamaican Dollar
  'TTD': '🇹🇹',  // Trinidad and Tobago Dollar
  'BBD': '🇧🇧',  // Barbadian Dollar
  'BSD': '🇧🇸',  // Bahamian Dollar
  'BZD': '🇧🇿',  // Belize Dollar
  'XCD': '🇦🇬',  // East Caribbean Dollar
  'HTG': '🇭🇹',  // Haitian Gourde

  // Europe
  'EUR': '🇪🇺',  // Euro
  'GBP': '🇬🇧',  // British Pound
  'CHF': '🇨🇭',  // Swiss Franc
  'NOK': '🇳🇴',  // Norwegian Krone
  'SEK': '🇸🇪',  // Swedish Krona
  'DKK': '🇩🇰',  // Danish Krone
  'PLN': '🇵🇱',  // Polish Złoty
  'CZK': '🇨🇿',  // Czech Koruna
  'HUF': '🇭🇺',  // Hungarian Forint
  'RON': '🇷🇴',  // Romanian Leu
  'BGN': '🇧🇬',  // Bulgarian Lev
  'HRK': '🇭🇷',  // Croatian Kuna
  'RSD': '🇷🇸',  // Serbian Dinar
  'TRY': '🇹🇷',  // Turkish Lira
  'RUB': '🇷🇺',  // Russian Ruble
  'UAH': '🇺🇦',  // Ukrainian Hryvnia
  'ISK': '🇮🇸',  // Icelandic Króna
  'ALL': '🇦🇱',  // Albanian Lek
  'BAM': '🇧🇦',  // Bosnia Convertible Mark
  'MKD': '🇲🇰',  // Macedonian Denar
  'MDL': '🇲🇩',  // Moldovan Leu

  // Asia Pacific
  'JPY': '🇯🇵',  // Japanese Yen
  'CNY': '🇨🇳',  // Chinese Yuan
  'KRW': '🇰🇷',  // South Korean Won
  'INR': '🇮🇳',  // Indian Rupee
  'SGD': '🇸🇬',  // Singapore Dollar
  'HKD': '🇭🇰',  // Hong Kong Dollar
  'TWD': '🇹🇼',  // Taiwan Dollar
  'THB': '🇹🇭',  // Thai Baht
  'PHP': '🇵🇭',  // Philippine Peso
  'MYR': '🇲🇾',  // Malaysian Ringgit
  'IDR': '🇮🇩',  // Indonesian Rupiah
  'VND': '🇻🇳',  // Vietnamese Dong
  'AUD': '🇦🇺',  // Australian Dollar
  'NZD': '🇳🇿',  // New Zealand Dollar
  'PKR': '🇵🇰',  // Pakistani Rupee
  'BDT': '🇧🇩',  // Bangladeshi Taka
  'LKR': '🇱🇰',  // Sri Lankan Rupee
  'NPR': '🇳🇵',  // Nepalese Rupee
  'MMK': '🇲🇲',  // Myanmar Kyat
  'KHR': '🇰🇭',  // Cambodian Riel
  'LAK': '🇱🇦',  // Lao Kip
  'MNT': '🇲🇳',  // Mongolian Tögrög
  'KZT': '🇰🇿',  // Kazakhstani Tenge
  'UZS': '🇺🇿',  // Uzbekistani Som
  'KGS': '🇰🇬',  // Kyrgyzstani Som
  'TJS': '🇹🇯',  // Tajikistani Somoni
  'TMT': '🇹🇲',  // Turkmenistan Manat
  'AFN': '🇦🇫',  // Afghan Afghani

  // Middle East
  'AED': '🇦🇪',  // UAE Dirham
  'SAR': '🇸🇦',  // Saudi Riyal
  'ILS': '🇮🇱',  // Israeli Shekel
  'QAR': '🇶🇦',  // Qatari Riyal
  'KWD': '🇰🇼',  // Kuwaiti Dinar
  'BHD': '🇧🇭',  // Bahraini Dinar
  'OMR': '🇴🇲',  // Omani Rial
  'JOD': '🇯🇴',  // Jordanian Dinar
  'LBP': '🇱🇧',  // Lebanese Pound
  'SYP': '🇸🇾',  // Syrian Pound
  'IQD': '🇮🇶',  // Iraqi Dinar
  'YER': '🇾🇪',  // Yemeni Rial
  'IRR': '🇮🇷',  // Iranian Rial

  // Africa
  'ZAR': '🇿🇦',  // South African Rand
  'NGN': '🇳🇬',  // Nigerian Naira
  'EGP': '🇪🇬',  // Egyptian Pound
  'KES': '🇰🇪',  // Kenyan Shilling
  'GHS': '🇬🇭',  // Ghanaian Cedi
  'MAD': '🇲🇦',  // Moroccan Dirham
  'TND': '🇹🇳',  // Tunisian Dinar
  'ETB': '🇪🇹',  // Ethiopian Birr
  'UGX': '🇺🇬',  // Ugandan Shilling
  'TZS': '🇹🇿',  // Tanzanian Shilling
  'RWF': '🇷🇼',  // Rwandan Franc
  'ZMW': '🇿🇲',  // Zambian Kwacha
  'BWP': '🇧🇼',  // Botswana Pula
  'MUR': '🇲🇺',  // Mauritian Rupee
  'SCR': '🇸🇨',  // Seychellois Rupee
  'AOA': '🇦🇴',  // Angolan Kwanza
  'MZN': '🇲🇿',  // Mozambican Metical
  'ZWL': '🇿🇼',  // Zimbabwean Dollar
  'NAD': '🇳🇦',  // Namibian Dollar
  'SZL': '🇸🇿',  // Swazi Lilangeni
  'LSL': '🇱🇸',  // Lesotho Loti
  'MWK': '🇲🇼',  // Malawian Kwacha
  'GMD': '🇬🇲',  // Gambian Dalasi
  'SLL': '🇸🇱',  // Sierra Leonean Leone
  'LRD': '🇱🇷',  // Liberian Dollar
  'GNF': '🇬🇳',  // Guinean Franc
  'CDF': '🇨🇩',  // Congolese Franc
  'BIF': '🇧🇮',  // Burundian Franc
  'DJF': '🇩🇯',  // Djiboutian Franc
  'ERN': '🇪🇷',  // Eritrean Nakfa
  'SOS': '🇸🇴',  // Somali Shilling
  'SSP': '🇸🇸',  // South Sudanese Pound
  'SDG': '🇸🇩',  // Sudanese Pound
  'LYD': '🇱🇾',  // Libyan Dinar
  'DZD': '🇩🇿',  // Algerian Dinar
  'MRU': '🇲🇷',  // Mauritanian Ouguiya
  'CVE': '🇨🇻',  // Cape Verdean Escudo
  'STN': '🇸🇹',  // São Tomé Dobra
  'XOF': '🇸🇳',  // West African CFA Franc
  'XAF': '🇨🇲',  // Central African CFA Franc
  'KMF': '🇰🇲',  // Comorian Franc
  'XPF': '🇵🇫',  // CFP Franc
  'MGA': '🇲🇬',  // Malagasy Ariary
};

/**
 * Get flag emoji for a currency code
 * @param currencyCode ISO 4217 currency code (e.g., 'USD', 'EUR')
 * @returns Flag emoji or world emoji if not found
 */
export function getFlagForCurrency(currencyCode: string): string {
  return CURRENCY_TO_FLAG[currencyCode.toUpperCase()] || '🌎';
}
