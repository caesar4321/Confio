// FLAG_SECURE on Android (ConfioSecureScreenPackage.kt): no screenshots,
// recordings, casting or Recents thumbnail of the store's live view.
import { NativeModules, Platform } from 'react-native';

export function setSecureScreen(secure: boolean): void {
  if (Platform.OS !== 'android') {
    return;
  }
  try {
    NativeModules.ConfioSecureScreen?.setSecure(secure);
  } catch {
    // An older native build without the module: nothing to set.
  }
}
