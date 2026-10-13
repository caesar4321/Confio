"""
AWS SSM Parameter Store and Secrets Manager utilities.

This module provides functions to fetch secrets from AWS at runtime.
Secrets are cached in memory to avoid repeated API calls.

App secrets live in SSM Parameter Store as SecureStrings under
`/confio/secrets/<name>` (standard tier: free storage and reads, vs $0.40 per
secret per month in Secrets Manager). `get_secret('prod/x')` reads
`/confio/secrets/prod/x` and falls back to the Secrets Manager secret `prod/x`
when no such parameter exists — which is still the case for `RDS_SECRET`
(RDS Proxy only authenticates through Secrets Manager).

Size limit: standard-tier parameters hold at most 4,096 bytes. The largest
today is prod/didit-workflow-ids-by-phone-country at 3,651 bytes (2026-10-13);
if a value outgrows 4 KB, `put-parameter` fails and that parameter needs
`--tier Advanced` ($0.05/month, 8 KB limit). The bulk load reads both tiers.
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
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not available - secrets will fall back to environment variables")


# Kept apart from /confio/global and /confio/algorand key material, so loading
# app secrets never pulls private keys into every process.
PARAMETER_PREFIX = '/confio/secrets/'
# Expected to be read from Secrets Manager; anything else falling back is a gap.
SECRETS_MANAGER_ONLY = frozenset({'RDS_SECRET'})

_parameter_secrets_cache: Dict[str, Dict[str, str]] = {}


def _parameter_secrets(region_name: str) -> Dict[str, str]:
    """
    Every `/confio/secrets/*` parameter, decrypted, in one paginated
    GetParametersByPath call per process. Each process reads ~27 secrets at
    import time and a deploy restarts ~8 services at once; per-name
    GetParameter calls would hit the 40 TPS standard throughput limit.

    Only a successful load is cached, so a transient failure at boot is
    retried on the next lookup instead of pinning the process to the fallback.
    """
    if region_name in _parameter_secrets_cache:
        return _parameter_secrets_cache[region_name]
    # Adaptive retries absorb throttling while several services boot at once;
    # without them one throttled page sent every later lookup back to retry
    # the whole load, compounding the throttling.
    client = boto3.session.Session().client(
        service_name='ssm',
        region_name=region_name,
        config=Config(retries={'mode': 'adaptive', 'max_attempts': 10}),
    )
    values = {}
    for page in client.get_paginator('get_parameters_by_path').paginate(
        Path=PARAMETER_PREFIX, Recursive=True, WithDecryption=True,
    ):
        for parameter in page['Parameters']:
            values[parameter['Name'][len(PARAMETER_PREFIX):]] = parameter['Value']
    _parameter_secrets_cache[region_name] = values
    return values


@lru_cache(maxsize=128)
def get_secret(secret_name: str, region_name: str = "eu-central-2") -> Union[str, Dict[str, Any]]:
    """
    Fetch a secret: SSM Parameter Store `/confio/secrets/<name>` first, then
    the Secrets Manager secret `<name>`.

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

    try:
        parameters = _parameter_secrets(region_name)
    except (ClientError, BotoCoreError) as e:
        logger.warning(f"Parameter Store load failed, reading {secret_name} from Secrets Manager: {e}")
        parameters = {}
    if secret_name not in parameters and parameters and secret_name not in SECRETS_MANAGER_ONLY:
        # Created after this process loaded its snapshot (e.g. a new alert
        # bot secret): one direct read keeps "create it, no restart needed".
        try:
            response = boto3.session.Session().client(service_name='ssm', region_name=region_name).get_parameter(
                Name=f'{PARAMETER_PREFIX}{secret_name}', WithDecryption=True,
            )
            parameters[secret_name] = response['Parameter']['Value']
        except ClientError as e:
            if e.response['Error']['Code'] != 'ParameterNotFound':
                logger.warning(f"Parameter Store read failed for {secret_name}: {e}")
        except BotoCoreError as e:  # network/credential errors: still try Secrets Manager
            logger.warning(f"Parameter Store read failed for {secret_name}: {e}")
    if secret_name in parameters:
        value = parameters[secret_name]
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if secret_name not in SECRETS_MANAGER_ONLY:
        logger.warning(f"{PARAMETER_PREFIX}{secret_name} not in Parameter Store, reading Secrets Manager")

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
