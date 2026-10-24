import { fundingPaymentDetails, sendStage, vexpaySendCopy } from '../vexpayOffRamp';

describe('vexpayOffRamp', () => {
  it('hands the funding path the vouched keys only', () => {
    expect(fundingPaymentDetails({
      depositAddress: '0xabc', network: 'BSC', depositAmountWei: '19820000000000000000', grossDebitAmountWei: '20000000000000000000',
    })).toEqual({
      confioDepositAddress: '0xabc',
      confioDepositNetwork: 'BSC',
      confioDepositAmountWei: '19820000000000000000',
      confioGrossDebitAmountWei: '20000000000000000000',
    });
    expect(fundingPaymentDetails({ depositAddress: '0xabc', network: 'BSC', depositAmountWei: '1' }))
      .not.toHaveProperty('confioGrossDebitAmountWei');
  });

  it('maps phases onto the four-step timeline', () => {
    expect(sendStage({ success: true, status: 'PENDING', phase: 'awaiting_funding' })).toBe(0);
    expect(sendStage({ success: true, status: 'PENDING', phase: 'funding_reported' })).toBe(1);
    expect(sendStage({ success: true, status: 'PROCESSING', phase: 'funded' })).toBe(2);
    expect(sendStage({ success: true, status: 'PROCESSING', phase: 'credit_pending' })).toBe(2);
    expect(sendStage({ success: true, status: 'COMPLETED', phase: 'paid' })).toBe(3);
  });

  it('never shows a failure for money under review', () => {
    const copy = vexpaySendCopy({ success: true, status: 'PROCESSING', phase: 'credit_review', statusDetail: 'needs_review:credit_unknown:500:' });
    expect(copy.title).toBe('Estamos revisando tu envío');
    expect(vexpaySendCopy({ success: true, status: 'FAILED', statusDetail: 'expired_unfunded' }).body)
      .toContain('No se envió nada');
  });
});
