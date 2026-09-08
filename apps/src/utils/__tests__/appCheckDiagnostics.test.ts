import { appCheckDiagnosticCode } from '../appCheckDiagnostics';

it('discards private native details and only emits fixed categories', () => {
  expect(appCheckDiagnosticCode('app attestation failed https://private/token')).toBe('attestation_rejected');
  expect(appCheckDiagnosticCode('Network failed secret@example.com')).toBe('network_error');
  expect(appCheckDiagnosticCode('secret@example.com')).toBe('unknown');
  expect(appCheckDiagnosticCode(undefined)).toBe('unknown');
});
