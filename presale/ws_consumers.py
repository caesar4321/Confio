import asyncio
import json
from urllib.parse import parse_qs

import logging
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
      - {type:"submit_request", internal_id: string, signed_transactions: list, sponsor_transactions?: list}

    Server → Client:
      - {type:"pong"}
      - {type:"server_ping"}
      - {type:"prepare_ready", pack:{internal_id, transactions, sponsor_transactions, user_signing_indexes, group_id}}
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
        try:
            logging.getLogger(__name__).info(f"[PRESALE][WS] receive_json type={t}")
        except Exception:
            pass
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
                platform = content.get("platform", "")
                pack = await self._optin_prepare(platform)
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
                platform = content.get("platform", "")
                try:
                    logging.getLogger(__name__).info(f"[PRESALE][WS] prepare_request amount={amount} platform={platform}")
                except Exception:
                    pass
                pack = await self._prepare(amount, platform)
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
                        "internal_id": pack.get("purchase_id"),
                        "purchase_id": pack.get("purchase_id"),  # backward compat
                        "transactions": pack.get("transactions"),
                        "sponsor_transactions": pack.get("sponsor_transactions"),
                        "user_signing_indexes": pack.get("user_signing_indexes", [1]),
                        "group_id": pack.get("group_id"),
                        "sponsor_topup": pack.get("sponsor_topup"),
                    },
                })
            except Exception as e:
                await self.send_json({"type": "error", "message": str(e) or "prepare_exception"})
            return
        if t == "submit_request":
            try:
                # Accept internal_id first, fallback to purchase_id for backward compatibility
                internal_id = content.get("internal_id") or content.get("purchase_id")
                signed_transactions = content.get("signed_transactions")
                sponsor_transactions = content.get("sponsor_transactions") or []
                res = await self._submit(internal_id, signed_transactions, sponsor_transactions)
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

    def _get_active_account(self):
        """
        Resolve the currently active account from the JWT context on the WebSocket scope.
        Falls back to the primary personal account if the requested context is missing.
        """
        from users.models import Account

        user = self.scope.get("user")
        ctx = self.scope.get("account_context") or {}
        try:
            account_type = str(ctx.get("account_type") or "personal").lower()
        except Exception:
            account_type = "personal"
        try:
            account_index = int(ctx.get("account_index") or 0)
        except Exception:
            account_index = 0

        account = Account.objects.filter(
            user=user,
            account_type=account_type,
            account_index=account_index,
            deleted_at__isnull=True,
        ).first()

        if not account and account_type != "personal":
            account = Account.objects.filter(
                user=user, account_type="personal", deleted_at__isnull=True
            ).first()

        # Lightweight log for debugging which account context is being used
        try:
            logging.getLogger(__name__).info(
                f"[PRESALE][WS] account_context type={account_type} index={account_index} resolved={getattr(account, 'algorand_address', None)}"
            )
        except Exception:
            pass

        return account

    @database_sync_to_async
    def _prepare(self, amount, platform: str = ""):
        from decimal import Decimal
        from django.utils import timezone
        from presale.models import PresalePhase, PresalePurchase, UserPresaleLimit, PresaleSettings
        from blockchain.presale_transaction_builder import PresaleTransactionBuilder
        from blockchain.algorand_account_manager import AlgorandAccountManager
        from algosdk.v2client import algod as _algod

        user = self.scope.get("user")

        # Geo-blocking check
        from .geo_utils import check_presale_eligibility
        is_eligible, error_msg = check_presale_eligibility(user)
        if not is_eligible:
            return {"success": False, "error": error_msg}

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
        account = self._get_active_account()
        if not account or not account.algorand_address or len(account.algorand_address) != 58:
            return {"success": False, "error": "no_algorand_address"}

        # BLOCK V1 USERS: require updated app (Keyless V2 migration)
        if not getattr(account, 'is_keyless_migrated', False):
            return {"success": False, "error": "Actualiza tu app para participar en la preventa."}

        # BLOCK ANDROID WITHOUT GOOGLE DRIVE BACKUP (Safety Check)
        # Uses Platform.OS sent from client for reliable device detection
        is_android = str(platform).lower() == 'android'
        if getattr(user, 'backup_provider', '') != 'google_drive' and is_android:
            return {
                "success": False, 
                "error": "Por favor, realiza un respaldo en Google Drive para proteger tu cuenta antes de participar."
            }


        # Compute CONFIO amount (phase pricing uses cUSD per token)
        confio_amount = (cusd_amount / phase.price_per_token).quantize(Decimal('0.000001'))
        cusd_base = int(cusd_amount * 10**6)

        # Guard-rail: ensure the active account has enough cUSD before we even build the group
        try:
            algod_client = _algod.AlgodClient(AlgorandAccountManager.ALGOD_TOKEN, AlgorandAccountManager.ALGOD_ADDRESS)
            acct = algod_client.account_info(account.algorand_address)
            assets = acct.get('assets') or []
            cusd_balance = 0
            for a in assets:
                if int(a.get('asset-id') or 0) == int(getattr(AlgorandAccountManager, 'CUSD_ASSET_ID', 0) or 0):
                    cusd_balance = int(a.get('amount') or 0)
                    break
            if cusd_balance < cusd_base:
                try:
                    logging.getLogger(__name__).warning(
                        f"[PRESALE][WS][PREPARE] insufficient cUSD bal={cusd_balance} need={cusd_base} addr={account.algorand_address}"
                    )
                except Exception:
                    pass
                return {"success": False, "error": "insufficient_cusd_balance", "balance": cusd_balance, "needed": cusd_base}
        except Exception:
            # If balance check fails, fall through to let caller handle downstream errors
            pass

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
        tx_pack = builder.build_buy_group(account.algorand_address, cusd_base)
        # Persist server-signed sponsor txns alongside purchase for reliable submit
        try:
            import json as _json
            purchase.notes = _json.dumps({
                'sponsor_transactions': tx_pack.get('sponsor_transactions') or [],
                'group_id': tx_pack.get('group_id'),
            })
            purchase.save(update_fields=['notes'])
        except Exception:
            pass
        # Log sponsor bump and appcall details for observability (INFO level)
        try:
            logger = logging.getLogger(__name__)
            from algosdk import encoding as _enc
            sp0 = next((s for s in (tx_pack.get('sponsor_transactions') or []) if int(s.get('index',-1)) == 0), None)
        except Exception:
            pass
        # Create UnifiedTransactionTable entry for this presale purchase
        from users.models_unified import UnifiedTransactionTable
        try:
            UnifiedTransactionTable.objects.create(
                transaction_type='presale',
                internal_id=purchase.internal_id,
                amount=str(purchase.cusd_amount),
                token_type='CUSD',
                status='processing',
                transaction_hash='',
                from_address=purchase.from_address,
                to_address='',
                presale_purchase=purchase,
            )
        except Exception as e:
            logger.error(f"[PRESALE][WS] Failed to create UnifiedTransactionTable entry: {e}")
            if sp0 and sp0.get('txn'):
                stx = _enc.msgpack_decode(sp0['txn'])
                recv = getattr(stx, 'receiver', None)
                amt = int(getattr(stx, 'amt', 0) or 0)
                fee = int(getattr(stx, 'fee', 0) or 0)
                logger.info(f"[PRESALE][WS][PREPARE] sponsor0 receiver={recv} amt={amt} fee={fee}")
            sp2 = next((s for s in (tx_pack.get('sponsor_transactions') or []) if int(s.get('index',-1)) == 2), None)
            if sp2 and sp2.get('txn'):
                atx = _enc.msgpack_decode(sp2['txn'])
                accs = getattr(atx, 'accounts', None)
                logger.info(f"[PRESALE][WS][PREPARE] appcall accounts={accs}")
        except Exception:
            pass
        try:
            from algosdk import encoding as _enc
            sp0 = next((s for s in (tx_pack.get('sponsor_transactions') or []) if int(s.get('index',-1)) == 0), None)
            if sp0 and sp0.get('txn'):
                stx = _enc.msgpack_decode(sp0['txn'])
                print(f"[PRESALE][DEBUG] sponsor0 -> recv={getattr(stx,'receiver',None)} amt={getattr(stx,'amt',None)} fee={getattr(stx,'fee',None)}")
        except Exception:
            pass
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
            "purchase_id": str(purchase.internal_id),
            "transactions": transactions,
            "sponsor_transactions": sponsors,  # raw for debugging/clients that need structure
            "user_signing_indexes": [1],
            "group_id": tx_pack.get('group_id'),
        }

    @database_sync_to_async
    def _optin_prepare(self, platform: str = ""):
        from users.models import Account
        from blockchain.presale_transaction_builder import PresaleTransactionBuilder
        from blockchain.algorand_account_manager import AlgorandAccountManager
        from algosdk.v2client import algod as _algod
        from algosdk import mnemonic as _mn
        from algosdk.transaction import PaymentTxn as _Pay
        import logging as _log

        user = self.scope.get("user")
        account = self._get_active_account()
        if not account or not account.algorand_address or len(account.algorand_address) != 58:
            return {"success": False, "error": "no_algorand_address"}

        # BLOCK V1 USERS: require updated app (Keyless V2 migration)
        if not getattr(account, 'is_keyless_migrated', False):
            return {"success": False, "error": "Actualiza tu app para participar en la preventa."}

        # BLOCK ANDROID WITHOUT GOOGLE DRIVE BACKUP (Safety Check)
        # Uses Platform.OS sent from client for reliable device detection
        backup_provider = getattr(user, 'backup_provider', '')
        is_android = str(platform).lower() == 'android'
        _log.getLogger(__name__).info(
            f"[PRESALE][WS][OPTIN_PREPARE] Backup check: backup_provider={backup_provider}, platform={platform}, is_android={is_android}"
        )
        if backup_provider != 'google_drive' and is_android:
            _log.getLogger(__name__).warning(
                f"[PRESALE][WS][OPTIN_PREPARE] BLOCKED: Android user without Google Drive backup"
            )
            return {
                "success": False, 
                "error": "Por favor, realiza un respaldo en Google Drive para proteger tu cuenta antes de participar."
            }

        # Ensure user's ALGO balance can cover app opt-in MBR; top-up if needed (standalone)
        try:
            algod_client = _algod.AlgodClient(AlgorandAccountManager.ALGOD_TOKEN, AlgorandAccountManager.ALGOD_ADDRESS)
            acct = algod_client.account_info(account.algorand_address)
            bal = int(acct.get('amount') or 0)
            minb = int(acct.get('min-balance') or 0)
            SAFETY_BUFFER = 250_000
            target = max(minb + SAFETY_BUFFER, 0)
            fund = max(target - bal, 0)
            if fund > 0 and fund < 200_000:
                fund = 200_000
            if fund > 0:
                sp = algod_client.suggested_params(); sp.flat_fee = True; sp.fee = max(getattr(sp, 'min_fee', 1000) or 1000, 1000)
                sponsor_sk = _mn.to_private_key(AlgorandAccountManager.SPONSOR_MNEMONIC)
                pay = _Pay(sender=AlgorandAccountManager.SPONSOR_ADDRESS, sp=sp, receiver=account.algorand_address, amt=int(fund))
                stx = pay.sign(sponsor_sk)
                txid = algod_client.send_transaction(stx)
                # Do not wait for confirmation here
                _log.getLogger(__name__).info(f"[PRESALE][WS][OPTIN_PREPARE] prefund user={account.algorand_address} amt={fund}")
        except Exception:
            pass

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

        # Log sponsor top-up details for opt-in
        try:
            import logging as _log
            from algosdk import encoding as _enc
            sp0 = next((s for s in sponsors if int(s.get('index',-1)) == 0), None)
            if sp0 and sp0.get('txn'):
                stx = _enc.msgpack_decode(sp0['txn'])
                recv = getattr(stx, 'receiver', None)
                amt = int(getattr(stx, 'amt', 0) or 0)
                fee = int(getattr(stx, 'fee', 0) or 0)
                _log.getLogger(__name__).info(f"[PRESALE][WS][OPTIN_PREPARE] sponsor0 receiver={recv} amt={amt} fee={fee}")
        except Exception:
            pass

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
        account = self._get_active_account()
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
        # Do not wait for confirmation in request path

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
        try:
            _wfc(algod_client, txid, 4)
        except Exception:
            # Best effort: even if confirmation wait fails, proceed
            pass
        return {"success": True, "txid": txid}

    @database_sync_to_async
    def _submit(self, purchase_id, signed_transactions, sponsor_transactions):
        from presale.models import PresalePurchase
        from algosdk.v2client import algod
        import base64
        import msgpack
        from django.conf import settings as _dj_settings

        # Load purchase
        try:
            purchase = PresalePurchase.objects.get(internal_id=purchase_id)
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

        # Always log entry and counts
        try:
            __import__('logging').getLogger(__name__).info(
                f"[PRESALE][WS][SUBMIT] begin purchase_id={purchase_id} signed_count={len(signed_transactions)} sponsors_count={len(sponsor_transactions or [])}"
            )
        except Exception:
            pass

        # Preflight: ensure user is opted into presale app; otherwise request opt-in first
        try:
            app_id = int(getattr(_dj_settings, 'ALGORAND_PRESALE_APP_ID', 0) or 0)
            if app_id:
                from blockchain.algorand_account_manager import AlgorandAccountManager
                algod_client_pf = algod.AlgodClient(
                    AlgorandAccountManager.ALGOD_TOKEN,
                    AlgorandAccountManager.ALGOD_ADDRESS,
                )
                acct_pf = algod_client_pf.account_info(purchase.from_address)
                opted = any(int(ls.get('id') or 0) == app_id for ls in (acct_pf.get('apps-local-state') or []))
                if not opted:
                    return {"success": False, "error": "requires_presale_app_optin"}
        except Exception:
            # If preflight fails, continue; typical path returns above when not opted
            pass

        # Prefer server-signed sponsor entries persisted at prepare; fallback to client, then rebuild
        try:
            import json as _json
            if purchase.notes:
                _notes = _json.loads(purchase.notes)
                for e in (_notes.get('sponsor_transactions') or []):
                    idx = int(e.get('index'))
                    signed = e.get('signed')
                    raw = e.get('txn')
                    if idx == 0:
                        sponsor0_b64 = signed or raw
                    elif idx == 2:
                        sponsor2_b64 = signed or raw
        except Exception:
            pass

        if (not sponsor0_b64) or (not sponsor2_b64):
            try:
                for e in (sponsor_transactions or []):
                    if isinstance(e, str):
                        e = json.loads(e)
                    idx = int(e.get('index'))
                    signed = e.get('signed')
                    raw = e.get('txn')
                    if idx == 0:
                        sponsor0_b64 = sponsor0_b64 or (signed or raw)
                    elif idx == 2:
                        sponsor2_b64 = sponsor2_b64 or (signed or raw)
            except Exception:
                pass

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
            # Always decode user-signed using raw msgpack dict to confirm sender; self-heal DB/sponsors if needed
            import base64 as _b64lib, msgpack as _mp
            from algosdk import encoding as _enc
            def _b64_bytes(s: str) -> bytes:
                missing = len(s) % 4
                if missing:
                    s += '=' * (4 - missing)
                return _b64lib.b64decode(s)
            def _tx_dict(b64s: str):
                try:
                    raw = _b64_bytes(b64s)
                    d = _mp.unpackb(raw, raw=True)
                    if isinstance(d, dict) and b'txn' in d:
                        d = d[b'txn']
                    return d if isinstance(d, dict) else None
                except Exception:
                    return None
            def _addr_from_key(pubkey: bytes) -> str:
                try:
                    return _enc.encode_address(pubkey)
                except Exception:
                    return None
            t1d = _tx_dict(user_signed_b64)
            user_sender_check = _addr_from_key(t1d.get(b'snd')) if t1d else None
            __import__('logging').getLogger(__name__).info(
                f"[PRESALE][WS][SUBMIT] USER sender={user_sender_check} expected={purchase.from_address}"
            )
            if purchase.from_address and user_sender_check and user_sender_check != purchase.from_address:
                # Update purchase to actual sender and rebuild sponsors so accounts align
                try:
                    purchase.from_address = user_sender_check
                    purchase.save(update_fields=['from_address'])
                    __import__('logging').getLogger(__name__).warning(
                        f"[PRESALE][WS][SUBMIT] Self-heal: updated purchase.from_address to {user_sender_check}"
                    )
                except Exception:
                    pass
                try:
                    from blockchain.presale_transaction_builder import PresaleTransactionBuilder
                    builder = PresaleTransactionBuilder()
                    cusd_base = int(purchase.cusd_amount * 10**6)
                    pack_fix = builder.build_buy_group(purchase.from_address, cusd_base)
                    sp_list = pack_fix.get('sponsor_transactions') or []
                    sponsor0_b64 = None; sponsor2_b64 = None
                    for e in sp_list:
                        if int(e.get('index')) == 0:
                            sponsor0_b64 = e.get('signed') or e.get('txn')
                        elif int(e.get('index')) == 2:
                            sponsor2_b64 = e.get('signed') or e.get('txn')
                    __import__('logging').getLogger(__name__).info(
                        f"[PRESALE][WS][SUBMIT] Rebuilt sponsors after sender update; have0={bool(sponsor0_b64)} have2={bool(sponsor2_b64)}"
                    )
                except Exception as _e:
                    return {"success": False, "error": "cannot_sign_sponsor"}
            # Debug: decode and log group fields
            try:
                import logging as _log
                if sponsor0_b64 and user_signed_b64 and sponsor2_b64:
                    # Decode as dicts
                    t0d = _tx_dict(sponsor0_b64)
                    t1d = t1d or _tx_dict(user_signed_b64)
                    t2d = _tx_dict(sponsor2_b64)
                    sender0 = _addr_from_key((t0d or {}).get(b'snd'))
                    recv0 = _addr_from_key((t0d or {}).get(b'rcv'))
                    fee0 = (t0d or {}).get(b'fee')
                    sender1 = _addr_from_key((t1d or {}).get(b'snd'))
                    recv1 = _addr_from_key((t1d or {}).get(b'arcv'))
                    amt1 = (t1d or {}).get(b'aamt')
                    fee1 = (t1d or {}).get(b'fee')
                    sender2 = _addr_from_key((t2d or {}).get(b'snd'))
                    accs2 = []
                    try:
                        for a in (t2d or {}).get(b'apat') or []:
                            accs2.append(_addr_from_key(a))
                    except Exception:
                        accs2 = None
                    fee2 = (t2d or {}).get(b'fee')
                    _log.getLogger(__name__).info(
                        f"[PRESALE][WS][SUBMIT] G0 pay sender={sender0} recv={recv0} fee={fee0}"
                    )
                    _log.getLogger(__name__).info(
                        f"[PRESALE][WS][SUBMIT] G1 axfer sender={sender1} recv={recv1} amt={amt1} fee={fee1}"
                    )
                    _log.getLogger(__name__).info(
                        f"[PRESALE][WS][SUBMIT] G2 appcall sender={sender2} fee={fee2} accounts={accs2}"
                    )

                    # Self-heal: ensure the appcall accounts[0] matches user-signed sender
                    try:
                        user_sender = sender1
                        app_user = (accs2[0] if (isinstance(accs2, list) and len(accs2) > 0) else None)
                        if user_sender and app_user and user_sender != app_user:
                            _log.getLogger(__name__).warning(
                                f"[PRESALE][WS][SUBMIT] Mismatch: user sender {user_sender} != app accounts[0] {app_user}; rebuilding sponsor txns"
                            )
                            from blockchain.presale_transaction_builder import PresaleTransactionBuilder
                            builder = PresaleTransactionBuilder()
                            cusd_base = int(purchase.cusd_amount * 10**6)
                            pack_fix = builder.build_buy_group(purchase.from_address, cusd_base)
                            sp_list = pack_fix.get('sponsor_transactions') or []
                            for e in sp_list:
                                if int(e.get('index')) == 0:
                                    sponsor0_b64 = e.get('signed') or e.get('txn')
                                elif int(e.get('index')) == 2:
                                    sponsor2_b64 = e.get('signed') or e.get('txn')
                            # Re-decode for logging after fix
                            t2d = _tx_dict(sponsor2_b64)
                            accs2 = []
                            try:
                                for a in (t2d or {}).get(b'apat') or []:
                                    accs2.append(_addr_from_key(a))
                            except Exception:
                                accs2 = None
                            _log.getLogger(__name__).info(
                                f"[PRESALE][WS][SUBMIT][FIXED] G2 accounts={accs2}"
                            )
                        elif user_sender and purchase.from_address and user_sender != purchase.from_address:
                            # User signed with a different address than expected
                            return {"success": False, "error": "user_sender_mismatch"}
                    except Exception:
                        pass
            except Exception:
                pass
            # Compose bytes in correct order
            def b64_to_bytes(b64s: str) -> bytes:
                missing = len(b64s) % 4
                if missing:
                    b64s += '=' * (4 - missing)
                return base64.b64decode(b64s)

            # Submit as a single base64-encoded blob (align with other flows)
            import base64 as _b64
            # Log full decoded txns (including app accounts) for diagnosis
            try:
                from algosdk import encoding as _enc
                t0 = _enc.msgpack_decode(b64_to_bytes(sponsor0_b64))
                t1 = _enc.msgpack_decode(b64_to_bytes(user_signed_b64))
                t2 = _enc.msgpack_decode(b64_to_bytes(sponsor2_b64))
                logger = __import__('logging').getLogger(__name__)
                logger.info(f"[PRESALE][WS][SUBMIT] G0 pay sender={getattr(t0,'sender',None)} recv={getattr(t0,'receiver',None)} amt={getattr(t0,'amt',None)} fee={getattr(t0,'fee',None)}")
                logger.info(f"[PRESALE][WS][SUBMIT] G1 axfer sender={getattr(t1,'sender',None)} asset={getattr(t1,'index',None)} recv={getattr(t1,'receiver',None)} amt={getattr(t1,'amt',None)} fee={getattr(t1,'fee',None)}")
                # Application accounts can be present on field 'accounts'
                accs = getattr(t2, 'accounts', None)
                logger.info(f"[PRESALE][WS][SUBMIT] G2 appcall sender={getattr(t2,'sender',None)} fee={getattr(t2,'fee',None)} accounts={accs}")
            except Exception:
                pass

            group_bytes = b''.join([
                b64_to_bytes(sponsor0_b64),
                b64_to_bytes(user_signed_b64),
                b64_to_bytes(sponsor2_b64),
            ])
            combined_b64 = _b64.b64encode(group_bytes).decode('utf-8')
            txid = algod_client.send_raw_transaction(combined_b64)

            # Save txid immediately
            purchase.transaction_hash = txid
            purchase.save(update_fields=['transaction_hash'])

            # Immediate return; Celery will confirm and notify

            return {"success": True, "txid": txid}
        except Exception as e:
            return {"success": False, "error": str(e) or "submit_failed"}
