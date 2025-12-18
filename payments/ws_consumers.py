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
      - {type: "prepare_request", amount: float, asset_type?: str, internal_id?: str, note?: str, recipient_business_id?: str}
      - {type: "submit_request", signed_transactions: list|jsonstr, internal_id?: str}

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
            internal_id = content.get("internal_id") or content.get("payment_id")
            note = content.get("note")
            recipient_business_id = content.get("recipient_business_id")

            if amount is None:
                await self.send_json({"type": "error", "message": "amount_required"})
                return

            try:
                pack = await self._create_prepare_pack(
                    amount=float(amount),
                    asset_type=str(asset_type),
                    internal_id=internal_id,
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
                        "internal_id": pack.get("internal_id"),
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
            internal_id = content.get("internal_id") or content.get("payment_id")
            if signed is None:
                await self.send_json({"type": "error", "message": "signed_transactions_required"})
                return
            try:
                result = await self._submit_payment(signed_transactions=signed, internal_id=internal_id)
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
    def _create_prepare_pack(self, amount, asset_type, internal_id=None, note=None, recipient_business_id=None):
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
            internal_id=internal_id,
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
            "internal_id": getattr(result, "internal_id", None),
        }

    @database_sync_to_async
    def _submit_payment(self, signed_transactions, internal_id=None):
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
            internal_id=internal_id,
        )
        return {
            "success": getattr(result, "success", False),
            "error": getattr(result, "error", None),
            "transaction_id": getattr(result, "transaction_id", None),
            "confirmed_round": getattr(result, "confirmed_round", None),
            "net_amount": getattr(result, "net_amount", None),
            "fee_amount": getattr(result, "fee_amount", None),
        }


