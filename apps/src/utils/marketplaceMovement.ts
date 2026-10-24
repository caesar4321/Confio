// Comprar ledger rows carry a description prefix the server sets
// (marketplace/ledger.py): "Comprar: " on the purchase, the sale and the
// refund. Neither side is a person to pay back, and the rows have no send
// behind them, so the detail screen offers no resend and fetches no send.

export const MARKETPLACE_PREFIX = 'Comprar: ';

export const isMarketplaceMovement = (description?: string | null): boolean =>
  typeof description === 'string' && description.startsWith(MARKETPLACE_PREFIX);
