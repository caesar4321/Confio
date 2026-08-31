const {readFileSync} = require('fs');
const {resolve} = require('path');
declare const __dirname: string;
export {};

const readScreen = (name: string) =>
  readFileSync(resolve(__dirname, `../${name}`), 'utf8');

describe('ramp quote fee hierarchy', () => {
  it('shows the on-ramp gross amount, then the Confío fee, then the final net receipt', () => {
    const source = readScreen('TopUpScreen.tsx');
    const gross = source.indexOf('Monto antes de comisión Confío');
    const fee = source.indexOf('Comisión de Confío', gross);
    const finalReceipt = source.indexOf('styles.quoteFinalLabel', fee);

    expect(gross).toBeGreaterThan(-1);
    expect(fee).toBeGreaterThan(gross);
    expect(finalReceipt).toBeGreaterThan(fee);
    expect(source.slice(finalReceipt, finalReceipt + 150)).toContain('Recibes aprox.');
  });

  it('places the off-ramp final receipt after the Confío fee', () => {
    const source = readScreen('SellScreen.tsx');
    const fee = source.indexOf('Comisión de Confío');
    const finalReceipt = source.indexOf('styles.quoteFinalLabel', fee);

    expect(fee).toBeGreaterThan(-1);
    expect(finalReceipt).toBeGreaterThan(fee);
    expect(source.slice(finalReceipt, finalReceipt + 150)).toContain('Recibes aprox.');
  });

  it('shows authoritative fees on ramp and external-wallet detail receipts', () => {
    const source = readScreen('TransactionDetailScreen.tsx');

    expect(source).toContain('if (isRampReceipt)');
    expect(source).toContain("label: 'Comisión de Confío'");
    expect(source).toContain("label: currentTx.type === 'received' ? 'Monto acreditado' : 'Recibe la billetera'");
    expect(source).toContain('const fee = serverFee(currentTx)');
    expect(source).not.toContain('computeConfioFee(currentTx.amount);\n          items.push({\n            label: currentTx.type');
  });

  it('uses balance-impact amounts on account cards and preserves receipt data', () => {
    const source = readScreen('AccountDetailScreen.tsx');
    const amountMapping = source.slice(
      source.indexOf('amount: isConversion'),
      source.indexOf('// For conversions, show the currency'),
    );

    expect(amountMapping).toContain(': signedBalanceAmount');
    expect(amountMapping).not.toContain('signedRampFiatAmount');
    expect(source).toContain("const signedBalanceAmount = tx.direction === 'received' && tx.netAmount");
    expect(source).toContain("if (type === 'received' && tx.toToken)");
    expect(source).not.toContain("tx.feeAmount && tx.toToken");
    expect(source).toContain('feeAmount: transaction.feeAmount');
    expect(source).toContain('rampFiatAmount: transaction.rampFiatAmount');
    expect(source).toContain('walletAmount: transaction.walletAmount');
    expect(source).toContain('grossAmount: tx.amount');
    expect(source).toContain('amount: detailAmount');
    expect(source).toContain('currency: detailCurrency');
  });
});
