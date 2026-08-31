const {readFileSync} = require('fs');
const {resolve} = require('path');
declare const __dirname: string;

const readScreen = (name: string) =>
  readFileSync(resolve(__dirname, `../${name}`), 'utf8');

describe('Algorand send preparation ownership', () => {
  it.each(['SendToFriendScreen.tsx', 'SendWithAddressScreen.tsx'])(
    'does not prepare while editing inputs in %s',
    screen => {
      const source = readScreen(screen);

      expect(source).not.toContain('prepareSendViaWs');
      expect(source).not.toMatch(/\bprepared:\s*prepared\b/);
    },
  );

  it('prepares once in the processing screen when the user submits', () => {
    const source = readScreen('TransactionProcessingScreen.tsx');

    expect(source).toContain('prepareSendViaWs');
    expect(source).toContain("withTimeout(prepareSendViaWs({");
  });
});

describe('BSC external-send receipt accounting', () => {
  it('propagates the authoritative conversion quote to the success screen', () => {
    const processing = readScreen('TransactionProcessingScreen.tsx');
    const success = readScreen('TransactionSuccessScreen.tsx');

    expect(processing).toContain('(transactionData as any).grossAmount = res?.grossAmount');
    expect(processing).toContain('(transactionData as any).feeAmount = res?.feeAmount');
    expect(processing).toContain('(transactionData as any).netAmount = res?.netAmount');
    expect(success).toContain('Comisión de Confío');
    expect(success).toContain('Comisión de red');
    expect(success).toContain('transactionData.netAmount');
    expect(success).toContain("navigate('SendUsdt'");
    expect(success).toContain('prefilledAddress: transactionData.recipientAddress');
  });
});
