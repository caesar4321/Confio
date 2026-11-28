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


# Why the person left the subscribe screen without opening the account: one
# tap on a sheet the app shows right after the screen closes. The server owns
# the question (smartAccountExitQuestion), so it can be reworded between app
# releases; apps/src/services/smartAccountExit.ts keeps the same list only as
# a fallback for a failed read. Each answer names one cause, never a second
# way to say "not now" (Julian, 2026-11-28). 'skipped' = closed without answering.
EXIT_TITLE = '¿Qué te hizo esperar?'
EXIT_OPTIONS = (
    ('money', 'Ahora no tengo ese dinero'),
    ('price', 'Me parece caro para lo que ofrece'),
    ('unclear', 'No entendí bien qué hace'),
    ('no_need', 'No necesito pagos ni inversiones automáticas'),
    ('move', 'No quiero mover mi dinero a otra cuenta'),
    # Only for someone the screen asks to verify first (exit_question).
    ('verify', 'Me falta verificarme'),
    ('other', 'Otra cosa'),
)
EXIT_REASONS = frozenset({key for key, _label in EXIT_OPTIONS} | {'skipped'})


def needs_verification(user) -> bool:
    """Verifying is this person's next step: not verified, and no document
    waiting on the reviewers. False on any doubt."""
    try:
        from assistant.suggestions import waits_on_review
        from security.identity_status import is_identity_verified
        return not is_identity_verified(user) and not waits_on_review(user)
    except Exception:  # noqa: BLE001
        logger.warning('smart account exit: identity unknown', exc_info=True)
        return False


def exit_question(user) -> dict:
    """The sheet's title and its answers in order ('other' last); the app shuffles the rest."""
    verify = needs_verification(user)
    return {'title': EXIT_TITLE,
            'options': [{'key': key, 'label': label} for key, label in EXIT_OPTIONS if key != 'verify' or verify]}
# Only an answer about a visit that just happened: the subscribe screen opened
# this recently and nothing was signed after it.
EXIT_WINDOW_HOURS = 2


def record_exit(user, reason: str, *, plan: str = '') -> bool:
    """Files one exit answer per person per day. False (nothing saved) for an
    unknown reason, no recent visit to the subscribe screen, or a signature
    after it. Never raises."""
    if user is None or not getattr(user, 'pk', None) or reason not in EXIT_REASONS:
        return False
    try:
        from datetime import timedelta

        from django.utils import timezone

        from security.geo import country_of
        from security.identity_status import is_identity_verified
        from users.funnel import emit_once
        from users.models_analytics import FunnelEvent

        now = timezone.now()
        visits = FunnelEvent.objects.filter(event_name=EVENT, user_id=user.pk)
        opened = (visits.filter(properties__stage='subscribe_opened',
                                created_at__gte=now - timedelta(hours=EXIT_WINDOW_HOURS))
                  .order_by('-created_at').values_list('created_at', flat=True).first())
        if opened is None or visits.filter(properties__stage__in=('subscribe_signed', 'subscribed'),
                                           created_at__gte=opened).exists():
            return False
        plan = plan if plan in ('annual', 'monthly') else ''
        emit_once(EVENT, user=user, country=country_of(user) or '', source_type='smart_account',
                  properties={'stage': 'exit_reason', 'reason': reason, 'plan': plan,
                              'verified': bool(is_identity_verified(user))},
                  dedupe_key=f'smart_account:exit:{user.pk}:{now:%Y-%m-%d}')
        return True
    except Exception:  # noqa: BLE001
        logger.warning('smart account exit answer failed', exc_info=True)
        return False
