"""Face authorization at the generic BSC rail's external-outflow boundary."""
from django.conf import settings


def has_external_outflow(calls, signer, *, legacy=False):
    """Inspect policy-validated calls; internal conversions do not spend a face.

    The legacy relay has a broader contract allowlist, so unknown calls are
    conservative. Known conversions are exempt only when their recipient is
    the signer. Approvals have already passed the spender policy.
    """
    from . import sponsor_7702 as sponsor
    signer = signer.lower()
    vaults = {
        str(getattr(settings, name, '') or '').lower()
        for name in ('CUSD_PLUS_VAULT_ADDRESS', 'CUSD_VAULT_ADDRESS')
    } - {''}
    conversions = {
        sponsor.SEL_SUBSCRIBE_AND_MINT, sponsor.SEL_REDEEM_TO_USDT,
        sponsor.SEL_WRAP_CUSD, sponsor.SEL_UNWRAP_TO_CUSD,
        sponsor.SEL_CUSD_MINT, sponsor.SEL_CUSD_REDEEM,
    }
    for call in calls:
        target = call['to'].lower()
        data = call['data'].removeprefix('0x').lower()
        selector = data[:8]
        recipient_word = None
        if selector == sponsor.SEL_TRANSFER:
            recipient_word = 0
        elif legacy and selector == '23b872dd':  # transferFrom
            recipient_word = 1
        elif target in vaults and selector in conversions:
            recipient_word = 2
        elif (legacy and selector == '7ff36ab5'
              and target == str(getattr(settings, 'CUSD_PLUS_PANCAKE_ROUTER', '') or '').lower()):
            # The allowed BNB auto-convert router returns tokens to the signer.
            recipient_word = 2
        elif selector == sponsor.SEL_APPROVE:
            if int(call.get('value', 0)):
                return True
            if legacy and (len(data) != 136 or '0x' + data[32:72] not in vaults):
                return True
            continue
        elif legacy:
            return True
        else:
            # Generic policy pins stock-trade settlement to the signer.
            continue
        end = 8 + (recipient_word + 1) * 64
        if len(data) < end or '0x' + data[end - 40:end] != signer:
            return True
        if int(call.get('value', 0)) and selector != '7ff36ab5':
            return True
    return False


def claim_external_outflow(user, context, calls, signer, *, namespace,
                           identifier, payload, legacy=False):
    if not has_external_outflow(calls, signer, legacy=legacy):
        return ''
    from security.identity_reuse import outgoing_identity_restriction
    restriction = outgoing_identity_restriction(user)
    if restriction:
        return restriction
    if context and context.get('account_type') == 'business':
        return ''
    from security.face_step_up import require_face_step_up, withdrawal_action_key
    key = withdrawal_action_key(namespace, identifier, payload)
    return require_face_step_up(user, 'withdrawal', action_key=key, consume=True)
