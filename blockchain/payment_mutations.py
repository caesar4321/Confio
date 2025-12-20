"""
Payment Contract GraphQL Mutations
Handles sponsored payments through the payment smart contract
"""
import graphene
import logging
import json
from decimal import Decimal
from typing import Optional
from django.conf import settings
from django.db import transaction as db_transaction
from users.models import Account, User
from .models import Payment, PaymentReceipt
from .payment_transaction_builder import PaymentTransactionBuilder
from .algorand_account_manager import AlgorandAccountManager
from algosdk.v2client import algod
from algosdk import account, encoding
from blockchain.kms_manager import get_kms_signer_from_settings
import asyncio
import base64
import msgpack
import time

logger = logging.getLogger(__name__)
SPONSOR_SIGNER = get_kms_signer_from_settings()


class CreateSponsoredPaymentMutation(graphene.Mutation):
    """
    Create a sponsored payment through the payment contract.
    The sponsor pays fees on behalf of the user, and the contract deducts 0.9% fee.
    Payments are always FROM personal/business accounts TO business accounts.
    The recipient business is determined from JWT context.
    Returns unsigned user transactions and signed sponsor transaction for atomic group.
    """
    
    class Arguments:
        amount = graphene.Float(required=True, description="Amount to send (before fees)")
        asset_type = graphene.String(required=False, default_value='CUSD', description="CUSD or CONFIO")
        internal_id = graphene.String(required=False, description="Optional payment ID for tracking")
        note = graphene.String(required=False, description="Optional transaction note")
        create_receipt = graphene.Boolean(required=False, default_value=False, description="Store payment receipt on-chain")
    
    success = graphene.Boolean()
    error = graphene.String()
    transactions = graphene.JSONString(description="Array of transaction objects to sign")
    user_signing_indexes = graphene.List(graphene.Int, description="Indexes of transactions user must sign")
    group_id = graphene.String()
    gross_amount = graphene.Float(description="Amount user pays")
    net_amount = graphene.Float(description="Amount recipient receives after 0.9% fee")
    fee_amount = graphene.Float(description="0.9% fee deducted by contract")
    internal_id = graphene.String(description="Payment ID for tracking")
    
    @classmethod
    def mutate(cls, root, info, amount, asset_type='CUSD', internal_id=None, 
              note=None, create_receipt=False):
        try:
            t0 = time.time()
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Firebase App Check (Warning Mode)
            from security.integrity_service import app_check_service
            app_check_service.verify_request_header(info.context, action='transfer', should_enforce=False)
            
            # Get JWT context for SENDER account determination
            from users.jwt_context import get_jwt_business_context_with_validation
            
            # First try to get sender context without permission check
            sender_jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            if not sender_jwt_context:
                return cls(success=False, error='Invalid JWT token or no access')
            
            # For business accounts, check send_funds permission separately
            if sender_jwt_context['account_type'] == 'business':
                # Re-validate with send_funds permission for business accounts
                business_context = get_jwt_business_context_with_validation(info, required_permission='send_funds')
                if not business_context:
                    return cls(success=False, error='No permission to send funds from business account')
                sender_jwt_context = business_context
            
            sender_account_type = sender_jwt_context['account_type']
            sender_account_index = sender_jwt_context['account_index']  # Must be present in JWT
            sender_business_id = sender_jwt_context.get('business_id')
            
            logger.info(f"Payment sender context: type={sender_account_type}, index={sender_account_index}, business_id={sender_business_id}")
            
            # Validate that we have the required context
            if sender_account_index is None:
                return cls(success=False, error='Missing account_index in JWT token')
            
            # Get the sender's account based on JWT context
            if sender_account_type == 'business' and sender_business_id:
                from users.models import Business
                try:
                    sender_business = Business.objects.get(id=sender_business_id)
                    sender_account = Account.objects.get(
                        business=sender_business,
                        account_type='business'
                    )
                except (Business.DoesNotExist, Account.DoesNotExist):
                    return cls(success=False, error='Sender business account not found')
            else:
                # Personal account sending - use exact account_index from JWT
                sender_account = Account.objects.filter(
                    user=user,
                    account_type=sender_account_type,
                    account_index=sender_account_index,
                    deleted_at__isnull=True
                ).first()
                
                logger.info(f"Looking up personal account: user={user.id}, type={sender_account_type}, index={sender_account_index}")
            
            if not sender_account or not sender_account.algorand_address:
                return cls(success=False, error='Sender Algorand address not found')
            
            # Validate sender's address format
            if len(sender_account.algorand_address) != 58:
                return cls(success=False, error='Invalid sender Algorand address format')
            
            # Get RECIPIENT business from context
            # For invoice payments, the recipient business comes from the invoice
            # For direct payments, it would come from JWT or request headers
            recipient_business_id = sender_jwt_context.get('recipient_business_id')
            
            # Try alternative sources for recipient business ID
            if not recipient_business_id:
                # Check request headers (set by PayInvoice mutation)
                request = info.context
                recipient_business_id = request.META.get('HTTP_X_RECIPIENT_BUSINESS_ID')
                
            # If still missing but we have internal_id (Invoice ID), verify if it matches an Invoice
            if not recipient_business_id and internal_id:
                from payments.models import Invoice
                # Try to find invoice by ID
                inv = Invoice.objects.filter(internal_id=internal_id).first()
                if inv and inv.merchant_business:
                    recipient_business_id = str(inv.merchant_business.id)
                    logger.info(f"Resolved recipient business {recipient_business_id} from Invoice {internal_id}")

            if not recipient_business_id:
                # For debugging - log available context
                logger.warning(f"No recipient_business_id found in context. JWT context: {sender_jwt_context}")
                logger.warning(f"Request META keys: {list(request.META.keys())}")
                return cls(success=False, error='Recipient business not specified in payment context')
            
            # Get recipient business account
            from users.models import Business
            try:
                recipient_business = Business.objects.get(id=recipient_business_id)
                recipient_account = Account.objects.get(
                    business=recipient_business,
                    account_type='business'
                )
                if not recipient_account.algorand_address:
                    return cls(success=False, error='Recipient business has no Algorand address')
                
                resolved_recipient_address = recipient_account.algorand_address
                logger.info(f"Payment from {sender_account_type} to business {recipient_business.name}: {resolved_recipient_address[:10]}...")
                
            except Business.DoesNotExist:
                return cls(success=False, error='Recipient business not found')
            except Account.DoesNotExist:
                return cls(success=False, error='Recipient business account not found')
            
            # Normalize token to canonical DB form
            asset_type_upper = str(asset_type or 'CUSD').upper()
            token_type_value = 'CUSD' if asset_type_upper == 'CUSD' else asset_type_upper

            # Initialize payment transaction builder
            builder = PaymentTransactionBuilder(network=settings.ALGORAND_NETWORK)
            
            # Determine asset ID
            # Determine asset ID from normalized token
            if asset_type_upper == 'CUSD':
                asset_id = builder.cusd_asset_id
            elif asset_type_upper == 'CONFIO':
                asset_id = builder.confio_asset_id
            else:
                return cls(success=False, error=f'Unsupported asset type: {asset_type}')
            
            logger.info(f"Payment mutation: Using asset ID {asset_id} for {token_type_value}")
            
            if not asset_id:
                return cls(success=False, error=f'{asset_type} not configured on this network')
            
            # Preflight: verify payment app configuration/compatibility
            preflight = builder.validate_payment_app(asset_id)
            if not preflight.get('success'):
                logger.error(f"Payment app preflight failed: {preflight.get('error')}")
                return cls(success=False, error=f"Payment app is not compatible/ready: {preflight.get('error')}")
            else:
                info_map = preflight.get('info') or {}
                logger.info(
                    f"Payment app preflight OK: app={info_map.get('app_id')}, "
                    f"confio={info_map.get('confio_asset_id')}, cusd={info_map.get('cusd_asset_id')}, "
                    f"fee_recipient={info_map.get('fee_recipient')}, sponsor={info_map.get('sponsor_address')}, "
                    f"approval_sha256={info_map.get('approval_sha256')}"
                )

            # Check sender has opted into the asset
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            # Optional MBR funding (disabled by default to avoid latency and confirmation wait)
            if getattr(settings, 'PAYMENT_MBR_CHECK_ENABLED', False):
                from blockchain.account_funding_service import account_funding_service
                funding_needed = account_funding_service.calculate_funding_needed(
                    sender_account.algorand_address,
                    for_app_optin=False  # For payment transactions
                )
                if funding_needed > 0:
                    logger.info(f"Account needs {funding_needed} microAlgos for MBR, funding...")
                    funding_result = account_funding_service.fund_account_for_optin(sender_account.algorand_address)
                    if not funding_result['success']:
                        logger.error(f"Failed to fund account: {funding_result.get('error')}")
                        return cls(success=False, error='Failed to fund account for minimum balance')
                    logger.info(f"Successfully funded account with {funding_result.get('amount_funded')} microAlgos")
            
            account_info = algod_client.account_info(sender_account.algorand_address)
            assets = account_info.get('assets', [])
            
            # Check balance (users are already opted-in during sign-up)
            asset_balance = next((asset['amount'] for asset in assets if asset['asset-id'] == asset_id), 0)
            # Cache asset_info to reduce network round-trips
            try:
                from .utils.cache import ttl_cache
                akey = ("asset_info", asset_id, AlgorandAccountManager.ALGOD_ADDRESS)
                asset_info = ttl_cache.get(akey)
                if not asset_info:
                    asset_info = algod_client.asset_info(asset_id)
                    ttl_cache.set(akey, asset_info, ttl_seconds=300.0)
            except Exception:
                asset_info = algod_client.asset_info(asset_id)
            decimals = asset_info['params'].get('decimals', 6)
            
            # Convert amount to base units
            amount_in_base = int(Decimal(str(amount)) * Decimal(10 ** decimals))
            balance_in_base = asset_balance
            
            if balance_in_base < amount_in_base:
                balance_formatted = balance_in_base / (10 ** decimals)
                return cls(
                    success=False,
                    error=f'Insufficient {asset_type} balance. You have {balance_formatted} but trying to send {amount}'
                )
            
            # Calculate net amount after 0.9% fee
            net_amount_base, fee_amount_base = builder.calculate_net_amount(amount_in_base)
            
            # Generate payment ID if not provided and receipt requested
            if create_receipt and not internal_id:
                import uuid
                internal_id = str(uuid.uuid4())
            
            # Create payment record in database for business payment
            payment_record = None
            if internal_id:
                # Idempotent creation of blockchain.Payment record by unique internal_id
                from django.db import IntegrityError
                with db_transaction.atomic():
                    # Get business owner for recipient tracking
                    recipient_user = recipient_business.owner if hasattr(recipient_business, 'owner') else None
                    defaults = {
                        'sender': user,
                        'sender_business': sender_business if sender_account_type == 'business' else None,
                        'recipient': recipient_user,
                        'recipient_business': recipient_business,
                        'amount': Decimal(str(amount)),
                        'currency': token_type_value,
                        'status': 'pending',
                        'blockchain_network': 'algorand',
                        'sender_address': sender_account.algorand_address,
                        'recipient_address': resolved_recipient_address,
                        'note': note or f"Payment to {recipient_business.name}",
                        'fee_amount': Decimal(str(fee_amount_base / (10 ** decimals))),
                        'net_amount': Decimal(str(net_amount_base / (10 ** decimals))),
                    }
                    try:
                        payment_record, created = Payment.objects.get_or_create(
                            internal_id=internal_id,
                            defaults=defaults,
                        )
                        if created:
                            logger.info(f"Created payment record {internal_id} for {amount} {asset_type} to business {recipient_business.name}")
                        else:
                            logger.info(f"Reusing existing payment record {internal_id}")
                    except IntegrityError:
                        payment_record = Payment.objects.filter(internal_id=internal_id).first()
                        logger.info(f"Payment record {internal_id} already exists; continuing idempotently")
            
            # Build sponsored payment transaction group using cUSD pattern
            try:
                tx_result = builder.build_sponsored_payment_cusd_style(
                    sender_address=sender_account.algorand_address,
                    recipient_address=resolved_recipient_address,
                    amount=amount_in_base,
                    asset_id=asset_id,
                    internal_id=internal_id if create_receipt else None,
                    note=note
                )
                
                if not tx_result.get('success'):
                    if payment_record:
                        payment_record.status = 'failed'
                        payment_record.save()
                    return cls(success=False, error=tx_result.get('error', 'Failed to build transactions'))
                
            except Exception as e:
                if payment_record:
                    payment_record.status = 'failed'
                    payment_record.save()
                raise e
            
            # Mark payment as pending signature (ready for client)
            if payment_record:
                payment_record.status = 'pending_signature'
                payment_record.save()
            
            # Handle new structure with sponsor_transactions array (like cUSD)
            sponsor_txns = tx_result.get('sponsor_transactions', [])
            
            logger.info(
                f"Created sponsored payment for user {user.id}: "
                f"{amount} {asset_type} from {sender_account.algorand_address[:10]}... "
                f"to {resolved_recipient_address[:10]}... "
                f"(gross: {amount_in_base / (10 ** decimals)}, net: {net_amount_base / (10 ** decimals)}, "
                f"fee: {fee_amount_base / (10 ** decimals)})"
            )
            
            # SOLUTION 1: Return ALL 4 transactions to frontend (sponsor ones pre-signed)
            # This ensures all transactions use the SAME chain parameters
            
            transaction_data = []
            
            # Add sponsor transactions (already signed if mnemonic available)
            sponsor_txns = tx_result.get('sponsor_transactions', [])
            for sp_txn in sponsor_txns:
                idx = sp_txn['index']
                # Use signed version if available, otherwise use unsigned
                # Both are base64 encoded from msgpack_encode
                txn_data = sp_txn['signed'] if sp_txn['signed'] else sp_txn['txn']
                is_signed = bool(sp_txn['signed'])
                
                transaction_data.append({
                    'index': idx,
                    'type': 'payment' if idx == 0 else 'application',
                    'transaction': txn_data,
                    'signed': is_signed,  # True only if actually signed
                    'needs_signature': not is_signed,  # Need signature if not signed
                    'message': 'Sponsor payment' if idx == 0 else 'App call'
                })
            
            # Add user transactions (need signing)
            user_txns = tx_result.get('transactions_to_sign', [])
            for i, user_txn in enumerate(user_txns):
                transaction_data.append({
                    'index': i + 1,  # User transactions at index 1 and 2
                    'type': 'asset_transfer',
                    'transaction': base64.b64encode(user_txn['txn']).decode() if isinstance(user_txn['txn'], bytes) else user_txn['txn'],
                    'signed': False,
                    'needs_signature': True,
                    'message': user_txn.get('message', f'Transaction {i+1}')
                })
            
            # Create PaymentTransaction after building all transaction data
            generated_internal_id = None  # Initialize for scope
            if internal_id:
                from payments.models import PaymentTransaction, Invoice
                # Resolve invoice by invoice_id (internal_id param is used as invoiceId in this flow)
                invoice_obj = Invoice.objects.filter(internal_id=internal_id).first()
                
                if not invoice_obj:
                     raise ValueError(f"Invoice not found for invoice_id {internal_id}")

                # Determine merchant/payer accounts from prior variables
                # sender_account, recipient_business, recipient_account were resolved above
                payer_user = user
                # Prefer the actual account user tied to the merchant business account
                merchant_user = getattr(recipient_account, 'user', None)
                # Best-effort phone composition for payer
                payer_phone_display = ''
                try:
                    cc = getattr(payer_user, 'phone_country_code', None)
                    pn = getattr(payer_user, 'phone_number', None)
                    if pn:
                        payer_phone_display = f"+{cc}{pn}" if cc else str(pn)
                except Exception:
                    pass
                # Build a unique placeholder hash to satisfy unique constraint before submit
                placeholder_hash = f"pending_blockchain_{invoice_obj.internal_id}_{int(time.time()*1000)}"
                # Assemble minimal defaults
                defaults = {
                    'payer_user': payer_user,
                    'merchant_account_user': merchant_user,
                    'payer_business': getattr(sender_account, 'business', None) if sender_account_type == 'business' else None,
                    'merchant_business': recipient_business,
                    'payer_type': 'user' if sender_account_type != 'business' else 'business',
                    'merchant_type': 'business',
                    # Use business name if business account, else user name
                    'payer_display_name': getattr(getattr(sender_account, 'business', None), 'name', '') if sender_account_type == 'business' else (f"{(payer_user.first_name or '').strip()} {(payer_user.last_name or '').strip()}".strip() or payer_user.username),
                    'merchant_display_name': getattr(recipient_business, 'name', ''),
                    'payer_phone': payer_phone_display,
                    'payer_account': sender_account,
                    'merchant_account': recipient_account,
                    'payer_address': sender_account.algorand_address,
                    'merchant_address': resolved_recipient_address,
                    'amount': Decimal(str(amount)),
                    'token_type': token_type_value,
                    'description': note or '',
                    'status': 'PENDING_BLOCKCHAIN',
                    'transaction_hash': placeholder_hash,
                    'blockchain_data': transaction_data,
                    'idempotency_key': None,
                    # internal_id is NOT specified here - model will auto-generate UUID
                }
                # Create if missing - lookup by invoice + payer for idempotency
                payment_tx, created = PaymentTransaction.objects.get_or_create(
                    invoice=invoice_obj,
                    payer_user=payer_user,
                    defaults=defaults
                )
                # Use the model's auto-generated UUID internal_id
                generated_internal_id = payment_tx.internal_id
                logger.info(f"PaymentTransaction {'created' if created else 'found'}: internal_id={generated_internal_id}, invoice={invoice_obj.internal_id}")

            return cls(
                success=True,
                transactions=transaction_data,  # ALL 4 transactions (sponsor pre-signed)
                user_signing_indexes=[1, 2],  # User signs transactions at index 1 and 2
                group_id=tx_result.get('group_id'),
                gross_amount=amount_in_base / (10 ** decimals),
                net_amount=net_amount_base / (10 ** decimals),
                fee_amount=fee_amount_base / (10 ** decimals),
                internal_id=generated_internal_id  # Return the UUID, not Invoice ID
            )
            
        except Exception as e:
            logger.error(f'Error creating sponsored payment: {str(e)}', exc_info=True)
            return cls(success=False, error=str(e))


