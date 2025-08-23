import uuid
from datetime import timedelta
from typing import Dict, Optional

import boto3
from botocore.client import Config
from django.conf import settings


def _ensure_bucket():
    if not settings.AWS_S3_BUCKET:
        raise ValueError("AWS_S3_BUCKET is not configured")


def build_s3_key(prefix: str, filename_hint: str) -> str:
    """Build a namespaced S3 key using a prefix and random UUID.

    filename_hint is used only to attach a sensible extension.
    """
    ext = ''
    if '.' in filename_hint:
        ext = filename_hint.split('.')[-1].lower()
        if ext:
            ext = f'.{ext}'
    return f"{prefix.rstrip('/')}/{uuid.uuid4().hex}{ext}"


def generate_presigned_put(
    *,
    key: str,
    content_type: str,
    expires_in_seconds: int = 900,
    metadata: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Generate a presigned URL for S3 PUT uploads.

    Returns a dict with url, method, headers, key and bucket.
    """
    _ensure_bucket()

    # Build client with optional explicit credentials
    # Ensure we sign against the correct regional endpoint to avoid
    # IllegalLocationConstraintException when the bucket is in a non-default region
    region = settings.AWS_S3_REGION or 'us-east-1'
    endpoint = f"https://s3.{region}.amazonaws.com" if region != 'us-east-1' else "https://s3.amazonaws.com"

    params = {
        'region_name': region,
        'config': Config(signature_version='s3v4'),
        'endpoint_url': endpoint,
    }
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        params.update({
            'aws_access_key_id': settings.AWS_ACCESS_KEY_ID,
            'aws_secret_access_key': settings.AWS_SECRET_ACCESS_KEY,
        })
    s3 = boto3.client('s3', **params)

    extra_params = {
        'Bucket': settings.AWS_S3_BUCKET,
        'Key': key,
        'ContentType': content_type,
    }
    if metadata:
        # Only include simple string metadata
        extra_params['Metadata'] = {str(k): str(v) for k, v in metadata.items()}

    url = s3.generate_presigned_url(
        ClientMethod='put_object',
        Params=extra_params,
        ExpiresIn=expires_in_seconds,
        HttpMethod='PUT'
    )

    # Required headers for the upload to be valid
    headers = {
        'Content-Type': content_type,
    }
    if metadata:
        for k, v in metadata.items():
            headers[f'x-amz-meta-{k}'] = str(v)

    return {
        'bucket': settings.AWS_S3_BUCKET,
        'key': key,
        'url': url,
        'method': 'PUT',
        'headers': headers,
        'expires_in': expires_in_seconds,
    }


def public_s3_url(key: str) -> str:
    """Return a direct HTTPS URL for the object (assuming public or signed retrieval elsewhere)."""
    region = settings.AWS_S3_REGION or 'us-east-1'
    bucket = settings.AWS_S3_BUCKET
    if region == 'us-east-1':
        return f"https://{bucket}.s3.amazonaws.com/{key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
