"""Comprar background work: settle user actions, run the escrow keeper,
moderate listings."""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

ACTION_BY_KIND = {
    'market_deposit': 'deposit', 'market_ship': 'ship', 'market_confirm': 'confirm',
    'market_dispute': 'dispute', 'market_refund': 'refund', 'market_reclaim': 'reclaim',
}


@shared_task(name='marketplace.confirm_market_action', bind=True, max_retries=25)
def confirm_market_action(self, order_id: int, batch_id: int):
    """Settle one user action from its batch, then mirror the chain. Keyed by
    the ORDER pk (the batch's source_id), so cusd_plus.reconcile_signed_batches
    can re-enqueue it for a process that died before scheduling anything."""
    from blockchain.models import SponsoredBatch

    from . import escrow
    from .models import Order

    try:
        order = Order.objects.select_related('store').get(pk=order_id)
        batch = SponsoredBatch.objects.get(id=batch_id)
    except (Order.DoesNotExist, SponsoredBatch.DoesNotExist):
        return
    action = ACTION_BY_KIND.get(batch.kind)
    # Isolation: only THIS order's batch may settle it.
    if action is None or batch.source_id != order.pk:
        logger.error('[COMPRAR] batch %s does not match order %s — refusing to settle',
                     batch.id, order.pk)
        return

    if batch.status in ('signed', 'sent'):
        from cusd_plus.tasks import _retry_countdown
        raise self.retry(countdown=_retry_countdown(self.request.retries))

    if batch.status == 'confirmed':
        if action == 'deposit' and not order.deposit_tx_hash and batch.tx_hash:
            # The post-broadcast write may have been lost; the batch is durable.
            Order.objects.filter(pk=order.pk, deposit_tx_hash='').update(deposit_tx_hash=batch.tx_hash)
            order.deposit_tx_hash = batch.tx_hash
        try:
            escrow.sync_order(order)
        except Exception as exc:  # noqa: BLE001 — the chain read decides; retry it
            logger.warning('[COMPRAR] sync after %s failed for order %s: %s', action, order.pk, exc)
            from cusd_plus.tasks import _retry_countdown
            raise self.retry(countdown=_retry_countdown(self.request.retries))
        return

    # The batch failed or reverted: nothing changed on chain.
    logger.warning('[COMPRAR] order %s %s failed: batch %s %s', order.pk, action, batch.id, batch.status)
    escrow._release_action(order, action)


@shared_task(name='marketplace.run_escrow_keeper')
def run_escrow_keeper():
    """Periodic: release shipped orders past releaseAt, refund disputes the
    arbiter left past the timeout, re-mirror open orders, cancel stale drafts."""
    from django.conf import settings

    from . import escrow
    from .models import Order

    now = timezone.now()
    if not escrow.enabled():
        return {'skipped': 'disabled'}

    # Authorizations that expired: a spent one becomes a real order (sync),
    # an unspent one hands its stock back. Drafts, superseded (cancelled)
    # drafts and deposits that died mid-flight all land here.
    expired = Order.objects.select_related('store').filter(
        status__in=('draft', 'cancelled', 'depositing'), stock_reserved=True,
        deposit_deadline__lt=int(now.timestamp()) - escrow.DEADLINE_GRACE_S,
    ).order_by('updated_at', 'pk')[:100]
    reconciled = 0
    for order in expired:
        try:
            chain = escrow.read_chain_order(order.order_id32)
            if chain['state'] == 'none':
                escrow.release_unspent_reservation(order)
            else:
                escrow.sync_order(order, chain)
            reconciled += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning('[COMPRAR] reconcile failed for order %s: %s', order.pk, exc)

    released = refunded = synced = 0
    for order in Order.objects.select_related('store').filter(
            escrow._pending_free_q(), status='shipped', release_at__lte=now,
    ).order_by('release_at')[:50]:
        try:
            escrow.keeper_release(order)
            released += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning('[COMPRAR] keeper release failed for order %s: %s', order.pk, exc)

    timeout = timedelta(days=int(getattr(settings, 'MARKETPLACE_DISPUTE_TIMEOUT_DAYS', 30)))
    for order in Order.objects.select_related('store').filter(
            escrow._pending_free_q(), status='disputed', disputed_at__lte=now - timeout,
    ).order_by('disputed_at')[:50]:
        try:
            escrow.keeper_refund_expired_dispute(order)
            refunded += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning('[COMPRAR] expired-dispute refund failed for order %s: %s', order.pk, exc)

    # Re-mirror anything open or stuck mid-action (keeper txs, lost confirms),
    # and settled orders whose exact settlement time (hence fee row) is still
    # pending. Least recently synced first, so nothing starves.
    from django.db.models import Q
    stale = now - timedelta(minutes=2)
    for order in Order.objects.select_related('store').filter(
            Q(status__in=('depositing', 'funded', 'shipped', 'disputed'))
            | Q(status__in=('released', 'refunded'), settled_at__isnull=True),
            updated_at__lte=stale).order_by('updated_at', 'pk')[:200]:
        try:
            escrow.sync_order(order)
            synced += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning('[COMPRAR] sync failed for order %s: %s', order.pk, exc)
    return {'reconciled': reconciled, 'released': released, 'refunded': refunded, 'synced': synced}


