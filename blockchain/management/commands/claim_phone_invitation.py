from django.core.management.base import BaseCommand
from django.conf import settings
from algosdk.v2client import algod
from algosdk import mnemonic
from algosdk import transaction
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    TransactionWithSigner,
    AccountTransactionSigner,
)
from blockchain.invite_send_transaction_builder import InviteSendTransactionBuilder
from send.models import PhoneInvite
from django.utils import timezone


class Command(BaseCommand):
    help = "Admin claim of an existing phone invite by phone number. Releases escrow to the provided address or the admin address."

    def add_arguments(self, parser):
        parser.add_argument('--phone', required=True, help='Phone number digits (e.g., 9293993619)')
        parser.add_argument('--phone-country', dest='phone_country', default=None, help='ISO country code (e.g., US) or calling code (+1)')
        parser.add_argument('--recipient-address', dest='recipient_address', default=None, help='Algorand address to receive funds; defaults to admin address')

    def handle(self, *args, **options):
        phone = options['phone']
        phone_country = options.get('phone_country')
        recipient_address = options.get('recipient_address')

        admin_mn = getattr(settings, 'ALGORAND_ADMIN_MNEMONIC', None)
        if not admin_mn:
            self.stderr.write(self.style.ERROR('ALGORAND_ADMIN_MNEMONIC is not set in settings'))
            return

        from blockchain.algorand_client import get_algod_client
        algod_client = get_algod_client()
        builder = InviteSendTransactionBuilder()

        # Find invitation_id by probing canonical and legacy keys
        canonical_key = builder.normalize_phone(phone, phone_country)
        digits_only = ''.join(ch for ch in (phone or '') if ch.isdigit())
        candidates = [builder.make_invitation_id(canonical_key)]
        try:
            from users.country_codes import COUNTRY_CODES
            cc = canonical_key.split(':', 1)[0]
            isos_with_cc = [row[2] for row in COUNTRY_CODES if row[1].replace('+', '') == cc]
            for iso in isos_with_cc:
                candidates.append(builder.make_invitation_id(f"{iso}:{digits_only}"))
        except Exception:
            pass

        invitation_id = None
        for cand in candidates:
            try:
                _ = algod_client.application_box_by_name(builder.app_id, cand.encode())
                invitation_id = cand
                break
            except Exception:
                continue

        if not invitation_id:
            self.stdout.write(self.style.WARNING('No on-chain invitation found for this phone'))
            return

        from algosdk import account as _acct
        admin_sk = mnemonic.to_private_key(admin_mn)
        admin_addr = _acct.address_from_private_key(admin_sk)
        recv = recipient_address or admin_addr

        params = algod_client.suggested_params()
        min_fee = getattr(params, 'min_fee', 1000) or 1000

        pay0 = transaction.PaymentTxn(
            sender=admin_addr,
            sp=transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True),
            receiver=admin_addr,
            amt=0
        )

        contract = builder.contract
        method = next((m for m in contract.methods if m.name == 'claim_invitation'), None)
        if method is None:
            self.stderr.write(self.style.ERROR('ABI method claim_invitation not found'))
            return

        atc = AtomicTransactionComposer()
        atc.add_transaction(TransactionWithSigner(pay0, AccountTransactionSigner(admin_sk)))
        atc.add_method_call(
            app_id=builder.app_id,
            method=method,
            sender=admin_addr,
            sp=transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True),
            signer=AccountTransactionSigner(admin_sk),
            method_args=[invitation_id, recv],
        )

        res = atc.execute(algod_client, 10)
        txid = res.tx_ids[-1] if res.tx_ids else ''
        self.stdout.write(self.style.SUCCESS(f'Claimed invitation {invitation_id}, txid={txid}'))

        # Update PhoneInvite if present
        try:
            inv = PhoneInvite.objects.filter(invitation_id=invitation_id).first()
            if inv:
                inv.status = 'claimed'
                inv.claimed_at = timezone.now()
                inv.claimed_txid = txid
                inv.save(update_fields=['status', 'claimed_at', 'claimed_txid', 'updated_at'])
        except Exception:
            pass

