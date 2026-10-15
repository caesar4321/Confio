/**
 * A screenshot of a sign-in error is often all support ever gets. "Intenta
 * nuevamente" looks the same for a Drive timeout, a refused token and a
 * partial listing; the support code does not.
 */
import { GoogleDriveStorageError } from '../googleDriveStorage';
import { withSupportCode, walletRecoveryMessage } from '../walletRecoveryErrors';

describe('withSupportCode', () => {
  it('puts a Drive failure\'s code under the message the user reads', () => {
    const timeout = new GoogleDriveStorageError('list', 0, 'request_timeout');

    expect(withSupportCode(timeout.message, timeout)).toBe(
      'No pudimos completar la operación de Google Drive (list). Intenta nuevamente.'
      + '\n\nCódigo de soporte: DRIVE-0-REQUEST_TIMEOUT',
    );
  });

  it('tells apart failures whose messages are identical', () => {
    const timeout = new GoogleDriveStorageError('list', 0, 'request_timeout');
    const partial = new GoogleDriveStorageError('list', 0, 'incomplete_listing');
    const serverError = new GoogleDriveStorageError('list', 503);

    expect(timeout.message).toBe(partial.message);
    expect(partial.message).toBe(serverError.message);
    const shown = [timeout, partial, serverError].map(error => withSupportCode(error.message, error));
    expect(new Set(shown).size).toBe(3);
  });

  it('keeps the code when the message is replaced by recovery guidance', () => {
    const timeout = new GoogleDriveStorageError('list', 0, 'request_timeout');

    expect(withSupportCode(walletRecoveryMessage(timeout), timeout))
      .toContain('Código de soporte: DRIVE-0-REQUEST_TIMEOUT');
  });

  it('leaves errors without a code untouched', () => {
    expect(withSupportCode('Cancelaste el inicio de sesión con Google.', new Error('x')))
      .toBe('Cancelaste el inicio de sesión con Google.');
  });

  it('never repeats a code the message already carries', () => {
    const timeout = new GoogleDriveStorageError('list', 0, 'request_timeout');
    const once = withSupportCode(timeout.message, timeout);

    expect(withSupportCode(once, timeout)).toBe(once);
  });

  it('refuses a code that is not the sanitized shape', () => {
    // Codes are built from status and Drive's reason, reduced to [A-Z0-9_-].
    // Anything else did not come from there and is not shown.
    const forged = { supportCode: 'call +504 9999-9999 now' };

    expect(withSupportCode('Error', forged)).toBe('Error');
  });
});
