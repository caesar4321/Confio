"""The ICP poll arms on a user's first dollars in: an incoming conversion or a received cUSD/Dollar+ send."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from conversion.models import Conversion
from send.models import SendTransaction
from users.models import User
from users.schema import PendingModalEnum, UserType


def make(name):
    return User.objects.create_user(username=name, email=f'{name}@x.test', password='x', firebase_uid=f'fb-{name}')


def pending(user):
    ctx = type('Ctx', (), {})()
    ctx.user = user
    info = type('Info', (), {'context': ctx})()
    return UserType.resolve_pending_modal(user, info)


def convert(user, kind='to_savings', status='COMPLETED', at=None):
    return Conversion.objects.create(
        actor_user=user, actor_type='user', conversion_type=kind,
        from_amount=Decimal('10'), to_amount=Decimal('10'), exchange_rate=Decimal('1'),
        fee_amount=Decimal('0'), status=status,
        completed_at=(at or timezone.now()) if status == 'COMPLETED' else None,
    )


def send(recipient, token, status='CONFIRMED', sender=None):
    return SendTransaction.objects.create(
        sender_user=sender, recipient_user=recipient, sender_address='0x' + '1' * 40,
        recipient_address='0x' + '2' * 40, amount=Decimal('5'), token_type=token, status=status,
    )


class FirstDollarsArmsPollTests(TestCase):
    def setUp(self):
        self.ana = make('ana')

    def armed(self, user=None):
        user = user or self.ana
        user.refresh_from_db()
        return user.first_cusd_acquired_at is not None

    def test_every_incoming_conversion_arms_icp(self):
        for kind in ('to_savings', 'usdt_to_cusd', 'usdc_to_cusd'):
            with self.subTest(kind=kind):
                user = make(f'c-{kind}')
                convert(user, kind)
                self.assertTrue(self.armed(user))
                self.assertEqual(pending(user), PendingModalEnum.ICP)

    def test_conversion_arms_when_it_flips_to_completed(self):
        conv = convert(self.ana, status='SUBMITTED')
        self.assertFalse(self.armed())
        conv.status, conv.completed_at = 'COMPLETED', timezone.now()
        conv.save()
        self.assertTrue(self.armed())

    def test_outgoing_and_business_conversions_do_not_arm(self):
        for kind in ('from_savings', 'cusd_to_usdt', 'cusd_to_usdc'):
            convert(self.ana, kind)
        Conversion.objects.create(
            actor_user=self.ana, actor_type='business', conversion_type='to_savings',
            from_amount=Decimal('10'), to_amount=Decimal('10'), exchange_rate=Decimal('1'),
            fee_amount=Decimal('0'), status='COMPLETED', completed_at=timezone.now())
        self.assertFalse(self.armed())

    def test_received_cusd_and_dollar_plus_sends_arm(self):
        for token in ('CUSD_PLUS', 'CUSD'):
            with self.subTest(token=token):
                user = make(f'r-{token.lower()}')
                send(user, token)
                self.assertTrue(self.armed(user))

    def test_usdt_unconfirmed_business_and_self_sends_do_not_arm(self):
        from users.models import Business
        send(self.ana, 'USDT')  # its USDT -> Dollar+ conversion arms instead
        send(self.ana, 'CUSD_PLUS', status='SUBMITTED')
        send(self.ana, 'CUSD_PLUS', sender=self.ana)
        biz = Business.objects.create(name='Tienda', category='retail')
        SendTransaction.objects.create(
            sender_user=make('client'), recipient_user=self.ana, recipient_business=biz,
            recipient_type='business', sender_address='0x' + '1' * 40, recipient_address='0x' + '2' * 40,
            amount=Decimal('5'), token_type='CUSD_PLUS', status='CONFIRMED')
        self.assertFalse(self.armed())

    def test_rating_arms_on_next_inflow_after_icp_answered(self):
        convert(self.ana)
        User.objects.filter(pk=self.ana.pk).update(confio_icp_captured_at=timezone.now())
        convert(self.ana)
        self.ana.refresh_from_db()
        self.assertIsNotNone(self.ana.rating_prompt_due_at)
        self.assertEqual(pending(self.ana), PendingModalEnum.RATING)

    def test_resave_of_the_first_conversion_never_arms_rating(self):
        conv = convert(self.ana)
        User.objects.filter(pk=self.ana.pk).update(confio_icp_captured_at=timezone.now())
        conv.save()  # later bookkeeping re-save of the same finished row
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.rating_prompt_due_at)

    def test_first_timestamp_is_kept(self):
        first = timezone.now() - timedelta(days=2)
        convert(self.ana, at=first)
        convert(self.ana)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.first_cusd_acquired_at, first)


class BackfillFirstDollarsTests(TestCase):
    def test_dry_run_writes_nothing_and_apply_uses_earliest_inflow(self):
        ana = make('ana-b')
        early = timezone.now() - timedelta(days=30)
        convert(ana, at=early)
        send(ana, 'CUSD_PLUS')
        User.objects.filter(pk=ana.pk).update(first_cusd_acquired_at=None)  # a pre-fix user

        out = StringIO()
        call_command('backfill_first_dollars_received', stdout=out)
        ana.refresh_from_db()
        self.assertIsNone(ana.first_cusd_acquired_at)
        self.assertIn('users to backfill: 1', out.getvalue())

        call_command('backfill_first_dollars_received', '--apply', stdout=StringIO())
        ana.refresh_from_db()
        self.assertEqual(ana.first_cusd_acquired_at, early)

    def test_since_filters_old_inflows_and_already_set_is_untouched(self):
        old, done = make('old-b'), make('done-b')
        convert(old, at=timezone.now() - timedelta(days=400))
        User.objects.filter(pk=old.pk).update(first_cusd_acquired_at=None)
        kept = timezone.now() - timedelta(days=1)
        convert(done)
        User.objects.filter(pk=done.pk).update(first_cusd_acquired_at=kept)

        since = (timezone.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        call_command('backfill_first_dollars_received', '--apply', '--since', since, stdout=StringIO())
        old.refresh_from_db()
        done.refresh_from_db()
        self.assertIsNone(old.first_cusd_acquired_at)
        self.assertEqual(done.first_cusd_acquired_at, kept)
