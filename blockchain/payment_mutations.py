"""
Payment Contract GraphQL Mutations
Handles sponsored payments through the payment smart contract
"""
import graphene
import logging
from decimal import Decimal
from typing import Optional
from django.conf import settings
from django.db import transaction as db_transaction
from users.models import Account, User
from .models import Payment, PaymentReceipt
from .payment_transaction_builder import PaymentTransactionBuilder
from .algorand_account_manager import AlgorandAccountManager
from algosdk.v2client import algod
from algosdk import mnemonic, account
import asyncio
import base64
import msgpack
import json

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
            
            # First get sender context (who is paying)
            sender_jwt_context = get_jwt_business_context_with_validation(info, required_permission='send_funds')
            if not sender_jwt_context:
                return cls(success=False, error='No access or permission to send funds')
            
            sender_account_type = sender_jwt_context['account_type']
            sender_account_index = sender_jwt_context['account_index']
            sender_business_id = sender_jwt_context.get('business_id')
            
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
                # Personal account sending
                sender_account = Account.objects.filter(
                    user=user,
                    account_type=sender_account_type,
                    account_index=sender_account_index,
                    deleted_at__isnull=True
                ).first()
            
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
            
            # Check sender has opted into the asset
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            account_info = algod_client.account_info(sender_account.algorand_address)
            assets = account_info.get('assets', [])
            
            if not any(asset['asset-id'] == asset_id for asset in assets):
                return cls(
                    success=False,
                    error=f'You need to opt into {asset_type} before sending. Please use the opt-in feature first.'
                )
            
            # Check balance
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
            
            # Build sponsored payment transaction group
            try:
                transactions, user_signing_indexes = builder.build_sponsored_payment(
                    sender_address=sender_account.algorand_address,
                    recipient_address=resolved_recipient_address,
                    amount=amount_in_base,
                    asset_id=asset_id,
                    payment_id=payment_id if create_receipt else None,
                    note=note
                )
            except Exception as e:
                if payment_record:
                    payment_record.status = 'failed'
                    payment_record.save()
                raise e
            
            # Get sponsor private key for signing
            sponsor_mnemonic = settings.ALGORAND_SPONSOR_MNEMONIC
            sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
            
            # Prepare transaction data for client
            transaction_data = []
            for i, txn in enumerate(transactions):
                if i in user_signing_indexes:
                    # User needs to sign this - send unsigned
                    encoded_txn = base64.b64encode(
                        msgpack.packb(txn.dictify())
                    ).decode()
                    is_signed = False
                else:
                    # Sponsor signs this
                    signed_txn = txn.sign(sponsor_private_key)
                    encoded_txn = base64.b64encode(
                        msgpack.packb(signed_txn.dictify())
                    ).decode()
                    is_signed = True
                
                # Determine transaction type
                txn_type = 'unknown'
                if hasattr(txn, 'index') and txn.index:
                    txn_type = 'asset_transfer'
                elif hasattr(txn, 'payment_transaction_type'):
                    txn_type = 'payment'
                elif hasattr(txn, 'application_id'):
                    txn_type = 'app_call'
                
                transaction_data.append({
                    'index': i,
                    'type': txn_type,
                    'transaction': encoded_txn,
                    'signed': is_signed,
                    'needs_signature': not is_signed
                })
            
            # Get group ID
            group_id = base64.b64encode(transactions[0].group).decode() if transactions[0].group else None
            
            logger.info(
                f"Created sponsored payment for user {user.id}: "
                f"{amount} {asset_type} from {sender_account.algorand_address[:10]}... "
                f"to {resolved_recipient_address[:10]}... "
                f"(gross: {amount_in_base / (10 ** decimals)}, net: {net_amount_base / (10 ** decimals)}, "
                f"fee: {fee_amount_base / (10 ** decimals)})"
            )
            
            return cls(
                success=True,
                transactions=transaction_data,
                user_signing_indexes=user_signing_indexes,
                group_id=group_id,
                gross_amount=amount_in_base / (10 ** decimals),
                net_amount=net_amount_base / (10 ** decimals),
                fee_amount=fee_amount_base / (10 ** decimals),
                payment_id=payment_id
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
            
            # Decode transactions
            import msgpack
            decoded_txns = []
            for txn_data in signed_transactions:
                if isinstance(txn_data, dict):
                    txn_b64 = txn_data.get('transaction')
                else:
                    txn_b64 = txn_data
                
                decoded = base64.b64decode(txn_b64)
                decoded_txns.append(decoded)
            
            # Submit to Algorand network
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            # Send the grouped transactions
            tx_id = algod_client.send_raw_transaction(b''.join(decoded_txns))
            logger.info(f"Payment transaction sent: {tx_id}")
            
            # Wait for confirmation
            from algosdk.transaction import wait_for_confirmation
            confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
            confirmed_round = confirmed_txn.get('confirmed-round', 0)
            
            # Update payment record if exists
            if payment_id:
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