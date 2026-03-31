import { Platform, StatusBar, Dimensions } from 'react-native';
import { initialWindowMetrics } from 'react-native-safe-area-context';

const { width, height } = Dimensions.get('window');
const insets = initialWindowMetrics?.insets ?? { top: 48, bottom: 24, left: 0, right: 0 };
const currentHeight = StatusBar.currentHeight || 24;

/**
 * Standardized App Layout Metrics
 * Provides unified cross-platform handling of status bars, notches, and navigation bars.
 */
export const APP_LAYOUT = {
  // Android translucent status bars don't accurately report safe area top, so we use currentHeight
  topSafeArea: Platform.OS === 'android' 
    ? currentHeight 
    : Math.max(insets.top, 20),
  
  bottomSafeArea: Math.max(insets.bottom, Platform.OS === 'ios' ? 24 : 16),
  
  headerHeight: Platform.OS === 'ios' ? 88 : 64,
  
  screenWidth: width,
  screenHeight: height,
};
