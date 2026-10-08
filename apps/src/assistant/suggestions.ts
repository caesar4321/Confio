// What the bubble offers on each screen. Deterministic and free: no model
// call happens until the user taps. Prompts are sent as if the user typed them.
export type ScreenHint = { hint: string; prompt: string };

// The bubble only floats over these screens. Camera, confirmation,
// processing and auth screens stay clean (allowlist, not denylist).
export const TAB_ROUTES = new Set(['Home', 'Invest', 'Discover', 'Profile']);
export const BUBBLE_ROUTES = new Set([
  ...TAB_ROUTES,
  'Send',
  'Receive',
  'AccountDetail',
  'StocksList',
  'StockDetail',
  'OndoStocksInfo',
  'ConfioPresale',
  'Financieras',
  'Achievements',
  'Notification',
  'TransactionDetail',
  'RampHistory',
  'PayoutMethods',
]);

// Screens built around amounts or a confirmation: the bubble tucks itself
// mostly behind the screen edge so it never covers a number or a button,
// and is still one tap (or drag) away.
export const DOCK_ROUTES = new Set([
  'AccountDetail', 'MonthSummary', 'MonthMovements', 'TransactionDetail', 'TransactionProcessing',
  'TransactionSuccess', 'PaymentConfirmation', 'PaymentProcessing', 'PaymentSuccess', 'BusinessPaymentSuccess',
  'Send', 'SendToFriend', 'SendWithAddress', 'SendUsdt', 'LocalSend', 'LocalReceive', 'LocalTransferStatus',
  'LocalAccountFunding', 'InfiniaPayment', 'CobrePayment', 'TopUp', 'Sell', 'ConvertSavings', 'WithdrawSavings',
  'RampInstructions', 'RampAddress', 'RampHistory', 'TradeConfirm', 'BuyStock', 'SellStock', 'StockDetail',
  'USDCDeposit', 'USDCManage', 'USDCHistory', 'USDCConversion', 'ConfioPresaleParticipate',
  'PayrollRun', 'PayrollRunDetail', 'PayrollReceipt', 'PayrollTopUp', 'PayrollPending', 'PayrollHistory',
  'PayrollRunsHistory', 'PayeeDetail', 'FriendDetail', 'EmployeeDetail', 'PendingIncoming', 'Verification',
]);

// Screens with their own pinned action bar where even a docked bubble would
// cover a button: the bubble steps away entirely there.
export const HIDDEN_ROUTES = new Set(['PaidOffer']);

const HINTS: Record<string, ScreenHint[]> = {
  Home: [
    { hint: '¿Te cuento en qué se fue tu dinero este mes?', prompt: '¿En qué gasté más este mes?' },
    { hint: 'Puedo abrir Pagar por ti. Solo pídemelo.', prompt: 'Abre QR para pagar' },
    { hint: '¿Cómo recargo dólares desde mi banco?', prompt: '¿Cómo recargo dólares desde mi banco?' },
  ],
  Invest: [
    { hint: '¿Qué es una acción? Te lo explico en 1 minuto.', prompt: '¿Qué es una acción y cómo funciona en Confío?' },
    { hint: '¿Cómo invierto en acciones de EE.UU.?', prompt: '¿Cómo invierto en acciones?' },
  ],
  StocksList: [
    { hint: '¿Qué significa diversificar?', prompt: '¿Qué significa diversificar?' },
  ],
  StockDetail: [
    { hint: '¿Qué riesgos tiene invertir en una acción?', prompt: '¿Qué riesgos tiene invertir en una sola acción?' },
  ],
  Send: [
    { hint: '¿A quién y cómo puedes enviar? Te guío.', prompt: '¿Cuáles son las formas de enviar dinero?' },
    { hint: '¿Cómo retiro a mi cuenta bancaria?', prompt: '¿Cómo retiro a mi cuenta bancaria?' },
  ],
  Receive: [
    { hint: '¿Cómo te pagan desde otro país?', prompt: '¿Cómo me pueden pagar desde otro país?' },
  ],
  AccountDetail: [
    { hint: '¿Comparo este mes con el anterior?', prompt: 'Compara este mes con el anterior' },
  ],
  Profile: [
    { hint: 'Personaliza a tu asistente: descríbelo o usa una foto de tu mascota.', prompt: '' },
  ],
  Financieras: [
    { hint: '¿Cómo cambio dólares por efectivo?', prompt: '¿Cómo cambio mis dólares por efectivo?' },
  ],
};

export function hintFor(route: string | undefined, seen: Set<string>): ScreenHint | null {
  if (!route) {
    return null;
  }
  const options = HINTS[route] ?? [];
  return options.find((option) => !seen.has(option.hint)) ?? null;
}
