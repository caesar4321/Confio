import base64
import logging
import boto3
from django.conf import settings
from cryptography.fernet import Fernet # type: ignore
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class GlobalKeyManager:
    """
    Manages the Global Wallet Master Key used for application-level encryption.
    Fetches the key from AWS SSM Parameter Store (encrypted by KMS).
    """
    _instance = None
    _fernet = None
    
    SSM_PARAMETER_NAME = '/confio/global/wallet-master-key'
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = GlobalKeyManager()
        return cls._instance
    
    def __init__(self):
        if GlobalKeyManager._instance is not None:
            raise Exception("This class is a singleton!")
        self._load_master_key()
    
    def _load_master_key(self):
        """
        Load the master key from SSM Parameter Store.
        The key in SSM is a 32-byte url-safe base64 encoded string (Fernet compliant).
        """
        try:
            # Check if explicitly overridden in settings (e.g. for testing)
            if hasattr(settings, 'CONFIO_GLOBAL_WALLET_MASTER_KEY'):
                key = settings.CONFIO_GLOBAL_WALLET_MASTER_KEY
                logger.info("Loaded Global Master Key from settings")
            else:
                region_name = getattr(settings, 'AWS_REGION', 'eu-central-2')
                ssm = boto3.client('ssm', region_name=region_name)
                
                logger.info(f"Fetching Global Master Key from SSM: {self.SSM_PARAMETER_NAME}")
                response = ssm.get_parameter(
                    Name=self.SSM_PARAMETER_NAME,
                    WithDecryption=True
                )
                key = response['Parameter']['Value']
                logger.info("Successfully loaded Global Master Key from SSM")

            # Initialize Fernet with the loaded key
            # Ensure key is bytes
            if isinstance(key, str):
                key = key.encode('utf-8')
                
            self._fernet = Fernet(key)
            
        except ClientError as e:
            logger.critical(f"Failed to load Global Master Key from SSM: {e}")
            raise RuntimeError(f"Could not load encryption master key: {e}")
        except Exception as e:
            logger.critical(f"Error initializing GlobalKeyManager: {e}")
            raise

    @property
    def fernet(self):
        if self._fernet is None:
            self._load_master_key()
        return self._fernet

def encrypt_data(plaintext: str) -> str:
    """
    Encrypt a plaintext string using the Global Master Key.
    Returns base64 encoded ciphertext string.
    """
    if not plaintext:
        return ""
    
    try:
        f = GlobalKeyManager.get_instance().fernet
        # Fernet encrypt expects bytes, returns bytes
        ciphertext_bytes = f.encrypt(plaintext.encode('utf-8'))
        return ciphertext_bytes.decode('utf-8')
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise

def decrypt_data(ciphertext: str) -> str:
    """
    Decrypt a ciphertext string using the Global Master Key.
    Returns original plaintext string.
    """
    if not ciphertext:
        return ""
        
    try:
        f = GlobalKeyManager.get_instance().fernet
        # Fernet decrypt expects bytes, returns bytes
        plaintext_bytes = f.decrypt(ciphertext.encode('utf-8'))
        return plaintext_bytes.decode('utf-8')
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        raise
