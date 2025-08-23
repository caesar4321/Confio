import RNFS from 'react-native-fs';
import { Buffer } from 'buffer';

export interface PresignedUpload {
  url: string;
  key: string;
  method: string; // 'PUT'
  headers: Record<string, string>;
  expires_in: number;
}

export async function uploadFileToPresigned(url: string, headers: Record<string, string>, filePath: string): Promise<void> {
  // Read file as base64, convert to binary buffer, then PUT
  const base64 = await RNFS.readFile(filePath.replace('file://', ''), 'base64');
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

