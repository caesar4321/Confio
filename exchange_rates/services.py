import requests
import logging
from decimal import Decimal
from typing import Optional, Dict, Any, Iterable
from django.utils import timezone
from django.conf import settings
from django.db.models import Case, When, Value, IntegerField
from .models import ExchangeRate, RateFetchLog

logger = logging.getLogger(__name__)


RATE_SOURCE_PRIORITY = {
    'parallel': [
        'binance_p2p',
        'yadio',
        'dolarapi',
        'bluelytics',
        'manual',
    ],
    'average': [
        'dolarapi',
        'manual',
    ],
    'official': [
        'exchangerate_api',
        'currencylayer',
        'bluelytics',
        'dolarapi',
        'bcv',
        'manual',
    ],
}


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

        # Try Binance P2P as a parallel-market proxy for supported fiat markets
        results['binance_p2p'] = self.fetch_binance_p2p_parallel_rates()

        # Try CurrencyLayer for additional VES rates
        results['currencylayer'] = self.fetch_currencylayer_rates()
        
        # Try Argentine-specific sources for ARS rates
        results['bluelytics'] = self.fetch_bluelytics_rates()
        results['dolarapi'] = self.fetch_dolarapi_rates()
        
        return results

    def fetch_dolartoday_rates(self) -> bool:
        """
        Legacy placeholder for DolarToday rates.

        The upstream source was removed (see README note) but tasks/commands may still call it.
        Return False and log a warning to avoid AttributeError crashes in Celery.
        """
        logger.warning("DolarToday source removed; fetch_dolartoday_rates is a no-op")
        return False
    
    
    def fetch_yadio_rates(self) -> bool:
        """
        Fetch VES/USD rates from Yadio.io
        Yadio provides various exchange rates including Venezuelan rates
        """
        start_time = timezone.now()
        
        try:
            # Yadio API endpoint for VES/USD
            url = "https://api.yadio.io/convert/1/VES/USD"
            
            response = self.session.get(url, timeout=10)
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
            
            response = self.session.get(url, timeout=10)
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

    def _extract_first_decimal(self, payload: Any, candidate_paths: Iterable[Iterable[Any]]) -> Optional[Decimal]:
        """
        Extract the first decimal-like value found in a set of nested paths.
        """
        for path in candidate_paths:
            current = payload
            try:
                for part in path:
                    current = current[part]
            except (KeyError, IndexError, TypeError):
                continue

            if current in (None, ''):
                continue

            try:
                return Decimal(str(current))
            except Exception:
                continue

        return None

    def _get_binance_p2p_quote_price(self, fiat_currency: str, trade_type: str) -> tuple[Optional[Decimal], Dict[str, Any]]:
        """
        Get a USDT/<fiat> quote from Binance's public C2C agent API.
        """
        url = "https://www.binance.com/bapi/c2c/v1/public/c2c/agent/quote-price"
        response = self.session.get(
            url,
            params={
                'fiat': fiat_currency,
                'asset': 'USDT',
                'tradeType': trade_type,
            },
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()
        price = self._extract_first_decimal(
            data,
            (
                ('data', 'price'),
                ('data', 'quotePrice'),
                ('data', 0, 'price'),
                ('data', 0, 'adv', 'price'),
                ('price',),
            ),
        )
        return price, data

    def _get_binance_p2p_ad_price(self, fiat_currency: str, trade_type: str) -> tuple[Optional[Decimal], Dict[str, Any]]:
        """
        Fallback parser for Binance ad-list responses when quote-price is unavailable.
        """
        url = "https://www.binance.com/bapi/c2c/v1/public/c2c/agent/ad-list"
        response = self.session.get(
            url,
            params={
                'fiat': fiat_currency,
                'asset': 'USDT',
                'tradeType': trade_type,
                'limit': 1,
            },
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()
        price = self._extract_first_decimal(
            data,
            (
                ('data', 0, 'price'),
                ('data', 0, 'adv', 'price'),
                ('data', 'items', 0, 'price'),
                ('data', 'items', 0, 'adv', 'price'),
            ),
        )
        return price, data

    def _fetch_binance_p2p_parallel_rate(self, fiat_currency: str) -> Dict[str, Any]:
        """
        Fetch a parallel-market proxy for a fiat currency from Binance P2P USDT quotes.

        We store the midpoint of BUY and SELL sides as fiat per USD, using USDT as
        a practical market proxy for USD in the local P2P market.
        """
        buy_price = sell_price = None
        buy_raw: Dict[str, Any] = {}
        sell_raw: Dict[str, Any] = {}

        try:
            try:
                buy_price, buy_raw = self._get_binance_p2p_quote_price(fiat_currency, 'BUY')
                sell_price, sell_raw = self._get_binance_p2p_quote_price(fiat_currency, 'SELL')
            except requests.exceptions.RequestException:
                # Fall back to the ad list endpoint if quote-price is unavailable.
                buy_price, buy_raw = self._get_binance_p2p_ad_price(fiat_currency, 'BUY')
                sell_price, sell_raw = self._get_binance_p2p_ad_price(fiat_currency, 'SELL')

            if not buy_price and not sell_price:
                raise ValueError(f"Binance P2P did not return a usable {fiat_currency}/USDT price")

            reference_price = (
                (buy_price + sell_price) / Decimal('2')
                if buy_price and sell_price
                else buy_price or sell_price
            )

            return {
                'success': True,
                'currency': fiat_currency,
                'price': reference_price,
                'buy_price': buy_price,
                'sell_price': sell_price,
                'buy_quote': buy_raw,
                'sell_quote': sell_raw,
                'pricing_method': 'midpoint' if buy_price and sell_price else 'single_side',
            }
        except Exception as e:
            return {
                'success': False,
                'currency': fiat_currency,
                'error': str(e),
            }

    def fetch_binance_p2p_parallel_rates(self) -> bool:
        """
        Fetch Binance P2P parallel-market proxies for VES, ARS, and BOB.
        """
        start_time = timezone.now()

        try:
            fiat_currencies = ('VES', 'ARS', 'BOB')
            fetched_results = [self._fetch_binance_p2p_parallel_rate(currency) for currency in fiat_currencies]
            successful_results = [result for result in fetched_results if result['success']]

            for result in successful_results:
                ExchangeRate.objects.create(
                    source_currency=result['currency'],
                    target_currency='USD',
                    rate=result['price'],
                    rate_type='parallel',
                    source='binance_p2p',
                    fetched_at=timezone.now(),
                    raw_data={
                        'proxy_asset': 'USDT',
                        'market': result['currency'],
                        'pricing_method': result['pricing_method'],
                        'buy_price': str(result['buy_price']) if result['buy_price'] else None,
                        'sell_price': str(result['sell_price']) if result['sell_price'] else None,
                        'buy_quote': result['buy_quote'],
                        'sell_quote': result['sell_quote'],
                    }
                )

            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            RateFetchLog.objects.create(
                source='binance_p2p',
                status='success' if successful_results else 'failed',
                rates_fetched=len(successful_results),
                error_message=None if successful_results else '; '.join(
                    result['error'] for result in fetched_results if not result['success']
                ),
                response_time_ms=response_time
            )

            logger.info(
                "Binance P2P: Successfully fetched %s parallel proxy rate(s)",
                len(successful_results)
            )
            return bool(successful_results)

        except requests.exceptions.RequestException as e:
            response_time = int((timezone.now() - start_time).total_seconds() * 1000)
            RateFetchLog.objects.create(
                source='binance_p2p',
                status='failed',
                rates_fetched=0,
                error_message=str(e),
                response_time_ms=response_time
            )
            logger.error(f"Binance P2P API error: {e}")
            return False

        except Exception as e:
            RateFetchLog.objects.create(
                source='binance_p2p',
                status='failed',
                rates_fetched=0,
                error_message=str(e)
            )
            logger.error(f"Binance P2P unexpected error: {e}")
            return False

    def fetch_binance_p2p_bob_rates(self) -> bool:
        """
        Backward-compatible wrapper for the management command name previously added.
        """
        return self.fetch_binance_p2p_parallel_rates()
    
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
        source_priority = RATE_SOURCE_PRIORITY.get(rate_type, [])
        queryset = ExchangeRate.objects.filter(
            source_currency=source_currency,
            target_currency=target_currency,
            rate_type=rate_type,
            is_active=True
        )

        if source_priority:
            priority_order = Case(
                *[
                    When(source=source, then=Value(index))
                    for index, source in enumerate(source_priority)
                ],
                default=Value(len(source_priority)),
                output_field=IntegerField(),
            )
            queryset = queryset.annotate(source_priority=priority_order).order_by('source_priority', '-fetched_at')
        else:
            queryset = queryset.order_by('-fetched_at')

        rate_obj = queryset.first()
        return rate_obj.rate if rate_obj else None
    
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
