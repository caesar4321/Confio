import requests
import logging
from decimal import Decimal
from typing import Optional, Dict, Any
from django.utils import timezone
from django.conf import settings
from .models import ExchangeRate, RateFetchLog

logger = logging.getLogger(__name__)


class ExchangeRateService:
    """
    Service for fetching exchange rates from various sources
    """
    
    def __init__(self):
        self.session = requests.Session()
        self.session.timeout = 30
    
    def fetch_all_rates(self) -> Dict[str, bool]:
        """
        Fetch rates from all available sources
        Returns dict with source names and success status
        """
        results = {}
        
        # Try Yadio for VES rates  
        results['yadio'] = self.fetch_yadio_rates()
        
        # Try ExchangeRate-API as general fallback
        results['exchangerate_api'] = self.fetch_exchangerate_api_rates()
        
        # Try CurrencyLayer for additional VES rates
        results['currencylayer'] = self.fetch_currencylayer_rates()
        
        # Try Argentine-specific sources for ARS rates
        results['bluelytics'] = self.fetch_bluelytics_rates()
        results['dolarapi'] = self.fetch_dolarapi_rates()
        
        return results
    
    
    def fetch_yadio_rates(self) -> bool:
        """
        Fetch VES/USD rates from Yadio.io
        Yadio provides various exchange rates including Venezuelan rates
        """
        start_time = timezone.now()
        
        try:
            # Yadio API endpoint for VES/USD
            url = "https://api.yadio.io/convert/1/VES/USD"
            
            response = self.session.get(url)
            response.raise_for_status()
            
            data = response.json()
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            
            rates_created = 0
            
            # Yadio returns the rate as how many USD you get for 1 VES
            # We need to invert it to get VES per USD
            if 'result' in data and data['result']:
                usd_per_ves = Decimal(str(data['result']))
                ves_per_usd = 1 / usd_per_ves
                
                ExchangeRate.objects.create(
                    source_currency='VES',
                    target_currency='USD',
                    rate=ves_per_usd,
                    rate_type='parallel',  # Yadio typically shows market rates
                    source='yadio',
                    fetched_at=timezone.now(),
                    raw_data=data
                )
                rates_created += 1
            
            # Log success
            RateFetchLog.objects.create(
                source='yadio',
                status='success',
                rates_fetched=rates_created,
                response_time_ms=response_time
            )
            
            logger.info(f"Yadio: Successfully fetched {rates_created} rates")
            return True
            
        except requests.exceptions.RequestException as e:
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            RateFetchLog.objects.create(
                source='yadio',
                status='failed',
                rates_fetched=0,
                error_message=str(e),
                response_time_ms=response_time
            )
            logger.error(f"Yadio API error: {e}")
            return False
        
        except Exception as e:
            RateFetchLog.objects.create(
                source='yadio',
                status='failed',
                rates_fetched=0,
                error_message=str(e)
            )
            logger.error(f"Yadio unexpected error: {e}")
            return False
    
    def fetch_exchangerate_api_rates(self) -> bool:
        """
        Fetch multiple currency rates from ExchangeRate-API
        This provides official rates for many countries
        """
        start_time = timezone.now()
        
        try:
            # ExchangeRate-API endpoint - get all rates with USD as base
            url = "https://api.exchangerate-api.com/v4/latest/USD"
            
            response = self.session.get(url)
            response.raise_for_status()
            
            data = response.json()
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            
            rates_created = 0
            
            # List of currencies we want to support (based on countries in the app)
            supported_currencies = {
                'VES': 'Venezuela',
                'ARS': 'Argentina', 
                'COP': 'Colombia',
                'PEN': 'Peru',
                'CLP': 'Chile',
                'BOB': 'Bolivia',
                'UYU': 'Uruguay',
                'PYG': 'Paraguay',
                'BRL': 'Brazil',
                'MXN': 'Mexico',
                'EUR': 'Europe',
                'GBP': 'United Kingdom',
                'CAD': 'Canada',
                'AUD': 'Australia',
                'JPY': 'Japan',
                'CNY': 'China',
                'KRW': 'South Korea',
                'INR': 'India',
                'SGD': 'Singapore',
                'THB': 'Thailand',
                'PHP': 'Philippines',
                'MYR': 'Malaysia',
                'IDR': 'Indonesia',
                'VND': 'Vietnam',
            }
            
            # Create exchange rate records for all supported currencies
            if 'rates' in data:
                for currency_code, country_name in supported_currencies.items():
                    if currency_code in data['rates']:
                        rate = Decimal(str(data['rates'][currency_code]))
                        
                        ExchangeRate.objects.create(
                            source_currency=currency_code,
                            target_currency='USD',
                            rate=rate,
                            rate_type='official',  # ExchangeRate-API provides official rates
                            source='exchangerate_api',
                            fetched_at=timezone.now(),
                            raw_data={'rate': float(rate), 'country': country_name}
                        )
                        rates_created += 1
            
            # Log success
            RateFetchLog.objects.create(
                source='exchangerate_api',
                status='success',
                rates_fetched=rates_created,
                response_time_ms=response_time
            )
            
            logger.info(f"ExchangeRate-API: Successfully fetched {rates_created} rates")
            return True
            
        except requests.exceptions.RequestException as e:
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            RateFetchLog.objects.create(
                source='exchangerate_api',
                status='failed',
                rates_fetched=0,
                error_message=str(e),
                response_time_ms=response_time
            )
            logger.error(f"ExchangeRate-API error: {e}")
            return False
        
        except Exception as e:
            RateFetchLog.objects.create(
                source='exchangerate_api',
                status='failed',
                rates_fetched=0,
                error_message=str(e)
            )
            logger.error(f"ExchangeRate-API unexpected error: {e}")
            return False
    
    def fetch_currencylayer_rates(self) -> bool:
        """
        Fetch VES/USD rates from CurrencyLayer (free tier)
        CurrencyLayer sometimes has VES rates when others don't
        """
        start_time = timezone.now()
        
        try:
            # CurrencyLayer free endpoint (no API key required for basic usage)
            url = "http://api.currencylayer.com/live?currencies=VES&source=USD&format=1"
            
            response = self.session.get(url)
            response.raise_for_status()
            
            data = response.json()
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            
            rates_created = 0
            
            # CurrencyLayer format: {"quotes": {"USDVES": 119.5}}
            if data.get('success') and 'quotes' in data:
                quotes = data['quotes']
                
                if 'USDVES' in quotes:
                    # CurrencyLayer gives USD to VES, we want VES per USD
                    usd_to_ves = Decimal(str(quotes['USDVES']))
                    
                    ExchangeRate.objects.create(
                        source_currency='VES',
                        target_currency='USD',
                        rate=usd_to_ves,
                        rate_type='official',  # CurrencyLayer typically provides official rates
                        source='currencylayer',
                        fetched_at=timezone.now(),
                        raw_data=data
                    )
                    rates_created += 1
            
            # Log success
            RateFetchLog.objects.create(
                source='currencylayer',
                status='success',
                rates_fetched=rates_created,
                response_time_ms=response_time
            )
            
            logger.info(f"CurrencyLayer: Successfully fetched {rates_created} rates")
            return True
            
        except requests.exceptions.RequestException as e:
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            RateFetchLog.objects.create(
                source='currencylayer',
                status='failed',
                rates_fetched=0,
                error_message=str(e),
                response_time_ms=response_time
            )
            logger.error(f"CurrencyLayer API error: {e}")
            return False
        
        except Exception as e:
            RateFetchLog.objects.create(
                source='currencylayer',
                status='failed',
                rates_fetched=0,
                error_message=str(e)
            )
            logger.error(f"CurrencyLayer unexpected error: {e}")
            return False
    
    def fetch_bluelytics_rates(self) -> bool:
        """
        Fetch ARS/USD rates from Bluelytics (Argentine blue dollar specialist)
        Provides both official and blue dollar (parallel market) rates
        """
        start_time = timezone.now()
        
        try:
            url = "https://api.bluelytics.com.ar/v2/latest"
            
            response = self.session.get(url)
            response.raise_for_status()
            
            data = response.json()
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            
            rates_created = 0
            
            # Bluelytics format: {"oficial": {"value_avg": 1283.0}, "blue": {"value_avg": 1305.0}}
            if 'oficial' in data and 'value_avg' in data['oficial']:
                oficial_rate = Decimal(str(data['oficial']['value_avg']))
                ExchangeRate.objects.create(
                    source_currency='ARS',
                    target_currency='USD',
                    rate=oficial_rate,
                    rate_type='official',
                    source='bluelytics',
                    fetched_at=timezone.now(),
                    raw_data=data
                )
                rates_created += 1
            
            if 'blue' in data and 'value_avg' in data['blue']:
                blue_rate = Decimal(str(data['blue']['value_avg']))
                ExchangeRate.objects.create(
                    source_currency='ARS',
                    target_currency='USD',
                    rate=blue_rate,
                    rate_type='parallel',  # Blue dollar is parallel market
                    source='bluelytics',
                    fetched_at=timezone.now(),
                    raw_data=data
                )
                rates_created += 1
            
            # Log success
            RateFetchLog.objects.create(
                source='bluelytics',
                status='success',
                rates_fetched=rates_created,
                response_time_ms=response_time
            )
            
            logger.info(f"Bluelytics: Successfully fetched {rates_created} ARS rates")
            return True
            
        except requests.exceptions.RequestException as e:
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            RateFetchLog.objects.create(
                source='bluelytics',
                status='failed',
                rates_fetched=0,
                error_message=str(e),
                response_time_ms=response_time
            )
            logger.error(f"Bluelytics API error: {e}")
            return False
        
        except Exception as e:
            RateFetchLog.objects.create(
                source='bluelytics',
                status='failed',
                rates_fetched=0,
                error_message=str(e)
            )
            logger.error(f"Bluelytics unexpected error: {e}")
            return False
    
    def fetch_dolarapi_rates(self) -> bool:
        """
        Fetch ARS/USD rates from DolarAPI (Argentine exchange rate specialist)
        Provides multiple rate types: oficial, blue, bolsa, etc.
        """
        start_time = timezone.now()
        
        try:
            url = "https://dolarapi.com/v1/dolares"
            
            response = self.session.get(url)
            response.raise_for_status()
            
            data = response.json()
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            
            rates_created = 0
            
            # DolarAPI format: [{"casa": "oficial", "venta": 1305}, {"casa": "blue", "venta": 1315}]
            for rate_info in data:
                if 'casa' in rate_info and 'venta' in rate_info:
                    casa = rate_info['casa']
                    venta_rate = Decimal(str(rate_info['venta']))
                    
                    # Map casa types to our rate_type system
                    rate_type_mapping = {
                        'oficial': 'official',
                        'blue': 'parallel',
                        'bolsa': 'average',
                        'contadoconliqui': 'average'
                    }
                    
                    rate_type = rate_type_mapping.get(casa, 'official')
                    
                    if casa in rate_type_mapping:  # Only save known types
                        ExchangeRate.objects.create(
                            source_currency='ARS',
                            target_currency='USD',
                            rate=venta_rate,
                            rate_type=rate_type,
                            source='dolarapi',
                            fetched_at=timezone.now(),
                            raw_data=rate_info
                        )
                        rates_created += 1
            
            # Log success
            RateFetchLog.objects.create(
                source='dolarapi',
                status='success',
                rates_fetched=rates_created,
                response_time_ms=response_time
            )
            
            logger.info(f"DolarAPI: Successfully fetched {rates_created} ARS rates")
            return True
            
        except requests.exceptions.RequestException as e:
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            RateFetchLog.objects.create(
                source='dolarapi',
                status='failed',
                rates_fetched=0,
                error_message=str(e),
                response_time_ms=response_time
            )
            logger.error(f"DolarAPI error: {e}")
            return False
        
        except Exception as e:
            RateFetchLog.objects.create(
                source='dolarapi',
                status='failed',
                rates_fetched=0,
                error_message=str(e)
            )
            logger.error(f"DolarAPI unexpected error: {e}")
            return False
    
    def get_current_rate(self, 
                        source_currency: str = 'VES', 
                        target_currency: str = 'USD', 
                        rate_type: str = 'parallel') -> Optional[Decimal]:
        """
        Get the current exchange rate
        """
        return ExchangeRate.get_rate_value(source_currency, target_currency, rate_type)
    
    def get_rate_with_fallback(self, 
                              source_currency: str = 'VES', 
                              target_currency: str = 'USD') -> Optional[Decimal]:
        """
        Get rate with fallback priority: parallel -> average -> official
        """
        # Try parallel market rate first (most accurate for Venezuelan market)
        rate = self.get_current_rate(source_currency, target_currency, 'parallel')
        if rate:
            return rate
        
        # Try average rate
        rate = self.get_current_rate(source_currency, target_currency, 'average')
        if rate:
            return rate
        
        # Fallback to official rate
        rate = self.get_current_rate(source_currency, target_currency, 'official')
        return rate


# Global instance
exchange_rate_service = ExchangeRateService()