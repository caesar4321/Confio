export type WalletRecoveryFailure = 'missing' | 'unreadable' | 'mismatch' | 'local_corrupt' | 'drive_access' | 'unexpected';

const preserveData = ' No desinstales Confío ni borres los datos de la app. Contáctanos para ayudarte.';
const messages: Record<WalletRecoveryFailure, string> = {
  missing: 'No encontramos un respaldo de tu billetera en este Google Drive. Verifica que sea la cuenta de Google donde guardaste tu respaldo.' + preserveData,
  unreadable: 'Encontramos un respaldo, pero no pudimos leer su contenido o descifrarlo.' + preserveData,
  mismatch: 'Los datos de billetera que pudimos recuperar no corresponden a la billetera registrada en tu cuenta.' + preserveData,
  local_corrupt: 'Los datos de tu billetera en este dispositivo están dañados y no pudimos recuperarlos.' + preserveData,
  drive_access: 'No pudimos acceder a Google Drive para completar la búsqueda de tu respaldo. Revisa tu conexión y los permisos de Drive e inténtalo de nuevo con la misma cuenta de Google.',
  unexpected: 'Ocurrió un error al recuperar tu billetera. Inténtalo de nuevo. Si continúa, contáctanos e indica el código RECOVERY-UNEXPECTED. No desinstales Confío ni borres los datos de la app.',
};

export class WalletRecoveryError extends Error {
  constructor(public readonly code: WalletRecoveryFailure) {
    super(messages[code]);
    this.name = 'WalletRecoveryError';
  }
}

// Classify typed failures only. Never infer a missing backup from arbitrary
// exception text, which may describe a device, storage, or programming error.
export function walletRecoveryMessage(error: unknown): string {
  if (error instanceof WalletRecoveryError) return messages[error.code];
  if (error instanceof Error && error.name === 'GoogleDriveStorageError') {
    return messages.drive_access;
  }
  return messages.unexpected;
}
