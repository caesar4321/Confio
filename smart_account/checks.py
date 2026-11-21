"""Startup checks for Cuenta inteligente settings."""
from django.conf import settings
from django.core.checks import Warning, register


@register()
def cancel_claim_required_with_beneficiaries(app_configs=None, **kwargs):
    """With beneficiaries on, an owner's personal batches should be required
    to carry cancelClaim() while a claim is pending (spec 6.4). Off, a claim
    can run its window out while the owner keeps using the app normally."""
    if (getattr(settings, 'SMART_ACCOUNT_BENEFICIARY_ENABLED', False)
            and not getattr(settings, 'SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM', False)):
        return [Warning(
            'SMART_ACCOUNT_BENEFICIARY_ENABLED is on but SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM is off: '
            'personal-wallet batches are not required to cancel a pending claim.',
            hint='Turn on SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM once the minimum supported app build '
                 'appends cancelClaim().',
            id='smart_account.W001')]
    return []
