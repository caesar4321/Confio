import logging

from celery import shared_task

from blockchain.algorand_client import get_algod_client

from .models import HumanitarianRelease
from .services import HumanitarianReleaseService


logger = logging.getLogger(__name__)


@shared_task(name='humanitarian.reconcile_submitted_releases')
def reconcile_submitted_releases():
    """Recover claimed releases by txid and identical signed bytes."""
    release_ids = list(
        HumanitarianRelease.objects.filter(status='submitted')
        .order_by('updated_at')
        .values_list('pk', flat=True)[:100]
    )
    if not release_ids:
        return 'No submitted humanitarian releases'

    # Recovery only reuses already signed bytes; it must not depend on KMS
    # availability or instantiate a signer.
    service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)
    service.algod = get_algod_client()
    outcomes = {}
    for release_id in release_ids:
        try:
            release = HumanitarianRelease.objects.get(pk=release_id)
            outcome = service.reconcile_submission(release)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        except Exception:
            logger.exception('Humanitarian release reconciliation failed release=%s', release_id)
            outcomes['error'] = outcomes.get('error', 0) + 1
    return ', '.join(f'{key}={value}' for key, value in sorted(outcomes.items()))
