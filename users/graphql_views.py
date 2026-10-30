import graphene
from graphene_django import DjangoObjectType
from .models_unified import UnifiedTransactionTable
from decimal import Decimal, InvalidOperation
from datetime import timedelta


def _positive_difference(gross, net):
    """Return an exact positive gross-net delta, or an empty string."""
    try:
        value = Decimal(str(gross)) - Decimal(str(net))
    except (InvalidOperation, TypeError, ValueError):
        return ''
    return format(value.normalize(), 'f') if value > 0 else ''


def _ramp_conversion_fee(ramp):
    """The Confío perimeter fee represented by a ramp ledger row.

    One conversion can settle several ramp deposits.  Attribution writes each
    ramp's gross/net allocation into metadata, so prefer that over assigning
    the conversion's entire fee to every ramp.  Older one-ramp rows fall back
    to the linked conversion's exact fee.
    """
    if getattr(ramp, 'status', None) != 'COMPLETED':
        return ''
    metadata = getattr(ramp, 'metadata', None) or {}
    allocation = metadata.get('conversion_allocation') or {}
    allocated = _positive_difference(
        allocation.get('gross_amount'), allocation.get('net_amount'))
    if allocated:
        return allocated

    conversion = getattr(ramp, 'conversion', None)
    if conversion is not None:
        fee = (
            getattr(conversion, 'fee_amount_exact', None)
            or getattr(conversion, 'fee_amount', None)
        )
        try:
            fee_decimal = Decimal(str(fee))
        except (InvalidOperation, TypeError, ValueError):
            fee_decimal = Decimal(0)
        if fee_decimal > 0:
            return format(fee_decimal.normalize(), 'f')

    # Guardarian persisted this before conversions gained exact fee columns.
    legacy_fee = metadata.get('confio_fee')
    if isinstance(legacy_fee, dict):
        legacy_fee = legacy_fee.get('fee_amount')
    try:
        legacy_decimal = Decimal(str(legacy_fee))
    except (InvalidOperation, TypeError, ValueError):
        return ''
    return format(legacy_decimal.normalize(), 'f') if legacy_decimal > 0 else ''


def _external_deposit_conversion(row):
    """Find the completed auto-conversion behind a raw external-USDT receipt.

    The chain scanner records the incoming transfer before the foreground app
    can mint cUSD/cUSD+.  Those hashes cannot be the same, so historical rows
    have no FK between the receipt and conversion.  Match only the narrow,
    unambiguous economic identity: same owner, exact gross, external-deposit
    source, completed entry conversion, near the observed receipt, and not a
    ramp conversion.  Never guess when more than one conversion matches. The
    contract rate can change, so two identical deposits need not have the same
    fee snapshot.
    """
    cached_marker = '_external_deposit_conversion_cache'
    if hasattr(row, cached_marker):
        return getattr(row, cached_marker)
    if getattr(row, 'transaction_type', None) != 'send':
        return None
    receipt = getattr(row, 'send_transaction', None)
    if (
        receipt is None
        or getattr(receipt, 'sender_type', None) != 'external'
        or str(getattr(receipt, 'token_type', '')).upper() != 'USDT'
    ):
        return None

    from conversion.models import Conversion

    query = Conversion.objects.filter(
        source='external_deposit',
        conversion_type__in=('to_savings', 'usdt_to_cusd'),
        status='COMPLETED',
        from_amount=receipt.amount,
        # The app can mint before the asynchronous chain scanner persists the
        # receipt, so DB creation order is not guaranteed even though chain
        # order is. Keep the lag window bounded to avoid matching an unrelated
        # historical conversion with the same round amount.
        created_at__gte=receipt.created_at - timedelta(hours=6),
        created_at__lte=receipt.created_at + timedelta(days=14),
        is_deleted=False,
        ramp_transactions__isnull=True,
        local_transfer_journey__isnull=True,
    )
    if receipt.recipient_business_id:
        query = query.filter(actor_business_id=receipt.recipient_business_id)
    elif receipt.recipient_user_id:
        query = query.filter(actor_user_id=receipt.recipient_user_id)
    else:
        return None
    candidates = list(query.order_by('created_at')[:2])
    conversion = candidates[0] if len(candidates) == 1 else None
    setattr(row, cached_marker, conversion)
    return conversion


def _preload_external_deposit_conversions(rows):
    """Resolve list-page external deposits with one bounded conversion query."""
    candidates_by_row = []
    owner_filter = None
    amounts = set()
    earliest = None
    latest = None

    for row in rows:
        if getattr(row, 'transaction_type', None) != 'send':
            continue
        receipt = getattr(row, 'send_transaction', None)
        if (
            receipt is None
            or getattr(receipt, 'sender_type', None) != 'external'
            or str(getattr(receipt, 'token_type', '')).upper() != 'USDT'
        ):
            continue
        business_id = getattr(receipt, 'recipient_business_id', None)
        user_id = getattr(receipt, 'recipient_user_id', None)
        if business_id:
            owner = ('business', business_id)
            clause = Q(actor_business_id=business_id)
        elif user_id:
            owner = ('user', user_id)
            clause = Q(actor_user_id=user_id)
        else:
            setattr(row, '_external_deposit_conversion_cache', None)
            continue
        owner_filter = clause if owner_filter is None else owner_filter | clause
        created_at = receipt.created_at
        candidates_by_row.append((row, receipt, owner))
        amounts.add(receipt.amount)
        earliest = created_at if earliest is None else min(earliest, created_at)
        latest = created_at if latest is None else max(latest, created_at)

    if not candidates_by_row or owner_filter is None:
        return

    from conversion.models import Conversion

    conversions = list(Conversion.objects.filter(
        source='external_deposit',
        conversion_type__in=('to_savings', 'usdt_to_cusd'),
        status='COMPLETED',
        from_amount__in=amounts,
        created_at__gte=earliest - timedelta(hours=6),
        created_at__lte=latest + timedelta(days=14),
        is_deleted=False,
        ramp_transactions__isnull=True,
        local_transfer_journey__isnull=True,
    ).filter(owner_filter).order_by('created_at'))

    for row, receipt, owner in candidates_by_row:
        matches = [
            conversion for conversion in conversions
            if conversion.from_amount == receipt.amount
            and receipt.created_at - timedelta(hours=6)
                <= conversion.created_at
                <= receipt.created_at + timedelta(days=14)
            and (
                ('business', conversion.actor_business_id) == owner
                if owner[0] == 'business'
                else ('user', conversion.actor_user_id) == owner
            )
        ]
        setattr(
            row, '_external_deposit_conversion_cache',
            matches[0] if len(matches) == 1 else None,
        )


