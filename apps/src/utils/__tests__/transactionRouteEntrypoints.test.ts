const fs = require('fs');
const path = require('path');
import { parse } from '@babel/parser';
import traverse from '@babel/traverse';

// Catch future entrypoints that bypass normalization, including nested push navigation.
it('routes every transaction detail and receipt entrypoint through an adapter', () => {
  const root = path.join(__dirname, '../..');
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory() && entry.name !== '__tests__') walk(file);
      else if (entry.isFile() && /\.tsx?$/.test(file)) files.push(file);
    }
  };
  walk(path.join(root, 'screens'));
  walk(path.join(root, 'services'));
  const seen = new Set<string>();
  const bypasses: string[] = [];
  const adapters = new Set(['transactionDetailRoute', 'transactionReceiptRoute', 'historyReceiptRoute', 'unifiedDetailRoute', 'paymentSuccessDetailRoute']);
  const unwrap = (node: any): any => node?.type === 'TSAsExpression' ? unwrap(node.expression) : node;
  for (const file of files) {
    const source = fs.readFileSync(file, 'utf8');
    if (!source.includes('TransactionDetail') && !source.includes('TransactionReceipt')) continue;
    const ast = parse(source, {sourceType: 'module', plugins: ['typescript', 'jsx']});
    traverse(ast, {'CallExpression|OptionalCallExpression'(p: any) {
      const n = p.node;
      if (!['MemberExpression', 'OptionalMemberExpression'].includes(n.callee.type) || n.callee.property.type !== 'Identifier' || n.callee.property.name !== 'navigate') return;
      let target = unwrap(n.arguments[0])?.value;
      let payload = unwrap(n.arguments[1]);
      if (target === 'Main' && payload?.type === 'ObjectExpression') {
        target = payload.properties.find((v: any) => v.key?.name === 'screen')?.value?.value;
        payload = payload.properties.find((v: any) => v.key?.name === 'params')?.value;
      }
      if (!['TransactionDetail', 'TransactionReceipt'].includes(target)) return;
      seen.add(path.basename(file));
      if (payload?.type === 'Identifier') {
        const binding = p.scope.getBinding(payload.name);
        payload = binding?.path.node.type === 'VariableDeclarator' ? binding.path.node.init : undefined;
      }
      if (payload?.type !== 'CallExpression' || !adapters.has(payload.callee?.name)) {
        bypasses.push(`${path.basename(file)}:${n.loc?.start.line}`);
      }
    }});
  }
  expect(bypasses).toEqual([]);
  expect([...seen].sort()).toEqual([
    'AccountDetailScreen.tsx', 'BusinessPaymentSuccessScreen.tsx', 'FriendDetailScreen.tsx',
    'NotificationScreen.tsx', 'PaymentSuccessScreen.tsx', 'RampHistoryScreen.tsx',
    'TransactionDetailScreen.tsx', 'TransactionSuccessScreen.tsx', 'USDCHistoryScreen.tsx',
    'messagingService.ts', 'pushNotificationService.ts',
  ].sort());
});
