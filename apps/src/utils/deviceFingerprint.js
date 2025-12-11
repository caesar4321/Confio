/**
 * Device Fingerprinting Utility for Confío
 * Collects comprehensive device information for security purposes
 */

import { Platform, Dimensions, NativeModules } from 'react-native';
import { getGenericPassword, setGenericPassword } from 'react-native-keychain';
import DeviceInfo from 'react-native-device-info';

class DeviceFingerprint {

  static async generateFingerprint() {
    try {
      // Get the stable device ID directly
      const deviceId = await this.getStableDeviceId();

      // Return ONLY the deviceId - nothing else matters for fingerprinting
      return {
        deviceId: deviceId
      };
    } catch (error) {
      console.error('Error generating device fingerprint:', error);
      // Even in fallback, try to get something stable
      try {
        const model = await DeviceInfo.getModel();
        return {
          deviceId: `fallback_${Platform.OS}_${model}`
        };
      } catch (e) {
        return {
          deviceId: `fallback_${Platform.OS}_unknown`
        };
      }
    }
  }

  static async getStableDeviceId() {
    try {
      // For Android, use Android ID which is stable until factory reset
      if (Platform.OS === 'android') {
        const androidId = await DeviceInfo.getAndroidId();
        if (androidId && androidId !== 'unknown') {
          return androidId;
        }
      }

      // For iOS or if Android ID fails, create a stable ID from device characteristics
      // IMPORTANT: Use getUniqueId() which returns IDFV on iOS / AndroidID on Android
      // getDeviceId() returns the MODEL (e.g. iPhone13,2) which is NOT unique!
      const deviceId = await DeviceInfo.getUniqueId();
      const brand = await DeviceInfo.getBrand(); // e.g., "Apple" or "Samsung"
      const systemVersion = await DeviceInfo.getSystemVersion(); // e.g., "13.0"

      // Try to get a persistent ID from keychain
      const stored = await getGenericPassword({ service: 'confio_persistent_device_id' });
      if (stored && stored.password) {
        return stored.password;
      }

      // Generate a new persistent ID based on device characteristics
      const baseString = `${Platform.OS}_${deviceId}_${brand}`;
      const persistentId = this.simpleHash(baseString);

      // Store it for future use
      await setGenericPassword(
        'persistent_id',
        persistentId,
        { service: 'confio_persistent_device_id' }
      );

      return persistentId;
    } catch (error) {
      console.error('Error getting stable device ID:', error);
      // Last resort - use device model
      try {
        const model = await DeviceInfo.getModel();
        return `fallback_${Platform.OS}_${model}`;
      } catch (e) {
        return `fallback_${Platform.OS}_unknown`;
      }
    }
  }

  static async getBasicDeviceInfo() {
    try {
      const deviceInfo = {
        platform: Platform.OS,
        platformVersion: Platform.Version,
        // Get additional info from Platform constants
        constants: Platform.constants || {},
        isTV: Platform.isTV || false,
        isTesting: Platform.isTesting || false
      };

      // Try to get commonly available device info
      try {
        deviceInfo.deviceId = await DeviceInfo.getDeviceId();
        deviceInfo.deviceType = await DeviceInfo.getDeviceType();
        deviceInfo.isEmulator = await DeviceInfo.isEmulator();
        deviceInfo.isTablet = DeviceInfo.isTablet();
      } catch (e) {
        // Some methods might not be available
      }

      // Try to get device name if available
      try {
        deviceInfo.deviceName = await DeviceInfo.getDeviceName();
      } catch (e) {
        // Method might not be available
      }

      // Check for notch if available (iOS)
      if (Platform.OS === 'ios') {
        try {
          deviceInfo.hasNotch = DeviceInfo.hasNotch();
        } catch (e) {
          // Method might not be available
        }

        // Check for dynamic island if available
        try {
          deviceInfo.hasDynamicIsland = DeviceInfo.hasDynamicIsland();
        } catch (e) {
          // Method might not be available
        }
      }

      return deviceInfo;
    } catch (error) {
      console.error('Error getting basic device info:', error);
      return {
        platform: Platform.OS,
        platformVersion: Platform.Version
      };
    }
  }

  static async getSystemFeatures() {
    try {
      // hasSystemFeature might not be available in all versions
      // Return an empty object for now as it's not critical
      return {};
    } catch (error) {
      console.error('Error getting system features:', error);
      return {};
    }
  }