def _visible_unified():
    """Ledger rows the app may show.

    `deleted_at` has always existed on the model but NO reader honored it, so
    31 rows soft-deleted on purpose (30 FAILED legacy USDC conversions, plus a
    cUSD+ conversion created for a geo-ineligible holder that could never
    complete) kept rendering as live movements. Every read resolver goes
    through here; writers keep using the plain manager so the sync path still
    sees deleted rows and cannot duplicate them.
    """
    from django.db.models import Exists, OuterRef
    from payment_accounts.models import PaymentBridgeTransfer
    owned_exit = PaymentBridgeTransfer.objects.filter(
        infinia_journey__direction='to_bank',
        source_tx_hash__iexact=OuterRef('conversion__to_transaction_hash'),
        quote__source_address__iexact=OuterRef('conversion__user_bsc_address'),
    ).exclude(source_tx_hash='')
    return UnifiedTransactionTable.objects.filter(deleted_at__isnull=True).exclude(
        conversion__local_transfer_journey__isnull=False
    ).annotate(_local_exit=Exists(owned_exit)).filter(_local_exit=False)
from django.db.models import Q


def _positive_fee_bps(value):
    """Return a stored positive basis-point snapshot, never today's rate."""
    try:
        bps = int(value)
    except (TypeError, ValueError):
        return None
    return bps if bps > 0 else None


def _send_fee_bps(send):
    try:
        import json
        metadata = json.loads(getattr(send, 'bsc_calls_json', '') or '{}')
        receipt = metadata.get('receipt') if isinstance(metadata, dict) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return _positive_fee_bps(
        receipt.get('fee_bps') if isinstance(receipt, dict) else None)


def _person_badge(row, info, user_id, business_id) -> tuple:
    """A person's public badges on a history row: never for a business, and
    never behind a Propina's pseudonym."""
    from users.status_badges import badge_of
    if not user_id or business_id or _is_tip_row(row):
        return None, None
    return badge_of(info, user_id)


def _preload_badges(rows, info):
    """One query for a whole history page (users/status_badges.py)."""
    from users.status_badges import preload_badges
    ids = set()
    for row in rows:
        if not _is_tip_row(row):
            if not row.sender_business_id:
                ids.add(row.sender_user_id)
            if not row.counterparty_business_id:
                ids.add(row.counterparty_user_id)
    preload_badges(info, ids)


def _is_tip_row(row) -> bool:
    """A Propina row of the unified ledger (a send keyed tip-…)."""
    from send.schema import is_tip_send
    return (getattr(row, 'transaction_type', '') == 'send' and bool(getattr(row, 'send_transaction_id', None))
            and is_tip_send(row.send_transaction))


