from django.core.management.base import BaseCommand
from p2p_exchange.models import P2PPaymentMethod
from p2p_exchange.schema import Query
from unittest.mock import Mock


class Command(BaseCommand):
    help = 'Debug payment methods differences between screens'

    def add_arguments(self, parser):
        parser.add_argument('country_code', type=str, help='Country code (e.g., AR)')

    def handle(self, *args, **options):
        country_code = options['country_code']
        
        # 1. Direct database query (what CreateOfferScreen might see)
        db_methods = P2PPaymentMethod.objects.filter(
            country_code=country_code,
            is_active=True
        ).order_by('display_order', 'display_name')
        
        self.stdout.write(f"\n1. Direct DB query (is_active=True):")
        self.stdout.write(f"   Count: {db_methods.count()}")
        
        # 2. GraphQL resolver simulation
        query = Query()
        mock_info = Mock()
        
        graphql_methods = query.resolve_p2p_payment_methods(mock_info, country_code=country_code)
        graphql_list = list(graphql_methods)
        
        self.stdout.write(f"\n2. GraphQL resolver result:")
        self.stdout.write(f"   Count: {len(graphql_list)}")
        
        # 3. Compare the lists
        db_ids = set(str(m.id) for m in db_methods)
        graphql_ids = set(str(m.id) for m in graphql_list)
        
        only_in_db = db_ids - graphql_ids
        only_in_graphql = graphql_ids - db_ids
        
        if only_in_db:
            self.stdout.write(f"\n3. Methods in DB but not in GraphQL ({len(only_in_db)}):")
            for pm_id in only_in_db:
                pm = P2PPaymentMethod.objects.get(id=pm_id)
                self.stdout.write(f"   - {pm.display_name} (ID: {pm.id})")
        
        if only_in_graphql:
            self.stdout.write(f"\n4. Methods in GraphQL but not in DB ({len(only_in_graphql)}):")
            for pm_id in only_in_graphql:
                pm = next(m for m in graphql_list if m.id == pm_id)
                self.stdout.write(f"   - {pm.display_name} (ID: {pm.id})")
        
        if not only_in_db and not only_in_graphql:
            self.stdout.write(self.style.SUCCESS("\n✓ Both queries return the same payment methods!"))
        
        # 4. Show sample methods
        self.stdout.write(f"\n5. Sample payment methods:")
        for pm in list(db_methods)[:5]:
            self.stdout.write(f"   - {pm.display_name} ({pm.provider_type})")
            self.stdout.write(f"     ID: {pm.id}, Active: {pm.is_active}")
            if pm.bank:
                self.stdout.write(f"     Bank: {pm.bank.name}")