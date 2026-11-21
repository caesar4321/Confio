"""JWT account context rules (spec 7.2, 10.3)."""
from types import SimpleNamespace
from unittest import mock

from graphql import GraphQLError

from smart_account import context, schema, services
from smart_account.models import SmartAccountBeneficiary, SmartAccountClaim
from users.jwt_context import get_jwt_business_context_with_validation

from .base import SmartAccountTestCase

from django.utils import timezone


def _resolve_info(field_name, operation='mutation', ctx=None, nested=False):
    return SimpleNamespace(
        path=SimpleNamespace(prev=object() if nested else None),
        operation=SimpleNamespace(operation=SimpleNamespace(value=operation)),
        field_name=field_name, context=ctx)


class SmartContextTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)

    def test_smart_context_is_refused_by_default_and_allowed_only_on_request(self):
        info = self.info(self.owner, 'smart', 0)
        self.assertIsNone(get_jwt_business_context_with_validation(info))
        self.assertIsNone(get_jwt_business_context_with_validation(info, required_permission='send_funds'))
        ctx = get_jwt_business_context_with_validation(info, allow_smart=True)
        self.assertEqual((ctx['account_type'], ctx['account_index']), ('smart', 0))

    def test_smart_context_for_an_account_the_user_does_not_hold_is_refused(self):
        stranger = self.make_user('stranger')
        self.assertIsNone(get_jwt_business_context_with_validation(
            self.info(stranger, 'smart', 0), allow_smart=True))
        self.assertIsNone(get_jwt_business_context_with_validation(
            self.info(self.owner, 'smart', 3), allow_smart=True))

    def test_unknown_account_type_is_never_personal(self):
        self.assertIsNone(get_jwt_business_context_with_validation(self.info(self.owner, 'vault', 0)))
        self.assertIsNotNone(get_jwt_business_context_with_validation(self.info(self.owner, 'personal', 0)))

    def test_existing_account_helpers_refuse_a_smart_context(self):
        from cusd_plus.schema import _active_account, _active_bsc_address
        info = self.info(self.owner, 'smart', 0)
        self.assertIsNone(_active_account(info))
        self.assertIsNone(_active_bsc_address(info))
        from payment_accounts.schema import _active_account as payment_account
        with self.assertRaises(Exception):
            payment_account(info)
        from marketplace.permissions import account_for
        with self.assertRaises(Exception):
            account_for(info)

    def test_mutation_gate_refuses_everything_outside_the_allowlist(self):
        from config.schema import schema as root_schema
        gate = context.SmartContextGateMiddleware()
        smart = self.info(self.owner, 'smart', 0).context
        fields = set(root_schema.graphql_schema.mutation_type.fields)
        self.assertTrue(context.ALLOWED_MUTATIONS - {'invalidateAuthTokens'} <= fields,
                        context.ALLOWED_MUTATIONS - fields)
        refused = fields - context.ALLOWED_MUTATIONS
        for name in sorted(refused):
            with self.assertRaises(GraphQLError, msg=name):
                gate.resolve(lambda *a, **k: 'ran', None, _resolve_info(name, ctx=smart))
        for name in ('prepareSmartAccountDeposit', 'sponsorBscBatch', 'prepareClaimCancel'):
            self.assertEqual(gate.resolve(lambda *a, **k: 'ran', None, _resolve_info(name, ctx=smart)), 'ran')

    def test_unsupported_flows_are_among_the_refused_mutations(self):
        """P2P, payroll, presale, perps, ramps and Comprar (dual enforcement)."""
        from cusd_plus import perps_schema
        from marketplace import schema as market
        from p2p_exchange import schema as p2p
        from payroll import schema as payroll
        from presale import schema as presale
        from ramps import schema as ramps
        import graphene
        for module_mutation in (p2p.Mutation, payroll.Mutation, presale.PresaleMutations, perps_schema.Mutation,
                                ramps.Mutation, market.Mutation):
            names = set(graphene.Schema(query=_Q, mutation=module_mutation).graphql_schema.mutation_type.fields)
            self.assertTrue(names)
            self.assertEqual(names & context.ALLOWED_MUTATIONS, set(), module_mutation)

    def test_gate_does_not_touch_other_contexts_queries_or_nested_fields(self):
        gate = context.SmartContextGateMiddleware()
        run = lambda *a, **k: 'ran'  # noqa: E731
        personal = self.info(self.owner, 'personal', 0).context
        smart = self.info(self.owner, 'smart', 0).context
        self.assertEqual(gate.resolve(run, None, _resolve_info('createP2pTrade', ctx=personal)), 'ran')
        self.assertEqual(gate.resolve(run, None, _resolve_info('anything', 'query', ctx=smart)), 'ran')
        self.assertEqual(gate.resolve(run, None, _resolve_info('createP2pTrade', ctx=smart, nested=True)), 'ran')
        with self.assertRaises(GraphQLError):
            gate.resolve(run, None, _resolve_info('anySubscription', 'subscription', ctx=smart))

    def test_switch_account_token_needs_ownership_and_carries_the_claims(self):
        from users.schema import SwitchAccountToken
        info = self.info(self.owner)
        result = SwitchAccountToken.mutate(None, info, account_type='smart', account_index=0)
        self.assertEqual((result.payload['account_type'], result.payload['account_index'],
                          result.payload['business_id']), ('smart', 0, None))
        stranger = self.make_user('stranger')
        with self.assertRaises(Exception):
            SwitchAccountToken.mutate(None, self.info(stranger), account_type='smart', account_index=0)
        with self.assertRaises(Exception):
            SwitchAccountToken.mutate(None, info, account_type='smart', account_index=1)

    def test_inherited_account_is_switched_to_by_its_index(self):
        from users.schema import SwitchAccountToken
        heir = self.make_user('heir')
        self.make_account(heir, status='inherited', index=1)
        result = SwitchAccountToken.mutate(None, self.info(heir), account_type='smart', account_index=1)
        self.assertEqual(result.payload['account_index'], 1)
        self.assertIsNotNone(get_jwt_business_context_with_validation(
            self.info(heir, 'smart', 1), allow_smart=True))

    def test_refresh_keeps_smart_claims_only_while_the_account_is_owned(self):
        from users.jwt import jwt_payload_handler
        ctx = SimpleNamespace(active_account_type='smart', active_account_index=0, active_business_id=None)
        self.assertEqual(jwt_payload_handler(self.owner, ctx)['account_type'], 'smart')
        stranger = self.make_user('stranger')
        payload = jwt_payload_handler(stranger, ctx)
        self.assertEqual((payload['account_type'], payload['account_index']), ('personal', 0))

    def test_business_and_employee_contexts_cannot_reach_the_mutations(self):
        info = self.info(self.owner, 'business', 0, business_id='999')
        with self.assertRaises(context.ContextError):
            context.resolve_viewer(info)
        with mock.patch('users.jwt_context.get_jwt_business_context_with_validation',
                        return_value={'account_type': 'business', 'account_index': 0, 'business_id': '5'}):
            for mutation, kwargs in (
                    (schema.PrepareSmartAccountCancel, {}),
                    (schema.PrepareSmartAccountDeposit, {'deposits': []}),
                    (schema.PrepareBeneficiaryDesignation,
                     {'beneficiary_handle': 'x', 'window_days': 180, 'disclosure_accepted': True}),
                    (schema.PrepareSmartAccountSubscribe, {'plan': 'annual', 'disclosures_accepted': True})):
                result = mutation.mutate(None, self.info(self.owner), **kwargs)
                self.assertFalse(result.success)
                self.assertEqual(result.error_code, 'personal_only')

    def test_claim_cancel_and_alert_work_from_every_context(self):
        heir = self.make_user('heir')
        row = SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=heir, beneficiary_address=heir.wallet,
            challenge_window_seconds=90 * 86400, state='active', designated_at=timezone.now())
        SmartAccountClaim.objects.create(
            beneficiary_row=row, initiated_at=timezone.now(), initiated_tx='0x' + '02' * 32,
            executable_at=timezone.now() + timezone.timedelta(days=90))
        with mock.patch('users.jwt_context.get_jwt_business_context_with_validation',
                        return_value={'account_type': 'business', 'account_index': 0, 'business_id': '5'}):
            result = schema.PrepareClaimCancel.mutate(None, self.info(self.owner, 'business', 0, '5'))
        self.assertTrue(result.success, result.error_code)
        self.assertEqual(len(result.calls), 1)
        self.assertEqual(result.calls[0].to, self.account.contract_address.lower())
        alert = schema.Query.resolve_smart_account_claim_alert(None, self.info(self.owner, 'business', 0, '5'))
        self.assertEqual(alert.beneficiary_name, services.display_name(heir))
        self.assertIsNone(schema.Query.resolve_smart_account_claim_alert(None, self.info(heir)))

    def test_no_mutation_takes_an_account_id_or_address_as_authority(self):
        from config.schema import schema as root_schema
        fields = root_schema.graphql_schema.mutation_type.fields
        mine = [n for n in fields if n.startswith(('prepareSmartAccount', 'prepareBeneficiary', 'prepareClaim',
                                                   'prepareInherited', 'declineBeneficiary'))]
        self.assertGreaterEqual(len(mine), 22)
        for name in mine:
            for arg in fields[name].args:
                self.assertNotRegex(arg.lower(), r'address|^accountid$|^account$|userid|owner', f'{name}.{arg}')
        # The opaque ids are checked against the JWT user.
        stranger = self.make_user('stranger')
        with self.assertRaises(services.PrepareError):
            services.inherited_account_for(self.viewer(stranger), str(self.account.internal_id))


import graphene  # noqa: E402


class _Q(graphene.ObjectType):
    ok = graphene.Boolean()
