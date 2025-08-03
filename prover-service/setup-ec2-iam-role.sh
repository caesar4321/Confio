#!/bin/bash

# Create IAM role for EC2 instances (best practice)

echo "🔐 Creating IAM Role for EC2 zkLogin Prover..."

ROLE_NAME="zkLogin-Prover-Role"
POLICY_NAME="zkLogin-Prover-Policy"

# Create trust policy for EC2
cat > ec2-trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create the role
echo "Creating IAM role..."
aws iam create-role \
    --role-name $ROLE_NAME \
    --assume-role-policy-document file://ec2-trust-policy.json \
    --description "Role for zkLogin Prover EC2 instances"

# Create policy with minimal permissions
cat > zklogin-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams"
      ],
      "Resource": "arn:aws:logs:eu-central-2:*:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:PutMetricData",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeTags"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ],
      "Resource": "arn:aws:ssm:eu-central-2:*:parameter/confio/zklogin/*"
    }
  ]
}
EOF

# Create and attach the policy
echo "Creating IAM policy..."
POLICY_ARN=$(aws iam create-policy \
    --policy-name $POLICY_NAME \
    --policy-document file://zklogin-policy.json \
    --description "Policy for zkLogin Prover EC2 instances" \
    --query 'Policy.Arn' \
    --output text)

echo "Attaching policy to role..."
aws iam attach-role-policy \
    --role-name $ROLE_NAME \
    --policy-arn $POLICY_ARN

# Attach AWS managed policies for CloudWatch
aws iam attach-role-policy \
    --role-name $ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy

# Create instance profile
echo "Creating instance profile..."
aws iam create-instance-profile \
    --instance-profile-name $ROLE_NAME

aws iam add-role-to-instance-profile \
    --instance-profile-name $ROLE_NAME \
    --role-name $ROLE_NAME

# Clean up temporary files
rm -f ec2-trust-policy.json zklogin-policy.json

echo "
✅ IAM Role created successfully!

Role Name: $ROLE_NAME
Instance Profile: $ROLE_NAME

This role provides:
- CloudWatch Logs access
- CloudWatch Metrics access
- EC2 describe permissions
- SSM Parameter Store access (for secrets)

To use this role:
1. Add --iam-instance-profile Name=$ROLE_NAME to launch-ec2-spot.sh
2. Or attach it to existing instances in the console

Benefits:
- No credentials stored on EC2 instance
- Automatic credential rotation
- Follows AWS best practices
- Better security and audit trail
"