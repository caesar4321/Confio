"""The "Oficial" rule for Descubrir channels.

A channel is Oficial only while ALL of these hold:

1. Staff granted it (``official_granted_at``), recording who and how they
   confirmed who controls the channel (``official_note``).
2. Its owner can be verified: a Confío system channel, or a business-owned
   channel whose business has a *verified* KYB (business IdentityVerification).
   System-owned channels qualify only as Confío's own kinds (founder, news,
   system); user-owned channels never qualify.
3. That KYB still holds right now. It is evaluated on every read, not copied
   at grant time, so a revoked or deleted KYB drops the badge by itself.

Businesses and institutions follow the same rule; ``kind`` only decides which
Descubrir section their posts appear under.
"""
from .models import ChannelKind, OwnerType

# Only Confío's own voices may skip KYB. A system-owned channel dressed up as a
# business or institution would otherwise be a way around rule 2.
CONFIO_KINDS = (ChannelKind.FOUNDER, ChannelKind.NEWS, ChannelKind.SYSTEM)

NOT_GRANTED = 'not_granted'
OFFICIAL = 'official'
OWNER_NOT_VERIFIED = 'owner_not_verified'
OWNER_NOT_ELIGIBLE = 'owner_not_eligible'


def verified_business_ids(business_ids):
    """The subset of business ids with a verified business KYB, in one query."""
    ids = {str(business_id) for business_id in business_ids if business_id}
    if not ids:
        return set()
    from security.models import IdentityVerification

    return set(
        IdentityVerification.objects.filter(
            status='verified',
            risk_factors__account_type='business',
            risk_factors__business_id__in=ids,
        ).values_list('risk_factors__business_id', flat=True)
    )


def owner_status(channel, verified_ids=None):
    """Whether the channel's owner can carry the badge, ignoring the grant."""
    if channel.owner_type == OwnerType.SYSTEM:
        return OFFICIAL if channel.kind in CONFIO_KINDS else OWNER_NOT_ELIGIBLE
    if channel.owner_type != OwnerType.BUSINESS or not channel.owner_business_id:
        return OWNER_NOT_ELIGIBLE
    if verified_ids is None:
        verified_ids = verified_business_ids([channel.owner_business_id])
    return OFFICIAL if str(channel.owner_business_id) in verified_ids else OWNER_NOT_VERIFIED


def official_status(channel, verified_ids=None):
    if channel.official_granted_at is None:
        return NOT_GRANTED
    return owner_status(channel, verified_ids)


def official_channel_ids(channels):
    """Ids of the Oficial channels among ``channels``, with one KYB query total."""
    channels = list({channel.id: channel for channel in channels}.values())
    verified_ids = verified_business_ids(
        channel.owner_business_id
        for channel in channels
        if channel.official_granted_at is not None and channel.owner_type == OwnerType.BUSINESS
    )
    return {channel.id for channel in channels if official_status(channel, verified_ids) == OFFICIAL}


def all_official_channel_ids():
    """Every Oficial channel right now, for filtering the Descubrir feed."""
    from .models import Channel

    return official_channel_ids(Channel.objects.filter(official_granted_at__isnull=False))
