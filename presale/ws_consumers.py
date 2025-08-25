import asyncio
import json
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async


class _DummyRequest:
    def __init__(self, user, meta):
        self.user = user
        self.META = meta


class _DummyInfo:
    def __init__(self, context):
        self.context = context


class PresaleSessionConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket for CONFIO Presale (prepare + submit, fully sponsored).

    Client → Server:
      - {type:"ping"}
      - {type:"prepare_request", amount: number|string}
      - {type:"submit_request", purchase_id: string, signed_transactions: list, sponsor_transactions?: list}

    Server → Client:
      - {type:"pong"}
      - {type:"server_ping"}
      - {type:"prepare_ready", pack:{purchase_id, transactions, sponsor_transactions, user_signing_indexes, group_id}}
      - {type:"error", message}
      - {type:"submit_ok", transaction_id}
    """

    KEEPALIVE_SEC = 25
    IDLE_TIMEOUT_SEC = 60

    async def connect(self):
        user = self.scope.get("user")
        if not user or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return
        params = parse_qs(self.scope.get("query_string", b"").decode())
        self._raw_token = (params.get("token", [None])[0]) or ""
        await self.accept()
        self._keepalive_task = asyncio.create_task(self._keepalive())
        self._idle_task = asyncio.create_task(self._idle_close())

    async def disconnect(self, code):
        for t in (getattr(self, "_keepalive_task", None), getattr(self, "_idle_task", None)):
            if t:
                t.cancel()

    async def receive_json(self, content, **kwargs):
        await self._reset_idle_timer()
        t = content.get("type")
        if t == "ping":
            await self.send_json({"type": "pong"})
            return
        if t == "claim_prepare":
            try:
                pack = await self._claim_prepare()
                if not pack.get("success"):
                    await self.send_json({"type": "error", "message": pack.get("error", "claim_prepare_failed")})
                    return
                await self.send_json({
                    "type": "prepare_ready",
                    "pack": {
                        "transactions": pack.get("transactions"),
                        "sponsor_transactions": pack.get("sponsor_transactions"),
                        "user_signing_indexes": [0],
                        "group_id": pack.get("group_id"),
                    },
                })
            except Exception as e:
                await self.send_json({"type": "error", "message": str(e) or "claim_prepare_exception"})
            return
        if t == "claim_submit":
            try:
                signed = content.get("signed_transactions")
                sponsors = content.get("sponsor_transactions") or []
                res = await self._claim_submit(signed, sponsors)
                if not res.get("success"):
                    await self.send_json({"type": "error", "message": res.get("error", "claim_submit_failed")})
                    return
                await self.send_json({"type": "submit_ok", "transaction_id": res.get("txid")})
            except Exception as e:
                await self.send_json({"type": "error", "message": str(e) or "claim_submit_exception"})
            return
        if t == "optin_prepare":
            try:
                pack = await self._optin_prepare()
                if not pack.get("success"):
                    await self.send_json({"type": "error", "message": pack.get("error", "optin_prepare_failed")})
                    return
                await self.send_json({
                    "type": "prepare_ready",
                    "pack": {
                        "transactions": pack.get("transactions"),
                        "sponsor_transactions": pack.get("sponsor_transactions"),
                        "user_signing_indexes": [1],
                        "group_id": pack.get("group_id"),
                    },
                })
            except Exception as e:
                await self.send_json({"type": "error", "message": str(e) or "optin_prepare_exception"})
            return
        if t == "optin_submit":
            try:
                signed = content.get("signed_transactions")
                sponsors = content.get("sponsor_transactions") or []
                res = await self._optin_submit(signed, sponsors)
                if not res.get("success"):
                    await self.send_json({"type": "error", "message": res.get("error", "optin_submit_failed")})
                    return
                await self.send_json({"type": "submit_ok", "transaction_id": res.get("txid")})
            except Exception as e:
                await self.send_json({"type": "error", "message": str(e) or "optin_submit_exception"})
            return
        if t == "prepare_request":
            try:
                amount = content.get("amount")
                pack = await self._prepare(amount)
                if not pack.get("success"):
                    # Special hint: presale app opt-in required
                    if pack.get('error') == 'requires_presale_app_optin':
                        await self.send_json({"type": "error", "message": "requires_presale_app_optin", "app_id": pack.get('app_id')})
                        return
                    await self.send_json({"type": "error", "message": pack.get("error", "prepare_failed")})
                    return
                await self.send_json({
                    "type": "prepare_ready",
                    "pack": {
                        "purchase_id": pack.get("purchase_id"),
                        "transactions": pack.get("transactions"),
                        "sponsor_transactions": pack.get("sponsor_transactions"),
                        "user_signing_indexes": pack.get("user_signing_indexes", [1]),
                        "group_id": pack.get("group_id"),
                    },
                })
            except Exception as e:
                await self.send_json({"type": "error", "message": str(e) or "prepare_exception"})
            return
        if t == "submit_request":
            try:
                purchase_id = content.get("purchase_id")
                signed_transactions = content.get("signed_transactions")
                sponsor_transactions = content.get("sponsor_transactions") or []
                res = await self._submit(purchase_id, signed_transactions, sponsor_transactions)
                if not res.get("success"):
                    await self.send_json({"type": "error", "message": res.get("error", "submit_failed")})
                    return
                await self.send_json({"type": "submit_ok", "transaction_id": res.get("txid")})
            except Exception as e:
                await self.send_json({"type": "error", "message": str(e) or "submit_exception"})
            return

    async def _keepalive(self):
        try:
            while True:
                await asyncio.sleep(self.KEEPALIVE_SEC)
                await self.send_json({"type": "server_ping"})
        except asyncio.CancelledError:
            return

    async def _idle_close(self):
        try:
            await asyncio.sleep(self.IDLE_TIMEOUT_SEC)
            await self.close(code=1000)
        except asyncio.CancelledError:
            return

    async def _reset_idle_timer(self):
        task = getattr(self, "_idle_task", None)
        if task:
            task.cancel()
        self._idle_task = asyncio.create_task(self._idle_close())

    @database_sync_to_async
    def _prepare(self, amount):
        from decimal import Decimal
        from django.utils import timezone
        from presale.models import PresalePhase, PresalePurchase, UserPresaleLimit, PresaleSettings
        from users.models import Account
        from blockchain.presale_transaction_builder import PresaleTransactionBuilder

        user = self.scope.get("user")

        # Validate presale is active and find phase
        settings_obj = PresaleSettings.get_settings()
        if not settings_obj.is_presale_active:
            return {"success": False, "error": "presale_inactive"}

        phase = PresalePhase.objects.filter(status='active').first()
        if not phase:
            return {"success": False, "error": "no_active_phase"}

        # Parse and validate amount
        try:
            cusd_amount = Decimal(str(amount))
        except Exception:
            return {"success": False, "error": "invalid_amount"}

        if cusd_amount < phase.min_purchase:
            return {"success": False, "error": "below_minimum"}
        if cusd_amount > phase.max_purchase:
            return {"success": False, "error": "above_maximum"}

        # Check user's limit
        upl, _ = UserPresaleLimit.objects.get_or_create(user=user, phase=phase)
        if phase.max_per_user and upl.total_purchased + cusd_amount > phase.max_per_user:
            return {"success": False, "error": "exceeds_user_limit"}

        # Resolve user's Algorand address
        account = Account.objects.filter(user=user, account_type='personal', deleted_at__isnull=True).first()
        if not account or not account.algorand_address or len(account.algorand_address) != 58:
            return {"success": False, "error": "no_algorand_address"}

        # Compute CONFIO amount (phase pricing uses cUSD per token)
        confio_amount = (cusd_amount / phase.price_per_token).quantize(Decimal('0.000001'))

        # Create purchase record (pending blockchain)
        purchase = PresalePurchase.objects.create(
            user=user,
            phase=phase,
            cusd_amount=cusd_amount,
            confio_amount=confio_amount,
            price_per_token=phase.price_per_token,
            status='processing',
            from_address=account.algorand_address,
        )

        # Build sponsored transaction group
        builder = PresaleTransactionBuilder()
        cusd_base = int(cusd_amount * 10**6)
        tx_pack = builder.build_buy_group(account.algorand_address, cusd_base)
        if not tx_pack.get('success'):
            # Clean up the pending record if we couldn't build a pack
            try:
                purchase.delete()
            except Exception:
                pass
            return {"success": False, **{k: v for k, v in tx_pack.items() if k != 'success'}}

        # Normalize transactions for client
        sponsors = tx_pack.get('sponsor_transactions') or []
        user_tx = tx_pack.get('transactions_to_sign') or []
        transactions = []

        # Preserve sponsor signatures if present
        for sp in sponsors:
            transactions.append({
                "index": sp.get('index'),
                "type": "payment" if sp.get('index') == 0 else "application",
                "transaction": sp.get('signed') or sp.get('txn'),
                "signed": bool(sp.get('signed')),
                "needs_signature": not bool(sp.get('signed')),
            })

        for ut in user_tx:
            transactions.append({
                "index": ut.get('index', 1),
                "type": "asset_transfer",
                "transaction": ut.get('txn'),
                "signed": False,
                "needs_signature": True,
            })

        return {
            "success": True,
            "purchase_id": str(purchase.id),
            "transactions": transactions,
            "sponsor_transactions": sponsors,  # raw for debugging/clients that need structure
            "user_signing_indexes": [1],
            "group_id": tx_pack.get('group_id'),
        }

    @database_sync_to_async
    def _optin_prepare(self):
        from users.models import Account
        from blockchain.presale_transaction_builder import PresaleTransactionBuilder

        user = self.scope.get("user")
        account = Account.objects.filter(user=user, account_type='personal', deleted_at__isnull=True).first()
        if not account or not account.algorand_address or len(account.algorand_address) != 58:
            return {"success": False, "error": "no_algorand_address"}

        builder = PresaleTransactionBuilder()
        tx_pack = builder.build_app_opt_in(account.algorand_address)
        if not tx_pack.get('success'):
            return {"success": False, "error": tx_pack.get('error', 'optin_prepare_failed')}
        if tx_pack.get('already_opted_in'):
            return {"success": True, "transactions": [], "sponsor_transactions": [], "group_id": None}

        sponsors = tx_pack.get('sponsor_transactions') or []
        user_tx = tx_pack.get('transactions_to_sign') or []

        transactions = []
        for sp in sponsors:
            transactions.append({
                "index": sp.get('index'),
                "type": "payment",
                "transaction": sp.get('signed') or sp.get('txn'),
                "signed": bool(sp.get('signed')),
                "needs_signature": not bool(sp.get('signed')),
            })
        for ut in user_tx:
            transactions.append({
                "index": ut.get('index', 1),
                "type": "application_opt_in",
                "transaction": ut.get('txn'),
                "signed": False,
                "needs_signature": True,
            })

        return {
            "success": True,
            "transactions": transactions,
            "sponsor_transactions": sponsors,
            "group_id": tx_pack.get('group_id'),
        }

    @database_sync_to_async
    def _claim_prepare(self):
        from presale.models import PresaleSettings
        from users.models import Account
        from blockchain.presale_transaction_builder import PresaleTransactionBuilder

        # Check global switch for claims
        settings_obj = PresaleSettings.get_settings()
        if not settings_obj.is_presale_claims_unlocked:
            return {"success": False, "error": "claims_locked"}

        user = self.scope.get("user")
        account = Account.objects.filter(user=user, account_type='personal', deleted_at__isnull=True).first()
        if not account or not account.algorand_address or len(account.algorand_address) != 58:
            return {"success": False, "error": "no_algorand_address"}

        builder = PresaleTransactionBuilder()
        tx_pack = builder.build_claim_group(account.algorand_address)
        if not tx_pack.get('success'):
            return {"success": False, "error": tx_pack.get('error', 'claim_prepare_failed')}

        sponsors = tx_pack.get('sponsor_transactions') or []
        user_tx = tx_pack.get('transactions_to_sign') or []
        transactions = []
        for ut in user_tx:
            transactions.append({
                "index": ut.get('index', 0),
                "type": "payment",
                "transaction": ut.get('txn'),
                "signed": False,
                "needs_signature": True,
            })
        for sp in sponsors:
            transactions.append({
                "index": sp.get('index', 1),
                "type": "application",
                "transaction": sp.get('signed') or sp.get('txn'),
                "signed": bool(sp.get('signed')),
                "needs_signature": not bool(sp.get('signed')),
            })
        return {
            "success": True,
            "transactions": transactions,
            "sponsor_transactions": sponsors,
            "group_id": tx_pack.get('group_id'),
        }

    @database_sync_to_async
    def _claim_submit(self, signed_transactions, sponsor_transactions):
        from algosdk.v2client import algod
        from blockchain.algorand_account_manager import AlgorandAccountManager
        import base64, json

        if not isinstance(signed_transactions, list) or not signed_transactions:
            return {"success": False, "error": "signed_transactions_required"}

        # Extract user witness (index 0)
        user_signed = None
        for tx in signed_transactions:
            try:
                idx = int(tx.get('index'))
                if idx == 0:
                    user_signed = tx.get('transaction')
                    break
            except Exception:
                if isinstance(tx, str) and not user_signed:
                    user_signed = tx
        if not user_signed:
            return {"success": False, "error": "missing_user_signed"}

        # Sponsor app call (index 1)
        sponsor1 = None
        try:
            for e in (sponsor_transactions or []):
                if isinstance(e, str):
                    e = json.loads(e)
                if int(e.get('index')) == 1:
                    sponsor1 = e.get('signed') or e.get('txn')
        except Exception:
            pass

        # If missing sponsor signature, rebuild and sign server-side
        if not sponsor1:
            try:
                # Recreate pack for address from the witness (not trivial). Simpler: rebuild requires user address.
                # We cannot derive user addr from signed bytes here robustly; rely on frontend/prepare flow to send sponsor txn.
                return {"success": False, "error": "missing_sponsor_signed"}
            except Exception:
                return {"success": False, "error": "cannot_sign_sponsor"}

        # Submit two txns combined
        def b64_to_bytes(b64s: str) -> bytes:
            missing = len(b64s) % 4
            if missing:
                b64s += '=' * (4 - missing)
            return base64.b64decode(b64s)

        algod_client = algod.AlgodClient(
            AlgorandAccountManager.ALGOD_TOKEN,
            AlgorandAccountManager.ALGOD_ADDRESS,
        )
        import base64 as _b64
        group_bytes = b''.join([b64_to_bytes(user_signed), b64_to_bytes(sponsor1)])
        combined_b64 = _b64.b64encode(group_bytes).decode('utf-8')
        txid = algod_client.send_raw_transaction(combined_b64)
        return {"success": True, "txid": txid}

    @database_sync_to_async
    def _optin_submit(self, signed_transactions, sponsor_transactions):
        from algosdk.v2client import algod
        from blockchain.algorand_account_manager import AlgorandAccountManager
        import base64, json

        if not isinstance(signed_transactions, list) or not signed_transactions:
            return {"success": False, "error": "signed_transactions_required"}

        sponsor0 = None
        try:
            for e in (sponsor_transactions or []):
                if isinstance(e, str):
                    e = json.loads(e)
                if int(e.get('index')) == 0:
                    sponsor0 = e.get('signed') or e.get('txn')
        except Exception:
            pass

        user_signed = None
        for tx in signed_transactions:
            try:
                idx = int(tx.get('index'))
                if idx == 1:
                    user_signed = tx.get('transaction')
                    break
            except Exception:
                if isinstance(tx, str) and not user_signed:
                    user_signed = tx
        if not user_signed or not sponsor0:
            return {"success": False, "error": "missing_signed_entries"}

        def b64_to_bytes(b64s: str) -> bytes:
            missing = len(b64s) % 4
            if missing:
                b64s += '=' * (4 - missing)
            import base64 as _b
            return _b.b64decode(b64s)

        algod_client = algod.AlgodClient(
            AlgorandAccountManager.ALGOD_TOKEN,
            AlgorandAccountManager.ALGOD_ADDRESS,
        )
        # Concatenate to a single binary blob and base64-encode (SDK accepts base64 string)
        import base64 as _b64
        group_bytes = b''.join([b64_to_bytes(sponsor0), b64_to_bytes(user_signed)])
        combined_b64 = _b64.b64encode(group_bytes).decode('utf-8')
        txid = algod_client.send_raw_transaction(combined_b64)
        return {"success": True, "txid": txid}

    @database_sync_to_async
    def _submit(self, purchase_id, signed_transactions, sponsor_transactions):
        from presale.models import PresalePurchase
        from algosdk.v2client import algod
        import base64
        import msgpack

        # Load purchase
        try:
            purchase = PresalePurchase.objects.get(id=purchase_id)
        except PresalePurchase.DoesNotExist:
            return {"success": False, "error": "purchase_not_found"}

        # Expect user-signed array with at least the axfer at index 1
        if not isinstance(signed_transactions, list) or not signed_transactions:
            return {"success": False, "error": "signed_transactions_required"}

        # Build final group: sponsor[0], user[1], sponsor[2]
        # Prefer the sponsor entries provided during prepare (already pre-signed)
        sponsor0_b64 = None
        sponsor2_b64 = None
        try:
            for e in (sponsor_transactions or []):
                if isinstance(e, str):
                    e = json.loads(e)
                idx = int(e.get('index'))
                signed = e.get('signed')
                raw = e.get('txn')
                if idx == 0:
                    sponsor0_b64 = signed or raw
                elif idx == 2:
                    sponsor2_b64 = signed or raw
        except Exception:
            pass

        # Extract user signed (index 1)
        user_signed_b64 = None
        for tx in signed_transactions:
            try:
                idx = int(tx.get('index'))
                if idx == 1:
                    user_signed_b64 = tx.get('transaction')
                    break
            except Exception:
                # Also allow simple list of strings
                if isinstance(tx, str) and not user_signed_b64:
                    user_signed_b64 = tx
        if not user_signed_b64:
            return {"success": False, "error": "missing_user_signed"}

        # If we still lack sponsor signatures, rebuild and sign with sponsor key
        if not sponsor0_b64 or not sponsor2_b64:
            try:
                from blockchain.presale_transaction_builder import PresaleTransactionBuilder
                builder = PresaleTransactionBuilder()
                # Re-create group with same amount to sign sponsor parts
                cusd_base = int(purchase.cusd_amount * 10**6)
                pack = builder.build_buy_group(purchase.from_address, cusd_base)
                sp_list = pack.get('sponsor_transactions') or []
                for e in sp_list:
                    if int(e.get('index')) == 0:
                        sponsor0_b64 = e.get('signed') or e.get('txn')
                    elif int(e.get('index')) == 2:
                        sponsor2_b64 = e.get('signed') or e.get('txn')
            except Exception:
                return {"success": False, "error": "cannot_sign_sponsor"}

        try:
            from blockchain.algorand_account_manager import AlgorandAccountManager
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS,
            )
            # Compose bytes in correct order
            def b64_to_bytes(b64s: str) -> bytes:
                missing = len(b64s) % 4
                if missing:
                    b64s += '=' * (4 - missing)
                return base64.b64decode(b64s)

            # Submit as a single base64-encoded blob (align with other flows)
            import base64 as _b64
            group_bytes = b''.join([
                b64_to_bytes(sponsor0_b64),
                b64_to_bytes(user_signed_b64),
                b64_to_bytes(sponsor2_b64),
            ])
            combined_b64 = _b64.b64encode(group_bytes).decode('utf-8')
            txid = algod_client.send_raw_transaction(combined_b64)

            # Save txid immediately (Celery will confirm and mark completed)
            purchase.transaction_hash = txid
            purchase.save(update_fields=['transaction_hash', 'updated_at'])

            return {"success": True, "txid": txid}
        except Exception as e:
            return {"success": False, "error": str(e) or "submit_failed"}
