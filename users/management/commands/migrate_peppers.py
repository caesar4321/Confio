from django.core.management.base import BaseCommand
from users.models_wallet import WalletPepper, WalletDerivationPepper
from users.encryption import encrypt_data
from django.db import transaction

class Command(BaseCommand):
    help = 'Encrypts existing plain text peppers into the new encrypted_pepper field'

    def handle(self, *args, **options):
        self.stdout.write("Starting pepper encryption migration...")
        
        # 1. Migrate WalletPepper (Rotating peppers)
        w_peppers = WalletPepper.objects.filter(encrypted_pepper__isnull=True)
        count = w_peppers.count()
        self.stdout.write(f"Found {count} WalletPeppers to migrate")
        
        migrated = 0
        with transaction.atomic():
            for wp in w_peppers:
                if wp.pepper:
                    # Encrypt the plain text pepper
                    # Note: We assign to encrypted_pepper. 
                    # If EncryptedCharField logic works on assignment, great.
                    # But EncryptedCharField usually encrypts on get_db_prep_value (save).
                    # So assignment in python should be plaintext?
                    # NO. EncryptedCharField expects plaintext in python, and encrypts on save.
                    # So we just assign the plaintext same as 'pepper'.
                    wp.encrypted_pepper = wp.pepper
                    wp.save()
                    migrated += 1
                    if migrated % 100 == 0:
                        self.stdout.write(f"Migrated {migrated}/{count} WalletPeppers")
        
        self.stdout.write(f"Successfully migrated {migrated} WalletPeppers")

        # 2. Migrate WalletDerivationPepper (Non-rotating peppers)
        wd_peppers = WalletDerivationPepper.objects.filter(encrypted_pepper__isnull=True)
        count = wd_peppers.count()
        self.stdout.write(f"Found {count} WalletDerivationPeppers to migrate")
        
        migrated = 0
        with transaction.atomic():
            for wdp in wd_peppers:
                if wdp.pepper:
                    wdp.encrypted_pepper = wdp.pepper
                    wdp.save()
                    migrated += 1
                    if migrated % 100 == 0:
                         self.stdout.write(f"Migrated {migrated}/{count} WalletDerivationPeppers")

        self.stdout.write(f"Successfully migrated {migrated} WalletDerivationPeppers")
        self.stdout.write(self.style.SUCCESS("Encryption migration complete"))
