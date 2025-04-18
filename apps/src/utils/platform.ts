import RNPlatform from 'react-native';

interface PlatformType {
  OS: 'ios' | 'android' | 'windows' | 'macos' | 'web';
}

const Platform = RNPlatform as unknown as PlatformType;

export const isIOS = () => Platform.OS === 'ios';
export const isAndroid = () => Platform.OS === 'android';
export const getPlatform = () => Platform.OS; 