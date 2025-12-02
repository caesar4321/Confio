import os
import django
import json
from graphene.test import Client

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from config.schema import schema
from django.contrib.auth import get_user_model
from notifications.models import Notification

User = get_user_model()

# Get the user (Julian Moon) - trying alternative phone or username
try:
    user = User.objects.get(phone_number='+19293993618')
except User.DoesNotExist:
    # Try finding any user with notifications
    user = Notification.objects.filter(notification_type='PAYROLL_RECEIVED').first().user
    print(f"Using user: {user.phone_number}")

# Create a test client
client = Client(schema)

# Define the query
query = """
query GetNotifications {
  notifications(first: 20) {
    edges {
      node {
        id
        notificationType
        title
        relatedObjectType
        actionUrl
        data
      }
    }
  }
}
"""

# Mock context with user
class Context:
    def __init__(self, user):
        self.user = user
        self.META = {}

# Mock the JWT context function
from unittest.mock import patch

# Find the user's account
from users.models import Account
account = Account.objects.filter(user=user, account_type='personal').first()

mock_context = {
    'account_type': 'personal',
    'account_index': 0,
    'account_id': account.id if account else None,
    'business_id': None
}

print(f"Using account: {account.id if account else 'None'}")

# Execute query with mocked context
with patch('notifications.schema.get_jwt_business_context_with_validation', return_value=mock_context):
    result = client.execute(query, context=Context(user))

print(json.dumps(result, indent=2))
