import asyncio
from types import SimpleNamespace
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


class PaySessionConsumer(AsyncJsonWebsocketConsumer):
    """
    Ephemeral WebSocket used during the Pay/Send flow to precompute and push
    the payment "prepare" pack to the client. Keep it simple: authenticate via
    existing JWT (?token=) and reuse existing GraphQL mutation logic to build
    the transaction pack.

    Messages (client → server):
      - {type: "ping"}
      - {type: "prepare_request", amount: float, asset_type?: str, payment_id?: str, note?: str, recipient_business_id?: str}
      - {type: "submit_request", signed_transactions: list|jsonstr, payment_id?: str}

    Messages (server → client):
      - {type: "pong"}
      - {type: "server_ping"}
      - {type: "prepare_ready", pack: {...}, expires_at?: number}
      - {type: "error", message: str}
    """

    KEEPALIVE_SEC = 25
    IDLE_TIMEOUT_SEC = 60

    async def connect(self):
        # Require authenticated user from JWTAuthMiddleware
        user = self.scope.get("user")
        if not user or not getattr(user, "is_authenticated", False):
            print("[ws/pay_session] unauthorized connect attempt")
            await self.close(code=4401)
            return

        # Extract raw token from query to build Authorization header for GraphQL utils
        query_string = self.scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        self._raw_token = (params.get("token", [None])[0]) or ""

        print(f"[ws/pay_session] connect user={getattr(user, 'id', None)}")
        # Accept connection (no subprotocol required for RN WebSocket)
        await self.accept()

        # Keep server-side ping and idle timeout
        self._keepalive_task = asyncio.create_task(self._keepalive())
        self._idle_task = asyncio.create_task(self._idle_close())

    async def disconnect(self, code):
        print(f"[ws/pay_session] disconnect code={code}")
        for t in (getattr(self, "_keepalive_task", None), getattr(self, "_idle_task", None)):
            if t:
                t.cancel()

    async def receive_json(self, content, **kwargs):
        # Reset idle timer on any activity
        await self._reset_idle_timer()

        msg_type = content.get("type")
        if msg_type == "ping":
            print("[ws/pay_session] <- ping")
            await self.send_json({"type": "pong"})
            return

        if msg_type == "prepare_request":
            print(f"[ws/pay_session] <- prepare_request content={content}")
            # Extract fields
            amount = content.get("amount")
            asset_type = content.get("asset_type") or "CUSD"
            payment_id = content.get("payment_id")
            note = content.get("note")
            recipient_business_id = content.get("recipient_business_id")

            if amount is None:
                await self.send_json({"type": "error", "message": "amount_required"})
                return

            try:
                pack = await self._create_prepare_pack(
                    amount=float(amount),
                    asset_type=str(asset_type),
                    payment_id=payment_id,
                    note=note,
                    recipient_business_id=recipient_business_id,
                )

                if not pack.get("success"):
                    print(f"[ws/pay_session] prepare_failed: {pack.get('error')}")
                    await self.send_json({"type": "error", "message": pack.get("error", "prepare_failed")})
                    return

                # Shape a compact pack for client
                # Normalize transactions to list if mutation returned JSON string
                transactions = pack.get("transactions")
                if isinstance(transactions, str):
                    import json as _json
                    try:
                        transactions = _json.loads(transactions)
                    except Exception:
                        transactions = None

                response = {
                    "type": "prepare_ready",
                    "pack": {
                        "transactions": transactions,
                        "user_signing_indexes": pack.get("user_signing_indexes"),
                        "group_id": pack.get("group_id"),
                        "gross_amount": pack.get("gross_amount"),
                        "net_amount": pack.get("net_amount"),
                        "fee_amount": pack.get("fee_amount"),
                        "payment_id": pack.get("payment_id"),
                    },
                }
                if not isinstance(response["pack"].get("transactions"), list):
                    print("[ws/pay_session] invalid_prepare_pack: transactions is not a list")
                    await self.send_json({"type": "error", "message": "invalid_prepare_pack"})
                    return
                print(f"[ws/pay_session] -> prepare_ready tx_count={len(response['pack']['transactions'])}")
                await self.send_json(response)
            except Exception as e:
                print(f"[ws/pay_session] prepare_exception: {e}")
                await self.send_json({"type": "error", "message": "prepare_exception"})
            return

        if msg_type == "submit_request":
            print("[ws/pay_session] <- submit_request")
            signed = content.get("signed_transactions")
            payment_id = content.get("payment_id")
            if signed is None:
                await self.send_json({"type": "error", "message": "signed_transactions_required"})
                return
            try:
                result = await self._submit_payment(signed_transactions=signed, payment_id=payment_id)
                if not result.get("success"):
                    print(f"[ws/pay_session] submit_failed: {result.get('error')}")
                    await self.send_json({"type": "error", "message": result.get("error", "submit_failed")})
                    return
                print("[ws/pay_session] -> submit_ok")
                await self.send_json({
                    "type": "submit_ok",
                    "transaction_id": result.get("transaction_id"),
                    "confirmed_round": result.get("confirmed_round"),
                    "net_amount": result.get("net_amount"),
                    "fee_amount": result.get("fee_amount"),
                })
            except Exception:
                print("[ws/pay_session] submit_exception")
                await self.send_json({"type": "error", "message": "submit_exception"})
            return

        # Unknown message type is ignored silently to keep protocol stable

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
    def _create_prepare_pack(self, amount, asset_type, payment_id=None, note=None, recipient_business_id=None):
        """
        Call existing GraphQL mutation to build the sponsored payment transactions,
        reusing business context validation. We emulate a GraphQL info/context.
        """
        from blockchain.payment_mutations import CreateSponsoredPaymentMutation

        # Build a fake Authorization header so jwt_context utils work
        meta = {}
        if self._raw_token:
            meta["HTTP_AUTHORIZATION"] = f"JWT {self._raw_token}"
        if recipient_business_id:
            # Payment mutation reads this header as a fallback
            meta["HTTP_X_RECIPIENT_BUSINESS_ID"] = str(recipient_business_id)

        user = self.scope.get("user")
        dummy_request = _DummyRequest(user=user, meta=meta)
        info = _DummyInfo(context=dummy_request)

        result = CreateSponsoredPaymentMutation.mutate(
            None,
            info,
            amount=amount,
            asset_type=asset_type,
            payment_id=payment_id,
            note=note,
            create_receipt=False,
        )

        # Graphene returns a mutation instance; extract fields
        return {
            "success": getattr(result, "success", False),
            "error": getattr(result, "error", None),
            "transactions": getattr(result, "transactions", None),
            "user_signing_indexes": getattr(result, "user_signing_indexes", None),
            "group_id": getattr(result, "group_id", None),
            "gross_amount": getattr(result, "gross_amount", None),
            "net_amount": getattr(result, "net_amount", None),
            "fee_amount": getattr(result, "fee_amount", None),
            "payment_id": getattr(result, "payment_id", None),
        }

    @database_sync_to_async
    def _submit_payment(self, signed_transactions, payment_id=None):
        from blockchain.payment_mutations import SubmitSponsoredPaymentMutation
        import json

        # Normalize signed_transactions to JSON string expected by mutation
        if isinstance(signed_transactions, (dict, list)):
            signed_str = json.dumps(signed_transactions)
        elif isinstance(signed_transactions, str):
            signed_str = signed_transactions
        else:
            signed_str = json.dumps(signed_transactions)

        user = self.scope.get("user")
        meta = {}
        if self._raw_token:
            meta["HTTP_AUTHORIZATION"] = f"JWT {self._raw_token}"
        dummy_request = _DummyRequest(user=user, meta=meta)
        info = _DummyInfo(context=dummy_request)

        result = SubmitSponsoredPaymentMutation.mutate(
            None,
            info,
            signed_transactions=signed_str,
            payment_id=payment_id,
        )
        return {
            "success": getattr(result, "success", False),
            "error": getattr(result, "error", None),
            "transaction_id": getattr(result, "transaction_id", None),
            "confirmed_round": getattr(result, "confirmed_round", None),
            "net_amount": getattr(result, "net_amount", None),
            "fee_amount": getattr(result, "fee_amount", None),
        }
