from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def payment_provider_configuration_checks(app_configs, **kwargs):
    issues = []
    callback = getattr(settings, 'PAYMENT_ACCOUNTS_CALLBACK_BASE_URL', '')
    cobre_values = [
        getattr(settings, 'COBRE_USER_ID', ''),
        getattr(settings, 'COBRE_SECRET', ''),
        getattr(settings, 'COBRE_WEBHOOK_SECRET', ''),
    ]
    infinia_values = [
        getattr(settings, 'INFINIA_SECRET_ID', ''),
        getattr(settings, 'INFINIA_SECRET_PASSWORD', ''),
    ]
    cobre_enabled = getattr(settings, 'COBRE_PAYMENT_ACCOUNTS_ENABLED', False)
    infinia_enabled = getattr(settings, 'INFINIA_PAYMENT_ACCOUNTS_ENABLED', False)
    if cobre_enabled and not all(cobre_values):
        issues.append(Error(
            'Cobre payment accounts are enabled without complete credentials.',
            id='payment_accounts.E006',
        ))
    if infinia_enabled and not all(infinia_values):
        issues.append(Error(
            'Infinia payment accounts are enabled without complete credentials.',
            id='payment_accounts.E007',
        ))
    if cobre_enabled and not callback:
        issues.append(Error(
            'Enabled payment-account providers require a callback base URL.',
            id='payment_accounts.E008',
        ))
    if any(cobre_values) and not all(cobre_values):
        issues.append(Error(
            'Cobre credentials and webhook secret must be configured together.',
            id='payment_accounts.E001',
        ))
    if any(infinia_values) and not all(infinia_values):
        issues.append(Error(
            'Both Infinia Basic Auth values must be configured together.',
            id='payment_accounts.E002',
        ))
    if infinia_enabled and not callback:
        issues.append(Error(
            'Infinia requires PAYMENT_ACCOUNTS_CALLBACK_BASE_URL for account and movement webhooks.',
            id='payment_accounts.E003',
        ))
    if callback and not callback.startswith('https://'):
        issues.append(Error(
            'Payment account callback base URL must use HTTPS.',
            id='payment_accounts.E004',
        ))
    kyc_mode = getattr(settings, 'INFINIA_KYC_MODE', '')
    if kyc_mode and kyc_mode not in {'HOSTED', 'EXTERNAL', 'SELF_DECLARED'}:
        issues.append(Error(
            'INFINIA_KYC_MODE is not a documented mode.',
            id='payment_accounts.E005',
        ))
    if infinia_enabled and kyc_mode != 'SELF_DECLARED':
        issues.append(Error(
            'Enabled Infinia payment accounts require Didit-backed SELF_DECLARED KYC mode.',
            id='payment_accounts.E009',
        ))
    if infinia_enabled and not getattr(settings, 'DIDIT_API_KEY', ''):
        issues.append(Error(
            'Enabled Infinia payment accounts require DIDIT_API_KEY.',
            id='payment_accounts.E010',
        ))
    if infinia_enabled and not getattr(settings, 'DIDIT_MEDIA_ALLOWED_HOSTS', []):
        issues.append(Error(
            'Enabled Infinia payment accounts require DIDIT_MEDIA_ALLOWED_HOSTS.',
            id='payment_accounts.E011',
        ))
    if all(cobre_values) and not callback:
        issues.append(Warning(
            'Configure PAYMENT_ACCOUNTS_CALLBACK_BASE_URL and register its Cobre webhook URL in the Cobre portal.',
            id='payment_accounts.W001',
        ))
    return issues
