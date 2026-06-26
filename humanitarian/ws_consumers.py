import asyncio
import base64
import json
import logging
import re
from decimal import Decimal
from urllib.parse import parse_qs

import msgpack
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)


class HumanitarianSessionConsumer(AsyncJsonWebsocketConsumer):
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
        for task in (getattr(self, "_keepalive_task", None), getattr(self, "_idle_task", None)):
            if task:
                task.cancel()

    async def receive_json(self, content, **kwargs):
        await self._reset_idle_timer()
        message_type = content.get("type")
        if message_type == "ping":
            await self.send_json({"type": "pong"})
            return
        if message_type == "donation_prepare":
            try:
                pack = await self._donation_prepare(content.get("campaign_slug"), content.get("amount"))
                if not pack.get("success"):
                    await self.send_json({"type": "error", "message": pack.get("error", "donation_prepare_failed")})
                    return
                await self.send_json({
                    "type": "prepare_ready",
                    "pack": {
                        "donation_id": pack.get("donation_id"),
                        "transactions": pack.get("transactions"),
                        "sponsor_transactions": pack.get("sponsor_transactions"),
                        "user_signing_indexes": [0],
                        "group_id": pack.get("group_id"),
                    },
                })
            except Exception as e:
                logger.exception("[HUMANITARIAN][WS] donation_prepare exception")
                await self.send_json({"type": "error", "message": str(e) or "donation_prepare_exception"})
            return
        if message_type == "donation_submit":
            try:
                res = await self._donation_submit(
                    content.get("donation_id"),
                    content.get("signed_transactions"),
                    content.get("sponsor_transactions") or [],
                )
                if not res.get("success"):
                    await self.send_json({"type": "error", "message": res.get("error", "donation_submit_failed")})
                    return
                await self.send_json({"type": "submit_ok", "transaction_id": res.get("txid")})
            except Exception as e:
                logger.exception("[HUMANITARIAN][WS] donation_submit exception")
                await self.send_json({"type": "error", "message": str(e) or "donation_submit_exception"})
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
            account = Account.objects.filter(user=user, account_type="personal", deleted_at__isnull=True).first()
        return account

    @database_sync_to_async
    def _donation_prepare(self, campaign_slug, amount):
        from algosdk.v2client import algod
        from blockchain.algorand_account_manager import AlgorandAccountManager
        from blockchain.humanitarian_transaction_builder import HumanitarianTransactionBuilder
        from humanitarian.models import HumanitarianCampaign, HumanitarianDonation

        user = self.scope.get("user")
        campaign = HumanitarianCampaign.objects.filter(slug=campaign_slug, status__iexact="active").first()
        if not campaign:
            return {"success": False, "error": "campaign_not_active"}

        try:
            donation_amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        except Exception:
            return {"success": False, "error": "invalid_amount"}
        if donation_amount < Decimal("1.00"):
            return {"success": False, "error": "below_minimum"}

        app_id = int(campaign.algorand_app_id or 0)
        if not app_id:
            from django.conf import settings
            app_id = int(getattr(settings, "ALGORAND_HUMANITARIAN_APP_ID", 0) or 0)
        if not app_id:
            return {"success": False, "error": "humanitarian_not_configured"}

        account = self._get_active_account()
        if not account or not account.algorand_address or len(account.algorand_address) != 58:
            return {"success": False, "error": "no_algorand_address"}
        if not getattr(account, "is_keyless_migrated", False):
            return {"success": False, "error": "Actualiza tu app para donar."}

        cusd_base = int(donation_amount * Decimal("1000000"))
        try:
            algod_client = algod.AlgodClient(AlgorandAccountManager.ALGOD_TOKEN, AlgorandAccountManager.ALGOD_ADDRESS)
            acct = algod_client.account_info(account.algorand_address)
            cusd_balance = 0
            for asset in acct.get("assets") or []:
                if int(asset.get("asset-id") or 0) == int(AlgorandAccountManager.CUSD_ASSET_ID):
                    cusd_balance = int(asset.get("amount") or 0)
                    break
            if cusd_balance < cusd_base:
                return {"success": False, "error": "insufficient_cusd_balance"}
        except Exception:
            pass

        donor_name = user.get_full_name() or user.username or "Donante Confio"
        donation = HumanitarianDonation.objects.create(
            campaign=campaign,
            donor_user=user,
            donor_display_name=donor_name[:160],
            amount=donation_amount,
            status="pending",
            from_address=account.algorand_address,
        )

        builder = HumanitarianTransactionBuilder(app_id=app_id)
        tx_pack = builder.build_donation_group(account.algorand_address, cusd_base, donation.public_id)
        if not tx_pack.get("success"):
            donation.status = "failed"
            donation.save(update_fields=["status", "updated_at"])
            return {"success": False, **{k: v for k, v in tx_pack.items() if k != "success"}}

        try:
            donation.campaign.vault_address = tx_pack.get("app_address") or donation.campaign.vault_address
            donation.campaign.algorand_app_id = app_id
            donation.campaign.save(update_fields=["vault_address", "algorand_app_id", "updated_at"])
        except Exception:
            pass

        transactions = []
        for ut in tx_pack.get("transactions_to_sign") or []:
            transactions.append({
                "index": ut.get("index", 0),
                "type": "asset_transfer",
                "transaction": ut.get("txn"),
                "signed": False,
                "needs_signature": True,
            })
        for sp in tx_pack.get("sponsor_transactions") or []:
            transactions.append({
                "index": sp.get("index"),
                "type": "application",
                "transaction": sp.get("signed") or sp.get("txn"),
                "signed": bool(sp.get("signed")),
                "needs_signature": not bool(sp.get("signed")),
            })

        return {
            "success": True,
            "donation_id": donation.public_id,
            "transactions": transactions,
            "sponsor_transactions": tx_pack.get("sponsor_transactions") or [],
            "group_id": tx_pack.get("group_id"),
        }

    @database_sync_to_async
    def _donation_submit(self, donation_id, signed_transactions, sponsor_transactions):
        from algosdk import encoding as algo_encoding
        from algosdk.transaction import wait_for_confirmation
        from algosdk.v2client import algod
        from blockchain.algorand_account_manager import AlgorandAccountManager
        from humanitarian.models import HumanitarianDonation

        try:
            donation = HumanitarianDonation.objects.select_related("campaign").get(public_id=donation_id)
        except HumanitarianDonation.DoesNotExist:
            return {"success": False, "error": "donation_not_found"}

        if donation.status == "confirmed" and donation.transaction_hash:
            return {"success": True, "txid": donation.transaction_hash}
        if not isinstance(signed_transactions, list) or not signed_transactions:
            return {"success": False, "error": "signed_transactions_required"}

        user_signed_b64 = None
        for tx in signed_transactions:
            try:
                if int(tx.get("index")) == 0:
                    user_signed_b64 = tx.get("transaction")
                    break
            except Exception:
                if isinstance(tx, str) and not user_signed_b64:
                    user_signed_b64 = tx
        if not user_signed_b64:
            return {"success": False, "error": "missing_user_signed"}

        sponsor_b64 = None
        try:
            for entry in sponsor_transactions or []:
                if isinstance(entry, str):
                    entry = json.loads(entry)
                if int(entry.get("index")) == 1:
                    sponsor_b64 = entry.get("signed") or entry.get("txn")
                    break
        except Exception:
            pass
        if not sponsor_b64:
            return {"success": False, "error": "missing_sponsor_signed"}

        def b64_to_bytes(value: str) -> bytes:
            missing = len(value) % 4
            if missing:
                value += "=" * (4 - missing)
            return base64.b64decode(value)

        try:
            raw = b64_to_bytes(user_signed_b64)
            decoded = msgpack.unpackb(raw, raw=True)
            tx_dict = decoded.get(b"txn") if isinstance(decoded, dict) and b"txn" in decoded else decoded
            sender = algo_encoding.encode_address(tx_dict.get(b"snd"))
            receiver = algo_encoding.encode_address(tx_dict.get(b"arcv"))
            amount = int(tx_dict.get(b"aamt") or 0)
            asset_id = int(tx_dict.get(b"xaid") or 0)
            expected_amount = int(donation.amount * Decimal("1000000"))
            if sender != donation.from_address:
                return {"success": False, "error": "user_sender_mismatch"}
            if amount != expected_amount:
                return {"success": False, "error": "amount_mismatch"}
            if asset_id != int(AlgorandAccountManager.CUSD_ASSET_ID):
                return {"success": False, "error": "asset_mismatch"}
            if donation.campaign.vault_address and receiver != donation.campaign.vault_address:
                return {"success": False, "error": "vault_mismatch"}
        except Exception as e:
            return {"success": False, "error": f"invalid_user_transaction:{e}"}

        algod_client = algod.AlgodClient(AlgorandAccountManager.ALGOD_TOKEN, AlgorandAccountManager.ALGOD_ADDRESS)
        group_bytes = b"".join([b64_to_bytes(user_signed_b64), b64_to_bytes(sponsor_b64)])
        combined_b64 = base64.b64encode(group_bytes).decode("utf-8")
        try:
            txid = algod_client.send_raw_transaction(combined_b64)
            try:
                wait_for_confirmation(algod_client, txid, 4)
            except Exception as confirm_exc:
                donation.transaction_hash = txid
                donation.save(update_fields=["transaction_hash", "updated_at"])
                logger.warning(
                    "[HUMANITARIAN][WS] donation confirmation pending donation=%s txid=%s error=%s",
                    donation.public_id,
                    txid,
                    confirm_exc,
                )
                return {"success": False, "error": "confirmation_pending"}

            from django.db import transaction as db_transaction

            with db_transaction.atomic():
                locked = HumanitarianDonation.objects.select_for_update().select_related("campaign").get(pk=donation.pk)
                if locked.status != "confirmed":
                    locked.status = "confirmed"
                    locked.transaction_hash = txid
                    locked.save(update_fields=["status", "transaction_hash", "updated_at"])
                    campaign = locked.campaign
                    campaign.total_donated = (campaign.total_donated or Decimal("0.00")) + locked.amount
                    campaign.donation_count = (campaign.donation_count or 0) + 1
                    campaign.save(update_fields=["total_donated", "donation_count", "updated_at"])
            return {"success": True, "txid": txid}
        except Exception as e:
            err = str(e)
            if "already in pool" in err.lower() or "already in ledger" in err.lower():
                match = re.search(r"(?:already in pool|already in ledger):\s*([A-Z2-7]{52})", err, re.IGNORECASE)
                if match and not donation.transaction_hash:
                    donation.transaction_hash = match.group(1)
                    donation.save(update_fields=["transaction_hash", "updated_at"])
                return {"success": False, "error": "confirmation_pending"}
            donation.status = "failed"
            donation.save(update_fields=["status", "updated_at"])
            return {"success": False, "error": err}
