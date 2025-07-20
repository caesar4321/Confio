from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from payments.models import Invoice
from users.models import Account
from datetime import timedelta

User = get_user_model()

class Command(BaseCommand):
    help = 'Test the Invoice model and admin functionality'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Testing Invoice model and admin...'))
        
        # Check if we have any users
        users = User.objects.all()
        if not users.exists():
            self.stdout.write(self.style.WARNING('No users found. Creating a test user...'))
            user = User.objects.create_user(
                username='testuser',
                email='test@example.com',
                password='testpass123'
            )
        else:
            user = users.first()
        
        # Check if user has accounts
        accounts = Account.objects.filter(user=user)
        if not accounts.exists():
            self.stdout.write(self.style.WARNING('No accounts found. Creating a test account...'))
            account = Account.objects.create(
                user=user,
                account_type='personal',
                account_index=0
            )
        else:
            account = accounts.first()
        
        # Create a test invoice
        self.stdout.write('Creating test invoice...')
        invoice = Invoice.objects.create(
            merchant_user=user,
            merchant_account=account,
            amount='10.50',
            token_type='cUSD',
            description='Test invoice for admin panel',
            expires_at=timezone.now() + timedelta(hours=24),
            status='PENDING'
        )
        
        self.stdout.write(self.style.SUCCESS(f'Created test invoice: {invoice.invoice_id}'))
        self.stdout.write(f'  - Amount: {invoice.amount} {invoice.token_type}')
        self.stdout.write(f'  - Status: {invoice.status}')
        self.stdout.write(f'  - QR Code Data: {invoice.qr_code_data}')
        self.stdout.write(f'  - Expires: {invoice.expires_at}')
        self.stdout.write(f'  - Is Expired: {invoice.is_expired}')
        
        # Test admin URL
        admin_url = f'/admin/payments/invoice/{invoice.id}/'
        self.stdout.write(f'Admin URL: {admin_url}')
        
        # List all invoices
        all_invoices = Invoice.objects.all()
        self.stdout.write(f'Total invoices in database: {all_invoices.count()}')
        
        self.stdout.write(self.style.SUCCESS('Invoice model and admin test completed successfully!')) 