  static getScreenInfo() {
    try {
      const screen = Dimensions.get('screen');
      const window = Dimensions.get('window');

      return {
        screenWidth: screen.width,
        screenHeight: screen.height,
        windowWidth: window.width,
        windowHeight: window.height,
        pixelRatio: screen.scale,
        fontScale: screen.fontScale || 1,
        // Calculate screen density category
        densityCategory: this.getScreenDensityCategory(screen.scale),
        // Calculate aspect ratio
        aspectRatio: Math.round((screen.width / screen.height) * 100) / 100
      };
    } catch (error) {
      console.error('Error getting screen info:', error);
      return {
        screenWidth: 0,
        screenHeight: 0,
        pixelRatio: 1
      };
    }
  }

  static getScreenDensityCategory(scale) {
    // Android density categories
    if (scale <= 1) return 'mdpi';
    if (scale <= 1.5) return 'hdpi';
    if (scale <= 2) return 'xhdpi';
    if (scale <= 3) return 'xxhdpi';
    return 'xxxhdpi';
  }

  static async getSystemInfo() {
    try {
      const systemInfo = {
        platform: Platform.OS,
        platformVersion: Platform.Version
      };

      // Try to get commonly available system info
      try {
        systemInfo.systemName = await DeviceInfo.getSystemName();
        systemInfo.systemVersion = await DeviceInfo.getSystemVersion();
        systemInfo.model = await DeviceInfo.getModel();
        systemInfo.brand = await DeviceInfo.getBrand();
        systemInfo.manufacturer = await DeviceInfo.getManufacturer();
      } catch (e) {
        // Some methods might not be available
      }

      // Try to get Android-specific info
      if (Platform.OS === 'android') {
        try {
          systemInfo.androidId = await DeviceInfo.getAndroidId();
        } catch (e) {
          // Method might not be available
        }
      }

      return systemInfo;
    } catch (error) {
      console.error('Error getting system info:', error);
      return {
        platform: Platform.OS,
        platformVersion: Platform.Version
      };
    }
  }

  static async getLocaleInfo() {
    try {
      const now = new Date();

      // Get available locale info - not all methods exist in react-native-device-info
      const localeInfo = {
        // Use JavaScript to get timezone info
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'unknown',
        timezoneOffset: now.getTimezoneOffset(),
        // Date formatting to detect locale
        dateFormat: now.toLocaleDateString(),
        timeFormat: now.toLocaleTimeString(),
        // Default values for unavailable methods
        locale: 'unknown',
        country: 'unknown',
        language: 'unknown',
        currency: 'unknown'
      };

      // Try to get device locale if available
      try {
        const preferredLocales = await DeviceInfo.getPreferredLocales();
        if (preferredLocales && preferredLocales.length > 0) {
          localeInfo.locale = preferredLocales[0];
          // Parse locale to get language and country
          const localeParts = preferredLocales[0].split(/[-_]/);
          if (localeParts.length > 0) {
            localeInfo.language = localeParts[0];
          }
          if (localeParts.length > 1) {
            localeInfo.country = localeParts[1];
          }
        }
      } catch (e) {
        // Method might not be available
      }

      // Try to get carrier info if available
      try {
        const carrier = await DeviceInfo.getCarrier();
        if (carrier) {
          localeInfo.carrier = carrier;
        }
      } catch (e) {
        // Method might not be available
      }

      return localeInfo;
    } catch (error) {
      console.error('Error getting locale info:', error);
      return {
        timezone: 'unknown',
        locale: 'unknown',
        timezoneOffset: 0
      };
    }
  }

  static async getBehavioralInfo() {
    try {
      // Use keychain for secure storage of behavioral data
      let behavioralData = {};

      try {
        const stored = await getGenericPassword({ service: 'confio_behavioral_data' });
        if (stored && stored.password) {
          behavioralData = JSON.parse(stored.password);
        }
      } catch (e) {
        // First time or error reading
      }

      const now = new Date().toISOString();
      const currentLaunchCount = (behavioralData.appLaunchCount || 0) + 1;

      // Update behavioral data
      const updatedData = {
        firstInstallTime: behavioralData.firstInstallTime || now,
        appLaunchCount: currentLaunchCount,
        lastLaunchTime: behavioralData.currentLaunchTime || now,
        currentLaunchTime: now,
        sessionPattern: this.updateSessionPattern(behavioralData.sessionPattern || [])
      };

      // Store updated data
      await setGenericPassword(
        'behavioral_data',
        JSON.stringify(updatedData),
        { service: 'confio_behavioral_data' }
      );

      return updatedData;
    } catch (error) {
      console.error('Error getting behavioral info:', error);
      return {
        appLaunchCount: 1,
        currentLaunchTime: new Date().toISOString()
      };
    }
  }

