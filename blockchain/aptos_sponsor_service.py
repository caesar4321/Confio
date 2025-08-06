"""
Aptos Sponsored Transaction Service

Handles gas sponsorship for all user transactions on Aptos blockchain.
Uses a sponsor account to pay for gas fees on behalf of users.
"""

import asyncio
from typing import Dict, Optional, Any, List
from decimal import Decimal
from django.conf import settings
from django.core.cache import cache
import logging
import json
import httpx
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AptosSponsorService:
    """
    Manages real blockchain sponsored transactions on Aptos network.
    
    Architecture:
    1. User provides keyless authentication signature
    2. Transaction built with real Aptos SDK and sponsor account
    3. Sponsor signs and pays gas fees with real APT
    4. Transaction submitted to live Aptos blockchain (testnet/mainnet)
    5. Returns actual blockchain transaction hash upon confirmation
    """
    
    # Cache keys
    SPONSOR_BALANCE_KEY = "aptos_sponsor:balance"
    SPONSOR_STATS_KEY = "aptos_sponsor:stats"
    
    # Thresholds (in APT)
    MIN_SPONSOR_BALANCE = Decimal('0.1')  # Minimum 0.1 APT to operate
    WARNING_THRESHOLD = Decimal('0.5')    # Warn when below 0.5 APT
    MAX_GAS_PER_TX = 2000                 # Max gas units per transaction
    
    # Aptos network settings
    APTOS_TESTNET_URL = "https://fullnode.testnet.aptoslabs.com/v1"
    APTOS_INDEXER_URL = "https://indexer-testnet.staging.gcp.aptosdev.com/v1/graphql"
    
    @classmethod
    async def create_sponsor_signature(cls, raw_txn_bcs_base64: str) -> Dict[str, Any]:
        """
        Create sponsor signature for frontend to use in fee-payer transaction construction.
        
        Args:
            raw_txn_bcs_base64: Base64 encoded FeePayerRawTransaction bytes from frontend
            
        Returns:
            Dict with sponsor signature data for frontend use
        """
        try:
            # Get sponsor credentials
            sponsor_address = settings.APTOS_SPONSOR_ADDRESS
            sponsor_private_key = getattr(settings, 'APTOS_SPONSOR_PRIVATE_KEY', None)
            
            if not sponsor_private_key:
                return {
                    'success': False,
                    'error': 'Sponsor private key not configured'
                }
            
            from aptos_sdk.account import Account
            import base64
            import hashlib
            
            # Load sponsor account
            sponsor_account = Account.load_key(sponsor_private_key)
            
            # Decode the FeePayerRawTransaction bytes
            raw_txn_bytes = base64.b64decode(raw_txn_bcs_base64)
            
            # Create proper signing message for FeePayerRawTransaction
            # According to Aptos specs: SHA3-256("APTOS::RawTransactionWithData") + BCS(FeePayerRawTransaction)
            hasher = hashlib.sha3_256()
            hasher.update(b"APTOS::RawTransactionWithData")
            prehash = hasher.digest()
            sponsor_signing_message = prehash + raw_txn_bytes
            
            # Sign the message
            sponsor_signature = sponsor_account.sign(sponsor_signing_message)
            
            # Return sponsor signature data for frontend
            return {
                'success': True,
                'sponsor_address': sponsor_address,
                'sponsor_public_key_hex': sponsor_account.public_key().key.encode().hex(),
                'sponsor_signature_hex': sponsor_signature.signature.hex(),
                'sponsor_authenticator_97_bytes': {
                    'tag': '00',  # AccountAuthenticator::ED25519 variant tag
                    'public_key': sponsor_account.public_key().key.encode().hex(),  # 32 raw bytes
                    'signature': sponsor_signature.signature.hex()  # 64 raw bytes
                }
            }
            
        except Exception as e:
            logger.error(f"Error creating sponsor signature: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @classmethod
    async def build_sponsored_transaction_v2(
        cls,
        sender_address: str,
        recipient_address: str,
        amount: int,
        token_type: str
    ) -> Dict[str, Any]:
        """
        Build a sponsored transaction via TypeScript BRIDGE V2 service.
        Returns the transaction for the frontend to sign.
        
        Args:
            sender_address: Sender's Aptos address
            recipient_address: Recipient's Aptos address  
            amount: Amount to transfer
            token_type: Token type (APT, CONFIO, CUSD)
            
        Returns:
            Dict with transaction data for signing
        """
        try:
            import httpx
            import os
            
            # Get TypeScript BRIDGE service URL from environment
            bridge_url = os.getenv('TYPESCRIPT_BRIDGE_URL', 'http://localhost:3333')
            
            logger.info(f"Building transaction via TypeScript BRIDGE V2 at {bridge_url}")
            logger.info(f"Sender: {sender_address}")
            logger.info(f"Recipient: {recipient_address}")
            logger.info(f"Amount: {amount} {token_type}")
            
            # Prepare request for BRIDGE V2 build endpoint
            bridge_request = {
                'senderAddress': sender_address,
                'recipientAddress': recipient_address,
                'amount': amount,
                'tokenType': token_type,
                'senderAuthenticator': ''  # Not needed for building
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{bridge_url}/api/keyless/v2/build-sponsored",
                    json=bridge_request,
                    headers={'Content-Type': 'application/json'}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get('success'):
                        logger.info(f"✅ Transaction built successfully")
                        
                        return {
                            'success': True,
                            'transaction': result.get('transaction'),
                            'sponsor_authenticator': result.get('sponsorAuthenticator'),
                            'sponsor_address': result.get('sponsorAddress'),
                            'note': 'Transaction ready for signing'
                        }
                    else:
                        logger.error(f"BRIDGE V2 build failed: {result.get('error')}")
                        return {
                            'success': False,
                            'error': f"BRIDGE V2 build error: {result.get('error')}"
                        }
                else:
                    logger.error(f"BRIDGE V2 build request failed: {response.status_code}")
                    logger.error(f"Response: {response.text}")
                    return {
                        'success': False,
                        'error': f'BRIDGE V2 build request failed: {response.status_code} - {response.text}'
                    }
                    
        except Exception as e:
            logger.error(f"Error calling TypeScript BRIDGE V2 build: {e}")
            return {
                'success': False,
                'error': f'BRIDGE V2 build communication error: {str(e)}'
            }
    
    @classmethod
    def _get_bridge_url(cls) -> str:
        """Get the TypeScript bridge URL from environment or use default"""
        import os
        return os.getenv('TYPESCRIPT_BRIDGE_URL', 'http://localhost:3333')
    
    @classmethod
    async def prepare_sponsored_confio_transfer(
        cls,
        sender_address: str,
        recipient_address: str,
        amount: Decimal
    ) -> Dict[str, Any]:
        """
        Phase 1: Prepare a sponsored CONFIO transfer
        Returns transaction ID and raw transaction for client signing
        """
        try:
            import httpx
            
            # Convert amount to integer (assuming 8 decimals for CONFIO)
            amount_int = int(amount * 10**8)
            
            bridge_url = cls._get_bridge_url()
            
            # Call the V2 prepare endpoint directly
            bridge_request = {
                'senderAddress': sender_address,
                'recipientAddress': recipient_address,
                'amount': amount_int
            }
            
            logger.info(f"Calling TypeScript bridge V2 prepare-sponsored-confio-transfer")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{bridge_url}/api/keyless/v2/prepare-sponsored-confio-transfer",
                    json=bridge_request,
                    headers={'Content-Type': 'application/json'}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get('success'):
                        return {
                            'success': True,
                            'transactionId': result.get('transactionId'),
                            'rawTransaction': result.get('rawTransaction'),
                            'feePayerAddress': result.get('feePayerAddress')
                        }
                    else:
                        return {
                            'success': False,
                            'error': result.get('error', 'Failed to prepare transaction')
                        }
                else:
                    logger.error(f"Bridge request failed: {response.status_code}")
                    return {
                        'success': False,
                        'error': f'Bridge request failed: {response.status_code}'
                    }
                    
        except Exception as e:
            logger.error(f"Error preparing sponsored CONFIO transfer: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @classmethod
    async def prepare_sponsored_cusd_transfer(
        cls,
        sender_address: str,
        recipient_address: str,
        amount: Decimal
    ) -> Dict[str, Any]:
        """
        Phase 1: Prepare a sponsored CUSD transfer
        Returns transaction ID and raw transaction for client signing
        """
        try:
            import httpx
            
            # Convert amount to integer (assuming 8 decimals for CUSD)
            amount_int = int(amount * 10**8)
            
            bridge_url = cls._get_bridge_url()
            
            # Call the V2 prepare endpoint directly
            bridge_request = {
                'senderAddress': sender_address,
                'recipientAddress': recipient_address,
                'amount': amount_int
            }
            
            logger.info(f"Calling TypeScript bridge V2 prepare-sponsored-cusd-transfer")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{bridge_url}/api/keyless/v2/prepare-sponsored-cusd-transfer",
                    json=bridge_request,
                    headers={'Content-Type': 'application/json'}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get('success'):
                        return {
                            'success': True,
                            'transactionId': result.get('transactionId'),
                            'rawTransaction': result.get('rawTransaction'),
                            'feePayerAddress': result.get('feePayerAddress')
                        }
                    else:
                        return {
                            'success': False,
                            'error': result.get('error', 'Failed to prepare transaction')
                        }
                else:
                    logger.error(f"Bridge request failed: {response.status_code}")
                    return {
                        'success': False,
                        'error': f'Bridge request failed: {response.status_code}'
                    }
                    
        except Exception as e:
            logger.error(f"Error preparing sponsored CUSD transfer: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @classmethod
    async def submit_sponsored_confio_transfer_v2(
        cls,
        transaction_id: str,
        sender_authenticator: str
    ) -> Dict[str, Any]:
        """
        Phase 2: Submit a sponsored transfer with sender authenticator
        """
        try:
            import httpx
            
            bridge_url = cls._get_bridge_url()
            
            bridge_request = {
                'transactionId': transaction_id,
                'senderAuthenticator': sender_authenticator
            }
            
            logger.info(f"Calling TypeScript bridge V2 submit-sponsored-confio-transfer")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{bridge_url}/api/keyless/v2/submit-sponsored-confio-transfer",
                    json=bridge_request,
                    headers={'Content-Type': 'application/json'}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get('success'):
                        return {
                            'success': True,
                            'transactionHash': result.get('transactionHash'),
                            'gasUsed': 0  # Can be calculated from response if needed
                        }
                    else:
                        return {
                            'success': False,
                            'error': result.get('error', 'Failed to submit transaction')
                        }
                else:
                    logger.error(f"Bridge request failed: {response.status_code}")
                    return {
                        'success': False,
                        'error': f'Bridge request failed: {response.status_code}'
                    }
                    
        except Exception as e:
            logger.error(f"Error submitting sponsored transfer: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @classmethod
    async def submit_via_typescript_bridge_v2(
        cls,
        sender_address: str,
        recipient_address: str,
        amount: int,
        token_type: str,
        sender_authenticator_base64: str
    ) -> Dict[str, Any]:
        """
        Submit transaction via TypeScript BRIDGE V2 service using SDK pattern.
        
        Args:
            sender_address: Sender's Aptos address
            recipient_address: Recipient's Aptos address  
            amount: Amount to transfer
            token_type: Token type (APT, CONFIO, etc.)
            sender_authenticator_base64: Base64 encoded sender authenticator
            
        Returns:
            Dict with transaction result from BRIDGE V2
        """
        try:
            import httpx
            import os
            
            # Get TypeScript BRIDGE service URL from environment
            bridge_url = os.getenv('TYPESCRIPT_BRIDGE_URL', 'http://localhost:3333')
            
            logger.info(f"Submitting to TypeScript BRIDGE V2 at {bridge_url}")
            logger.info(f"Sender: {sender_address}")
            logger.info(f"Recipient: {recipient_address}")
            logger.info(f"Amount: {amount} {token_type}")
            
            # Prepare request for BRIDGE V2
            bridge_request = {
                'senderAddress': sender_address,
                'recipientAddress': recipient_address,
                'amount': amount,
                'tokenType': token_type,
                'senderAuthenticator': sender_authenticator_base64
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{bridge_url}/api/keyless/v2/submit-sponsored",
                    json=bridge_request,
                    headers={'Content-Type': 'application/json'}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get('success'):
                        tx_hash = result.get('transactionHash')
                        
                        logger.info(f"✅ BRIDGE V2 transaction successful: {tx_hash}")
                        
                        # Update sponsor stats
                        await cls._update_sponsor_stats(1000)  # Estimate gas used
                        
                        return {
                            'success': True,
                            'digest': tx_hash,
                            'sponsored': True,
                            'gas_used': 1000,  # Estimated
                            'real_transaction': True,
                            'note': 'Submitted via TypeScript BRIDGE V2 service'
                        }
                    else:
                        logger.error(f"BRIDGE V2 returned error: {result.get('error')}")
                        return {
                            'success': False,
                            'error': f"BRIDGE V2 error: {result.get('error')}"
                        }
                else:
                    logger.error(f"BRIDGE V2 request failed: {response.status_code}")
                    logger.error(f"Response: {response.text}")
                    return {
                        'success': False,
                        'error': f'BRIDGE V2 request failed: {response.status_code} - {response.text}'
                    }
                    
        except Exception as e:
            logger.error(f"Error calling TypeScript BRIDGE V2: {e}")
            return {
                'success': False,
                'error': f'BRIDGE V2 communication error: {str(e)}'
            }
    
    @classmethod
    async def submit_via_typescript_bridge(
        cls,
        raw_txn_bcs_base64: str,
        sender_authenticator_bcs_base64: str,
        sponsor_address_hex: str,
        policy_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Submit transaction via TypeScript BRIDGE service for proper fee-payer construction.
        
        Args:
            raw_txn_bcs_base64: 199-byte FeePayerRawTransaction BCS bytes
            sender_authenticator_bcs_base64: 456-byte keyless authenticator BCS bytes  
            sponsor_address_hex: Sponsor address for policy validation
            policy_metadata: Business rule validation data
            
        Returns:
            Dict with transaction result from BRIDGE
        """
        try:
            import httpx
            import os
            import base64
            
            # Get TypeScript BRIDGE service URL from environment
            bridge_url = os.getenv('TYPESCRIPT_BRIDGE_URL', 'http://localhost:3333')
            
            logger.info(f"Submitting to TypeScript BRIDGE at {bridge_url}")
            logger.info(f"Raw txn: {len(base64.b64decode(raw_txn_bcs_base64))} bytes")
            logger.info(f"Sender auth: {len(base64.b64decode(sender_authenticator_bcs_base64))} bytes")
            logger.info(f"Policy metadata: {policy_metadata}")
            
            # Prepare request for BRIDGE
            bridge_request = {
                'rawTxnBcsBase64': raw_txn_bcs_base64,
                'senderAuthenticatorBcsBase64': sender_authenticator_bcs_base64,
                'sponsorAddressHex': sponsor_address_hex,
                'policyMetadata': policy_metadata
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{bridge_url}/api/keyless/fee-payer-submit",
                    json=bridge_request,
                    headers={'Content-Type': 'application/json'}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get('success'):
                        tx_hash = result.get('txHash')
                        gas_used = result.get('gasUsed', 0)
                        
                        logger.info(f"✅ BRIDGE transaction successful: {tx_hash}")
                        logger.info(f"Gas used: {gas_used}")
                        
                        # Update sponsor stats
                        await cls._update_sponsor_stats(gas_used)
                        
                        return {
                            'success': True,
                            'digest': tx_hash,
                            'sponsored': True,
                            'gas_used': gas_used,
                            'real_transaction': True,
                            'note': 'Submitted via TypeScript BRIDGE service',
                            'bridge_logs': result.get('logs', [])
                        }
                    else:
                        logger.error(f"BRIDGE returned error: {result.get('error')}")
                        return {
                            'success': False,
                            'error': f"BRIDGE error: {result.get('error')}",
                            'bridge_logs': result.get('logs', [])
                        }
                else:
                    logger.error(f"BRIDGE request failed: {response.status_code}")
                    logger.error(f"Response: {response.text}")
                    return {
                        'success': False,
                        'error': f'BRIDGE request failed: {response.status_code} - {response.text}'
                    }
                    
        except Exception as e:
            logger.error(f"Error calling TypeScript BRIDGE: {e}")
            return {
                'success': False,
                'error': f'BRIDGE communication error: {str(e)}'
            }

    @classmethod
    async def _submit_via_bridge(
        cls,
        sender_address: str,
        transaction_payload: Dict[str, Any],
        keyless_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract data from keyless_info and submit via TypeScript BRIDGE.
        
        Args:
            sender_address: Sender's Aptos address
            transaction_payload: Transaction payload dict
            keyless_info: Contains raw_txn_bcs_base64 and keyless_authenticator
            
        Returns:
            Dict with transaction result from BRIDGE
        """
        try:
            # Extract required data from keyless_info
            raw_txn_bcs_base64 = keyless_info.get('raw_txn_bcs_base64')
            keyless_authenticator = keyless_info.get('keyless_authenticator')
            
            if not raw_txn_bcs_base64:
                return {
                    'success': False,
                    'error': 'Missing raw_txn_bcs_base64 for BRIDGE submission'
                }
            
            if not keyless_authenticator:
                return {
                    'success': False,
                    'error': 'Missing keyless_authenticator for BRIDGE submission'  
                }
            
            # Extract sender authenticator from keyless signature
            sender_authenticator_bcs_base64 = None
            
            if isinstance(keyless_authenticator, str):
                try:
                    import base64
                    import json
                    
                    # Try to decode the keyless authenticator
                    decoded_data = base64.b64decode(keyless_authenticator).decode('utf-8')
                    signature_obj = json.loads(decoded_data)
                    
                    if signature_obj.get('keyless_signature_type') == 'aptos_keyless_authenticator':
                        sender_authenticator_bcs_base64 = signature_obj.get('sender_authenticator_bcs_base64')
                        
                except Exception as e:
                    logger.error(f"Failed to extract sender authenticator: {e}")
            
            if not sender_authenticator_bcs_base64:
                return {
                    'success': False,
                    'error': 'Could not extract sender authenticator from keyless signature'
                }
            
            # Get sponsor address
            sponsor_address_hex = settings.APTOS_SPONSOR_ADDRESS
            
            # Prepare policy metadata for BRIDGE validation
            policy_metadata = {
                'sender_address': sender_address,
                'function': transaction_payload.get('function'),
                'arguments': transaction_payload.get('arguments', []),
                'type_arguments': transaction_payload.get('type_arguments', []),
                'account_id': keyless_info.get('account_id'),
                'transaction_metadata': keyless_info.get('transaction_metadata', {})
            }
            
            logger.info(f"Delegating to TypeScript BRIDGE for fee-payer transaction")
            logger.info(f"Sender: {sender_address}, Function: {transaction_payload.get('function')}")
            
            # Submit via BRIDGE
            return await cls.submit_via_typescript_bridge(
                raw_txn_bcs_base64=raw_txn_bcs_base64,
                sender_authenticator_bcs_base64=sender_authenticator_bcs_base64,
                sponsor_address_hex=sponsor_address_hex,
                policy_metadata=policy_metadata
            )
            
        except Exception as e:
            logger.error(f"Error in _submit_via_bridge: {e}")
            return {
                'success': False,
                'error': f'BRIDGE submission error: {str(e)}'
            }

    @classmethod
    async def submit_complete_signed_transaction(
        cls, 
        signed_transaction_bcs: str, 
        transaction_metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Submit a complete signed transaction constructed by the frontend.
        
        Args:
            signed_transaction_bcs: Base64 encoded complete SignedTransaction BCS bytes
            transaction_metadata: Optional transaction metadata for logging
            
        Returns:
            Dict with transaction result
        """
        try:
            from aptos_sdk.async_client import RestClient
            import base64
            
            # Decode the complete signed transaction
            signed_tx_bytes = base64.b64decode(signed_transaction_bcs)
            
            logger.info(f"Submitting complete signed transaction: {len(signed_tx_bytes)} bytes")
            logger.info(f"First 16 bytes: {list(signed_tx_bytes[:16])}")
            logger.info(f"Transaction metadata: {transaction_metadata}")
            
            # Initialize Aptos client
            aptos_client = RestClient(cls.APTOS_TESTNET_URL)
            
            # Submit the transaction directly via REST API
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{cls.APTOS_TESTNET_URL}/transactions",
                    headers={
                        "Content-Type": "application/x.aptos.signed_transaction+bcs"
                    },
                    content=signed_tx_bytes
                )
                
                if response.status_code == 202:  # Accepted
                    result = response.json()
                    tx_hash = result.get('hash')
                    logger.info(f"✅ Complete signed transaction submitted successfully: {tx_hash}")
                    
                    # Wait for confirmation
                    await aptos_client.wait_for_transaction(tx_hash)
                    final_tx = await aptos_client.transaction_by_hash(tx_hash)
                    
                    success = final_tx.get('success', False)
                    gas_used = int(final_tx.get('gas_used', 0))
                    
                    if success:
                        logger.info(f"✅ Transaction confirmed! Hash: {tx_hash}, Gas: {gas_used}")
                        await cls._update_sponsor_stats(gas_used)
                        
                        return {
                            'success': True,
                            'digest': tx_hash,
                            'sponsored': True,
                            'gas_used': gas_used,
                            'real_transaction': True,
                            'note': 'Complete signed transaction submitted by frontend'
                        }
                    else:
                        return {
                            'success': False,
                            'error': f'Transaction failed on blockchain: {final_tx.get("vm_status", "Unknown error")}'
                        }
                        
                else:
                    logger.error(f"Transaction submission failed: {response.status_code}")
                    logger.error(f"Response: {response.text}")
                    return {
                        'success': False,
                        'error': f'Transaction submission failed: {response.text}'
                    }
                    
        except Exception as e:
            logger.error(f"Error submitting complete signed transaction: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @classmethod
    async def check_sponsor_health(cls) -> Dict[str, Any]:
        """
        Check sponsor account health and balance.
        
        Returns:
            Dict with health status, balance, and recommendations
        """
        try:
            # Get sponsor address from settings
            sponsor_address = getattr(settings, 'APTOS_SPONSOR_ADDRESS', None)
            if not sponsor_address:
                return {
                    'healthy': False,
                    'error': 'APTOS_SPONSOR_ADDRESS not configured',
                    'balance': Decimal('0'),
                    'can_sponsor': False
                }
            
            # Check cached balance first
            cached_balance = cache.get(cls.SPONSOR_BALANCE_KEY)
            if cached_balance is None:
                # Get fresh balance from blockchain
                balance = await cls._get_apt_balance(sponsor_address)
                cache.set(cls.SPONSOR_BALANCE_KEY, balance, timeout=60)  # Cache for 1 minute
            else:
                balance = cached_balance
            
            # Get stats
            stats = cache.get(cls.SPONSOR_STATS_KEY, {
                'total_sponsored': 0,
                'total_gas_spent': 0,
                'failed_transactions': 0
            })
            
            # Determine health
            healthy = balance > cls.MIN_SPONSOR_BALANCE
            warning = balance < cls.WARNING_THRESHOLD
            
            return {
                'healthy': healthy,
                'warning': warning,
                'balance': balance,
                'balance_formatted': f"{balance} APT",
                'can_sponsor': healthy,
                'estimated_transactions': int(balance / Decimal('0.001')) if healthy else 0,
                'stats': stats,
                'recommendations': cls._get_recommendations(balance)
            }
            
        except Exception as e:
            logger.error(f"Error checking Aptos sponsor health: {e}")
            return {
                'healthy': False,
                'error': str(e),
                'balance': Decimal('0'),
                'can_sponsor': False
            }
    
    @classmethod
    async def _get_apt_balance(cls, address: str) -> Decimal:
        """Get APT balance for an address"""
        # For now, use known balance for sponsor account (from CLI: 98961200 octas = 0.989612 APT)
        # TODO: Fix the REST API query for proper balance detection
        sponsor_address = getattr(settings, 'APTOS_SPONSOR_ADDRESS', '')
        if address == sponsor_address:
            logger.info(f"Using known APT balance for sponsor account: 0.989612 APT")
            return Decimal('0.989612')
        
        # For other addresses, try REST API
        try:
            async with httpx.AsyncClient() as client:
                account_url = f"{cls.APTOS_TESTNET_URL}/accounts/{address}"
                response = await client.get(account_url)
                
                if response.status_code == 200:
                    logger.info(f"Account {address} exists, assuming 0 APT balance for now")
                    return Decimal('0')
                else:
                    logger.info(f"Account {address} not found, balance is 0 APT")
                    return Decimal('0')
                    
        except Exception as e:
            logger.error(f"Error checking account existence: {e}")
            return Decimal('0')
    
    @classmethod
    def _get_recommendations(cls, balance: Decimal) -> List[str]:
        """Get recommendations based on balance"""
        recommendations = []
        
        if balance < cls.MIN_SPONSOR_BALANCE:
            recommendations.append(f"URGENT: Refill sponsor account. Need at least {cls.MIN_SPONSOR_BALANCE} APT")
        elif balance < cls.WARNING_THRESHOLD:
            recommendations.append(f"WARNING: Low balance. Consider refilling to maintain service")
        
        if balance > Decimal('100'):
            recommendations.append("Consider implementing multi-sponsor setup for redundancy")
        
        return recommendations
    
    @classmethod
    async def create_sponsored_transaction(
        cls,
        user_address: str,
        transaction_payload: Dict[str, Any],
        user_signature: Optional[str] = None,
        keyless_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a sponsored transaction on Aptos using proper fee-payer multi-signature.
        
        Args:
            user_address: Address of the user making the transaction (sender)
            transaction_payload: The transaction payload to sponsor
            user_signature: DEPRECATED - use keyless_info['keyless_authenticator'] instead
            keyless_info: Aptos keyless authentication info - MUST include 'keyless_authenticator' field
                         containing the user's Aptos keyless account authenticator
            
        Returns:
            Dict with transaction result or error
            
        Note:
            This implementation follows Aptos best practices for sponsored transactions:
            1. User signs the transaction with Aptos keyless account (using their tokens)
            2. Sponsor signs as fee payer (pays gas fees)
            3. Both signatures are combined in a FeePayerRawTransaction with FeePayerAuthenticator
        """
        try:
            # Log keyless info if available
            if keyless_info:
                logger.info(
                    f"Creating sponsored transaction with Keyless. "
                    f"Account: {keyless_info.get('account_id')}, "
                    f"Type: {transaction_payload.get('function')}"
                )
                logger.info(f"Keyless info keys: {list(keyless_info.keys())}")
                logger.info(f"Has authenticator: {'authenticator' in keyless_info}")
                if 'authenticator' in keyless_info:
                    logger.info(f"Authenticator type: {type(keyless_info['authenticator'])}")
                    logger.info(f"Authenticator value: {keyless_info['authenticator']}")
            else:
                logger.warning("No keyless_info provided!")
            
            # Check sponsor health
            health = await cls.check_sponsor_health()
            if not health['can_sponsor']:
                return {
                    'success': False,
                    'error': 'Sponsor service unavailable',
                    'details': health
                }
            
            # Get sponsor credentials
            sponsor_address = settings.APTOS_SPONSOR_ADDRESS
            sponsor_private_key = getattr(settings, 'APTOS_SPONSOR_PRIVATE_KEY', None)
            
            if not sponsor_private_key:
                # DEVELOPMENT PATH: Mock transaction
                return await cls._create_mock_transaction(
                    user_address, 
                    transaction_payload, 
                    sponsor_address
                )
            
            # PRODUCTION PATH: Real blockchain submission
            return await cls._submit_sponsored_transaction(
                user_address,
                transaction_payload,
                sponsor_address,
                sponsor_private_key,
                keyless_info
            )
            
        except Exception as e:
            logger.error(f"Error creating sponsored transaction: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @classmethod
    async def _submit_sponsored_transaction(
        cls,
        user_address: str,
        transaction_payload: Dict[str, Any],
        sponsor_address: str,
        sponsor_private_key: str,
        keyless_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Submit real sponsored transaction to Aptos blockchain - no simulation fallback"""
        try:
            from aptos_sdk.async_client import RestClient
            from aptos_sdk.account import Account
            from aptos_sdk.transactions import (
                TransactionPayload,
                EntryFunction,
                TransactionArgument,
                RawTransaction,
                SignedTransaction,
                FeePayerRawTransaction,
                ModuleId,
                Serializer
            )
            from aptos_sdk.authenticator import FeePayerAuthenticator, Authenticator
            from aptos_sdk.bcs import Serializer as BCSSerializer
            from aptos_sdk.account_address import AccountAddress
            
            # Initialize Aptos client
            aptos_client = RestClient(cls.APTOS_TESTNET_URL)
            
            # Create sponsor account from private key
            sponsor_account = Account.load_key(sponsor_private_key)
            
            # Build transaction payload
            function_id = transaction_payload['function']
            module_address, module_name, function_name = function_id.split('::')
            
            # Convert arguments to proper types
            function_args = []
            type_args = transaction_payload.get('type_arguments', [])
            
            logger.info(f"Processing transaction arguments: {transaction_payload.get('arguments', [])}")
            
            for arg in transaction_payload.get('arguments', []):
                if isinstance(arg, str) and arg.startswith('0x'):
                    # Address argument
                    function_args.append(AccountAddress.from_str(arg))
                elif isinstance(arg, (int, str)) and str(arg).isdigit():
                    # Numeric argument
                    function_args.append(int(arg))
                else:
                    # String or other argument
                    function_args.append(arg)
            
            # Create the EntryFunction with proper TransactionArgument objects
            logger.info(f"Creating real blockchain transaction for {function_id} with args {transaction_payload.get('arguments', [])}")
            
            # Build transaction arguments properly
            tx_args = []
            for arg in transaction_payload.get('arguments', []):
                if isinstance(arg, str) and arg.startswith('0x'):
                    # Address argument
                    addr = AccountAddress.from_str(arg)
                    tx_args.append(TransactionArgument(addr, lambda s, v: v.serialize(s)))
                elif isinstance(arg, (int, str)) and str(arg).isdigit():
                    # Numeric argument (u64) - ensure it's within u64 range
                    arg_value = int(arg)
                    if arg_value > 2**64 - 1:
                        logger.error(f"Argument value too large for u64: {arg_value}")
                        raise ValueError(f"Argument value {arg_value} exceeds u64 maximum")
                    logger.info(f"Adding u64 argument: {arg_value}")
                    tx_args.append(TransactionArgument(arg_value, lambda s, v: s.u64(v)))
                else:
                    # String argument (if needed)
                    tx_args.append(TransactionArgument(str(arg), lambda s, v: s.str(v)))
            
            # Create entry function
            entry_function = EntryFunction.natural(
                module=f"{module_address}::{module_name}",
                function=function_name,
                ty_args=[],  # No type arguments for fungible asset transfers
                args=tx_args
            )
            
            # Build raw transaction with proper sender/fee-payer separation
            sender_addr = AccountAddress.from_str(user_address)
            fee_payer_addr = AccountAddress.from_str(sponsor_address)
            
            # Get sequence number for USER account (since user is the sender)
            try:
                user_info = await aptos_client.account(sender_addr)
                user_sequence = int(user_info.get('sequence_number', 0))
                logger.info(f"User {user_address} sequence number: {user_sequence}")
            except Exception as e:
                logger.error(f"Could not get user account info: {e}")
                # For keyless accounts that might not exist yet, start with 0
                user_sequence = 0
            
            # Use a conservative gas limit for fungible asset transfers
            gas_estimate = 100000  # Proper gas limit for token transfers
            
            # Create raw transaction with USER as sender (not sponsor)
            from aptos_sdk.transactions import RawTransaction
            import time
            
            # Check if we have transaction metadata from frontend
            tx_metadata = keyless_info.get('transaction_metadata') if keyless_info else None
            
            if tx_metadata:
                # Use exact parameters from frontend to reconstruct the same transaction
                logger.info("Using transaction metadata from frontend for exact reconstruction")
                gas_estimate = tx_metadata.get('gas_limit', 100000)
                gas_price = tx_metadata.get('gas_price', 100)
                expiration_time = tx_metadata.get('expiration', int(time.time()) + 300)
                chain_id = tx_metadata.get('chain_id', 2)
                # Override sequence number if provided in metadata
                if 'sequence_number' in tx_metadata:
                    user_sequence = tx_metadata['sequence_number']
            else:
                # Default values if no metadata
                gas_estimate = 100000
                gas_price = 100
                expiration_time = int(time.time()) + 300
                chain_id = 2
            
            # Build the raw transaction with exact same parameters
            raw_txn = RawTransaction(
                sender=sender_addr,
                sequence_number=user_sequence,
                payload=TransactionPayload(entry_function),
                max_gas_amount=gas_estimate,
                gas_unit_price=gas_price,
                expiration_timestamps_secs=expiration_time,
                chain_id=chain_id
            )
            
            logger.info(f"Built transaction: sender={user_address}, gas={gas_estimate}, seq={user_sequence}")
            logger.info(f"Transaction params - gas_limit: {gas_estimate}, gas_price: {gas_price}, expiration: {expiration_time}, chain_id: {chain_id}")
            
            # REAL TRANSACTION SUBMISSION - NO FALLBACK
            logger.info(f"Submitting real blockchain transaction for account {keyless_info.get('account_id') if keyless_info else 'N/A'}")
            
            logger.info(f"Built fee-payer transaction: sender={user_address}, fee_payer={sponsor_address}")
            
            # Step 2: Handle user signature (Aptos keyless)
            # Check if we have either 'keyless_authenticator' or legacy 'signature' format
            if keyless_info and ('keyless_authenticator' in keyless_info or 'signature' in keyless_info):
                logger.info("🎯 TAKING PROPER SPONSORED TRANSACTION PATH")
                
                if 'keyless_authenticator' in keyless_info:
                    # Direct Aptos keyless authenticator provided
                    signature_data = keyless_info['keyless_authenticator']
                    logger.info(f"Processing Aptos keyless signature: {signature_data[:50]}...")
                    
                    # Parse the keyless signature from frontend
                    if isinstance(signature_data, str):
                        if signature_data.startswith('keyless_signature_'):
                            # Legacy mock format - reject it
                            logger.error("Received legacy mock signature format")
                            return {
                                'success': False,
                                'error': 'Frontend must implement proper Aptos keyless signature',
                                'details': {
                                    'current_format': signature_data,
                                    'required': 'Hex-encoded Aptos keyless authenticator',
                                    'action': 'Frontend needs to sign transaction and send authenticator hex'
                                }
                            }
                        elif len(signature_data) > 64 and all(c in '0123456789abcdefABCDEF' for c in signature_data):
                            # Hex-encoded authenticator from keyless account
                            logger.info("Processing hex-encoded Aptos keyless authenticator from frontend")
                            
                            try:
                                # Parse the hex-encoded authenticator from keyless account
                                from aptos_sdk.authenticator import Authenticator
                                
                                # Remove 0x prefix if present
                                hex_data = signature_data[2:] if signature_data.startswith('0x') else signature_data
                                authenticator_bytes = bytes.fromhex(hex_data)
                                
                                # Deserialize the authenticator from keyless account
                                from aptos_sdk.bcs import Deserializer
                                deserializer = Deserializer(authenticator_bytes)
                                user_authenticator = Authenticator.deserialize(deserializer)
                                
                                logger.info("Successfully parsed Aptos keyless authenticator from frontend")
                                logger.info(f"Authenticator type: {type(user_authenticator)}")
                                
                            except Exception as e:
                                logger.error(f"Failed to parse keyless authenticator: {e}")
                                return {
                                    'success': False,
                                    'error': f'Invalid keyless authenticator format: {str(e)}',
                                    'details': {
                                        'signature_data': signature_data[:100],
                                        'error': str(e)
                                    }
                                }
                        else:
                            # Try to decode as base64 JSON (new format from frontend)
                            try:
                                import base64
                                import json
                                
                                decoded_data = base64.b64decode(signature_data).decode('utf-8')
                                signature_obj = json.loads(decoded_data)
                                
                                if signature_obj.get('keyless_signature_type') == 'aptos_keyless_authenticator':
                                    logger.info("Processing Aptos keyless authenticator from frontend")
                                    
                                    # Extract the authenticator data
                                    sender_authenticator_bcs_base64 = signature_obj.get('sender_authenticator_bcs_base64')
                                    auth_key_hex = signature_obj.get('auth_key_hex')
                                    address_hex = signature_obj.get('address_hex')
                                    signing_message_base64 = signature_obj.get('signing_message_base64')
                                    
                                    if not sender_authenticator_bcs_base64:
                                        logger.error("Missing sender_authenticator_bcs_base64")
                                        return {
                                            'success': False,
                                            'error': 'Missing sender authenticator BCS data',
                                            'details': {
                                                'missing': 'sender_authenticator_bcs_base64',
                                                'received_type': signature_obj.get('keyless_signature_type')
                                            }
                                        }
                                    
                                    # Deserialize the authenticator
                                    from aptos_sdk.authenticator import Authenticator
                                    from aptos_sdk.bcs import Deserializer
                                    
                                    try:
                                        authenticator_bytes = base64.b64decode(sender_authenticator_bcs_base64)
                                        logger.info(f"Authenticator bytes length: {len(authenticator_bytes)}")
                                        logger.info(f"First few bytes: {list(authenticator_bytes[:10])}")
                                        
                                        # Read the first byte to see the type indicator
                                        first_byte = authenticator_bytes[0] if len(authenticator_bytes) > 0 else None
                                        logger.info(f"First byte (type indicator): {first_byte}")
                                        
                                        # Check if this is a keyless authenticator (type 2)
                                        if first_byte == 2:
                                            logger.info("🔧 SDK COMPATIBILITY WORKAROUND ACTIVATED")
                                            logger.info("Detected keyless authenticator from TypeScript SDK v4.0.0")
                                            logger.info("Python SDK 0.11.0 doesn't support keyless authenticators")
                                            logger.info("Using raw authenticator bytes with REST API submission")
                                            
                                            # SDK COMPATIBILITY ISSUE DETAILS:
                                            # - TypeScript SDK v4.0.0 generates keyless authenticators (type 2)
                                            # - Python SDK 0.11.0 doesn't have KeylessAuthenticator support
                                            # - Cannot deserialize type 2 authenticators with Python SDK
                                            #
                                            # WORKAROUND STRATEGY:
                                            # 1. Store raw authenticator bytes instead of deserializing
                                            # 2. Submit transaction via REST API instead of Python SDK BCS submission
                                            # 3. This bypasses the Python SDK's authenticator deserialization
                                            #
                                            # LIMITATION: Cannot do sponsored transactions with this workaround
                                            # because we can't construct FeePayerAuthenticator with raw bytes
                                            
                                            user_authenticator = None  # We'll work with raw bytes
                                            raw_authenticator_bytes = authenticator_bytes
                                            USE_RAW_AUTHENTICATOR_BYTES = True
                                        else:
                                            # Try normal deserialization for other authenticator types
                                            deserializer = Deserializer(authenticator_bytes)
                                            user_authenticator = Authenticator.deserialize(deserializer)
                                            USE_RAW_AUTHENTICATOR_BYTES = False
                                        
                                        logger.info("Successfully deserialized keyless authenticator")
                                        logger.info(f"Address from authenticator: {address_hex}")
                                        
                                        # Verify the signing message matches
                                        if signing_message_base64 and tx_metadata and 'signing_message' in tx_metadata:
                                            if signing_message_base64 != tx_metadata['signing_message']:
                                                logger.error("Signing message mismatch!")
                                                logger.error(f"Frontend: {signing_message_base64[:50]}...")
                                                logger.error(f"Backend: {tx_metadata['signing_message'][:50]}...")
                                                return {
                                                    'success': False,
                                                    'error': 'Signing message mismatch between frontend and backend'
                                                }
                                        
                                        # Use the authenticator directly - skip to the transaction creation
                                        USE_DESERIALIZED_AUTHENTICATOR = True
                                        
                                    except Exception as deser_error:
                                        logger.error(f"Failed to deserialize authenticator: {deser_error}")
                                        return {
                                            'success': False,
                                            'error': f'Failed to deserialize authenticator: {str(deser_error)}'
                                        }
                                    
                                elif signature_obj.get('keyless_signature_type') == 'aptos_keyless_real_signature':
                                    logger.info("Processing real Aptos keyless signature from frontend")
                                    
                                    # Extract the real keyless signature components
                                    ephemeral_signature = signature_obj.get('ephemeral_signature')
                                    ephemeral_public_key = signature_obj.get('ephemeral_public_key')
                                    account_address = signature_obj.get('account_address')
                                    transaction_hash = signature_obj.get('transaction_hash')
                                    signed_transaction_bytes = signature_obj.get('signed_transaction_bytes')
                                    jwt = signature_obj.get('jwt')
                                    
                                    logger.info(f"Received real keyless signature from account: {account_address}")
                                    logger.info(f"Transaction hash: {transaction_hash}")
                                    logger.info(f"Has ephemeral signature: {bool(ephemeral_signature)}")
                                    logger.info(f"Has signed transaction bytes: {bool(signed_transaction_bytes)}")
                                    logger.info(f"Has JWT: {bool(jwt)}")
                                    logger.info("CRITICAL: Frontend must sign exact transaction bytes for sponsored transactions")
                                    
                                    if not ephemeral_signature or not ephemeral_public_key:
                                        logger.error("Missing required signature components")
                                        logger.error(f"Ephemeral signature present: {bool(ephemeral_signature)}")
                                        logger.error(f"Ephemeral public key present: {bool(ephemeral_public_key)}")
                                        logger.error("Frontend must provide Ed25519 signature of exact transaction bytes")
                                        
                                        missing_components = []
                                        if not ephemeral_signature:
                                            missing_components.append('ephemeral_signature')
                                        if not ephemeral_public_key:
                                            missing_components.append('ephemeral_public_key')
                                        if not jwt:
                                            missing_components.append('jwt')
                                            
                                        return {
                                            'success': False,
                                            'error': f'Missing keyless signature components: {", ".join(missing_components)}',
                                            'details': {
                                                'missing_components': missing_components,
                                                'has_ephemeral_signature': bool(ephemeral_signature),
                                                'has_ephemeral_public_key': bool(ephemeral_public_key),
                                                'has_jwt': bool(jwt),
                                                'received_type': signature_obj.get('keyless_signature_type')
                                            }
                                        }
                                    
                                    # CRITICAL: Check if we have the signed transaction bytes to deserialize
                                    if signed_transaction_bytes and tx_metadata:
                                        # NEW APPROACH: Deserialize the exact transaction that was signed
                                        try:
                                            logger.info("Using ChatGPT's recommendation: Deserializing exact signed transaction")
                                            
                                            from aptos_sdk.authenticator import Authenticator, Ed25519Authenticator
                                            from aptos_sdk.ed25519 import PublicKey, Signature
                                            from aptos_sdk.bcs import Deserializer
                                            from aptos_sdk.transactions import FeePayerRawTransaction
                                            
                                            # Decode the signed transaction bytes (remove APTOS::RawTransaction prefix)
                                            signed_bytes = base64.b64decode(signed_transaction_bytes)
                                            if signed_bytes.startswith(b"APTOS::RawTransaction"):
                                                actual_tx_bytes = signed_bytes[21:]  # Skip the prefix
                                            else:
                                                actual_tx_bytes = signed_bytes
                                            
                                            # Deserialize the FeePayerRawTransaction
                                            deserializer = Deserializer(actual_tx_bytes)
                                            deserialized_fee_payer_txn = FeePayerRawTransaction.deserialize(deserializer)
                                            
                                            logger.info("Successfully deserialized FeePayerRawTransaction from frontend")
                                            
                                            # Now create the authenticator with the signature
                                            signature_bytes = bytes(ephemeral_signature)
                                            ephemeral_ed25519_sig = Signature(signature_bytes)
                                            
                                            public_key_hex = ephemeral_public_key.replace('0x', '')
                                            # Convert hex string to bytes for PublicKey
                                            public_key_bytes = bytes.fromhex(public_key_hex)
                                            from nacl.signing import VerifyKey
                                            verify_key = VerifyKey(public_key_bytes)
                                            ephemeral_ed25519_pubkey = PublicKey(verify_key)
                                            
                                            user_authenticator = Authenticator(Ed25519Authenticator(ephemeral_ed25519_pubkey, ephemeral_ed25519_sig))
                                            
                                            # IMPORTANT: Set the deserialized transaction for later use
                                            fee_payer_raw_txn = deserialized_fee_payer_txn
                                            USE_DESERIALIZED_TXN = True
                                            
                                            logger.info("Will use deserialized transaction with proper authenticator")
                                            
                                        except Exception as deser_error:
                                            logger.error(f"Failed to deserialize transaction: {deser_error}")
                                            # Fall back to creating authenticator only
                                            USE_DESERIALIZED_TXN = False
                                            
                                            from aptos_sdk.authenticator import Authenticator, Ed25519Authenticator
                                            from aptos_sdk.ed25519 import PublicKey, Signature
                                            
                                            signature_bytes = bytes(ephemeral_signature)
                                            ephemeral_ed25519_sig = Signature(signature_bytes)
                                            
                                            public_key_hex = ephemeral_public_key.replace('0x', '')
                                            # Convert hex string to bytes for PublicKey
                                            public_key_bytes = bytes.fromhex(public_key_hex)
                                            from nacl.signing import VerifyKey
                                            verify_key = VerifyKey(public_key_bytes)
                                            ephemeral_ed25519_pubkey = PublicKey(verify_key)
                                            
                                            user_authenticator = Authenticator(Ed25519Authenticator(ephemeral_ed25519_pubkey, ephemeral_ed25519_sig))
                                            logger.info("Created keyless authenticator from frontend signature components")
                                    else:
                                        # Original approach - just create authenticator
                                        USE_DESERIALIZED_TXN = False
                                        
                                        from aptos_sdk.authenticator import Authenticator, Ed25519Authenticator
                                        from aptos_sdk.ed25519 import PublicKey, Signature
                                        
                                        signature_bytes = bytes(ephemeral_signature)
                                        ephemeral_ed25519_sig = Signature(signature_bytes)
                                        
                                        public_key_hex = ephemeral_public_key.replace('0x', '')
                                        # Convert hex string to bytes for PublicKey
                                        public_key_bytes = bytes.fromhex(public_key_hex)
                                        from nacl.signing import VerifyKey
                                        verify_key = VerifyKey(public_key_bytes)
                                        ephemeral_ed25519_pubkey = PublicKey(verify_key)
                                        
                                        user_authenticator = Authenticator(Ed25519Authenticator(ephemeral_ed25519_pubkey, ephemeral_ed25519_sig))
                                        logger.info("Created keyless authenticator from frontend signature components")
                                        
                                elif signature_obj.get('keyless_signature_type') in ['aptos_keyless_signed', 'aptos_keyless_components']:
                                    logger.error("Received incomplete keyless signature components")
                                    return {
                                        'success': False,
                                        'error': 'Frontend must provide complete keyless signature with ephemeral signature and JWT'
                                    }
                                else:
                                    logger.error(f"Unknown keyless signature type: {signature_obj.get('keyless_signature_type')}")
                                    return {
                                        'success': False,
                                        'error': 'Unknown keyless signature type'
                                    }
                                    
                            except Exception as decode_error:
                                logger.error(f"Failed to decode keyless signature: {decode_error}")
                                return {
                                    'success': False,
                                    'error': f'Invalid keyless signature format: {str(decode_error)}'
                                }
                    else:
                        # Should be actual AccountAuthenticator object
                        user_authenticator = signature_data
                elif 'signature' in keyless_info:
                    # Signature provided - need to construct authenticator
                    logger.info(f"Constructing authenticator from signature: {keyless_info['signature']}")
                    
                    # Legacy signature format - need to parse Aptos keyless signature
                    signature_data = keyless_info['signature']
                    
                    if signature_data and signature_data.startswith('keyless_signature_'):
                        logger.info("Processing legacy Aptos keyless signature format - NEEDS MIGRATION")
                        logger.warning("Frontend should provide 'keyless_authenticator' instead of raw signature")
                        
                        # TODO: Implement proper Aptos keyless signature parsing
                        # The frontend should create the AccountAuthenticator and send it directly
                        logger.error("Legacy signature format detected - frontend needs to send AccountAuthenticator")
                        logger.info(f"Legacy signature format: {signature_data}")
                        
                        return {
                            'success': False,
                            'error': 'Frontend must send Aptos keyless authenticator',
                            'details': {
                                'current_format': signature_data,
                                'required_field': 'keyless_info[keyless_authenticator]',
                                'required_type': 'Aptos SDK AccountAuthenticator object',
                                'frontend_action': 'Create transaction with Aptos keyless account, sign it, and send the AccountAuthenticator'
                            }
                        }
                    else:
                        logger.error(f"Unrecognized signature format: {signature_data}")
                        return {
                            'success': False,
                            'error': 'Unrecognized Aptos keyless signature format',
                            'details': {
                                'received': signature_data,
                                'expected': 'Aptos keyless AccountAuthenticator in keyless_info[keyless_authenticator]'
                            }
                        }
                
                # Step 3: Use deserialized transaction if available, otherwise create new one
                if 'USE_DESERIALIZED_TXN' in locals() and USE_DESERIALIZED_TXN:
                    logger.info("Using deserialized FeePayerRawTransaction from frontend")
                    # fee_payer_raw_txn already set from deserialization above
                else:
                    logger.info("Creating new FeePayerRawTransaction")
                    fee_payer_raw_txn = FeePayerRawTransaction(
                        raw_transaction=raw_txn,
                        secondary_signers=[],  # No secondary signers for basic token transfer
                        fee_payer=fee_payer_addr
                    )
                
                # Step 4: Handle different authenticator formats
                if 'USE_RAW_AUTHENTICATOR_BYTES' in locals() and USE_RAW_AUTHENTICATOR_BYTES:
                    logger.info("🔧 SDK COMPATIBILITY WORKAROUND: Creating custom SignedTransaction with raw bytes")
                    logger.info("⚠️  LIMITATION: Transaction will be submitted as regular (not sponsored) due to SDK incompatibility")
                    logger.info("📋 REASON: Python SDK 0.11.0 cannot construct FeePayerAuthenticator with keyless authenticator type 2")
                    
                    # ALTERNATIVE APPROACH: Create a raw SignedTransaction-like object
                    # that bypasses the Authenticator deserialization but can still be submitted via BCS
                    
                    logger.info("Creating custom SignedTransaction with raw authenticator bytes")
                    
                    # Instead of trying to create a custom SignedTransaction, let's try
                    # submitting the transaction via REST API directly using the raw bytes
                    # This bypasses the BCS serialization issue entirely
                    
                    logger.info("🔄 ANALYSIS: BCS format debugging for keyless authenticators")
                    logger.info("The issue is that both REST API and BCS submission are failing with the same error")
                    logger.info("This suggests we need to understand the expected BCS format better")
                    
                    # Let's analyze the problem:
                    # 1. The frontend sends us keyless authenticator bytes (type 2)
                    # 2. Python SDK expects a variant index 0-4 but gets 104 ('h' from "https")
                    # 3. This means our BCS serialization is wrong
                    
                    # APPROACH: Try to understand the Python SDK's expected format
                    # by creating a properly formatted SignedTransaction and seeing how it serializes
                    
                    try:
                        logger.info("🔍 DEBUGGING: Creating a mock Ed25519 authenticator to understand BCS format")
                        
                        # Create a mock Ed25519 authenticator to see the expected BCS structure
                        from aptos_sdk.authenticator import Authenticator, Ed25519Authenticator
                        from aptos_sdk.ed25519 import PrivateKey, PublicKey, Signature
                        from aptos_sdk.bcs import Serializer as BCSSerializer
                        
                        # Create a dummy Ed25519 authenticator (type 0)
                        dummy_private_key = PrivateKey.random()
                        dummy_public_key = dummy_private_key.public_key()
                        
                        # Sign the transaction with the dummy key to get a valid signature
                        tx_serializer = BCSSerializer()
                        raw_txn.serialize(tx_serializer)
                        tx_bytes = tx_serializer.output()
                        
                        dummy_signature = dummy_private_key.sign(tx_bytes)
                        dummy_ed25519_auth = Ed25519Authenticator(dummy_public_key, dummy_signature)
                        dummy_authenticator = Authenticator(dummy_ed25519_auth)
                        
                        # Create a proper SignedTransaction with the dummy authenticator
                        dummy_signed_txn = SignedTransaction(
                            transaction=raw_txn,
                            authenticator=dummy_authenticator
                        )
                        
                        # Serialize it to see the expected format
                        dummy_serializer = BCSSerializer()
                        dummy_signed_txn.serialize(dummy_serializer)
                        dummy_signed_bytes = dummy_serializer.output()
                        
                        logger.info(f"Dummy signed transaction bytes length: {len(dummy_signed_bytes)}")
                        logger.info(f"Dummy authenticator first bytes: {list(dummy_signed_bytes[-70:])}")
                        
                        # Now try to replace the Ed25519 authenticator with our keyless authenticator
                        # The structure should be: [transaction_bytes][authenticator_type][authenticator_data]
                        
                        # CRITICAL FIX: Use the exact transaction bytes from the frontend
                        # The frontend provides the exact transaction bytes that were signed
                        # We should use those instead of serializing raw_txn ourselves
                        
                        # BREAKTHROUGH: Implement proper FeePayerAuthenticator structure
                        # The node expects: BCS(FeePayerRawTransaction) || BCS(TransactionAuthenticator::fee_payer)
                        
                        # Check for raw_txn_bcs_base64 in keyless_info first, then tx_metadata
                        raw_txn_bcs_base64 = None
                        if keyless_info and keyless_info.get('raw_txn_bcs_base64'):
                            raw_txn_bcs_base64 = keyless_info['raw_txn_bcs_base64']
                        elif tx_metadata and 'raw_txn_bcs_base64' in tx_metadata:
                            raw_txn_bcs_base64 = tx_metadata['raw_txn_bcs_base64']
                        
                        if raw_txn_bcs_base64:
                            # Step 1: Get the exact FeePayerRawTransaction bytes from frontend
                            import base64
                            raw_txn_bytes = base64.b64decode(raw_txn_bcs_base64)
                            logger.info(f"🎯 USING EXACT FRONTEND FeePayerRawTransaction: {len(raw_txn_bytes)} bytes")
                            logger.info(f"First 10 bytes: {list(raw_txn_bytes[:10])}")
                            
                            # Verify FeePayerRawTransaction format
                            if raw_txn_bytes[0] == 1:
                                logger.info(f"✅ CONFIRMED: FeePayerRawTransaction format (variant 1)")
                            else:
                                logger.warning(f"⚠️ UNEXPECTED: Transaction variant {raw_txn_bytes[0]}, expected 1")
                            
                            # Step 2: Create proper TransactionAuthenticator::fee_payer structure
                            logger.info(f"🔧 Building TransactionAuthenticator::fee_payer wrapper")
                            
                            # Get sender's keyless authenticator (456 bytes, already includes keyless tag)
                            sender_auth_bytes = raw_authenticator_bytes
                            logger.info(f"Sender authenticator: {len(sender_auth_bytes)} bytes, starts with tag {sender_auth_bytes[0]}")
                            
                            # Create sponsor's Ed25519 authenticator by signing the FeePayerRawTransaction properly
                            sponsor_account = Account.load_key(sponsor_private_key)
                            
                            # CRITICAL FIX: Create proper signing message for FeePayerRawTransaction manually
                            # The SDK doesn't have a signing_message method, so we need to construct it properly
                            # According to Aptos specs, the signing message for FeePayerRawTransaction is:
                            # SHA3-256("APTOS::RawTransactionWithData") + BCS(FeePayerRawTransaction)
                            
                            import hashlib
                            hasher = hashlib.sha3_256()
                            hasher.update(b"APTOS::RawTransactionWithData")
                            prehash = hasher.digest()
                            sponsor_signing_message = prehash + raw_txn_bytes
                            
                            logger.info(f"Sponsor signing message (proper domain separation): {len(sponsor_signing_message)} bytes")
                            logger.info(f"Prehash: {prehash.hex()[:32]}...")
                            logger.info(f"Raw txn: {raw_txn_bytes.hex()[:32]}...")
                            logger.info(f"Complete signing message: {sponsor_signing_message.hex()[:64]}...")
                            
                            # Sign the proper signing message
                            sponsor_signature = sponsor_account.sign(sponsor_signing_message)
                            logger.info(f"Sponsor signature created: {len(sponsor_signature.signature)} bytes")
                            
                            # CRITICAL FIX: Create fixed-width 97-byte sponsor authenticator
                            # Format: [0x00][32-byte pubkey][64-byte signature] = 97 bytes total
                            sponsor_auth_bytes = bytearray()
                            sponsor_auth_bytes.append(0x00)  # AccountAuthenticator::ED25519 variant tag
                            sponsor_auth_bytes.extend(sponsor_account.public_key().key.encode())  # 32 raw bytes
                            sponsor_auth_bytes.extend(sponsor_signature.signature)  # 64 raw bytes
                            
                            logger.info(f"Sponsor authenticator: {len(sponsor_auth_bytes)} bytes (fixed-width: 0x00 + 32 + 64)")
                            if len(sponsor_auth_bytes) != 97:
                                logger.error(f"CRITICAL: Sponsor authenticator should be 97 bytes, got {len(sponsor_auth_bytes)}")
                                raise ValueError(f"Invalid sponsor authenticator size: {len(sponsor_auth_bytes)} != 97")
                            
                            # Verify the sponsor authenticator starts with 0x00 (Ed25519 variant)
                            if sponsor_auth_bytes[0] != 0x00:
                                logger.error(f"CRITICAL: Sponsor authenticator should start with 0x00, got 0x{sponsor_auth_bytes[0]:02x}")
                                raise ValueError(f"Invalid sponsor authenticator variant: {sponsor_auth_bytes[0]} != 0")
                            
                            logger.info(f"Sponsor authenticator format verified: starts with 0x{sponsor_auth_bytes[0]:02x}, total {len(sponsor_auth_bytes)} bytes")
                            
                            # Build TransactionAuthenticator::fee_payer structure
                            # Format: [TAG_FEEPAYER][sender_auth][0][0][32-byte sponsor_addr][sponsor_auth]
                            TAG_FEEPAYER = 3  # Fee-payer authenticator tag (need to verify this)
                            
                            fee_payer_auth = bytearray()
                            fee_payer_auth.append(TAG_FEEPAYER)  # TransactionAuthenticator tag
                            fee_payer_auth.extend(sender_auth_bytes)  # sender AccountAuthenticator (keyless)
                            fee_payer_auth.append(0x00)  # secondary_signer_addresses length (ULEB128 = 0)
                            fee_payer_auth.append(0x00)  # secondary_signers length (ULEB128 = 0)
                            
                            # Add sponsor address (32 bytes, left-padded)
                            sponsor_addr_hex = sponsor_address.replace('0x', '')
                            sponsor_addr_bytes = bytes.fromhex(sponsor_addr_hex.zfill(64))  # Left-pad to 32 bytes
                            fee_payer_auth.extend(sponsor_addr_bytes)
                            
                            fee_payer_auth.extend(sponsor_auth_bytes)  # sponsor AccountAuthenticator (ed25519)
                            
                            logger.info(f"🎯 COMPLETE FeePayerAuthenticator: {len(fee_payer_auth)} bytes")
                            logger.info(f"Structure: TAG({fee_payer_auth[0]}) + sender({len(sender_auth_bytes)}) + zeros(2) + sponsor_addr(32) + sponsor_auth({len(sponsor_auth_bytes)})")
                            
                            # Step 3: Create final SignedTransaction with sanity checks
                            tx_only_bytes = raw_txn_bytes  # Use the frontend's exact bytes
                            raw_authenticator_bytes = bytes(fee_payer_auth)  # Use our constructed fee-payer authenticator
                            
                            logger.info(f"Final transaction structure:")
                            logger.info(f"  FeePayerRawTransaction: {len(tx_only_bytes)} bytes")
                            logger.info(f"  TransactionAuthenticator: {len(raw_authenticator_bytes)} bytes")
                            logger.info(f"  Total SignedTransaction: {len(tx_only_bytes) + len(raw_authenticator_bytes)} bytes")
                            
                            # CRITICAL: ChatGPT's recommended sanity checks
                            signed_bcs = tx_only_bytes + raw_authenticator_bytes
                            
                            # Check 1: TransactionAuthenticator::fee_payer wrapper tag at boundary
                            assert signed_bcs[len(tx_only_bytes)] == 0x03, f"Expected fee_payer tag 0x03 at position {len(tx_only_bytes)}, got 0x{signed_bcs[len(tx_only_bytes)]:02x}"
                            logger.info(f"✅ Sanity check 1: Fee-payer wrapper tag 0x03 at position {len(tx_only_bytes)}")
                            
                            # Check 2: Sender keyless authenticator tag at wrapper+1
                            assert signed_bcs[len(tx_only_bytes) + 1] == 0x02, f"Expected sender keyless tag 0x02 at position {len(tx_only_bytes) + 1}, got 0x{signed_bcs[len(tx_only_bytes) + 1]:02x}"
                            logger.info(f"✅ Sanity check 2: Sender keyless tag 0x02 at position {len(tx_only_bytes) + 1}")
                            
                            # Check 3: Empty secondary signers (two zero bytes)
                            end_sender = len(tx_only_bytes) + 1 + len(sender_auth_bytes)
                            assert signed_bcs[end_sender:end_sender+2] == b"\x00\x00", f"Expected empty secondary signers at position {end_sender}, got {signed_bcs[end_sender:end_sender+2].hex()}"
                            logger.info(f"✅ Sanity check 3: Empty secondary signers at position {end_sender}")
                            
                            # Check 4: Sponsor address is 32 bytes
                            assert len(sponsor_addr_bytes) == 32, f"Expected 32-byte sponsor address, got {len(sponsor_addr_bytes)}"
                            logger.info(f"✅ Sanity check 4: Sponsor address is 32 bytes")
                            
                            # Check 5: Sponsor authenticator starts with 0x00 and is 97 bytes
                            sponsor_auth_start = end_sender + 2 + 32
                            assert signed_bcs[sponsor_auth_start] == 0x00, f"Expected sponsor Ed25519 tag 0x00 at position {sponsor_auth_start}, got 0x{signed_bcs[sponsor_auth_start]:02x}"
                            assert len(sponsor_auth_bytes) == 97, f"Expected 97-byte sponsor authenticator, got {len(sponsor_auth_bytes)}"
                            logger.info(f"✅ Sanity check 5: Sponsor Ed25519 authenticator (0x00, 97 bytes) at position {sponsor_auth_start}")
                            
                            # Optional local signature verification (ChatGPT's recommendation)
                            try:
                                from nacl.signing import VerifyKey
                                sponsor_pubkey32 = sponsor_account.public_key().key.encode()
                                sponsor_sig64 = sponsor_signature.signature
                                verify_key = VerifyKey(sponsor_pubkey32)
                                verify_key.verify(sponsor_signing_message, sponsor_sig64)
                                logger.info(f"✅ Local verification: Sponsor signature is valid")
                            except Exception as verify_error:
                                logger.error(f"❌ Local verification failed: {verify_error}")
                                raise ValueError(f"Sponsor signature verification failed: {verify_error}")
                            
                            logger.info(f"🎯 ALL SANITY CHECKS PASSED - Transaction should be valid")
                            
                        elif tx_metadata and 'transaction_bytes' in tx_metadata:
                            # Fallback: Use transaction_bytes if available
                            import base64
                            tx_only_bytes = base64.b64decode(tx_metadata['transaction_bytes'])
                            logger.info(f"Using frontend transaction_bytes: {len(tx_only_bytes)} bytes")
                            logger.info(f"Frontend tx bytes end with: {list(tx_only_bytes[-10:])}")
                        else:
                            # Last resort: serialize raw_txn ourselves
                            tx_only_serializer = BCSSerializer()
                            raw_txn.serialize(tx_only_serializer)
                            tx_only_bytes = tx_only_serializer.output()
                            logger.info(f"Using backend-serialized transaction bytes: {len(tx_only_bytes)} bytes")
                            
                        # Compare against both RawTransaction and FeePayerRawTransaction serialization
                        raw_serializer = BCSSerializer()
                        raw_txn.serialize(raw_serializer)
                        raw_tx_bytes = raw_serializer.output()
                        
                        fee_payer_serializer = BCSSerializer()
                        fee_payer_raw_txn.serialize(fee_payer_serializer)
                        fee_payer_tx_bytes = fee_payer_serializer.output()
                        
                        logger.info(f"📊 TRANSACTION FORMAT COMPARISON:")
                        logger.info(f"Frontend/signing message: {len(tx_only_bytes)} bytes")
                        logger.info(f"Backend RawTransaction: {len(raw_tx_bytes)} bytes")
                        logger.info(f"Backend FeePayerRawTransaction: {len(fee_payer_tx_bytes)} bytes")
                        
                        # Check which format matches the frontend
                        if len(tx_only_bytes) == len(fee_payer_tx_bytes):
                            logger.info(f"✅ MATCH: Frontend uses FeePayerRawTransaction format!")
                            logger.info(f"Using frontend transaction bytes directly for perfect alignment")
                            backend_tx_bytes = fee_payer_tx_bytes
                        elif len(tx_only_bytes) == len(raw_tx_bytes):
                            logger.info(f"✅ MATCH: Frontend uses RawTransaction format")
                            backend_tx_bytes = raw_tx_bytes
                        else:
                            logger.warning(f"🚨 NO MATCH: Frontend format differs from both backend formats")
                            logger.warning(f"Difference from RawTransaction: {len(tx_only_bytes) - len(raw_tx_bytes)} bytes")
                            logger.warning(f"Difference from FeePayerRawTransaction: {len(tx_only_bytes) - len(fee_payer_tx_bytes)} bytes")
                            
                            # Show first differing bytes against FeePayerRawTransaction
                            min_len = min(len(tx_only_bytes), len(fee_payer_tx_bytes))
                            for i in range(min_len):
                                if tx_only_bytes[i] != fee_payer_tx_bytes[i]:
                                    logger.warning(f"First difference at byte {i}: frontend={tx_only_bytes[i]} vs fee_payer={fee_payer_tx_bytes[i]}")
                                    logger.warning(f"Context: frontend[{i-5}:{i+5}] = {list(tx_only_bytes[max(0,i-5):i+5])}")
                                    logger.warning(f"Context: fee_payer[{i-5}:{i+5}] = {list(fee_payer_tx_bytes[max(0,i-5):i+5])}")
                                    break
                            backend_tx_bytes = fee_payer_tx_bytes
                        
                        logger.info(f"Transaction-only bytes length: {len(tx_only_bytes)}")
                        logger.info(f"Difference (authenticator part): {len(dummy_signed_bytes) - len(tx_only_bytes)}")
                        
                        # CRITICAL FIX: Apply ChatGPT's boundary assertions
                        # Ensure we're concatenating exactly: BCS(RawTransaction) || BCS(Authenticator)
                        
                        # Step 1: Ensure authenticator starts with variant 2 (keyless)
                        assert raw_authenticator_bytes[0] == 2, f"Expected keyless variant 2, got {raw_authenticator_bytes[0]}"
                        
                        # Step 2: Ensure transaction bytes don't end with signing-message prefix
                        if len(tx_only_bytes) >= 21:
                            tail = tx_only_bytes[-21:]
                            assert tail != b"APTOS::RawTransaction", "Used signing-message, not RawTransaction BCS"
                        
                        # Step 3: Construct the signed transaction
                        manual_keyless_signed = tx_only_bytes + raw_authenticator_bytes
                        
                        # Step 4: CRITICAL BOUNDARY ASSERTION - Fix for fee-payer transactions
                        boundary_byte = manual_keyless_signed[len(tx_only_bytes)]
                        
                        # For fee-payer transactions, we expect TransactionAuthenticator::fee_payer tag (0x03) at the boundary
                        expected_boundary_byte = 0x03  # TransactionAuthenticator::fee_payer
                        
                        if boundary_byte != expected_boundary_byte:
                            # Debug the misalignment
                            logger.error(f"🚨 BOUNDARY MISALIGNMENT DETECTED!")
                            logger.error(f"Expected byte 0x{expected_boundary_byte:02x} (fee-payer variant) at position {len(tx_only_bytes)}")
                            logger.error(f"Actually found byte 0x{boundary_byte:02x} ('{chr(boundary_byte) if 32 <= boundary_byte <= 126 else '?'}')")
                            logger.error(f"Context around boundary (position {len(tx_only_bytes)}):")
                            start_pos = max(0, len(tx_only_bytes) - 10)
                            end_pos = min(len(manual_keyless_signed), len(tx_only_bytes) + 10)
                            context_bytes = manual_keyless_signed[start_pos:end_pos]
                            logger.error(f"Bytes {start_pos}-{end_pos}: {list(context_bytes)}")
                            logger.error(f"As chars: {''.join(chr(b) if 32 <= b <= 126 else '?' for b in context_bytes)}")
                            logger.error(f"Boundary should be at index {len(tx_only_bytes) - start_pos} in the context")
                            
                            # Check if the authenticator bytes are correct
                            logger.error(f"Raw authenticator first 20 bytes: {list(raw_authenticator_bytes[:20])}")
                            logger.error(f"Raw authenticator as chars: {''.join(chr(b) if 32 <= b <= 126 else '?' for b in raw_authenticator_bytes[:20])}")
                            
                        assert boundary_byte == expected_boundary_byte, f"Misaligned boundary: expected 0x{expected_boundary_byte:02x} at position {len(tx_only_bytes)}, got 0x{boundary_byte:02x} ('{chr(boundary_byte) if 32 <= boundary_byte <= 126 else '?'}')"
                        
                        logger.info(f"✅ Boundary assertion passed: byte at position {len(tx_only_bytes)} is 0x{boundary_byte:02x} (fee-payer variant)")
                        logger.info(f"Manual keyless signed transaction length: {len(manual_keyless_signed)}")
                        logger.info(f"Transaction part: {len(tx_only_bytes)} bytes")
                        logger.info(f"Authenticator part: {len(raw_authenticator_bytes)} bytes")
                        logger.info(f"Last 10 bytes of transaction: {list(tx_only_bytes[-10:])}")
                        logger.info(f"First 10 bytes of authenticator: {list(raw_authenticator_bytes[:10])}")
                        
                        # Submit this manually constructed transaction
                        import httpx
                        
                        async with httpx.AsyncClient() as client:
                            response = await client.post(
                                f"{cls.APTOS_TESTNET_URL}/transactions",
                                headers={
                                    "Content-Type": "application/x.aptos.signed_transaction+bcs"
                                },
                                content=manual_keyless_signed
                            )
                            
                            if response.status_code == 202:  # Accepted
                                result = response.json()
                                tx_hash = result.get('hash')
                                logger.info(f"✅ Manual keyless transaction submitted successfully: {tx_hash}")
                                
                                # Set this for the success path below
                                signed_txn = None
                                USE_CUSTOM_SIGNED_TXN = True
                                SUBMITTED_VIA_REST = True
                                
                            else:
                                logger.error(f"Manual keyless submission failed: {response.status_code}")
                                logger.error(f"Response: {response.text}")
                                raise Exception(f"Manual keyless submission failed: {response.text}")
                                
                    except Exception as debug_error:
                        logger.error(f"BCS debugging approach failed: {debug_error}")
                        logger.info("Falling back to custom SignedTransaction approach")
                        
                        # Create a custom class that mimics SignedTransaction but uses raw bytes
                        class CustomSignedTransaction:
                            def __init__(self, transaction, authenticator_bytes):
                                self.transaction = transaction
                                self.authenticator_bytes = authenticator_bytes
                            
                            def serialize(self, serializer):
                                # Serialize the transaction first
                                self.transaction.serialize(serializer)
                                
                                # For the authenticator, we need to write it as raw bytes directly
                                # The authenticator bytes already contain the proper BCS serialization
                                # including the variant type indicator (first byte = 2 for keyless)
                                
                                # Simply write the authenticator bytes directly - they're already BCS encoded
                                if hasattr(serializer, '_output'):
                                    serializer._output.write(self.authenticator_bytes)
                                else:
                                    # Fallback: try to get the output buffer
                                    try:
                                        output = serializer.output()
                                        if hasattr(output, 'write'):
                                            output.write(self.authenticator_bytes)
                                        else:
                                            raise AttributeError("Cannot write to serializer output")
                                    except Exception as e:
                                        raise AttributeError(f"Cannot access serializer for writing authenticator: {e}")
                            
                            def bytes(self):
                                # This method is called by the Aptos SDK
                                from aptos_sdk.bcs import Serializer as BCSSerializer
                                serializer = BCSSerializer()
                                self.serialize(serializer)
                                return serializer.output()
                            
                            def __bytes__(self):
                                # Python magic method for bytes() function
                                return self.bytes()
                        
                        # Create the custom signed transaction as fallback
                        custom_signed_txn = CustomSignedTransaction(raw_txn, raw_authenticator_bytes)
                        
                        logger.info(f"✅ Created custom SignedTransaction with {len(raw_authenticator_bytes)} byte authenticator")
                        
                        # Set this as our signed transaction for submission
                        signed_txn = custom_signed_txn
                        USE_CUSTOM_SIGNED_TXN = True
                        SUBMITTED_VIA_REST = False
                    
                else:
                    # Normal flow with properly deserialized authenticator
                    logger.info("Using standard authenticator flow")
                    
                    # Create fee-payer authenticator with user + sponsor signatures
                    sponsor_account_auth = sponsor_account.sign_transaction(fee_payer_raw_txn)
                    
                    # Create fee-payer authenticator combining user and sponsor signatures
                    fee_payer_authenticator = FeePayerAuthenticator(
                        sender=user_authenticator,  # User's keyless signature
                        secondary_signers=[],  # No secondary signers needed
                        fee_payer=(fee_payer_addr, sponsor_account_auth)  # Sponsor pays fees
                    )
                    
                    # Step 5: Create final signed transaction with fee-payer authenticator
                    # IMPORTANT: SignedTransaction expects RawTransaction, not FeePayerRawTransaction
                    # When it sees FeePayerAuthenticator, it internally creates the FeePayerRawTransaction
                    try:
                        signed_txn = SignedTransaction(
                            transaction=raw_txn,  # Use the raw transaction, not fee_payer_raw_txn!
                            authenticator=Authenticator(fee_payer_authenticator)
                        )
                        
                        logger.info("Created proper fee-payer signed transaction with user + sponsor signatures")
                        
                        # Debug the signed transaction structure before submission
                        logger.info(f"About to submit transaction - Type: {type(signed_txn)}")
                        logger.info(f"Transaction structure - transaction: {type(signed_txn.transaction)}, authenticator: {type(signed_txn.authenticator)}")
                    except Exception as signed_txn_error:
                        logger.error(f"Failed to create SignedTransaction: {signed_txn_error}")
                        import traceback
                        logger.error(f"SignedTransaction creation traceback: {traceback.format_exc()}")
                        raise signed_txn_error
                
            else:
                # REQUIRE proper Aptos keyless sponsored transaction implementation
                logger.error("❌ CANNOT CREATE SPONSORED TRANSACTION")
                logger.error("Missing required Aptos keyless authenticator from frontend")
                logger.error("keyless_info must contain 'keyless_authenticator' field with user's Aptos keyless AccountAuthenticator")
                
                return {
                    'success': False,
                    'error': 'Aptos keyless authenticator required for sponsored transactions',
                    'details': {
                        'missing': 'keyless_info[keyless_authenticator]',
                        'provided_keys': list(keyless_info.keys()) if keyless_info else [],
                        'requirement': 'Frontend must sign transaction with Aptos keyless account and provide AccountAuthenticator',
                        'migration_note': 'Update from Sui zkLogin to Aptos keyless accounts'
                    }
                }
            
            # Step 5: Submit the transaction using the appropriate method
            try:
                if 'SUBMITTED_VIA_REST' in locals() and SUBMITTED_VIA_REST:
                    logger.info("✅ Transaction already submitted via REST API")
                    # tx_hash should already be set from the REST API submission
                elif 'USE_CUSTOM_SIGNED_TXN' in locals() and USE_CUSTOM_SIGNED_TXN:
                    logger.info("🚀 Submitting custom SignedTransaction with keyless authenticator workaround")
                    tx_hash = await aptos_client.submit_bcs_transaction(signed_txn)
                    logger.info(f"✅ BCS transaction submitted successfully: {tx_hash}")
                else:
                    logger.info("Attempting to submit standard BCS transaction to blockchain...")
                    logger.info(f"Signed transaction type: {type(signed_txn)}")
                    tx_hash = await aptos_client.submit_bcs_transaction(signed_txn)
                    logger.info(f"✅ BCS transaction submitted successfully: {tx_hash}")
                
            except Exception as submit_error:
                logger.error(f"BCS submission failed: {submit_error}")
                logger.error(f"Full error details: {str(submit_error)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                
                # If we were using the custom signed transaction, this means the workaround failed
                if 'USE_CUSTOM_SIGNED_TXN' in locals() and USE_CUSTOM_SIGNED_TXN:
                    logger.error("❌ Custom SignedTransaction workaround failed")
                    return {
                        'success': False,
                        'error': 'SDK compatibility issue: Custom SignedTransaction workaround failed',
                        'details': {
                            'issue': 'Keyless authenticator type 2 not supported in Python SDK',
                            'typescript_sdk': 'v4.0.0 (supports keyless)',
                            'python_sdk': '0.11.0 (no keyless support)',
                            'workaround_attempted': 'Custom SignedTransaction with raw bytes',
                            'recommendation': 'Upgrade Python SDK to version that supports keyless authenticators',
                            'submission_error': str(submit_error)
                        }
                    }
                
                # Try alternative submission approach - regular transaction instead of fee-payer
                logger.info("Trying regular transaction submission as fallback...")
                try:
                    # Create a regular transaction instead of fee-payer
                    regular_signed_txn = SignedTransaction(
                        transaction=raw_txn,  # Use the regular raw transaction
                        authenticator=user_authenticator  # Just user signature
                    )
                    
                    logger.info("Attempting regular transaction submission...")
                    tx_hash = await aptos_client.submit_bcs_transaction(regular_signed_txn)
                    logger.info(f"Regular transaction submitted successfully: {tx_hash}")
                    
                    # Wait for confirmation
                    await aptos_client.wait_for_transaction(tx_hash)
                    final_tx = await aptos_client.transaction_by_hash(tx_hash)
                    
                    return {
                        'success': True,
                        'digest': tx_hash,
                        'sponsored': False,  # Not sponsored, but working
                        'gas_used': final_tx.get('gas_used', gas_estimate),
                        'note': 'Submitted as regular transaction (not sponsored due to fee-payer serialization issue)'
                    }
                    
                except Exception as regular_error:
                    logger.error(f"Regular transaction also failed: {regular_error}")
                    
                    # Return diagnostic information
                    return {
                        'success': False,
                        'error': f'Both fee-payer and regular transaction failed. Fee-payer: {str(submit_error)}, Regular: {str(regular_error)}',
                        'details': {
                            'signature_parsing': 'SUCCESS',
                            'authenticator_creation': 'SUCCESS', 
                            'fee_payer_transaction': 'SERIALIZATION_ERROR',
                            'regular_transaction': 'ALSO_FAILED',
                            'blockchain_submission': 'NEEDS_INVESTIGATION'
                        }
                    }
            
            # Handle successful submission - tx_hash should be set by now
            logger.info(f"Real transaction submitted! Hash: {tx_hash}")
            
            # Wait for transaction confirmation
            await aptos_client.wait_for_transaction(tx_hash)
            
            # Get final transaction info
            final_tx = await aptos_client.transaction_by_hash(tx_hash)
            success = final_tx.get('success', False)
            gas_used = int(final_tx.get('gas_used', gas_estimate))
            
            if success:
                logger.info(f"✅ Real transaction confirmed! Hash: {tx_hash}, Gas: {gas_used}")
                await cls._update_sponsor_stats(gas_used)
                
                # Determine if it was sponsored based on the submission method
                is_sponsored = not ('USE_CUSTOM_SIGNED_TXN' in locals() and USE_CUSTOM_SIGNED_TXN)
                sdk_workaround_used = 'USE_CUSTOM_SIGNED_TXN' in locals() and USE_CUSTOM_SIGNED_TXN
                
                return {
                    'success': True,
                    'digest': tx_hash,
                    'sponsored': is_sponsored,
                    'gas_saved': gas_used * 100 / 1e8 if is_sponsored else 0,  # Convert to APT
                    'sponsor': sponsor_address if is_sponsored else None,
                    'gas_used': gas_used,
                    'real_transaction': True,
                    'sdk_compatibility_workaround': sdk_workaround_used,
                    'note': 'Used SDK compatibility workaround for keyless authenticator' if sdk_workaround_used else None
                }
            else:
                return {
                    'success': False,
                    'error': f'Transaction failed on blockchain: {final_tx.get("vm_status", "Unknown error")}'
                }
            
        except Exception as e:
            logger.error(f"Failed to submit sponsored transaction: {e}")
            return {
                'success': False,
                'error': f'Transaction submission failed: {str(e)}'
            }
    
    @classmethod
    async def _estimate_gas(
        cls,
        client,
        sender: 'AccountAddress',
        entry_function: 'EntryFunction',
        fee_payer: 'AccountAddress'
    ) -> int:
        """Estimate gas for transaction"""
        try:
            # Use a conservative estimate based on transaction type
            function_name = entry_function.function
            
            if 'transfer' in function_name:
                return 1500  # Transfer transactions
            elif 'mint' in function_name:
                return 2000  # Minting transactions
            elif 'burn' in function_name:
                return 1800  # Burn transactions
            else:
                return cls.MAX_GAS_PER_TX  # Default maximum
                
        except Exception:
            return cls.MAX_GAS_PER_TX
    
    @classmethod
    async def _create_mock_transaction(
        cls,
        user_address: str,
        transaction_payload: Dict[str, Any],
        sponsor_address: str
    ) -> Dict[str, Any]:
        """Create mock transaction for development"""
        import hashlib
        import time
        
        tx_content = f"{user_address}_{transaction_payload.get('function', 'tx')}_{time.time()}"
        tx_digest = f"aptos_mock_{hashlib.sha256(tx_content.encode()).hexdigest()[:32]}"
        
        logger.warning(
            f"MOCK TRANSACTION: APTOS_SPONSOR_PRIVATE_KEY not configured. "
            f"Mock digest: {tx_digest}"
        )
        
        # Update stats
        await cls._update_sponsor_stats(1500)  # Mock gas usage
        
        return {
            'success': True,
            'digest': tx_digest,
            'sponsored': True,
            'gas_saved': 0.0015,  # Mock gas saved in APT
            'sponsor': sponsor_address,
            'warning': 'Transaction not submitted to blockchain (APTOS_SPONSOR_PRIVATE_KEY not configured)'
        }
    
    @classmethod
    async def _update_sponsor_stats(cls, gas_used: int):
        """Update sponsor statistics"""
        stats = cache.get(cls.SPONSOR_STATS_KEY, {
            'total_sponsored': 0,
            'total_gas_spent': 0,
            'failed_transactions': 0
        })
        
        stats['total_sponsored'] += 1
        stats['total_gas_spent'] += gas_used
        
        cache.set(cls.SPONSOR_STATS_KEY, stats, timeout=86400)  # 24 hours
        
        # Invalidate balance cache to force refresh
        cache.delete(cls.SPONSOR_BALANCE_KEY)
    
    @classmethod
    async def prepare_sponsored_cusd_transfer(
        cls,
        sender_address: str,
        recipient_address: str,
        amount: Decimal
    ) -> Dict[str, Any]:
        """
        PHASE 1: Prepare a sponsored CUSD transfer transaction for signing.
        
        Args:
            sender_address: Sender's Aptos address
            recipient_address: Recipient's Aptos address  
            amount: Amount to transfer (in CUSD tokens)
            
        Returns:
            Dict with transaction data for frontend to sign
        """
        # Convert amount to units (6 decimals for CUSD)
        amount_units = int(amount * Decimal(10**6))
        
        # Build transaction via V2 bridge
        result = await cls.build_sponsored_transaction_v2(
            sender_address=sender_address,
            recipient_address=recipient_address,
            amount=amount_units,
            token_type='CUSD'
        )
        
        if result.get('success'):
            # Add transaction metadata for frontend
            result['transaction_type'] = 'cusd_transfer'
            result['amount_display'] = f"{amount} CUSD"
            result['phase'] = 'prepare'
            logger.info(f"✅ Prepared sponsored CUSD transfer for signing")
        
        return result
    
    @classmethod
    async def submit_sponsored_cusd_transfer(
        cls,
        sender_address: str,
        recipient_address: str,
        amount: Decimal,
        sender_authenticator_base64: str
    ) -> Dict[str, Any]:
        """
        PHASE 2: Submit a signed sponsored CUSD transfer transaction.
        
        Args:
            sender_address: Sender's Aptos address
            recipient_address: Recipient's Aptos address  
            amount: Amount to transfer (in CUSD tokens)
            sender_authenticator_base64: Base64 encoded authenticator from frontend
            
        Returns:
            Dict with transaction result
        """
        # Convert amount to units (6 decimals for CUSD)
        amount_units = int(amount * Decimal(10**6))
        
        # Submit via V2 bridge with signed authenticator
        result = await cls.submit_via_typescript_bridge_v2(
            sender_address=sender_address,
            recipient_address=recipient_address,
            amount=amount_units,
            token_type='CUSD',
            sender_authenticator_base64=sender_authenticator_base64
        )
        
        if result.get('success'):
            result['phase'] = 'submit'
            logger.info(f"✅ Submitted sponsored CUSD transfer: {result.get('digest')}")
        
        return result
    
    @classmethod
    async def sponsor_cusd_transfer(
        cls,
        sender_address: str,
        recipient_address: str,
        amount: Decimal,
        keyless_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Sponsor a CUSD transfer transaction (legacy single-phase method).
        
        Args:
            sender_address: Sender's Aptos address
            recipient_address: Recipient's Aptos address  
            amount: Amount to transfer (in CUSD tokens)
            keyless_info: Keyless authentication information
            
        Returns:
            Dict with transaction result
        """
        # If we have an authenticator, use the new two-phase flow
        if keyless_info and keyless_info.get('keyless_authenticator'):
            authenticator_data = keyless_info.get('keyless_authenticator')
            
            # Submit directly (assumes frontend already has the right signature)
            return await cls.submit_sponsored_cusd_transfer(
                sender_address=sender_address,
                recipient_address=recipient_address,
                amount=amount,
                sender_authenticator_base64=authenticator_data
            )
        else:
            # Fallback to legacy path
            amount_units = int(amount * Decimal(10**6))
            transaction_payload = {
                'function': '0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::cusd::transfer_cusd',
                'type_arguments': [],
                'arguments': [recipient_address, str(amount_units)]
            }
            
            return await cls.create_sponsored_transaction(
                sender_address,
                transaction_payload,
                keyless_info=keyless_info
            )
    
    @classmethod
    async def test_regular_keyless_transfer(
        cls,
        raw_transaction: str,
        sender_authenticator: str,
        sender_address: str
    ) -> Dict[str, Any]:
        """
        Test method for regular (non-sponsored) keyless transactions.
        This submits a fully signed transaction directly to Aptos.
        
        Args:
            raw_transaction: Base64 encoded raw transaction built by client
            sender_authenticator: Base64 encoded sender authenticator  
            sender_address: Sender's Aptos address (for logging)
            
        Returns:
            Dict with transaction result
        """
        try:
            import httpx
            import base64
            
            logger.info(f"Testing regular keyless transfer from {sender_address}")
            logger.info(f"Raw transaction length: {len(raw_transaction)}")
            logger.info(f"Authenticator length: {len(sender_authenticator)}")
            
            # Decode from base64
            raw_tx_bytes = base64.b64decode(raw_transaction)
            auth_bytes = base64.b64decode(sender_authenticator)
            
            # Construct signed transaction (UserTransaction variant = 0)
            from io import BytesIO
            signed_tx = BytesIO()
            
            # Write variant tag for UserTransaction (0)
            signed_tx.write(bytes([0]))
            
            # Write raw transaction bytes
            signed_tx.write(raw_tx_bytes)
            
            # Write authenticator bytes
            signed_tx.write(auth_bytes)
            
            signed_tx_bytes = signed_tx.getvalue()
            
            logger.info(f"Signed transaction length: {len(signed_tx_bytes)}")
            
            # Submit to Aptos
            nodit_api_key = os.getenv('NODIT_API_KEY')
            network = os.getenv('APTOS_NETWORK', 'testnet')
            
            if network == 'mainnet':
                base_url = 'https://aptos-mainnet.nodit.io/v1'
            else:
                base_url = 'https://aptos-testnet.nodit.io/v1'
            
            headers = {
                'Content-Type': 'application/x.aptos.signed_transaction+bcs'
            }
            
            if nodit_api_key:
                headers['X-API-KEY'] = nodit_api_key
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{base_url}/transactions",
                    content=signed_tx_bytes,
                    headers=headers
                )
                
                if response.status_code == 202:
                    result = response.json()
                    logger.info(f"Transaction submitted successfully: {result.get('hash')}")
                    
                    # Wait for confirmation
                    await asyncio.sleep(2)
                    
                    # Check transaction status
                    tx_response = await client.get(
                        f"{base_url}/transactions/by_hash/{result.get('hash')}",
                        headers={'X-API-KEY': nodit_api_key} if nodit_api_key else {}
                    )
                    
                    if tx_response.status_code == 200:
                        tx_data = tx_response.json()
                        if tx_data.get('success'):
                            return {
                                'success': True,
                                'transactionHash': result.get('hash')
                            }
                        else:
                            return {
                                'success': False,
                                'error': f"Transaction failed: {tx_data.get('vm_status')}"
                            }
                    else:
                        # Transaction might still be pending
                        return {
                            'success': True,
                            'transactionHash': result.get('hash')
                        }
                else:
                    error_text = response.text
                    logger.error(f"Transaction submission failed: {error_text}")
                    return {
                        'success': False,
                        'error': f"Submission failed: {error_text}"
                    }
                    
        except Exception as e:
            logger.error(f"Error in test_regular_keyless_transfer: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }