"""
AWS Secrets Manager and SSM Parameter Store utilities.

This module provides functions to fetch secrets from AWS at runtime.
Secrets are cached in memory to avoid repeated API calls.
"""
import os
import json
import logging
from functools import lru_cache
from typing import Union, Dict, Any

logger = logging.getLogger(__name__)

# Only import boto3 if we're in production (EC2/ECS)
# This allows local development without boto3
try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not available - secrets will fall back to environment variables")


@lru_cache(maxsize=128)
def get_secret(secret_name: str, region_name: str = "eu-central-2") -> Union[str, Dict[str, Any]]:
    """
    Fetch secret from AWS Secrets Manager.

    Args:
        secret_name: Name or ARN of the secret
        region_name: AWS region (default: eu-central-2)

    Returns:
        Secret value as a string or dictionary (if JSON)
        Falls back to environment variable if boto3 unavailable

    Raises:
        Exception: If secret not found or access denied
    """
    # Fallback to environment variables if boto3 not available (local dev)
    if not BOTO3_AVAILABLE:
        env_var_name = secret_name.replace('/', '_').replace('-', '_').upper()
        value = os.getenv(env_var_name)
        if value:
            logger.info(f"Using environment variable {env_var_name} for secret {secret_name}")
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        else:
            raise Exception(f"boto3 not available and environment variable {env_var_name} not set")

    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceNotFoundException':
            raise Exception(f"Secret {secret_name} not found in region {region_name}")
        elif error_code == 'InvalidRequestException':
            raise Exception(f"Invalid request for secret {secret_name}")
        elif error_code == 'InvalidParameterException':
            raise Exception(f"Invalid parameter for secret {secret_name}")
        elif error_code == 'AccessDeniedException':
            raise Exception(f"Access denied to secret {secret_name}. Check IAM permissions.")
        else:
            logger.error(f"Error fetching secret {secret_name}: {e}")
            raise

    # Secret can be string or binary
    if 'SecretString' in get_secret_value_response:
        secret = get_secret_value_response['SecretString']
        try:
            return json.loads(secret)
        except json.JSONDecodeError:
            return secret
    else:
        # Binary secret (rare)
        return get_secret_value_response['SecretBinary']


@lru_cache(maxsize=128)
def get_parameter(parameter_name: str, region_name: str = "eu-central-2") -> str:
    """
    Fetch parameter from SSM Parameter Store.

    Args:
        parameter_name: Name of the parameter (e.g., /confio/algorand/...)
        region_name: AWS region (default: eu-central-2)

    Returns:
        Parameter value as a string (decrypted if SecureString)
        Falls back to environment variable if boto3 unavailable

    Raises:
        Exception: If parameter not found or access denied
    """
    # Fallback to environment variables if boto3 not available (local dev)
    if not BOTO3_AVAILABLE:
        env_var_name = parameter_name.strip('/').replace('/', '_').upper()
        value = os.getenv(env_var_name)
        if value:
            logger.info(f"Using environment variable {env_var_name} for parameter {parameter_name}")
            return value
        else:
            raise Exception(f"boto3 not available and environment variable {env_var_name} not set")

    session = boto3.session.Session()
    client = session.client(
        service_name='ssm',
        region_name=region_name
    )

    try:
        response = client.get_parameter(
            Name=parameter_name,
            WithDecryption=True
        )
        return response['Parameter']['Value']
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ParameterNotFound':
            raise Exception(f"Parameter {parameter_name} not found in region {region_name}")
        elif error_code == 'AccessDeniedException':
            raise Exception(f"Access denied to parameter {parameter_name}. Check IAM permissions.")
        else:
            logger.error(f"Error fetching parameter {parameter_name}: {e}")
            raise


def is_running_on_aws() -> bool:
    """
    Check if the application is running on AWS (EC2/ECS/Lambda).

    Returns:
        True if running on AWS, False otherwise
    """
    # Check for EC2 instance metadata
    if os.path.exists('/sys/hypervisor/uuid'):
        try:
            with open('/sys/hypervisor/uuid', 'r') as f:
                uuid = f.read().strip()
                if uuid.startswith('ec2'):
                    return True
        except:
            pass

    # Check for ECS metadata
    if os.getenv('ECS_CONTAINER_METADATA_URI') or os.getenv('ECS_CONTAINER_METADATA_URI_V4'):
        return True

    # Check for Lambda
    if os.getenv('AWS_LAMBDA_FUNCTION_NAME'):
        return True

    # Check for IAM role (EC2/ECS instance profile)
    if os.getenv('AWS_CONTAINER_CREDENTIALS_RELATIVE_URI'):
        return True

    return False
