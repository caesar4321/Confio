import { Buffer } from 'buffer';

declare global {
  interface Window {
    atob: (str: string) => string;
    btoa: (str: string) => string;
  }
}

export function base64ToBytes(b64: string): Uint8Array {
  // If Buffer is available (you're already pulling in 'buffer'), use it:
  try {
    return Uint8Array.from(Buffer.from(b64, 'base64'));
  } catch {
    // Fallback to atob() for pure JS
    const binary = (global as any).atob?.(b64) || window.atob(b64);
    const arr = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      arr[i] = binary.charCodeAt(i);
    }
    return arr;
  }
}

export function bytesToBase64(bytes: Uint8Array): string {
  try {
    return Buffer.from(bytes).toString('base64');
  } catch {
    // Fallback to btoa() for pure JS
    let binary = '';
    for (let i = 0; i < bytes.length; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return (global as any).btoa?.(binary) || window.btoa(binary);
  }
} 