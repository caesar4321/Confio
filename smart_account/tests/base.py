"""Shared fixtures. Chain access is mocked; the Telegram alert path and push
delivery are patched for every test (local tests otherwise reach the real
team channel and real devices)."""
import itertools
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from smart_account import abi, context
from smart_account.models import SmartAccount

FACTORY = '0x' + 'fa' * 20
VAULT = '0x' + 'a1' * 20       # cUSD+
CUSD = '0x' + 'c1' * 20
STOCK_ROUTER = '0x' + '51' * 20
SWAP_ROUTER = '0x' + '52' * 20
USDT = '0x55d398326f99059ff775485246999027b3197955'
BUILD = {'HTTP_X_CONFIO_VERSION': '6.0.0'}
WAD = 10 ** 18

SETTINGS = dict(
    SMART_ACCOUNT_ENABLED=True, SMART_ACCOUNT_FACTORY_ADDRESS=FACTORY,
    SMART_ACCOUNT_ALLOWED_USER_IDS='*', SMART_ACCOUNT_MIN_APP_VERSION='6.0.0',
    SMART_ACCOUNT_BENEFICIARY_ENABLED=True, SMART_ACCOUNT_PAYOUT_RAILS='',
    SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=False, SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM=False,
    SMART_ACCOUNT_RELAYER_REFERRAL_ENABLED=False,
    SMART_ACCOUNT_MONTHLY_PRICE_USD='14.99', SMART_ACCOUNT_ANNUAL_PRICE_USD='149.99',
    SMART_ACCOUNT_DEFAULT_PLAN='annual',
    CUSD_PLUS_VAULT_ADDRESS=VAULT, CUSD_VAULT_ADDRESS=CUSD, BSC_CONFIO_TOKEN_ADDRESS='',
    CUSD_PLUS_STOCK_ROUTER_ADDRESS=STOCK_ROUTER, CRYPTO_SWAP_ROUTER_ADDRESS=SWAP_ROUTER,
    CUSD_CONVERSION_FEE_ENABLED=False,
)

_addresses = itertools.count(1)


