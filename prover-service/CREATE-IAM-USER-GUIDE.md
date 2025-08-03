# Create IAM User for Confio Deployment (NOT Root!)

⚠️ **NEVER use root access keys!** Follow these steps to create a limited IAM user:

## Step 1: Create IAM User

1. **Go to IAM Console**: https://console.aws.amazon.com/iam/
2. Click **"Users"** → **"Create user"**
3. **User name**: `confio-deployer`
4. Click **"Next"**

## Step 2: Set Permissions

Choose **"Attach policies directly"** and add these policies:

### For EC2 Management:
- ✅ `AmazonEC2FullAccess` (or create custom policy below)

### For Future App Deployment:
- ✅ `AmazonS3FullAccess`
- ✅ `AmazonRDSFullAccess` 
- ✅ `CloudWatchFullAccess`

### OR Create Custom Policy (More Secure):

Click **"Create policy"** and use this JSON:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2SpotManagement",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus",
        "ec2:CreateTags",
        "ec2:DescribeTags",
        "ec2:DescribeSecurityGroups",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:DescribeImages",
        "ec2:DescribeKeyPairs",
        "ec2:DescribeSubnets",
        "ec2:DescribeVpcs",
        "ec2:RequestSpotInstances",
        "ec2:DescribeSpotInstanceRequests",
        "ec2:CancelSpotInstanceRequests"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "eu-central-2"
        }
      }
    },
    {
      "Sid": "IAMRoleManagement",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:CreateInstanceProfile",
        "iam:AddRoleToInstanceProfile",
        "iam:AttachRolePolicy",
        "iam:CreatePolicy",
        "iam:PassRole",
        "iam:GetRole",
        "iam:GetInstanceProfile"
      ],
      "Resource": [
        "arn:aws:iam::*:role/zkLogin-*",
        "arn:aws:iam::*:instance-profile/zkLogin-*",
        "arn:aws:iam::*:policy/zkLogin-*"
      ]
    }
  ]
}
```

Name it: `ConfioDeploymentPolicy`

## Step 3: Review and Create

1. Click **"Next"** → **"Create user"**
2. User is created!

## Step 4: Create Access Keys

1. Click on the user `confio-deployer`
2. Go to **"Security credentials"** tab
3. Click **"Create access key"**
4. Choose **"Command Line Interface (CLI)"**
5. Check the confirmation box
6. Click **"Create access key"**
7. **Download the CSV file** (keep it secure!)

## Step 5: Configure AWS CLI

```bash
aws configure --profile confio
```

Enter:
- AWS Access Key ID: [from CSV]
- AWS Secret Access Key: [from CSV]
- Default region: eu-central-2
- Output format: json

## Step 6: Test

```bash
aws sts get-caller-identity --profile confio
```

## Step 7: Use for Deployment

```bash
export AWS_PROFILE=confio
./launch-ec2-spot.sh
```

## 🔐 Security Best Practices

1. **Enable MFA** on this IAM user:
   - In IAM → Users → confio-deployer → Security credentials
   - Click "Assign MFA device"

2. **Rotate keys regularly** (every 90 days)

3. **Delete keys** after EC2 is set up and use IAM roles

4. **Never commit** the CSV file or credentials to git

## 🚨 If You Already Created Root Keys

1. **Delete them immediately** after creating IAM user
2. Go to: Security credentials → Access keys → Delete
3. Enable MFA on root account
4. Never use root account for daily tasks