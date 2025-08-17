"""
Execute conversions with signed transactions from client
"""
import logging
import json
import base64
from typing import Dict, List
from django.db import transaction as db_transaction
from conversion.models import Conversion
from blockchain.algorand_client import AlgorandClient
from blockchain.algorand_sponsor_service import AlgorandSponsorService
from algosdk import encoding
from algosdk.transaction import wait_for_confirmation

logger = logging.getLogger(__name__)


class ConversionExecutor:
    """Execute conversions with client-signed transactions"""
    
    def __init__(self):
        self.algorand_client = AlgorandClient()
        self.sponsor_service = AlgorandSponsorService()
        
    async def execute_signed_conversion(
        self,
        conversion_id: str,
        signed_transactions_json: str
    ) -> Dict:
        """
        Execute a conversion with pre-signed transactions from client
        
        Args:
            conversion_id: ID of the conversion
            signed_transactions_json: JSON string containing:
                - userSignedTxns: List of base64 encoded signed transactions
                - groupId: Base64 encoded group ID
                - sponsorTxIndex: Index of sponsor transaction in group
                
        Returns:
            Dict with execution result
        """
        try:
            # Parse the signed transactions data
            tx_data = json.loads(signed_transactions_json)
            user_signed_txns = tx_data.get('userSignedTxns', [])
            group_id_b64 = tx_data.get('groupId')
            sponsor_tx_index = tx_data.get('sponsorTxIndex', 0)
            
            if not user_signed_txns:
                return {
                    'success': False,
                    'error': 'No signed transactions provided'
                }
            
            # Get the conversion
            conversion = Conversion.objects.get(
                id=conversion_id,
                status__in=['PENDING', 'PENDING_SIG']
            )
            
            # Get sponsor transaction and sign it
            sponsor_signed_txn = await self.sponsor_service.sign_sponsor_transaction(
                conversion.conversion_type,
                conversion.from_amount
            )
            
            if not sponsor_signed_txn:
                return {
                    'success': False,
                    'error': 'Failed to sign sponsor transaction'
                }
            
            # Decode user signed transactions
            decoded_txns = []
            for txn_b64 in user_signed_txns:
                decoded_txns.append(base64.b64decode(txn_b64))
            
            # Combine all transactions in correct order
            # Sponsor transaction goes first (index 0)
            all_txns = [sponsor_signed_txn] + decoded_txns
            
            # Send the transaction group
            tx_id = self.algorand_client.algod.send_transactions(all_txns)
            
            # Wait for confirmation
            confirmed_txn = wait_for_confirmation(self.algorand_client.algod, tx_id, 10)
            
            # Update conversion status
            with db_transaction.atomic():
                conversion.from_transaction_hash = tx_id
                conversion.to_transaction_hash = tx_id
                conversion.status = 'COMPLETED'
                conversion.save()
            
            # Get the block number
            block = confirmed_txn.get('confirmed-round', 0)
            
            logger.info(f"Conversion {conversion_id} executed successfully: tx {tx_id}, block {block}")
            
            return {
                'success': True,
                'transaction_id': tx_id,
                'block': block,
                'conversion_id': str(conversion.id)
            }
            
        except Conversion.DoesNotExist:
            return {
                'success': False,
                'error': 'Conversion not found or not pending'
            }
        except Exception as e:
            logger.error(f"Error executing signed conversion: {e}")
            return {
                'success': False,
                'error': str(e)
            }


