from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from users.models import Account, Business
from users.models_unified import UnifiedTransactionTable
from django.db.models import Q

class Command(BaseCommand):
    help = 'Debug transaction query logic'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str)

    def handle(self, *args, **options):
        User = get_user_model()
        username = options['username']
        user = User.objects.get(username=username)
        
        self.stdout.write(f"User: {user.username} (ID: {user.id})")
        
        # 1. Check Personal Account
        account = Account.objects.get(user=user, account_type='personal', account_index=0)
        self.stdout.write(f"\n--- Personal Account (ID: {account.id}) ---")
        
        # Logic from resolve_current_account_transactions for personal account
        queryset = UnifiedTransactionTable.objects.filter(
            Q(
                Q(sender_user=user) & Q(sender_business__isnull=True)
            ) | 
            Q(
                Q(counterparty_user=user) & Q(counterparty_business__isnull=True)
            ) |
            Q(
                Q(counterparty_user=user) & Q(transaction_type='payroll')
            )
        ).order_by('-created_at')[:10]
        
        self.stdout.write(f"Query found {queryset.count()} transactions")
        for tx in queryset:
            self.stdout.write(f"  ID: {tx.id}, Type: {tx.transaction_type}, Token: {tx.token_type}, Amount: {tx.amount}")
            self.stdout.write(f"    Sender: {tx.sender_display_name} (Biz: {tx.sender_business})")
            self.stdout.write(f"    Counterparty: {tx.counterparty_display_name} (User: {tx.counterparty_user})")

        # 2. Check specific payroll items directly
        self.stdout.write(f"\n--- Direct Payroll Check ---")
        payroll_txs = UnifiedTransactionTable.objects.filter(
            transaction_type='payroll',
            counterparty_user=user
        )
        self.stdout.write(f"Total Payroll Txs for user: {payroll_txs.count()}")
        for tx in payroll_txs:
             self.stdout.write(f"  ID: {tx.id}, Token: '{tx.token_type}'")
