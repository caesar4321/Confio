"""An edited phone or address reaches the provider accounts already open.

Runs after the save, off the request: a provider that is down or refuses the
update (Koywe rejects any write to a blocked account) never fails the save, and
the task retries.
"""
import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def queue_profile_push(user_id: int) -> None:
    def enqueue():
        from ramps.tasks import push_ramp_profile
        try:
            push_ramp_profile.delay(user_id)
        except Exception:
            logger.exception('Could not queue the profile push for user %s', user_id)
    transaction.on_commit(enqueue)


def _push_to_koywe(user) -> bool:
    from ramps.koywe_client import KoyweClient
    from ramps.models import RampTransaction
    from ramps.schema import _get_koywe_auth_email, _get_koywe_contact_profile
    orders = (RampTransaction.objects.filter(actor_user=user, provider='koywe').exclude(country_code='')
              .order_by('-created_at'))
    # A reservation still waiting for Koywe has no email yet.
    last_order = orders.filter(metadata__auth_email__gt='').first() or orders.first()
    if last_order is None:
        return False
    country_code = last_order.country_code
    # Koywe holds the account under the last order's email, whatever the
    # address form says now; the next order is what migrates it.
    email = ((last_order.metadata or {}).get('auth_email')
             or _get_koywe_auth_email(user=user, country_code=country_code))
    profile = _get_koywe_contact_profile(user=user, country_code=country_code, email_override=email)
    return KoyweClient().push_account_profile(email=email, country_code=country_code, contact_profile=profile)


def _push_to_infinia(user) -> int:
    from payment_accounts.clients import InfiniaClient
    from payment_accounts.compliance import declared_address_for_provider
    from payment_accounts.models import ProviderProfile
    from ramps.contact_phone import provider_phone
    from ramps.schema import _build_effective_ramp_address_snapshot
    profiles = ProviderProfile.objects.filter(
        confio_account__user=user, provider='infinia', owner_type='individual', kyc_mode='SELF_DECLARED',
    ).exclude(provider_owner_id__isnull=True).exclude(provider_owner_id='')
    if not profiles.exists():
        return 0
    individual = {'address': declared_address_for_provider(_build_effective_ramp_address_snapshot(user))}
    phone = provider_phone(user)
    if phone:
        individual['phone_number'] = phone
    client = InfiniaClient()
    for profile in profiles:
        client.update_owner(profile.provider_owner_id, {'individual': individual})
    return profiles.count()


def push_to_providers(user_id: int) -> list[str]:
    """Pushes to each provider independently; returns the ones that failed."""
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.get(pk=user_id)
    failed = []
    for name, push in (('koywe', _push_to_koywe), ('infinia', _push_to_infinia)):
        try:
            push(user)
        except Exception:
            logger.exception('Profile push to %s failed for user %s', name, user_id)
            failed.append(name)
    return failed
