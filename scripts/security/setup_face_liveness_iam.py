"""Provision the IAM pieces behind the face step-up (security/face_step_up.py).

Creates or updates, idempotently:

1. The client role (FACE_LIVENESS_CLIENT_ROLE_ARN). The backend assumes it per
   face check and hands the app credentials that can do exactly one thing:
   rekognition:StartFaceLivenessSession. Only the backend role may assume it,
   and only with the `face-liveness-<user_id>` session name the code uses.
2. An inline policy on the backend role: create/read liveness sessions and
   CompareFaces in the Face Liveness region (eu-west-1, Ireland), assume
   the client role, and read/write the stored KYC selfies
   under face-references/ in the eu-central-2 verification bucket.

Dry run by default; pass --apply to change anything.

    AWS_PROFILE=Julian python scripts/security/setup_face_liveness_iam.py \\
        --backend-role <ec2-instance-role-name> --bucket <AWS_VERIFICATION_BUCKET> --apply

Then set FACE_REKOGNITION_REGION=eu-west-1,
FACE_LIVENESS_CLIENT_ROLE_ARN (printed at the end), and
FACE_STEP_UP_AVAILABLE=True in the backend environment. FACE_STEP_UP_ENABLED
turns on enforcement once the app build with the liveness screen is out.
"""
import argparse
import json

import boto3
from botocore.exceptions import ClientError

CLIENT_ROLE_NAME = 'confio-face-liveness-client'
CLIENT_POLICY_NAME = 'start-face-liveness-session'
BACKEND_POLICY_NAME = 'confio-face-step-up'
REKOGNITION_REGION = 'eu-west-1'
REFERENCE_PREFIX = 'face-references'  # security/face_step_up.py REFERENCE_PREFIX


def client_trust_policy(backend_role_arn: str) -> dict:
    return {
        'Version': '2012-10-17',
        'Statement': [{
            'Effect': 'Allow',
            'Principal': {'AWS': backend_role_arn},
            'Action': 'sts:AssumeRole',
            'Condition': {'StringLike': {'sts:RoleSessionName': 'face-liveness-*'}},
        }],
    }


def client_permissions_policy() -> dict:
    # StartFaceLivenessSession has no resource-level scoping; '*' is the
    # narrowest AWS allows. The region condition keeps it to Ireland.
    return {
        'Version': '2012-10-17',
        'Statement': [{
            'Effect': 'Allow',
            'Action': 'rekognition:StartFaceLivenessSession',
            'Resource': '*',
            'Condition': {'StringEquals': {'aws:RequestedRegion': REKOGNITION_REGION}},
        }],
    }


def backend_policy(client_role_arn: str, bucket: str) -> dict:
    return {
        'Version': '2012-10-17',
        'Statement': [
            {
                'Sid': 'FaceLivenessAndMatch',
                'Effect': 'Allow',
                'Action': [
                    'rekognition:CreateFaceLivenessSession',
                    'rekognition:GetFaceLivenessSessionResults',
                    'rekognition:CompareFaces',
                ],
                'Resource': '*',
                'Condition': {'StringEquals': {'aws:RequestedRegion': REKOGNITION_REGION}},
            },
            {
                'Sid': 'IssueClientCredentials',
                'Effect': 'Allow',
                'Action': 'sts:AssumeRole',
                'Resource': client_role_arn,
            },
            {
                'Sid': 'FaceReferences',
                'Effect': 'Allow',
                'Action': ['s3:PutObject', 's3:GetObject', 's3:DeleteObject'],
                'Resource': f'arn:aws:s3:::{bucket}/{REFERENCE_PREFIX}/*',
            },
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--backend-role', required=True, help='IAM role name the Django backend runs as')
    parser.add_argument('--bucket', required=True, help='AWS_VERIFICATION_BUCKET (eu-central-2)')
    parser.add_argument('--apply', action='store_true', help='make the changes (default: dry run)')
    args = parser.parse_args()

    iam = boto3.client('iam')
    backend_role_arn = iam.get_role(RoleName=args.backend_role)['Role']['Arn']
    account_id = backend_role_arn.split(':')[4]
    client_role_arn = f'arn:aws:iam::{account_id}:role/{CLIENT_ROLE_NAME}'

    trust = client_trust_policy(backend_role_arn)
    client_perms = client_permissions_policy()
    backend_perms = backend_policy(client_role_arn, args.bucket)

    print(f'Backend role: {backend_role_arn}')
    print(f'\nClient role {CLIENT_ROLE_NAME} trust policy:\n{json.dumps(trust, indent=2)}')
    print(f'\nClient role inline policy {CLIENT_POLICY_NAME}:\n{json.dumps(client_perms, indent=2)}')
    print(f'\nBackend role inline policy {BACKEND_POLICY_NAME}:\n{json.dumps(backend_perms, indent=2)}')

    if not args.apply:
        print('\nDry run: nothing changed. Re-run with --apply.')
        return

    try:
        iam.create_role(
            RoleName=CLIENT_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description='Confio face step-up: app streams one Rekognition Face Liveness session',
            MaxSessionDuration=3600,
        )
        print(f'\nCreated role {CLIENT_ROLE_NAME}')
    except ClientError as exc:
        if exc.response['Error']['Code'] != 'EntityAlreadyExists':
            raise
        iam.update_assume_role_policy(RoleName=CLIENT_ROLE_NAME, PolicyDocument=json.dumps(trust))
        print(f'\nRole {CLIENT_ROLE_NAME} exists; trust policy updated')
    iam.put_role_policy(RoleName=CLIENT_ROLE_NAME, PolicyName=CLIENT_POLICY_NAME,
                        PolicyDocument=json.dumps(client_perms))
    iam.put_role_policy(RoleName=args.backend_role, PolicyName=BACKEND_POLICY_NAME,
                        PolicyDocument=json.dumps(backend_perms))
    print('Policies applied.\n')
    print(f'FACE_LIVENESS_CLIENT_ROLE_ARN={client_role_arn}')
    print('FACE_STEP_UP_AVAILABLE=True')


if __name__ == '__main__':
    main()
