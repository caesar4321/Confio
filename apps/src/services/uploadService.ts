import RNFS from 'react-native-fs';
import { Buffer } from 'buffer';
import { Platform } from 'react-native';

export interface PresignedUpload {
  url: string;
  key: string;
  method: string; // 'PUT'
  headers: Record<string, string>;
  expires_in: number;
}

async function normalizeUriToPath(uri: string): Promise<string> {
  // Handle iOS Camera Roll URIs (ph://)
  if (Platform.OS === 'ios' && uri.startsWith('ph://')) {
    const tempPath = `${RNFS.TemporaryDirectoryPath}${Math.random().toString(36).slice(2)}.jpg`;
    // Copy original resolution (width/height 0 = original per RNFS docs)
    await RNFS.copyAssetsFileIOS(uri, tempPath, 0, 0, 1.0, 0.9, 'contain');
    return tempPath;
  }
  // Older iOS scheme
  if (Platform.OS === 'ios' && uri.startsWith('assets-library://')) {
    const tempPath = `${RNFS.TemporaryDirectoryPath}${Math.random().toString(36).slice(2)}.jpg`;
    await RNFS.copyAssetsFileIOS(uri, tempPath, 0, 0, 1.0, 0.9, 'contain');
    return tempPath;
  }
  // file:// path (iOS/Android)
  if (uri.startsWith('file://')) return uri.replace('file://', '');
  // content:// (Android) – try to read by copying stream via readFile (may fail on some OEMs)
  if (Platform.OS === 'android' && uri.startsWith('content://')) {
    // RNFS can't read content:// directly reliably; try copy to cache via copyFile if supported
    const dest = `${RNFS.CachesDirectoryPath}/${Math.random().toString(36).slice(2)}.jpg`;
    try {
      await RNFS.copyFile(uri, dest);
      return dest;
    } catch {
      // Fallback not implemented; callers should use a picker that returns file:// on Android
      throw new Error('Unable to access content URI on Android; please select a file path.');
    }
  }
  // Default: assume plain path
  return uri;
}

export async function uploadFileToPresigned(url: string, headers: Record<string, string>, uri: string): Promise<void> {
  const path = await normalizeUriToPath(uri);
  // Read file as base64, convert to binary buffer, then PUT
  const base64 = await RNFS.readFile(path, 'base64');
  const binary = Buffer.from(base64, 'base64');
  const resp = await fetch(url, {
    method: 'PUT',
    headers: headers || {},
    body: binary as any,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(`Upload failed (${resp.status}): ${text}`);
  }
}
