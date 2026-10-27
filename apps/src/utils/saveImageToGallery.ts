// Save a local image (a captured card, a QR) to the phone's gallery.
// Android 10+ and iOS need nothing extra (iOS asks with the Info.plist text);
// Android 7–9 write to public storage and need the storage permission first.
import { PermissionsAndroid, Platform } from 'react-native';
import { CameraRoll } from '@react-native-camera-roll/camera-roll';

export async function saveImageToGallery(uri: string): Promise<void> {
  if (Platform.OS === 'android' && Number(Platform.Version) < 29) {
    const granted = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.WRITE_EXTERNAL_STORAGE);
    if (granted !== PermissionsAndroid.RESULTS.GRANTED) {
      throw new Error('storage permission denied');
    }
  }
  await CameraRoll.save(uri, { type: 'photo' });
}
