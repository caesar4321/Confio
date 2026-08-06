"""Narrow exceptions to the generic Solana sponsorship safety policy.

Normal transactions need no per-product policy: if no instruction receives
the sponsor account, programs cannot spend sponsor SOL.  This registry exists
only for instructions that intentionally receive account zero, currently the
cUSD+ primary-issuance instruction that checks the registered sponsor signer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.conf import settings
from solders.pubkey import Pubkey

from blockchain.solana_sponsor_service import (
    SolanaSponsorPolicyError,
    ValidatedSponsoredTransaction,
)

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
DEPOSIT_AND_MINT_DISCRIMINATOR = hashlib.sha256(
    b"global:deposit_and_mint"
).digest()[:8]


@dataclass(frozen=True)
class CusdPlusDepositPolicy:
    program_id: str
    usdy_mint: str
    cusd_mint: str
    reserve: str
    max_usdy_base_units: int

    def __call__(self, validated: ValidatedSponsoredTransaction) -> None:
        message = validated.transaction.message
        keys = tuple(message.account_keys)
        try:
            program = Pubkey.from_string(self.program_id)
            sponsor = keys[0]
            expected_user = Pubkey.from_string(validated.expected_user_signer)
            config, _ = Pubkey.find_program_address([b"config"], program)
            vault_authority, _ = Pubkey.find_program_address(
                [b"vault-authority"], program
            )
            sponsor_record, _ = Pubkey.find_program_address(
                [b"sponsor", bytes(sponsor)], program
            )
        except (ValueError, IndexError):
            raise SolanaSponsorPolicyError("bad_cusd_plus_policy_config") from None

        sponsor_instructions = []
        for instruction in message.instructions:
            accounts = tuple(bytes(instruction.accounts))
            if any(keys[index] == sponsor for index in accounts):
                sponsor_instructions.append((instruction, accounts))
        if len(sponsor_instructions) != 1:
            raise SolanaSponsorPolicyError("bad_sponsor_instruction_count")

        instruction, accounts = sponsor_instructions[0]
        if str(keys[int(instruction.program_id_index)]) != self.program_id:
            raise SolanaSponsorPolicyError("bad_sponsor_program")
        # Exact Anchor account order; no remaining accounts. The sponsor may
        # occur only in its declared signer position, never as a transfer
        # source or destination hidden elsewhere in the instruction.
        if (
            len(accounts) != 12
            or accounts[1] != 0
            or sum(keys[index] == sponsor for index in accounts) != 1
        ):
            raise SolanaSponsorPolicyError("bad_cusd_plus_accounts")
        if keys[accounts[0]] != expected_user:
            raise SolanaSponsorPolicyError("bad_cusd_plus_depositor")
        try:
            expected_fixed = {
                2: sponsor_record,
                3: config,
                4: vault_authority,
                5: Pubkey.from_string(self.usdy_mint),
                6: Pubkey.from_string(self.cusd_mint),
                9: Pubkey.from_string(self.reserve),
            }
        except ValueError:
            raise SolanaSponsorPolicyError("bad_cusd_plus_policy_config") from None
        if any(keys[accounts[position]] != value for position, value in expected_fixed.items()):
            raise SolanaSponsorPolicyError("bad_cusd_plus_accounts")
        # The v1 vault deliberately supports the legacy SPL Token program
        # only. Token-2022 transfer-fee and hook extensions would make the
        # nominal instruction amount differ from the backing actually moved.
        if str(keys[accounts[10]]) != TOKEN_PROGRAM:
            raise SolanaSponsorPolicyError("bad_token_program")
        if str(keys[accounts[11]]) != TOKEN_PROGRAM:
            raise SolanaSponsorPolicyError("bad_token_program")

        data = bytes(instruction.data)
        if len(data) != 24 or data[:8] != DEPOSIT_AND_MINT_DISCRIMINATOR:
            raise SolanaSponsorPolicyError("bad_cusd_plus_instruction")
        usdy_in = int.from_bytes(data[8:16], "little")
        min_shares_out = int.from_bytes(data[16:24], "little")
        if (
            usdy_in <= 0
            or min_shares_out <= 0
            or usdy_in > self.max_usdy_base_units
        ):
            raise SolanaSponsorPolicyError("bad_cusd_plus_amount")


def sponsor_reference_policy():
    """Return the configured policy hook for a sponsor-aware transaction."""
    program_id = getattr(settings, "SOLANA_CUSD_PLUS_PROGRAM_ID", "") or ""
    usdy_mint = getattr(settings, "SOLANA_USDY_MINT", "") or ""
    cusd_mint = getattr(settings, "SOLANA_CUSD_PLUS_MINT", "") or ""
    reserve = getattr(settings, "SOLANA_CUSD_PLUS_RESERVE", "") or ""
    if not all((program_id, usdy_mint, cusd_mint, reserve)):
        raise SolanaSponsorPolicyError("sponsor_policy_not_configured")
    return CusdPlusDepositPolicy(
        program_id=program_id,
        usdy_mint=usdy_mint,
        cusd_mint=cusd_mint,
        reserve=reserve,
        max_usdy_base_units=int(
            getattr(settings, "SOLANA_CUSD_PLUS_MAX_DEPOSIT_BASE_UNITS", 0)
        ),
    )
