import React from 'react';
import renderer, { act } from 'react-test-renderer';
import FeatherGlyphs from 'react-native-vector-icons/glyphmaps/Feather.json';

// The Feather component ships ESM; the glyph NAMES come from its glyphmap
// JSON below, which is what this suite actually checks.
jest.mock('react-native-vector-icons/Feather', () => 'Icon');

jest.mock('../../../config/theme', () => ({
  colors: {
    primaryDark: '#10B981',
    primaryLight: '#D1FAE5',
    primarySoft: '#ECFDF5',
    offRampIcon: '#F59E0B',
    offRampLight: '#FEF3C7',
    warningLight: '#FEF3C7',
    danger: '#EF4444',
    dangerLight: '#FEE2E2',
    secondary: '#8B5CF6',
    violetLight: '#EDE9FE',
    accent: '#3B82F6',
    infoLight: '#DBEAFE',
    neutralDark: '#F3F4F6',
    background: '#FFFFFF',
    white: '#FFFFFF',
    text: { primary: '#1F2937', secondary: '#6B7280' },
  },
}));

import { CUSTOM_GLYPHS } from '../glyphs';
import { IconChip } from '../IconChip';
import { localTransferVisual, notificationVisual, transactionVisual, TONES } from '../vocabulary';

const NOTIFICATION_TYPES = [
  'LOCAL_TRANSFER_UPDATED', 'SEND_RECEIVED', 'SEND_SENT', 'SEND_FROM_EXTERNAL', 'INVITE_RECEIVED',
  'SEND_INVITATION_SENT', 'SEND_INVITATION_CLAIMED', 'SEND_INVITATION_EXPIRED', 'PAYMENT_RECEIVED',
  'PAYMENT_SENT', 'INVOICE_PAID', 'PAYROLL_RECEIVED', 'PAYROLL_SENT', 'CONVERSION_COMPLETED',
  'CONVERSION_FAILED', 'USDC_DEPOSIT_PENDING', 'USDC_DEPOSIT_COMPLETED', 'USDC_DEPOSIT_FAILED',
  'USDC_WITHDRAWAL_PENDING', 'USDC_WITHDRAWAL_COMPLETED', 'USDC_WITHDRAWAL_FAILED', 'RAMP_PENDING',
  'RAMP_PROCESSING', 'RAMP_COMPLETED', 'RAMP_FAILED', 'ACCOUNT_VERIFIED', 'SECURITY_ALERT',
  'NEW_LOGIN', 'BUSINESS_EMPLOYEE_ADDED', 'BUSINESS_EMPLOYEE_REMOVED', 'BUSINESS_PERMISSION_CHANGED',
  'ACHIEVEMENT_EARNED', 'REFERRAL_FRIEND_JOINED', 'REFERRAL_FIRST_TRANSACTION',
  'REFERRAL_ACTION_REMINDER', 'REFERRAL_EVENT_TOP_UP', 'REFERRAL_EVENT_CONVERSION',
  'REFERRAL_EVENT_SEND', 'REFERRAL_EVENT_PAYMENT', 'REFERRAL_REWARD_READY',
  'REFERRAL_REWARD_CLAIMED', 'PROMOTION', 'SYSTEM', 'ANNOUNCEMENT', 'PRESALE_PURCHASE_CONFIRMED',
  'PRESALE_AVAILABLE',
];

const TRANSACTION_KINDS = [
  'received', 'sent', 'send', 'local_transfer', 'payment', 'payroll', 'humanitarian', 'exchange',
  'conversion', 'ramp', 'reward', 'presale', 'stocks', 'deposit', 'withdrawal',
];

const everyVisual = () => [
  ...NOTIFICATION_TYPES.map(type => notificationVisual(type)),
  ...['awaiting_credit', 'completed', 'refunded', 'failed', 'needs_review'].flatMap(stage =>
    [true, false].map(incoming => localTransferVisual(stage, incoming))),
  ...TRANSACTION_KINDS.flatMap(kind => [true, false].map(incoming => transactionVisual(kind, incoming))),
];

