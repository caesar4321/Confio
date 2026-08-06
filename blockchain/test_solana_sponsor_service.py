import base64
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.null_signer import NullSigner
from solders.pubkey import Pubkey
from solders.transaction import Transaction, VersionedTransaction

from blockchain.solana_kms_signer import SolanaKMSSigner
from blockchain.solana_policies import (
    CusdPlusDepositPolicy,
    DEPOSIT_AND_MINT_DISCRIMINATOR,
    TOKEN_PROGRAM,
)
from blockchain.solana_sponsor_service import (
    SolanaSponsorPolicyError,
    SolanaSponsorService,
)


class _LocalSigner:
    def __init__(self, keypair):
        self.keypair = keypair
        self.address = str(keypair.pubkey())

    def sign_message(self, message):
        return bytes(self.keypair.sign_message(message))


def _partially_signed_transaction(sponsor, user, program, *, sponsor_in_ix=False):
    accounts = [AccountMeta(user.pubkey(), True, True)]
    if sponsor_in_ix:
        accounts.append(AccountMeta(sponsor.pubkey(), True, True))
    instruction = Instruction(
        program,
        b"confio-test",
        accounts,
    )
    message = MessageV0.try_compile(
        sponsor.pubkey(), [instruction], [], Hash.new_unique()
    )
    tx = VersionedTransaction(
        message,
        [NullSigner(sponsor.pubkey()), user],
    )
    return base64.b64encode(bytes(tx)).decode("ascii")


