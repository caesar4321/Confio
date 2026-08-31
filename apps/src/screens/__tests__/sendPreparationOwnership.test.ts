const {readFileSync} = require('fs');
const {resolve} = require('path');
const {resolveTransferReceiptParticipants} = require('../../utils/tokenDisplay');
const {confirmedReceiptContext} = require('../../utils/fcmData');
declare const __dirname: string;

const readScreen = (name: string) =>
  readFileSync(resolve(__dirname, `../${name}`), 'utf8');

const readService = (name: string) =>
  readFileSync(resolve(__dirname, `../../services/${name}`), 'utf8');

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

describe('BSC external-send fee layout', () => {
  it('constrains and wraps the fee copy inside the Send card', () => {
    const source = readScreen('SendUsdtScreen.tsx');

    expect(source).toMatch(/feeAmountContainer:\s*\{[^}]*flex:\s*1[^}]*minWidth:\s*0[^}]*\}/s);
    expect(source).toMatch(/feeAmount:\s*\{[^}]*flexShrink:\s*1[^}]*textAlign:\s*'right'[^}]*\}/s);
    expect(source).toMatch(/netAmount:\s*\{[^}]*flexShrink:\s*1[^}]*textAlign:\s*'right'[^}]*\}/s);
  });
});

describe('official transfer receipt identities', () => {
  const currentUser = { firstName: 'Julian', lastName: 'Torres', username: 'julian' };

  it.each([
    ['outgoing internal', { type: 'sent', to: 'Ana Pérez' }, { senderName: 'Julian Torres', recipientName: 'Ana Pérez' }],
    ['incoming internal', { type: 'received', from: 'Ana Pérez' }, { senderName: 'Ana Pérez', recipientName: 'Julian Torres' }],
    ['outgoing external', { type: 'sent', recipientAddress: '0x1234567890abcdef1234567890abcdef12345678' }, { senderName: 'Julian Torres', recipientName: '0x123456…12345678' }],
    ['incoming external', { type: 'deposit', senderAddress: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' }, { senderName: 'AAAAAAAA…AAAAAAAA', recipientName: 'Julian Torres' }],
  ])('resolves %s identities', (_label, transaction, expected) => {
    expect(resolveTransferReceiptParticipants(transaction, currentUser)).toMatchObject(expected);
  });

  it('does not mistake the recipient user for the incoming sender', () => {
    expect(resolveTransferReceiptParticipants({
      type: 'received', recipientUser: currentUser,
      counterpartyUser: { firstName: 'Ana', lastName: 'Pérez' },
    }, currentUser)).toMatchObject({ senderName: 'Ana Pérez', recipientName: 'Julian Torres' });
  });

  it('keeps the authenticated recipient authoritative for AccountDetail incoming aliases', () => {
    const ana = { firstName: 'Ana', lastName: 'Pérez', username: 'ana' };
    expect(resolveTransferReceiptParticipants({
      type: 'received', counterpartyUser: ana, recipientUser: ana,
    }, currentUser)).toMatchObject({
      senderName: 'Ana Pérez', recipientName: 'Julian Torres',
      senderUsername: 'ana', recipientUsername: 'julian',
    });
  });

  it('keeps business identity details aligned with the displayed business name', () => {
    expect(resolveTransferReceiptParticipants({
      type: 'sent', senderBusiness: { name: 'Café Confío', username: 'cafeconfio' },
      to: 'Ana Pérez',
    }, currentUser)).toMatchObject({
      senderName: 'Café Confío', senderUsername: 'cafeconfio', recipientName: 'Ana Pérez',
    });
  });

  it('keeps recipient business identity details aligned on incoming transfers', () => {
    expect(resolveTransferReceiptParticipants({
      type: 'received', from: 'Ana Pérez',
      recipientBusiness: { name: 'Café Confío', username: 'cafeconfio' },
    }, currentUser)).toMatchObject({
      senderName: 'Ana Pérez', recipientName: 'Café Confío', recipientUsername: 'cafeconfio',
    });
  });

  it('ignores a generic sender placeholder and resolves the authenticated sender', () => {
    expect(resolveTransferReceiptParticipants({
      type: 'sent', senderName: 'Billetera externa', to: 'Ana Pérez',
    }, currentUser)).toMatchObject({ senderName: 'Julian Torres', recipientName: 'Ana Pérez' });
  });

  it('ignores a generic receiver placeholder and resolves the external address', () => {
    expect(resolveTransferReceiptParticipants({
      type: 'sent', recipientName: 'Usuario',
      recipientAddress: '0x1234567890abcdef1234567890abcdef12345678',
    }, currentUser)).toMatchObject({ recipientName: '0x123456…12345678' });
  });

  it('ignores the generated external sender placeholder when the full address is available', () => {
    expect(resolveTransferReceiptParticipants({
      type: 'received', senderName: 'Externo (ABCD...WXYZ)',
      senderAddress: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
    }, currentUser)).toMatchObject({ senderName: 'AAAAAAAA…AAAAAAAA' });
  });

  it('prefers a full recipient address over a lossy address display value', () => {
    expect(resolveTransferReceiptParticipants({
      type: 'sent', to: '0x12345678...',
      recipientAddress: '0x1234567890abcdef1234567890abcdef12345678',
    }, currentUser)).toMatchObject({ recipientName: '0x123456…12345678' });
  });

  it('abbreviates full wallet addresses supplied through from and to aliases', () => {
    const address = '0x1234567890abcdef1234567890abcdef12345678';
    expect(resolveTransferReceiptParticipants(
      { type: 'transfer', from: address, to: address }, currentUser,
    )).toMatchObject({ senderName: '0x123456…12345678', recipientName: '0x123456…12345678' });
  });

  it('preserves explicit identities when direction is ambiguous', () => {
    expect(resolveTransferReceiptParticipants(
      { type: 'transfer', from: 'Carlos', to: 'María', amount: '5' }, currentUser,
    )).toMatchObject({ senderName: 'Carlos', recipientName: 'María', isOutgoing: false, isIncoming: false });
  });

  it.each([
    [{ type: 'received', amount: '-5', from: 'Ana' }, { isIncoming: true, isOutgoing: false }],
    [{ type: 'sent', amount: '+5', to: 'Ana' }, { isIncoming: false, isOutgoing: true }],
  ])('keeps explicit direction authoritative over display amount sign', (transaction, expected) => {
    expect(resolveTransferReceiptParticipants(transaction, currentUser)).toMatchObject(expected);
  });

  it('uses a recognized direction field when type is only the generic transfer category', () => {
    expect(resolveTransferReceiptParticipants({
      type: 'transfer', direction: 'received', from: 'Ana Pérez', amount: '5',
    }, currentUser)).toMatchObject({
      senderName: 'Ana Pérez', recipientName: 'Julian Torres', isIncoming: true, isOutgoing: false,
    });
  });

  it.each([
    [{ amount: '-5', to: 'Ana Pérez' }, { senderName: 'Julian Torres', recipientName: 'Ana Pérez', isOutgoing: true }],
    [{ amount: '+5', from: 'Ana Pérez' }, { senderName: 'Ana Pérez', recipientName: 'Julian Torres', isIncoming: true }],
  ])('uses the amount sign only when no explicit direction is available', (transaction, expected) => {
    expect(resolveTransferReceiptParticipants(transaction, currentUser)).toMatchObject(expected);
  });

  it('keeps a lossy wallet identity when no full address is available', () => {
    expect(resolveTransferReceiptParticipants({
      type: 'sent', to: '0x12345678...',
    }, currentUser)).toMatchObject({ recipientName: '0x12345678...' });
  });

  it('falls back to Usuario only when neither side has an identity', () => {
    expect(resolveTransferReceiptParticipants({}, null)).toMatchObject({
      senderName: 'Usuario', recipientName: 'Usuario',
    });
  });

  it('resolves direction-aware usernames and authenticated phone details', () => {
    const authenticated = {
      ...currentUser, phoneCountry: '51', phoneNumber: '999888777',
    };
    expect(resolveTransferReceiptParticipants({
      type: 'received', counterpartyUser: { firstName: 'Ana', username: 'ana' },
    }, authenticated)).toMatchObject({
      senderUsername: 'ana', recipientUsername: 'julian', recipientPhone: '51:999888777',
    });
  });
});

describe('push-opened official receipt context', () => {
  it.each([
    ['SEND_SENT', 'sent'],
    ['SEND_RECEIVED', 'received'],
  ])('preserves the %s viewer direction', (notificationType, direction) => {
    expect(confirmedReceiptContext({}, notificationType)).toMatchObject({ direction });
  });

  it('preserves snake-case external-side addresses from the FCM payload', () => {
    expect(confirmedReceiptContext({
      sender_address: 'sender-wallet', recipient_address: 'recipient-wallet',
    }, 'SEND_RECEIVED')).toEqual({
      direction: 'received',
      senderAddress: 'sender-wallet',
      recipientAddress: 'recipient-wallet',
    });
  });

  it.each([
    [{ from_address: 'snake-sender', to_address: 'snake-recipient' }, 'snake-sender', 'snake-recipient'],
    [{ fromAddress: 'camel-sender', toAddress: 'camel-recipient' }, 'camel-sender', 'camel-recipient'],
  ])('normalizes alternate FCM address aliases', (payload, senderAddress, recipientAddress) => {
    expect(confirmedReceiptContext(payload, 'SEND_RECEIVED')).toMatchObject({
      senderAddress, recipientAddress,
    });
  });

  it('wires normalized direction and addresses into direct receipt navigation', () => {
    const source = readService('pushNotificationService.ts');
    expect(source).toContain('confirmedReceiptContext(transactionData, notification_type)');
    expect(source).toContain('type: receiptDirection');
    expect(source).toContain('senderAddress,');
    expect(source).toContain('recipientAddress,');
    expect(source).toContain("screen: 'TransactionReceipt'");
  });
});

describe('official receipt screen integration', () => {
  it('renders a recoverable message when the route has no transaction', () => {
    const source = readScreen('TransactionReceiptScreen.tsx');
    expect(source).toContain('if (!transaction)');
    expect(source).toContain('No se encontró la transacción.');
  });

  it('passes direction-aware participant names and details to the receipt view', () => {
    const source = readScreen('TransactionReceiptScreen.tsx');
    expect(source).toContain('resolveTransferReceiptParticipants(transaction, userProfile)');
    expect(source).toContain('senderName = transferParticipants.senderName');
    expect(source).toContain('recipientName = transferParticipants.recipientName');
    expect(source).toContain('const sUsername = transferParticipants.senderUsername');
    expect(source).toContain('const rUsername = transferParticipants.recipientUsername');
  });
});
