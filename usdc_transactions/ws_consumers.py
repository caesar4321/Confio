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


class WithdrawSessionConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket for USDC withdrawals (prepare + submit, two-step).
    - prepare: {type:"prepare", amount:"<decimal>", destination_address:"<algo_addr>"}
      -> {type:"prepare_ready", pack:{internal_id, transactions:[b64], sponsor_transactions:[json], group_id}}
    - submit: {type:"submit", internal_id:"<id>", signed_transactions:[b64], sponsor_transactions:[json|string]}
      -> {type:"submit_ok", txid, internal_id}
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
        if t == "prepare":
            amount = content.get("amount")
            dest = content.get("destination_address")
            try:
                pack = await self._prepare(amount=str(amount), destination_address=str(dest))
                if not pack.get("success"):
                    await self.send_json({"type": "error", "message": pack.get("error", "prepare_failed")})
                    return
                await self.send_json({
                    "type": "prepare_ready",
                    "pack": {
                        "internal_id": pack.get("internal_id"),
                        "transactions": pack.get("transactions"),
                        "sponsor_transactions": pack.get("sponsor_transactions"),
                        "group_id": pack.get("group_id"),
                    },
                })
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"WS Prepare Error: {e}")
                await self.send_json({"type": "error", "message": str(e) or "prepare_exception"})
            return
        if t == "submit":
            iid = content.get("internal_id") or content.get("withdrawal_id")
            signed_transactions = content.get("signed_transactions")
            sponsor_transactions = content.get("sponsor_transactions") or []
            try:
                res = await self._submit(internal_id=str(iid), signed_transactions=signed_transactions, sponsor_transactions=sponsor_transactions)
                if not res.get("success"):
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"WS Submit Failed: {res.get('error')}")
                    await self.send_json({"type": "error", "message": res.get("error", "submit_failed")})
                    return
                await self.send_json({"type": "submit_ok", "txid": res.get("txid"), "internal_id": res.get("internal_id")})
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"WS Submit Exception: {e}")
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
    def _prepare(self, amount: str, destination_address: str):
        from django.conf import settings
        from algosdk.v2client import algod
        from algosdk import transaction as algo_txn
        from algosdk import encoding as algo_encoding
        from decimal import Decimal
        from users.jwt_context import get_jwt_business_context_with_validation
        from users.models import Account
        from usdc_transactions.models import USDCWithdrawal

        user = self.scope.get("user")
        meta = {}
        if self._raw_token:
            meta["HTTP_AUTHORIZATION"] = f"JWT {self._raw_token}"
        info = _DummyInfo(context=_DummyRequest(user=user, meta=meta))

        # Validate JWT context
        jwt_ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not jwt_ctx:
            return {"success": False, "error": "No access or permission"}
        acct = None
        if jwt_ctx['account_type'] == 'business' and jwt_ctx.get('business_id'):
            acct = Account.objects.filter(account_type='business', business_id=jwt_ctx['business_id'], account_index=jwt_ctx.get('account_index', 0)).first() or \
                   Account.objects.filter(account_type='business', business_id=jwt_ctx['business_id']).order_by('account_index').first()
        else:
            acct = Account.objects.filter(user=user, account_type='personal', account_index=jwt_ctx.get('account_index', 0)).first()
        if not acct or not acct.algorand_address:
            return {"success": False, "error": "Active account not found or missing Algorand address"}

        # Normalize inputs
        destination_address = (destination_address or '').strip()
        amount_str = (amount or '').strip()
        # Accept locale formats: if only comma present, treat as decimal separator; otherwise strip commas
        if ',' in amount_str and '.' not in amount_str:
            amount_str = amount_str.replace(',', '.')
        else:
            amount_str = amount_str.replace(',', '')
        amount_str = amount_str.replace(' ', '')

        # Robust Algorand address validation using SDK
        try:
            is_valid_addr = algo_encoding.is_valid_address(destination_address)
        except Exception:
            is_valid_addr = False
        if not is_valid_addr:
            return {"success": False, "error": "invalid_address"}

        # Validate amount is a positive decimal
        try:
            from decimal import Decimal as _D
            if _D(amount_str) <= _D('0'):
                return {"success": False, "error": "invalid_amount"}
        except Exception:
            return {"success": False, "error": "invalid_amount"}

        # Create the DB row (pending signature)
        actor_business = getattr(acct, 'business', None)
        actor_type = 'business' if actor_business else 'user'
        actor_display_name = actor_business.name if actor_business else (user.get_full_name() or user.username)
        withdrawal = USDCWithdrawal.objects.create(
            actor_user=user,
            actor_business=actor_business,
            actor_type=actor_type,
            actor_display_name=actor_display_name,
            actor_address=acct.algorand_address,
            amount=Decimal(str(amount_str)),
            destination_address=destination_address,
            status='PENDING'
        )

        # Build group [sponsor_pay, user_axfer]
        from blockchain.algorand_client import get_algod_client
        algod_client = get_algod_client()
        params = algod_client.suggested_params()
        min_fee = getattr(params, 'min_fee', 1000) or 1000

        # Sponsor payment covers the entire group fee (2 txns => 2 * min_fee)
        group_size = 2
        sp_sp = algo_txn.SuggestedParams(fee=min_fee * group_size, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
        sponsor_payment = algo_txn.PaymentTxn(
            sender=settings.ALGORAND_SPONSOR_ADDRESS,
            sp=sp_sp,
            receiver=acct.algorand_address,
            amt=0,
            note=b"Sponsored USDC withdrawal"
        )

        # User USDC transfer with 0 fee (sponsored)
        sp_user = algo_txn.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
        usdc_id = int(getattr(settings, 'ALGORAND_USDC_ASSET_ID', 0) or 0)
        aamt = int(Decimal(str(amount_str)) * Decimal(1_000_000))
        user_axfer = algo_txn.AssetTransferTxn(
            sender=acct.algorand_address,
            sp=sp_user,
            receiver=destination_address,
            amt=aamt,
            index=usdc_id,
        )

        gid = algo_txn.calculate_group_id([sponsor_payment, user_axfer])
        sponsor_payment.group = gid
        user_axfer.group = gid

        # Pre-sign sponsor via KMS
        try:
            from blockchain.kms_manager import get_kms_signer_from_settings
            signer = get_kms_signer_from_settings()
            signer.assert_matches_address(getattr(settings, "ALGORAND_SPONSOR_ADDRESS", None))
            sponsor_signed_b64 = signer.sign_transaction_msgpack(sponsor_payment)
        except Exception:
            sponsor_signed_b64 = None

        return {
            "success": True,
            "internal_id": str(withdrawal.internal_id),
            "transactions": [algo_encoding.msgpack_encode(user_axfer)],
            "sponsor_transactions": [json.dumps({"txn": algo_encoding.msgpack_encode(sponsor_payment), "signed": sponsor_signed_b64, "index": 0})],
            "group_id": (gid and __import__('base64').b64encode(gid).decode('utf-8')),
        }

    @database_sync_to_async
    def _submit(self, internal_id: str, signed_transactions, sponsor_transactions):
        from django.conf import settings
        from algosdk.v2client import algod
        import base64, json as _json, msgpack
        from algosdk import transaction as algo_txn
        from usdc_transactions.models import USDCWithdrawal
        from usdc_transactions.models_unified import UnifiedUSDCTransactionTable
        from django.utils import timezone as dj_tz

        try:
            w = USDCWithdrawal.objects.get(internal_id=internal_id)
        except USDCWithdrawal.DoesNotExist:
            return {"success": False, "error": "withdrawal_not_found"}

        if not isinstance(signed_transactions, list) or not signed_transactions:
            return {"success": False, "error": "signed_transactions_required"}

        parsed = []
        for s in (sponsor_transactions or []):
            parsed.append(_json.loads(s) if isinstance(s, str) else s)
        signed_by_idx = {}
        for e in parsed:
            idx = int(e.get('index'))
            sb64 = e.get('signed')
            if not sb64:
                return {"success": False, "error": "missing_signed_sponsor_txn"}
            stx = algo_txn.SignedTransaction.undictify(msgpack.unpackb(base64.b64decode(sb64), raw=False))
            signed_by_idx[idx] = stx

        user_signed = []
        for s in signed_transactions:
            ub = base64.b64decode(s)
            user_signed.append(algo_txn.SignedTransaction.undictify(msgpack.unpackb(ub, raw=False)))

        total = len(signed_by_idx) + len(user_signed)
        ordered = []
        u_ptr = 0
        for i in range(total):
            if i in signed_by_idx:
                ordered.append(signed_by_idx[i])
            else:
                ordered.append(user_signed[u_ptr]); u_ptr += 1

        from blockchain.algorand_client import get_algod_client
        algod_client = get_algod_client()
        try:
            txid = algod_client.send_transactions(ordered)
        except Exception as e:
            msg = str(e).lower()
            if 'transaction already in ledger' in msg:
                # Idempotency: treat as success
                # Extract txid from the last transaction we attempted to send
                txid = ordered[-1].get_txid()
                # Log it
                print(f"WS Submit: Transaction {txid} already in ledger, treating as success")
            else:
                # Re-raise legitimate errors
                raise
        ref_txid = ordered[-1].get_txid()

        # Mark withdrawal as processing (submitted)
        w.status = 'PROCESSING'
        w.updated_at = dj_tz.now()
        w.save(update_fields=['status', 'updated_at'])

        # Update/create unified row with SUBMITTED + txhash
        try:
            UnifiedUSDCTransactionTable.objects.update_or_create(
                usdc_withdrawal=w,
                defaults={
                    'transaction_id': str(w.internal_id),
                    'transaction_type': 'withdrawal',
                    'actor_user': w.actor_user,
                    'actor_business': w.actor_business,
                    'actor_type': w.actor_type,
                    'actor_display_name': w.actor_display_name,
                    'actor_address': w.actor_address,
                    'amount': w.amount,
                    'currency': 'USDC',
                    'source_address': w.actor_address,
                    'destination_address': w.destination_address,
                    'transaction_hash': ref_txid,
                    'network': 'ALGORAND',
                    'status': 'SUBMITTED',
                    'created_at': w.created_at,
                    'transaction_date': w.created_at,
                    'updated_at': dj_tz.now(),
                }
            )
        except Exception:
            pass

        # Do not send notification here; Celery will emit on confirmation (success/failure)

        return {"success": True, "txid": ref_txid, "internal_id": str(w.internal_id)}