class SolanaSponsorServiceTests(unittest.TestCase):
    def setUp(self):
        self.sponsor = Keypair()
        self.user = Keypair()
        self.program = Pubkey.new_unique()
        self.rpc_calls = []

        def rpc(method, params):
            self.rpc_calls.append((method, params))
            if method == "sendTransaction":
                signed = VersionedTransaction.from_bytes(base64.b64decode(params[0]))
                return str(signed.signatures[0])
            return {
                "isBlockhashValid": {"context": {"slot": 1}, "value": True},
                "getFeeForMessage": {"context": {"slot": 1}, "value": 10_000},
                "getBalance": {"context": {"slot": 1}, "value": 1_000_000_000},
                "simulateTransaction": {"context": {"slot": 1}, "value": {"err": None}},
            }[method]

        self.service = SolanaSponsorService(
            signer=_LocalSigner(self.sponsor),
            rpc_url="unused",
            rpc_call=rpc,
            allowed_program_ids=[str(self.program)],
            max_fee_lamports=20_000,
            min_sponsor_balance_lamports=0,
        )

    def test_adds_fee_payer_signature_and_relays(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program
        )
        result = self.service.sponsor_and_send(
            encoded,
            expected_user_signer=str(self.user.pubkey()),
            fee_authorizer=lambda fee, balance, slot, validated: None,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["feeLamports"], 10_000)
        self.assertEqual(
            [call[0] for call in self.rpc_calls],
            [
                "isBlockhashValid",
                "getFeeForMessage",
                "getBalance",
                "simulateTransaction",
                "sendTransaction",
            ],
        )

        signed_wire = base64.b64decode(self.rpc_calls[-1][1][0])
        signed = VersionedTransaction.from_bytes(signed_wire)
        self.assertTrue(all(signed.verify_with_results()))

    def test_accepts_legacy_transaction_wire_format(self):
        instruction = Instruction(
            self.program,
            b"legacy",
            [AccountMeta(self.user.pubkey(), True, True)],
        )
        tx = Transaction.new_with_payer([instruction], self.sponsor.pubkey())
        tx.partial_sign([self.user], Hash.new_unique())
        encoded = base64.b64encode(bytes(tx)).decode("ascii")

        result = self.service.sponsor_and_send(
            encoded,
            expected_user_signer=str(self.user.pubkey()),
            fee_authorizer=lambda fee, balance, slot, validated: None,
        )
        self.assertTrue(result["success"])

    def test_rejects_malformed_legacy_header_before_rpc_or_kms(self):
        instruction = Instruction(
            self.program,
            b"legacy",
            [AccountMeta(self.user.pubkey(), True, True)],
        )
        tx = Transaction.new_with_payer([instruction], self.sponsor.pubkey())
        tx.partial_sign([self.user], Hash.new_unique())
        wire = bytearray(bytes(tx))
        # shortvec signature count is one byte for this fixture, followed by
        # two 64-byte signatures. Corrupt the legacy header's unsigned
        # readonly count beyond the number of unsigned account keys.
        message_offset = 1 + 2 * 64
        wire[message_offset + 2] = 255
        wire[65:129] = bytes(self.user.sign_message(bytes(wire[message_offset:])))
        encoded = base64.b64encode(wire).decode("ascii")

        with self.assertRaisesRegex(SolanaSponsorPolicyError, "bad_transaction"):
            self.service.validate_transaction(
                encoded, expected_user_signer=str(self.user.pubkey())
            )
        self.assertEqual(self.rpc_calls, [])

    def test_rejects_transaction_that_can_spend_sponsor_lamports(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program, sponsor_in_ix=True
        )
        with self.assertRaisesRegex(
            SolanaSponsorPolicyError, "sponsor_account_referenced"
        ):
            self.service.validate_transaction(
                encoded, expected_user_signer=str(self.user.pubkey())
            )

    def test_sponsor_reference_requires_exact_flow_policy(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program, sponsor_in_ix=True
        )
        with self.assertRaisesRegex(
            SolanaSponsorPolicyError, "sponsor_policy_required"
        ):
            self.service.validate_transaction(
                encoded,
                expected_user_signer=str(self.user.pubkey()),
                allow_sponsor_account_reference=True,
            )

        seen = []
        validated = self.service.validate_transaction(
            encoded,
            expected_user_signer=str(self.user.pubkey()),
            allow_sponsor_account_reference=True,
            policy_hook=lambda transaction: seen.append(transaction),
        )
        self.assertEqual(seen, [validated])

    def test_rejects_unregistered_user_signer(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program
        )
        with self.assertRaisesRegex(SolanaSponsorPolicyError, "wrong_user_signer"):
            self.service.validate_transaction(
                encoded, expected_user_signer=str(Keypair().pubkey())
            )

    def test_rejects_non_allowlisted_program(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, Pubkey.new_unique()
        )
        with self.assertRaisesRegex(SolanaSponsorPolicyError, "program_not_allowed"):
            self.service.validate_transaction(
                encoded, expected_user_signer=str(self.user.pubkey())
            )

    def test_empty_program_allowlist_is_generic(self):
        service = SolanaSponsorService(
            signer=_LocalSigner(self.sponsor),
            rpc_url="unused",
            rpc_call=lambda method, params: None,
            allowed_program_ids=[],
            max_fee_lamports=20_000,
            min_sponsor_balance_lamports=0,
        )
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, Pubkey.new_unique()
        )
        validated = service.validate_transaction(
            encoded, expected_user_signer=str(self.user.pubkey())
        )
        self.assertEqual(validated.user_signers, (str(self.user.pubkey()),))

    def test_rejects_fee_over_cap_before_kms_signing(self):
        self.service._rpc_override = lambda method, params: {
            "isBlockhashValid": {"value": True},
            "getFeeForMessage": {"value": 20_001},
        }[method]
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program
        )
        with self.assertRaisesRegex(SolanaSponsorPolicyError, "fee_too_high"):
            self.service.sponsor_and_send(
                encoded,
                expected_user_signer=str(self.user.pubkey()),
                fee_authorizer=lambda fee, balance, slot, validated: None,
            )

    def test_requires_durable_fee_authorization_before_broadcast(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program
        )
        with self.assertRaisesRegex(
            SolanaSponsorPolicyError, "fee_authorization_required"
        ):
            self.service.sponsor_and_send(
                encoded,
                expected_user_signer=str(self.user.pubkey()),
            )
        self.assertNotIn("sendTransaction", [call[0] for call in self.rpc_calls])

    def test_preserves_configured_sponsor_balance_floor(self):
        self.service.min_sponsor_balance_lamports = 999_995_000
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program
        )
        with self.assertRaisesRegex(SolanaSponsorPolicyError, "sponsor_balance_low"):
            self.service.sponsor_and_send(
                encoded,
                expected_user_signer=str(self.user.pubkey()),
                fee_authorizer=lambda fee, balance, slot, validated: None,
            )
        self.assertNotIn("simulateTransaction", [call[0] for call in self.rpc_calls])

    def test_reserves_fee_before_signing_or_exposing_wire_to_rpc(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program
        )

        def authorize(fee, balance, slot, validated):
            self.assertEqual(fee, 10_000)
            self.assertEqual(balance, 1_000_000_000)
            self.assertEqual(slot, 1)
            self.assertNotIn("simulateTransaction", [call[0] for call in self.rpc_calls])

        recorded = []
        self.service.sponsor_and_send(
            encoded,
            expected_user_signer=str(self.user.pubkey()),
            fee_authorizer=authorize,
            signature_recorder=lambda signature, validated: recorded.append(signature),
        )
        self.assertEqual(len(recorded), 1)

    def test_terminal_sent_retry_short_circuits_all_rpc_and_kms_work(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program
        )
        result = self.service.sponsor_and_send(
            encoded,
            expected_user_signer=str(self.user.pubkey()),
            fee_authorizer=lambda fee, balance, slot, validated: self.fail("reauthorized"),
            transaction_lookup=lambda validated: {
                "status": "sent",
                "signature": "5" * 64,
                "fee_lamports": 10_000,
            },
        )
        self.assertEqual(result["signature"], "5" * 64)
        self.assertEqual(self.rpc_calls, [])

    def test_unknown_retry_reconciles_known_signature(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program
        )
        signature = "6" * 64
        self.service._rpc_override = lambda method, params: {
            "getSignatureStatuses": {
                "value": [{"slot": 1, "confirmations": 1, "err": None}]
            }
        }[method]
        result = self.service.sponsor_and_send(
            encoded,
            expected_user_signer=str(self.user.pubkey()),
            fee_authorizer=lambda fee, balance, slot, validated: self.fail("reauthorized"),
            transaction_lookup=lambda validated: {
                "status": "unknown",
                "signature": signature,
                "fee_lamports": 10_000,
            },
        )
        self.assertEqual(result["signature"], signature)

    def test_rejects_rpc_signature_mismatch_and_retains_local_signature(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program
        )
        original_rpc = self.service._rpc_override

        def mismatching_rpc(method, params):
            if method == "sendTransaction":
                return "4" * 64
            return original_rpc(method, params)

        self.service._rpc_override = mismatching_rpc
        recorded = []
        with self.assertRaisesRegex(
            SolanaSponsorPolicyError, "broadcast_signature_mismatch"
        ):
            self.service.sponsor_and_send(
                encoded,
                expected_user_signer=str(self.user.pubkey()),
                fee_authorizer=lambda fee, balance, slot, validated: None,
                signature_recorder=lambda signature, validated: recorded.append(signature),
            )
        self.assertEqual(len(recorded), 1)
        self.assertNotEqual(recorded[0], "4" * 64)

    def test_rejects_negative_rpc_fee_before_authorization(self):
        encoded = _partially_signed_transaction(
            self.sponsor, self.user, self.program
        )
        self.service._rpc_override = lambda method, params: {
            "isBlockhashValid": {"value": True},
            "getFeeForMessage": {"value": -1},
        }[method]
        with self.assertRaisesRegex(SolanaSponsorPolicyError, "invalid_fee"):
            self.service.sponsor_and_send(
                encoded,
                expected_user_signer=str(self.user.pubkey()),
                fee_authorizer=lambda fee, balance, slot, validated: self.fail("authorized"),
            )


