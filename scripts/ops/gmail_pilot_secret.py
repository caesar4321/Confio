"""Store the Gmail pilot's Google OAuth client in SSM without showing it to anyone.

Run on the owner's Mac, in a terminal (it asks; nothing is echoed or printed):
    AWS_PROFILE=Julian myvenv/bin/python scripts/ops/gmail_pilot_secret.py

Writes /confio/secrets/prod/gmail-pilot (SecureString, eu-central-2). On a
re-run the token key is kept: replacing it would orphan every stored token.
"""
import getpass
import json

import boto3
from botocore.exceptions import ClientError
from cryptography.fernet import Fernet

NAME = '/confio/secrets/prod/gmail-pilot'
REGION = 'eu-central-2'


def main():
    ssm = boto3.client('ssm', region_name=REGION)
    try:
        current = json.loads(ssm.get_parameter(Name=NAME, WithDecryption=True)['Parameter']['Value'])
    except ClientError as exc:
        if exc.response['Error']['Code'] != 'ParameterNotFound':
            raise
        current = {}
    client_id = input('Google OAuth client ID: ').strip()
    if not client_id.endswith('.apps.googleusercontent.com'):
        raise SystemExit('That is not a client ID. Nothing was written.')
    client_secret = getpass.getpass('Google OAuth client secret (hidden): ').strip()
    if not client_secret:
        raise SystemExit('Empty secret. Nothing was written.')
    value = {'client_id': client_id, 'client_secret': client_secret,
             'token_key': current.get('token_key') or Fernet.generate_key().decode()}
    ssm.put_parameter(Name=NAME, Value=json.dumps(value), Type='SecureString', Overwrite=True)
    print(f'Saved {NAME} in {REGION}.')


if __name__ == '__main__':
    main()
