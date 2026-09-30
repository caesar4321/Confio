export {};

const {readFileSync} = require('fs');
const {resolve} = require('path');
declare const __dirname: string;

describe('Unpaid recharge resume wiring', () => {
  const source = readFileSync(resolve(__dirname, '../TopUpScreen.tsx'), 'utf8');
  const branch = source.slice(source.indexOf("if (result?.nextStep === 'resume_order'"),
    source.indexOf('if (!result?.success || !result?.orderId)'));

  it('offers recovery before treating the refused creation as a generic failure', () => {
    expect(branch).toContain('Ver recarga pendiente');
    expect(branch).toContain("navigation.replace('RampInstructions'");
    expect(branch).toContain('return;');
    expect(branch).not.toContain('placeOrder(');
  });

  it('resumes the original order and currency, not the new quote or a stale QR', () => {
    for (const field of ['orderId', 'countryCode', 'fiatCurrency', 'paymentMethodCode', 'paymentMethodDisplay', 'destination']) {
      expect(branch).toContain(`result.${field}`);
    }
    expect(branch).not.toContain('selectedMethod');
    expect(branch).not.toContain('paymentDetails:');
    expect(branch).not.toContain('nextActionUrl:');
    expect(branch).not.toContain('amountOut:');
  });

  it('requests the existing destination on both creation mutations', () => {
    const mutations = readFileSync(resolve(__dirname, '../../apollo/mutations.ts'), 'utf8');
    for (const name of ['CREATE_RAMP_ORDER', 'CREATE_RAMP_ORDER_SAVINGS']) {
      expect(mutations.split(`export const ${name} = gql\``)[1].split('`;')[0]).toMatch(/paymentDetails\s+destination/);
    }
  });
});
