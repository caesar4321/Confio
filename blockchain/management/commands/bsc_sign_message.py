"""
Sign an arbitrary message with the BSC KMS sponsor key (EIP-191
personal_sign format).

Built for explorer address-ownership verification: BscScan/Etherscan's
"token info update" flow asks for a message (containing their nonce)
signed by the contract DEPLOYER — which for Confío's BSC contracts is the
non-extractable KMS sponsor, so no wallet can produce this signature.
Paste the message they display here, paste the printed signature there.

Usage:
  myvenv/bin/python manage.py bsc_sign_message "message text from the form"
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "EIP-191 personal_sign a message with the BSC KMS sponsor key"

    def add_arguments(self, parser):
        parser.add_argument("message", help="Exact message text to sign (verbatim from the verification form)")

    def handle(self, *args, **options):
        from eth_utils import keccak

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        message = options["message"].encode()
        digest = keccak(b"\x19Ethereum Signed Message:\n" + str(len(message)).encode() + message)

        signer = get_bsc_sponsor_signer_from_settings()
        v, r, s = signer.sign_digest(digest)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v + 27])

        self.stdout.write(f"Signer:    {signer.address}")
        self.stdout.write(f"Message:   {options['message']!r}")
        self.stdout.write(f"Signature: 0x{signature.hex()}")