class UnifiedTransactionType(DjangoObjectType):
    """GraphQL type for unified transaction view"""
    
    # Computed fields for the current user's perspective
    direction = graphene.String(description="Transaction direction from current user perspective")
    display_amount = graphene.String(description="Formatted amount with +/- based on direction")
    # The fee the recipient did NOT receive. Blank when there is none. The
    # Released clients derived this from a hardcoded 0.9%, which becomes wrong
    # when the rate changes or a flow prices differently. New clients read
    # this snapshot and net_amount below instead.
    fee_amount = graphene.String(description="Fee deducted before the recipient was credited ('' if none)")
    fee_bps = graphene.Int(description="Stored fee-rate snapshot in basis points (null if no fee or unavailable)")
    net_amount = graphene.String(description="What the recipient actually received (amount - fee)")
    display_counterparty = graphene.String(description="Name of the counterparty from user perspective")
    display_description = graphene.String(description="Transaction description")
    
    # Override nullable fields
    error_message = graphene.String(description="Error message if transaction failed")
    sender_phone = graphene.String(description="Sender phone number")
    counterparty_phone = graphene.String(description="Counterparty phone number")
    # Public badges of the people on the row (users/status_badges.py).
    sender_status_tier = graphene.String()
    sender_is_referral_verified = graphene.Boolean()
    counterparty_status_tier = graphene.String()
    counterparty_is_referral_verified = graphene.Boolean()
    description = graphene.String(description="Transaction description")
    invoice_id = graphene.String(description="Invoice ID for payments")
    payment_transaction_id = graphene.String(description="Payment transaction ID")
    transaction_hash = graphene.String(description="Transaction hash on blockchain")
    internal_id = graphene.String(description="Standardized Internal ID (UUID)")
    idempotency_key = graphene.String(description="Source transaction idempotency key")
    
    # Add conversion-specific computed fields
    conversion_type = graphene.String(description="Conversion type (usdc_to_cusd, cusd_to_usdc)")
    from_amount = graphene.String(description="Amount being converted from")
    to_amount = graphene.String(description="Amount being converted to")
    from_token = graphene.String(description="Token being converted from")
    to_token = graphene.String(description="Token being converted to")
    
    # P2P Trade ID for navigation
    p2p_trade_id = graphene.String(description="P2P Trade ID if this is an exchange transaction")
    ramp_direction = graphene.String(description="Ramp direction (on_ramp/off_ramp)")
    local_transfer_id = graphene.String()
    local_transfer_pending_amount = graphene.Boolean()

    def resolve_local_transfer_id(self, info):
        if self.local_money_flow_id:
            return str(self.local_money_flow.infinia_journey.internal_id)
        return None

    def resolve_local_transfer_pending_amount(self, info):
        return bool(self.local_money_flow_id and self.sender_type == 'external' and self.status != 'CONFIRMED')
    ramp_provider = graphene.String(description="Ramp provider display name")
    ramp_fiat_amount = graphene.String(description="Ramp fiat-side amount")
    ramp_fiat_currency = graphene.String(description="Ramp fiat-side currency")
    ramp_status = graphene.String(description="Ramp-specific status (PENDING, PROCESSING, COMPLETED, etc)")
    
    # Expose Payroll Item ID for QR code verification
    item_id = graphene.String(description="Payroll Item ID")

    # Override token_type to be String to avoid Enum validation errors with mixed case
    token_type = graphene.String(description="Token type (CUSD, USDC, etc)")
    
    class Meta:
        model = UnifiedTransactionTable
        fields = [
            'id',
            'transaction_type',
            'created_at',
            'updated_at',
            'amount',
            'token_type',
            'status',
            'transaction_hash',
            'sender_user',
            'sender_business',
            'sender_type',
            'sender_display_name',
            'sender_address',
            'counterparty_user',
            'counterparty_business',
            'counterparty_type',
            'counterparty_display_name',
            'counterparty_address',
            'is_invitation',
            'invitation_claimed',
            'invitation_reverted',
            'invitation_expires_at',
        ]
    
    def resolve_internal_id(self, info):
        """Standardize internal_id (always return 32-char hex for conversions)"""
        # If it's a conversion, check the internal_id property which returns the UUID
        if self.transaction_type == 'conversion':
            # self.internal_id uses the property accessor (UnifiedTransactionTable.internal_id)
            # which returns the actual UUID object from the related Conversion
            val = self.internal_id
            if val:
                # If it's a UUID object, return hex. If string (already hex?), return it.
                if hasattr(val, 'hex'):
                    return val.hex
                return str(val).replace('-', '')
        
        # For others, return as string (already 32-char hex in DB)
        return str(self.internal_id) if self.internal_id else None

    def resolve_idempotency_key(self, info):
        """Expose source idempotency key where one exists."""
        if self.transaction_type == 'send' and self.send_transaction:
            return self.send_transaction.idempotency_key
        if self.transaction_type == 'payment' and self.payment_transaction:
            return self.payment_transaction.idempotency_key
        return None

    def resolve_direction(self, info):
        """Resolve transaction direction based on current user's address"""
        context = getattr(info, 'context', None)
        user = getattr(context, 'user', None) if context else None
        return row_direction(self, user)
    
    def resolve_display_amount(self, info):
        """Legacy signed gross amount.

        Released clients reuse this field as the receipt's gross. Changing it
        to net would make their payment detail subtract the fee twice. New
        cards receive net_amount separately and choose it for credits.
        """
        try:
            # Handle conversions
            if self.transaction_type == 'conversion':
                return str(self.amount)
            
            # Handle P2P exchanges
            if self.transaction_type == 'exchange':
                direction = UnifiedTransactionType.resolve_direction(self, info)
                if direction == 'sent':
                    return f'-{self.amount}'
                if direction == 'received':
                    return f'+{self.amount}'
                return str(self.amount)
                
            direction = UnifiedTransactionType.resolve_direction(self, info)
            if direction == 'sent':
                return f'-{self.amount}'
            if direction == 'received':
                return f'+{self.amount}'
        except Exception as e:
            print(f"Error in resolve_display_amount: {e}")
        return str(self.amount)
    
    def resolve_fee_amount(self, info):
        if self.fee_amount:
            return self.fee_amount
        if self.transaction_type == 'ramp':
            ramp = getattr(self, 'ramp_transaction', None)
            return _ramp_conversion_fee(ramp) if ramp is not None else ''
        conversion = _external_deposit_conversion(self)
        if conversion is not None:
            fee = (
                getattr(conversion, 'fee_amount_exact', None)
                or getattr(conversion, 'fee_amount', None)
            )
            return str(fee or '')
        return ''

    def resolve_fee_bps(self, info):
        # A rate without an actual deducted fee would create a misleading fee
        # section on historical and explicitly fee-free transactions.
        try:
            fee = Decimal(str(UnifiedTransactionType.resolve_fee_amount(self, info) or 0))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if fee <= 0:
            return None

        if self.transaction_type == 'ramp':
            ramp = getattr(self, 'ramp_transaction', None)
            conversion = getattr(ramp, 'conversion', None) if ramp is not None else None
            bps = _positive_fee_bps(
                getattr(conversion, 'conversion_fee_bps', None))
            if bps is not None:
                return bps
            metadata = getattr(ramp, 'metadata', None) or {}
            legacy_fee = metadata.get('confio_fee') or {}
            if isinstance(legacy_fee, dict):
                bps = _positive_fee_bps(legacy_fee.get('fee_bps'))
                if bps is not None:
                    return bps
            return _positive_fee_bps(metadata.get('confio_fee_bps'))

        conversion = getattr(self, 'conversion', None)
        bps = _positive_fee_bps(
            getattr(conversion, 'conversion_fee_bps', None))
        if bps is not None:
            return bps

        send = getattr(self, 'send_transaction', None)
        bps = _send_fee_bps(send) if send is not None else None
        if bps is not None:
            return bps

        conversion = _external_deposit_conversion(self)
        return _positive_fee_bps(
            getattr(conversion, 'conversion_fee_bps', None))

    def resolve_net_amount(self, info):
        """What reached the recipient. Authoritative — not a client guess."""
        # A ramp row already stores the post-conversion crypto amount.  Its
        # linked conversion fee is exposed above for the receipt, but must not
        # be subtracted from this already-net value a second time.
        if self.transaction_type == 'ramp':
            return str(self.amount)
        conversion = _external_deposit_conversion(self)
        if conversion is not None:
            net = (
                getattr(conversion, 'net_amount_exact', None)
                or getattr(conversion, 'to_amount', None)
            )
            return str(net or self.amount)
        return self.amount_for_direction('received')

    # A Propina: pseudonyms only, no wallet address for either side (nor the
    # hash, which names both on-chain), never "external". `self` is the row.
    def resolve_sender_address(self, info):
        return '' if _is_tip_row(self) else self.sender_address

    def resolve_counterparty_address(self, info):
        return '' if _is_tip_row(self) else self.counterparty_address

    def resolve_sender_type(self, info):
        return 'user' if _is_tip_row(self) else self.sender_type

    def resolve_counterparty_type(self, info):
        return 'user' if _is_tip_row(self) else self.counterparty_type

    def resolve_transaction_hash(self, info):
        return '' if _is_tip_row(self) else self.transaction_hash

    def resolve_sender_user(self, info):
        from send.schema import tip_safe_user
        return tip_safe_user(self.send_transaction, self.sender_user, info) if self.send_transaction_id else self.sender_user

    def resolve_counterparty_user(self, info):
        from send.schema import tip_safe_user
        return (tip_safe_user(self.send_transaction, self.counterparty_user, info)
                if self.send_transaction_id else self.counterparty_user)

    def resolve_sender_status_tier(self, info):
        return _person_badge(self, info, self.sender_user_id, self.sender_business_id)[0]

    def resolve_sender_is_referral_verified(self, info):
        return _person_badge(self, info, self.sender_user_id, self.sender_business_id)[1]

    def resolve_counterparty_status_tier(self, info):
        return _person_badge(self, info, self.counterparty_user_id, self.counterparty_business_id)[0]

    def resolve_counterparty_is_referral_verified(self, info):
        return _person_badge(self, info, self.counterparty_user_id, self.counterparty_business_id)[1]

    def resolve_counterparty_phone(self, info):
        """Only the number the viewer typed on their own send (their contact
        or what they entered). Never an account's verified number: older
        rows copied it here, and Confío's number graph is never shown."""
        viewer = getattr(info.context, 'user', None)
        send = getattr(self, 'send_transaction', None)
        if (self.transaction_type == 'send' and send is not None and viewer is not None
                and send.sender_user_id == getattr(viewer, 'pk', None)
                and (send.recipient_phone_from_sender or send.is_invitation)):
            return send.recipient_phone
        return ''

    def resolve_sender_phone(self, info):
        return ''

    def _send_name(self, info, user, business, stored):
        """A send row is written at prepare, before money moves: until it is
        CONFIRMED, a person's stored name shows only where the name rule
        allows (users/name_visibility.py). Business names always stand."""
        send = getattr(self, 'send_transaction', None)
        if (self.transaction_type != 'send' or self.status == 'CONFIRMED'
                or business is not None or user is None
                # A Propina stores Comunidad pseudonyms: those stand, always.
                or str(getattr(send, 'idempotency_key', '') or '').startswith('tip-')):
            return stored
        from users.name_visibility import can_see_name
        return stored if can_see_name(info, user) else f'@{user.username}'

    def resolve_counterparty_display_name(self, info):
        return UnifiedTransactionType._send_name(
            self, info, self.counterparty_user, self.counterparty_business, self.counterparty_display_name)

    def resolve_sender_display_name(self, info):
        return UnifiedTransactionType._send_name(
            self, info, self.sender_user, self.sender_business, self.sender_display_name)

    def resolve_display_counterparty(self, info):
        """Resolve counterparty name based on direction"""
        try:
            # Conversions have no counterparty — they are one account moving
            # between its own products. Name the MOVE, not a fake party.
            if self.transaction_type == 'conversion':
                ctype = self.get_conversion_type()
                if ctype == 'to_savings':
                    return 'USDT → cUSD+'
                if ctype == 'from_savings':
                    return 'cUSD+ → USDT'
                if ctype == 'usdc_to_cusd':
                    return 'USDC → cUSD'
                if ctype == 'cusd_to_usdc':
                    return 'cUSD → USDC'
                return 'Confío System'
            
            # Handle P2P exchanges
            if self.transaction_type == 'exchange':
                direction = UnifiedTransactionType.resolve_direction(self, info)
                if direction == 'sent':
                    return self.counterparty_display_name or 'Unknown'
                if direction == 'received':
                    return self.sender_display_name or 'Unknown'
                return 'Unknown'
                
            # Get direction directly
            direction = UnifiedTransactionType.resolve_direction(self, info)
            if direction in ('sent', 'received'):
                # An EXTERNAL party has no display name by definition (money
                # to/from a raw address), so falling through to "Unknown" was
                # guaranteed for every external send and every inbound
                # deposit. The address IS the name in that case.
                if direction == 'sent':
                    return (UnifiedTransactionType.resolve_counterparty_display_name(self, info)
                            or _short_addr(self.to_address) or 'Unknown')
                elif direction == 'received':
                    return (UnifiedTransactionType.resolve_sender_display_name(self, info)
                            or _short_addr(self.from_address) or 'Unknown')
        except Exception as e:
            print(f"Error in resolve_display_counterparty: {e}")
        return 'Unknown'
    
    def resolve_display_description(self, info):
        """Resolve description with proper context"""
        try:
            # Handle conversions with their description
            if self.transaction_type == 'conversion':
                return self.description or 'Conversión'

            if self.transaction_type == 'ramp':
                if getattr(self, 'ramp_transaction', None):
                    return 'Recarga' if self.ramp_transaction.direction == 'on_ramp' else 'Retiro'
                return self.description or 'Ramp'

            if self.transaction_type == 'humanitarian':
                release = getattr(self, 'humanitarian_release', None)
                if release and release.kind == 'reimbursement':
                    return 'Reembolso de donación'
                direction = UnifiedTransactionType.resolve_direction(self, info)
                if direction == 'received':
                    return 'Ayuda humanitaria recibida'
                if direction == 'sent':
                    return 'Donación humanitaria'
                return self.description or 'Ayuda humanitaria'
            
            # Handle P2P exchanges with their description
            if self.transaction_type == 'exchange':
                return self.description or 'Intercambio P2P'
                
            if self.transaction_type == 'payment':
                # Get direction directly
                direction = UnifiedTransactionType.resolve_direction(self, info)
                if direction in ('sent', 'received'):
                    if direction == 'sent':
                        return f"Pago a {self.counterparty_display_name or 'Unknown'}"
                    elif direction == 'received':
                        return f"Pago recibido de {self.sender_display_name or 'Unknown'}"
        except Exception as e:
            print(f"Error in resolve_display_description: {e}")
        return self.description or ''
    
    def resolve_conversion_type(self, info):
        """Extract conversion type from description"""
        return self.get_conversion_type()
    
    def resolve_from_amount(self, info):
        """For conversions, this is the amount field"""
        return self.get_from_amount()
    
    def resolve_to_amount(self, info):
        """Extract to_amount from conversion description"""
        return self.get_to_amount()
    
    def resolve_from_token(self, info):
        """For conversions, determine from token"""
        return self.get_from_token()
    
    def resolve_to_token(self, info):
        """For conversions, determine to token"""
        conversion = _external_deposit_conversion(self)
        if conversion is not None:
            return conversion.to_token
        return self.get_to_token()
    
    def resolve_p2p_trade_id(self, info):
        """Return P2P Trade ID if this is an exchange transaction"""
        if self.transaction_type == 'exchange' and self.p2p_trade_id:
            return str(self.p2p_trade_id)
        return None

    def resolve_ramp_direction(self, info):
        if self.transaction_type == 'ramp' and getattr(self, 'ramp_transaction', None):
            return self.ramp_transaction.direction
        return None

    def resolve_ramp_provider(self, info):
        if self.transaction_type == 'ramp' and getattr(self, 'ramp_transaction', None):
            from ramps.ve_pagomovil import public_provider_name
            return public_provider_name(self.ramp_transaction)
        return None

    def resolve_ramp_fiat_amount(self, info):
        if self.transaction_type == 'ramp' and getattr(self, 'ramp_transaction', None):
            ramp = self.ramp_transaction
            if ramp.fiat_amount is not None:
                return str(ramp.fiat_amount)
            # VEXPay reports the amount only once a payment is confirmed. Until
            # then (or if it never is) the row shows what the person was told
            # to pay, in their own currency like every other top-up.
            expected = ((ramp.metadata or {}).get('vexpay') or {}).get('expected_ves')
            return str(expected) if expected else None
        return None

    def resolve_ramp_fiat_currency(self, info):
        if self.transaction_type == 'ramp' and getattr(self, 'ramp_transaction', None):
            return self.ramp_transaction.fiat_currency or None

    def resolve_ramp_status(self, info):
        if self.transaction_type == 'ramp' and getattr(self, 'ramp_transaction', None):
            return self.ramp_transaction.status or None
        return None
        return None

    def resolve_item_id(self, info):
        """Return Payroll Item ID if this is a payroll transaction"""
        if self.transaction_type == 'payroll':
            # Use getattr to avoid potential errors if relationship is missing (though it shouldn't be for payroll type)
            payroll_item = getattr(self, 'payroll_item', None)
            if payroll_item:
                return payroll_item.item_id
        return None


