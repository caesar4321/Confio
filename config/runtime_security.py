"""Validated runtime security settings; secret values never enter logs."""
import re
from django.core.exceptions import ImproperlyConfigured


def load_runtime_security(*, secret_name, debug, fetch, read_env):
    if secret_name:
        try:
            values = fetch(secret_name)
        except Exception:
            raise ImproperlyConfigured("Runtime security secret is unavailable") from None
        if not isinstance(values, dict):
            raise ImproperlyConfigured("Runtime security secret must be a JSON object")
        values = dict(values)
    elif debug:
        values = {key: read_env(key, '') for key in (
            'FUNNEL_INGEST_SECRET', 'REVIEW_TEST_CODE', 'REVIEW_TEST_CODE_2', 'ADMIN_PATH')}
        values['ADMIN_PATH'] = values.get('ADMIN_PATH') or 'local-control-panel'
    else:
        raise ImproperlyConfigured("CONFIO_RUNTIME_SECURITY_SECRET is required outside DEBUG mode")
    for key in ('FUNNEL_INGEST_SECRET', 'FUNNEL_INGEST_PREVIOUS_SECRET',
                'REVIEW_TEST_CODE', 'REVIEW_TEST_CODE_2', 'ADMIN_PATH'):
        value = values.get(key, '')
        if not isinstance(value, str):
            raise ImproperlyConfigured("Runtime security fields must be strings")
        values[key] = value.strip()
    path = values['ADMIN_PATH'].strip('/')
    if not re.fullmatch(r'[A-Za-z0-9_-]{12,80}', path):
        raise ImproperlyConfigured("ADMIN_PATH must contain 12-80 URL-safe characters")
    if not debug and path in ('confio-control-panel', 'local-control-panel'):
        raise ImproperlyConfigured("Production requires a randomized ADMIN_PATH")
    values['ADMIN_PATH'] = path
    if not debug and not values['FUNNEL_INGEST_SECRET']:
        raise ImproperlyConfigured("Funnel ingestion secret is required outside DEBUG mode")
    return values
