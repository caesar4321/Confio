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


class ConvertSessionConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket for cUSD <> USDC conversion (prepare + submit, two-step).
    - prepare: {type:"prepare", direction:"usdc_to_cusd"|"cusd_to_usdc", amount:string}
      -> {type:"prepare_ready", pack:{conversion_id, transactions, sponsor_transactions, group_id}}
    - submit: {type:"submit", conversion_id, signed_transactions:[b64], sponsor_transactions:[json|string]}
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
                        "conversion_id": pack.get("conversion_id"),
                        "transactions": pack.get("transactions"),
                        "sponsor_transactions": pack.get("sponsor_transactions"),
                        "group_id": pack.get("group_id"),
                    },
                })
            except Exception as e:
                await self.send_json({"type": "error", "message": str(e) or "prepare_exception"})
            return
        if t == "submit":
            conversion_id = content.get("conversion_id")
            signed_transactions = content.get("signed_transactions")
            sponsor_transactions = content.get("sponsor_transactions") or []
            try:
                res = await self._submit(conversion_id=str(conversion_id), signed_transactions=signed_transactions, sponsor_transactions=sponsor_transactions)
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
        conv_id = getattr(conv, 'id', None) if conv else None
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
            "conversion_id": str(conv_id) if conv_id else None,
            "transactions": txs_norm,
            "sponsor_transactions": sponsors_norm,
            "group_id": getattr(res, 'group_id', None),
        }

    @database_sync_to_async
    def _submit(self, conversion_id: str, signed_transactions, sponsor_transactions):
        from conversion.models import Conversion
        from algosdk.v2client import algod
        import base64, json as _json, msgpack
        from algosdk import transaction as algo_txn
        from django.conf import settings

        # Load conversion
        try:
            conv = Conversion.objects.get(id=conversion_id)
        except Conversion.DoesNotExist:
            return {"success": False, "error": "conversion_not_found"}

        # Compose group: sponsor entries by index plus user-signed tx(s)
        if not isinstance(signed_transactions, list) or not signed_transactions:
            return {"success": False, "error": "signed_transactions_required"}

        # Parse sponsor list of JSON strings
        parsed = []
        for s in (sponsor_transactions or []):
            parsed.append(_json.loads(s) if isinstance(s, str) else s)
        signed_by_idx = {}

        # If sponsor provided signatures, we still pass raw as signed
        for e in parsed:
            idx = int(e.get('index'))
            signed_b64 = e.get('signed')
            if signed_b64:
                sb = base64.b64decode(signed_b64)
                stx = algo_txn.SignedTransaction.undictify(msgpack.unpackb(sb, raw=False))
                signed_by_idx[idx] = stx
            else:
                # Fallback: allow unsigned only if user provided signed counterpart for same index (should not happen)
                b = base64.b64decode(e.get('txn'))
                try:
                    stx = algo_txn.SignedTransaction.undictify(msgpack.unpackb(b, raw=False))
                    signed_by_idx[idx] = stx
                except Exception:
                    return {"success": False, "error": "missing_signed_sponsor_txn"}

        # User signed one or more txns; usually index 1
        user_signed = []
        for s in signed_transactions:
            try:
                ub = base64.b64decode(s)
                user_signed.append(algo_txn.SignedTransaction.undictify(msgpack.unpackb(ub, raw=False)))
            except Exception:
                return {"success": False, "error": "invalid_signed_txn"}

        # Determine group size from sponsor count + user tx count
        total = len(signed_by_idx) + len(user_signed)
        # Fill ordered group by index positions
        ordered = []
        u_ptr = 0
        for i in range(total):
            if i in signed_by_idx:
                ordered.append(signed_by_idx[i])
            else:
                if u_ptr >= len(user_signed):
                    return {"success": False, "error": "group_shape_mismatch"}
                ordered.append(user_signed[u_ptr])
                u_ptr += 1

        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
        txid = algod_client.send_transactions(ordered)
        ref_txid = ordered[-1].get_txid()

        # Mark conversion as SUBMITTED and store txid
        conv.status = 'SUBMITTED'
        conv.to_transaction_hash = ref_txid
        conv.save(update_fields=['status', 'to_transaction_hash', 'updated_at'])

        return {"success": True, "txid": ref_txid}