  static updateSessionPattern(existingPattern) {
    const now = new Date();
    const hour = now.getHours();
    const dayOfWeek = now.getDay();

    // Keep only last 20 sessions
    const pattern = existingPattern.slice(-19);
    pattern.push({
      hour,
      dayOfWeek,
      timestamp: now.toISOString()
    });

    return pattern;
  }

  static async getPersistentId() {
    try {
      // Try to get existing persistent ID from keychain
      const stored = await getGenericPassword({ service: 'confio_device_id' });

      if (stored && stored.password) {
        return stored.password;
      }

      // Generate new persistent ID based on stable device characteristics
      const stableId = await this.generateStableDeviceId();

      // Store in keychain for faster access
      await setGenericPassword(
        'device_id',
        stableId,
        { service: 'confio_device_id' }
      );

      return stableId;
    } catch (error) {
      console.error('Error getting persistent ID:', error);
      // Return a stable ID based on available info
      return this.generateFallbackStableId();
    }
  }

  static async generateStableDeviceId() {
    try {
      const deviceInfo = await this.getBasicDeviceInfo();
      const systemInfo = await this.getSystemInfo();
      const screenInfo = this.getScreenInfo();

      // Collect all stable identifiers available
      const stableComponents = [];

      // Android ID is stable across app reinstalls (until factory reset)
      if (systemInfo.androidId && systemInfo.androidId !== 'unknown') {
        stableComponents.push(`aid:${systemInfo.androidId}`);
      }

      // Device model and manufacturer are stable
      if (systemInfo.model) {
        stableComponents.push(`model:${systemInfo.model}`);
      }
      if (systemInfo.manufacturer) {
        stableComponents.push(`mfr:${systemInfo.manufacturer}`);
      }
      if (systemInfo.brand) {
        stableComponents.push(`brand:${systemInfo.brand}`);
      }

      // Screen characteristics are stable
      stableComponents.push(`screen:${screenInfo.screenWidth}x${screenInfo.screenHeight}@${screenInfo.pixelRatio}`);

      // Device type and platform
      if (deviceInfo.deviceType) {
        stableComponents.push(`type:${deviceInfo.deviceType}`);
      }
      stableComponents.push(`os:${deviceInfo.platform}-${systemInfo.systemVersion || Platform.Version}`);

      // iOS specific stable identifiers
      if (Platform.OS === 'ios' && deviceInfo.deviceId) {
        stableComponents.push(`did:${deviceInfo.deviceId}`);
      }

      // Create a stable hash from these components
      const stableString = stableComponents.join('|');

      // If we have Android ID or iOS device ID, use it as primary identifier
      if (systemInfo.androidId && systemInfo.androidId !== 'unknown') {
        return `cfio_android_${systemInfo.androidId}_${this.simpleHash(stableString)}`;
      } else if (Platform.OS === 'ios') {
        // Use getUniqueId for iOS (IDFV)
        const uniqueId = await DeviceInfo.getUniqueId();
        return `cfio_ios_${uniqueId}_${this.simpleHash(stableString)}`;
      } else {
        // Fallback to hash-based ID
        return `cfio_device_${this.simpleHash(stableString)}`;
      }
    } catch (error) {
      console.error('Error generating stable device ID:', error);
      return this.generateFallbackStableId();
    }
  }

  static generateFallbackStableId() {
    // Generate a stable ID based on minimal available info
    const screen = Dimensions.get('screen');
    const fallbackString = [
      Platform.OS,
      Platform.Version,
      screen.width,
      screen.height,
      screen.scale
    ].join('-');

    return `cfio_fallback_${this.simpleHash(fallbackString)}`;
  }