describe('the icon vocabulary', () => {
  it('only names glyphs that exist — a typo would render an empty chip', () => {
    const unknown = everyVisual()
      .map(visual => visual.glyph)
      .filter(glyph => !CUSTOM_GLYPHS[glyph] && !(glyph in FeatherGlyphs));
    expect(unknown).toEqual([]);
  });

  it('covers every notification type the server can send', () => {
    const fallback = notificationVisual('A_TYPE_SHIPPED_LATER');
    expect(fallback.glyph).toBe('bell');
    NOTIFICATION_TYPES.forEach(type => {
      expect(notificationVisual(type)).not.toEqual(fallback);
    });
  });

  it('says direction in the color and category in the glyph', () => {
    // Same event, opposite directions: one glyph, two colors.
    expect(notificationVisual('PAYMENT_SENT').glyph).toBe(notificationVisual('PAYMENT_RECEIVED').glyph);
    expect(notificationVisual('PAYMENT_RECEIVED').color).toBe(TONES.moneyIn.color);
    expect(notificationVisual('PAYMENT_SENT').color).toBe(TONES.moneyOut.color);
    expect(transactionVisual('payroll', true).color).toBe(TONES.moneyIn.color);
    expect(transactionVisual('payroll', false).color).toBe(TONES.moneyOut.color);
  });

  it('keeps the two lists speaking the same language', () => {
    expect(transactionVisual('conversion', false).glyph).toBe(notificationVisual('CONVERSION_COMPLETED').glyph);
    expect(transactionVisual('ramp', true).glyph).toBe(notificationVisual('RAMP_COMPLETED').glyph);
    expect(transactionVisual('payment', true).glyph).toBe(notificationVisual('PAYMENT_RECEIVED').glyph);
  });

  it('gives a local transfer its own glyph instead of the default arrow', () => {
    expect(transactionVisual('local_transfer', false).glyph).toBe('bank');
    expect(transactionVisual('local_transfer', true).color).toBe(TONES.moneyIn.color);
    expect(transactionVisual('stocks', false).glyph).toBe('trending-up');
    // An unmapped kind still has to render something sane.
    expect(transactionVisual('a_kind_shipped_later', true).glyph).toBe('arrow-down');
    // Deep links from notifications open the detail screen with these names.
    expect(transactionVisual('send', false)).toEqual(transactionVisual('sent', false));
    expect(transactionVisual('deposit', true).glyph).toBe('coin');
    expect(transactionVisual('withdrawal', false).glyph).toBe('coin');
  });

  it('never badges an outgoing row, where ink would read as a blob', () => {
    const outgoing = [
      notificationVisual('SEND_SENT'), notificationVisual('PAYMENT_SENT'),
      notificationVisual('PAYROLL_SENT'), notificationVisual('USDC_WITHDRAWAL_COMPLETED'),
      ...TRANSACTION_KINDS.map(kind => transactionVisual(kind, false)),
    ];
    outgoing.forEach(visual => expect(visual.badge).toBeUndefined());
  });

  it('leaves state to the badge, not to a second glyph', () => {
    // Every ramp state is the same card; only the badge and tint move.
    const ramps = ['RAMP_PENDING', 'RAMP_PROCESSING', 'RAMP_COMPLETED', 'RAMP_FAILED']
      .map(type => notificationVisual(type));
    expect(new Set(ramps.map(r => r.glyph))).toEqual(new Set(['card']));
    expect(ramps.map(r => r.badge)).toEqual(['pending', 'pending', 'done', 'failed']);
  });
});

describe('local transfer stages', () => {
  it('separates the four states a transfer can end in', () => {
    expect(localTransferVisual('completed').badge).toBe('done');
    expect(localTransferVisual('refunded').badge).toBe('returned');
    expect(localTransferVisual('failed').badge).toBe('failed');
    expect(localTransferVisual('needs_review').badge).toBe('review');
  });

  it('reads every non-terminal stage as in flight, including unknown ones', () => {
    expect(localTransferVisual('awaiting_credit').badge).toBe('pending');
    expect(localTransferVisual('paying_out').badge).toBe('pending');
    expect(localTransferVisual('a_stage_shipped_later').badge).toBe('pending');
    expect(localTransferVisual(undefined).badge).toBe('pending');
  });

  it('marks an arrived incoming transfer as money in, not just finished', () => {
    expect(localTransferVisual('completed', true).badge).toBe('incoming');
    // Direction must not soften a failure into an arrival.
    expect(localTransferVisual('failed', true).badge).toBe('failed');
  });
});

describe('IconChip', () => {
  const render = (element: React.ReactElement) => {
    let root: renderer.ReactTestRenderer;
    act(() => { root = renderer.create(element); });
    return root!.toJSON() as any;
  };
  const styleOf = (node: any) => Object.assign({}, ...[].concat(node?.props?.style || []));

  it('rings the badge in the row color it sits on', () => {
    const tree = render(<IconChip visual={localTransferVisual('completed')} ringColor="#ECFDF5" />);
    const badge = tree.children.map(styleOf).find((style: any) => style.borderColor);
    expect(badge.borderColor).toBe('#ECFDF5');
    expect(badge.backgroundColor).toBe('#10B981');
    // The chip tint has to stay distinct from the unread row it sits on.
    expect(styleOf(tree).backgroundColor).toBe('#D1FAE5');
  });

  it('draws a circle for notifications and a squircle for the ledger', () => {
    expect(styleOf(render(<IconChip visual={transactionVisual('sent', false)} />)).borderRadius).toBe(20);
    expect(styleOf(render(<IconChip visual={transactionVisual('sent', false)} radius={12} />)).borderRadius).toBe(12);
  });

  it('renders a bare glyph with no badge when there is no state to show', () => {
    const tree = render(<IconChip visual={notificationVisual('ACHIEVEMENT_EARNED')} />);
    expect(tree.children.map(styleOf).some((style: any) => style.borderColor)).toBe(false);
  });
});