def _short_addr(addr):
    """A raw address is a usable NAME when there is no person behind it."""
    a = (addr or '').strip()
    if not a:
        return ''
    return f'{a[:6]}…{a[-4:]}' if len(a) > 12 else a


def row_direction(row, user):
    """'sent' | 'received' | 'conversion' | 'unknown' for the viewer.

    The viewer is `user` plus the hints the resolvers stamp on each row
    (_account_type, _account_business_id, _user_address). Shared by the
    GraphQL type and the month summary so both read direction identically.
    """
    if row.transaction_type == 'local_transfer':
        return 'received' if row.sender_type == 'external' else 'sent'
    # Conversions are always "self" transactions
    if row.transaction_type == 'conversion':
        return 'conversion'
    if row.transaction_type == 'ramp':
        if getattr(row, 'ramp_transaction', None):
            return 'received' if row.ramp_transaction.direction == 'on_ramp' else 'sent'
        return 'unknown'

    # Payroll: derive from user identity first (addresses may be missing)
    if row.transaction_type == 'payroll':
        if user and user.is_authenticated:
            if row.counterparty_user_id == user.id:
                return 'received'
            if row.sender_user_id == user.id:
                return 'sent'
        # If viewing as business context, sender is the business
        acct_type = getattr(row, '_account_type', None)
        acct_biz_id = getattr(row, '_account_business_id', None)
        if acct_type == 'business' and acct_biz_id:
            if row.sender_business_id == acct_biz_id:
                return 'sent'
            if row.counterparty_business_id == acct_biz_id:
                return 'received'

    # P2P exchanges need special handling: derive from the viewer's active account context first
    if row.transaction_type == 'exchange':
        acct_type = getattr(row, '_account_type', None)
        acct_biz_id = getattr(row, '_account_business_id', None)
        if acct_type == 'business' and acct_biz_id:
            if row.sender_business and row.sender_business.id == acct_biz_id:
                return 'sent'
            if row.counterparty_business and row.counterparty_business.id == acct_biz_id:
                return 'received'
        elif user and user.is_authenticated:
            # Fall back to user identity when personal account
            if row.sender_user and row.sender_user.id == user.id:
                return 'sent'
            if row.counterparty_user and row.counterparty_user.id == user.id:
                return 'received'
        return 'unknown'

    # Get the user's address from the transaction context
    user_address = getattr(row, '_user_address', None)

    if user_address and hasattr(row, 'get_direction_for_address'):
        try:
            direction = row.get_direction_for_address(user_address)
            if direction in ('sent', 'received'):
                return direction
        except Exception as e:
            print(f"Error in resolve_direction: {e}")

    # Historical transfers retain their old wallet addresses after migration.
    # Fall back to the recorded account identity, not the current wallet. A
    # business's owning user must never be mistaken for its personal account.
    if row.transaction_type in ('send', 'payment') and user and user.is_authenticated:
        account_type = getattr(row, '_account_type', 'personal')
        business_id = getattr(row, '_account_business_id', None)
        if account_type == 'business':
            sent = bool(business_id and getattr(row, 'sender_business_id', None) == business_id)
            received = bool(business_id and getattr(row, 'counterparty_business_id', None) == business_id)
        elif account_type == 'personal':
            sent = (getattr(row, 'sender_user_id', None) == user.id
                    and not getattr(row, 'sender_business_id', None))
            received = (getattr(row, 'counterparty_user_id', None) == user.id
                        and not getattr(row, 'counterparty_business_id', None))
        else:
            return 'unknown'
        # Self transfers need a matching address to disambiguate accounts.
        if sent != received:
            return 'sent' if sent else 'received'
    return 'unknown'


