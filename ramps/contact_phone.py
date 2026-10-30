"""The number providers get for a person who signed up without a phone.

Infinia and Koywe both require one on the provider owner. It is self-declared
and never verified, so it is kept away from `User.phone_number`/`phone_key`:
those mean a verified identity and drive matching. This one reaches nobody but
the provider that opens the person's account, and when someone with a verified
phone sets one, it replaces that number for providers only.
"""
from users.phone_utils import normalize_any_phone, to_international

MIN_LOCAL_DIGITS = 6


def normalize_contact_phone(raw: str) -> str | None:
    """'+59171234567' for a number with a real calling code, else None."""
    digits = ''.join(ch for ch in (raw or '') if ch.isdigit())
    key = normalize_any_phone(f'+{digits}') if digits else None
    if not key or ':' not in key:
        return None
    local = key.partition(':')[2]
    if len(local) < MIN_LOCAL_DIGITS or len(digits) > 15 or len(set(local)) == 1:
        return None
    return to_international(key)


def saved_contact_phone(user) -> str:
    if not getattr(user, 'pk', None):
        return ''
    from ramps.models import RampUserAddress
    return (RampUserAddress.objects.filter(user=user).values_list('contact_phone', flat=True).first() or '').strip()


def provider_phone(user) -> str:
    """The number providers get: the one the person set, else the verified one."""
    return saved_contact_phone(user) or (to_international(user=user) if getattr(user, 'phone_number', None) else '')


def has_provider_phone(user) -> bool:
    return bool(getattr(user, 'phone_number', None) or saved_contact_phone(user))
