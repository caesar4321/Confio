import { WalletRecoveryError, walletRecoveryMessage } from '../walletRecoveryErrors';

describe('wallet recovery guidance', () => {
  it.each([
    ['missing', 'No encontramos un respaldo'],
    ['unreadable', 'no pudimos leer su contenido o descifrarlo'],
    ['mismatch', 'no corresponden a la billetera registrada'],
    ['drive_access', 'misma cuenta de Google'],
    ['unexpected', 'RECOVERY-UNEXPECTED'],
    ['local_corrupt', 'este dispositivo están dañados'],
  ] as const)('maps %s to specific guidance', (code, text) => {
    expect(walletRecoveryMessage(new WalletRecoveryError(code))).toContain(text);
  });

  it('preserves Drive access failures without claiming the backup is missing', () => {
    const error = new Error('private provider diagnostic');
    error.name = 'GoogleDriveStorageError';
    expect(walletRecoveryMessage(error)).toContain('permisos de Drive');
    expect(walletRecoveryMessage(error)).not.toContain('private provider diagnostic');
  });

  it('does not classify arbitrary exception text as a missing backup or network failure', () => {
    expect(walletRecoveryMessage(new Error('backup missing timeout'))).toContain('RECOVERY-UNEXPECTED');
    expect(walletRecoveryMessage(null)).toContain('RECOVERY-UNEXPECTED');
  });

  it('does not expose internal diagnostics from typed error subclasses', () => {
    const error = new WalletRecoveryError('local_corrupt');
    error.message = 'internal storage alias and diagnostic';
    expect(walletRecoveryMessage(error)).toContain('este dispositivo están dañados');
    expect(walletRecoveryMessage(error)).not.toContain('internal storage');
  });
});
