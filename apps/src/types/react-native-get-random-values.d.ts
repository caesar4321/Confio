declare module 'react-native-get-random-values' {
  export function getRandomValues<T extends ArrayBufferView | null>(array: T): T;
} 