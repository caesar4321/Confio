import { Platform, StatusBar } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

export const useAppSafeArea = () => {
  const insets = useSafeAreaInsets();
  
  // Safe top constraint handling Android translucent/hidden notch bar quirks
  // Android often reports 0 for insets.top if WindowTranslucentStatus is used, so we fallback to StatusBar.currentHeight.
  const top = Platform.OS === 'android' 
    ? (StatusBar.currentHeight || insets.top || 24)
    : Math.max(insets.top, 20); // iOS minimum status bar
    
  return {
    top,
    bottom: Math.max(insets.bottom, Platform.OS === 'ios' ? 24 : 16),
    headerHeight: top + 44, // Using standard 44px navigation bar height plus top inset
  };
};
