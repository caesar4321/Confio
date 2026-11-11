import {
  heavyFeeNote,
  LocalTransferFee,
  processorFeeDeferred,
  processorFeeIncludes,
  processorFeeView,
  receiptFeeState,
} from '../localTransferFee';

const fee = (overrides: Partial<LocalTransferFee> = {}): LocalTransferFee => ({
  processingUsd: '0.5', networkUsd: '0.75', maintenanceUsd: '0', debtUsd: '0',
  totalUsd: '1.25', deferredUsd: '0', ...overrides,
});
const usd = (value: string) => `US$${Number(value).toFixed(2)}`;

describe('receiptFeeState', () => {
  it('shows a fee as charged only once its collection is confirmed', () => {
    expect(receiptFeeState(fee({ collected: true }), 'completed')).toBe('charged');
    expect(receiptFeeState(fee({ collected: true }), 'refunded')).toBe('charged');
    expect(receiptFeeState(fee({ collected: false }), 'awaiting_wallet_conversion')).toBe('pending');
    expect(receiptFeeState(fee(), 'awaiting_credit')).toBe('pending');
  });

  it('never lists a fee on a transfer that ended without collecting it', () => {
    for (const stage of ['failed', 'refunded', 'completed']) {
      expect(receiptFeeState(fee({ collected: false }), stage)).toBe('hidden');
    }
    expect(receiptFeeState(null, 'completed')).toBe('hidden');
    expect(receiptFeeState(fee({ totalUsd: '0', collected: true }), 'completed')).toBe('hidden');
  });
});

describe('processorFeeView', () => {
  it('shows nothing when no fee applies or the server did not answer', () => {
    expect(processorFeeView(null, 20)).toBeNull();
    expect(processorFeeView(undefined, 20)).toBeNull();
    expect(processorFeeView(fee({ totalUsd: '0' }), 20)).toBeNull();
    expect(processorFeeView(fee({ totalUsd: 'nope' }), 20)).toBeNull();
  });

  it('flags a flat fee that is a large share of a small send', () => {
    // Colombia Bre-B: US$1.25 on US$5 is a quarter of the send.
    expect(processorFeeView(fee(), 5)?.heavyPercent).toBe(25);
    expect(heavyFeeNote(processorFeeView(fee(), '5')!)).toContain('25%');
    // Exactly at the threshold counts; just under does not.
    expect(processorFeeView(fee(), 25)?.heavyPercent).toBe(5);
    expect(processorFeeView(fee(), 26)?.heavyPercent).toBeNull();
    expect(heavyFeeNote(processorFeeView(fee(), 100)!)).toBeNull();
  });

  it('does not judge the share without an amount, or when the fee exceeds it', () => {
    expect(processorFeeView(fee())?.heavyPercent).toBeNull();
    expect(processorFeeView(fee(), '')?.heavyPercent).toBeNull();
    expect(processorFeeView(fee(), 1)?.heavyPercent).toBeNull();
    expect(processorFeeView(fee(), 1.25)?.heavyPercent).toBeNull();
  });

  it('names the account costs that ride on the fee', () => {
    const plain = processorFeeView(fee(), 50)!;
    expect(processorFeeIncludes(plain, usd)).toBeNull();
    const maintenance = processorFeeView(fee({ maintenanceUsd: '0.20', totalUsd: '1.45' }), 50)!;
    expect(processorFeeIncludes(maintenance, usd)).toBe('Incluye US$0.20 de mantenimiento de cuenta.');
    const both = processorFeeView(fee({ maintenanceUsd: '0.20', debtUsd: '0.05', totalUsd: '1.50' }), 50)!;
    expect(processorFeeIncludes(both, usd))
      .toBe('Incluye US$0.20 de mantenimiento de cuenta y US$0.05 de comisiones pendientes.');
    expect(both.total).toBe('1.50');
  });

  it('says what a deposit too small for its fee leaves for later', () => {
    expect(processorFeeDeferred(processorFeeView(fee(), 50)!, usd)).toBeNull();
    const capped = processorFeeView(fee({ totalUsd: '0.10', deferredUsd: '1.15' }))!;
    expect(processorFeeDeferred(capped, usd)).toBe('Quedan US$1.15 de comisión para tu próxima operación.');
  });
});
