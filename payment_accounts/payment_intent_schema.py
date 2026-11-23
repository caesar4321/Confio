"""JWT-scoped API of prepared payments (payment_intents.py).

Its own fields and operations on purpose: the app asks for them in their own
documents, so an older server fails only the payment card, never the thread
or the Pagar screen. The account comes from the JWT; no account id is taken.
"""
import graphene

from . import payment_intents
from .services import PaymentAccountError


def _owner(info):
    from .schema import _active_account
    return _active_account(info, permission='send_funds', owner_only=True)


def _error(exc):
    from .schema import _public_error
    return _public_error(exc)


def _code(exc):
    # 'error': a failure that is not about this payment (provider or network down).
    return getattr(exc, 'code', '') or 'error'


def _iso(value):
    return value.isoformat() if value else None


class PaymentIntentType(graphene.ObjectType):
    """Everything the card and the signing sheet show. Rendered from the
    server's row only: never from the assistant's text."""
    id = graphene.UUID(required=True)
    # quoted | awaiting_signature | paying | paid | refunding | refunded |
    # failed | under_review | expired | cancelled
    status = graphene.String(required=True)
    status_reason = graphene.String(required=True)
    created_by = graphene.String(required=True)
    source = graphene.String(required=True)
    method_id = graphene.String(required=True)
    # local_charge | local_transfer | ramp_order | confio_send. The provider
    # that carries it is the server's business and is not exposed.
    family = graphene.String(required=True)
    destination_id = graphene.UUID()  # Infinia rails only
    payee_name = graphene.String(required=True)
    # holder_verified | confio_account | provider_named | institution_charge |
    # institution_amount | signed_charge | signed_amount | saved_payee |
    # self_reported | unverified
    payee_level = graphene.String(required=True)
    # The identifier being paid (a key, a masked account, phone and document).
    payee_account = graphene.String(required=True)
    payee_document = graphene.String(required=True)
    institution = graphene.String(required=True)
    # amount_exact: the payee receives exactly amount_local. Otherwise the
    # dollars are fixed, amount_local is what should arrive, and minimum_local
    # (when the rail can promise one) the least that is authorized.
    amount_exact = graphene.Boolean(required=True)
    amount_local = graphene.String(required=True)
    minimum_local = graphene.String()
    currency = graphene.String(required=True)
    total_usd = graphene.String(required=True)
    fee_usd = graphene.String(required=True)
    estimated_return_usd = graphene.String(required=True)
    rate = graphene.String(required=True)
    charge_expires_at = graphene.String()
    expires_at = graphene.String(required=True)
    display_hash = graphene.String(required=True)
    journey_id = graphene.UUID()
    # The provider order (ramp_order) or the send (confio_send) once it exists.
    order_id = graphene.String()
    message_id = graphene.ID()
    created_at = graphene.String(required=True)


def intent_type(intent):
    if intent is None:
        return None
    status, row = payment_intents.status(intent)
    journey = row if intent.family in ('local_charge', 'local_transfer') else None
    shown = payment_intents.display_fields(intent)
    return PaymentIntentType(
        id=intent.internal_id, status=status, status_reason=intent.state_reason, created_by=intent.created_by,
        source=intent.source, method_id=intent.rail_method_id, family=intent.family,
        destination_id=intent.destination.internal_id if intent.destination_id else None,
        payee_name=shown['payee_name'], payee_level=shown['payee_level'], payee_account=shown['payee_account'],
        payee_document=shown['payee_document'], institution=shown['institution'],
        amount_exact=intent.amount_exact, amount_local=shown['amount_local'],
        minimum_local=shown['minimum_local'] or None, currency=shown['currency'], order_id=intent.order_ref or None,
        total_usd=shown['total_usd'], fee_usd=shown['fee_usd'],
        estimated_return_usd=shown['estimated_return_usd'], rate=shown['rate'],
        charge_expires_at=_iso(intent.charge_expires_at), expires_at=_iso(intent.expires_at),
        display_hash=intent.display_hash, journey_id=journey.internal_id if journey else None,
        message_id=intent.message_id, created_at=_iso(intent.created_at))


