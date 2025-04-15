#!/bin/bash

# Check if environment argument is provided
if [ -z "$1" ]; then
    echo "Usage: ./switch-env.sh [development|production]"
    exit 1
fi

ENV=$1
INFO_PLIST="ios/Confio/Info.plist"

# Backup the original file
cp "$INFO_PLIST" "${INFO_PLIST}.bak"

if [ "$ENV" == "development" ]; then
    # Development environment (Sui Test)
    sed -i '' "s|<string>730050241347-m60gqh7aahb818c6g7vb4jkpkl5iauld.apps.googleusercontent.com</string>|<string>1001709244115-2h2k3sdvr3ggr1t5pgob4pkb3k92ug1p.apps.googleusercontent.com</string>|g" "$INFO_PLIST"
    echo "Switched to development environment (Sui Test)"
elif [ "$ENV" == "production" ]; then
    # Production environment
    sed -i '' "s|<string>1001709244115-2h2k3sdvr3ggr1t5pgob4pkb3k92ug1p.apps.googleusercontent.com</string>|<string>730050241347-m60gqh7aahb818c6g7vb4jkpkl5iauld.apps.googleusercontent.com</string>|g" "$INFO_PLIST"
    echo "Switched to production environment"
else
    echo "Invalid environment. Use 'development' or 'production'"
    # Restore backup
    mv "${INFO_PLIST}.bak" "$INFO_PLIST"
    exit 1
fi

echo "Environment switched successfully. You may need to clean and rebuild the app." 