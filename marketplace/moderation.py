"""Listing moderation for Comprar: the community reviewer (Luna → Sol) with
a marketplace policy. Fail closed: a listing the AI cannot judge stays
pending_review and is never shown; an outage is never an approval.

Each photo is reviewed with the listing text (the reviewer takes one image per
call). Approved photos are re-encoded (EXIF/GPS stripped) and published to the
publications bucket; the pending uploads stay private.
"""

import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inbox.community import ReviewUnavailable  # noqa: F401 — re-exported for tasks

logger = logging.getLogger(__name__)

MAX_PHOTOS = 4
PENDING_PREFIX = 'marketplace/pending/'

PRODUCT_POLICY = """You are the listing reviewer for "Comprar", a marketplace inside Confío, a digital-dollar wallet used by everyday people in Latin America. Sellers are identity-verified small producers (artisans, family businesses) selling PHYSICAL goods for home delivery. Buyers are ordinary people, many new to digital money.

ALLOW: physical products such as handicrafts, textiles and clothing, accessories, jewelry, home goods, toys, cosmetics, and PACKAGED shelf-stable food. Honest descriptions, prices, sizes, materials, photos of the product.

REJECT:
- Anything not a physical product: services, digital goods, gift cards, tickets, accounts, crypto or investment offers, loans, "work from home" schemes.
- Prohibited goods: weapons or parts, ammunition, drugs or medicines (including supplements with medical claims), alcohol, tobacco/vapes, live animals, counterfeit or replica brands, stolen goods, adult/sexual items, hazardous chemicals, perishable or home-cooked food needing refrigeration.
- Contact details or off-platform payment requests in text or image (phone numbers, WhatsApp, social handles, bank accounts, QR codes, "pay me directly") — buyers must pay through Confío's protected checkout.
- Scams, misleading claims, impersonation of brands or people, personal data of others, hate, sexual content, violence.
- Photos that do not show the product being sold."""


def pending_prefix(user) -> str:
    return f'{PENDING_PREFIX}{user.id}/'


def _decide(body: str, image) -> dict:
    from inbox.community import (ESCALATION_INSTRUCTIONS, FIRST_PASS_INSTRUCTIONS,
                                 _call_reviewer, _needs_escalation)

    first = _call_reviewer(
        model=settings.COMMUNITY_REVIEW_MODEL, effort=settings.COMMUNITY_REVIEW_REASONING_EFFORT,
        instructions=FIRST_PASS_INSTRUCTIONS, decisions=['approve', 'reject', 'escalate'],
        body=body, image=image, policy=PRODUCT_POLICY)
    if not _needs_escalation(first):
        return first
    return _call_reviewer(
        model=settings.COMMUNITY_ESCALATION_MODEL, effort=settings.COMMUNITY_ESCALATION_REASONING_EFFORT,
        instructions=ESCALATION_INSTRUCTIONS, decisions=['approve', 'reject'],
        body=body, image=image, policy=PRODUCT_POLICY)


def _listing_text(product) -> str:
    return (f'Title: {product.title}\nCategory: {product.get_category_display()}\n'
            f'Price: {product.price_local} {product.currency_code}\n'
            f'Description: {product.description}')


def start_review(product, *, update_fields=None) -> str:
    """Save the product as pending with a NEW review claim in the same write
    as its content, then queue the review. A reviewer (or a pause/unpause)
    holding an older claim can never act on this revision. Returns the claim.
    `update_fields` limits the write (content fields are added by the caller)."""
    from .tasks import review_product

    claim = uuid.uuid4().hex
    product.status = 'pending_review'
    product.review_claim = claim
    product.review_verdict = None
    product.rejection_reason = ''
    review_fields = ['status', 'review_claim', 'review_verdict', 'rejection_reason', 'updated_at']
    if update_fields is None:
        product.save()
    else:
        product.save(update_fields=[*update_fields, *review_fields])
    transaction.on_commit(lambda: review_product.delay(product.pk, claim))
    return claim


def run_product_review(product_id: int, claim: str) -> str:
    from inbox import public_objects
    from inbox.community import load_pending_image, publish_image
    from security.s3_utils import build_s3_key

    from .models import Product

    product = Product.objects.select_related('store').filter(pk=product_id).first()
    if product is None or product.review_claim != claim or product.status != 'pending_review':
        return 'stale'
    text = _listing_text(product)
    keys = list(product.pending_photo_keys or [])[:MAX_PHOTOS]

    verdicts = []
    images = []
    if not keys:
        verdicts.append(_decide(text, None))
    for key in keys:
        try:
            image = load_pending_image(key, bucket=settings.AWS_COMMUNITY_UPLOAD_BUCKET)
        except ValueError as exc:
            verdicts.append({'decision': 'reject', 'category': 'other', 'confidence': 1.0,
                             'reason': 'Una de las fotos no se pudo leer. Sube JPG, PNG o WEBP.',
                             'model': f'image-check: {exc}'[:120]})
            break
        verdict = _decide(text, image)
        verdicts.append(verdict)
        if verdict['decision'] != 'approve':
            break
        images.append(image)

    rejected = next((v for v in verdicts if v['decision'] != 'approve'), None)
    if rejected:
        if Product.objects.filter(pk=product.pk, review_claim=claim, status='pending_review').update(
                status='rejected', review_verdict=verdicts, reviewed_at=timezone.now(),
                rejection_reason=(rejected.get('reason') or '')[:300]):
            return 'rejected'
        return 'stale'

    urls = []
    for image in images:
        key = build_s3_key(f"marketplace/{timezone.now():%Y/%m}", 'product.jpg')
        public_objects.reserve(settings.AWS_PUBLICATIONS_BUCKET, key)
        publish_image(image, key)
        public_objects.mark_live(settings.AWS_PUBLICATIONS_BUCKET, key)
        from security.s3_utils import public_s3_url
        urls.append(public_s3_url(key, bucket=settings.AWS_PUBLICATIONS_BUCKET))
    if Product.objects.filter(pk=product.pk, review_claim=claim, status='pending_review').update(
            status='active', review_verdict=verdicts, reviewed_at=timezone.now(),
            photo_urls=urls or product.photo_urls, pending_photo_keys=[]):
        return 'approved'
    return 'stale'
