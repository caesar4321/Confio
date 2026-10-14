const fs = require('fs');
const path = require('path');
import { parse } from '@babel/parser';
import traverse from '@babel/traverse';
import { transformSync } from '@babel/core';
import * as routes from '../transactionRoutes';

const uuid = '12345678-1234-4234-8234-123456789abc';
function evaluate(expression: string, scope: Record<string, unknown>) {
  const compiled = transformSync(`const result = ${expression}`, {
    configFile: false, babelrc: false, plugins: ['@babel/plugin-transform-typescript'],
  })!.code!;
  return new Function(...Object.keys(scope), `${compiled}; return result;`)(...Object.values(scope));
}
const source = fs.readFileSync(path.join(__dirname, '../../screens/TransactionDetailScreen.tsx'), 'utf8');
const ast = () => parse(source, {sourceType: 'module', plugins: ['typescript', 'jsx']});

it('both detail-screen receipt buttons preserve refreshed values over the stale route', () => {
  const expressions: string[] = [];
  traverse(ast(), {CallExpression(p) {
    if (p.node.callee.type === 'Identifier' && p.node.callee.name === 'transactionReceiptRoute') {
      expressions.push(source.slice(p.node.start!, p.node.end!));
    }
  }});
  expect(expressions).toHaveLength(2);
  const currentTx = {internalId: uuid, type: 'payment', amount: '-100', feeAmount: '0.9',
    status: 'confirmed', createdAt: '2026-08-28T11:17:09Z', senderName: 'Pagador', recipientName: 'Comercio'};
  for (const expression of expressions) {
    const route = evaluate(expression, {...routes, currentTx, resolvedInternalId: uuid,
      transactionData: {internalId: uuid, amount: '-90', feeAmount: '0', status: 'pending', createdAt: '2026-08-28T11:00:00Z'}});
    expect(route.transaction).toMatchObject(currentTx);
  }
});

it.each([
  ['payment', {amount: '-100'}, '-100'],
  ['payment', {notification_type: 'PAYMENT_SENT'}, '-100'],
  ['payment', {notification_type: 'PAYMENT_RECEIVED'}, '+100'],
  ['sent', {}, '-100'],
  ['received', {}, '+100'],
])('a fetched %s keeps the viewer perspective (%j)', (resolvedType, transactionData, expected) => {
  let expression = '';
  traverse(ast(), {AssignmentExpression(p) {
    if (p.node.left.type !== 'Identifier' || p.node.left.name !== 'txData' || p.node.right.type !== 'ObjectExpression') return;
    const amount = p.node.right.properties.find((v: any) => v.key?.name === 'amount') as any;
    if (amount) expression = source.slice(amount.value.start, amount.value.end);
  }});
  expect(expression).not.toBe('');
  expect(evaluate(expression, {...routes, resolvedType, transactionData, tx: {amount: '100'}})).toBe(expected);
});

it('carries the fetched source timestamp into a shared receipt when the route omitted it', () => {
  let expression = '';
  traverse(ast(), {AssignmentExpression(p) {
    if (p.node.left.type === 'Identifier' && p.node.left.name === 'txData' && p.node.right.type === 'ObjectExpression') {
      expression = source.slice(p.node.right.start!, p.node.right.end!);
    }
  }});
  const timestamp = '2026-08-28T11:17:09Z';
  const current = evaluate(expression, {...routes, resolvedType: 'payment', transactionData: {amount: '-100'},
    tx: {amount: '100', createdAt: timestamp, internalId: uuid, tokenType: 'CUSD', status: 'CONFIRMED'},
    moment: require('moment'), isInvite: false, claimedFromRoute: false, revertedFromRoute: false});
  expect(routes.transactionReceiptRoute({transaction: current, type: 'payment'}).transaction).toMatchObject({
    amount: '-100', createdAt: timestamp, date: timestamp, status: 'confirmed',
  });
});

it.each(['TransactionSuccessScreen', 'PaymentSuccessScreen'])('%s shares the latest known server status', screen => {
  const code = fs.readFileSync(path.join(__dirname, '../../screens', screen + '.tsx'), 'utf8');
  const parsed = parse(code, {sourceType: 'module', plugins: ['typescript', 'jsx']});
  const expressions: string[] = [];
  traverse(parsed, {CallExpression(p) {
    if (p.node.callee.type === 'Identifier' && ['transactionReceiptRoute', 'paymentSuccessDetailRoute'].includes(p.node.callee.name)) {
      expressions.push(code.slice(p.node.start!, p.node.end!));
    }
  }});
  expect(expressions.length).toBeGreaterThan(0);
  for (const status of ['CONFIRMED', 'FAILED']) {
    for (const expression of expressions) {
      const result = evaluate(expression, {...routes, settledStatus: status, userProfile: undefined, profileData: undefined,
        transactionData: {internalId: uuid, status: 'SUBMITTED', type: 'payment', amount: '100', currency: 'CUSD', merchant: 'Comercio'}});
      expect((result.transaction || result.transactionData).status).toBe(status);
    }
  }
});

it('notification entrypoints use operation timestamps ahead of notification delivery', () => {
  const code = fs.readFileSync(path.join(__dirname, '../../screens/NotificationScreen.tsx'), 'utf8');
  const parsed = parse(code, {sourceType: 'module', plugins: ['typescript', 'jsx']});
  const expressions: string[] = [];
  traverse(parsed, {
    ObjectProperty(p) {
      if (p.node.key.type === 'Identifier' && p.node.key.name === 'createdAt') {
        const expression = code.slice(p.node.value.start!, p.node.value.end!);
        if (expression.includes('fullData') || expression.includes('notification.')) expressions.push(expression);
      }
    },
    VariableDeclarator(p) {
      if (p.node.id.type === 'Identifier' && p.node.id.name === 'createdAt' && p.node.init) expressions.push(code.slice(p.node.init.start!, p.node.init.end!));
    },
  });
  expect(expressions.length).toBeGreaterThanOrEqual(2);
  const timestamp = '2026-08-28T11:17:09Z';
  for (const expression of expressions) {
    expect(evaluate(expression, {...routes, fullData: {created_at: timestamp}, notification: {createdAt: '2026-10-11T11:00:00Z'}})).toBe(timestamp);
  }
});

it.each(['CUSD_PLUS', 'USDT', 'CONFIO'])('preserves payroll notification token_type %s', token => {
  const code = fs.readFileSync(path.join(__dirname, '../../screens/NotificationScreen.tsx'), 'utf8');
  const parsed = parse(code, {sourceType: 'module', plugins: ['typescript', 'jsx']});
  let expression = '';
  traverse(parsed, {CallExpression(p) {
    if (p.node.callee.type === 'Identifier' && p.node.callee.name === 'transactionReceiptRoute') expression = code.slice(p.node.start!, p.node.end!);
  }});
  const result = evaluate(expression, {...routes, id: uuid, isReceived: true,
    employeeNameResolved: 'Empleado', employeeUsernameResolved: 'empleado', employeePhoneResolved: '',
    currentUserName: 'Empresa', profileData: undefined, notificationCreatedAt: undefined,
    data: {token_type: token, amount: '100', created_at: '2026-08-28T11:17:09Z', business_name: 'Empresa'}});
  expect(result.transaction.currency).toBe(token);
});
