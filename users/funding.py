"""Has this person ever put money into Confío?"""


def has_funded(user_or_id):
    """True once any money actually arrived: a confirmed incoming row (top-ups,
    sends and pay-ins all write one, but start PENDING; failed or unclaimed
    invitation sends don't count). Ever-funded, not "has a balance today"."""
    from users.models_unified import UnifiedTransactionTable

    user_id = getattr(user_or_id, 'pk', user_or_id)
    return UnifiedTransactionTable.objects.filter(
        counterparty_user_id=user_id, status='CONFIRMED', deleted_at__isnull=True,
    ).exclude(is_invitation=True, invitation_claimed=False).exists()