class SendSessionConsumer(AsyncJsonWebsocketConsumer):
    """
    Ephemeral WebSocket for the Send flow (sponsored direct send).
    Prepares a 2-txn group (sponsor signed + user unsigned) and submits after client signature.
    """

    KEEPALIVE_SEC = 25
    IDLE_TIMEOUT_SEC = 60

    async def connect(self):
        user = self.scope.get("user")
        if not user or not getattr(user, "is_authenticated", False):
            print("[ws/send_session] unauthorized connect attempt")
            await self.close(code=4401)
            return

        query_string = self.scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        self._raw_token = (params.get("token", [None])[0]) or ""
        self._sponsor_txn = None  # keep last prepared sponsor txn for submit

        print(f"[ws/send_session] connect user={getattr(user, 'id', None)}")
        await self.accept()

        self._keepalive_task = asyncio.create_task(self._keepalive())
        self._idle_task = asyncio.create_task(self._idle_close())

    async def disconnect(self, code):
        print(f"[ws/send_session] disconnect code={code}")
        for t in (getattr(self, "_keepalive_task", None), getattr(self, "_idle_task", None)):
            if t:
                t.cancel()

    async def receive_json(self, content, **kwargs):
        await self._reset_idle_timer()

        msg_type = content.get("type")
        if msg_type == "ping":
            print("[ws/send_session] <- ping")
            await self.send_json({"type": "pong"})
            return

        if msg_type == "prepare_request":
            print(f"[ws/send_session] <- prepare_request content={content}")
            amount = content.get("amount")
            asset_type = content.get("asset_type") or "CUSD"
            note = content.get("note")
            recipient_address = content.get("recipient_address")
            recipient_user_id = content.get("recipient_user_id")
            recipient_phone = content.get("recipient_phone")

            if amount is None:
                await self.send_json({"type": "error", "message": "amount_required"})
                return
            if not (recipient_address or recipient_user_id or recipient_phone):
                await self.send_json({"type": "error", "message": "recipient_required"})
                return

            try:
                pack = await self._create_prepare_pack(
                    amount=float(amount),
                    asset_type=str(asset_type),
                    note=note,
                    recipient_address=recipient_address,
                    recipient_user_id=recipient_user_id,
                    recipient_phone=recipient_phone,
                )

                if not pack.get("success"):
                    print(f"[ws/send_session] prepare_failed: {pack.get('error')}")
                    await self.send_json({"type": "error", "message": pack.get("error", "prepare_failed")})
                    return

                # Normalize to a list of 2 transactions
                sponsor_txn = pack.get("sponsor_transaction")
                user_txn = pack.get("user_transaction")
                self._sponsor_txn = sponsor_txn
                transactions = [
                    {"index": 0, "type": "payment", "transaction": sponsor_txn, "signed": True, "needs_signature": False},
                    {"index": 1, "type": "asset_transfer", "transaction": user_txn, "signed": False, "needs_signature": True},
                ]

                response = {
                    "type": "prepare_ready",
                    "pack": {
                        "transactions": transactions,
                        "user_signing_indexes": [1],
                        "group_id": pack.get("group_id"),
                        "gross_amount": None,
                        "net_amount": None,
                        "fee_amount": pack.get("total_fee"),
                    },
                }
                print(f"[ws/send_session] -> prepare_ready tx_count={len(transactions)}")
                await self.send_json(response)
            except Exception as e:
                print(f"[ws/send_session] prepare_exception: {e}")
                await self.send_json({"type": "error", "message": "prepare_exception"})
            return

        if msg_type == "submit_request":
            print("[ws/send_session] <- submit_request")
            signed = content.get("signed_transactions")
            signed_sponsor_txn = content.get("signed_sponsor_txn")
            if not signed:
                await self.send_json({"type": "error", "message": "signed_transactions_required"})
                return
            try:
                # Find the user-signed txn at index 1
                user_signed = None
                try:
                    for tx in signed:
                        if int(tx.get("index", -1)) == 1:
                            user_signed = tx.get("transaction")
                            break
                except Exception:
                    pass
                if not user_signed and isinstance(signed, dict):
                    user_signed = signed.get("signed_user_txn")
                if not user_signed:
                    await self.send_json({"type": "error", "message": "signed_user_txn_required"})
                    return
                # Determine sponsor txn: prefer explicit payload, then prepped session state, else from array index 0
                sponsor_txn = signed_sponsor_txn or self._sponsor_txn
                if not sponsor_txn:
                    try:
                        for tx in signed:
                            if int(tx.get("index", -1)) == 0 and tx.get("signed"):
                                sponsor_txn = tx.get("transaction")
                                break
                    except Exception:
                        pass
                if not sponsor_txn:
                    await self.send_json({"type": "error", "message": "signed_sponsor_txn_required"})
                    return

                result = await self._submit_group(
                    signed_user_txn=user_signed,
                    signed_sponsor_txn=sponsor_txn,
                )
                if not result.get("success"):
                    print(f"[ws/send_session] submit_failed: {result.get('error')}")
                    await self.send_json({"type": "error", "message": result.get("error", "submit_failed")})
                    return
                print("[ws/send_session] -> submit_ok")
                await self.send_json({
                    "type": "submit_ok",
                    "transaction_id": result.get("transaction_id"),
                    "internal_id": result.get("internal_id"),
                    "confirmed_round": result.get("confirmed_round"),
                    "net_amount": None,
                    "fee_amount": None,
                })
            except Exception:
                print("[ws/send_session] submit_exception")
                await self.send_json({"type": "error", "message": "submit_exception"})
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
    def _create_prepare_pack(self, amount, asset_type, note=None, recipient_address=None, recipient_user_id=None, recipient_phone=None):
        from blockchain.mutations import AlgorandSponsoredSendMutation

        meta = {}
        if self._raw_token:
            meta["HTTP_AUTHORIZATION"] = f"JWT {self._raw_token}"
        user = self.scope.get("user")
        dummy_request = _DummyRequest(user=user, meta=meta)
        info = _DummyInfo(context=dummy_request)

        result = AlgorandSponsoredSendMutation.mutate(
            None,
            info,
            recipient_address=recipient_address,
            recipient_user_id=recipient_user_id,
            recipient_phone=recipient_phone,
            amount=amount,
            asset_type=asset_type,
            note=note,
        )

        return {
            "success": getattr(result, "success", False),
            "error": getattr(result, "error", None),
            "user_transaction": getattr(result, "user_transaction", None),
            "sponsor_transaction": getattr(result, "sponsor_transaction", None),
            "group_id": getattr(result, "group_id", None),
            "total_fee": getattr(result, "total_fee", None),
        }

    @database_sync_to_async
    def _submit_group(self, signed_user_txn, signed_sponsor_txn=None):
        from blockchain.mutations import SubmitSponsoredGroupMutation

        meta = {}
        if self._raw_token:
            meta["HTTP_AUTHORIZATION"] = f"JWT {self._raw_token}"
        user = self.scope.get("user")
        dummy_request = _DummyRequest(user=user, meta=meta)
        info = _DummyInfo(context=dummy_request)

        result = SubmitSponsoredGroupMutation.mutate(
            None,
            info,
            signed_user_txn=signed_user_txn,
            signed_sponsor_txn=signed_sponsor_txn,
        )

        return {
            "success": getattr(result, "success", False),
            "error": getattr(result, "error", None),
            "transaction_id": getattr(result, "transaction_id", None),
            "internal_id": getattr(result, "internal_id", None),
            "confirmed_round": getattr(result, "confirmed_round", None),
        }
