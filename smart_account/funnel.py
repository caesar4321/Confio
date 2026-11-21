"""Server-side stages of the paid funnel (event `smart_account_funnel`,
spec 7.9): written from reconciled chain events, once per user and stage.
Analytics never fail the caller."""
import logging

logger = logging.getLogger(__name__)
EVENT = 'smart_account_funnel'
SERVER_STAGES = ('subscribed', 'first_deposit', 'rule_created', 'beneficiary_set', 'cancelled')


def record(user, stage: str, *, plan: str = '', key: str = '') -> None:
    if user is None or stage not in SERVER_STAGES:
        return
    try:
        from security.geo import country_of
        from users.funnel import emit_once
        emit_once(EVENT, user=user, country=country_of(user) or '', source_type='smart_account',
                  properties={'stage': stage, 'plan': plan or ''},
                  dedupe_key=f'smart_account:{stage}:{user.pk}:{key}')
    except Exception:  # noqa: BLE001
        logger.warning('smart account funnel event failed', exc_info=True)
