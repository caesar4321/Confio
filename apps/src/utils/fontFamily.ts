import { Platform } from 'react-native';

const androidFontBugSignature =
  Platform.OS === 'android'
    ? `${Platform.constants?.Brand || ''} ${Platform.constants?.Manufacturer || ''}`.toLowerCase()
    : '';

const isXiaomiFontBugDevice =
  androidFontBugSignature.includes('xiaomi') ||
  androidFontBugSignature.includes('redmi') ||
  androidFontBugSignature.includes('poco');

export const technicalFontFamily = Platform.select({
  ios: 'Menlo',
  android: isXiaomiFontBugDevice ? 'sans-serif-medium' : 'monospace',
  default: undefined,
});
