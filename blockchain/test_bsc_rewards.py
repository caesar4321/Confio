"""
BSC rewards attestation (blockchain/bsc_rewards_service.py) + the wholesale
migration switch in achievements/services/referral_rewards.py.

RPC + KMS mocked, house style — no chain, no DB writes beyond the referral
sync's own ORM (which is exercised via SimpleTestCase-safe mocks).

    myvenv/bin/python manage.py test blockchain.test_bsc_rewards
"""
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings

from blockchain.bsc_rewards_service import BscRewardsService, SEL_SET_ELIGIBLE

VAULT = "0x1766A2Ac798dA2247E5Da6E410453D526FD2f6ab"
SPONSOR = "0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D"
USER = "0x" + "11" * 20
REF = "0x" + "22" * 20
WAD = 10 ** 18


@override_settings(BSC_REWARD_VAULT_ADDRESS=VAULT, BSC_SPONSOR_ADDRESS=SPONSOR, BSC_CHAIN_ID=56)
class BscRewardsServiceTests(SimpleTestCase):
    def _rpc(self, calls):
        """Return an eth-RPC stub driven by a dict of {method: value} or a
        callable for eth_call keyed on the selector."""
        def _fn(method, params, *a, **k):
            v = calls.get(method)
            return v(params) if callable(v) else v
        return _fn

    def _eth_call_router(self, price_round=1, price=Decimal("0.25"), pending=False):
        def _call(params):
            data = params[0]["data"]
            sel = data[2:10]
            from eth_utils import keccak
            def s(sig):
                return keccak(text=sig)[:4].hex()
            if sel == s("priceRound()"):
                return "0x" + format(price_round, "x").rjust(64, "0")
            if sel == s("manualPriceActive()"):
                return "0x" + "0" * 63 + "1"
            if sel == s("manualPrice()"):
                return "0x" + format(int(price * WAD), "x").rjust(64, "0")
            if sel == s("rewards(address)"):
                amt = WAD if pending else 0
                return ("0x" + format(amt, "x").rjust(64, "0")
                        + "0" * 64 + "0" * 64 + "0" * 64 + "0" * 64 + "0" * 64)
            if sel == SEL_SET_ELIGIBLE:
                return "0x"  # simulation ok
            return "0x"
        return _call

    def test_convert_cusd_to_confio_uses_vault_price(self):
        svc = BscRewardsService()
        with mock.patch("cusd_plus.sponsor_7702._rpc",
                        side_effect=self._rpc({"eth_call": self._eth_call_router(price=Decimal("0.25"))})):
            self.assertEqual(svc.convert_cusd_to_confio(Decimal("5")), Decimal("20"))  # $5 / $0.25
            self.assertEqual(svc.convert_cusd_to_confio(Decimal("10")), Decimal("40"))

    def test_mark_eligibility_sends_setEligible_with_pinned_round(self):
        svc = BscRewardsService()
        signer = mock.Mock(address=SPONSOR)
        signer.sign_typed_transaction.return_value = ("0xraw", "0xhash")
        captured = {}

        def _rpc(method, params, *a, **k):
            if method == "eth_call":
                return self._eth_call_router(price_round=3)(params)
            if method == "eth_gasPrice":
                return hex(1_000_000_000)
            if method == "eth_getTransactionCount":
                return hex(30)
            if method == "eth_getBalance":
                return hex(WAD)  # 1 BNB, plenty
            if method == "eth_sendRawTransaction":
                captured["raw"] = params[0]
                return "0xsent"
            return "0x"

        with mock.patch("cusd_plus.sponsor_7702._rpc", side_effect=_rpc), \
             mock.patch("cusd_plus.sponsor_7702.acquire_sponsor_nonce_lock", return_value=True), \
             mock.patch("cusd_plus.sponsor_7702.release_sponsor_nonce_lock"), \
             mock.patch("blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings",
                        return_value=signer):
            res = svc.mark_eligibility(
                user_address=USER, reward_cusd_wei=5 * WAD,
                referrer_confio_wei=20 * WAD, referrer_address=REF)

        self.assertEqual(res.tx_hash, "0xsent")
        self.assertEqual(res.tx_id, "0xsent")  # drop-in compat
        # The tx targeted the vault with setEligible calldata pinning round 3.
        tx = signer.sign_typed_transaction.call_args[0][0]
        self.assertEqual(tx["to"].lower(), VAULT.lower())
        data = tx["data"]
        self.assertEqual(data[2:10], SEL_SET_ELIGIBLE)
        # round is the 3rd arg (offset 2*64 into the abi tail): user, cusd, round
        self.assertEqual(int(data[10 + 128:10 + 192], 16), 3)
        self.assertEqual(int(data[10 + 64:10 + 128], 16), 5 * WAD)

    def test_pending_allocation_is_idempotent_noop(self):
        svc = BscRewardsService()
        with mock.patch("cusd_plus.sponsor_7702._rpc",
                        side_effect=self._rpc({"eth_call": self._eth_call_router(pending=True)})):
            res = svc.mark_eligibility(user_address=USER, reward_cusd_wei=5 * WAD)
        self.assertTrue(res.already_recorded)
        self.assertEqual(res.tx_hash, "already-recorded")

    def test_inactive_price_refused(self):
        svc = BscRewardsService()

        def _call(params):
            from eth_utils import keccak
            if params[0]["data"][2:10] == keccak(text="manualPriceActive()")[:4].hex():
                return "0x" + "0" * 64  # inactive
            return "0x"

        with mock.patch("cusd_plus.sponsor_7702._rpc",
                        side_effect=self._rpc({"eth_call": _call})):
            with self.assertRaises(RuntimeError):
                svc.convert_cusd_to_confio(Decimal("5"))


class ToMicroTests(SimpleTestCase):
    def test_decimals_switch(self):
        from achievements.services.referral_rewards import to_micro
        self.assertEqual(to_micro(Decimal("5")), 5_000_000)          # 6dp default
        self.assertEqual(to_micro(Decimal("5"), 18), 5 * WAD)        # BSC wei
        self.assertEqual(to_micro(Decimal("20"), 18), 20 * WAD)
