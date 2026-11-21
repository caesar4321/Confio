// "Compartir → Confío": a payment QR shared from another app (a store's Pix
// checkout, a delivery app, a WhatsApp screenshot) opens Pagar with that QR,
// exactly as if it had been scanned. Nothing is paid here: the payment screen
// shows the merchant and amount and the person confirms there.
//
// Android: the image arrives through ConfioShareIntent (ACTION_SEND image/*).
// iOS: the Share Extension reads the QR itself and opens confio://shared-qr?p=…
import { useEffect, useRef } from 'react';
import { Alert, AppState, Linking, NativeEventEmitter, NativeModules } from 'react-native';

const MAX_PAYLOAD = 4096;

/** The QR payload in a confio://shared-qr link, or null for any other link. */
export function parseSharedQrUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  const match = /^confio:\/\/shared-qr\/?\?(.*)$/i.exec(url.trim());
  if (!match) return null;
  for (const part of match[1].split('&')) {
    const [key, value = ''] = part.split('=');
    if (key !== 'p') continue;
    let payload: string;
    try {
      payload = decodeURIComponent(value.replace(/\+/g, ' ')).trim();
    } catch {
      return null;
    }
    return payload && payload.length <= MAX_PAYLOAD ? payload : null;
  }
  return null;
}

// iOS hands the QR over as a link. The tabs (and this hook) mount only after
// login, so links are caught from module load, when the app first imports the
// tab bar, and kept until a hook takes them, like Android's pending image.
// getInitialURL is read once per process, not on every remount.
let pendingLink: string | null = null;
let linkListener: ((payload: string) => void) | null = null;
let liveLinkSeen = false;

function receiveLink(url?: string | null) {
  const payload = parseSharedQrUrl(url);
  if (!payload) return;
  if (linkListener) linkListener(payload);
  else pendingLink = payload;
}

Linking.addEventListener('url', event => { liveLinkSeen = true; receiveLink(event.url); });
// The launch link is older than any link that arrives while the app runs:
// never let it replay after a newer share.
Linking.getInitialURL().then(url => { if (!liveLinkSeen) receiveLink(url); }).catch(() => {});

export function useSharedQr(open: (payload: string) => void) {
  const openRef = useRef(open);
  openRef.current = open;

  useEffect(() => {
    let alive = true;
    const native = NativeModules.ConfioShareIntent;
    let draining = false;

    const fromImage = async (uri: string) => {
      try {
        // Loaded on use: the tab bar imports this hook, and the decoder is a
        // native module nothing else on that path needs.
        const RNQRGenerator = require('rn-qr-generator').default;
        const detected = await RNQRGenerator.detect({ uri });
        const value = detected?.values?.[0];
        if (!alive) return;
        if (value) openRef.current(value);
        else Alert.alert('Sin código QR', 'No encontramos un código QR en la imagen que compartiste.', [{ text: 'Entendido' }]);
      } catch {
        if (alive) Alert.alert('Sin código QR', 'No pudimos leer un código QR de esa imagen.', [{ text: 'Entendido' }]);
      } finally {
        native?.releaseSharedImage?.(uri);
      }
    };

    const drain = async () => {
      if (!native?.consumeSharedImage || draining) return;
      draining = true;
      try {
        const uri: string | null = await native.consumeSharedImage();
        if (uri && alive) await fromImage(uri);
      } catch {
        if (alive) Alert.alert('No pudimos abrir la imagen', 'Vuelve a compartirla con Confío.', [{ text: 'Entendido' }]);
      } finally {
        draining = false;
      }
    };

    const listener = (payload: string) => { if (alive) openRef.current(payload); };
    linkListener = listener;
    if (pendingLink) {
      const payload = pendingLink;
      pendingLink = null;
      openRef.current(payload);
    }

    void drain();
    const shareSub = native ? new NativeEventEmitter(native).addListener('ConfioSharedImage', () => { void drain(); }) : null;
    const appSub = AppState.addEventListener('change', state => { if (state === 'active') void drain(); });
    return () => {
      alive = false;
      if (linkListener === listener) linkListener = null;
      shareSub?.remove();
      appSub.remove();
    };
  }, []);
}
