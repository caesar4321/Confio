// RNFS no longer required for identity uploads (using presigned POST + FormData).
// Keep imports minimal to avoid native module errors on Android.

export interface PresignedUpload {
  url: string;
  key: string;
  method: string; // 'PUT'
  headers: Record<string, string>;
  expires_in: number;
}

// Removed: normalizeUriToPath and RNFS usage

export async function uploadFileToPresigned(_url: string, _headers: Record<string, string>, _uri: string): Promise<void> {
  throw new Error('PUT uploads disabled: use presigned POST (fields)');
}

export async function uploadFileToPresignedForm(
  url: string,
  fields: Record<string, string>,
  uri: string,
  filename: string,
  contentType: string
): Promise<void> {
  const form = new FormData();
  // Add all policy fields first
  Object.entries(fields || {}).forEach(([k, v]) => form.append(k, v as any));
  // Then the file part named 'file'
  form.append('file', {
    uri,
    name: filename,
    type: contentType,
  } as any);
  const resp = await fetch(url, {
    method: 'POST',
    body: form as any,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(`Upload failed (${resp.status}): ${text}`);
  }
}
