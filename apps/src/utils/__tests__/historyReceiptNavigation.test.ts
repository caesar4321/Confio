const fs = require('fs');
const path = require('path');
import { parse } from '@babel/parser';
import traverse from '@babel/traverse';
import { transformSync } from '@babel/core';
import moment from 'moment';
import { historyReceiptRoute, unifiedTransactionReceipt, transferDirection } from '../transactionReceipt';
import { transactionFriendRoute } from '../transactionFriend';

// Execute the actual route expressions from both screens. This catches omissions
// at navigation, which testing the metadata helper alone would miss.
function screenRoute(screen: string, tx: Record<string, unknown>, type: string) {
  const source = fs.readFileSync(path.join(__dirname, '../../screens', screen + '.tsx'), 'utf8');
  const ast = parse(source, { sourceType: 'module', plugins: ['typescript', 'jsx'] });
  let receiptExpression = '';
  let routeExpression = '';
  traverse(ast, {
    ObjectProperty(p) {
      if (p.node.key.type === 'Identifier' && p.node.key.name === 'receipt') {
        receiptExpression = source.slice(p.node.value.start!, p.node.value.end!);
      }
    },
    CallExpression(p) {
      if (p.node.callee.type === 'Identifier' && p.node.callee.name === 'historyReceiptRoute') {
        routeExpression = source.slice(p.node.start!, p.node.end!);
      }
    },
  });
  expect(receiptExpression).not.toBe('');
  expect(routeExpression).not.toBe('');
  const receipt = new Function('tx', 'unifiedTransactionReceipt', `return ${receiptExpression}`)(tx, unifiedTransactionReceipt);
  const amount = type === 'received' ? '+100' : type === 'sent' ? '-100' : '100';
  const transaction = { ...tx, receipt, type, amount, currency: 'cUSD', status: 'completed', date: tx.createdAt, to: 'Amiga' };
  const scope = {
    transaction, historyReceiptRoute, moment, detailAmount: amount, detailCurrency: 'cUSD',
    contactInfo: { displayName: 'Amiga' }, isStockMovement: false,
    friend: { name: 'Amiga', avatar: 'A' }, friendStatusTier: null, friendIsReferralVerified: false,
    senderStatusTier: null, senderIsReferralVerified: false, recipientStatusTier: null, recipientIsReferralVerified: false,
  };
  const compiled = transformSync(`const result = ${routeExpression};`, {
    configFile: false, babelrc: false, plugins: ['@babel/plugin-transform-typescript'],
  })!.code!;
  return new Function(...Object.keys(scope), `${compiled}; return result;`)(...Object.values(scope));
}

const row = {
  id: '2963', internalId: '12345678-1234-4234-8234-123456789abc',
  createdAt: '2026-08-28T11:17:09Z', direction: 'sent',
  senderUser: { id: '5', phoneKey: '57:3000000000' },
  counterpartyUser: { id: '139', phoneKey: '57:3000000001' },
  feeAmount: '0', feeBps: 0, netAmount: '100',
};

describe('history receipt navigation contract', () => {
  it.each(['sent', 'received', 'unknown'])('preserves metadata through both entrypoints (%s)', direction => {
    const source = { ...row, direction };
    const account = screenRoute('AccountDetailScreen', source, direction);
    const friend = screenRoute('FriendDetailScreen', source, direction);
    for (const route of [account, friend]) {
      expect(route.transactionType).toBe(direction);
      expect(route.transactionData).toMatchObject({
        ...unifiedTransactionReceipt(source), amount: direction === 'received' ? '+100' : direction === 'sent' ? '-100' : '100', currency: 'cUSD', status: 'completed',
      });
      expect(route.transactionData.id).not.toBe(source.id);
    }
    for (const route of [account, friend]) {
      const target = transactionFriendRoute(route.transactionData, true, 'Amiga');
      if (direction === 'unknown') expect(target).toBeNull();
      else expect(target?.friendId).toBe(direction === 'sent' ? '139' : '5');
    }
  });
  it.each(['AccountDetailScreen', 'FriendDetailScreen'])('does not invent metadata in %s', screen => {
    const { transactionData } = screenRoute(screen, { id: '2963' }, 'unknown');
    expect(transactionData.id).toBeUndefined();
    expect(transactionData.timestamp).toBeUndefined();
    expect(transactionData.createdAt).toBeUndefined();
    expect(transactionData.date || undefined).toBeUndefined();
    expect(transactionFriendRoute(transactionData, true, 'Amiga')).toBeNull();
  });
  it('keeps source metadata authoritative even if presentation contains stale fields', () => {
    const route = historyReceiptRoute('sent', unifiedTransactionReceipt(row), {
      amount: '-100', currency: 'cUSD', status: 'completed', id: '2963', timestamp: 'today',
    });
    expect(route.transactionData?.id).toBe(row.internalId);
    expect(route.transactionData?.timestamp).toBe(row.createdAt);
  });
  it.each([undefined, null, '', 'unknown', 'unexpected'])('does not infer received from %s', value => {
    expect(transferDirection(value)).toBe('unknown');
  });
});

