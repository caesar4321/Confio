import graphene
from graphene_django import DjangoObjectType
from .models import ExchangeRate
from .services import exchange_rate_service


class ExchangeRateType(DjangoObjectType):
    class Meta:
        model = ExchangeRate
        fields = (
            'id', 'source_currency', 'target_currency', 'rate', 'rate_type', 
            'source', 'fetched_at', 'created_at', 'is_active'
        )


class Query(graphene.ObjectType):
    # Get current exchange rate
    current_exchange_rate = graphene.Field(
        graphene.Decimal,
        source_currency=graphene.String(default_value='VES'),
        target_currency=graphene.String(default_value='USD'),
        rate_type=graphene.String(default_value='parallel')
    )
    
    # Get exchange rate with fallback
    exchange_rate_with_fallback = graphene.Field(
        graphene.Decimal,
        source_currency=graphene.String(default_value='VES'),
        target_currency=graphene.String(default_value='USD')
    )
    
    # Get all recent rates for a currency pair
    exchange_rates = graphene.List(
        ExchangeRateType,
        source_currency=graphene.String(default_value='VES'),
        target_currency=graphene.String(default_value='USD'),
        rate_type=graphene.String(),
        limit=graphene.Int(default_value=10)
    )
    
    def resolve_current_exchange_rate(self, info, source_currency, target_currency, rate_type):
        """Get the most recent exchange rate"""
        return exchange_rate_service.get_current_rate(source_currency, target_currency, rate_type)
    
    def resolve_exchange_rate_with_fallback(self, info, source_currency, target_currency):
        """Get exchange rate with fallback logic"""
        return exchange_rate_service.get_rate_with_fallback(source_currency, target_currency)
    
    def resolve_exchange_rates(self, info, source_currency, target_currency, rate_type=None, limit=10):
        """Get recent exchange rates for analysis"""
        filters = {
            'source_currency': source_currency,
            'target_currency': target_currency,
            'is_active': True
        }
        
        if rate_type:
            filters['rate_type'] = rate_type
        
        return ExchangeRate.objects.filter(**filters)[:limit]


class RefreshExchangeRates(graphene.Mutation):
    """Mutation to manually trigger exchange rate refresh"""
    
    success = graphene.Boolean()
    message = graphene.String()
    sources = graphene.JSONString()
    
    def mutate(self, info):
        try:
            results = exchange_rate_service.fetch_all_rates()
            successful_sources = sum(1 for success in results.values() if success)
            total_sources = len(results)
            
            return RefreshExchangeRates(
                success=successful_sources > 0,
                message=f"Refreshed rates from {successful_sources}/{total_sources} sources",
                sources=results
            )
        except Exception as e:
            return RefreshExchangeRates(
                success=False,
                message=f"Failed to refresh rates: {str(e)}",
                sources={}
            )


class Mutation(graphene.ObjectType):
    refresh_exchange_rates = RefreshExchangeRates.Field()