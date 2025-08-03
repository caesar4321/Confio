"""
Simple transaction execution using Sui CLI
This is a temporary solution until we integrate the proper SDK

For testing purposes, this also includes mock transaction support
that operates on database balances when blockchain tokens are not available.
"""
import subprocess
import json
import asyncio
import logging
from typing import Dict, Any, Optional
from decimal import Decimal

logger = logging.getLogger(__name__)


class SimpleTransaction:
    """Execute transactions using Sui CLI commands"""
    
    @staticmethod
    async def send_coins(
        sender_address: str,
        recipient_address: str, 
        amount: Decimal,
        coin_type: str,
        coin_object_id: str,
        sponsor_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send coins using Sui CLI
        
        Note: This requires the sender's key to be in the local Sui wallet
        """
        try:
            # Build the Sui CLI command
            cmd = [
                "sui", "client", "transfer",
                "--to", recipient_address,
                "--object-id", coin_object_id,
                "--gas-budget", "10000000"
            ]
            
            # Execute the command
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                # Parse the output to find the transaction digest
                output = result.stdout
                
                # Look for "Transaction Digest: <digest>"
                import re
                digest_match = re.search(r'Transaction Digest: (\w+)', output)
                
                if digest_match:
                    digest = digest_match.group(1)
                    logger.info(f"Transaction successful! Digest: {digest}")
                    
                    return {
                        'success': True,
                        'digest': digest,
                        'output': output
                    }
                else:
                    logger.warning("Transaction executed but couldn't parse digest")
                    return {
                        'success': True,
                        'digest': 'unknown',
                        'output': output
                    }
            else:
                logger.error(f"Sui CLI error: {result.stderr}")
                return {
                    'success': False,
                    'error': result.stderr
                }
                
        except Exception as e:
            logger.error(f"Error in simple transaction: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod  
    async def execute_with_sponsor(
        user_address: str,
        transaction_data: Dict[str, Any],
        sponsor_address: str,
        sponsor_key: str,
        prepared_coins: Optional[Dict[str, Any]] = None,
        zklogin_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a sponsored transaction
        
        This is a simplified version that transfers from sponsor directly
        Real sponsorship requires transaction wrapper support
        
        Args:
            user_address: User's Sui address
            transaction_data: Transaction data to execute
            sponsor_address: Sponsor's Sui address
            sponsor_key: Sponsor's private key
            prepared_coins: Pre-selected coins (optional)
            zklogin_info: zkLogin information if available (optional)
        """
        # Log zkLogin info if available
        if zklogin_info:
            logger.info(
                f"Transaction has zkLogin support. "
                f"Proof ID: {zklogin_info.get('proof_id')}"
            )
        
        # Extract transaction details
        function = transaction_data.get('function', '')
        
        if function == 'split_and_transfer':
            # This is a simple transfer
            coin_object_id = transaction_data['arguments'][0]  # First argument is coin object
            recipient = transaction_data['arguments'][2]  # Third argument is recipient
            amount_str = transaction_data['arguments'][1]  # Second argument is amount
            coin_type = transaction_data['typeArguments'][0]
            
            # Parse coin type to get token symbol
            if 'cusd' in coin_type.lower():
                token = 'CUSD'
                decimals = 6
            elif 'confio' in coin_type.lower():
                token = 'CONFIO' 
                decimals = 9
            else:
                token = 'UNKNOWN'
                decimals = 9
            
            # Convert amount from smallest units
            amount_units = int(amount_str)
            amount = Decimal(amount_units) / Decimal(10 ** decimals)
            
            logger.info(
                f"Executing sponsored transfer: {amount} {token} "
                f"from {user_address} to {recipient} "
                f"using coin object: {coin_object_id}"
            )
            
            # For actual blockchain transaction, we need to:
            # 1. Get coins from the sponsor account
            # 2. Transfer the exact amount
            
            # For now, let's use sponsor's coins to send
            # In production, this would use transaction sponsorship
            from blockchain.coin_management import CoinManager
            from blockchain.blockchain_settings import CUSD_PACKAGE_ID, CONFIO_PACKAGE_ID
            
            try:
                # Get sponsor's coins
                if token == 'CUSD':
                    full_coin_type = f"{CUSD_PACKAGE_ID}::cusd::CUSD"
                elif token == 'CONFIO':
                    full_coin_type = f"{CONFIO_PACKAGE_ID}::confio::CONFIO"
                else:
                    return {
                        'success': False,
                        'error': f'Unknown token type: {token}'
                    }
                
                # Get sponsor's coins for this token
                sponsor_coins = await CoinManager.get_coin_objects(
                    sponsor_address,
                    full_coin_type
                )
                
                if not sponsor_coins:
                    return {
                        'success': False,
                        'error': f'No blockchain {token} coins found for sponsor. Cannot execute transaction.'
                    }
                
                # Use the first available coin
                sponsor_coin = sponsor_coins[0]
                logger.info(f"Using sponsor coin: {sponsor_coin['objectId']} with balance: {sponsor_coin['balance']}")
                
                # Execute transfer using sponsor's coin
                return await SimpleTransaction.send_coins(
                    sponsor_address,
                    recipient,
                    amount,
                    token,
                    sponsor_coin['objectId'],
                    None  # No additional sponsor needed
                )
                
            except Exception as e:
                logger.error(f"Error getting sponsor coins: {e}")
                return {
                    'success': False,
                    'error': f'Failed to get sponsor coins: {str(e)}'
                }
        
        return {
            'success': False,
            'error': f'Unsupported transaction type: {function}'
        }
    