# Helper function for GraphQL mutations
def execute_signed_conversion_sync(conversion_id: str, signed_transactions: str) -> Dict:
    """
    Synchronous version for executing conversions with signed transactions
    Used by GraphQL mutations to avoid async context issues
    """
    try:
        import json
        from algosdk import account, encoding as algo_encoding
        from algosdk.transaction import Transaction
        from django.conf import settings
        
        # Parse the signed transactions data
        tx_data = json.loads(signed_transactions)
        user_signed_txns = tx_data.get('userSignedTxns', [])
        group_id_b64 = tx_data.get('groupId')
        sponsor_tx_index = tx_data.get('sponsorTxIndex', 0)
        
        if not user_signed_txns:
            return {
                'success': False,
                'error': 'No signed transactions provided'
            }
        
        # Get the conversion
        conversion = Conversion.objects.get(
            id=conversion_id,
            status__in=['PENDING', 'PENDING_SIG']
        )
        
        # Initialize Algorand client
        algod_client = AlgorandClient()
        
        # DO NOT REBUILD TRANSACTIONS!
        # The client already signed the correct transactions with the correct group ID
        # Just submit what the client signed
        
        logger.info(f"Executing conversion {conversion_id} with {len(user_signed_txns)} signed transactions")
        
        # Decode and log details
        import msgpack
        decoded_pairs = []  # [(dict, raw_bytes)]
        for txn_b64 in user_signed_txns:
            raw = base64.b64decode(txn_b64)
            try:
                d = msgpack.unpackb(raw, raw=False)
            except Exception:
                d = None
            decoded_pairs.append((d, raw))

        user_bytes_list = []
        types = []
        from algosdk.encoding import encode_address
        dbg = []
        idx = 0
        for d, raw in decoded_pairs:
            user_bytes_list.append(raw)
            if isinstance(d, dict):
                td = d.get('txn', {})
                t = td.get('type')
                types.append(t)
                if t == 'pay':
                    snd = encode_address(td.get('snd')) if td.get('snd') else 'na'
                    rcv = encode_address(td.get('rcv')) if td.get('rcv') else 'na'
                    amt = td.get('amt')
                    fee = td.get('fee')
                    dbg.append(f"pay[i={idx}] snd={snd} rcv={rcv} amt={amt} fee={fee}")
                elif t == 'axfer':
                    snd = encode_address(td.get('snd')) if td.get('snd') else 'na'
                    arcv = encode_address(td.get('arcv')) if td.get('arcv') else 'na'
                    xaid = td.get('xaid')
                    aamt = td.get('aamt')
                    fee = td.get('fee')
                    dbg.append(f"axfer[i={idx}] snd={snd} arcv={arcv} xaid={xaid} aamt={aamt} fee={fee}")
                elif t == 'appl':
                    snd = encode_address(td.get('snd')) if td.get('snd') else 'na'
                    apid = td.get('apid')
                    fee = td.get('fee')
                    dbg.append(f"appl[i={idx}] snd={snd} apid={apid} fee={fee}")
            idx += 1
        if types:
            logger.info(f"Submitting atomic group of {len(user_bytes_list)} transactions in order: {types}")
        if dbg:
            logger.info("[ConversionExecutor] Txn details: " + " | ".join(dbg))

        # Concatenate the raw transaction bytes
        combined_txns = b''.join(user_bytes_list)
        
        # Encode to base64 for submission
        combined_b64 = base64.b64encode(combined_txns).decode('utf-8')
        
        # Submit the atomic group
        logger.info(f"Submitting atomic group of {len(user_bytes_list)} transactions")
        tx_id = algod_client.algod.send_raw_transaction(combined_b64)
        
        # Wait for confirmation (synchronously)
        confirmed_txn = wait_for_confirmation(algod_client.algod, tx_id, 10)
        
        # Update conversion status
        with db_transaction.atomic():
            conversion.from_transaction_hash = tx_id
            conversion.to_transaction_hash = tx_id
            conversion.status = 'COMPLETED'
            conversion.save()
        
        # Get the block number
        block = confirmed_txn.get('confirmed-round', 0)
        
        logger.info(f"Conversion {conversion_id} executed successfully: tx {tx_id}, block {block}")
        
        return {
            'success': True,
            'transaction_id': tx_id,
            'block': block,
            'conversion_id': str(conversion.id)
        }
        
    except Conversion.DoesNotExist:
        return {
            'success': False,
            'error': 'Conversion not found or not pending'
        }
    except Exception as e:
        logger.error(f"Error executing signed conversion (sync): {e}")
        # Attempt a dryrun to capture failing pc/stack for debugging
        try:
            import json as _json
            from algosdk.v2client import algod as _algod
            algod_client = AlgorandClient()
            # Reuse the same signed transactions from above scope
            tx_data = _json.loads(signed_transactions)
            user_signed_txns = tx_data.get('userSignedTxns', [])
            # Dryrun with the exact signed blobs
            payload = {
                'txns': user_signed_txns
            }
            resp = algod_client.algod.algod_request("POST", "/v2/teal/dryrun", data=_json.dumps(payload))
            # Log summarized dryrun results
            dr = resp
            results = dr.get('results', [])
            for i, r in enumerate(results):
                err = r.get('error')
                msg = r.get('app-call-messages') or []
                trace = r.get('trace') or []
                logger.error(f"[Dryrun] tx[{i}] error={err} msgs={msg}")
                # Log last few trace steps if present
                for step in trace[-5:]:
                    pc = step.get('pc')
                    op = step.get('op')
                    stk = step.get('stack', [])
                    logger.error(f"[Dryrun] pc={pc} op={op} stack={stk}")
        except Exception as _de:
            logger.error(f"Dryrun attempt failed: {_de}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            'success': False,
            'error': str(e)
        }
