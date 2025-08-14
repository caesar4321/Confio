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
from algosdk import mnemonic, account, encoding
import asyncio
import base64
import msgpack

logger = logging.getLogger(__name__)


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
        payment_id = graphene.String(required=False, description="Optional payment ID for tracking")
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
    payment_id = graphene.String(description="Payment ID for tracking")
    
    @classmethod
    def mutate(cls, root, info, amount, asset_type='CUSD', payment_id=None, 
              note=None, create_receipt=False):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
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
            
            # Initialize payment transaction builder
            builder = PaymentTransactionBuilder(network=settings.ALGORAND_NETWORK)
            
            # Determine asset ID
            asset_type_upper = asset_type.upper()
            if asset_type_upper == 'CUSD':
                asset_id = builder.cusd_asset_id
            elif asset_type_upper == 'CONFIO':
                asset_id = builder.confio_asset_id
            else:
                return cls(success=False, error=f'Unsupported asset type: {asset_type}')
            
            logger.info(f"Payment mutation: Using asset ID {asset_id} for {asset_type_upper}")
            
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
            
            # Check and fund account if needed for MBR
            from blockchain.account_funding_service import account_funding_service
            
            # Calculate funding needed for current MBR
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
            if create_receipt and not payment_id:
                import uuid
                payment_id = str(uuid.uuid4())
            
            # Create payment record in database for business payment
            payment_record = None
            if payment_id:
                with db_transaction.atomic():
                    # Get business owner for recipient tracking
                    recipient_user = recipient_business.owner if hasattr(recipient_business, 'owner') else None
                    
                    payment_record = Payment.objects.create(
                        sender=user,
                        sender_business=sender_business if sender_account_type == 'business' else None,
                        recipient=recipient_user,  # Business owner for tracking
                        recipient_business=recipient_business,  # The actual business recipient
                        amount=Decimal(str(amount)),
                        currency=asset_type_upper,
                        payment_id=payment_id,
                        status='pending',
                        blockchain_network='algorand',
                        sender_address=sender_account.algorand_address,
                        recipient_address=resolved_recipient_address,
                        note=note or f"Payment to {recipient_business.name}",
                        fee_amount=Decimal(str(fee_amount_base / (10 ** decimals))),
                        net_amount=Decimal(str(net_amount_base / (10 ** decimals)))
                    )
                    logger.info(f"Created payment record {payment_id} for {amount} {asset_type} to business {recipient_business.name}")
            
            # Build sponsored payment transaction group using cUSD pattern
            try:
                tx_result = builder.build_sponsored_payment_cusd_style(
                    sender_address=sender_account.algorand_address,
                    recipient_address=resolved_recipient_address,
                    amount=amount_in_base,
                    asset_id=asset_id,
                    payment_id=payment_id if create_receipt else None,
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
            
            # Store sponsor transactions for later reconstruction (in both Payment and PaymentTransaction if available)
            # Only return user transactions to frontend (the 2 AXFERs for 4-txn group)
            sponsor_data = {
                'sponsor_transactions': [
                    {
                        'index': st['index'],
                        'txn': st['signed'] if st.get('signed') else st['txn'],
                        'signed': True
                    } for st in tx_result.get('sponsor_transactions', [])
                ],
                'group_id': tx_result.get('group_id')
            }
            
            if payment_record:
                # Store sponsor transactions in blockchain_data for SubmitSponsoredPayment to use
                payment_record.blockchain_data = json.dumps(sponsor_data)
                payment_record.save()
                logger.info(f"Stored sponsor transactions in payment record {payment_id}")
            
            # Also store in PaymentTransaction if it exists (for invoice payments)
            try:
                from payments.models import PaymentTransaction
                payment_transaction = PaymentTransaction.objects.filter(payment_transaction_id=payment_id).first()
                if payment_transaction:
                    # Update blockchain_data to include sponsor transactions
                    existing_data = payment_transaction.blockchain_data or {}
                    existing_data.update(sponsor_data)
                    payment_transaction.blockchain_data = existing_data
                    payment_transaction.save()
                    logger.info(f"Stored sponsor transactions in PaymentTransaction {payment_id}")
            except Exception as e:
                logger.warning(f"Could not store sponsor transactions in PaymentTransaction: {e}")
            
            # Only return user transactions (the 2 AXFERs) to frontend
            # Frontend should NOT receive sponsor transactions
            transaction_data = []
            user_txns = tx_result.get('transactions_to_sign', [])
            
            # For 4-txn group, we have 2 user transactions (merchant and fee AXFERs)
            for i, user_txn in enumerate(user_txns):
                transaction_data.append({
                    'index': i,  # Client will use 0 and 1 for the two AXFERs
                    'type': 'asset_transfer',
                    'transaction': base64.b64encode(user_txn['txn']).decode() if isinstance(user_txn['txn'], bytes) else user_txn['txn'],
                    'signed': False,
                    'needs_signature': True,
                    'message': user_txn.get('message', f'Transaction {i+1}')
                })
            
            return cls(
                success=True,
                transactions=transaction_data,  # Only user transactions (2 AXFERs)
                user_signing_indexes=[0, 1],  # User signs both AXFERs
                group_id=tx_result.get('group_id'),
                gross_amount=amount_in_base / (10 ** decimals),
                net_amount=net_amount_base / (10 ** decimals),
                fee_amount=fee_amount_base / (10 ** decimals),
                payment_id=payment_id
            )
            
        except Exception as e:
            logger.error(f'Error creating sponsored payment: {str(e)}', exc_info=True)
            return cls(success=False, error=str(e))


class SubmitSponsoredPaymentCUSDStyleMutation(graphene.Mutation):
    """
    Submit a sponsored payment using the cUSD conversion pattern.
    Handles transactions_to_sign and sponsor_transactions separately.
    """
    
    class Arguments:
        signed_transactions = graphene.JSONString(
            required=True,
            description="JSON with userSignedTxns array and groupId"
        )
        payment_id = graphene.String(required=False, description="Payment ID for database update")
    
    success = graphene.Boolean()
    error = graphene.String()
    transaction_id = graphene.String()
    confirmed_round = graphene.Int()
    
    @classmethod  
    def mutate(cls, root, info, signed_transactions, payment_id=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            logger.info(f"Submitting cUSD-style sponsored payment group for user {user.id}")
            
            # Parse the signed_transactions - should be JSON like cUSD conversion
            import json
            if isinstance(signed_transactions, str):
                try:
                    tx_data = json.loads(signed_transactions)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse signed_transactions JSON: {e}")
                    return cls(success=False, error='Invalid transaction format')
            else:
                tx_data = signed_transactions
                
            # Check if this is the new format with index/transaction objects
            # or the old format with just transaction strings
            if isinstance(signed_transactions, list) and len(signed_transactions) > 0:
                if isinstance(signed_transactions[0], dict) and 'transaction' in signed_transactions[0]:
                    # New format: [{"index": 0, "transaction": "..."}, ...]
                    logger.info(f"Detected new format with index/transaction objects")
                    # Sort by index to ensure correct order
                    sorted_txns = sorted(signed_transactions, key=lambda x: x.get('index', 0))
                    user_signed_txns = [txn['transaction'] for txn in sorted_txns]
                else:
                    # Direct array of transaction strings
                    user_signed_txns = signed_transactions
            else:
                # Old format with userSignedTxns
                user_signed_txns = tx_data.get('userSignedTxns', [])
            
            group_id_b64 = tx_data.get('groupId')
            
            if not user_signed_txns:
                return cls(success=False, error='No signed transactions provided')
            
            logger.info(f"Received {len(user_signed_txns)} user-signed transactions")
            
            # Get sponsor transactions from the backend - these should already be signed
            # In cUSD style, sponsor transactions are pre-signed and stored or recreated
            from blockchain.algorand_sponsor_service import AlgorandSponsorService
            
            sponsor_service = AlgorandSponsorService()
            
            # For payment transactions, we need to recreate the sponsor transactions
            # This is different from cUSD where they're pre-built and stored
            # We'll need to reconstruct the group and get the sponsor parts
            
            # Decode user signed transactions to get transaction details
            decoded_user_txns = []
            for txn_b64 in user_signed_txns:
                decoded = base64.b64decode(txn_b64)
                decoded_user_txns.append(decoded)
            
            # For payments following the new 4-transaction pattern:
            # [Payment(sponsor→user), AssetTransfer(user→merchant), AssetTransfer(user→fee_recipient), AppCall(sponsor)]
            # User signs the two AssetTransfers (indices 1 and 2)
            # Sponsor signs Payment (index 0) and AppCall (index 3)
            
            # Recreate sponsor transactions based on the group ID and user transactions
            # This requires parsing the user transactions to extract group context
            
            import msgpack
            
            # Verify we have exactly 2 user transactions for the 4-txn pattern
            if len(decoded_user_txns) != 2:
                return cls(success=False, error=f'Expected 2 user-signed transactions, got {len(decoded_user_txns)}')
            
            logger.info(f"=== USER TRANSACTION ORDER DEBUG ===")
            for i, txn_bytes in enumerate(decoded_user_txns):
                txn_data = msgpack.unpackb(txn_bytes, raw=False)
                if 'txn' in txn_data:
                    txn = txn_data['txn']
                    sender = encoding.encode_address(txn.get('snd', b''))
                    if txn.get('type') == 'axfer' or txn.get('arcv'):
                        receiver = encoding.encode_address(txn.get('arcv', b''))
                        amount = txn.get('aamt', 0)
                        logger.info(f"User txn[{i}]: AXFER from {sender[:10]}... to {receiver[:10]}..., amount={amount}")
                    else:
                        logger.info(f"User txn[{i}]: Type={txn.get('type')}, Sender={sender[:10]}...")
            
            # Parse the merchant transfer (first user transaction)
            user_txn_msgpack = msgpack.unpackb(decoded_user_txns[0], raw=False)
            
            if 'txn' not in user_txn_msgpack:
                return cls(success=False, error='Invalid merchant transaction format')
                
            merchant_txn_data = user_txn_msgpack['txn']
            
            # Debug user transaction details
            logger.info(f"=== USER TRANSACTION DEBUG ===")
            logger.info(f"Transaction type: {merchant_txn_data.get('type')}")
            
            # Get sender from the transaction
            sender_bytes = merchant_txn_data.get('snd')
            if sender_bytes:
                try:
                    sender_addr = encoding.encode_address(sender_bytes)
                    logger.info(f"Transaction sender: {sender_addr}")
                except Exception as e:
                    logger.error(f"Failed to encode sender address: {e}")
            
            # Get receiver from the transaction
            receiver_bytes = merchant_txn_data.get('arcv')
            if receiver_bytes:
                try:
                    receiver_addr = encoding.encode_address(receiver_bytes)
                    logger.info(f"Transaction receiver: {receiver_addr}")
                except Exception as e:
                    logger.error(f"Failed to encode receiver address: {e}")
            
            # Parse the fee transfer (second user transaction)
            fee_txn_msgpack = msgpack.unpackb(decoded_user_txns[1], raw=False)
            if 'txn' not in fee_txn_msgpack:
                return cls(success=False, error='Invalid fee transaction format')
            
            fee_txn_data = fee_txn_msgpack['txn']
            
            # Get group ID from either transaction
            group_id_bytes = merchant_txn_data.get('grp') or fee_txn_data.get('grp')
            
            if not group_id_bytes:
                return cls(success=False, error='User transactions missing group ID')
            
            # Extract transaction details from both transfers
            user_address = encoding.encode_address(merchant_txn_data.get('snd', b''))
            recipient_address_from_txn = encoding.encode_address(merchant_txn_data.get('arcv', b''))  # From user's transaction
            fee_recipient = encoding.encode_address(fee_txn_data.get('arcv', b''))
            asset_id = merchant_txn_data.get('xaid', 0)
            net_amount = merchant_txn_data.get('aamt', 0)
            fee_amount = fee_txn_data.get('aamt', 0)
            
            # For invoice payments, use the recipient address from the database
            # This ensures we send to the business's actual blockchain address, not what the client thinks
            recipient_address = recipient_address_from_txn  # Default to transaction value
            if payment_id:
                from payments.models import Payment
                try:
                    payment_record = Payment.objects.get(payment_id=payment_id)
                    if payment_record.recipient_address:
                        recipient_address = payment_record.recipient_address
                        logger.info(f"Got recipient address from payment record: {recipient_address[:10]}...")
                except Payment.DoesNotExist:
                    logger.warning(f"Payment record {payment_id} not found, using address from transaction")
            
            logger.info(f"=== EXTRACTED ADDRESSES FROM USER TXNS ===")
            logger.info(f"User (sender): {user_address}")
            logger.info(f"Recipient from txn: {recipient_address_from_txn}")
            logger.info(f"Recipient (final): {recipient_address}")
            logger.info(f"Fee recipient: {fee_recipient}")
            
            # Total amount is net + fee
            amount = net_amount + fee_amount
            
            # Payment ID is optional for the 4-transaction pattern
            # We already have all the needed info from the transactions themselves
            
            # Recreate the sponsor transactions for 4-transaction pattern
            builder = PaymentTransactionBuilder(network=settings.ALGORAND_NETWORK)
            
            # Get suggested parameters
            params = builder.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            
            # Check if user needs MBR top-up
            mbr_topup = 0
            try:
                account_info = builder.algod_client.account_info(user_address)
                current_balance = account_info.get('amount', 0)
                min_balance_required = account_info.get('min-balance', 0)
                if current_balance < min_balance_required:
                    mbr_topup = min(min_balance_required - current_balance, 100_000)  # Cap at 0.1 ALGO
            except:
                pass  # Skip MBR check on error
            
            # Transaction 0: Sponsor payment to user (MBR top-up or 0)
            sponsor_payment_fee = min_fee * 3  # Pays for itself + 2 user AXFERs
            sponsor_params = SuggestedParams(
                fee=sponsor_payment_fee,
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            sponsor_payment = transaction.PaymentTxn(
                sender=builder.sponsor_address,
                sp=sponsor_params,
                receiver=user_address,
                amt=mbr_topup,  # MBR top-up or 0
                note=b"Sponsored payment with MBR" if mbr_topup > 0 else b"Sponsored payment"
            )
            sponsor_payment.group = group_id_bytes
            
            # Transaction 3: App call from sponsor (last in 4-txn group)
            app_call_fee = min_fee  # App call pays its own fee
            app_params = SuggestedParams(
                fee=app_call_fee,
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            # Determine method based on asset
            if asset_id == builder.cusd_asset_id:
                method_name = "pay_with_cusd"
            elif asset_id == builder.confio_asset_id:
                method_name = "pay_with_confio"
            else:
                return cls(success=False, error=f'Unknown asset ID: {asset_id}')
            
            # Use simplified 2-arg method signature (contract accesses transactions directly)
            method = Method(
                name=method_name,
                args=[
                    Argument(arg_type="address", name="recipient"),
                    Argument(arg_type="string", name="payment_id")
                ],
                returns=Returns(arg_type="void")
            )
            
            # Properly ABI-encode the arguments
            from algosdk.abi import ABIType
            address_type = ABIType.from_string("address")
            string_type = ABIType.from_string("string")
            
            # Debug addresses before encoding
            logger.info(f"=== ADDRESS VALIDATION DEBUG ===")
            logger.info(f"User address: {user_address}")
            logger.info(f"Recipient address: {recipient_address}")
            
            # Validate addresses
            try:
                user_decoded = encoding.decode_address(user_address)
                logger.info(f"✓ User address is valid: {user_address}")
            except Exception as e:
                logger.error(f"✗ User address is INVALID: {user_address} - Error: {e}")
                return cls(success=False, error=f'Invalid user address: {user_address}')
            
            try:
                recipient_decoded = encoding.decode_address(recipient_address)
                logger.info(f"✓ Recipient address is valid: {recipient_address}")
            except Exception as e:
                logger.error(f"✗ Recipient address is INVALID: {recipient_address} - Error: {e}")
                return cls(success=False, error=f'Invalid recipient address: {recipient_address}')
            
            # Encode the arguments
            recipient_arg = encoding.decode_address(recipient_address)  # Address is just 32 bytes
            payment_id_arg = string_type.encode(payment_id if payment_id else "")  # String needs ABI encoding
            
            # Log accounts array before creating app call
            logger.info(f"=== APP CALL ACCOUNTS ARRAY ===")
            logger.info(f"accounts[0] = {user_address}")
            logger.info(f"accounts[1] = {recipient_address}")
            logger.info(f"Expected: gtxn[1].Sender ({user_address}) == accounts[0] ({user_address})")
            
            app_call = transaction.ApplicationCallTxn(
                sender=builder.sponsor_address,
                sp=app_params,
                index=builder.payment_app_id,
                on_complete=transaction.OnComplete.NoOpOC,
                app_args=[
                    method.get_selector(),
                    recipient_arg,  # 32-byte address
                    payment_id_arg  # ABI-encoded string with length prefix
                ],
                accounts=[user_address, recipient_address],  # Pass user and recipient as account references
                foreign_assets=[asset_id]
            )
            app_call.group = group_id_bytes
            
            # Sign sponsor transactions
            sponsor_mnemonic = settings.ALGORAND_SPONSOR_MNEMONIC
            sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
            
            signed_sponsor_payment = sponsor_payment.sign(sponsor_private_key)
            signed_app_call = app_call.sign(sponsor_private_key)
            
            # Combine all transactions in correct 4-txn order: 
            # [sponsor_payment, user_merchant_transfer, user_fee_transfer, sponsor_app_call]
            all_transactions = [
                msgpack.packb(signed_sponsor_payment.dictify()),  # Index 0: Sponsor payment
                decoded_user_txns[0],                              # Index 1: User's merchant transfer (already msgpack)
                decoded_user_txns[1],                              # Index 2: User's fee transfer (already msgpack)
                msgpack.packb(signed_app_call.dictify())          # Index 3: Sponsor app call
            ]
            
            # Submit to Algorand network
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            logger.info(f"Submitting 4-transaction payment group: sponsor_payment, merchant_transfer, fee_transfer, app_call")
            logger.info(f"Net amount to merchant: {net_amount}, Fee: {fee_amount}, Total: {amount}")
            
            # Send the transaction array as raw bytes
            combined_txns = b''.join(all_transactions)
            tx_id = algod_client.send_raw_transaction(base64.b64encode(combined_txns).decode('utf-8'))
            logger.info(f"Payment transaction sent: {tx_id}")
            
            # Wait for confirmation
            from algosdk.transaction import wait_for_confirmation
            confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
            confirmed_round = confirmed_txn.get('confirmed-round', 0)
            
            # Update payment record if exists
            if payment_id:
                # First try to update PaymentTransaction (for invoice payments)
                try:
                    from payments.models import PaymentTransaction, Invoice
                    from django.utils import timezone
                    
                    payment_transaction = PaymentTransaction.objects.get(payment_transaction_id=payment_id)
                    payment_transaction.status = 'CONFIRMED'
                    payment_transaction.transaction_hash = tx_id
                    payment_transaction.save()
                    
                    # If this payment has an associated invoice, mark it as PAID
                    if payment_transaction.invoice:
                        invoice = payment_transaction.invoice
                        if invoice.status != 'PAID':
                            invoice.status = 'PAID'
                            invoice.paid_at = timezone.now()
                            invoice.paid_by_user = payment_transaction.payer_user
                            invoice.paid_by_business = payment_transaction.payer_business
                            invoice.save()
                            logger.info(f"Marked invoice {invoice.invoice_id} as PAID after blockchain confirmation")
                    
                    logger.info(f"Updated PaymentTransaction {payment_id} as confirmed with tx {tx_id}")
                    
                    # Create notifications (same logic as before)
                    # ... notification code can be added here if needed
                    
                except:
                    # Fall back to Payment model if PaymentTransaction doesn't exist
                    try:
                        payment_record = Payment.objects.get(payment_id=payment_id)
                        payment_record.status = 'completed'
                        payment_record.transaction_hash = tx_id
                        payment_record.confirmed_at_block = confirmed_round
                        payment_record.save()
                        
                        logger.info(f"Updated payment record {payment_id} as completed")
                    except Payment.DoesNotExist:
                        logger.warning(f"Payment record {payment_id} not found for update")
            
            logger.info(
                f"Sponsored payment confirmed for user {user.id}: "
                f"TxID: {tx_id}, Round: {confirmed_round}"
            )
            
            return cls(
                success=True,
                transaction_id=tx_id,
                confirmed_round=confirmed_round
            )
            
        except Exception as e:
            logger.error(f'Error submitting cUSD-style sponsored payment: {str(e)}', exc_info=True)
            
            # Update payment record as failed if exists
            if payment_id:
                try:
                    payment_record = Payment.objects.get(payment_id=payment_id)
                    payment_record.status = 'failed'
                    payment_record.error_message = str(e)
                    payment_record.save()
                except Payment.DoesNotExist:
                    pass
            
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
        payment_id = graphene.String(required=False, description="Payment ID for database update")
    
    success = graphene.Boolean()
    error = graphene.String()
    transaction_id = graphene.String()
    confirmed_round = graphene.Int()
    net_amount = graphene.Float()
    fee_amount = graphene.Float()
    
    @classmethod  
    def mutate(cls, root, info, signed_transactions, payment_id=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            logger.info(f"Submitting sponsored payment group for user {user.id}")
            logger.info(f"Raw signed_transactions type: {type(signed_transactions)}")
            logger.info(f"Raw signed_transactions: {signed_transactions[:200] if isinstance(signed_transactions, str) else str(signed_transactions)[:200]}")
            
            # Parse the signed_transactions - it might be a JSON string
            import msgpack
            import json
            from algosdk import transaction, encoding, mnemonic
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
            # Frontend sends: [{"index": 1, "transaction": "..."}, {"index": 2, "transaction": "..."}] for 4-txn groups
            # Or [{"index": 0, "transaction": "..."}, {"index": 1, "transaction": "..."}] for 3-txn groups
            if isinstance(signed_transactions, list) and len(signed_transactions) > 0:
                if isinstance(signed_transactions[0], dict) and 'transaction' in signed_transactions[0]:
                    logger.info(f"Extracting transactions from index/transaction format")
                    # Sort by index to ensure correct order
                    sorted_txns = sorted(signed_transactions, key=lambda x: x.get('index', 0))
                    # Log the indices we received
                    received_indices = [txn.get('index', -1) for txn in sorted_txns]
                    logger.info(f"Received transactions with indices: {received_indices}")
                    # Extract just the transaction strings
                    signed_transactions = [txn['transaction'] for txn in sorted_txns]
                    logger.info(f"Extracted {len(signed_transactions)} transaction strings")
            
            # Check if we're dealing with a 4-txn group (new format with 2 user transactions)
            # In the new format, we only get the 2 user-signed AXFERs
            if len(signed_transactions) == 2:
                logger.info("Detected 4-txn payment group; will load stored sponsor transactions")
                if not payment_id:
                    return cls(success=False, error='Payment ID required for 4-txn sponsored submission')
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

                # Prefer stored sponsor transactions from creation time to preserve exact group hash
                sponsor_b64_by_index = {}
                try:
                    from payments.models import PaymentTransaction
                    pt = PaymentTransaction.objects.filter(payment_transaction_id=payment_id).first()
                    if pt and pt.blockchain_data:
                        bd = pt.blockchain_data
                        if isinstance(bd, str):
                            bd = json.loads(bd)
                        for st in bd.get('sponsor_transactions', []):
                            sponsor_b64_by_index[st.get('index')] = st.get('txn')
                except Exception as e:
                    logger.warning(f"PaymentTransaction lookup/parse failed: {e}")
                if not sponsor_b64_by_index:
                    try:
                        pay = Payment.objects.get(payment_id=payment_id)
                        if pay.blockchain_data:
                            bd = pay.blockchain_data
                            if isinstance(bd, str):
                                bd = json.loads(bd)
                            for st in bd.get('sponsor_transactions', []):
                                sponsor_b64_by_index[st.get('index')] = st.get('txn')
                    except Exception as e:
                        logger.warning(f"Payment record lookup/parse failed: {e}")

                used_stored_sponsors = False
                if 0 in sponsor_b64_by_index and 3 in sponsor_b64_by_index:
                    # Assemble exact group with stored sponsor transactions
                    signed_txn_objects = [
                        sponsor_b64_by_index[0],
                        signed_transactions[0],
                        signed_transactions[1],
                        sponsor_b64_by_index[3],
                    ]
                    used_stored_sponsors = True
                    logger.info("Using stored sponsor transactions for 4-txn group")

                if not used_stored_sponsors:
                    # Rebuild and re-sign sponsor transactions from the live user-signed group
                    # Extract fields from user AXFER[0]
                    asset_id = user_txn.get('xaid', 0)
                    recipient_bytes = user_txn.get('arcv', b'')
                    if not isinstance(recipient_bytes, (bytes, bytearray)) or len(recipient_bytes) != 32:
                        return cls(success=False, error='Invalid recipient in user transaction')
                    recipient_address = encoding.encode_address(recipient_bytes)

                    # Build using builder (for IDs and sponsor address)
                    builder = PaymentTransactionBuilder(network=settings.ALGORAND_NETWORK)
                    # Reuse the user's transaction suggested params to keep group hash consistent
                    user_params_txn = user_txn  # dict under 'txn'
                    fv = user_params_txn.get('fv')
                    lv = user_params_txn.get('lv')
                    gh = user_params_txn.get('gh')
                    gen = user_params_txn.get('gen')
                    # Fallback to live suggested params if any missing
                    live_params = builder.algod_client.suggested_params()
                    from algosdk.transaction import SuggestedParams
                    params = SuggestedParams(
                        fee=getattr(live_params, 'min_fee', 1000) or 1000,
                        first=fv if isinstance(fv, int) else live_params.first,
                        last=lv if isinstance(lv, int) else live_params.last,
                        gh=gh if isinstance(gh, (bytes, bytearray)) else live_params.gh,
                        gen=gen if isinstance(gen, str) else live_params.gen,
                        flat_fee=True
                    )

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

                    # Determine method selector (used only for consistency in app args composition)
                    if asset_id == builder.cusd_asset_id:
                        method_name = "pay_with_cusd"
                    elif asset_id == builder.confio_asset_id:
                        method_name = "pay_with_confio"
                    else:
                        return cls(success=False, error=f'Unknown asset ID: {asset_id}')

                    from algosdk.abi import Method, Argument, Returns
                    method = Method(
                        name=method_name,
                        args=[
                            Argument(arg_type="address", name="recipient"),
                            Argument(arg_type="string", name="payment_id")
                        ],
                        returns=Returns(arg_type="void")
                    )

                    # Compute optional MBR top-up (capped), but allow 0
                    account_info = builder.algod_client.account_info(user_address)
                    current_balance = account_info.get('amount', 0)
                    min_balance_required = account_info.get('min-balance', 0)
                    mbr_topup = 0
                    if current_balance < min_balance_required:
                        mbr_topup = min(min_balance_required - current_balance, 100_000)

                    # Fees: sponsor pays for itself + 2 user AXFERs; app call pays own min fee
                    sponsor_payment_fee = (getattr(params, 'min_fee', 1000) or 1000) * 3
                    app_call_fee = getattr(params, 'min_fee', 1000) or 1000

                    from algosdk import transaction

                    sponsor_params = SuggestedParams(
                        fee=sponsor_payment_fee,
                        first=params.first,
                        last=params.last,
                        gh=params.gh,
                        gen=params.gen,
                        flat_fee=True
                    )
                    sponsor_payment = transaction.PaymentTxn(
                        sender=builder.sponsor_address,
                        sp=sponsor_params,
                        receiver=user_address,
                        amt=mbr_topup,
                        note=b"Sponsored payment" if mbr_topup == 0 else b"Sponsored payment with MBR"
                    )
                    sponsor_payment.group = group_id_bytes

                    # Build sponsor app call with strict fields
                    app_params = SuggestedParams(
                        fee=app_call_fee,
                        first=params.first,
                        last=params.last,
                        gh=params.gh,
                        gen=params.gen,
                        flat_fee=True
                    )

                    # ABI-encode args
                    from algosdk.abi import ABIType
                    string_type = ABIType.from_string("string")
                    recipient_arg = encoding.decode_address(recipient_address)
                    payment_id_arg = string_type.encode(payment_id if payment_id else "")

                    app_call = transaction.ApplicationCallTxn(
                        sender=builder.sponsor_address,
                        sp=app_params,
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

                    # Sign sponsor transactions
                    sponsor_mnemonic = settings.ALGORAND_SPONSOR_MNEMONIC
                    if not sponsor_mnemonic:
                        return cls(success=False, error='Sponsor mnemonic not configured')
                    sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)

                    from algosdk import encoding as algo_encoding
                    sponsor_payment_b64 = algo_encoding.msgpack_encode(sponsor_payment.sign(sponsor_private_key))
                    app_call_b64 = algo_encoding.msgpack_encode(app_call.sign(sponsor_private_key))

                    # Combine transactions in strict order [0..3]
                    signed_txn_objects = [
                        sponsor_payment_b64,
                        signed_transactions[0],
                        signed_transactions[1],
                        app_call_b64,
                    ]

                    logger.info("Rebuilt and re-signed sponsor transactions for 4-txn group (fallback)")
                
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
                        
                        # Test decode to validate
                        _ = base64.b64decode(txn_b64)
                        signed_txn_objects.append(txn_b64)
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
            
            # Debug: Log transaction structure before sending
            logger.info(f"=== SUBMITTING TRANSACTION GROUP ===")
            for i, txn_b64 in enumerate(signed_txn_objects):
                # Decode base64 to inspect transaction
                try:
                    import msgpack
                    txn_bytes = base64.b64decode(txn_b64)
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
                for txn_b64 in signed_txn_objects:
                    try:
                        txn_bytes = base64.b64decode(txn_b64)
                        txn_dict = msgpack.unpackb(txn_bytes, raw=False)
                        decoded_txns.append(txn_dict)
                    except:
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
                        
                        logger.info(f"  Txn[0] (pay): sender={pay_sender[:10]}..., receiver={pay_receiver[:10]}..., amount={pay_amount}")
                        logger.info(f"  Txn[1] (merchant axfer): sender={merchant_sender[:10]}..., receiver={merchant_receiver[:10]}..., amount={merchant_amount}")
                        logger.info(f"  Txn[2] (fee axfer): sender={fee_sender[:10]}..., receiver={fee_receiver[:10]}..., amount={fee_amount}")
                        logger.info(f"  Txn[3] (appl): sender={appl_sender[:10]}...")
                    else:
                        # 3-txn group (old format)
                        logger.info(f"  Txn[0] (pay): sender={pay_sender[:10]}..., receiver={pay_receiver[:10]}..., amount={pay_amount}")
                        logger.info(f"  Txn[1] (axfer): sender={axfer_sender[:10]}..., receiver={axfer_receiver[:10]}...")
                        logger.info(f"  Txn[2] (appl): sender={appl_sender[:10]}...")
                    
                    logger.info(f"AppCall details:")
                    logger.info(f"  ABI selector: {abi_selector}")
                    logger.info(f"  ABI recipient (at app_args[1]): {abi_recipient[:10]}..." if abi_recipient != 'missing' else "  ABI recipient: missing")
                    logger.info(f"  ABI payment_id (at app_args[2]): {abi_payment_id}")
                    logger.info(f"  Accounts[0] (payer): {accounts_0[:10]}..." if accounts_0 != 'missing' else "  Accounts[0]: missing")
                    logger.info(f"  Accounts[1] (recipient): {accounts_1[:10]}..." if accounts_1 != 'missing' else "  Accounts[1]: missing")
                    
                    # Critical assertions the contract will check
                    if is_4txn_group:
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
            # Combine all transactions and send as a single base64 string
            combined_txns = b''.join([base64.b64decode(t) for t in signed_txn_objects])
            try:
                tx_id = algod_client.send_raw_transaction(base64.b64encode(combined_txns).decode('utf-8'))
                logger.info(f"Payment transaction sent: {tx_id}")
            except Exception as e_send:
                # Attempt a TEAL dryrun for detailed diagnostics in DEBUG mode
                from django.conf import settings as dj_settings
                err_text = str(e_send)
                from algosdk.error import AlgodHTTPError
                if isinstance(e_send, AlgodHTTPError) and 'logic eval error' in err_text and getattr(dj_settings, 'DEBUG', False):
                    try:
                        # Build a dryrun request body that's compatible across SDK versions
                        # Expecting: {"txns": [ base64-encoded signed txn msgpacks ]}
                        dr_body = {"txns": signed_txn_objects}
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
                            # Some SDKs accept dict directly
                            dr_resp = dryrun_client.dryrun(dr_body)
                        except Exception:
                            # Fallback to raw JSON request
                            import json as _json
                            dr_bytes = _json.dumps(dr_body).encode('utf-8')
                            dr_resp = dryrun_client.algod_request("POST", "/v2/teal/dryrun", data=dr_bytes)
                        # Log a compact view of the dryrun trace
                        import json as _json
                        dr_json = _json.dumps(dr_resp, default=str)
                        logger.error(f"[DRYRUN] logic eval error during submit. Dryrun response (truncated): {dr_json[:4000]}")
                    except Exception as dre:
                        logger.error(f"[DRYRUN] Failed to execute dryrun: {dre}")
                # Re-raise so the outer handler updates DB and returns error to client
                raise
            
            # Wait for confirmation
            from algosdk.transaction import wait_for_confirmation
            confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
            confirmed_round = confirmed_txn.get('confirmed-round', 0)
            
            # Update payment record if exists
            if payment_id:
                # First try to update PaymentTransaction (for invoice payments)
                try:
                    from payments.models import PaymentTransaction, Invoice
                    from django.utils import timezone
                    
                    payment_transaction = PaymentTransaction.objects.get(payment_transaction_id=payment_id)
                    payment_transaction.status = 'CONFIRMED'
                    payment_transaction.transaction_hash = tx_id
                    payment_transaction.save()
                    
                    # If this payment has an associated invoice, mark it as PAID
                    if payment_transaction.invoice:
                        invoice = payment_transaction.invoice
                        if invoice.status != 'PAID':
                            invoice.status = 'PAID'
                            invoice.paid_at = timezone.now()
                            invoice.paid_by_user = payment_transaction.payer_user
                            invoice.paid_by_business = payment_transaction.payer_business
                            invoice.save()
                            logger.info(f"Marked invoice {invoice.invoice_id} as PAID after blockchain confirmation")
                    
                    # Now that blockchain confirmed, create and send notifications
                    try:
                        from notifications.models import Notification, NotificationType
                        from notifications.fcm_service import send_push_notification
                        from decimal import Decimal
                        
                        # Get all needed data for notifications
                        payer_user = payment_transaction.payer_user
                        payer_account = payment_transaction.payer_account
                        payer_business = payment_transaction.payer_business
                        payer_display_name = payment_transaction.payer_display_name
                        payer_phone = payment_transaction.payer_phone
                        
                        merchant_user = payment_transaction.merchant_account_user
                        merchant_account = payment_transaction.merchant_account
                        merchant_business = payment_transaction.merchant_business
                        merchant_display_name = payment_transaction.merchant_display_name
                        
                        # Convert amount to string for display with 2 decimal places
                        amount_decimal = Decimal(str(payment_transaction.amount))
                        amount_str = f"{amount_decimal:.2f}"
                        
                        logger.info(f"Creating notifications for confirmed payment {payment_transaction.id}")
                        
                        # Create notification for payer (sender)
                        payer_notification = Notification.objects.create(
                            user=payer_user,
                            account=payer_account,
                            business=payer_business,
                            notification_type=NotificationType.PAYMENT_SENT,
                            title="Pago enviado",
                            message=f"Pagaste {amount_str} {payment_transaction.token_type} a {merchant_display_name}",
                            data={
                                'transaction_type': 'payment',
                                'amount': f'-{amount_str}',  # Negative for sent
                                'token_type': payment_transaction.token_type,
                                'currency': payment_transaction.token_type,
                                'transaction_id': str(payment_transaction.id),
                                'payment_transaction_id': payment_transaction.payment_transaction_id,
                                'merchant_name': merchant_display_name,
                                'merchant_address': payment_transaction.merchant_address,
                                'payer_name': payer_display_name,
                                'payer_phone': payer_phone,
                                'payer_address': payment_transaction.payer_address,
                                'status': 'confirmed',  # Now it's confirmed!
                                'created_at': payment_transaction.created_at.isoformat(),
                                'description': payment_transaction.description or '',
                                'transaction_hash': tx_id,  # Use the real blockchain tx hash
                                'invoice_id': invoice.invoice_id if invoice else None,
                                # For TransactionDetailScreen
                                'type': 'sent',
                                'to': merchant_display_name,
                                'toAddress': payment_transaction.merchant_address,
                                'from': payer_display_name,
                                'fromAddress': payment_transaction.payer_address,
                                'date': payment_transaction.created_at.strftime('%Y-%m-%d'),
                                'time': payment_transaction.created_at.strftime('%H:%M'),
                                'hash': tx_id,
                            },
                            related_object_type='payment',
                            related_object_id=payment_transaction.id,
                            action_url=f'confio://transaction/{payment_transaction.id}'
                        )
                        
                        # Create notification for merchant (receiver)
                        merchant_notification = Notification.objects.create(
                            user=merchant_user,
                            account=merchant_account,
                            business=merchant_business,
                            notification_type=NotificationType.PAYMENT_RECEIVED,
                            title="Pago recibido",
                            message=f"Recibiste {amount_str} {payment_transaction.token_type} de {payer_display_name}",
                            data={
                                'transaction_type': 'payment',
                                'amount': f'+{amount_str}',  # Positive for received
                                'token_type': payment_transaction.token_type,
                                'currency': payment_transaction.token_type,
                                'transaction_id': str(payment_transaction.id),
                                'payment_transaction_id': payment_transaction.payment_transaction_id,
                                'payer_name': payer_display_name,
                                'payer_phone': payer_phone,
                                'payer_address': payment_transaction.payer_address,
                                'merchant_name': merchant_display_name,
                                'merchant_address': payment_transaction.merchant_address,
                                'status': 'confirmed',  # Now it's confirmed!
                                'created_at': payment_transaction.created_at.isoformat(),
                                'description': payment_transaction.description or '',
                                'transaction_hash': tx_id,  # Use the real blockchain tx hash
                                'invoice_id': invoice.invoice_id if invoice else None,
                                # For TransactionDetailScreen
                                'type': 'received',
                                'from': payer_display_name,
                                'fromAddress': payment_transaction.payer_address,
                                'to': merchant_display_name,
                                'toAddress': payment_transaction.merchant_address,
                                'date': payment_transaction.created_at.strftime('%Y-%m-%d'),
                                'time': payment_transaction.created_at.strftime('%H:%M'),
                                'hash': tx_id,
                            },
                            related_object_type='payment',
                            related_object_id=payment_transaction.id,
                            action_url=f'confio://transaction/{payment_transaction.id}'
                        )
                        
                        # Send push notifications
                        # Send to payer
                        logger.info(f"Sending push notification to payer {payer_user.id}")
                        payer_push_result = send_push_notification(
                            notification=payer_notification,
                            additional_data={
                                'type': 'payment',
                                'transactionType': 'payment'
                            }
                        )
                        logger.info(f"Payer push result: {payer_push_result}")
                        
                        # Send to merchant
                        logger.info(f"Sending push notification to merchant {merchant_user.id}")
                        merchant_push_result = send_push_notification(
                            notification=merchant_notification,
                            additional_data={
                                'type': 'payment',
                                'transactionType': 'payment'
                            }
                        )
                        logger.info(f"Merchant push result: {merchant_push_result}")
                        
                    except Exception as e:
                        # Log the error but don't fail the submission
                        logger.error(f"Error creating payment notifications: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    logger.info(f"Updated PaymentTransaction {payment_id} as confirmed with tx {tx_id}")
                except:
                    # Fall back to Payment model if PaymentTransaction doesn't exist
                    try:
                        payment_record = Payment.objects.get(payment_id=payment_id)
                        payment_record.status = 'completed'
                        payment_record.transaction_hash = tx_id
                        payment_record.confirmed_at_block = confirmed_round
                        payment_record.save()
                        
                        # Create receipt if payment was completed
                        PaymentReceipt.objects.create(
                            payment=payment_record,
                            transaction_hash=tx_id,
                            block_number=confirmed_round,
                            receipt_data={
                                'network': 'algorand',
                                'contract': 'payment',
                                'confirmed_round': confirmed_round
                            }
                        )
                        
                        logger.info(f"Updated payment record {payment_id} as completed")
                    except Payment.DoesNotExist:
                        logger.warning(f"Payment record {payment_id} not found for update")
            
            # Extract fee information from transaction (0.9% of gross)
            # This would need to be parsed from the actual transaction data
            # For now, we'll estimate based on the 0.9% fee
            
            logger.info(
                f"Sponsored payment confirmed for user {user.id}: "
                f"TxID: {tx_id}, Round: {confirmed_round}"
            )
            
            return cls(
                success=True,
                transaction_id=tx_id,
                confirmed_round=confirmed_round
            )
            
        except Exception as e:
            logger.error(f'Error submitting sponsored payment: {str(e)}', exc_info=True)
            
            # Update payment record as failed if exists
            if payment_id:
                try:
                    payment_record = Payment.objects.get(payment_id=payment_id)
                    payment_record.status = 'failed'
                    payment_record.error_message = str(e)
                    payment_record.save()
                except Payment.DoesNotExist:
                    pass
            
            return cls(success=False, error=str(e))


class CreateDirectPaymentMutation(graphene.Mutation):
    """
    Create a direct (non-sponsored) payment through the payment contract.
    User pays all fees themselves.
    """
    
    class Arguments:
        recipient_address = graphene.String(required=True, description="Algorand address of recipient")
        amount = graphene.Float(required=True, description="Amount to send (before fees)")
        asset_type = graphene.String(required=False, default_value='CUSD', description="CUSD or CONFIO")
        payment_id = graphene.String(required=False, description="Optional payment ID for tracking")
        note = graphene.String(required=False, description="Optional transaction note")
        create_receipt = graphene.Boolean(required=False, default_value=False, description="Store payment receipt on-chain")
    
    success = graphene.Boolean()
    error = graphene.String()
    transactions = graphene.JSONString(description="Array of unsigned transactions")
    user_signing_indexes = graphene.List(graphene.Int, description="All transaction indexes (user signs all)")
    group_id = graphene.String()
    gross_amount = graphene.Float(description="Amount user pays")
    net_amount = graphene.Float(description="Amount recipient receives after 0.9% fee")
    fee_amount = graphene.Float(description="0.9% fee deducted by contract")
    total_transaction_fee = graphene.Float(description="Total Algorand transaction fees in ALGO")
    
    @classmethod
    def mutate(cls, root, info, recipient_address, amount, asset_type='CUSD', 
              payment_id=None, note=None, create_receipt=False):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Get user's account
            user_account = Account.objects.filter(
                user=user,
                account_type='personal',
                deleted_at__isnull=True
            ).first()
            
            if not user_account or not user_account.algorand_address:
                return cls(success=False, error='No Algorand address found')
            
            # Validate recipient address
            import re
            if len(recipient_address) != 58 or not re.match(r'^[A-Z2-7]{58}$', recipient_address):
                return cls(success=False, error='Invalid recipient Algorand address format')
            
            # Initialize payment transaction builder
            builder = PaymentTransactionBuilder(network=settings.ALGORAND_NETWORK)
            
            # Determine asset ID
            asset_type_upper = asset_type.upper()
            if asset_type_upper == 'CUSD':
                asset_id = builder.cusd_asset_id
            elif asset_type_upper == 'CONFIO':
                asset_id = builder.confio_asset_id
            else:
                return cls(success=False, error=f'Unsupported asset type: {asset_type}')
            
            # Convert amount to base units
            decimals = 6  # Both cUSD and CONFIO use 6 decimals
            amount_in_base = int(Decimal(str(amount)) * Decimal(10 ** decimals))
            
            # Calculate net amount after 0.9% fee
            net_amount_base, fee_amount_base = builder.calculate_net_amount(amount_in_base)
            
            # Generate payment ID if not provided and receipt requested
            if create_receipt and not payment_id:
                import uuid
                payment_id = str(uuid.uuid4())
            
            # Build direct payment transaction group
            transactions, user_signing_indexes = builder.build_direct_payment(
                sender_address=user_account.algorand_address,
                recipient_address=recipient_address,
                amount=amount_in_base,
                asset_id=asset_id,
                payment_id=payment_id if create_receipt else None,
                note=note
            )
            
            # Encode unsigned transactions for client
            transaction_data = []
            for i, txn in enumerate(transactions):
                encoded_txn = base64.b64encode(
                    msgpack.packb(txn.dictify())
                ).decode()
                
                transaction_data.append({
                    'index': i,
                    'transaction': encoded_txn,
                    'signed': False,
                    'needs_signature': True
                })
            
            # Calculate total transaction fees
            total_fee = sum(txn.fee for txn in transactions)
            
            # Get group ID
            group_id = base64.b64encode(transactions[0].group).decode() if transactions[0].group else None
            
            logger.info(
                f"Created direct payment for user {user.id}: "
                f"{amount} {asset_type} to {recipient_address[:10]}... "
                f"(fees: {total_fee / 1_000_000} ALGO)"
            )
            
            return cls(
                success=True,
                transactions=transaction_data,
                user_signing_indexes=user_signing_indexes,
                group_id=group_id,
                gross_amount=amount_in_base / (10 ** decimals),
                net_amount=net_amount_base / (10 ** decimals),
                fee_amount=fee_amount_base / (10 ** decimals),
                total_transaction_fee=total_fee / 1_000_000  # Convert to ALGO
            )
            
        except Exception as e:
            logger.error(f'Error creating direct payment: {str(e)}', exc_info=True)
            return cls(success=False, error=str(e))
