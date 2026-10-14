"""
One-off: copy Secrets Manager secrets into SSM Parameter Store SecureStrings
(see config/secrets.py). Values are never printed.

    AWS_PROFILE=Julian myvenv/bin/python scripts/ops/migrate_secrets_to_ssm.py

App secrets go to /confio/secrets/<name>; the ops test-wallet key goes to
/confio/ops/<name> so app processes never load it. Re-running is safe
(Overwrite=True). Deleting the old secrets is a separate step, done once
production has run on Parameter Store for a few days.
"""
import boto3

REGION = 'eu-central-2'
STANDARD_TIER_MAX_BYTES = 4096

# Stay in Secrets Manager: the RDS-managed master secret and the ConfioAI
# CloudFormation stack's own secret. (RDS_SECRET stayed until RDS Proxy was
# deleted on 2026-10-14, then moved to /confio/secrets/RDS_SECRET as well.)
KEEP = {'confioai/runtime'}
KEEP_PREFIXES = ('rds!',)
# Retired: superseded by prod/ondo-gm-{read,write}-key on 2026-07-31, or unused.
RETIRED = {
    'prod/ondo-api-key',
    'prod/ondo-gm-api-key',
    'prod/coinbase-cdp-api',
    'prod/coinbase-cdp-sandbox',
    'test/coinbase-cdp-sandbox',
}
OPS_KEYS = {'ops/cow-solver-test-wallet'}


def target(name):
    return f'/confio/{name}' if name in OPS_KEYS else f'/confio/secrets/{name}'


def main():
    session = boto3.session.Session(region_name=REGION)
    sm, ssm = session.client('secretsmanager'), session.client('ssm')
    names = sorted(
        s['Name'] for page in sm.get_paginator('list_secrets').paginate() for s in page['SecretList']
    )
    for name in names:
        if name in KEEP or name.startswith(KEEP_PREFIXES):
            print(f'{name:45} kept in Secrets Manager')
            continue
        if name in RETIRED:
            print(f'{name:45} retired, not copied')
            continue
        value = sm.get_secret_value(SecretId=name)['SecretString']
        size = len(value.encode())
        tier = 'Standard' if size <= STANDARD_TIER_MAX_BYTES else 'Advanced'
        ssm.put_parameter(
            Name=target(name),
            Value=value,
            Type='SecureString',
            Tier=tier,
            Overwrite=True,
            Description=f'Copied from Secrets Manager {name}',
        )
        stored = ssm.get_parameter(Name=target(name), WithDecryption=True)['Parameter']['Value']
        print(f'{name:45} {size:5} bytes  {tier:8}  {"OK" if stored == value else "MISMATCH"}')


if __name__ == '__main__':
    main()
