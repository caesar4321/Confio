import {gql} from '@apollo/client';
import {secureRandomBytes} from '../setup/entropyGuard';
import {credentialStorage} from './credentialStorage';

export const STEREUM_QR_AVAILABILITY = gql`query StereumQrAvailability {
  stereumQrAvailability { enabled canPay pendingRequestId }
}`;
export const DECODE_STEREUM_QR = gql`mutation DecodeStereumQr($requestId: UUID!, $payload: String!) {
  decodeStereumQr(requestId: $requestId, payload: $payload) {
    requestId recipientName bankName accountLast4 amount fixedAmount currency expiresOn
  }
}`;
export const PAY_STEREUM_QR = gql`mutation PayStereumQr($requestId: UUID!, $decodeRequestId: UUID!, $amount: String!) {
  payStereumQr(requestId: $requestId, decodeRequestId: $decodeRequestId, amount: $amount) { requestId status }
}`;
export const STEREUM_QR_PAYMENT = gql`query StereumQrPayment($requestId: UUID!) {
  stereumQrPayment(requestId: $requestId) { requestId status }
}`;
export interface QrPreview {
  requestId: string; recipientName: string; bankName: string; accountLast4: string;
  amount: string; fixedAmount: boolean; currency: string; expiresOn: string;
}
export interface QrPayment {requestId: string; status: string}
export const qrRequestId = () => {
  const bytes = secureRandomBytes(16, 'a QR payment request');
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
};
const key = (account: string) => `confio.stereum.qr.pending.${account}`;
export const readPendingQr = async (account: string) => {
  const bytes = await credentialStorage.retrieveSecretStrict(key(account));
  if (!bytes) return null;
  const id = new TextDecoder().decode(bytes);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) throw new Error('Referencia de pago guardada inválida. Contacta soporte.');
  return id;
};
export const savePendingQr = (account: string, id: string) => credentialStorage.storeSecret(key(account), new TextEncoder().encode(id));
export const clearPendingQr = (account: string) => credentialStorage.deleteSecret(key(account));
export const validBobAmount = (amount: string) => /^\d+([.,]\d{1,2})?$/.test(amount)
  && Number(amount.replace(',', '.')) >= 1 && Number(amount.replace(',', '.')) <= 69000;
