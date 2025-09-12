"""
Default payment methods for P2P exchange system.
Payment methods are organized by country to provide region-specific options.
"""

# Global payment methods available in multiple countries
GLOBAL_PAYMENT_METHODS = [
    {
        'name': 'efectivo',
        'display_name': 'Efectivo',
        'icon': 'dollar-sign',
        'is_active': True,  # Note: Removed from high-inflation countries like Venezuela
    },
    {
        'name': 'paypal',
        'display_name': 'PayPal',
        'icon': 'credit-card',
        'is_active': True,
    },
    {
        'name': 'wise',
        'display_name': 'Wise (TransferWise)',
        'icon': 'credit-card',
        'is_active': True,
    },
    {
        'name': 'binance_pay',
        'display_name': 'Binance Pay',
        'icon': 'credit-card',
        'is_active': True,
    },
    {
        'name': 'skrill',
        'display_name': 'Skrill',
        'icon': 'credit-card',
        'is_active': True,
    },
]

# Country-specific payment methods
COUNTRY_PAYMENT_METHODS = {
    'VE': [  # Venezuela
        {
            'name': 'banco_venezuela',
            'display_name': 'Banco Venezuela',
            'icon': 'bank',
            'is_active': True,
        },
        {
            'name': 'mercantil',
            'display_name': 'Mercantil',
            'icon': 'bank',
            'is_active': True,
        },
        {
            'name': 'banesco',
            'display_name': 'Banesco',
            'icon': 'bank',
            'is_active': True,
        },
        {
            'name': 'pago_movil',
            'display_name': 'Pago Móvil',
            'icon': 'smartphone',
            'is_active': True,
        },
        {
            'name': 'zelle',
            'display_name': 'Zelle',
            'icon': 'credit-card',
            'is_active': True,
        },
        {
            'name': 'paypal',
            'display_name': 'PayPal',
            'icon': 'credit-card',
            'is_active': True,
        },
        {
            'name': 'wally',
            'display_name': 'Wally',
            'icon': 'smartphone',
            'is_active': True,
        },
    ],
    'US': [  # United States
        {
            'name': 'zelle',
            'display_name': 'Zelle',
            'icon': 'credit-card',
            'is_active': True,
        },
        {
            'name': 'venmo',
            'display_name': 'Venmo',
            'icon': 'smartphone',
            'is_active': True,
        },
        {
            'name': 'cashapp',
            'display_name': 'Cash App',
            'icon': 'smartphone',
            'is_active': True,
        },
        {
            'name': 'bank_transfer',
            'display_name': 'Bank Transfer (ACH)',
            'icon': 'bank',
            'is_active': True,
        },
    ],
    'AS': [  # American Samoa
        {
            'name': 'bank_transfer',
            'display_name': 'Bank Transfer',
            'icon': 'bank',
            'is_active': True,
        },
        {
            'name': 'western_union',
            'display_name': 'Western Union',
            'icon': 'credit-card',
            'is_active': True,
        },
        {
            'name': 'moneygram',
            'display_name': 'MoneyGram',
            'icon': 'credit-card',
            'is_active': True,
        },
    ],
    'AR': [  # Argentina
        {
            'name': 'mercadopago',
            'display_name': 'Mercado Pago',
            'icon': 'smartphone',
            'is_active': True,
        },
        {
            'name': 'transferencia_bancaria',
            'display_name': 'Transferencia Bancaria',
            'icon': 'bank',
            'is_active': True,
        },
        {
            'name': 'uala',
            'display_name': 'Ualá',
            'icon': 'credit-card',
            'is_active': True,
        },
    ],
    'CO': [  # Colombia
        {
            'name': 'nequi',
            'display_name': 'Nequi',
            'icon': 'smartphone',
            'is_active': True,
        },
        {
            'name': 'daviplata',
            'display_name': 'DaviPlata',
            'icon': 'smartphone',
            'is_active': True,
        },
        {
            'name': 'bancolombia',
            'display_name': 'Bancolombia',
            'icon': 'bank',
            'is_active': True,
        },
    ],
    'PE': [  # Peru
        {
            'name': 'yape',
            'display_name': 'Yape',
            'icon': 'smartphone',
            'is_active': True,
        },
        {
            'name': 'plin',
            'display_name': 'Plin',
            'icon': 'smartphone',
            'is_active': True,
        },
        {
            'name': 'bcp',
            'display_name': 'BCP',
            'icon': 'bank',
            'is_active': True,
        },
    ],
    'MX': [  # Mexico
        {
            'name': 'oxxo',
            'display_name': 'OXXO',
            'icon': 'dollar-sign',
            'is_active': True,
        },
        {
            'name': 'spei',
            'display_name': 'SPEI',
            'icon': 'bank',
            'is_active': True,
        },
        {
            'name': 'bbva_mexico',
            'display_name': 'BBVA México',
            'icon': 'bank',
            'is_active': True,
        },
    ],
}

def get_payment_methods_for_country(country_code: str) -> list:
    """
    Get payment methods available for a specific country.
    For Venezuela, returns only country-specific methods (which include the main global ones).
    For other countries, returns country-specific methods plus global methods.
    """
    country_methods = COUNTRY_PAYMENT_METHODS.get(country_code, [])
    
    # For Venezuela, return only the country-specific methods as they already include the needed global ones
    if country_code == 'VE':
        return country_methods
    
    # For other countries, combine with global methods
    return country_methods + GLOBAL_PAYMENT_METHODS