@shared_task(name='marketplace.review_product', bind=True, max_retries=5)
def review_product(self, product_id: int, claim: str):
    from .moderation import ReviewUnavailable, run_product_review

    try:
        run_product_review(product_id, claim)
    except ReviewUnavailable as exc:
        logger.warning('[COMPRAR] product %s review unavailable: %s', product_id, exc)
        raise self.retry(countdown=60 * (2 ** self.request.retries))


@shared_task(name='marketplace.review_rating', bind=True, max_retries=5)
def review_rating(self, rating_id: int):
    from .moderation import ReviewUnavailable, run_rating_review

    try:
        run_rating_review(rating_id)
    except ReviewUnavailable as exc:
        logger.warning('[COMPRAR] review %s moderation unavailable: %s', rating_id, exc)
        raise self.retry(countdown=60 * (2 ** self.request.retries))


# A moderation task that exhausted its retries (a long reviewer outage) would
# leave its item pending for good: a listing stuck "En revisión", a review
# never published. A periodic task of its own (never the money keeper, which a
# slow broker must not hold up) hands them back. The interval outlasts a
# task's whole retry chain (~31 min), and each hand-back expires at the next
# one, so a backlog cannot stack copies of the same review.
STUCK_REVIEW_AFTER_MIN = 60


def enqueue_rating_review(rating_id: int) -> None:
    """Queue a review's moderation; a broker hiccup is logged, never raised
    (the rating is saved; the stuck-review sweep picks it up)."""
    try:
        review_rating.apply_async((rating_id,), expires=STUCK_REVIEW_AFTER_MIN * 60)
    except Exception as exc:  # noqa: BLE001
        logger.warning('[COMPRAR] could not queue review %s: %s', rating_id, exc)


@shared_task(name='marketplace.requeue_stuck_reviews')
def requeue_stuck_reviews_task():
    return requeue_stuck_reviews()


def requeue_stuck_reviews(now=None) -> dict:
    from datetime import timedelta

    from .models import OrderRating, Product

    now = now or timezone.now()
    cutoff = now - timedelta(minutes=STUCK_REVIEW_AFTER_MIN)
    # Each hand-back is stamped, so a long outage re-queues an item every
    # STUCK_REVIEW_AFTER_MIN, not on every keeper run.
    products = list(Product.objects.filter(status='pending_review', deleted_at__isnull=True,
                                           updated_at__lt=cutoff).exclude(review_claim='')
                    .values_list('pk', 'review_claim')[:50])
    for pk, claim in products:
        if Product.objects.filter(pk=pk, review_claim=claim, status='pending_review',
                                  updated_at__lt=cutoff).update(updated_at=now):
            review_product.apply_async((pk, claim), expires=STUCK_REVIEW_AFTER_MIN * 60)
    ratings = list(OrderRating.objects.filter(comment_status='pending', comment_queued_at__lt=cutoff)
                   .values_list('pk', flat=True)[:50])
    for pk in ratings:
        if OrderRating.objects.filter(pk=pk, comment_status='pending', comment_queued_at__lt=cutoff) \
                .update(comment_queued_at=now):
            enqueue_rating_review(pk)
    return {'products': len(products), 'ratings': len(ratings)}