def _viewer_address_for(transaction, account):
    """The account address on the SAME CHAIN as this transaction.

    Direction ("did I send or receive this?") is decided by comparing the
    row's from/to against the viewer's address. Those columns hold a BSC
    address for the BSC tokens and an Algorand address for the rest, so
    handing back algorand_address unconditionally made every cUSD+/USDT row
    match neither side: direction came out 'unknown', which in turn renders
    the counterparty as "Unknown" and the amount without a +/- sign.

    CONFIO lives on BOTH chains — the legacy ASA and the re-issued BEP-20 —
    so the token alone cannot say which address to compare. Decide from the
    row's own addresses: a 0x-prefixed from/to is a BSC row whatever the
    token. Without this, BSC CONFIO payments matched neither side and
    rendered with no direction and an "Unknown" counterparty.
    """
    token = (getattr(transaction, 'token_type', '') or '').upper()
    if token in ('CUSD_BSC', 'CUSD_PLUS', 'USDT', 'BNB'):
        return getattr(account, 'bsc_address', None) or ''
    # Token labels are not the ultimate chain authority: CONFIO exists on
    # both chains, and future dual-chain assets can too. A 0x endpoint makes
    # this an EVM row regardless of symbol.
    for field in ('from_address', 'to_address', 'sender_address',
                  'counterparty_address'):
        value = (getattr(transaction, field, '') or '').strip().lower()
        if value.startswith('0x'):
            return getattr(account, 'bsc_address', None) or ''
    return account.algorand_address


