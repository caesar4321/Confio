# Platform-Specific Setup Guide

This guide helps avoid conflicts when developing React Native apps across different platforms (macOS, Windows, Linux).

## 🚨 Critical: Files That Cause Conflicts

### Never Commit These Files

These files contain platform-specific paths and will cause build failures for other developers:

| File | Purpose | Platform-Specific Content |
|------|---------|---------------------------|
| `android/local.properties` | Android SDK location | SDK path (different on each OS) |
| `ios/.xcode.env.local` | Node.js location for iOS | Node.js path (different on each OS) |
| `*.xcworkspace/xcuserdata/` | Xcode user settings | User-specific Xcode preferences |
| `*.xcodeproj/xcuserdata/` | Xcode user settings | User-specific Xcode preferences |
| `.env*` | Environment variables | API keys, secrets, local configs |

### Platform-Specific Paths

#### Android SDK Paths
```properties
# macOS
sdk.dir=/Users/julian/Library/Android/sdk

# Windows
sdk.dir=C:\\Users\\YourName\\AppData\\Local\\Android\\Sdk

# Linux
sdk.dir=/home/username/Android/Sdk
```

#### Node.js Paths for iOS
```bash
# macOS (Homebrew)
export NODE_BINARY=/opt/homebrew/bin/node

# macOS (nvm)
export NODE_BINARY=/Users/username/.nvm/versions/node/18.17.0/bin/node

# Windows
export NODE_BINARY=C:\\Program Files\\nodejs\\node.exe

# Linux
export NODE_BINARY=/usr/bin/node
```

## 🛠️ Automatic Setup

### For macOS/Linux Developers

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd apps
   ```

2. **Run the setup script:**
   ```bash
   ./scripts/setup-platform.sh
   ```

3. **Install dependencies:**
   ```bash
   yarn install
   ```

4. **iOS setup (macOS only):**
   ```bash
   cd ios
   bundle install
   bundle exec pod install
   cd ..
   ```

5. **Run the app:**
   ```bash
   # iOS (macOS only)
   yarn ios
   
   # Android
   yarn android
   ```

### For Windows Developers

1. **Clone the repository:**
   ```cmd
   git clone <repository-url>
   cd apps
   ```

2. **Run the setup script:**
   ```cmd
   scripts\setup-platform.bat
   ```

3. **Install dependencies:**
   ```cmd
   yarn install
   ```

4. **Run Android app:**
   ```cmd
   yarn android
   ```

## 🔧 Manual Setup (If Scripts Fail)

### Android Configuration

1. **Create `android/local.properties`:**
   ```properties
   ## This file must *NOT* be checked into Version Control Systems,
   # as it contains information specific to your local configuration.
   #
   # Location of the SDK. This is only used by Gradle.
   # For customization when using a Version Control System, please read the
   # header note.
   
   # Find your Android SDK path:
   # macOS: /Users/YOUR_USERNAME/Library/Android/sdk
   # Windows: C:\\Users\\YOUR_USERNAME\\AppData\\Local\\Android\\Sdk
   # Linux: /home/YOUR_USERNAME/Android/Sdk
   sdk.dir=/path/to/your/android/sdk
   ```

2. **Find your Android SDK path:**
   - **macOS**: Open Android Studio → Preferences → Appearance & Behavior → System Settings → Android SDK
   - **Windows**: Open Android Studio → File → Settings → Appearance & Behavior → System Settings → Android SDK
   - **Linux**: Usually `/home/username/Android/Sdk` or `/usr/local/android-sdk`

### iOS Configuration (macOS Only)

1. **Create `ios/.xcode.env.local`:**
   ```bash
   # Find your Node.js path:
   # macOS (Homebrew): /opt/homebrew/bin/node
   # macOS (nvm): /Users/YOUR_USERNAME/.nvm/versions/node/VERSION/bin/node
   # Windows: C:\\Program Files\\nodejs\\node.exe
   # Linux: /usr/bin/node or /usr/local/bin/node
   export NODE_BINARY=/path/to/your/node
   ```

2. **Find your Node.js path:**
   ```bash
   which node
   # or
   where node  # on Windows
   ```

## 🚫 Conflict Prevention Strategies

### 1. Git Ignore Configuration

The `.gitignore` file already excludes problematic files:

```gitignore
# Platform-specific files that should not be committed
local.properties
.xcode.env.local
*.xcworkspace/xcuserdata/
*.xcodeproj/xcuserdata/
*.xcodeproj/project.xcworkspace/xcuserdata/

# Environment files
.env
.env.local
.env.development
.env.production
```

### 2. Template Files

Use these template files as reference:
- `android/local.properties.template` - Shows the format and common paths
- `ios/.xcode.env.template` - Shows the format and common paths

### 3. Pre-commit Hooks

Consider adding pre-commit hooks to prevent accidental commits:

```bash
# .git/hooks/pre-commit
#!/bin/bash

