"""
Mapping from country ISO codes to their respective currencies
Used to determine which exchange rate to show based on selected country
"""

# Country code (ISO 3166-1 alpha-2) to currency code (ISO 4217) mapping
COUNTRY_TO_CURRENCY = {
    # Latin America (Primary focus)
    'VE': 'VES',  # Venezuela - Bolívar
    'AR': 'ARS',  # Argentina - Peso
    'CO': 'COP',  # Colombia - Peso
    'PE': 'PEN',  # Peru - Sol
    'CL': 'CLP',  # Chile - Peso
    'BO': 'BOB',  # Bolivia - Boliviano
    'UY': 'UYU',  # Uruguay - Peso
    'PY': 'PYG',  # Paraguay - Guaraní
    'BR': 'BRL',  # Brazil - Real
    'MX': 'MXN',  # Mexico - Peso
    'EC': 'USD',  # Ecuador - US Dollar (dollarized)
    'PA': 'USD',  # Panama - US Dollar (dollarized)
    'GT': 'GTQ',  # Guatemala - Quetzal
    'HN': 'HNL',  # Honduras - Lempira
    'SV': 'USD',  # El Salvador - US Dollar (dollarized)
    'NI': 'NIO',  # Nicaragua - Córdoba
    'CR': 'CRC',  # Costa Rica - Colón
    'DO': 'DOP',  # Dominican Republic - Peso
    'CU': 'CUP',  # Cuba - Peso
    'JM': 'JMD',  # Jamaica - Dollar
    'TT': 'TTD',  # Trinidad and Tobago - Dollar
    
    # North America
    'US': 'USD',  # United States - Dollar
    'CA': 'CAD',  # Canada - Dollar
    
    # Europe
    'GB': 'GBP',  # United Kingdom - Pound
    'EU': 'EUR',  # European Union - Euro
    'DE': 'EUR',  # Germany - Euro
    'FR': 'EUR',  # France - Euro
    'ES': 'EUR',  # Spain - Euro
    'IT': 'EUR',  # Italy - Euro
    'PT': 'EUR',  # Portugal - Euro
    'NL': 'EUR',  # Netherlands - Euro
    'BE': 'EUR',  # Belgium - Euro
    'AT': 'EUR',  # Austria - Euro
    'IE': 'EUR',  # Ireland - Euro
    'FI': 'EUR',  # Finland - Euro
    'GR': 'EUR',  # Greece - Euro
    'CH': 'CHF',  # Switzerland - Franc
    'NO': 'NOK',  # Norway - Krone
    'SE': 'SEK',  # Sweden - Krona
    'DK': 'DKK',  # Denmark - Krone
    'PL': 'PLN',  # Poland - Złoty
    'CZ': 'CZK',  # Czech Republic - Koruna
    'HU': 'HUF',  # Hungary - Forint
    'RO': 'RON',  # Romania - Leu
    'BG': 'BGN',  # Bulgaria - Lev
    'HR': 'EUR',  # Croatia - Euro (adopted 2023)
    'RS': 'RSD',  # Serbia - Dinar
    'TR': 'TRY',  # Turkey - Lira
    'RU': 'RUB',  # Russia - Ruble
    'UA': 'UAH',  # Ukraine - Hryvnia
    
    # Asia Pacific
    'JP': 'JPY',  # Japan - Yen
    'CN': 'CNY',  # China - Yuan
    'KR': 'KRW',  # South Korea - Won
    'IN': 'INR',  # India - Rupee
    'SG': 'SGD',  # Singapore - Dollar
    'HK': 'HKD',  # Hong Kong - Dollar
    'TW': 'TWD',  # Taiwan - Dollar
    'TH': 'THB',  # Thailand - Baht
    'PH': 'PHP',  # Philippines - Peso
    'MY': 'MYR',  # Malaysia - Ringgit
    'ID': 'IDR',  # Indonesia - Rupiah
    'VN': 'VND',  # Vietnam - Dong
    'AU': 'AUD',  # Australia - Dollar
    'NZ': 'NZD',  # New Zealand - Dollar
    
    # Middle East & Africa
    'AE': 'AED',  # UAE - Dirham
    'SA': 'SAR',  # Saudi Arabia - Riyal
    'IL': 'ILS',  # Israel - Shekel
    'EG': 'EGP',  # Egypt - Pound
    'ZA': 'ZAR',  # South Africa - Rand
    'NG': 'NGN',  # Nigeria - Naira
    'KE': 'KES',  # Kenya - Shilling
    'GH': 'GHS',  # Ghana - Cedi
    'MA': 'MAD',  # Morocco - Dirham
    'TN': 'TND',  # Tunisia - Dinar
}

# Currency code to currency name mapping
CURRENCY_NAMES = {
    'USD': 'US Dollar',
    'VES': 'Venezuelan Bolívar',
    'ARS': 'Argentine Peso',
    'COP': 'Colombian Peso',
    'PEN': 'Peruvian Sol',
    'CLP': 'Chilean Peso',
    'BOB': 'Bolivian Boliviano',
    'UYU': 'Uruguayan Peso',
    'PYG': 'Paraguayan Guaraní',
    'BRL': 'Brazilian Real',
    'MXN': 'Mexican Peso',
    'EUR': 'Euro',
    'GBP': 'British Pound',
    'CAD': 'Canadian Dollar',
    'JPY': 'Japanese Yen',
    'CNY': 'Chinese Yuan',
    'KRW': 'South Korean Won',
    'INR': 'Indian Rupee',
    'SGD': 'Singapore Dollar',
    'AUD': 'Australian Dollar',
    'CHF': 'Swiss Franc',
    'THB': 'Thai Baht',
    'PHP': 'Philippine Peso',
    'MYR': 'Malaysian Ringgit',
    'IDR': 'Indonesian Rupiah',
    'VND': 'Vietnamese Dong',
    'TRY': 'Turkish Lira',
    'ZAR': 'South African Rand',
    'AED': 'UAE Dirham',
    'SAR': 'Saudi Riyal',
}

# Currency symbols mapping
CURRENCY_SYMBOLS = {
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
}


def get_currency_for_country(country_code: str) -> str:
    """
    Get the currency code for a given country ISO code
    Returns USD as fallback for unknown countries
    """
    return COUNTRY_TO_CURRENCY.get(country_code.upper(), 'USD')


def get_currency_name(currency_code: str) -> str:
    """
    Get the human-readable name for a currency code
    """
    return CURRENCY_NAMES.get(currency_code.upper(), currency_code)


def get_currency_symbol(currency_code: str) -> str:
    """
    Get the symbol for a currency code
    """
    return CURRENCY_SYMBOLS.get(currency_code.upper(), currency_code)


def is_currency_supported(currency_code: str) -> bool:
    """
    Check if a currency is supported by our exchange rate system
    """
    return currency_code.upper() in CURRENCY_NAMES