def jwt_account(user, jwt_context):
    """The Account named by a validated JWT context, or None."""
    from users.models import Account
    account_type = jwt_context['account_type']
    account_index = jwt_context['account_index']
    business_id = jwt_context.get('business_id')
    try:
        if account_type == 'business' and business_id:
            # For business accounts, find the account by business_id (normalize index if needed)
            try:
                return Account.objects.get(
                    business_id=business_id,
                    account_type='business',
                    account_index=account_index
                )
            except Account.DoesNotExist:
                return Account.objects.filter(
                    business_id=business_id,
                    account_type='business'
                ).order_by('account_index').first()
        # For personal accounts
        return Account.objects.get(
            user=user,
            account_type=account_type,
            account_index=account_index
        )
    except Account.DoesNotExist:
        return None


def account_unified_queryset(user, account, account_type, business_id):
    """Every ledger row the active (JWT) account may see — the one scope
    shared by the history list and the month summary ("Tu mes"), so the two
    can never disagree about which movements exist.
    """
    if account_type == 'business' and business_id:
        # For business accounts, filter by business relationships using JWT business_id
        from users.models import Business
        business = Business.objects.get(id=business_id)
        queryset = _visible_unified().filter(
            Q(sender_business=business) |
            Q(counterparty_business=business)
        )
    else:
        # For personal accounts, filter by user relationships
        # Include:
        # 1. Personal-to-personal transactions (no business involved)
        # 2. Payroll transactions where user is the recipient
        queryset = _visible_unified().filter(
            Q(
                Q(sender_user=user) & Q(sender_business__isnull=True)
            ) |
            Q(
                Q(counterparty_user=user) & Q(counterparty_business__isnull=True)
            ) |
            Q(
                Q(counterparty_user=user) & Q(transaction_type='payroll')
            )
        )
    queryset = queryset.filter(Q(local_money_flow__isnull=True) | Q(local_money_flow__confio_account=account))
    # A ramp's own conversion is shown as part of the ramp row, never twice.
    return queryset.exclude(
        Q(transaction_type='conversion') & Q(conversion__ramp_transactions__isnull=False)
    )


