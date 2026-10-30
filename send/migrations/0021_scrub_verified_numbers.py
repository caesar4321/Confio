"""No verified phone number is kept beside who paid whom.

Sends, payments and history rows copied both parties' OTP-verified numbers.
None of it reaches anyone any more (the resolvers return only a number the
viewer typed), and none of it is needed: what stays is a number its sender
typed for their own send (recipient_phone_from_sender, invitations). Every
other copy is blanked. Not reversible on purpose.
"""
from django.db import migrations
from django.db.models import Q


def scrub(apps, schema_editor):
    SendTransaction = apps.get_model('send', 'SendTransaction')
    PaymentTransaction = apps.get_model('payments', 'PaymentTransaction')
    Unified = apps.get_model('users', 'UnifiedTransactionTable')

    typed = Q(recipient_phone_from_sender=True) | Q(is_invitation=True)
    SendTransaction.objects.exclude(sender_phone='').exclude(sender_phone__isnull=True).update(sender_phone='')
    SendTransaction.objects.exclude(typed).exclude(recipient_phone='').exclude(
        recipient_phone__isnull=True).update(recipient_phone='')
    PaymentTransaction.objects.exclude(payer_phone='').update(payer_phone='')

    Unified.objects.exclude(sender_phone='').update(sender_phone='')
    send_typed = Q(send_transaction__recipient_phone_from_sender=True) | Q(send_transaction__is_invitation=True)
    Unified.objects.exclude(send_typed).exclude(counterparty_phone='').exclude(
        counterparty_phone__isnull=True).update(counterparty_phone='')


class Migration(migrations.Migration):

    dependencies = [
        ('send', '0020_repair_claimed_invites'),
        ('payments', '0010_personal_merchants'),
        ('users', '0060_employee_invitation_user'),
    ]

    operations = [migrations.RunPython(scrub, migrations.RunPython.noop)]
