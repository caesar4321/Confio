@echo off
setlocal enabledelayedexpansion

echo 🚀 Setting up platform-specific configurations for React Native...

REM Detect platform
if "%OS%"=="Windows_NT" (
    set PLATFORM=windows
) else (
    echo ❌ This script is designed for Windows
    exit /b 1
)

echo 📱 Detected platform: %PLATFORM%

REM Setup Android local.properties
echo 🤖 Setting up Android configuration...

if not exist "android\local.properties" (
    echo Creating android\local.properties...
    
    REM Try to find Android SDK in common Windows locations
    if exist "%LOCALAPPDATA%\Android\Sdk" (
        set SDK_PATH=%LOCALAPPDATA%\Android\Sdk
    ) else if exist "C:\Users\%USERNAME%\AppData\Local\Android\Sdk" (
        set SDK_PATH=C:\Users\%USERNAME%\AppData\Local\Android\Sdk
    ) else (
        echo ⚠️  Android SDK not found in common Windows locations.
        echo Please install Android Studio or Android SDK and run this script again.
        echo Expected locations:
        echo   - %LOCALAPPDATA%\Android\Sdk
        echo   - C:\Users\%USERNAME%\AppData\Local\Android\Sdk
        exit /b 1
    )
    
    (
        echo ## This file must *NOT* be checked into Version Control Systems,
        echo # as it contains information specific to your local configuration.
        echo #
        echo # Location of the SDK. This is only used by Gradle.
        echo # For customization when using a Version Control System, please read the
        echo # header note.
        echo sdk.dir=%SDK_PATH%
    ) > android\local.properties
    
    echo ✅ Created android\local.properties with SDK path: %SDK_PATH%
) else (
    echo ✅ android\local.properties already exists
)

REM Setup iOS .xcode.env.local (for Windows developers who might use WSL or need to reference)
echo 🍎 Setting up iOS configuration...

if not exist "ios\.xcode.env.local" (
    echo Creating ios\.xcode.env.local...
    
    REM Try to find Node.js in common Windows locations
    where node >nul 2>&1
    if %ERRORLEVEL% == 0 (
        for /f "tokens=*" %%i in ('where node') do set NODE_PATH=%%i
    ) else if exist "C:\Program Files\nodejs\node.exe" (
        set NODE_PATH=C:\Program Files\nodejs\node.exe
    ) else (
        echo ⚠️  Node.js not found. Please install Node.js and run this script again.
        exit /b 1
    )
    
    (
        echo export NODE_BINARY=%NODE_PATH%
    ) > ios\.xcode.env.local
    
    echo ✅ Created ios\.xcode.env.local with Node.js path: %NODE_PATH%
) else (
    echo ✅ ios\.xcode.env.local already exists
)

echo.
echo 🎉 Platform setup complete!
echo.
echo Next steps:
echo 1. Install dependencies: yarn install
echo 2. For Android: yarn android
echo 3. For iOS (requires macOS or WSL): yarn ios
echo.
echo If you encounter any issues, check the template files:
echo - android\local.properties.template
echo - ios\.xcode.env.template
echo.
echo Note: iOS development requires macOS. Windows developers can use:
echo - WSL2 with Ubuntu for limited iOS development
echo - Remote macOS machine
echo - Cloud-based iOS development services 