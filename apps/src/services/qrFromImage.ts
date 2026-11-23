// A payment QR inside a picture the person hands the app (a screenshot, a
// photo of a bill): read on the phone, like Pagar's "Galería" does.
import { localPaymentQrRoute } from '../utils/localPaymentQr';

/** The code of the first QR in the image when it is a payment code of a
 * local rail (Pix, QR Argentina, Bre-B, QR Bolivia); null for any other
 * picture, any other kind of QR, or a phone that cannot read one. */
export async function paymentCodeInImage(uri: string): Promise<string | null> {
  try {
    const RNQRGenerator = (await import('rn-qr-generator')).default;
    const detected = await RNQRGenerator.detect({ uri });
    const value = detected?.values?.[0];
    return typeof value === 'string' && localPaymentQrRoute(value) ? value.trim() : null;
  } catch {
    return null;
  }
}
