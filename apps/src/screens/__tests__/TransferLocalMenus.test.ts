const {readFileSync} = require('fs');
const {resolve} = require('path');
declare const __dirname: string;
export {};

const screen = (name: string) => readFileSync(resolve(__dirname, `../${name}.tsx`), 'utf8');

describe('local transfer menu boundaries', () => {
  it('keeps technical funding/history out of the country sheets', () => {
    const source = screen('TransferScreen');
    expect(source).toContain('¿A dónde quieres enviar?');
    expect(source).toContain('¿Dónde quieres recibir?');
    expect(source).not.toContain('Envíos y conversiones anteriores');
    expect(source).not.toContain('recoveryOptions');
    expect(source).not.toContain('BRIDGE_AVAILABILITY');
    expect(source).not.toContain("navigate('LocalAccountFunding')");
  });

  it('preserves transfer status and pending confirmation access', () => {
    expect(screen('LocalSendScreen')).toContain("navigate('LocalTransferStatus')");
    expect(screen('LocalTransferStatusScreen')).toContain("navigate('LocalAccountFunding')");
  });
});
