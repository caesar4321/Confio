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


class P2PSessionConsumer(AsyncJsonWebsocketConsumer):
    """
    Ephemeral WebSocket for P2P trade prepare/submit flows.
    Mirrors the Pay/Send session pattern: prepare returns unsigned user txns and
    pre-signed sponsor txns; submit signs/sends and responds immediately while
    Celery confirms on-chain and sends notifications.

    Messages (client → server):
      - {type: "ping"}
      - {type: "prepare", action: "create"|"accept"|"mark_paid"|"confirm_received"|"cancel", trade_id: string, amount?: number, asset_type?: string, payment_ref?: string}
      - {type: "submit", action: "create"|"accept"|"mark_paid"|"confirm_received"|"cancel", trade_id: string, signed_user_txns?: [base64], signed_user_txn?: base64, sponsor_transactions: [json|string]}

    Messages (server → client):
      - {type: "pong"}
      - {type: "server_ping"}
      - {type: "prepare_ready", action, pack: { user_transactions, sponsor_transactions, group_id, trade_id }}
      - {type: "submit_ok", action, txid}
      - {type: "error", message}
    """

    KEEPALIVE_SEC = 25
    IDLE_TIMEOUT_SEC = 60

    async def connect(self):
        user = self.scope.get("user")
        if not user or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        query_string = self.scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
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
        msg_type = content.get("type")
        if msg_type == "ping":
            await self.send_json({"type": "pong"})
            return

        if msg_type == "prepare":
            action = (content.get("action") or "").strip()
            trade_id = content.get("trade_id")
            amount = content.get("amount")
            asset_type = content.get("asset_type") or "CUSD"
            payment_ref = content.get("payment_ref")
            reason = content.get("reason")

            try:
                pack = await self._prepare(action=action, trade_id=trade_id, amount=amount, asset_type=asset_type, payment_ref=payment_ref, reason=reason)
                if not pack.get("success"):
                    await self.send_json({"type": "error", "message": pack.get("error", "prepare_failed")})
                    return
                await self.send_json({
                    "type": "prepare_ready",
                    "action": action,
                    "pack": {
                        "user_transactions": pack.get("user_transactions") or [],
                        "sponsor_transactions": pack.get("sponsor_transactions") or [],
                        "group_id": pack.get("group_id"),
                        "trade_id": pack.get("trade_id"),
                    },
                })
            except Exception:
                await self.send_json({"type": "error", "message": "prepare_exception"})
            return

        if msg_type == "submit":
            action = (content.get("action") or "").strip()
            trade_id = content.get("trade_id")
            signed_user_txns = content.get("signed_user_txns")  # list for 2-txn user flows
            signed_user_txn = content.get("signed_user_txn")    # single appcall for accept/mark/cancel/confirm
            sponsor_transactions = content.get("sponsor_transactions") or []

            try:
                res = await self._submit(action=action, trade_id=trade_id, signed_user_txns=signed_user_txns, signed_user_txn=signed_user_txn, sponsor_transactions=sponsor_transactions)
                if not res.get("success"):
                    await self.send_json({"type": "error", "message": res.get("error", "submit_failed"), "action": action})
                    return
                await self.send_json({
                    "type": "submit_ok",
                    "action": action,
                    "txid": res.get("txid") or res.get("transaction_id"),
                })
            except Exception as e:
                # Surface the exception to the client for debugging
                try:
                    msg = str(e) or "submit_exception"
                except Exception:
                    msg = "submit_exception"
                await self.send_json({"type": "error", "message": msg, "action": action})
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
    def _prepare(self, action, trade_id=None, amount=None, asset_type="CUSD", payment_ref=None, reason=None):
        from blockchain.p2p_trade_mutations import (
            PrepareP2PCreateTrade,
            PrepareP2pAcceptTrade,
            PrepareP2PMarkPaid,
            PrepareP2PCancel,
            PrepareP2PConfirmReceived,
            PrepareP2POpenDispute,
        )

        meta = {}
        if self._raw_token:
            meta["HTTP_AUTHORIZATION"] = f"JWT {self._raw_token}"
        user = self.scope.get("user")
        info = _DummyInfo(context=_DummyRequest(user=user, meta=meta))

        if action == "create":
            result = PrepareP2PCreateTrade.mutate(None, info, trade_id=trade_id, amount=float(amount), asset_type=asset_type)
        elif action == "accept":
            result = PrepareP2pAcceptTrade.mutate(None, info, trade_id=trade_id)
        elif action == "mark_paid":
            result = PrepareP2PMarkPaid.mutate(None, info, trade_id=trade_id, payment_ref=payment_ref or "")
        elif action == "confirm_received":
            result = PrepareP2PConfirmReceived.mutate(None, info, trade_id=trade_id)
        elif action == "cancel":
            result = PrepareP2PCancel.mutate(None, info, trade_id=trade_id)
        elif action == "open_dispute":
            result = PrepareP2POpenDispute.mutate(None, info, trade_id=trade_id, reason=(reason or ""))
        else:
            return {"success": False, "error": "unknown_action"}

        return {
            "success": getattr(result, "success", False),
            "error": getattr(result, "error", None),
            "user_transactions": getattr(result, "user_transactions", None),
            "sponsor_transactions": [
                {"txn": e.txn, "index": e.index} if hasattr(e, "txn") else e for e in (getattr(result, "sponsor_transactions", []) or [])
            ],
            "group_id": getattr(result, "group_id", None),
            "trade_id": getattr(result, "trade_id", trade_id),
        }

    @database_sync_to_async
    def _submit(self, action, trade_id, signed_user_txns=None, signed_user_txn=None, sponsor_transactions=None):
        from blockchain.p2p_trade_mutations import (
            SubmitP2PCreateTrade,
            SubmitP2pAcceptTrade,
            MarkP2PTradePaid,
            CancelP2PTrade,
            ConfirmP2PTradeReceived,
            SubmitP2POpenDispute,
        )
        import json as _json

        meta = {}
        if self._raw_token:
            meta["HTTP_AUTHORIZATION"] = f"JWT {self._raw_token}"
        user = self.scope.get("user")
        info = _DummyInfo(context=_DummyRequest(user=user, meta=meta))

        # Normalize sponsor_transactions to list of JSON strings
        s_list = sponsor_transactions or []
        norm = []
        for e in s_list:
            if isinstance(e, str):
                norm.append(e)
            else:
                norm.append(_json.dumps(e))

        if action == "create":
            if not signed_user_txns or not isinstance(signed_user_txns, list):
                return {"success": False, "error": "signed_user_txns_required"}
            result = SubmitP2PCreateTrade.mutate(None, info, signed_user_txns=signed_user_txns, sponsor_transactions=norm, trade_id=trade_id)
        elif action == "accept":
            if not signed_user_txn:
                return {"success": False, "error": "signed_user_txn_required"}
            result = SubmitP2pAcceptTrade.mutate(None, info, trade_id=trade_id, signed_user_txn=signed_user_txn, sponsor_transactions=norm)
        elif action == "mark_paid":
            if not signed_user_txn:
                return {"success": False, "error": "signed_user_txn_required"}
            result = MarkP2PTradePaid.mutate(None, info, trade_id=trade_id, payment_ref="", signed_user_txn=signed_user_txn, sponsor_transactions=norm)
        elif action == "confirm_received":
            if not signed_user_txn:
                return {"success": False, "error": "signed_user_txn_required"}
            result = ConfirmP2PTradeReceived.mutate(None, info, trade_id=trade_id, signed_user_txn=signed_user_txn, sponsor_transactions=norm)
        elif action == "cancel":
            if not signed_user_txn:
                return {"success": False, "error": "signed_user_txn_required"}
            result = CancelP2PTrade.mutate(None, info, trade_id=trade_id, signed_user_txn=signed_user_txn, sponsor_transactions=norm)
        elif action == "open_dispute":
            if not signed_user_txn:
                return {"success": False, "error": "signed_user_txn_required"}
            result = SubmitP2POpenDispute.mutate(None, info, trade_id=trade_id, signed_user_txn=signed_user_txn, sponsor_transactions=norm, reason="")
        else:
            return {"success": False, "error": "unknown_action"}

        return {
            "success": getattr(result, "success", False),
            "error": getattr(result, "error", None),
            "txid": getattr(result, "txid", None),
            "transaction_id": getattr(result, "transaction_id", None),
        }