class SubmitSponsoredPaymentMutation(graphene.Mutation):
    """
    Submit a complete sponsored payment transaction group after client signing.
    Accepts the full transaction group with user signatures.
    """
    
    class Arguments:
        signed_transactions = graphene.JSONString(
            required=True,
            description="Array of base64 encoded signed transactions in group order"
        )
        internal_id = graphene.String(required=False, description="Payment ID for database update")
    
    success = graphene.Boolean()
    error = graphene.String()
    transaction_id = graphene.String()
    confirmed_round = graphene.Int()
    net_amount = graphene.Float()
    fee_amount = graphene.Float()
    
    @classmethod  
    def mutate(cls, root, info, signed_transactions, internal_id=None):
        try:
            t0 = time.time()
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            verbose = getattr(settings, 'PAYMENT_VERBOSE_LOGS', False)
            logger.info(f"Submitting sponsored payment group for user {user.id}")
            logger.info(f"Raw signed_transactions type: {type(signed_transactions)}")
            if verbose:
                logger.info(f"Raw signed_transactions: {signed_transactions[:200] if isinstance(signed_transactions, str) else str(signed_transactions)[:200]}")
            
            # Parse the signed_transactions - it might be a JSON string
            t_parse_start = time.time()
            import msgpack
            import json
            from algosdk import transaction, encoding
            from algosdk.transaction import SuggestedParams
            from algosdk.abi import Method, Argument, Returns
            from blockchain.payment_transaction_builder import PaymentTransactionBuilder
            
            # If it's a string, parse it as JSON
            if isinstance(signed_transactions, str):
                try:
                    signed_transactions = json.loads(signed_transactions)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse signed_transactions JSON: {e}")
                    return cls(success=False, error='Invalid transaction format')
            
            # Extract transactions from the format sent by frontend
            # Frontend sends: list of dicts with {index, transaction}
            sorted_txn_dicts = None
            if isinstance(signed_transactions, list) and len(signed_transactions) > 0:
                if isinstance(signed_transactions[0], dict) and 'transaction' in signed_transactions[0]:
                    logger.info(f"Extracting transactions from index/transaction format")
                    # Sort by index to ensure correct order
                    sorted_txn_dicts = sorted(signed_transactions, key=lambda x: x.get('index', 0))
                    # Log the indices we received
                    received_indices = [txn.get('index', -1) for txn in sorted_txn_dicts]
                    if verbose:
                        logger.info(f"Received transactions with indices: {received_indices}")
                    # Also create a simple list of strings for legacy 2-txn path
                    signed_transactions = [txn['transaction'] for txn in sorted_txn_dicts]
                    if verbose:
                        logger.info(f"Prepared {len(signed_transactions)} transaction strings for legacy path")
            
            # SOLUTION 1: Accept all 4 transactions from client (sponsor ones already signed)
            t_prebuild_start = time.time()
            # This ensures all transactions have the SAME chain parameters
            
            dict_count = len(sorted_txn_dicts) if isinstance(sorted_txn_dicts, list) else 0
            if verbose:
                logger.info(f"Transaction count (dicts): {dict_count} | (strings): {len(signed_transactions) if isinstance(signed_transactions, list) else 'n/a'}")
            
            # Check if we received all 4 transactions (new approach)
            if isinstance(sorted_txn_dicts, list) and len(sorted_txn_dicts) == 4:
                logger.info("Received complete 4-txn payment group (sponsor pre-signed)")
                # Extract raw bytes from each transaction
                signed_txn_objects = []
                for i, txn_data in enumerate(sorted_txn_dicts):
                    txn_b64 = txn_data.get('transaction')
                    
                    try:
                        # Decode base64 to get raw bytes
                        decoded_bytes = base64.b64decode(txn_b64)
                        signed_txn_objects.append(decoded_bytes)
                        if verbose:
                            logger.info(f"  Transaction {i}: decoded successfully")
                    except Exception as e:
                        logger.error(f"Failed to decode transaction {i}: {e}")
                        raise
                
                if verbose:
                    logger.info("All 4 transactions ready for submission")
                
            elif len(signed_transactions) == 2:
                logger.error("Received only 2 transactions - this is no longer supported!")
                return cls(success=False, error='Invalid transaction count. Expected 4 transactions for payment group, received 2.')
                
                # ===== OPTION B: DETERMINISTIC REBUILD OF SPONSOR TRANSACTIONS =====
                # Recipe: Extract ALL parameters from user txns to rebuild exact same group
                # Decode user transactions to inspect payer + group id
                decoded_user_txns = []
                for txn_b64 in signed_transactions:
                    # At this point, signed_transactions is a list of base64 strings
                    decoded = base64.b64decode(txn_b64)
                    decoded_user_txns.append(decoded)
                
                # Debug: Log what transactions we received
                logger.info(f"=== USER TRANSACTION ORDER DEBUG ===")
                for i, txn_bytes in enumerate(decoded_user_txns):
                    txn_data = msgpack.unpackb(txn_bytes, raw=False)
                    if 'txn' in txn_data:
                        txn = txn_data['txn']
                        sender = encoding.encode_address(txn.get('snd', b''))
                        group_id = base64.b64encode(txn.get('grp', b'')).decode() if txn.get('grp') else 'None'
                        if txn.get('arcv'):  # Asset transfer
                            receiver = encoding.encode_address(txn.get('arcv', b''))
                            amount = txn.get('aamt', 0)
                            logger.info(f"User txn[{i}]: AXFER from {sender[:10]}... to {receiver[:10]}..., amount={amount}, grp={group_id[:10]}...")
                        else:
                            logger.info(f"User txn[{i}]: Type={txn.get('type')}, Sender={sender[:10]}..., grp={group_id[:10]}...")
                
                # Parse the first user transaction (merchant AXFER) to get the payer address and group id
                user_txn_dict = msgpack.unpackb(decoded_user_txns[0], raw=False)
                if 'txn' not in user_txn_dict:
                    return cls(success=False, error='Invalid user transaction format')

                user_txn = user_txn_dict['txn']
                user_address = encoding.encode_address(user_txn.get('snd', b''))
                group_id_bytes = user_txn.get('grp')
                logger.info(f"=== GROUP ID DEBUG ===")
                logger.info(f"Group ID from user txn: {base64.b64encode(group_id_bytes).decode() if group_id_bytes else 'None'}")

                # Rebuild and re-sign sponsor transactions deterministically (Option B)
                # Extract fields from user AXFER[0]
                asset_id = user_txn.get('xaid', 0)
                recipient_bytes = user_txn.get('arcv', b'')
                if not isinstance(recipient_bytes, (bytes, bytearray)) or len(recipient_bytes) != 32:
                    return cls(success=False, error='Invalid recipient in user transaction')
                recipient_address = encoding.encode_address(recipient_bytes)

                builder = PaymentTransactionBuilder(network=settings.ALGORAND_NETWORK)
                # Preflight app compatibility with the asset_id derived from user txn
                preflight = builder.validate_payment_app(asset_id)
                if not preflight.get('success'):
                    logger.error(f"Payment app preflight (submit) failed: {preflight.get('error')}")
                    return cls(success=False, error=f"Payment app is not compatible/ready: {preflight.get('error')}")
                else:
                    info_map = preflight.get('info') or {}
                    logger.info(
                        f"Payment app preflight (submit) OK: app={info_map.get('app_id')}, "
                        f"confio={info_map.get('confio_asset_id')}, cusd={info_map.get('cusd_asset_id')}, "
                        f"fee_recipient={info_map.get('fee_recipient')}, sponsor={info_map.get('sponsor_address')}, "
                        f"approval_sha256={info_map.get('approval_sha256')}"
                    )

                # Determine method selector
                if asset_id == builder.cusd_asset_id:
                    method_name = "pay_with_cusd"
                elif asset_id == builder.confio_asset_id:
                    method_name = "pay_with_confio"
                else:
                    return cls(success=False, error=f'Unknown asset ID: {asset_id}')

                from algosdk.abi import Method, Argument, Returns, ABIType
                from algosdk.transaction import SuggestedParams
                method = Method(
                    name=method_name,
                    args=[
                        Argument(arg_type="address", name="recipient"),
                        Argument(arg_type="string", name="payment_id")
                    ],
                    returns=Returns(arg_type="void")
                )

                # Use round/genesis parameters from user txn to guarantee byte-level match
                first = user_txn.get('fv')
                last = user_txn.get('lv')
                gh = user_txn.get('gh')
                # Use empty string when user txn omitted genesis_id to avoid altering bytes
                gen = user_txn.get('gen') or ""
                # Clone Exactly: use fv/lv/gh/gen from user AXFER to avoid drift
                params = SuggestedParams(
                    fee=1000,  # placeholder; we set explicit fees on each txn
                    first=first,
                    last=last,
                    gh=gh,
                    gen=gen,
                    flat_fee=True
                )
                # Deterministic sponsor payment: no variable MBR top-up
                mbr_topup = 0

                # Fixed fees to match builder policy and guarantee deterministic bytes
                sponsor_payment_fee = 3000
                app_call_fee = 2000
                
                # Extract exact parameters from user's first transaction to ensure consistency
                # We need to decode one user transaction to get the exact params they used
                import msgpack as _mp
                user_txn_dict = _mp.unpackb(base64.b64decode(signed_transactions[0]), raw=False)
                user_first = user_txn_dict.get('txn', {}).get('fv', params.first)
                user_last = user_txn_dict.get('txn', {}).get('lv', params.last)
                user_gh = user_txn_dict.get('txn', {}).get('gh', params.gh)
                user_gen = user_txn_dict.get('txn', {}).get('gen', params.gen)

                # Build with exact same parameters as user transactions
                sp_pay = SuggestedParams(
                    fee=sponsor_payment_fee,
                    first=user_first,
                    last=user_last,
                    gh=user_gh,
                    gen=user_gen,
                    flat_fee=True
                )
                sponsor_payment = transaction.PaymentTxn(
                    sender=builder.sponsor_address,
                    sp=sp_pay,
                    receiver=user_address,
                    amt=mbr_topup,
                    note=b"Sponsored payment"  # Must match creation exactly
                )
                sponsor_payment.group = group_id_bytes

                # ABI-encode args (recipient is fixed; payment_id may be empty depending on creation)
                string_type = ABIType.from_string("string")
                recipient_arg = encoding.decode_address(recipient_address)
                # CRITICAL: Use the actual internal_id if provided, otherwise empty string
                # This must match what was used during creation
                pid_from_submit = str(internal_id) if internal_id is not None else ""
                payment_id_arg = string_type.encode(pid_from_submit)
                logger.info(f"Rebuilding app call with payment_id: '{pid_from_submit}' (length: {len(pid_from_submit)})")

                sp_app = SuggestedParams(
                    fee=app_call_fee,
                    first=user_first,
                    last=user_last,
                    gh=user_gh,
                    gen=user_gen,
                    flat_fee=True
                )
                app_call = transaction.ApplicationCallTxn(
                    sender=builder.sponsor_address,
                    sp=sp_app,
                    index=builder.payment_app_id,
                    on_complete=transaction.OnComplete.NoOpOC,
                    app_args=[
                        method.get_selector(),
                        recipient_arg,
                        payment_id_arg
                    ],
                    accounts=[user_address, recipient_address],
                    foreign_assets=[asset_id]
                )
                app_call.group = group_id_bytes

                # Self-check: recompute expected group id from rebuilt sponsor txns + user txns
                try:
                    # Define helper before using it
                    def _b64(b: bytes) -> str:
                        try:
                            return base64.b64encode(b or b"").decode()
                        except Exception:
                            return ""

                    from algosdk import transaction as _tx
                    from algosdk import encoding as _enc
                    # Load user txns as Transaction objects from signed msgpack using SignedTransaction decoder
                    # This preserves exact field defaults (e.g., missing fee -> 0) to avoid gid drift
                    def _load_user_txn_precise(b64: str):
                        b = base64.b64decode(b64)
                        # Decode into SignedTransaction, then extract the inner Transaction object
                        stx = _enc.msgpack_decode(b)
                        if not hasattr(stx, 'txn'):
                            raise ValueError('Decoded object is not a SignedTransaction')
                        # Also keep the raw txn dict for diagnostics
                        raw = msgpack.unpackb(b, raw=False)
                        raw_txn = raw.get('txn') if isinstance(raw, dict) else None
                        return stx.txn, (raw_txn if isinstance(raw_txn, dict) else {})

                    user_txn1_obj, user_txn1_raw = _load_user_txn_precise(signed_transactions[0])
                    user_txn2_obj, user_txn2_raw = _load_user_txn_precise(signed_transactions[1])

                    # Compute gid with fixed fees/policy for empty vs provided pid
                    def _compute_gid_fixed(pid_str: str):
                        # User transactions in sponsored payments ALWAYS have fee=0
                        # SignedTransaction decoding preserves this; no adjustment needed
                        sp_for_gid = SuggestedParams(
                            fee=sponsor_payment_fee, first=user_first, last=user_last, gh=user_gh, gen=user_gen, flat_fee=True
                        )
                        app_for_gid = SuggestedParams(
                            fee=app_call_fee, first=user_first, last=user_last, gh=user_gh, gen=user_gen, flat_fee=True
                        )
                        pay_tmp = transaction.PaymentTxn(
                            sender=builder.sponsor_address,
                            sp=sp_for_gid,
                            receiver=user_address,
                            amt=0,
                            note=b"Sponsored payment"
                        )
                        pid_bytes = string_type.encode(pid_str or "")
                        app_tmp = transaction.ApplicationCallTxn(
                            sender=builder.sponsor_address,
                            sp=app_for_gid,
                            index=builder.payment_app_id,
                            on_complete=transaction.OnComplete.NoOpOC,
                            app_args=[method.get_selector(), recipient_arg, pid_bytes],
                            accounts=[user_address, recipient_address],
                            foreign_assets=[asset_id]
                        )
                        gid_local = _tx.calculate_group_id([pay_tmp, user_txn1_obj, user_txn2_obj, app_tmp])
                        return gid_local, pay_tmp, app_tmp

                    # Always use the payment_id that was passed (matching creation)
                    expected_gid_pid, pay_p, app_p = _compute_gid_fixed(pid_from_submit)
                    
                    # Also compute without payment_id for comparison
                    expected_gid_empty, pay_e, app_e = _compute_gid_fixed("")
                    
                    # Check which one matches
                    if expected_gid_pid == group_id_bytes:
                        logger.info(f"✓ Group hash matches with payment_id='{pid_from_submit}'")
                        sponsor_payment = pay_p
                        app_call = app_p
                        expected_gid = expected_gid_pid
                    elif expected_gid_empty == group_id_bytes:
                        logger.info("✓ Group hash matches with empty payment_id")
                        sponsor_payment = pay_e
                        app_call = app_e
                        expected_gid = expected_gid_empty
                    else:
                        logger.warning("Group hash mismatch during Option B rebuild - investigating")
                        # Provide additional diagnostics
                        def _fv_lv_gh_gen(tx):
                            return tx.get('fv'), tx.get('lv'), _b64(tx.get('gh', b'')), tx.get('gen', '')
                        fv1, lv1, gh1, gen1 = _fv_lv_gh_gen(user_txn1_raw)
                        fv2, lv2, gh2, gen2 = _fv_lv_gh_gen(user_txn2_raw)
                        logger.warning(f"user_txn1: fv={fv1}, lv={lv1}, gh={gh1}, gen='{gen1}' fee={user_txn1_raw.get('fee')}")
                        logger.warning(f"user_txn2: fv={fv2}, lv={lv2}, gh={gh2}, gen='{gen2}' fee={user_txn2_raw.get('fee')}")
                        logger.warning(f"sponsor_pay_fee_fixed={sponsor_payment_fee}, app_call_fee_fixed={app_call_fee}")
                        
                        # More detailed debugging
                        logger.error("=== GROUP HASH MISMATCH DEBUG ===")
                        logger.error(f"User group ID: {_b64(group_id_bytes)[:20]}...")
                        logger.error(f"Empty pid GID: {_b64(expected_gid_empty)[:20]}...")
                        logger.error(f"With pid GID: {_b64(expected_gid_pid)[:20]}...")
                        logger.error(f"Payment ID used: '{pid_from_submit}'")
                        logger.error(f"User txn1 fee (obj): {user_txn1_obj.fee if hasattr(user_txn1_obj, 'fee') else 'N/A'}")
                        logger.error(f"User txn2 fee (obj): {user_txn2_obj.fee if hasattr(user_txn2_obj, 'fee') else 'N/A'}")
                        logger.error(f"App call with pid app_args: {[_b64(arg)[:20] if isinstance(arg, bytes) else str(arg)[:20] for arg in app_p.app_args]}")
                        logger.error(f"App call empty app_args: {[_b64(arg)[:20] if isinstance(arg, bytes) else str(arg)[:20] for arg in app_e.app_args]}")

                        # Deterministic variant search (no storage) to find a gid match
                        from itertools import product
                        variant_matched = False
                        variants_tried = 0
                        user_orders = [
                            (user_txn1_obj, user_txn2_obj),
                            (user_txn2_obj, user_txn1_obj)
                        ]
                        accounts_variants = [
                            (user_address, recipient_address),
                            (recipient_address, user_address)
                        ]
                        fee_pairs = [
                            (sponsor_payment_fee, app_call_fee),
                            (app_call_fee, sponsor_payment_fee)
                        ]
                        notes = [b"Sponsored payment", None]
                        pids = [pid_from_submit, ""]
                        for (u1, u2), (acc0, acc1), (fee0, fee3), note_bytes, pid_opt in product(user_orders, accounts_variants, fee_pairs, notes, pids):
                            variants_tried += 1
                            sp_for_gid = SuggestedParams(
                                fee=fee0, first=user_first, last=user_last, gh=user_gh, gen=user_gen, flat_fee=True
                            )
                            app_for_gid = SuggestedParams(
                                fee=fee3, first=user_first, last=user_last, gh=user_gh, gen=user_gen, flat_fee=True
                            )
                            pay_tmp = transaction.PaymentTxn(
                                sender=builder.sponsor_address,
                                sp=sp_for_gid,
                                receiver=user_address,
                                amt=0,
                                note=note_bytes if note_bytes is not None else None
                            )
                            pid_bytes = string_type.encode(pid_opt or "")
                            app_tmp = transaction.ApplicationCallTxn(
                                sender=builder.sponsor_address,
                                sp=app_for_gid,
                                index=builder.payment_app_id,
                                on_complete=transaction.OnComplete.NoOpOC,
                                app_args=[method.get_selector(), recipient_arg, pid_bytes],
                                accounts=[acc0, acc1],
                                foreign_assets=[asset_id]
                            )
                            gid_local = _tx.calculate_group_id([pay_tmp, u1, u2, app_tmp])
                            if gid_local == group_id_bytes:
                                sponsor_payment = pay_tmp
                                app_call = app_tmp
                                expected_gid = gid_local
                                logger.info(
                                    f"✓ Variant matched gid. order={'12' if (u1 is user_txn1_obj) else '21'}, "
                                    f"accounts={'payer_first' if (acc0==user_address) else 'recipient_first'}, "
                                    f"fees=({fee0},{fee3}), note={'present' if note_bytes else 'absent'}, pid={'present' if pid_opt else 'empty'}"
                                )
                                variant_matched = True
                                break
                        if not variant_matched:
                            logger.warning(f"Tried {variants_tried} variants; none matched gid. Proceeding will fail.")
                            # Use the payment_id version anyway since that's what was created
                            logger.warning("Proceeding with payment_id version despite mismatch")
                            sponsor_payment = pay_p
                            app_call = app_p
                            expected_gid = expected_gid_pid
                except Exception as ghe:
                    logger.warning(f"Group-hash self-check skipped due to parsing error: {ghe}")

                SPONSOR_SIGNER.assert_matches_address(getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None))

                # CRITICAL: Final verification before signing
                # Ensure the rebuilt group matches what the user signed
                try:
                    from algosdk.transaction import calculate_group_id
                    # Parse user transactions as Transaction objects
                    import msgpack as _mp
                    u1_dict = _mp.unpackb(base64.b64decode(signed_transactions[0]), raw=False)
                    u2_dict = _mp.unpackb(base64.b64decode(signed_transactions[1]), raw=False)
                    u1_txn = transaction.Transaction.undictify(u1_dict['txn'])
                    u2_txn = transaction.Transaction.undictify(u2_dict['txn'])
                    
                    # Calculate what group ID we would get with our rebuilt txns
                    final_group_id = calculate_group_id([sponsor_payment, u1_txn, u2_txn, app_call])
                    
                    if final_group_id != group_id_bytes:
                        logger.error("CRITICAL: Rebuilt group ID doesn't match user's group!")
                        logger.error(f"Rebuilt: {base64.b64encode(final_group_id).decode()[:20]}...")
                        logger.error(f"User's:  {base64.b64encode(group_id_bytes).decode()[:20]}...")
                        
                        # Debug: Log the exact parameters being used
                        logger.error(f"Sponsor payment: amt={sponsor_payment.amt}, note={sponsor_payment.note}")
                        logger.error(f"App call: app_args count={len(app_call.app_args)}, accounts={app_call.accounts}")
                        logger.error(f"App call foreign_assets={app_call.foreign_assets}")
                        
                        # Try to identify what's different
                        test_txns = [sponsor_payment, u1_txn, u2_txn, app_call]
                        for i, txn in enumerate(test_txns):
                            logger.error(f"Txn[{i}]: fv={txn.first_valid_round}, lv={txn.last_valid_round}, fee={txn.fee}")
                        
                        return cls(success=False, error='Cannot rebuild matching transaction group - please retry payment')
                    
                    logger.info("✓ Group ID verification passed - signing sponsor transactions")
                except Exception as e:
                    logger.warning(f"Could not verify group ID: {e}")
                    # Continue anyway but log warning

                # Sign sponsor transactions and prepare bytes
                stx0 = SPONSOR_SIGNER.sign_transaction(sponsor_payment)
                stx3 = SPONSOR_SIGNER.sign_transaction(app_call)
                
                # Debug: Log the sponsor transaction details
                logger.info(f"Sponsor payment txn: fv={sponsor_payment.first_valid_round}, lv={sponsor_payment.last_valid_round}, fee={sponsor_payment.fee}")
                logger.info(f"Sponsor app call: fv={app_call.first_valid_round}, lv={app_call.last_valid_round}, fee={app_call.fee}")

                # Keep exact user-signed bytes; do not re-encode as objects
                user_bytes_1 = base64.b64decode(signed_transactions[0])
                user_bytes_2 = base64.b64decode(signed_transactions[1])

                # Encode signed transactions using SDK canonical msgpack (returns base64 string)
                from algosdk import encoding as algo_encoding
                sponsor_b64_0 = algo_encoding.msgpack_encode(stx0)  # Returns base64 string
                sponsor_b64_3 = algo_encoding.msgpack_encode(stx3)  # Returns base64 string
                # Decode to get raw bytes
                sponsor_bytes_0 = base64.b64decode(sponsor_b64_0)
                sponsor_bytes_3 = base64.b64decode(sponsor_b64_3)

                # Strict order [0 pay, 1 user→merchant, 2 user→fee, 3 app]
                signed_txn_objects = [sponsor_bytes_0, user_bytes_1, user_bytes_2, sponsor_bytes_3]
                logger.info("Rebuilt sponsor txns and prepared raw bytes for 4-txn group")
            else:
                # Old format or already complete group
                logger.info(f"Processing {len(signed_transactions)} transactions as complete group")
                
                # Keep transactions as base64 strings for algod client
                signed_txn_objects = []
                
                for i, txn_data in enumerate(signed_transactions):
                    if isinstance(txn_data, dict):
                        txn_b64 = txn_data.get('transaction')
                    else:
                        txn_b64 = txn_data
                    
                    # Validate it's valid base64
                    try:
                        # Add padding if needed
                        missing_padding = len(txn_b64) % 4
                        if missing_padding:
                            txn_b64 += '=' * (4 - missing_padding)
                        
                        # Decode to bytes and append
                        decoded_bytes = base64.b64decode(txn_b64)
                        signed_txn_objects.append(decoded_bytes)
                        if verbose:
                            logger.info(f"  Transaction {i}: validated successfully")
                    except Exception as e:
                        logger.error(f"Failed to validate transaction {i}: {e}")
                        logger.error(f"Base64 string preview: {txn_b64[:50]}...")
                        raise
            
            # Submit to Algorand network
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )

            logger.info(f"Submitting payment transaction group of {len(signed_txn_objects)} transactions")
            
            # Debug: Log transaction structure before sending (verbose only)
            if verbose:
                logger.info(f"=== SUBMITTING TRANSACTION GROUP ===")
                for i, item in enumerate(signed_txn_objects):
                    # Support SignedTransaction, raw bytes, or base64 strings for logging
                    try:
                        import msgpack
                        if hasattr(item, 'dictify'):
                            txn_dict = item.dictify()
                        else:
                            if isinstance(item, (bytes, bytearray)):
                                txn_bytes = item
                            else:
                                txn_bytes = base64.b64decode(item)
                            txn_dict = msgpack.unpackb(txn_bytes, raw=False)
                        
                        # Log transaction details
                        if isinstance(txn_dict, dict) and 'txn' in txn_dict:
                            txn_data = txn_dict['txn']
                            txn_type = txn_data.get('type', 'unknown')
                            sender = txn_data.get('snd', b'')
                            if isinstance(sender, bytes) and len(sender) == 32:
                                from algosdk import encoding
                                sender_addr = encoding.encode_address(sender)
                            else:
                                sender_addr = 'unknown'
                            
                            logger.info(f"  Txn {i}: Type={txn_type}, Sender={sender_addr[:10]}...")
                            
                            # Log more details based on type
                            if txn_type == 'pay':
                                rcv = txn_data.get('rcv', b'')
                                if isinstance(rcv, bytes) and len(rcv) == 32:
                                    rcv_addr = encoding.encode_address(rcv)
                                    logger.info(f"         Receiver={rcv_addr[:10]}..., Amount={txn_data.get('amt', 0)}")
                            elif txn_type == 'axfer':
                                arcv = txn_data.get('arcv', b'')
                                if isinstance(arcv, bytes) and len(arcv) == 32:
                                    arcv_addr = encoding.encode_address(arcv)
                                    logger.info(f"         AssetReceiver={arcv_addr[:10]}..., Amount={txn_data.get('aamt', 0)}, AssetID={txn_data.get('xaid', 0)}")
                            elif txn_type == 'appl':
                                logger.info(f"         AppID={txn_data.get('apid', 0)}, OnComplete={txn_data.get('apan', 0)}")
                                # Log accounts array
                                apat = txn_data.get('apat', [])
                                if apat:
                                    logger.info(f"         Accounts={[encoding.encode_address(a)[:10] + '...' if isinstance(a, bytes) and len(a) == 32 else 'invalid' for a in apat]}")
                        else:
                            logger.info(f"  Txn {i}: Unable to parse transaction structure")
                    except Exception as e:
                        logger.info(f"  Txn {i}: Unable to decode for logging: {e}")
                    logger.info(f"=====================================")
            
            # Pre-submit validation to produce clearer errors (byte-level)
            try:
                # Decode transactions for validation
                decoded_txns = []
                for item in signed_txn_objects:
                    try:
                        if hasattr(item, 'dictify'):
                            from algosdk import encoding as _enc
                            txn_bytes = _enc.msgpack_encode(item)
                        elif isinstance(item, (bytes, bytearray)):
                            txn_bytes = item
                        elif isinstance(item, str):
                            txn_bytes = base64.b64decode(item)
                        else:
                            txn_bytes = b''
                        txn_dict = msgpack.unpackb(txn_bytes, raw=False)
                        decoded_txns.append(txn_dict)
                    except Exception:
                        decoded_txns.append(None)
                
                appl_txn = next((t for t in decoded_txns if isinstance(t, dict) and t.get('txn', {}).get('type') == 'appl'), None)
                axfer_txn = next((t for t in decoded_txns if isinstance(t, dict) and t.get('txn', {}).get('type') == 'axfer'), None)
                pay_txn = next((t for t in decoded_txns if isinstance(t, dict) and t.get('txn', {}).get('type') == 'pay'), None)
                
                if appl_txn and axfer_txn:
                    apid = appl_txn['txn'].get('apid')
                    from algosdk import logic as algo_logic
                    app_addr = algo_logic.get_application_address(apid)
                    apat = appl_txn['txn'].get('apat', [])
                    xaid = axfer_txn['txn'].get('xaid')
                    
                    # ChatGPT's debugging: Log all critical fields for pc=1330 assertion
                    from algosdk import encoding as algo_encoding
                    
                    # Helper function to decode address safely
                    def addr32(b):
                        if isinstance(b, (bytes, bytearray)) and len(b) == 32:
                            return algo_encoding.encode_address(b)
                        return 'invalid'
                    
                    # Extract all relevant fields
                    appl_sender = addr32(appl_txn['txn'].get('snd', b''))
                    axfer_sender = addr32(axfer_txn['txn'].get('snd', b''))
                    axfer_receiver = addr32(axfer_txn['txn'].get('arcv', b''))
                    
                    # Extract payment transaction fields if exists
                    pay_sender = addr32(pay_txn['txn'].get('snd', b'')) if pay_txn else 'no_pay_txn'
                    pay_receiver = addr32(pay_txn['txn'].get('rcv', b'')) if pay_txn else 'no_pay_txn'
                    pay_amount = pay_txn['txn'].get('amt', -1) if pay_txn else -1
                    
                    # Extract app args (ABI encoding)
                    # For 4-txn group with NEW format: [selector, recipient_address, payment_id]
                    apaa = appl_txn['txn'].get('apaa', [])
                    abi_selector = apaa[0].hex() if len(apaa) > 0 and isinstance(apaa[0], bytes) else 'missing'
                    # Recipient at position 1 (NEW format - no tx refs in app_args)
                    abi_recipient = addr32(apaa[1]) if len(apaa) > 1 and isinstance(apaa[1], bytes) and len(apaa[1]) == 32 else 'missing'
                    # Payment ID at position 2
                    abi_payment_id = apaa[2].decode() if len(apaa) > 2 and isinstance(apaa[2], bytes) else 'missing'
                    
                    # Extract foreign assets (THIS IS THE KEY CHECK!)
                    apas = appl_txn['txn'].get('apas', [])
                    if verbose:
                        logger.info(f"AppCall foreign assets (apas): {apas}")
                    if not apas:
                        logger.error("CRITICAL: AppCall has NO foreign assets! This will fail pc=1330")
                    elif apas[0] != xaid:
                        logger.error(f"CRITICAL: AppCall foreign asset {apas[0]} != AXFER asset {xaid}")
                    
                    # Extract accounts array
                    accounts_0 = addr32(apat[0]) if len(apat) > 0 else 'missing'
                    accounts_1 = addr32(apat[1]) if len(apat) > 1 else 'missing'
                    
                    # Log all critical payer binding fields  
                    # Detect if we have a 4-txn group (new format) or 3-txn group (old format)
                    is_4txn_group = len(decoded_txns) == 4
                    
                    if verbose:
                        logger.info(f"=== PAYER BINDING DEBUG ({len(decoded_txns)}-TXN GROUP) ===")
                        logger.info(f"Group structure:")
                    
                    if is_4txn_group:
                        # 4-txn group: [Payment(sponsor→user), AXFER(user→merchant), AXFER(user→fee), AppCall(sponsor)]
                        merchant_axfer = decoded_txns[1] if len(decoded_txns) > 1 else None
                        fee_axfer = decoded_txns[2] if len(decoded_txns) > 2 else None
                        
                        # Get merchant AXFER details
                        merchant_sender = addr32(merchant_axfer['txn'].get('snd', b'')) if merchant_axfer else 'missing'
                        merchant_receiver = addr32(merchant_axfer['txn'].get('arcv', b'')) if merchant_axfer else 'missing'
                        merchant_amount = merchant_axfer['txn'].get('aamt', 0) if merchant_axfer else 0
                        
                        # Get fee AXFER details  
                        fee_sender = addr32(fee_axfer['txn'].get('snd', b'')) if fee_axfer else 'missing'
                        fee_receiver = addr32(fee_axfer['txn'].get('arcv', b'')) if fee_axfer else 'missing'
                        fee_amount = fee_axfer['txn'].get('aamt', 0) if fee_axfer else 0
                        
                        if verbose:
                            logger.info(f"  Txn[0] (pay): sender={pay_sender[:10]}..., receiver={pay_receiver[:10]}..., amount={pay_amount}")
                            logger.info(f"  Txn[1] (merchant axfer): sender={merchant_sender[:10]}..., receiver={merchant_receiver[:10]}..., amount={merchant_amount}")
                            logger.info(f"  Txn[2] (fee axfer): sender={fee_sender[:10]}..., receiver={fee_receiver[:10]}..., amount={fee_amount}")
                            logger.info(f"  Txn[3] (appl): sender={appl_sender[:10]}...")
                    else:
                        # 3-txn group (old format)
                        if verbose:
                            logger.info(f"  Txn[0] (pay): sender={pay_sender[:10]}..., receiver={pay_receiver[:10]}..., amount={pay_amount}")
                            logger.info(f"  Txn[1] (axfer): sender={axfer_sender[:10]}..., receiver={axfer_receiver[:10]}...")
                            logger.info(f"  Txn[2] (appl): sender={appl_sender[:10]}...")
                    
                    if verbose:
                        logger.info(f"AppCall details:")
                        logger.info(f"  ABI selector: {abi_selector}")
                        logger.info(f"  ABI recipient (at app_args[1]): {abi_recipient[:10]}..." if abi_recipient != 'missing' else "  ABI recipient: missing")
                        logger.info(f"  ABI payment_id (at app_args[2]): {abi_payment_id}")
                        logger.info(f"  Accounts[0] (payer): {accounts_0[:10]}..." if accounts_0 != 'missing' else "  Accounts[0]: missing")
                        logger.info(f"  Accounts[1] (recipient): {accounts_1[:10]}..." if accounts_1 != 'missing' else "  Accounts[1]: missing")
                    
                    # Critical assertions the contract will check
                    if is_4txn_group:
                        if verbose:
                            logger.info("Contract assertions for 4-txn group:")
                            logger.info(f"  1. Merchant AXFER sender == Txn.accounts[0]?")
                            logger.info(f"     {merchant_sender[:10]}... == {accounts_0[:10]}...? {merchant_sender == accounts_0}")
                            logger.info(f"  2. Fee AXFER sender == Txn.accounts[0]?")
                            logger.info(f"     {fee_sender[:10]}... == {accounts_0[:10]}...? {fee_sender == accounts_0}")
                            logger.info(f"  3. Gtxn[0].receiver == Txn.accounts[0]?")
                            logger.info(f"     {pay_receiver[:10]}... == {accounts_0[:10]}...? {pay_receiver == accounts_0}")
                            logger.info(f"  4. Caster will compute tx refs: index 1 for merchant, index 2 for fee")

                        # Byte-level equality checks to mirror TEAL exactly
                        try:
                            appl_apat = appl_txn['txn'].get('apat', [])
                            acct0_bytes = appl_apat[0] if len(appl_apat) > 0 else b''
                            # Locate group members explicitly
                            gtxn0 = decoded_txns[0]['txn'] if decoded_txns and decoded_txns[0] and decoded_txns[0].get('txn',{}).get('type') == 'pay' else None
                            gtxn1 = decoded_txns[1]['txn'] if len(decoded_txns) > 1 and decoded_txns[1] and decoded_txns[1].get('txn',{}).get('type') == 'axfer' else None
                            gtxn2 = decoded_txns[2]['txn'] if len(decoded_txns) > 2 and decoded_txns[2] and decoded_txns[2].get('txn',{}).get('type') == 'axfer' else None
                            # Fall back to search by type
                            if gtxn0 is None:
                                for d in decoded_txns:
                                    if isinstance(d, dict) and d.get('txn',{}).get('type') == 'pay':
                                        gtxn0 = d['txn']
                                        break
                            if gtxn1 is None or gtxn2 is None:
                                axfers = [d['txn'] for d in decoded_txns if isinstance(d, dict) and d.get('txn',{}).get('type') == 'axfer']
                                if len(axfers) >= 2:
                                    gtxn1, gtxn2 = axfers[0], axfers[1]

                            snd1 = gtxn1.get('snd', b'') if gtxn1 else b''
                            snd2 = gtxn2.get('snd', b'') if gtxn2 else b''
                            rcv0 = gtxn0.get('rcv', b'') if gtxn0 else b''
                            # Log hex equality
                            def hx(b):
                                return b.hex() if isinstance(b, (bytes, bytearray)) else 'invalid'
                            if verbose:
                                logger.info(f"  [BYTES] snd1==acct0? {snd1 == acct0_bytes} (snd1={hx(snd1)}, acct0={hx(acct0_bytes)})")
                                logger.info(f"  [BYTES] snd2==acct0? {snd2 == acct0_bytes} (snd2={hx(snd2)}, acct0={hx(acct0_bytes)})")
                                logger.info(f"  [BYTES] rcv0==acct0? {rcv0 == acct0_bytes} (rcv0={hx(rcv0)}, acct0={hx(acct0_bytes)})")
                        except Exception as be:
                            logger.warning(f"Byte-level equality check failed: {be}")
                        
                        # Validation warnings for 4-txn group
                        if merchant_sender != accounts_0:
                            logger.error(f"CRITICAL: Merchant AXFER sender ({merchant_sender}) != accounts[0] ({accounts_0})")
                        if fee_sender != accounts_0:
                            logger.error(f"CRITICAL: Fee AXFER sender ({fee_sender}) != accounts[0] ({accounts_0})")
                    else:
                        if verbose:
                            logger.info("Contract assertions for 3-txn group:")
                            logger.info(f"  1. Gtxn[1].sender == Txn.accounts[0]?")
                            logger.info(f"     {axfer_sender[:10]}... == {accounts_0[:10]}...? {axfer_sender == accounts_0}")
                            logger.info(f"  2. Gtxn[0].receiver == Txn.accounts[0]?")
                            logger.info(f"     {pay_receiver[:10]}... == {accounts_0[:10]}...? {pay_receiver == accounts_0}")
                        
                        # Validation warnings for 3-txn group
                        if axfer_sender != accounts_0:
                            logger.error(f"CRITICAL: AXFER sender ({axfer_sender}) != accounts[0] ({accounts_0})")
                    
                    if pay_receiver != accounts_0:
                        logger.error(f"CRITICAL: Payment receiver ({pay_receiver}) != accounts[0] ({accounts_0})")
                    
                    if verbose:
                        logger.info("=====================================")
                    # Check that app_args are correctly formatted
                    if abi_recipient == 'missing':
                        logger.error(f"CRITICAL: Recipient address missing from app_args[1]")
                        logger.error("App args should be: [selector, recipient_address, payment_id]")
                    
                    # Require recipient in accounts[1]
                    if len(apat) < 2 or not isinstance(apat[1], (bytes, bytearray)):
                        logger.error(f"Pre-submit validation failed: AppCall.accounts must include payer and recipient; got {len(apat)}")
                        return cls(success=False, error="Payment AppCall missing recipient in accounts array")
                    # Decode recipient from accounts[1]
                    if len(apat) >= 2 and isinstance(apat[1], (bytes, bytearray)):
                        recipient_addr = algo_encoding.encode_address(apat[1])
                        logger.info(f"Pre-submit: apid={apid}, asset={xaid}, app_addr={app_addr}, recipient={recipient_addr}")
                        # Check recipient opt-in to asset
                        try:
                            algod_client.account_asset_info(recipient_addr, xaid)
                        except Exception as e:
                            logger.error(f"Recipient {recipient_addr} not opted-in to asset {xaid}: {e}")
                            return cls(success=False, error=f"Recipient is not opted-in to asset {xaid}")
                        # Check app opt-in to asset
                        try:
                            algod_client.account_asset_info(app_addr, xaid)
                        except Exception as e:
                            logger.error(f"App {apid} address {app_addr} not opted-in to asset {xaid}: {e}")
                            return cls(success=False, error=f"Payment app not opted-in to asset {xaid}")

                        # Validate app global asset IDs match the used asset
                        try:
                            app_info = algod_client.application_info(apid)
                            gstate = app_info.get('params', {}).get('global-state', [])
                            def decode_key(b64k: str) -> str:
                                import base64
                                try:
                                    return base64.b64decode(b64k).decode('utf-8')
                                except Exception:
                                    return ''
                            state_map = {decode_key(e.get('key','')): e.get('value', {}) for e in gstate}
                            def get_uint(name: str) -> int:
                                v = state_map.get(name)
                                if isinstance(v, dict) and v.get('type') == 2:
                                    return int(v.get('uint', 0))
                                return 0
                            cusd_id = get_uint('cusd_asset_id')
                            confio_id = get_uint('confio_asset_id')
                            # Decide expected asset based on match
                            if xaid == confio_id:
                                expected = 'confio'
                            elif xaid == cusd_id:
                                expected = 'cusd'
                            else:
                                logger.error(f"Asset {xaid} does not match app configured assets (confio={confio_id}, cusd={cusd_id})")
                                return cls(success=False, error=f"Asset {xaid} is not configured in payment app")
                        except Exception as ge:
                            logger.warning(f"Could not validate app global state assets: {ge}")
                else:
                    logger.warning("Could not find appl/axfer txns for pre-submit validation")
            except Exception as ve:
                logger.warning(f"Pre-submit validation skipped due to error: {ve}")

            # Send the grouped transactions
            t_send_start = time.time()
            # Normalize to a list of SignedTransaction bytes and submit as list (preferred)
            try:
                from algosdk import transaction as _txn
                import msgpack as _mp
                import base64 as _b64

                def ensure_stx_bytes(x) -> bytes:
                    if isinstance(x, (bytes, bytearray)):
                        d = _mp.unpackb(x, raw=False)
                        _txn.SignedTransaction.undictify(d)
                        return bytes(x)
                    if isinstance(x, str):
                        b = _b64.b64decode(x)
                        d = _mp.unpackb(b, raw=False)
                        _txn.SignedTransaction.undictify(d)
                        return b
                    if hasattr(x, 'dictify') and hasattr(x, 'txn'):
                        from algosdk import encoding as _enc
                        b64_str = _enc.msgpack_encode(x)  # Returns base64 string
                        b = _b64.b64decode(b64_str)  # Decode to raw bytes
                        d = _mp.unpackb(b, raw=False)
                        _txn.SignedTransaction.undictify(d)
                        return b
                    raise TypeError('Unsupported transaction element; expected SignedTransaction bytes/base64 or object')

                tx_bytes_list = [ensure_stx_bytes(x) for x in signed_txn_objects]

                # Final validation
                for i, b in enumerate(tx_bytes_list):
                    d = _mp.unpackb(b, raw=False)
                    _txn.SignedTransaction.undictify(d)

                # Submit as base64-encoded string (SDK expects base64 input, will decode internally)
                combined_bytes = b"".join(tx_bytes_list)
                combined_b64 = base64.b64encode(combined_bytes).decode('utf-8')
                tx_id = algod_client.send_raw_transaction(combined_b64)
                t_send_end = time.time()
                logger.info(f"Payment transaction sent: {tx_id} (send_time={t_send_end - t_send_start:.3f}s, prebuild={t_send_start - t_prebuild_start:.3f}s, parse={t_prebuild_start - t_parse_start:.3f}s, total={t_send_end - t0:.3f}s)")
            except Exception as e_send:
                # Attempt a TEAL dryrun for detailed diagnostics in DEBUG mode
                from django.conf import settings as dj_settings
                err_text = str(e_send)
                from algosdk.error import AlgodHTTPError
                if isinstance(e_send, AlgodHTTPError) and 'logic eval error' in err_text and getattr(dj_settings, 'DEBUG', False):
                    try:
                        # Build a dryrun request body: list of base64-encoded signed txn msgpacks
                        dr_b64 = [base64.b64encode(tx).decode('utf-8') if isinstance(tx, (bytes, bytearray)) else tx for tx in signed_txn_objects]
                        dr_body = {"txns": dr_b64}
                        dr_resp = None
                        # Prefer a separate dryrun Algod if configured (e.g., localnet)
                        from algosdk.v2client.algod import AlgodClient as _AlgodClient
                        dr_addr = getattr(dj_settings, 'ALGORAND_DRYRUN_ALGOD_ADDRESS', None)
                        dr_token = getattr(dj_settings, 'ALGORAND_DRYRUN_ALGOD_TOKEN', None)
                        dryrun_client = None
                        if dr_addr:
                            dryrun_client = _AlgodClient(dr_token or '', dr_addr)
                        else:
                            # Use the same Algod client if no separate dryrun endpoint is configured
                            dryrun_client = algod_client
                        try:
                            logger.error(f"[DRYRUN] Using algod at: {dr_addr or getattr(dj_settings, 'ALGORAND_ALGOD_ADDRESS', 'same-as-submit')}")
                        except Exception:
                            pass
                        try:
                            # Some SDKs accept dict directly
                            dr_resp = dryrun_client.dryrun(dr_body)
                        except Exception:
                            # Fallback to raw JSON request
                            import json as _json
                            dr_bytes = _json.dumps(dr_body).encode('utf-8')
                            try:
                                dr_resp = dryrun_client.algod_request("POST", "/v2/teal/dryrun", data=dr_bytes)
                            except Exception as dr404:
                                # If dryrun endpoint is unavailable (404), attempt simulate as a fallback
                                try:
                                    sim_body = {
                                        "txn-groups": [
                                            {"txns": signed_txn_objects}
                                        ]
                                    }
                                    sim_bytes = _json.dumps(sim_body).encode('utf-8')
                                    sim_resp = dryrun_client.algod_request("POST", "/v2/transactions/simulate", data=sim_bytes)
                                    logger.error(f"[SIMULATE] response (truncated): {_json.dumps(sim_resp, default=str)[:4000]}")
                                except Exception as sim_e:
                                    logger.error(f"[SIMULATE] Failed to execute simulate: {sim_e}")
                                    raise dr404
                        # Log a compact view of the dryrun trace
                        import json as _json
                        dr_json = _json.dumps(dr_resp, default=str)
                        logger.error(f"[DRYRUN] logic eval error during submit. Dryrun response (truncated): {dr_json[:4000]}")
                    except Exception as dre:
                        logger.error(f"[DRYRUN] Failed to execute dryrun: {dre}")
                # Re-raise so the outer handler updates DB and returns error to client
                raise
            
            # Async confirm: mark as submitted, enqueue Celery poller, and return immediately
            t_update_start = time.time()
            if internal_id:
                try:
                    from payments.models import PaymentTransaction
                    payment_transaction = PaymentTransaction.objects.get(internal_id=internal_id)
                    payment_transaction.status = 'SUBMITTED'
                    payment_transaction.transaction_hash = tx_id
                    payment_transaction.save()
                except Exception as e:
                    logger.warning(f"Could not update PaymentTransaction {internal_id} to SUBMITTED: {e}")
                # Do not enqueue here; rely on Celery poller to pick up confirmations

            logger.info(
                f"Sponsored payment submitted for user {user.id}: TxID: {tx_id}. (db+enqueue={time.time() - t_update_start:.3f}s, total_mutation={time.time() - t0:.3f}s) Confirmation handled asynchronously."
            )

            return cls(
                success=True,
                transaction_id=tx_id,
                confirmed_round=None
            )
            
        except Exception as e:
            logger.error(f'Error submitting sponsored payment: {str(e)}', exc_info=True)
            
            # Update payment record as failed if exists
            if internal_id:
                try:
                    payment_record = Payment.objects.get(internal_id=internal_id)
                    payment_record.status = 'failed'
                    payment_record.error_message = str(e)
                    payment_record.save()
                except Payment.DoesNotExist:
                    pass
            
            return cls(success=False, error=str(e))
