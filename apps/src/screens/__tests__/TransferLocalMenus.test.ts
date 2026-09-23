const {readFileSync} = require('fs');
const {resolve} = require('path');
declare const __dirname: string;
export {};

const screen = (name: string) => readFileSync(resolve(__dirname, `../${name}.tsx`), 'utf8');

describe('local transfer menu boundaries', () => {
  it('keeps technical funding/history out of the country sheets', () => {
    const source = screen('TransferScreen');
    expect(source).toContain('¿A dónde quieres enviar?');
    // Enviar only sends; receiving lives on the Recibir screen.
    expect(source).not.toContain('¿Dónde quieres recibir?');
    expect(screen('ReceiveScreen')).toContain('useLocalRailOptions()');
    expect(source).not.toContain('Envíos y conversiones anteriores');
    expect(source).not.toContain('recoveryOptions');
    expect(source).not.toContain('BRIDGE_AVAILABILITY');
    expect(source).not.toContain("navigate('LocalAccountFunding')");
  });

  it('lists a rail the identity blocks, with its own waitlist modal', () => {
    // The rail rows live in the shared hook (Transferir sheets + Recibir).
    const source = readFileSync(resolve(__dirname, '../../hooks/useLocalRailOptions.ts'), 'utf8');
    expect(source).toContain('isIdentityBlocked(method)');
    expect(source).toContain('local_rail_blocked_interest');
    expect(source).toContain('No disponible por ahora para tu nacionalidad');
    expect(source).toContain('showIdentityBlockedInterest(`${method.title} · ${countryName(method.country)}`, stage =>');
  });

  it('shows local rails the same way on Enviar and Recibir', () => {
    // One pattern for both verbs: usable rails inline, the rest behind
    // "Más países", drawn by the same card. They drifted apart once.
    expect(screen('TransferScreen')).toContain('<LocalRailsCard');
    expect(screen('ReceiveScreen')).toContain('<LocalRailsCard');
    expect(screen('TransferScreen')).toContain('<AdvancedCard');
    expect(screen('ReceiveScreen')).toContain('<AdvancedCard');
    // Avanzado lists tokens inline in both directions — no sheet on one side.
    expect(screen('TransferScreen')).not.toContain('¿Qué moneda quieres enviar?');
  });

  it('preserves transfer status and pending confirmation access', () => {
    expect(screen('LocalSendScreen')).toContain("navigate('LocalTransferStatus')");
    expect(screen('LocalTransferStatusScreen')).toContain("navigate('LocalAccountFunding')");
  });
});
