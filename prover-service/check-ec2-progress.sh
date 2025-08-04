#!/bin/bash

# Script to check EC2 compilation progress via SSM

INSTANCE_ID="i-08a3605c990ad715d"
REGION="eu-central-2"

echo "🔍 Checking EC2 instance compilation status..."

# Try AWS Systems Manager Session Manager
echo "📡 Attempting to connect via SSM..."
aws ssm start-session --region $REGION --target $INSTANCE_ID --document-name AWS-StartInteractiveCommand --parameters command="ps aux | grep circom; echo '---'; ls -la ~/kzero-circuit/zkLogin_js/ 2>/dev/null; echo '---'; tail -20 /var/log/user-data.log 2>/dev/null"

# If SSM doesn't work, check instance status
echo "📊 Instance status:"
aws ec2 describe-instance-status --region $REGION --instance-ids $INSTANCE_ID --query 'InstanceStatuses[0].[InstanceState.Name,InstanceStatus.Status,SystemStatus.Status]' --output text