import uuid
from datetime import timedelta
from typing import Dict, Optional

import boto3
from botocore.client import Config
from django.conf import settings

def _get_bucket() -> str:
    """Resolve the verification bucket (required)."""
    return getattr(settings, 'AWS_VERIFICATION_BUCKET', None)


def _ensure_bucket():
    if not _get_bucket():
        raise ValueError("AWS_VERIFICATION_BUCKET is not configured")


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
        'Bucket': _get_bucket(),
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
        'bucket': _get_bucket(),
        'key': key,
        'url': url,
        'method': 'PUT',
        'headers': headers,
        'expires_in': expires_in_seconds,
    }


def public_s3_url(key: str) -> str:
    """Return a direct HTTPS URL for the object (assuming public or signed retrieval elsewhere)."""
    region = settings.AWS_S3_REGION or 'us-east-1'
    bucket = _get_bucket()
    if region == 'us-east-1':
        return f"https://{bucket}.s3.amazonaws.com/{key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

def generate_presigned_get(*, key: str, expires_in_seconds: int = 300) -> str:
    """Generate a short-lived presigned GET URL to view/download an object.

    Used in admin to securely preview private verification files without
    making the bucket public.
    """
    _ensure_bucket()

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

    return s3.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': _get_bucket(), 'Key': key},
        ExpiresIn=expires_in_seconds,
        HttpMethod='GET'
    )

def key_from_url(url: str) -> Optional[str]:
    """Extract the S3 key from a public-style URL. Returns None if unknown format.

    Supports:
      - https://<bucket>.s3.amazonaws.com/<key>
      - https://<bucket>.s3.<region>.amazonaws.com/<key>
    """
    try:
        if not url:
            return None
        # Strip querystring
        base = url.split('?', 1)[0]
        # Find the third slash: protocol(https://) + domain + /<key>
        # Split on '/', keep parts after domain
        parts = base.split('/')
        # e.g., ['https:', '', 'bucket.s3.amazonaws.com', '<key...>']
        if len(parts) >= 4 and parts[2].endswith('amazonaws.com'):
            key = '/'.join(parts[3:])
            return key or None
        return None
    except Exception:
        return None


def generate_presigned_post(
    *,
    key: str,
    content_type: str,
    expires_in_seconds: int = 900,
    metadata: Optional[Dict[str, str]] = None,
    conditions: Optional[list] = None,
) -> Dict[str, str]:
    """Generate a presigned POST for multipart form uploads (mobile-friendly).

    Returns dict with url, fields, key, bucket, method='POST', expires_in.
    """
    _ensure_bucket()

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

    fields = {'Content-Type': content_type}
    if metadata:
        for k, v in metadata.items():
            fields[f'x-amz-meta-{k}'] = str(v)

    conds = conditions[:] if conditions else []
    # Ensure content type and metadata must match
    conds.append({'Content-Type': content_type})
    if metadata:
        for k, v in metadata.items():
            conds.append({f'x-amz-meta-{k}': str(v)})

    post = s3.generate_presigned_post(
        Bucket=_get_bucket(),
        Key=key,
        Fields=fields,
        Conditions=conds,
        ExpiresIn=expires_in_seconds,
    )

    return {
        'bucket': _get_bucket(),
        'key': key,
        'url': post['url'],
        'method': 'POST',
        'fields': post['fields'],
        'expires_in': expires_in_seconds,
    }