def vault_preview(fee_bps: int = 90):
    """cusd_plus.cusd_vault.preview_redeem_wei with CusdVault's real
    arithmetic: fee = mulDiv(gross, feeBps, 10000, Ceil), net = gross - fee."""
    def preview(gross_wei):
        gross = int(gross_wei)
        fee = -(-gross * fee_bps // 10_000) if gross and fee_bps else 0
        return SimpleNamespace(gross_wei=gross, fee_wei=fee, net_wei=gross - fee, fee_bps=fee_bps)
    return preview


def new_address() -> str:
    return '0x' + format(next(_addresses), 'x').rjust(40, '0').replace('0', 'e', 1)


class FakeChain:
    """Stand-in for smart_account.chain reads."""

    def __init__(self):
        self.balances = {}          # (token, holder) -> int
        self.views = {}             # (address, view) -> value
        self.rules = {}             # (address, id) -> dict
        self.fees = {'monthly': int(14.99 * 100) * 10 ** 16, 'annual': int(149.99 * 100) * 10 ** 16}
        self.scheduled = {'monthly': (0, 0), 'annual': (0, 0)}
        self.accounts = {}          # owner -> account (factory.accountOf)
        self.generations = {}       # owner -> factory.generationOf
        self.inheritance = True
        self.paused = False
        self.fail = set()           # names that raise

    def _maybe_fail(self, name):
        if name in self.fail:
            raise RuntimeError(f'rpc down: {name}')

    def balance_of(self, token, holder):
        self._maybe_fail('balance_of')
        return self.balances.get((token.lower(), holder.lower()), 0)

    def account_view(self, address, name):
        self._maybe_fail('account_view')
        return self.views.get((address.lower(), name), 0)

    def account_rule(self, address, rule_id):
        self._maybe_fail('account_rule')
        rule = dict(self.rules[(address.lower(), int(rule_id))])
        if 'epoch' not in rule:
            # Unless a test says otherwise, the rule was stored in the
            # account's current subscription epoch (the mirror's).
            account = SmartAccount.all_objects.filter(contract_address__iexact=address).first()
            rule['epoch'] = int(account.subscription_epoch) if account is not None else 0
        return rule

    def factory_fee_usd_wei(self, plan):
        self._maybe_fail('factory_fee_usd_wei')
        return self.fees[plan]

    def factory_scheduled_fee(self, plan):
        return self.scheduled[plan]

    def predict_address_at(self, owner, generation):
        self._maybe_fail('predict_address')
        return '0x' + ('bb' if not generation else format(int(generation), '02x')) * 8 + owner.lower()[2:26]

    def _replaceable(self, account, owner):
        return bool(self.views.get((account, 'inherited'))) or self.views.get((account, 'owner')) != owner

    def predict_address(self, owner):
        # The factory's predictAddress: the current account while it is
        # still the owner's, else where the next createAccount deploys.
        owner = owner.lower()
        current = self.accounts.get(owner, abi.ZERO_ADDRESS)
        generation = self.generations.get(owner, 0)
        if int(current, 16):
            if not self._replaceable(current, owner):
                self._maybe_fail('predict_address')
                return current
            generation += 1
        return self.predict_address_at(owner, generation)

    def generation_of(self, owner):
        self._maybe_fail('generation_of')
        return self.generations.get(owner.lower(), 0)

    def create_account(self, owner):
        """What a mined createAccount does to the factory views."""
        owner = owner.lower()
        address = self.predict_address(owner)
        if int(self.accounts.get(owner, abi.ZERO_ADDRESS), 16):
            assert address != self.accounts[owner], 'account exists'
            self.generations[owner] = self.generations.get(owner, 0) + 1
        self.accounts[owner] = address
        self.views[(address, 'owner')] = owner
        self.views[(address, 'inherited')] = False
        return address

    def account_of(self, owner):
        self._maybe_fail('account_of')
        return self.accounts.get(owner.lower(), abi.ZERO_ADDRESS)

    def patches(self):
        names = ['balance_of', 'account_view', 'account_rule', 'factory_fee_usd_wei',
                 'factory_scheduled_fee', 'predict_address', 'predict_address_at', 'generation_of', 'account_of']
        out = [mock.patch(f'smart_account.chain.{n}', side_effect=getattr(self, n)) for n in names]
        out += [
            mock.patch('smart_account.chain.p_plus_wad', side_effect=lambda: WAD),
            # Post-accrual pPlus window (quotes.plus_price_window); tests of
            # the accrual itself patch the vault reads under the real function.
            mock.patch('smart_account.quotes.plus_price_window', side_effect=lambda *a, **k: (WAD, WAD)),
            mock.patch('smart_account.chain.inheritance_enabled', side_effect=lambda: self.inheritance),
            mock.patch('smart_account.chain.window_allowed', side_effect=lambda s: s in (90 * 86400, 180 * 86400, 365 * 86400)),
            mock.patch('smart_account.chain.relayer_paused', side_effect=lambda: self.paused),
            mock.patch('smart_account.chain.conversion_fee_bps', side_effect=lambda: 90),
            mock.patch('smart_account.chain.usdt_address', side_effect=lambda: USDT),
            mock.patch('smart_account.chain.confio_sale', side_effect=lambda: (abi.ZERO_ADDRESS, abi.ZERO_ADDRESS)),
        ]
        return out


@override_settings(**SETTINGS)
class SmartAccountTestCase(TestCase):
    mock_approvals = True

    def setUp(self):
        super().setUp()
        cache.clear()
        self.chain = FakeChain()
        from smart_account import services as _services
        self.real_residence_check = _services.residence_check
        self.ops_alert = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)
        self.ops_alert_mock = self.ops_alert.start()
        patches = self.chain.patches() + [
            mock.patch('config.ops_alerts.send_public_notice', return_value=True),
            mock.patch('config.ops_alerts._send', return_value=True),
            mock.patch('notifications.utils.send_push_notification', return_value={'success': True, 'sent': 0, 'failed': 0}),
            mock.patch('security.identity_status.is_identity_verified', side_effect=lambda u: u.pk not in self.unverified),
            mock.patch('security.identity_reuse.outgoing_identity_restriction', side_effect=lambda u: self.holds.get(u.pk, '')),
            mock.patch('security.minors.is_known_minor', return_value=False),
            mock.patch('smart_account.services.residence_check', side_effect=lambda u: self.residence.get(u.pk, 'ok')),
            mock.patch('cusd_plus.fee_referral.same_person', return_value=False),
            mock.patch('cusd_plus.gm_holdings.holdings_units', return_value={}),
            mock.patch('cusd_plus.crypto_holdings.holdings_units', return_value={}),
            mock.patch('cusd_plus.vault.invalidate_position'),
            mock.patch('cusd_plus.gm_holdings.invalidate_holdings'),
            mock.patch('cusd_plus.crypto_holdings.invalidate_holdings'),
            mock.patch('smart_account.offer.viewer_dollar', return_value='cusd_plus'),
        ]
        if self.mock_approvals:
            # The factory approval sent before a designation/acceptance batch
            # (smart_account/approvals.py) is exercised in test_approvals.
            patches += [
                mock.patch('smart_account.approvals.ensure_designation', return_value='existing'),
                mock.patch('smart_account.approvals.ensure_acceptance', return_value='existing'),
            ]
        self.unverified, self.holds, self.residence = set(), {}, {}
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.ops_alert.stop)

    # ── fixtures ──
    def make_user(self, username: str):
        from users.models import Account
        user = get_user_model().objects.create_user(
            username=username, password='x', firebase_uid=f'uid-{username}', first_name=username.capitalize())
        account = Account.objects.create(user=user, account_type='personal', account_index=0,
                                         bsc_address=new_address())
        user.wallet = account.bsc_address.lower()
        return user

    def make_account(self, user, *, status='active', plan='annual', paid_days=30, index=0, **fields):
        from users.models import Account
        personal = context.personal_account(user)
        contract = new_address()
        row = Account.objects.create(user=user, account_type='smart', account_index=index, bsc_address=contract)
        values = dict(owner_user=user, owner_account=personal, account=row, contract_address=contract,
                      status=status, plan=plan if status not in ('none', 'inherited') else '',
                      paid_until=timezone.now() + timezone.timedelta(days=paid_days))
        if status == 'inherited':
            values.update(inherited_at=timezone.now(), paid_until=None)
        values.update(fields)
        # The chain agrees with the row unless a test says otherwise.
        self.chain.views[(contract.lower(), 'owner')] = personal.bsc_address.lower()
        self.chain.views[(contract.lower(), 'inherited')] = status == 'inherited'
        if status != 'inherited' and index == 0:
            # factory.accountOf names the owner's own account.
            self.chain.accounts.setdefault(personal.bsc_address.lower(), contract.lower())
        return SmartAccount.objects.create(**values)

    def info(self, user, account_type='personal', index=0, business_id=None, meta=None):
        from graphql_jwt.utils import jwt_encode
        payload = {'user_id': user.pk, 'username': user.username, 'auth_token_version': 1,
                   'account_type': account_type, 'account_index': index, 'business_id': business_id,
                   'exp': int(timezone.now().timestamp()) + 3600, 'origIat': int(timezone.now().timestamp())}
        headers = {'HTTP_AUTHORIZATION': 'JWT ' + jwt_encode(payload), **BUILD, **(meta or {})}
        user.is_authenticated  # noqa: B018 — real user objects are authenticated
        return SimpleNamespace(context=SimpleNamespace(user=user, META=headers))

    def viewer(self, user, account_type='personal'):
        return context.Viewer(user=user, personal_account=context.personal_account(user),
                              context_type=account_type, meta=dict(BUILD))

    def fund(self, token, holder, amount):
        self.chain.balances[(token.lower(), holder.lower())] = int(amount)
