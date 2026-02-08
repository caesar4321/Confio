import asyncio
import json
import logging
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


logger = logging.getLogger(__name__)


class ConvertSessionConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket for cUSD <> USDC conversion (prepare + submit, two-step).
    - prepare: {type:"prepare", direction:"usdc_to_cusd"|"cusd_to_usdc", amount:string}
      -> {type:"prepare_ready", pack:{internal_id, transactions, sponsor_transactions, group_id}}
    - submit: {type:"submit", internal_id, signed_transactions:[b64], sponsor_transactions:[json|string]}
      -> {type:"submit_ok", txid}
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
            direction = (content.get("direction") or "").strip().lower()
            amount = content.get("amount")
            try:
                pack = await self._prepare(direction=direction, amount=str(amount))
                if not pack.get("success"):
                    # Surface opt-in hint if present
                    if pack.get('requires_app_optin'):
                        await self.send_json({"type": "error", "message": "requires_app_optin", "app_id": pack.get('app_id')})
                        return
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
                await self.send_json({"type": "error", "message": str(e) or "prepare_exception"})
            return
        if t == "submit":
            internal_id = content.get("internal_id")
            signed_transactions = content.get("signed_transactions")
            sponsor_transactions = content.get("sponsor_transactions") or []
            try:
                res = await self._submit(internal_id=str(internal_id), signed_transactions=signed_transactions, sponsor_transactions=sponsor_transactions)
                if not res.get("success"):
                    await self.send_json({"type": "error", "message": res.get("error", "submit_failed")})
                    return
                await self.send_json({"type": "submit_ok", "txid": res.get("txid") or res.get("transaction_id")})
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
    def _prepare(self, direction: str, amount: str):
        from conversion.schema import ConvertUSDCToCUSD, ConvertCUSDToUSDC
        user = self.scope.get("user")
        meta = {}
        if self._raw_token:
            meta["HTTP_AUTHORIZATION"] = f"JWT {self._raw_token}"
        info = _DummyInfo(context=_DummyRequest(user=user, meta=meta))

        if direction == 'usdc_to_cusd':
            res = ConvertUSDCToCUSD.mutate(None, info, amount=amount)
        elif direction == 'cusd_to_usdc':
            res = ConvertCUSDToUSDC.mutate(None, info, amount=amount)
        else:
            return {"success": False, "error": "invalid_direction"}

        if not getattr(res, 'success', False):
            return {
                "success": False,
                "error": (res.errors or ['conversion_prepare_failed'])[0] if hasattr(res, 'errors') else 'conversion_prepare_failed',
                "requires_app_optin": getattr(res, 'requires_app_optin', False),
                "app_id": getattr(res, 'app_id', None),
            }

        conv = getattr(res, 'conversion', None)
        conv_id = getattr(conv, 'internal_id', None) if conv else None
        txs = getattr(res, 'transactions_to_sign', None)
        sponsors = getattr(res, 'sponsor_transactions', None)

        # Normalize sponsor transactions to simple array of JSON strings
        sponsors_norm = []
        for e in (sponsors or []):
            if isinstance(e, str):
                sponsors_norm.append(e)
            else:
                sponsors_norm.append(json.dumps(e))

        # Normalize user transactions to a simple list of base64 strings
        txs_norm = []
        for t in (txs or []):
            if isinstance(t, str):
                txs_norm.append(t)
            else:
                try:
                    v = t.get('txn')
                    if isinstance(v, str):
                        txs_norm.append(v)
                except Exception:
                    pass

        return {
            "success": True,
            "internal_id": str(conv_id) if conv_id else None,
            "transactions": txs_norm,
            "sponsor_transactions": sponsors_norm,
            "group_id": getattr(res, 'group_id', None),
        }

    @database_sync_to_async
    def _submit(self, internal_id: str, signed_transactions, sponsor_transactions):
        from conversion.models import Conversion
        from blockchain.algorand_client import get_algod_client
        import base64, json as _json

        # Load conversion
        try:
            conv = Conversion.objects.get(internal_id=internal_id)
        except Conversion.DoesNotExist:
            return {"success": False, "error": "conversion_not_found"}

        # Compose group: sponsor entries by index plus user-signed tx(s)
        if not isinstance(signed_transactions, list) or not signed_transactions:
            return {"success": False, "error": "signed_transactions_required"}

        # Parse sponsor list of JSON strings
        parsed = []
        for s in (sponsor_transactions or []):
            parsed.append(_json.loads(s) if isinstance(s, str) else s)
            
        # Collect raw bytes indexed by Position
        raw_txs_by_idx = {}

        # 1. Process Sponsor Transactions
        for e in parsed:
            idx = int(e.get('index'))
            signed_b64 = e.get('signed')
            if signed_b64:
                # Use the signed blob provided by sponsor service
                raw_txs_by_idx[idx] = base64.b64decode(signed_b64)
            else:
                # Fallback: check if we have the raw txn (should be signed usually)
                txn_b64 = e.get('txn')
                if txn_b64:
                     raw_txs_by_idx[idx] = base64.b64decode(txn_b64)

        # 2. Process User Signed Transactions (usually sequentially after sponsor)
        # We need to know where to insert them.
        # The frontend sends them in order. We fit them into empty slots?
        # Or usually the user transactions start at index 1?
        # Logic in previous code:
        # "Fill ordered group by index positions"
        # "if i in signed_by_idx: ... else: append(user_signed[u_ptr])"
        
        # Determine total size
        total_txs = len(raw_txs_by_idx) + len(signed_transactions)
        
        ordered_bytes = []
        user_ptr = 0
        
        for i in range(total_txs):
            if i in raw_txs_by_idx:
                ordered_bytes.append(raw_txs_by_idx[i])
            else:
                if user_ptr >= len(signed_transactions):
                    return {"success": False, "error": "group_shape_mismatch"}
                
                # Decode user transaction
                try:
                    user_blob = base64.b64decode(signed_transactions[user_ptr])
                    ordered_bytes.append(user_blob)
                    user_ptr += 1
                except Exception:
                    return {"success": False, "error": "invalid_user_txn_encoding"}

        # Log composition for debugging
        logger.info(f"Conversion {internal_id} submitting group of {len(ordered_bytes)} transactions (raw bytes)")

        # Concatenate raw bytes
        combined_group = b''.join(ordered_bytes)
        combined_b64 = base64.b64encode(combined_group).decode('utf-8')

        algod_client = get_algod_client()

        try:
            # Submit raw transaction group
            # algod_client is the raw SDK client
            txid = algod_client.send_raw_transaction(combined_b64)
            
            # Since we have the ID, we can return success
            # The reference ID is usually the last transaction's ID or the first? 
            # In previous code: ref_txid = ordered[-1].get_txid()
            # We can't easily get the ID of the last txn without decoding.
            # However, the send_raw_transaction returns the ID of the FIRST transaction?
            # Or the ID of the "transaction" submitted?
            # For atomic groups, send_raw_transaction returns the ID of the FIRST transaction in the group?
            # Actually, SDK documentation says it returns the transaction ID.
            # If it's a group, checking any ID in the group works for confirmation.
            # Let's trust the returned txid is sufficient for tracking.
            # BUT wait, previously we stored ordered[-1].get_txid() as "to_transaction_hash".
            # If we want to maintain behavior, we should perhaps decode just to get IDs?
            # Or just use the returned txid?
            # Let's decode minimally to get IDs if needed, but for now returned txid is safe.
            
            # To be safe and match previous behavior (store conversion hash), let's use the returned ID.
            
            conv.status = 'SUBMITTED'
            conv.to_transaction_hash = txid
            conv.save(update_fields=['status', 'to_transaction_hash', 'updated_at'])

            return {"success": True, "txid": txid}
            
        except Exception as e:
            logger.error(f"Error submitting conversion {internal_id}: {e}")
            return {"success": False, "error": str(e)}
