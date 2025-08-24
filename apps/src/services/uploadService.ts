// RNFS no longer required for identity uploads (using presigned POST + FormData).
// Keep imports minimal to avoid native module errors on Android.

export interface PresignedUpload {
  url: string;
  key: string;
  method: string; // 'PUT'
  headers: Record<string, string>;
  expiresIn: number;
}

// Removed: normalizeUriToPath and RNFS usage

export async function uploadFileToPresigned(url: string, headers: Record<string, string>, uri: string): Promise<void> {
  // Minimal PUT upload using fetch. Caller must ensure correct Content-Type header.
  // RN's fetch supports file body via blob from uri when using RN >= 0.59.
  // We fallback to FormData only for POST; for PUT, we stream the file directly.
  // Some RN environments accept body as `{ uri, type, name }` even for PUT; here we use Blob for portability.
  const body: any = (global as any).Blob
    ? // @ts-ignore create blob from file URI when available
      await (await fetch(uri)).blob()
    : // Fallback: try RN-style file object
      ({ uri, type: headers?.['Content-Type'] || 'application/octet-stream', name: 'evidence.mp4' } as any)

  const resp = await fetch(url, {
    method: 'PUT',
    headers: headers || {},
    body,
  } as any)
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`Upload failed (${resp.status}): ${text}`)
  }
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
