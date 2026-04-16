import os
import sys

os.environ['USE_KMS_SIGNING'] = 'False'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from conversion.models import Conversion

convs = Conversion.objects.filter(status='FAILED').order_by('-created_at')[:10]
for c in convs:
    print(f"ID: {c.internal_id.hex}, Status: {c.status}, Error: {c.error_message}, TxHash: {c.to_transaction_hash}")
