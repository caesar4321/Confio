const {readFileSync} = require('fs');
const {resolve} = require('path');

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
