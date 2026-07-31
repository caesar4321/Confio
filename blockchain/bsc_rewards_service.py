"""
BSC CONFIO rewards — the BSC sibling of blockchain/rewards_service.py.

Attests per-user referral/usage eligibility into ConfioRewardVault on BNB
Smart Chain by calling `setEligible` as the ATTESTOR key (the KMS sponsor,
which the vault was deployed with). Plain type-2 KMS transaction, not a
7702 batch — the attestor IS msg.sender at the vault. Same shared sponsor
nonce lock as payroll payouts so concurrent attestations can't collide.

The wholesale migration target of the reward program (Julian, 2026-07-31):
new referral rewards attest here instead of on Algorand. The main reward
is cUSD-denominated and converted to CONFIO ON-CHAIN at the vault's manual
price; the referral amount is converted HERE and passed as CONFIO (the
same asymmetry as the Algorand contract). Every call pins the vault's
`priceRound` so a mid-flight Safe re-price is rejected, not silently
applied at the new rate.
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.conf import settings
from eth_abi import encode as abi_encode
from eth_utils import keccak, to_checksum_address

logger = logging.getLogger(__name__)

WAD = 10 ** 18


def _sel(sig: str) -> str:
    return keccak(text=sig)[:4].hex()


SEL_SET_ELIGIBLE = _sel("setEligible(address,uint256,uint64,address,uint256)")
SEL_REWARDS = _sel("rewards(address)")
SEL_MANUAL_PRICE = _sel("manualPrice()")
SEL_MANUAL_ACTIVE = _sel("manualPriceActive()")
SEL_PRICE_ROUND = _sel("priceRound()")

# Fork-free fixed budget: setEligible is one SSTORE-heavy write + counters.
GAS_SET_ELIGIBLE = 220_000


@dataclass
class BscRewardResult:
    tx_hash: str
    referee_confio_wei: int
    referrer_confio_wei: int
    already_recorded: bool = False

    # Drop-in compatibility with the Algorand RewardSyncResult the referral
    # sync consumes (it reads .tx_id and .box_name).
    @property
    def tx_id(self) -> str:
        return self.tx_hash

    @property
    def box_name(self) -> str:
        return ""  # no boxes on BSC


class BscRewardsService:
    """Thin attestor client for ConfioRewardVault. Constructed per use so a
    disabled/unconfigured environment fails loudly at call time, not import."""

    def __init__(self):
        self.vault = (getattr(settings, "BSC_REWARD_VAULT_ADDRESS", "") or "").lower()
        if not self.vault:
            raise RuntimeError("BSC_REWARD_VAULT_ADDRESS is not configured")
        self.chain_id = int(getattr(settings, "BSC_CHAIN_ID", 56))

    # ── vault reads (eth_call) ───────────────────────────────────────

    def _call(self, data: str) -> str:
        from cusd_plus.sponsor_7702 import _rpc
        return _rpc("eth_call", [{"to": self.vault, "data": data}, "latest"])

    def price_round(self) -> int:
        out = self._call("0x" + SEL_PRICE_ROUND)
        return int(out, 16) if out and out != "0x" else 0

    def manual_price_wad(self) -> int:
        active = self._call("0x" + SEL_MANUAL_ACTIVE)
        if not (active and int(active, 16) == 1):
            raise RuntimeError("reward vault manual price is not active")
        out = self._call("0x" + SEL_MANUAL_PRICE)
        price = int(out, 16) if out and out != "0x" else 0
        if price <= 0:
            raise RuntimeError("reward vault manual price is zero")
        return price

    def convert_cusd_to_confio(self, cusd_amount: Decimal) -> Decimal:
        """cUSD → CONFIO at the vault's active price (floor, matching the
        contract's Math.mulDiv)."""
        price = self.manual_price_wad()
        confio_wei = (int(Decimal(cusd_amount) * WAD) * WAD) // price
        return Decimal(confio_wei) / WAD

    def _reward_pending(self, user_addr: str) -> bool:
        """rewards(user) → the contract reverts a re-attestation while
        amount!=0 or refAmount!=0; check first so we treat that as an
        idempotent no-op instead of an error (mirrors the Algorand box
        check)."""
        out = self._call("0x" + SEL_REWARDS + user_addr.lower().replace("0x", "").rjust(64, "0"))
        if not out or out == "0x":
            return False
        body = out[2:]
        amount = int(body[0:64], 16)
        ref_amount = int(body[64:128], 16)
        return amount != 0 or ref_amount != 0

    # ── attestation (plain KMS tx from the attestor/sponsor) ─────────

    def mark_eligibility(
        self,
        *,
        user_address: str,
        reward_cusd_wei: int,
        referrer_confio_wei: int = 0,
        referrer_address: Optional[str] = None,
    ) -> BscRewardResult:
        from cusd_plus.sponsor_7702 import (
            _rpc,
            acquire_sponsor_nonce_lock,
            release_sponsor_nonce_lock,
        )
        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        if reward_cusd_wei <= 0:
            raise ValueError("reward_cusd_wei must be positive")
        user_address = to_checksum_address(user_address)
        if referrer_confio_wei > 0:
            if not referrer_address:
                raise ValueError("referrer_address required when referrer_confio_wei > 0")
            referrer_address = to_checksum_address(referrer_address)
        else:
            referrer_address = "0x" + "0" * 40

        # Idempotency: a still-pending allocation must not be rewritten (the
        # contract would revert). Report it as already recorded.
        if self._reward_pending(user_address):
            logger.info("[REWARD][BSC] %s already has a pending allocation; skipping", user_address)
            return BscRewardResult("already-recorded", 0, referrer_confio_wei, already_recorded=True)

        price_round = self.price_round()
        calldata = "0x" + SEL_SET_ELIGIBLE + abi_encode(
            ["address", "uint256", "uint64", "address", "uint256"],
            [user_address, int(reward_cusd_wei), int(price_round),
             referrer_address, int(referrer_confio_wei)],
        ).hex()

        signer = get_bsc_sponsor_signer_from_settings()
        attestor = signer.address
        expected = (getattr(settings, "BSC_SPONSOR_ADDRESS", "") or "").lower()
        if expected and attestor.lower() != expected:
            raise RuntimeError("KMS signer is not the configured attestor/sponsor")

        # Pre-flight the exact call (bad price round, pending, insufficient
        # reserve all surface here before any gas is spent).
        try:
            _rpc("eth_call", [{"from": attestor, "to": self.vault, "data": calldata}, "latest"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[REWARD][BSC] setEligible simulation reverted for %s: %s",
                           user_address, exc)
            raise

        gas_price = max(int(_rpc("eth_gasPrice", []), 16),
                        int(getattr(settings, "CUSD_PLUS_GAS_PRICE_FLOOR_WEI", 100_000_000)))
        price_cap = int(getattr(settings, "CUSD_PLUS_7702_MAX_GAS_PRICE_WEI", 5_000_000_000))
        if gas_price > price_cap:
            raise RuntimeError("gas_price_too_high")
        fee_per_gas = min((gas_price * 12) // 10, price_cap)

        if not acquire_sponsor_nonce_lock():
            raise RuntimeError("sponsor_busy")
        try:
            nonce = int(_rpc("eth_getTransactionCount", [attestor, "pending"]), 16)
            balance = int(_rpc("eth_getBalance", [attestor, "latest"]), 16)
            if balance < (GAS_SET_ELIGIBLE * fee_per_gas * 11) // 10:
                raise RuntimeError("attestor_balance_low")
            tx = {
                "type": 2, "chainId": self.chain_id, "nonce": nonce,
                "maxPriorityFeePerGas": fee_per_gas, "maxFeePerGas": fee_per_gas,
                "gas": GAS_SET_ELIGIBLE, "to": to_checksum_address(self.vault),
                "value": 0, "data": calldata, "accessList": [],
            }
            raw, tx_hash = signer.sign_typed_transaction(tx)
            sent = _rpc("eth_sendRawTransaction", [raw])
        finally:
            release_sponsor_nonce_lock()

        logger.info("[REWARD][BSC] setEligible sent for %s (round %s): %s",
                    user_address, price_round, sent or tx_hash)
        return BscRewardResult(sent or tx_hash, int(reward_cusd_wei), referrer_confio_wei)
