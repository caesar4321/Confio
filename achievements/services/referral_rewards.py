"""
Business logic for syncing referral rewards with the Algorand vault.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional
from urllib.parse import quote

from django.db import transaction
from django.utils import timezone

from achievements.models import ReferralRewardEvent, UserReferral
from blockchain.rewards_service import ConfioRewardsService
from notifications.models import NotificationType as NotificationTypeChoices
from notifications.utils import create_notification
from users.models import Account

DEFAULT_EVENT_REWARD_CONFIG: Dict[str, Dict[str, Any]] = {
    # Event slug -> configuration:
    #   threshold: minimum fiat/token amount (Decimal, optional)
    #   referee_confio: CONFIO tokens to award the referred user (Decimal)
    #   referrer_confio: CONFIO tokens to award the referrer (Decimal)
    #   reward_cusd: cUSD notion used for vault accounting (Decimal, optional)
    "top_up": {
        "threshold": Decimal("20"),
        "referee_confio": Decimal("15"),
        "referrer_confio": Decimal("5"),
        "records_checkpoint": "conversion_usdc_to_cusd",
    },
    "conversion_usdc_to_cusd": {
        "threshold": Decimal("20"),
        "reward_cusd": Decimal("5"),
        "referrer_confio": Decimal("3"),
        "requires_checkpoint": "top_up",
    },
    "send": {
        "referee_confio": Decimal("8"),
        "referrer_confio": Decimal("2"),
        "notification_type": NotificationTypeChoices.REFERRAL_FIRST_TRANSACTION,
    },
    "payment": {
        "referee_confio": Decimal("10"),
        "referrer_confio": Decimal("3"),
    },
    "p2p_trade": {
        "referee_confio": Decimal("12"),
        "referrer_confio": Decimal("4"),
    },
}

MICRO_MULTIPLIER = Decimal("1000000")
logger = logging.getLogger(__name__)

TOP_UP_CHECKPOINT_KEY = "top_up_checkpoint"

EVENT_NOTIFICATION_TEMPLATES: Dict[str, Dict[str, Dict[str, str]]] = {
    "top_up": {
        "notification_type": NotificationTypeChoices.REFERRAL_EVENT_TOP_UP,
        "referee": {
            "title": "Recarga confirmada 🎉",
            "message": "Ya tienes saldo para explorar Confío. Haz tu primera conversión o envío para desbloquear tus CONFIO.",
        },
        "referrer": {
            "title": "Tu referido recargó su billetera",
            "message": "Ayúdale a convertir a cUSD para que ambos reciban los CONFIO del bono.",
        },
    },
    "conversion_usdc_to_cusd": {
        "notification_type": NotificationTypeChoices.REFERRAL_EVENT_CONVERSION,
        "referee": {
            "title": "Conversión lista ✅",
            "message": "Tu saldo ya está en cUSD. Comparte tu enlace e invita a otro amigo para seguir ganando CONFIO.",
        },
        "referrer": {
            "title": "Tu amigo convirtió a cUSD",
            "message": "Tus CONFIO de recompensa están listos. Invita a otro contacto y repite la fórmula.",
        },
    },
    "send": {
        "notification_type": NotificationTypeChoices.REFERRAL_EVENT_SEND,
        "referee": {
            "title": "Primer envío completado",
            "message": "Demostraste que puedes enviar dinero gratis. Invita a un amigo y gana CONFIO juntos.",
        },
        "referrer": {
            "title": "Tu referido ya envió su primer pago",
            "message": "Comparte tu enlace otra vez y sigue sumando recompensas.",
        },
    },
    "payment": {
        "notification_type": NotificationTypeChoices.REFERRAL_EVENT_PAYMENT,
        "referee": {
            "title": "Pagaste con Confío",
            "message": "Tu compra quedó registrada. Cuenta tu experiencia e invita a otro amigo.",
        },
        "referrer": {
            "title": "Tu referido pagó con Confío",
            "message": "Tus CONFIO están en camino. Comparte el enlace con otro contacto.",
        },
    },
    "p2p_trade": {
        "notification_type": NotificationTypeChoices.REFERRAL_EVENT_P2P_TRADE,
        "referee": {
            "title": "Primer trade P2P completado",
            "message": "Ya dominas el intercambio. Invita a otro amigo para desbloquear más CONFIO.",
        },
        "referrer": {
            "title": "Tu referido cerró su primer trade",
            "message": "Tus recompensas están reservadas. Sigue invitando para multiplicarlas.",
        },
    },
}


@dataclass
class EventContext:
    """Input payload describing the qualifying event."""

    event: str
    amount: Optional[Decimal] = None
    metadata: Optional[Dict[str, Any]] = None


def to_micro(amount: Decimal) -> int:
    """Convert a token amount (Decimal) into micro units."""
    return int((amount * MICRO_MULTIPLIER).to_integral_value())


def get_primary_algorand_address(user) -> Optional[str]:
    """Return the personal Algorand address for the given user."""
    account = (
        Account.objects.filter(
            user=user,
            account_type="personal",
            account_index=0,
            deleted_at__isnull=True,
        )
        .order_by("id")
        .first()
    )
    return account.algorand_address if account else None


def _get_referred_user_referral(user) -> Optional[UserReferral]:
    return (
        UserReferral.objects.filter(
            referred_user=user,
            deleted_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )


def _user_label(user) -> str:
    if not user:
        return "tu amigo"
    for attr in [user.first_name, user.username, user.email, getattr(user, 'phone_number', None)]:
        if attr:
            return attr
    return f"usuario {user.id}"


def _mark_top_up_checkpoint(referral: UserReferral, event: ReferralRewardEvent, event_ctx: EventContext) -> None:
    """Persist that the referred user completed the minimum top-up."""
    metadata = event.metadata or {}
    metadata.update(event_ctx.metadata or {})
    metadata["checkpoint"] = "top_up_recorded"
    event.metadata = metadata
    event.reward_status = "skipped"
    event.error = "Recarga registrada; esperando conversión a cUSD."
    event.save(update_fields=["metadata", "reward_status", "error", "updated_at"])

    referral_meta = referral.reward_metadata or {}
    referral_meta[TOP_UP_CHECKPOINT_KEY] = {
        "amount": str(event_ctx.amount or Decimal("0")),
        "recorded_at": timezone.now().isoformat(),
        "transaction_reference": (event_ctx.metadata or {}).get("transaction_hash"),
    }
    referral.reward_metadata = referral_meta
    referral.save(update_fields=["reward_metadata", "updated_at"])
    notify_referral_stage(referral, event_ctx)


def _has_top_up_checkpoint(referral: UserReferral) -> bool:
    """Return True if the referral has already met the top-up prerequisite."""
    checkpoint = (referral.reward_metadata or {}).get(TOP_UP_CHECKPOINT_KEY)
    return bool(checkpoint and checkpoint.get("recorded_at"))


def notify_referral_stage(referral: UserReferral, event_ctx: EventContext) -> None:
    """Send stage-specific notifications for both referee and referrer."""
    template = EVENT_NOTIFICATION_TEMPLATES.get(event_ctx.event)
    if not template:
        return

    referral_id = referral.id
    friend_name = _user_label(referral.referred_user)

    def _action_url(role: str) -> str:
        return (
            f"confio://referrals/event-detail?"
            f"event={quote(event_ctx.event)}&"
            f"referral_id={referral_id}&"
            f"role={role}"
        )

    referee_template = template.get("referee")
    if referral.referred_user and referee_template:
        create_notification(
            user=referral.referred_user,
            notification_type=template["notification_type"],
            title=referee_template["title"],
            message=referee_template["message"],
            data={
                "event": event_ctx.event,
                "referral_id": referral_id,
                "role": "referee",
                "friend_name": friend_name,
            },
            action_url=_action_url("referee"),
        )

    referrer_template = template.get("referrer")
    if referral.referrer_user and referrer_template:
        create_notification(
            user=referral.referrer_user,
            notification_type=template["notification_type"],
            title=referrer_template["title"],
            message=referrer_template["message"],
            data={
                "event": event_ctx.event,
                "referral_id": referral_id,
                "role": "referrer",
                "friend_name": friend_name,
            },
            action_url=_action_url("referrer"),
        )


def notify_referral_joined(referral: UserReferral) -> None:
    """Notify referrer and referee that the link is active."""
    referred_name = _user_label(referral.referred_user)
    if referral.referrer_user:
        create_notification(
            user=referral.referrer_user,
            notification_type=NotificationTypeChoices.REFERRAL_FRIEND_JOINED,
            title="Tu referido ya está en Confío",
            message=f"{referred_name} se registró con tu invitación. Ayúdale a completar su primera transacción para desbloquear las recompensas.",
            data={
                'referral_id': referral.id,
                'referred_user_id': referral.referred_user_id,
            },
            action_url=f"confio://referrals/friend-joined?referral_id={referral.id}&friend_name={quote(referred_name)}",
        )

    if referral.referred_user:
        create_notification(
            user=referral.referred_user,
            notification_type=NotificationTypeChoices.REFERRAL_ACTION_REMINDER,
            title="Activa tus recompensas de referido",
            message="Completa tu primera transacción para reclamar los CONFIO de bienvenida.",
            data={
                'referral_id': referral.id,
                'referrer_user_id': referral.referrer_user_id,
            },
            action_url=f"confio://referrals/action?step=pending&referral_id={referral.id}",
        )


def notify_reward_ready(referral: UserReferral, referee_confio: Decimal) -> None:
    """Let the referred user know their CONFIO can be claimed."""
    if not referral.referred_user or referee_confio <= Decimal("0"):
        return

    amount_str = f"{referee_confio:.2f}"
    friend_name = _user_label(referral.referrer_user) if referral.referrer_user else ""
    create_notification(
        user=referral.referred_user,
        notification_type=NotificationTypeChoices.REFERRAL_REWARD_READY,
        title="Tus $CONFIO están listos",
        message=f"Reclama {amount_str} $CONFIO del bono por referidos.",
        data={
            "referral_id": referral.id,
            "amount": amount_str,
            "friend_name": friend_name,
        },
        action_url="confio://referrals/reward-claim",
    )


def _locate_referral_for_user(user):
    referral = UserReferral.objects.filter(
        referred_user=user,
        deleted_at__isnull=True,
    ).order_by('-created_at').first()
    if referral:
        return referral, 'referee'

    referral = UserReferral.objects.filter(
        referrer_user=user,
        deleted_at__isnull=True,
    ).order_by('-created_at').first()
    if referral:
        return referral, 'referrer'

    return None, None


def sync_referral_reward_for_event(user, event_ctx: EventContext) -> Optional[UserReferral]:
    """
    Attempt to sync referral reward eligibility for a given user/event.

    Returns the updated referral when eligibility was triggered, otherwise None.
    """
    referral, actor_role = _locate_referral_for_user(user)

    config = DEFAULT_EVENT_REWARD_CONFIG.get(event_ctx.event)
    if not config:
        return None

    if referral and referral.reward_status == "eligible":
        return referral

    threshold: Optional[Decimal] = config.get("threshold")
    if threshold is not None:
        if event_ctx.amount is None or event_ctx.amount < threshold:
            return None

    referee_confio = config.get("referee_confio")
    referrer_confio = config.get("referrer_confio", Decimal("0"))
    reward_cusd = config.get("reward_cusd")

    event_defaults = {
        "actor_role": actor_role or "referee",
        "amount": event_ctx.amount or Decimal("0"),
        "transaction_reference": (event_ctx.metadata or {}).get("transaction_hash", ""),
        "occurred_at": timezone.now(),
        "metadata": event_ctx.metadata or {},
        "referral": referral,
    }

    event, created = ReferralRewardEvent.objects.get_or_create(
        user=user,
        trigger=event_ctx.event,
        defaults=event_defaults,
    )
    if not created:
        updated_fields = []
        if referral and event.referral_id != referral.id:
            event.referral = referral
            updated_fields.append("referral")
        if event.metadata != (event_ctx.metadata or {}):
            combined = event.metadata
            combined.update(event_ctx.metadata or {})
            event.metadata = combined
            updated_fields.append("metadata")
        if updated_fields:
            event.save(update_fields=updated_fields + ["updated_at"])

    if event.reward_status in {"eligible", "claimed"}:
        return referral if referral else None

    if referral is None:
        return None

    # Handle chained prerequisites (e.g., top_up -> conversion)
    if config.get("records_checkpoint") and referral:
        _mark_top_up_checkpoint(referral, event, event_ctx)
        return referral

    requires_checkpoint = config.get("requires_checkpoint")
    if requires_checkpoint == "top_up" and not _has_top_up_checkpoint(referral):
        event.reward_status = "skipped"
        event.error = "Necesitamos registrar una recarga mínima antes de esta conversión."
        event.save(update_fields=["reward_status", "error", "updated_at"])
        return referral

    service = ConfioRewardsService()

    if reward_cusd and (not referee_confio or referee_confio <= 0):
        try:
            referee_confio = service.convert_cusd_to_confio(reward_cusd)
        except Exception as exc:
            logger.warning(
                "Unable to convert reward_cusd to CONFIO (reward=%s): %s",
                reward_cusd,
                exc,
            )
            referee_confio = Decimal("0")

    if not reward_cusd:
        reward_cusd = referee_confio or Decimal("0")

    referee_confio = referee_confio or Decimal("0")

    reward_cusd_micro = to_micro(reward_cusd)
    referee_confio_micro = to_micro(referee_confio)
    referrer_confio_micro = to_micro(referrer_confio)

    referee_address = get_primary_algorand_address(referral.referred_user)
    if not referee_address:
        event.reward_status = "failed"
        event.error = "Usuario referido sin dirección Algorand."
        event.save(update_fields=["reward_status", "error", "updated_at"])
        return referral

    referrer_address: Optional[str] = None
    if referrer_confio > 0 and referral.referrer_user:
        referrer_address = get_primary_algorand_address(referral.referrer_user)
        if not referrer_address:
            referrer_confio = Decimal("0")
            referrer_confio_micro = 0

    try:
        result = service.mark_eligibility(
            user_address=referee_address,
            reward_cusd_micro=reward_cusd_micro,
            referee_confio_micro=referee_confio_micro,
            referrer_confio_micro=referrer_confio_micro,
            referrer_address=referrer_address,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "Error syncing referral reward: %s (user=%s, referral=%s, event=%s)",
            exc,
            getattr(user, "id", None),
            referral.id if referral else None,
            event_ctx.event,
            exc_info=True,
        )
        event.reward_status = "failed"
        event.error = str(exc)
        event.save(
            update_fields=[
                "reward_status",
                "error",
                "updated_at",
            ]
        )
        referral.reward_error = str(exc)
        referral.reward_last_attempt_at = timezone.now()
        referral.save(update_fields=["reward_error", "reward_last_attempt_at"])
        return referral

    with transaction.atomic():
        event.reward_status = "eligible"
        event.reward_tx_id = result.tx_id
        event.error = ""
        event.save(
            update_fields=[
                "reward_status",
                "reward_tx_id",
                "error",
                "updated_at",
            ]
        )

        referral.reward_status = "eligible"
        referral.reward_tx_id = result.tx_id
        referral.reward_box_name = result.box_name
        referral.reward_error = ""
        referral.reward_event = referral.reward_event or event_ctx.event
        referral.reward_referee_confio = referee_confio
        referral.reward_referrer_confio = referrer_confio
        referral.reward_metadata.update(event_ctx.metadata or {})
        referral.reward_submitted_at = timezone.now()
        referral.reward_last_attempt_at = referral.reward_submitted_at
        referral.save(
            update_fields=[
                "reward_status",
                "reward_tx_id",
                "reward_box_name",
                "reward_error",
                "reward_event",
                "reward_referee_confio",
                "reward_referrer_confio",
                "reward_metadata",
                "reward_submitted_at",
                "reward_last_attempt_at",
            ]
        )

    notify_referral_stage(referral, event_ctx)
    notify_reward_ready(referral, referee_confio)
    return referral
