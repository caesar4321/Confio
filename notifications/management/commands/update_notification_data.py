from django.core.management.base import BaseCommand
from django.db import transaction
from notifications.models import Notification
from send.models import SendTransaction
import json


class Command(BaseCommand):
    help = 'Update existing notifications with complete transaction data for better navigation'

    def handle(self, *args, **options):
        self.stdout.write('Updating notification data fields...')
        
        # Get all notifications related to SendTransaction
        notifications = Notification.objects.filter(
            related_object_type='SendTransaction',
            related_object_id__isnull=False
        )
        
        updated_count = 0
        failed_count = 0
        
        for notification in notifications:
            try:
                # Get the related transaction
                tx = SendTransaction.objects.get(id=notification.related_object_id)
                
                # Determine if this is a sent or received transaction
                is_sent = notification.notification_type in ['SEND_SENT', 'SEND_INVITATION_SENT']
                
                # Build complete data for TransactionDetailScreen
                amount_str = str(tx.amount)
                # Add + or - sign based on transaction type
                if is_sent:
                    amount_str = f'-{amount_str}'
                else:
                    amount_str = f'+{amount_str}'
                    
                notification.data.update({
                    'transaction_type': 'send',
                    'type': 'sent' if is_sent else 'received',
                    'from': tx.sender_display_name or 'Usuario',
                    'fromAddress': tx.sender_address,
                    'to': tx.recipient_display_name or tx.recipient_phone or 'Usuario',
                    'toAddress': tx.recipient_address,
                    'amount': amount_str,
                    'currency': tx.token_type,
                    'status': tx.status.lower(),
                    'hash': tx.transaction_hash or '',
                    'note': tx.memo or '',
                    'date': tx.created_at.strftime('%Y-%m-%d'),
                    'time': tx.created_at.strftime('%H:%M'),
                    'avatar': (tx.recipient_display_name[0] if is_sent and tx.recipient_display_name 
                              else tx.sender_display_name[0] if not is_sent and tx.sender_display_name 
                              else 'U'),
                    'isInvitedFriend': bool(tx.invitation_expires_at),
                })
                
                notification.save()
                updated_count += 1
                
            except SendTransaction.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f'Transaction {notification.related_object_id} not found for notification {notification.id}'
                ))
                failed_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Error updating notification {notification.id}: {str(e)}'
                ))
                failed_count += 1
        
        self.stdout.write(self.style.SUCCESS(
            f'Updated {updated_count} notifications. Failed: {failed_count}'
        ))