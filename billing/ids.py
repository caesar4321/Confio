import uuid

from django.utils.deconstruct import deconstructible


@deconstructible
class PrefixedPublicId:
    """Migration-safe callable for opaque, type-identifying public IDs."""

    def __init__(self, prefix):
        self.prefix = prefix

    def __call__(self):
        return f'{self.prefix}_{uuid.uuid4().hex}'


subject_id = PrefixedPublicId('subj')
obligation_id = PrefixedPublicId('obl')
invoice_id = PrefixedPublicId('inv')
payment_intent_id = PrefixedPublicId('pi')
quote_id = PrefixedPublicId('qt')
payment_id = PrefixedPublicId('pay')
effect_id = PrefixedPublicId('eff')
settlement_id = PrefixedPublicId('set')
application_id = PrefixedPublicId('app')
event_id = PrefixedPublicId('evt')
outbox_id = PrefixedPublicId('out')
api_key_id = PrefixedPublicId('key')
request_id = PrefixedPublicId('req')
webhook_endpoint_id = PrefixedPublicId('we')
webhook_delivery_id = PrefixedPublicId('wd')
institution_connection_id = PrefixedPublicId('icn')
identity_grant_id = PrefixedPublicId('igr')
identity_session_id = PrefixedPublicId('ise')
schedule_id = PrefixedPublicId('sch')
import_id = PrefixedPublicId('imp')
cip_sandbox_member_id = PrefixedPublicId('cipsm')
cip_sandbox_receipt_id = PrefixedPublicId('cipsr')
