"""Partial disclosure of identifiers shown to people who may not own them."""

EMAIL_MASK = '•••'


def mask_email(email):
    """Show an owner enough of an address to recognize it, and a stranger too
    little to learn it: 'julian@gmail.com' -> 'ju•••@gmail.com'.

    The mask has a fixed length so it does not reveal the address length.
    Missing or malformed values reveal nothing.
    """
    local, at, domain = (email or '').strip().rpartition('@')
    if not at or not local or not domain:
        return ''
    visible = 1 if len(local) <= 4 else 2
    return f'{local[:visible]}{EMAIL_MASK}@{domain}'
