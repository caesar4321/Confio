import calendar
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from billing.models import (
    BillingObligation,
    BillingSchedule,
    CipSandboxMember,
    InstitutionConnection,
    ObligationSubject,
)
from billing.sandbox_cip import verify_member_and_issue_link
from users.models import Account, Business, User


class Command(BaseCommand):
    help = 'Idempotently seed one CIP sandbox member, monthly due, and secure app link.'

    def add_arguments(self, parser):
        parser.add_argument('--merchant-username', required=True)
        parser.add_argument('--merchant-bsc-address', required=True)
        parser.add_argument('--member-number', required=True)
        parser.add_argument('--amount-pen', default='50.00')
        parser.add_argument('--period', help='YYYY-MM; defaults to the current Lima month')

    @transaction.atomic
    def handle(self, *args, **options):
        if not getattr(settings, 'BILLING_CIP_SANDBOX_ENABLED', False):
            raise CommandError('BILLING_CIP_SANDBOX_ENABLED must be true')
        if not getattr(settings, 'BILLING_CIP_SANDBOX_TOKEN', ''):
            raise CommandError('BILLING_CIP_SANDBOX_TOKEN must be configured')
        merchant_address = options['merchant_bsc_address']
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}', merchant_address):
            raise CommandError('--merchant-bsc-address must be a 20-byte 0x address')
        member_number = options['member_number'].strip()
        if not member_number or len(member_number) > 80:
            raise CommandError('--member-number must contain 1 to 80 characters')
        try:
            amount = Decimal(options['amount_pen']).quantize(Decimal('0.01'))
            amount_minor = int(amount * 100)
        except (InvalidOperation, ValueError):
            raise CommandError('--amount-pen must be a valid positive amount')
        if not 0 < amount_minor <= 9_223_372_036_854_775_807:
            raise CommandError('--amount-pen is outside the supported positive range')
        try:
            period_start = (
                datetime.strptime(options['period'], '%Y-%m').date()
                if options.get('period') else timezone.localdate(timezone=ZoneInfo('America/Lima')).replace(day=1))
        except ValueError:
            raise CommandError('--period must use YYYY-MM')
        period_end = date(
            period_start.year, period_start.month,
            calendar.monthrange(period_start.year, period_start.month)[1])

        try:
            merchant_user = User.objects.select_for_update().get(
                username=options['merchant_username'], is_active=True, deleted_at__isnull=True)
        except User.DoesNotExist:
            raise CommandError('merchant user not found')
        account = Account.objects.select_related('business').filter(
            user=merchant_user, account_type='business', account_index=0).first()
        if account is not None and account.business_id is not None and (
                account.business.name != 'CIP Sandbox' or account.business.deleted_at is not None):
            raise CommandError('merchant account 0 belongs to another business')
        business = account.business if account and account.business_id else Business.objects.create(
            name='CIP Sandbox', category='services')
        if account is None:
            account = Account.objects.create(
                user=merchant_user, account_type='business', account_index=0,
                business=business)
        if account.deleted_at is not None:
            raise CommandError('merchant account 0 is deleted')
        if account.bsc_address and account.bsc_address.lower() != merchant_address.lower():
            raise CommandError('existing merchant receiver address differs; seed cannot replace it')
        account.business = business
        account.bsc_address = merchant_address
        account.save(update_fields=('business', 'bsc_address', 'updated_at'))
        connection, _ = InstitutionConnection.objects.get_or_create(
            business=business, provider='cip', mode='test',
            defaults={'status': 'sandbox'})
        if connection.status != 'sandbox':
            raise CommandError('existing CIP test connection is not sandbox')

        subject, _ = ObligationSubject.objects.get_or_create(
            business=business, mode='test', external_id=f'cip:{member_number}',
            defaults={
                'subject_type': 'membership',
                'display_label': f'Colegiado ••••{member_number[-4:]}',
                'masked_reference': f'CIP ••••{member_number[-4:]}',
            })
        CipSandboxMember.objects.get_or_create(
            connection=connection, subject=subject,
            defaults={'member_number': member_number, 'habilidad': 'inactive'})
        schedule, created = BillingSchedule.objects.get_or_create(
            business=business, mode='test', external_reference=f'cip:{member_number}:monthly',
            defaults={
                'subject': subject, 'amount_minor': amount_minor,
                'currency': 'PEN', 'presentation_mode': 'payer_amount',
                'anchor_day': min(period_start.day, 28),
                'next_period_start': period_end + timedelta(days=1),
            })
        if not created and (schedule.subject_id != subject.id
                            or schedule.amount_minor != amount_minor):
            raise CommandError('existing schedule differs from requested member or amount')
        aware_start = timezone.make_aware(
            datetime.combine(period_start, time.min), timezone=ZoneInfo('America/Lima'))
        obligation, obligation_created = BillingObligation.objects.get_or_create(
            business=business, mode='test',
            external_reference=f'cip:{member_number}:{period_start:%Y-%m}',
            defaults={
                'subject': subject, 'schedule': schedule,
                'period_key': period_start.isoformat(), 'currency': 'PEN',
                'original_amount_minor': amount_minor,
                'amount_remaining_minor': amount_minor,
                'line_items_snapshot': [{
                    'description': f'Cuota CIP {period_start:%Y-%m}',
                    'amount_minor': amount_minor,
                }],
                'period_start': period_start, 'period_end': period_end,
                'issued_at': aware_start,
                'due_at': aware_start + timedelta(days=10),
                'status': 'open', 'source_version': 'cip-sandbox-v1',
            })
        if not obligation_created and (
                obligation.subject_id != subject.id or obligation.schedule_id != schedule.id
                or obligation.original_amount_minor != amount_minor
                or obligation.currency != 'PEN' or obligation.period_start != period_start
                or obligation.period_end != period_end):
            raise CommandError('existing obligation differs from requested seed')
        result = verify_member_and_issue_link(
            member_number=member_number, connection=connection)
        self.stdout.write(self.style.SUCCESS('CIP sandbox pilot ready'))
        self.stdout.write(f'connection={connection.public_id}')
        self.stdout.write(f"member_reference={result['member_reference']}")
        self.stdout.write(f"habilidad={result['habilidad']}")
        self.stdout.write(f"membership_link={result['membership_link']}")
        self.stdout.write(f"expires_at={result['expires_at']}")