class PaymentIntentQuery(graphene.ObjectType):
    payment_intent = graphene.Field(PaymentIntentType, id=graphene.UUID(required=True))
    assistant_payment_intent = graphene.Field(
        PaymentIntentType, message_id=graphene.ID(required=True),
        description="The prepared payment shown on one of the viewer's own assistant messages "
                    '(the latest one after a re-quote).')

    def resolve_payment_intent(self, info, id):
        try:
            return intent_type(payment_intents.get(_owner(info), id))
        except PaymentAccountError:
            return None

    def resolve_assistant_payment_intent(self, info, message_id):
        try:
            return intent_type(payment_intents.for_message(_owner(info), message_id))
        except PaymentAccountError:
            return None


class PaymentRequestInput(graphene.InputObjectType):
    """What the person gave for a payment that is not just a code. Never an
    account id, a payee name to show or a price: those are the rail's answer."""
    # br_pix | br_qr | ar_qr | ar_cvu | co_breb | co_qr | mx_clabe |
    # ve_pagomovil_send | bo_qr | confio_send. Optional for a code that
    # declares its own rail (Pix, QR Argentina, QR Bre-B).
    method_id = graphene.String()
    # A key, an account number (CLABE, CVU/CBU), or a QR's text.
    value = graphene.String()
    amount_usd = graphene.String()    # dollars to send (transfers, Pago Móvil, Confío)
    # An exact local amount the recipient receives: bolivianos for a QR Bolivia
    # without an amount; for a key/account/open QR (Infinia) or Pago Móvil, the
    # pesos/reais/bolívares paid exactly (priced in dollars by the server).
    # Never together with amount_usd (refused).
    amount_local = graphene.String()
    phone = graphene.String()         # Pago Móvil
    cedula = graphene.String()
    bank_code = graphene.String()
    holder_name = graphene.String()
    recipient = graphene.String()     # confio_send: the @usuario


SOURCES = {'pasted_code': 'paste', 'shared_qr': 'share', 'scanned_qr': 'scan', 'form': 'scan',
           'saved_payee': 'scan'}


class PreparePaymentIntent(graphene.Mutation):
    """A payment the person started outside a chat message: a code they
    scanned, shared or pasted, or details they typed. Moves no money. With
    in_chat, the card is also added to the assistant thread as a system line."""

    class Arguments:
        code = graphene.String()
        source = graphene.String(required=True)
        in_chat = graphene.Boolean(default_value=False)
        request = PaymentRequestInput()

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    error_code = graphene.String()
    intent = graphene.Field(PaymentIntentType)

    @classmethod
    def mutate(cls, root, info, code=None, source='', in_chat=False, request=None):
        try:
            owner = _owner(info)
            if source not in SOURCES:
                raise PaymentAccountError('Invalid source')
            details = {key: value for key, value in dict(request or {}).items() if value not in (None, '')}
            details['meta'] = getattr(info.context, 'META', None) or {}
            if code is None and not details.get('value') and not details.get('method_id'):
                raise PaymentAccountError('A payment code or request is required')
            intent = payment_intents.prepare(
                owner, info.context.user, code, created_by=SOURCES[source], source=source, request=details)
            if in_chat:
                # The card exists either way: a thread that cannot take the
                # line now must not turn a prepared payment into an error.
                try:
                    from assistant.service import post_system_note
                    from assistant.engine import PAYMENT_CHIP
                    # The chip is what a reloaded thread shows the app: this
                    # line carries a card (the same marker as an assistant reply).
                    message, _ = post_system_note(
                        info.context.user, 'Preparé este pago. Revísalo antes de pagar.',
                        f'payment_intent:{intent.internal_id}', actions=[dict(PAYMENT_CHIP)],
                        payment_intent={'id': str(intent.internal_id)})
                    if message is not None:
                        payment_intents.attach_message(intent.internal_id, message.pk)
                        intent.message_id = message.pk
                except Exception:  # noqa: BLE001
                    import logging
                    logging.getLogger(__name__).exception('payment intent line not added to the thread')
            return cls(success=True, errors=[], intent=intent_type(intent))
        except Exception as exc:
            return cls(success=False, errors=[_error(exc)], error_code=_code(exc))


