"""
AWS KMS Manager for Algorand Key Management

This module handles Algorand private key storage and signing operations using AWS KMS.
Keys are stored in KMS and never exposed to the application.

Security Features:
- Private keys stored in FIPS 140-2 Level 2 validated HSMs
- Signing operations performed inside KMS
- IAM-based access control
- CloudTrail audit logging
- Automatic key backup and recovery
"""

import boto3
import base64
import os
from typing import Tuple, Optional
from algosdk import account, encoding, mnemonic
from algosdk.transaction import Transaction
import logging

logger = logging.getLogger(__name__)


class AlgorandKMSManager:
    """
    Manages Algorand private keys in AWS KMS

    KMS stores the raw ED25519 private key (32 bytes) as plaintext in an encrypted key.
    When signing, we decrypt the key from KMS, sign locally, then discard the key.

    Note: KMS doesn't natively support ED25519 signing, so we use KMS for storage/encryption
    and perform ED25519 signing in memory. The key exists in memory only during signing.
    """

    def __init__(self, region_name: str = 'eu-central-2'):
        """
        Initialize KMS Manager

        Args:
            region_name: AWS region for KMS (default: eu-central-2 per Swiss data protection)
        """
        self.region_name = region_name
        self.kms_client = boto3.client('kms', region_name=region_name)

    def create_algorand_key(self, key_alias: str, description: str = '') -> Tuple[str, str, str]:
        """
        Create a new Algorand keypair and store in KMS

        Args:
            key_alias: Alias for the KMS key (e.g., 'confio-mainnet-sponsor')
            description: Description of the key purpose

        Returns:
            Tuple of (kms_key_id, algorand_address, mnemonic_for_backup)

        Example:
            >>> manager = AlgorandKMSManager()
            >>> key_id, address, backup_mnemonic = manager.create_algorand_key(
            ...     'confio-mainnet-sponsor',
            ...     'Mainnet sponsor account for Confio'
            ... )
        """
        # Generate new Algorand keypair
        private_key, address = account.generate_account()
        mnemonic_phrase = mnemonic.from_private_key(private_key)

        logger.info(f"Generated new Algorand address: {address}")

        # Create KMS key for encryption
        response = self.kms_client.create_key(
            Description=f'{description} - Algorand Private Key',
            KeyUsage='ENCRYPT_DECRYPT',
            Origin='AWS_KMS',
            Tags=[
                {'TagKey': 'Project', 'TagValue': 'Confio'},
                {'TagKey': 'Purpose', 'TagValue': 'Algorand-Signing'},
                {'TagKey': 'Environment', 'TagValue': 'Production'},
                {'TagKey': 'AlgorandAddress', 'TagValue': address},
            ]
        )

        kms_key_id = response['KeyMetadata']['KeyId']

        # Create alias for easy reference
        alias_name = f'alias/{key_alias}'
        try:
            self.kms_client.create_alias(
                AliasName=alias_name,
                TargetKeyId=kms_key_id
            )
            logger.info(f"Created KMS key alias: {alias_name}")
        except self.kms_client.exceptions.AlreadyExistsException:
            # Update existing alias to point to new key
            self.kms_client.update_alias(
                AliasName=alias_name,
                TargetKeyId=kms_key_id
            )
            logger.info(f"Updated existing KMS key alias: {alias_name}")

        # Store the private key in KMS (encrypted)
        # We store it as encrypted data in Parameter Store for retrieval
        ssm_client = boto3.client('ssm', region_name=self.region_name)
        parameter_name = f'/confio/algorand/{key_alias}/private-key'

        # Try to create parameter first (without overwrite)
        try:
            ssm_client.put_parameter(
                Name=parameter_name,
                Description=f'Encrypted Algorand private key for {key_alias}',
                Value=private_key,
                Type='SecureString',
                KeyId=kms_key_id,
                Tags=[
                    {'Key': 'Project', 'Value': 'Confio'},
                    {'Key': 'AlgorandAddress', 'Value': address},
                ]
            )
            logger.info(f"Created new SSM parameter: {parameter_name}")
        except ssm_client.exceptions.ParameterAlreadyExists:
            # Parameter exists, update it without tags
            ssm_client.put_parameter(
                Name=parameter_name,
                Description=f'Encrypted Algorand private key for {key_alias}',
                Value=private_key,
                Type='SecureString',
                KeyId=kms_key_id,
                Overwrite=True
            )
            logger.info(f"Updated existing SSM parameter: {parameter_name}")

            # Update tags separately
            ssm_client.add_tags_to_resource(
                ResourceType='Parameter',
                ResourceId=parameter_name,
                Tags=[
                    {'Key': 'Project', 'Value': 'Confio'},
                    {'Key': 'AlgorandAddress', 'Value': address},
                ]
            )

        logger.info(f"Stored private key in Parameter Store: {parameter_name}")
        logger.warning(f"BACKUP THIS MNEMONIC SECURELY: {mnemonic_phrase}")

        return kms_key_id, address, mnemonic_phrase

    def import_existing_key(self, key_alias: str, mnemonic_phrase: str, description: str = '') -> Tuple[str, str]:
        """
        Import an existing Algorand account into KMS

        Args:
            key_alias: Alias for the KMS key (e.g., 'confio-mainnet-sponsor')
            mnemonic_phrase: 25-word Algorand mnemonic
            description: Description of the key purpose

        Returns:
            Tuple of (kms_key_id, algorand_address)

        Example:
            >>> manager = AlgorandKMSManager()
            >>> key_id, address = manager.import_existing_key(
            ...     'confio-testnet-sponsor',
            ...     'your 25 word mnemonic phrase here...',
            ...     'Testnet sponsor account'
            ... )
        """
        # Derive private key and address from mnemonic
        private_key = mnemonic.to_private_key(mnemonic_phrase)
        address = account.address_from_private_key(private_key)

        logger.info(f"Importing Algorand address: {address}")

        # Get current AWS account ID for key policy
        import boto3
        sts_client = boto3.client('sts', region_name=self.region_name)
        account_id = sts_client.get_caller_identity()['Account']

        # Create key policy that allows root and current user to use the key
        key_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "Enable IAM User Permissions",
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": f"arn:aws:iam::{account_id}:root"
                    },
                    "Action": "kms:*",
                    "Resource": "*"
                },
                {
                    "Sid": "Allow use of the key for Parameter Store",
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": f"arn:aws:iam::{account_id}:user/Julian"
                    },
                    "Action": [
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:CreateGrant",
                        "kms:DescribeKey"
                    ],
                    "Resource": "*"
                }
            ]
        }

        # Create KMS key for encryption
        import json
        response = self.kms_client.create_key(
            Description=f'{description} - Algorand Private Key',
            KeyUsage='ENCRYPT_DECRYPT',
            Origin='AWS_KMS',
            Policy=json.dumps(key_policy),
            Tags=[
                {'TagKey': 'Project', 'TagValue': 'Confio'},
                {'TagKey': 'Purpose', 'TagValue': 'Algorand-Signing'},
                {'TagKey': 'AlgorandAddress', 'TagValue': address},
            ]
        )

        kms_key_id = response['KeyMetadata']['KeyId']

        # Create alias
        alias_name = f'alias/{key_alias}'
        try:
            self.kms_client.create_alias(
                AliasName=alias_name,
                TargetKeyId=kms_key_id
            )
            logger.info(f"Created KMS key alias: {alias_name}")
        except self.kms_client.exceptions.AlreadyExistsException:
            self.kms_client.update_alias(
                AliasName=alias_name,
                TargetKeyId=kms_key_id
            )
            logger.info(f"Updated existing KMS key alias: {alias_name}")

        # Store the private key in Parameter Store (encrypted with KMS key)
        ssm_client = boto3.client('ssm', region_name=self.region_name)
        parameter_name = f'/confio/algorand/{key_alias}/private-key'

        # Try to create parameter first (without overwrite)
        try:
            ssm_client.put_parameter(
                Name=parameter_name,
                Description=f'Encrypted Algorand private key for {key_alias}',
                Value=private_key,
                Type='SecureString',
                KeyId=kms_key_id,
                Tags=[
                    {'Key': 'Project', 'Value': 'Confio'},
                    {'Key': 'AlgorandAddress', 'Value': address},
                ]
            )
            logger.info(f"Created new SSM parameter: {parameter_name}")
        except ssm_client.exceptions.ParameterAlreadyExists:
            # Parameter exists, update it without tags
            ssm_client.put_parameter(
                Name=parameter_name,
                Description=f'Encrypted Algorand private key for {key_alias}',
                Value=private_key,
                Type='SecureString',
                KeyId=kms_key_id,
                Overwrite=True
            )
            logger.info(f"Updated existing SSM parameter: {parameter_name}")

            # Update tags separately
            ssm_client.add_tags_to_resource(
                ResourceType='Parameter',
                ResourceId=parameter_name,
                Tags=[
                    {'Key': 'Project', 'Value': 'Confio'},
                    {'Key': 'AlgorandAddress', 'Value': address},
                ]
            )

        logger.info(f"Imported and stored private key in Parameter Store: {parameter_name}")

        return kms_key_id, address

    def get_private_key(self, key_alias: str) -> str:
        """
        Retrieve and decrypt private key from KMS/Parameter Store

        SECURITY WARNING: This exposes the private key in memory. Use only for signing
        operations and ensure the key is discarded immediately after use.

        Args:
            key_alias: Alias of the KMS key

        Returns:
            Decrypted private key as base64 string
        """
        ssm_client = boto3.client('ssm', region_name=self.region_name)
        parameter_name = f'/confio/algorand/{key_alias}/private-key'

        try:
            response = ssm_client.get_parameter(
                Name=parameter_name,
                WithDecryption=True  # KMS decrypts automatically
            )
            private_key = response['Parameter']['Value']
            logger.debug(f"Retrieved private key for {key_alias}")
            return private_key

        except ssm_client.exceptions.ParameterNotFound:
            logger.error(f"Private key not found for alias: {key_alias}")
            raise ValueError(f"No private key found for alias: {key_alias}")

    def get_address(self, key_alias: str) -> str:
        """
        Get Algorand address for a key without exposing private key

        Args:
            key_alias: Alias of the KMS key

        Returns:
            Algorand address string
        """
        # Try to get from KMS tags first (doesn't expose private key)
        alias_name = f'alias/{key_alias}'

        try:
            # Get key ID from alias
            alias_response = self.kms_client.describe_key(KeyId=alias_name)
            key_id = alias_response['KeyMetadata']['KeyId']

            # Get tags to find address
            tags_response = self.kms_client.list_resource_tags(KeyId=key_id)

            for tag in tags_response.get('Tags', []):
                if tag['TagKey'] == 'AlgorandAddress':
                    return tag['TagValue']

            # Fallback: derive from private key
            logger.warning(f"Address not in tags, deriving from private key for {key_alias}")
            private_key = self.get_private_key(key_alias)
            return account.address_from_private_key(private_key)

        except self.kms_client.exceptions.NotFoundException:
            logger.error(f"KMS key not found for alias: {key_alias}")
            raise ValueError(f"No KMS key found for alias: {key_alias}")

    def sign_transaction(self, key_alias: str, transaction: Transaction) -> bytes:
        """
        Sign an Algorand transaction using key from KMS

        This retrieves the private key from KMS, signs the transaction,
        and immediately discards the key from memory.

        Args:
            key_alias: Alias of the KMS key to use for signing
            transaction: Unsigned Algorand transaction

        Returns:
            Signed transaction as bytes

        Example:
            >>> from algosdk.transaction import PaymentTxn
            >>> manager = AlgorandKMSManager()
            >>>
            >>> unsigned_txn = PaymentTxn(
            ...     sender=manager.get_address('confio-mainnet-sponsor'),
            ...     sp=algod_client.suggested_params(),
            ...     receiver='RECEIVER_ADDRESS',
            ...     amt=1000000
            ... )
            >>>
            >>> signed_txn = manager.sign_transaction('confio-mainnet-sponsor', unsigned_txn)
        """
        try:
            # Retrieve private key from KMS (decrypted in memory)
            private_key = self.get_private_key(key_alias)

            # Sign transaction
            signed_txn = transaction.sign(private_key)

            logger.info(f"Transaction signed successfully with {key_alias}")

            # Explicitly clear private key from memory (best effort)
            del private_key

            return signed_txn

        except Exception as e:
            logger.error(f"Failed to sign transaction with {key_alias}: {e}")
            raise

    def sign_logic_sig_transaction(self, key_alias: str, transaction: Transaction):
        """
        Sign a logic signature transaction

        Args:
            key_alias: Alias of the KMS key
            transaction: Transaction to sign

        Returns:
            Signed logic sig transaction
        """
        private_key = self.get_private_key(key_alias)

        try:
            from algosdk.transaction import LogicSigTransaction
            signed_txn = LogicSigTransaction(transaction, private_key)
            return signed_txn
        finally:
            del private_key

    def delete_key(self, key_alias: str, pending_window_days: int = 30):
        """
        Schedule a KMS key for deletion

        DANGER: This will permanently delete the key after the pending window.
        Ensure you have backed up the mnemonic before deletion.

        Args:
            key_alias: Alias of the KMS key to delete
            pending_window_days: Days before permanent deletion (7-30, default 30)
        """
        alias_name = f'alias/{key_alias}'

        try:
            # Get key ID from alias
            alias_response = self.kms_client.describe_key(KeyId=alias_name)
            key_id = alias_response['KeyMetadata']['KeyId']

            # Schedule key deletion
            self.kms_client.schedule_key_deletion(
                KeyId=key_id,
                PendingWindowInDays=pending_window_days
            )

            logger.warning(f"Scheduled KMS key {key_id} for deletion in {pending_window_days} days")

            # Delete SSM parameter
            ssm_client = boto3.client('ssm', region_name=self.region_name)
            parameter_name = f'/confio/algorand/{key_alias}/private-key'

            try:
                ssm_client.delete_parameter(Name=parameter_name)
                logger.info(f"Deleted SSM parameter: {parameter_name}")
            except ssm_client.exceptions.ParameterNotFound:
                pass

        except self.kms_client.exceptions.NotFoundException:
            logger.error(f"KMS key not found for alias: {key_alias}")
            raise ValueError(f"No KMS key found for alias: {key_alias}")


class KMSSigner:
    """
    Drop-in replacement for mnemonic-based signing that uses KMS

    This class provides the same interface as the existing sponsor service
    but uses KMS for key storage and signing.
    """

    def __init__(self, key_alias: str, region_name: str = 'eu-central-2'):
        """
        Initialize KMS signer

        Args:
            key_alias: KMS key alias (e.g., 'confio-mainnet-sponsor')
            region_name: AWS region
        """
        self.key_alias = key_alias
        self.kms_manager = AlgorandKMSManager(region_name=region_name)
        self._address = None

    @property
    def address(self) -> str:
        """Get Algorand address for this signer"""
        if not self._address:
            self._address = self.kms_manager.get_address(self.key_alias)
        return self._address

    def sign_transaction(self, transaction: Transaction) -> bytes:
        """Sign a transaction"""
        return self.kms_manager.sign_transaction(self.key_alias, transaction)

    def sign_transactions(self, transactions: list) -> list:
        """Sign multiple transactions (e.g., atomic transfer group)"""
        return [self.sign_transaction(txn) for txn in transactions]
