#!/bin/bash

# Platform-specific setup script for React Native development
# This script helps configure local.properties and .xcode.env.local for different platforms

set -e

echo "🚀 Setting up platform-specific configurations for React Native..."

# Detect platform
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="macos"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
    PLATFORM="windows"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    PLATFORM="linux"
else
    echo "❌ Unsupported platform: $OSTYPE"
    exit 1
fi

echo "📱 Detected platform: $PLATFORM"

# Setup Android local.properties
echo "🤖 Setting up Android configuration..."

if [ ! -f "android/local.properties" ]; then
    echo "Creating android/local.properties..."
    
    case $PLATFORM in
        "macos")
            # Try to find Android SDK in common macOS locations
            if [ -d "$HOME/Library/Android/sdk" ]; then
                SDK_PATH="$HOME/Library/Android/sdk"
            elif [ -d "/opt/homebrew/share/android-commandlinetools" ]; then
                SDK_PATH="/opt/homebrew/share/android-commandlinetools"
            else
                echo "⚠️  Android SDK not found in common locations."
                echo "Please install Android Studio or Android SDK and run this script again."
                echo "Expected locations:"
                echo "  - $HOME/Library/Android/sdk"
                echo "  - /opt/homebrew/share/android-commandlinetools"
                exit 1
            fi
            ;;
        "windows")
            # Windows paths
            if [ -d "$LOCALAPPDATA/Android/Sdk" ]; then
                SDK_PATH="$LOCALAPPDATA/Android/Sdk"
            elif [ -d "C:/Users/$USERNAME/AppData/Local/Android/Sdk" ]; then
                SDK_PATH="C:/Users/$USERNAME/AppData/Local/Android/Sdk"
            else
                echo "⚠️  Android SDK not found in common Windows locations."
                echo "Please install Android Studio or Android SDK and run this script again."
                exit 1
            fi
            ;;
        "linux")
            # Linux paths
            if [ -d "$HOME/Android/Sdk" ]; then
                SDK_PATH="$HOME/Android/Sdk"
            elif [ -d "/usr/local/android-sdk" ]; then
                SDK_PATH="/usr/local/android-sdk"
            else
                echo "⚠️  Android SDK not found in common Linux locations."
                echo "Please install Android Studio or Android SDK and run this script again."
                exit 1
            fi
            ;;
    esac
    
    cat > android/local.properties << EOF
## This file must *NOT* be checked into Version Control Systems,
# as it contains information specific to your local configuration.
#
# Location of the SDK. This is only used by Gradle.
# For customization when using a Version Control System, please read the
# header note.
sdk.dir=$SDK_PATH
EOF
    
    echo "✅ Created android/local.properties with SDK path: $SDK_PATH"
else
    echo "✅ android/local.properties already exists"
fi

# Setup iOS .xcode.env.local
echo "🍎 Setting up iOS configuration..."

if [ ! -f "ios/.xcode.env.local" ]; then
    echo "Creating ios/.xcode.env.local..."
    
    case $PLATFORM in
        "macos")
            # Try to find Node.js in common macOS locations
            if command -v node &> /dev/null; then
                NODE_PATH=$(which node)
            elif [ -f "/opt/homebrew/bin/node" ]; then
                NODE_PATH="/opt/homebrew/bin/node"
            elif [ -f "/usr/local/bin/node" ]; then
                NODE_PATH="/usr/local/bin/node"
            else
                echo "⚠️  Node.js not found. Please install Node.js and run this script again."
                exit 1
            fi
            ;;
        "windows")
            # Windows paths
            if command -v node &> /dev/null; then
                NODE_PATH=$(which node)
            elif [ -f "C:/Program Files/nodejs/node.exe" ]; then
                NODE_PATH="C:/Program Files/nodejs/node.exe"
            else
                echo "⚠️  Node.js not found. Please install Node.js and run this script again."
                exit 1
            fi
            ;;
        "linux")
            # Linux paths
            if command -v node &> /dev/null; then
                NODE_PATH=$(which node)
            elif [ -f "/usr/bin/node" ]; then
                NODE_PATH="/usr/bin/node"
            elif [ -f "/usr/local/bin/node" ]; then
                NODE_PATH="/usr/local/bin/node"
            else
                echo "⚠️  Node.js not found. Please install Node.js and run this script again."
                exit 1
            fi
            ;;
    esac
    
    cat > ios/.xcode.env.local << EOF
export NODE_BINARY=$NODE_PATH
EOF
    
    echo "✅ Created ios/.xcode.env.local with Node.js path: $NODE_PATH"
else
    echo "✅ ios/.xcode.env.local already exists"
fi

echo ""
echo "🎉 Platform setup complete!"
echo ""
echo "Next steps:"
echo "1. Install dependencies: yarn install"
echo "2. For iOS: cd ios && bundle install && bundle exec pod install"
echo "3. Run the app: yarn ios (macOS) or yarn android"
echo ""
echo "If you encounter any issues, check the template files:"
echo "- android/local.properties.template"
echo "- ios/.xcode.env.template" 