class UnifiedTransactionQuery(graphene.ObjectType):
    """GraphQL queries for unified transactions"""
    
    unified_transactions = graphene.List(
        UnifiedTransactionType,
        account_type=graphene.String(required=True),
        account_index=graphene.Int(required=True),
        limit=graphene.Int(default_value=50),
        offset=graphene.Int(default_value=0),
        token_types=graphene.List(graphene.String),
        description="Get unified transactions for a specific account"
    )
    
    current_account_transactions = graphene.List(
        UnifiedTransactionType,
        limit=graphene.Int(default_value=50),
        offset=graphene.Int(default_value=0),
        token_types=graphene.List(graphene.String),
        transaction_types=graphene.List(graphene.String),
        description="Get unified transactions for current JWT account context"
    )
    
    unified_transactions_with_friend = graphene.List(
        UnifiedTransactionType,
        friend_user_id=graphene.ID(),
        friend_phone=graphene.String(),
        limit=graphene.Int(default_value=50),
        offset=graphene.Int(default_value=0),
        description="Get unified transactions between current user and a specific friend"
    )
    
    def resolve_unified_transactions(self, info, account_type, account_index, 
                                   limit=50, offset=0, token_types=None):
        """Resolve unified transactions for the current user's account"""
        user = info.context.user
        if not user.is_authenticated:
            return []
        
        # Get the account
        from users.models import Account
        try:
            account = Account.objects.get(
                user=user,
                account_type=account_type,
                account_index=account_index
            )
        except Account.DoesNotExist:
            return []
        
        # Base query - all transactions involving this account
        if account.account_type == 'business' and account.business:
            # For business accounts, filter by business relationships
            queryset = _visible_unified().select_related(
                'send_transaction', 
                'payment_transaction', 
                'conversion', 
                'p2p_trade', 
                'payroll_item', 
                'referral_reward_event', 
                'presale_purchase',
                'ramp_transaction',
                'ramp_transaction__conversion',
                'humanitarian_donation',
                'humanitarian_release',
            ).filter(
                Q(sender_business=account.business) | 
                Q(counterparty_business=account.business)
            )
        else:
            # For personal accounts, filter by user relationships
            # Include:
            # 1. Personal-to-personal transactions (no business involved)
            # 2. Payroll transactions where user is the recipient
            queryset = _visible_unified().select_related(
                'send_transaction', 
                'payment_transaction', 
                'conversion', 
                'p2p_trade', 
                'payroll_item', 
                'referral_reward_event', 
                'presale_purchase',
                'ramp_transaction',
                'ramp_transaction__conversion',
                'humanitarian_donation',
                'humanitarian_release',
            ).filter(
                Q(
                    Q(sender_user=user) & Q(sender_business__isnull=True)
                ) | 
                Q(
                    Q(counterparty_user=user) & Q(counterparty_business__isnull=True)
                ) |
                Q(
                    Q(counterparty_user=user) & Q(transaction_type='payroll')
                )
            )
        
        # Filter by token types if provided (case-insensitive to handle legacy rows)
        queryset = queryset.select_related('local_money_flow__infinia_journey').filter(Q(local_money_flow__isnull=True) | Q(local_money_flow__confio_account=account))
        if token_types:
            from django.db.models.functions import Upper
            wanted = [t.upper() for t in token_types]
            queryset = queryset.annotate(tok_upper=Upper('token_type')).filter(tok_upper__in=wanted)
        
        queryset = queryset.exclude(
            Q(transaction_type='conversion') & Q(conversion__ramp_transactions__isnull=False)
        )

        # Order by created_at descending to show newest first
        queryset = queryset.order_by('-created_at')
        
        # Apply pagination and add viewer context hints to each transaction for resolvers
        transactions = list(queryset[offset:offset + limit])
        _preload_external_deposit_conversions(transactions)
        _preload_badges(transactions, info)
        for transaction in transactions:
            # Hints used by resolvers to compute perspective/direction correctly
            transaction._user_address = _viewer_address_for(transaction, account)
            transaction._account_type = account.account_type
            transaction._account_business_id = getattr(account.business, 'id', None) if account.account_type == 'business' else None
        
        return transactions
    
    def resolve_current_account_transactions(
            self, info, limit=50, offset=0, token_types=None,
            transaction_types=None):
        """Resolve unified transactions using JWT account context"""
        from .jwt_context import get_jwt_business_context_with_validation
        
        # Get JWT context with validation and permission check
        jwt_context = get_jwt_business_context_with_validation(info, required_permission='view_transactions')
        if not jwt_context:
            return []
            
        # Get the user from the request
        user = info.context.user
        if not user or not user.is_authenticated:
            return []
            
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        print(f"Transaction resolver - JWT context: user_id={user.id}, account_type={account_type}, account_index={account_index}, business_id={business_id}")
        
        account = jwt_account(user, jwt_context)
        if account is None:
            print(f"Account not found for type {account_type}, index {account_index}, business_id {business_id}")
            return []

        print(f"Found account: {account.id}, business: {account.business.id if account.business else None}")
        print(f"Transaction resolver - DEBUG: Using JWT business_id={business_id} for query")
        
        queryset = account_unified_queryset(user, account, account_type, business_id)

        # Filter by token types if provided (case-insensitive)
        if token_types:
            from django.db.models.functions import Upper
            wanted = [t.upper() for t in token_types]
            queryset = queryset.annotate(tok_upper=Upper('token_type')).filter(tok_upper__in=wanted)

        # Apply operation filtering before pagination.  History screens must
        # not fetch a mixed page and discard unrelated rows client-side: a
        # busy account could otherwise have every ramp row pushed beyond the
        # first page even though those rows exist in the ledger.
        if transaction_types:
            from django.db.models.functions import Lower
            wanted_types = [
                str(value).strip().lower()
                for value in transaction_types
                if str(value).strip()
            ]
            queryset = queryset.annotate(
                transaction_type_lower=Lower('transaction_type'),
            ).filter(transaction_type_lower__in=wanted_types)

        queryset = queryset.select_related(
            'local_money_flow__infinia_journey',
            'send_transaction',
            'payment_transaction',
            'conversion',
            'p2p_trade',
            'payroll_item',
            'referral_reward_event',
            'presale_purchase',
            'ramp_transaction',
            'ramp_transaction__conversion',
            'humanitarian_donation',
            'humanitarian_release',
        )

        # Order by created_at descending to show newest first
        queryset = queryset.order_by('-created_at')

        # Apply pagination and add viewer context hints to each transaction for resolvers
        transactions = list(queryset[offset:offset + limit])
        _preload_external_deposit_conversions(transactions)
        _preload_badges(transactions, info)
        print(f"Found {len(transactions)} transactions for account {account.id}")
        for transaction in transactions:
            transaction._user_address = _viewer_address_for(transaction, account)
            transaction._account_type = account.account_type
            transaction._account_business_id = getattr(account.business, 'id', None) if account.account_type == 'business' else None
        
        return transactions
    
    def resolve_unified_transactions_with_friend(self, info, friend_user_id=None, friend_phone=None, 
                                               limit=50, offset=0):
        """Resolve unified transactions between current user and a specific friend"""
        from .jwt_context import get_jwt_business_context_with_validation
        
        # Get JWT context with validation and permission check
        jwt_context = get_jwt_business_context_with_validation(info, required_permission='view_transactions')
        if not jwt_context:
            return []
            
        # Get the user from the request
        user = info.context.user
        if not user or not user.is_authenticated:
            return []
        
        # Must have either friend_user_id or friend_phone
        if not friend_user_id and not friend_phone:
            return []
        
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        print(f"Friend transactions resolver - JWT context: user_id={user.id}, account_type={account_type}, account_index={account_index}, business_id={business_id}")
        
        # Get the account using JWT context
        from users.models import Account
        try:
            if account_type == 'business' and business_id:
                # For business accounts, find the account by business_id (normalize index if needed)
                try:
                    account = Account.objects.get(
                        business_id=business_id,
                        account_type='business',
                        account_index=account_index
                    )
                except Account.DoesNotExist:
                    account = Account.objects.filter(
                        business_id=business_id,
                        account_type='business'
                    ).order_by('account_index').first()
                    if not account:
                        raise
            else:
                # For personal accounts
                account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index
                )
        except Account.DoesNotExist:
            print(f"Friend transactions - Account not found for type {account_type}, index {account_index}, business_id {business_id}")
            return []
        
        print(f"Found account: {account.id}, business: {account.business.id if account.business else None}")
        
        # Base query - transactions involving the current account (similar to current_account_transactions)
        if account_type == 'business' and business_id:
            # For business accounts, filter by business relationships using JWT business_id
            from users.models import Business
            business = Business.objects.get(id=business_id)
            print(f"Friend transactions resolver - Filtering transactions for business id={business.id}, name={business.name}")
            queryset = _visible_unified().filter(
                Q(sender_business=business) | 
                Q(counterparty_business=business)
            )
        else:
            # For personal accounts, filter by user relationships
            # Include:
            # 1. Personal-to-personal transactions (no business involved)
            # 2. Payroll transactions where user is the recipient
            queryset = _visible_unified().filter(
                Q(
                    Q(sender_user=user) & Q(sender_business__isnull=True)
                ) | 
                Q(
                    Q(counterparty_user=user) & Q(counterparty_business__isnull=True)
                ) |
                Q(
                    Q(counterparty_user=user) & Q(transaction_type='payroll')
                )
            )
        
        # Filter by friend criteria
        friend_conditions = Q()
        
        if friend_user_id:
            # Filter by friend user ID
            friend_conditions |= Q(
                Q(sender_user_id=friend_user_id) | Q(counterparty_user_id=friend_user_id)
            )
        
        if friend_phone:
            # Only numbers the viewer typed on their own sends: matching
            # stored verified numbers would tell them who holds a number.
            friend_conditions |= Q(
                Q(transaction_type='send', send_transaction__sender_user=user,
                  send_transaction__recipient_phone=friend_phone)
                & (Q(send_transaction__recipient_phone_from_sender=True) | Q(send_transaction__is_invitation=True))
            )
        
        # Apply friend filter
        queryset = queryset.filter(friend_conditions)

        queryset = queryset.select_related(
            'send_transaction',
            'payment_transaction',
            'conversion',
            'p2p_trade',
            'payroll_item',
            'referral_reward_event',
            'presale_purchase',
            'ramp_transaction',
            'ramp_transaction__conversion',
            'humanitarian_donation',
            'humanitarian_release',
        )
        
        queryset = queryset.exclude(
            Q(transaction_type='conversion') & Q(conversion__ramp_transactions__isnull=False)
        )

        # Order by created_at descending to show newest first
        queryset = queryset.order_by('-created_at')
        
        # Apply pagination and add user address to each transaction for direction calculation
        transactions = list(queryset[offset:offset + limit])
        _preload_external_deposit_conversions(transactions)
        _preload_badges(transactions, info)
        
        print(f"Friend transactions resolver - Found {len(transactions)} transactions for account {account.id} with friend criteria")
        
        # Set the user's address on each transaction for the resolvers
        for transaction in transactions:
            transaction._user_address = _viewer_address_for(transaction, account)
            transaction._account_type = account.account_type
            transaction._account_business_id = account.business_id if account.account_type == 'business' else None

        return transactions
