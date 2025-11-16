import re
from typing import Optional
from django.contrib.auth import get_user_model

User = get_user_model()


USERNAME_MAX_LENGTH = 20
USERNAME_MIN_LENGTH = 3
USERNAME_REGEX = re.compile(r'[^a-zA-Z0-9_]')


def generate_compliant_username(
    seed: Optional[str],
    fallback: str = "confio",
    exclude_user_id: Optional[int] = None,
) -> str:
    """
    Generate a username that matches the client constraint:
    - Only letters, numbers, underscore
    - Between 3 and 20 characters
    - Unique (case-insensitive)
    """
    seed = (seed or "").strip()
    base = USERNAME_REGEX.sub("", seed)
    if not base:
        base = fallback
    # Enforce length and lowercase for consistency
    base = base[:USERNAME_MAX_LENGTH]
    base = base.lower()
    if len(base) < USERNAME_MIN_LENGTH:
        base = (base + fallback)[:USERNAME_MAX_LENGTH]
    counter = 0
    candidate = base
    while True:
        qs = User.objects.filter(username__iexact=candidate)
        if exclude_user_id:
            qs = qs.exclude(id=exclude_user_id)
        if not qs.exists():
            return candidate
        counter += 1
        suffix = f"_{counter}"
        candidate = f"{base[:USERNAME_MAX_LENGTH - len(suffix)]}{suffix}"