class ConfirmPaymentIntent(graphene.Mutation):
    """The person opened the signing sheet for the figures with this
    display_hash. Nothing moves here: it hands back what the owner signs
    next, through the rail's existing flow, by sign_kind:

      journey_bridge  transfer + request_id + account ids + minimum_fx_output
                      → Confío Face, createInfiniaJourney, sign the batch
      ramp_order      order_id → the rail's own start-funding mutation, then
                      the sponsored batch (Pago Móvil, QR Bolivia)
      bsc_send        send (calls, intent id) → submitBscSend"""

    class Arguments:
        id = graphene.UUID(required=True)
        display_hash = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    error_code = graphene.String()
    intent = graphene.Field(PaymentIntentType)
    sign_kind = graphene.String()
    transfer = graphene.Field('payment_accounts.schema.PaymentBridgeTransferType')
    request_id = graphene.UUID()
    local_account_id = graphene.UUID()
    crypto_account_id = graphene.UUID()
    minimum_fx_output = graphene.String()
    order_id = graphene.String()
    send = graphene.Field('send.schema.PrepareBscSend')
    # Set when the rail wants a step first (e.g. Confío Face): the same value
    # the rail's own mutation returns.
    next_step = graphene.String()

    @classmethod
    def mutate(cls, root, info, id, display_hash):
        try:
            owner = _owner(info)  # the minors gate is inside confirm (_require_owner)
            intent, signing = payment_intents.confirm_any(owner, info.context.user, id, display_hash, info)
            out = cls(success=True, errors=[], intent=intent_type(intent), sign_kind=signing['kind'])
            if signing['kind'] == 'journey_bridge':
                out.transfer, out.request_id = signing['transfer'], intent.request_id
                out.local_account_id = signing['local'].internal_id
                out.crypto_account_id = signing['crypto'].internal_id
                out.minimum_fx_output = format(signing['minimum_fx_output'], 'f')
            elif signing['kind'] == 'ramp_order':
                out.order_id = signing['order_id']
            else:
                out.order_id, out.send = signing['send_id'], signing.get('send')
            return out
        except Exception as exc:
            # The card as it stands now (still valid, or over): the app never
            # has to guess which from the error alone.
            current = None
            try:
                current = intent_type(payment_intents.get(_owner(info), id))
            except Exception:  # noqa: BLE001 - the refusal itself is the answer
                pass
            return cls(success=False, errors=[_error(exc)], error_code=_code(exc), intent=current,
                       next_step=getattr(exc, 'next_step', None) or None)


class RequotePaymentIntent(graphene.Mutation):
    """New figures for the same code: a new intent on the same message."""

    class Arguments:
        id = graphene.UUID(required=True)

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    error_code = graphene.String()
    intent = graphene.Field(PaymentIntentType)

    @classmethod
    def mutate(cls, root, info, id):
        try:
            intent = payment_intents.requote(_owner(info), info.context.user, id,
                                             meta=getattr(info.context, 'META', None) or {})
            return cls(success=True, errors=[], intent=intent_type(intent))
        except Exception as exc:
            return cls(success=False, errors=[_error(exc)], error_code=_code(exc))


class CancelPaymentIntent(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    error_code = graphene.String()
    intent = graphene.Field(PaymentIntentType)

    @classmethod
    def mutate(cls, root, info, id):
        try:
            return cls(success=True, errors=[], intent=intent_type(payment_intents.cancel(_owner(info), id)))
        except Exception as exc:
            return cls(success=False, errors=[_error(exc)], error_code=_code(exc))


class TrackPaymentIntent(graphene.Mutation):
    """Funnel steps only the app sees: card_shown, sheet_opened."""

    class Arguments:
        id = graphene.UUID(required=True)
        event = graphene.String(required=True)

    success = graphene.Boolean(required=True)

    @classmethod
    def mutate(cls, root, info, id, event):
        try:
            payment_intents.track_client(_owner(info), id, event)
            return cls(success=True)
        except Exception:  # noqa: BLE001 - analytics never surface an error
            return cls(success=False)


class PaymentIntentMutation(graphene.ObjectType):
    prepare_payment_intent = PreparePaymentIntent.Field()
    confirm_payment_intent = ConfirmPaymentIntent.Field()
    requote_payment_intent = RequotePaymentIntent.Field()
    cancel_payment_intent = CancelPaymentIntent.Field()
    track_payment_intent = TrackPaymentIntent.Field()