it('uses a neutral amount label when direction is unknown', () => {
  const source = fs.readFileSync(path.join(__dirname, '../../screens/TransactionDetailScreen.tsx'), 'utf8');
  const ast = parse(source, { sourceType: 'module', plugins: ['typescript', 'jsx'] });
  let expression = '';
  traverse(ast, { VariableDeclarator(p) {
    if (p.node.id.type === 'Identifier' && p.node.id.name === 'amountLabel') {
      expression = source.slice(p.node.init!.start!, p.node.init!.end!);
    }
  } });
  expect(new Function('currentTx', 'isPaymentDebit', `return ${expression}`)({ type: 'unknown' }, false)).toBe('Monto');
});

function friendRows(rows: Record<string, unknown>[]) {
  const source = fs.readFileSync(path.join(__dirname, '../../screens/FriendDetailScreen.tsx'), 'utf8');
  const ast = parse(source, { sourceType: 'module', plugins: ['typescript', 'jsx'] });
  let expression = '';
  traverse(ast, { VariableDeclarator(p) {
    if (p.node.id.type === 'Identifier' && p.node.id.name === 'formatTransactions' && p.node.init?.type === 'CallExpression') {
      const callback = p.node.init.arguments[0];
      expression = source.slice(callback.start!, callback.end!);
    }
  } });
  const compiled = transformSync(`const format = ${expression}`, {
    configFile: false, babelrc: false, plugins: ['@babel/plugin-transform-typescript'],
  })!.code!;
  return new Function('friendTransactions', 'friend', 'formatTokenLabel', 'unifiedTransactionReceipt', 'transferDirection', 'moment',
    `${compiled}; return format();`)(rows, {name: 'Amiga'}, (x: string) => x, unifiedTransactionReceipt, transferDirection, moment);
}

it('formats unknown transfers without inventing a sender or a direction', () => {
  const [transaction] = friendRows([{...row, direction: null, transactionType: 'send', amount: '100'}]);
  expect(transaction.type).toBe('unknown');
  expect(transaction.from).toBeUndefined();
  expect(transaction.to).toBeUndefined();
});

it('uses the same local calendar date and time, retaining the source timestamp for sorting', () => {
  const timestamp = '2026-08-28T01:17:09Z';
  const [transaction] = friendRows([{...row, createdAt: timestamp, transactionType: 'send'}]);
  expect(transaction.date).toBe(moment(timestamp).format('YYYY-MM-DD'));
  expect(transaction.time).toBe(moment(timestamp).format('HH:mm'));
  expect(transaction.receipt.createdAt).toBe(timestamp);
});

it.each([undefined, null, 'not-a-date'])('keeps unavailable dates safe (%s)', createdAt => {
  const [transaction] = friendRows([{...row, createdAt, transactionType: 'send'}]);
  expect(transaction.date).toBe('');
  expect(transaction.time).toBe('');
});

it.each([
  [{}, 'No disponible'],
  [{createdAt: 'not-a-date'}, 'No disponible'],
  [{date: '2026-08-28', time: '07:17'}, '28/08/2026 • 07:17'],
  [{date: '2026-08-28T11:17:09Z'}, '28/08/2026'],
])('preserves real legacy dates and rejects missing or invalid dates (%j)', (currentTx, expected) => {
  const source = fs.readFileSync(path.join(__dirname, '../../screens/TransactionDetailScreen.tsx'), 'utf8');
  const ast = parse(source, { sourceType: 'module', plugins: ['typescript', 'jsx'] });
  let expression = '';
  traverse(ast, { VariableDeclarator(p) {
    if (p.node.id.type === 'Identifier' && p.node.id.name === 'dateTimeDisplay') {
      expression = source.slice(p.node.init!.start!, p.node.init!.end!);
    }
  } });
  const compiled = transformSync(`const value = ${expression};`, {
    configFile: false, babelrc: false, plugins: ['@babel/plugin-transform-typescript'],
  })!.code!;
  expect(new Function('currentTx', 'moment', `${compiled}; return value;`)(currentTx, moment)).toBe(expected);
});

it('groups unavailable account dates separately, after dated transactions', () => {
  const source = fs.readFileSync(path.join(__dirname, '../../screens/AccountDetailScreen.tsx'), 'utf8');
  const ast = parse(source, { sourceType: 'module', plugins: ['typescript', 'jsx'] });
  let expression = '';
  traverse(ast, { VariableDeclarator(p) {
    if (p.node.id.type === 'Identifier' && p.node.id.name === 'groupedTransactions' && p.node.init?.type === 'CallExpression') {
      const callback = p.node.init.arguments[0];
      expression = source.slice(callback.start!, callback.end!);
    }
  } });
  const compiled = transformSync(`const group = ${expression}`, {
    configFile: false, babelrc: false, plugins: ['@babel/plugin-transform-typescript'],
  })!.code!;
  const rows = [{id: 'missing'}, {id: 'invalid', date: 'not-a-date'}, {id: 'valid', date: '2026-08-28T11:17:09Z'}];
  const groups = new Function('filteredTransactions', 'moment', `${compiled}; return group();`)(rows, moment);
  expect(groups[groups.length - 1]).toEqual({title: 'Fecha no disponible', data: rows.slice(0, 2)});
  expect(groups[0].data).toEqual([rows[2]]);
});
