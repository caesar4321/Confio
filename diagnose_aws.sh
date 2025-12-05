#!/bin/bash
# Diagnose AWS credentials issue

echo "🔍 AWS Credentials Diagnostic"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check what's in the credentials file
echo "1️⃣ Checking ~/.aws/credentials for confio1:"
grep -A2 "\[confio1\]" ~/.aws/credentials | sed 's/aws_secret_access_key.*/aws_secret_access_key = ***HIDDEN***/'
echo ""

# Check for environment variables that might interfere
echo "2️⃣ Checking for AWS environment variables:"
env | grep -i aws || echo "None found"
echo ""

# Check for aliases
echo "3️⃣ Checking for AWS aliases:"
alias | grep aws || echo "None found"
echo ""

# Test with explicit credentials (bypassing everything)
echo "4️⃣ Testing credentials with us-east-1 (always works):"
command aws sts get-caller-identity --profile confio1 --region us-east-1 2>&1
RESULT_US=$?
echo ""

# Test with eu-central-2
echo "5️⃣ Testing credentials with eu-central-2:"
command aws sts get-caller-identity --profile confio1 --region eu-central-2 2>&1
RESULT_EU=$?
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Results:"
if [ $RESULT_US -eq 0 ]; then
    echo "✅ us-east-1: WORKS"
else
    echo "❌ us-east-1: FAILED - Credentials are invalid"
fi

if [ $RESULT_EU -eq 0 ]; then
    echo "✅ eu-central-2: WORKS"
else
    echo "❌ eu-central-2: FAILED"
    if [ $RESULT_US -eq 0 ]; then
        echo "   (Region might still be propagating - wait 5 minutes)"
    else
        echo "   (Credentials themselves are invalid)"
    fi
fi

echo ""
echo "💡 Next steps:"
if [ $RESULT_US -ne 0 ] && [ $RESULT_EU -ne 0 ]; then
    echo "   1. Go to AWS Console → IAM → Users → confio1 → Security credentials"
    echo "   2. Check if access key is 'Active'"
    echo "   3. Delete the access key and create a NEW one"
    echo "   4. Run: ./setup_confio1_creds.sh (to add new key)"
fi
