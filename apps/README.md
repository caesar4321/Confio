# Confío React Native App

This is the React Native mobile application for Confío, a Web3 wallet for Latin America.

## 🚀 Quick Start

### Prerequisites

- **Node.js** (v18 or higher)
- **Yarn** package manager
- **React Native CLI**
- **Android Studio** (for Android development)
- **Xcode** (for iOS development, macOS only)

### Platform-Specific Setup

#### For macOS/Linux Developers

1. **Run the setup script:**
   ```bash
   ./scripts/setup-platform.sh
   ```

2. **Install dependencies:**
   ```bash
   yarn install
   ```

3. **iOS setup (macOS only):**
   ```bash
   cd ios
   bundle install
   bundle exec pod install
   cd ..
   ```

4. **Run the app:**
   ```bash
   # iOS (macOS only)
   yarn ios
   
   # Android
   yarn android
   ```

#### For Windows Developers

1. **Run the setup script:**
   ```cmd
   scripts\setup-platform.bat
   ```

2. **Install dependencies:**
   ```cmd
   yarn install
   ```

3. **Run Android app:**
   ```cmd
   yarn android
   ```

4. **For iOS development on Windows:**
   - Use WSL2 with Ubuntu for limited iOS development
   - Use a remote macOS machine
   - Use cloud-based iOS development services

## 🔧 Manual Configuration

If the setup scripts don't work, you can manually configure platform-specific files:

### Android Configuration

1. **Create `android/local.properties`:**
   ```properties
   ## This file must *NOT* be checked into Version Control Systems,
   # as it contains information specific to your local configuration.
   #
   # Location of the SDK. This is only used by Gradle.
   # For customization when using a Version Control System, please read the
   # header note.
   
   # macOS: /Users/YOUR_USERNAME/Library/Android/sdk
   # Windows: C:\\Users\\YOUR_USERNAME\\AppData\\Local\\Android\\Sdk
   # Linux: /home/YOUR_USERNAME/Android/Sdk
   sdk.dir=/path/to/your/android/sdk
   ```

### iOS Configuration

1. **Create `ios/.xcode.env.local`:**
   ```bash
   # macOS (Homebrew): /opt/homebrew/bin/node
   # macOS (nvm): /Users/YOUR_USERNAME/.nvm/versions/node/VERSION/bin/node
   # Windows: C:\\Program Files\\nodejs\\node.exe
   # Linux: /usr/bin/node or /usr/local/bin/node
   export NODE_BINARY=/path/to/your/node
   ```

## 🚫 Avoiding Platform Conflicts

### Files That Should NOT Be Committed

The following files contain platform-specific paths and should never be committed to Git:

- `android/local.properties` - Contains Android SDK path
- `ios/.xcode.env.local` - Contains Node.js path
- `*.xcworkspace/xcuserdata/` - Xcode user-specific data
- `*.xcodeproj/xcuserdata/` - Xcode user-specific data
- `*.xcodeproj/project.xcworkspace/xcuserdata/` - Xcode user-specific data
- `.env*` files - Environment variables

### Template Files

Use these template files as reference:
- `android/local.properties.template` - Android SDK configuration template
- `ios/.xcode.env.template` - iOS Node.js configuration template

### Best Practices

1. **Always run setup scripts** when cloning the repository
2. **Never commit** platform-specific configuration files
3. **Use template files** as reference for manual configuration
4. **Test on both platforms** before merging platform-specific changes
5. **Document platform differences** in commit messages

## 🏗️ Project Structure

```
apps/
├── android/              # Android-specific native code
├── ios/                  # iOS-specific native code (macOS only)
├── src/                  # React Native source code
│   ├── components/       # Reusable components
│   ├── screens/          # App screens
│   ├── services/         # API services
│   ├── utils/            # Utility functions
│   └── ...
├── scripts/              # Build and setup scripts
│   ├── setup-platform.sh # macOS/Linux setup script
│   └── setup-platform.bat # Windows setup script
└── ...
```

## 🔧 Development Workflow

### For Cross-Platform Development

1. **Shared Code Changes:**
   - All changes in `src/` are shared across platforms
   - Test on both iOS and Android before committing

2. **Platform-Specific Changes:**
   - Document platform differences clearly
   - Use platform-specific files when necessary
   - Test thoroughly on the target platform

3. **Native Dependencies:**
   - iOS: Update `ios/Podfile` and run `pod install`
   - Android: Update `android/app/build.gradle` and sync

### Common Issues and Solutions

#### Android Build Issues

1. **SDK not found:**
   - Run `./scripts/setup-platform.sh` (macOS/Linux) or `scripts\setup-platform.bat` (Windows)
   - Verify Android SDK installation
   - Check `android/local.properties` path

2. **Gradle sync failed:**
   - Clean project: `cd android && ./gradlew clean`
   - Invalidate caches in Android Studio
   - Check Gradle version compatibility

#### iOS Build Issues

1. **Node.js not found:**
   - Run `./scripts/setup-platform.sh`
   - Verify Node.js installation
   - Check `ios/.xcode.env.local` path

2. **Pod install failed:**
   - Update CocoaPods: `sudo gem install cocoapods`
   - Clean and reinstall: `cd ios && rm -rf Pods && bundle exec pod install`

## 📱 Multi-Account Features

The app supports multiple accounts per user:

- **Personal Accounts**: Individual wallets for personal transactions
- **Business Accounts**: Dedicated wallets for business operations
- **Account Switching**: Seamless switching between accounts
- **Deterministic Addresses**: Same OAuth identity + account context = same Sui address

## 🔒 Security Features

- **Non-custodial**: Private keys never stored on servers
- **Secure Storage**: Uses React Native Keychain for sensitive data
- **zkLogin Integration**: Zero-knowledge proof authentication
- **Token Management**: Automatic refresh and secure storage

## 🧪 Testing

```bash
# Run tests
yarn test

# Run tests with coverage
yarn test --coverage

# Run specific test file
yarn test zkLogin.test.ts
```

## 📦 Building for Production

### Android

```bash
# Generate signed APK
cd android
./gradlew assembleRelease

# Generate signed AAB (for Play Store)
./gradlew bundleRelease
```

### iOS

```bash
# Archive for App Store
# Use Xcode: Product > Archive
```

## 🤝 Contributing

1. **Fork the repository**
2. **Create a feature branch**
3. **Make your changes**
4. **Test on both platforms** (if applicable)
5. **Submit a pull request**

### Platform-Specific Contributions

- **iOS changes**: Test on macOS
- **Android changes**: Test on your platform
- **Cross-platform changes**: Test on both platforms
- **Documentation**: Update README for platform differences

## 📄 License

MIT License - see main repository for details.