class _FakeKms:
    def __init__(self):
        self.private_key = Ed25519PrivateKey.generate()

    def get_public_key(self, **kwargs):
        public_der = self.private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return {
            "KeySpec": "ECC_NIST_EDWARDS25519",
            "KeyUsage": "SIGN_VERIFY",
            "PublicKey": public_der,
        }

    def sign(self, **kwargs):
        if kwargs["MessageType"] != "RAW" or kwargs["SigningAlgorithm"] != "ED25519_SHA_512":
            raise AssertionError("wrong KMS Ed25519 signing parameters")
        return {"Signature": self.private_key.sign(kwargs["Message"])}


class SolanaKMSSignerTests(unittest.TestCase):
    def test_native_ed25519_signature_and_address(self):
        signer = SolanaKMSSigner("test", kms_client=_FakeKms())
        message = b"solana message bytes"
        signature = signer.sign_message(message)
        self.assertEqual(len(signature), 64)
        self.assertEqual(len(Pubkey.from_string(signer.address).__bytes__()), 32)


class CusdPlusSponsorPolicyTests(unittest.TestCase):
    def test_exact_deposit_instruction_can_reference_fee_payer(self):
        sponsor = Keypair()
        user = Keypair()
        program = Pubkey.new_unique()
        usdy_mint = Pubkey.new_unique()
        cusd_mint = Pubkey.new_unique()
        reserve = Pubkey.new_unique()
        config, _ = Pubkey.find_program_address([b"config"], program)
        vault_authority, _ = Pubkey.find_program_address([b"vault-authority"], program)
        sponsor_record, _ = Pubkey.find_program_address(
            [b"sponsor", bytes(sponsor.pubkey())], program
        )
        accounts = [
            AccountMeta(user.pubkey(), True, True),
            AccountMeta(sponsor.pubkey(), True, False),
            AccountMeta(sponsor_record, False, False),
            AccountMeta(config, False, False),
            AccountMeta(vault_authority, False, False),
            AccountMeta(usdy_mint, False, False),
            AccountMeta(cusd_mint, False, True),
            AccountMeta(Pubkey.new_unique(), False, True),
            AccountMeta(Pubkey.new_unique(), False, True),
            AccountMeta(reserve, False, True),
            AccountMeta(Pubkey.from_string(TOKEN_PROGRAM), False, False),
            AccountMeta(Pubkey.from_string(TOKEN_PROGRAM), False, False),
        ]
        data = (
            DEPOSIT_AND_MINT_DISCRIMINATOR
            + (1_000_000).to_bytes(8, "little")
            + (900_000).to_bytes(8, "little")
        )
        instruction = Instruction(program, data, accounts)
        message = MessageV0.try_compile(
            sponsor.pubkey(), [instruction], [], Hash.new_unique()
        )
        tx = VersionedTransaction(
            message, [NullSigner(sponsor.pubkey()), user]
        )
        encoded = base64.b64encode(bytes(tx)).decode("ascii")
        policy = CusdPlusDepositPolicy(
            program_id=str(program),
            usdy_mint=str(usdy_mint),
            cusd_mint=str(cusd_mint),
            reserve=str(reserve),
            max_usdy_base_units=2_000_000,
        )
        service = SolanaSponsorService(
            signer=_LocalSigner(sponsor),
            rpc_url="unused",
            rpc_call=lambda method, params: None,
            allowed_program_ids=[],
            max_fee_lamports=20_000,
            min_sponsor_balance_lamports=0,
        )
        validated = service.validate_transaction(
            encoded,
            expected_user_signer=str(user.pubkey()),
            policy_hook=policy,
            allow_sponsor_account_reference=True,
        )
        self.assertEqual(validated.program_ids, (str(program),))

    def test_depositor_must_be_the_registered_user_not_an_extra_signer(self):
        sponsor = Keypair()
        registered_user = Keypair()
        unrelated_depositor = Keypair()
        program = Pubkey.new_unique()
        usdy_mint = Pubkey.new_unique()
        cusd_mint = Pubkey.new_unique()
        reserve = Pubkey.new_unique()
        config, _ = Pubkey.find_program_address([b"config"], program)
        vault_authority, _ = Pubkey.find_program_address([b"vault-authority"], program)
        sponsor_record, _ = Pubkey.find_program_address(
            [b"sponsor", bytes(sponsor.pubkey())], program
        )
        deposit_accounts = [
            AccountMeta(unrelated_depositor.pubkey(), True, True),
            AccountMeta(sponsor.pubkey(), True, False),
            AccountMeta(sponsor_record, False, False),
            AccountMeta(config, False, False),
            AccountMeta(vault_authority, False, False),
            AccountMeta(usdy_mint, False, False),
            AccountMeta(cusd_mint, False, True),
            AccountMeta(Pubkey.new_unique(), False, True),
            AccountMeta(Pubkey.new_unique(), False, True),
            AccountMeta(reserve, False, True),
            AccountMeta(Pubkey.from_string(TOKEN_PROGRAM), False, False),
            AccountMeta(Pubkey.from_string(TOKEN_PROGRAM), False, False),
        ]
        deposit = Instruction(
            program,
            DEPOSIT_AND_MINT_DISCRIMINATOR
            + (1_000_000).to_bytes(8, "little")
            + (900_000).to_bytes(8, "little"),
            deposit_accounts,
        )
        harmless_cosign = Instruction(
            Pubkey.new_unique(),
            b"cosign",
            [AccountMeta(registered_user.pubkey(), True, False)],
        )
        message = MessageV0.try_compile(
            sponsor.pubkey(), [deposit, harmless_cosign], [], Hash.new_unique()
        )
        tx = VersionedTransaction(
            message,
            [NullSigner(sponsor.pubkey()), unrelated_depositor, registered_user],
        )
        encoded = base64.b64encode(bytes(tx)).decode("ascii")
        policy = CusdPlusDepositPolicy(
            program_id=str(program),
            usdy_mint=str(usdy_mint),
            cusd_mint=str(cusd_mint),
            reserve=str(reserve),
            max_usdy_base_units=2_000_000,
        )
        service = SolanaSponsorService(
            signer=_LocalSigner(sponsor),
            rpc_url="unused",
            rpc_call=lambda method, params: None,
            allowed_program_ids=[],
            max_fee_lamports=20_000,
            min_sponsor_balance_lamports=0,
        )
        with self.assertRaisesRegex(
            SolanaSponsorPolicyError, "bad_cusd_plus_depositor"
        ):
            service.validate_transaction(
                encoded,
                expected_user_signer=str(registered_user.pubkey()),
                policy_hook=policy,
                allow_sponsor_account_reference=True,
            )


if __name__ == "__main__":
    unittest.main()