# Check for platform-specific files
if git diff --cached --name-only | grep -E "(local\.properties|\.xcode\.env\.local|\.env)"; then
    echo "❌ Error: Attempting to commit platform-specific files!"
    echo "These files should not be committed:"
    git diff --cached --name-only | grep -E "(local\.properties|\.xcode\.env\.local|\.env)"
    exit 1
fi
```

### 4. Documentation

Always document platform-specific changes in commit messages:

```bash
git commit -m "feat: Add new native module

- iOS: Updated Podfile for new dependency
- Android: Updated build.gradle for new library
- Cross-platform: Added shared TypeScript interfaces

Platform-specific files (not committed):
- android/local.properties (SDK path)
- ios/.xcode.env.local (Node.js path)"
```

## 🔄 Development Workflow

### For Cross-Platform Teams

1. **Shared Code Changes:**
   - All changes in `src/` are shared
   - Test on both platforms before committing
   - Use platform-specific imports when necessary

2. **Native Dependencies:**
   - **iOS**: Update `ios/Podfile`, run `pod install`
   - **Android**: Update `android/app/build.gradle`, sync project
   - **Both**: Update `package.json` dependencies

3. **Platform-Specific Features:**
   - Use `Platform.OS` for conditional code
   - Create platform-specific files: `Component.ios.tsx`, `Component.android.tsx`
   - Document platform differences clearly

### Example: Platform-Specific Component

```typescript
// Component.tsx (shared)
import { Platform } from 'react-native';

const Component = () => {
  if (Platform.OS === 'ios') {
    return <IOSComponent />;
  }
  return <AndroidComponent />;
};

// Component.ios.tsx (iOS only)
export const IOSComponent = () => {
  // iOS-specific implementation
};

// Component.android.tsx (Android only)
export const AndroidComponent = () => {
  // Android-specific implementation
};
```

## 🐛 Common Issues and Solutions

### Android Issues

#### "SDK not found" Error
```bash
# Solution: Run setup script or create local.properties
./scripts/setup-platform.sh  # macOS/Linux
scripts\setup-platform.bat   # Windows
```

#### Gradle Sync Failed
```bash
# Solution: Clean and rebuild
cd android
./gradlew clean
./gradlew build
```

#### Build Tools Version Mismatch
```bash
# Solution: Update build.gradle
android {
    compileSdkVersion 34
    buildToolsVersion "34.0.0"
}
```

### iOS Issues

#### "Node.js not found" Error
```bash
# Solution: Run setup script or create .xcode.env.local
./scripts/setup-platform.sh
```

#### Pod Install Failed
```bash
# Solution: Clean and reinstall
cd ios
rm -rf Pods
bundle exec pod install
```

#### Xcode Version Issues
```bash
# Solution: Update Xcode and CocoaPods
sudo gem install cocoapods
```

## 📱 Platform Limitations

### Windows Developers

**iOS Development Limitations:**
- Cannot build iOS apps natively
- Cannot run iOS Simulator
- Cannot use Xcode

**Solutions:**
1. **WSL2 with Ubuntu**: Limited iOS development support
2. **Remote macOS**: Use remote desktop or SSH
3. **Cloud Services**: Use services like Expo or cloud-based iOS development
4. **Focus on Android**: Develop and test Android features, let macOS developers handle iOS

### macOS Developers

**Advantages:**
- Can develop for both iOS and Android
- Full access to Xcode and iOS Simulator
- Native performance for both platforms

**Responsibilities:**
- Test iOS-specific features
- Handle iOS build issues
- Maintain iOS-specific configurations

## 🔍 Verification Checklist

Before committing changes, verify:

- [ ] No platform-specific files are staged for commit
- [ ] Changes work on your platform
- [ ] Cross-platform changes are tested (if applicable)
- [ ] Platform differences are documented
- [ ] Template files are updated (if needed)

## 📞 Getting Help

### For Setup Issues

1. **Check template files** for correct format
2. **Run setup scripts** to auto-configure
3. **Verify paths** match your system
4. **Check documentation** for your platform

### For Build Issues

1. **Clean and rebuild** the project
2. **Check platform-specific configurations**
3. **Verify dependencies** are installed
4. **Check platform limitations**

### For Team Collaboration

1. **Document platform differences** in commit messages
2. **Test on both platforms** before merging
3. **Use platform-specific branches** for major changes
4. **Communicate platform limitations** to the team

## 🎯 Best Practices Summary

1. **Always run setup scripts** when cloning
2. **Never commit** platform-specific files
3. **Use template files** as reference
4. **Test on both platforms** when possible
5. **Document platform differences** clearly
6. **Communicate limitations** to the team
7. **Use platform-specific imports** when needed
8. **Keep shared code** platform-agnostic 