  static simpleHash(str) {
    // Simple hash function for creating stable IDs
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; // Convert to 32-bit integer
    }
    return Math.abs(hash).toString(36);
  }

  static async getHardwareInfo() {
    try {
      const screen = Dimensions.get('screen');

      // Calculate approximate hardware specs based on screen
      const pixelCount = screen.width * screen.height * screen.scale * screen.scale;
      const hardwareClass = this.getHardwareClass(pixelCount, screen.scale);

      const hardwareInfo = {
        screenPixelCount: pixelCount,
        hardwareClass,
        screenSize: this.getScreenSizeCategory(screen.width, screen.height, screen.scale),
        // Memory estimation based on hardware class (fallback)
        estimatedMemory: this.estimateMemory(hardwareClass)
      };

      // Try to get battery level if available
      try {
        const batteryLevel = await DeviceInfo.getBatteryLevel();
        if (batteryLevel !== -1) {
          hardwareInfo.batteryLevel = batteryLevel;
        }
      } catch (e) {
        // Method might not be available
      }

      // Try to get power state if available
      try {
        const powerState = await DeviceInfo.getPowerState();
        if (powerState) {
          hardwareInfo.powerState = powerState;
        }
      } catch (e) {
        // Method might not be available
      }

      return hardwareInfo;
    } catch (error) {
      console.error('Error getting hardware info:', error);
      return {
        hardwareClass: 'unknown'
      };
    }
  }

  static getHardwareClass(pixelCount, scale) {
    // Rough hardware classification
    if (pixelCount > 8000000) return 'high-end';
    if (pixelCount > 2000000) return 'mid-range';
    return 'low-end';
  }

  static getScreenSizeCategory(width, height, scale) {
    const diagonalDp = Math.sqrt(width * width + height * height);

    if (diagonalDp > 900) return 'tablet';
    if (diagonalDp > 700) return 'large-phone';
    if (diagonalDp > 500) return 'normal-phone';
    return 'small-phone';
  }

  static estimateMemory(hardwareClass) {
    const estimates = {
      'high-end': '8GB+',
      'mid-range': '4-6GB',
      'low-end': '2-3GB'
    };
    return estimates[hardwareClass] || 'unknown';
  }

  static async getReactNativeInfo() {
    try {
      const rnInfo = {
        // React Native specific info
        hermes: typeof HermesInternal !== 'undefined',
        // Debug mode
        __DEV__: __DEV__ || false,
        // Available native modules (partial list for fingerprinting)
        availableModules: this.getAvailableModules()
      };

      // Try to get app info if available
      try {
        rnInfo.appName = await DeviceInfo.getApplicationName();
        rnInfo.bundleId = await DeviceInfo.getBundleId();
        rnInfo.buildNumber = await DeviceInfo.getBuildNumber();
        rnInfo.version = await DeviceInfo.getVersion();
      } catch (e) {
        // Methods might not be available
      }

      // Try to get installation time if available
      try {
        rnInfo.firstInstallTime = await DeviceInfo.getFirstInstallTime();
        rnInfo.lastUpdateTime = await DeviceInfo.getLastUpdateTime();
      } catch (e) {
        // Methods might not be available
      }

      return rnInfo;
    } catch (error) {
      console.error('Error getting React Native info:', error);
      return {
        __DEV__: false
      };
    }
  }

  static getAvailableModules() {
    try {
      // Check for common native modules
      const modules = {};
      const commonModules = ['KeychainModule', 'RNCNetInfo', 'RNGestureHandlerModule'];

      commonModules.forEach(moduleName => {
        modules[moduleName] = NativeModules[moduleName] !== undefined;
      });

      return modules;
    } catch (error) {
      return {};
    }
  }

  static getFallbackFingerprint() {
    // Minimal fingerprint when main generation fails
    return {
      deviceId: `fallback_${Platform.OS}_${Date.now()}`,
      platform: Platform.OS,
      model: 'unknown',
      systemVersion: Platform.Version.toString(),
      timestamp: new Date().toISOString(),
      isFallback: true,
      fingerprintVersion: '2.0'
    };
  }

  static async generateHash(fingerprint) {
    try {
      // Simply use the device ID as the hash since it's already unique and stable
      if (fingerprint.deviceId) {
        // Create a SHA-256-like hash of the device ID for consistency
        return this.simpleHash(fingerprint.deviceId);
      }

      // Fallback to hashing the entire fingerprint
      const fingerprintString = JSON.stringify(fingerprint, Object.keys(fingerprint).sort());
      return this.simpleHash(fingerprintString);
    } catch (error) {
      console.error('Error generating fingerprint hash:', error);
      return 'hash-error-' + Date.now();
    }
  }

  static async getQuickFingerprint() {
    // Lightweight version for frequent calls
    try {
      const screen = Dimensions.get('screen');
      const stored = await getGenericPassword({ service: 'confio_device_id' });
      const persistentId = stored ? stored.password : 'no-id';

      return {
        persistentId,
        platform: Platform.OS,
        screenWidth: screen.width,
        screenHeight: screen.height,
        pixelRatio: screen.scale,
        timestamp: new Date().toISOString()
      };
    } catch (error) {
      console.error('Error generating quick fingerprint:', error);
      return {
        platform: Platform.OS,
        timestamp: new Date().toISOString(),
        error: true
      };
    }
  }

  static async clearStoredData() {
    // For debugging or user privacy - clear stored behavioral data
    try {
      // Note: This won't clear the persistent ID to maintain device tracking
      await setGenericPassword(
        'behavioral_data',
        JSON.stringify({}),
        { service: 'confio_behavioral_data' }
      );
      return true;
    } catch (error) {
      console.error('Error clearing stored data:', error);
      return false;
    }
  }
}

export default DeviceFingerprint;
export { DeviceFingerprint };