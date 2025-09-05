import { NativeModules, Platform } from 'react-native';

type NativeMediaPicker = {
  pickImage: () => Promise<string | null>;
  pickVideo: () => Promise<string | null>;
};

const native: NativeMediaPicker | undefined =
  Platform.OS === 'android' ? (NativeModules.MediaPicker as NativeMediaPicker) : undefined;

export async function pickImageUri(): Promise<string | null> {
  if (Platform.OS !== 'android') {
    // On iOS, callers should use the system picker or a library.
    return null;
  }
  if (!native?.pickImage) return null;
  try {
    return await native.pickImage();
  } catch {
    return null;
  }
}

export async function pickVideoUri(): Promise<string | null> {
  if (Platform.OS !== 'android') return null;
  if (!native?.pickVideo) return null;
  try {
    return await native.pickVideo();
  } catch {
    return null;
  }
}

