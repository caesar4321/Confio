// Custom glyphs for the money concepts Feather has no word for.
//
// Feather is the app's icon language, so anything drawn here shares its
// 24-unit grid, its 1.9 stroke and its round caps — a custom glyph has to sit
// in a list next to `gift` or `briefcase` without looking imported. Only
// concepts Feather genuinely lacks live here: a bank facade, a wallet, a swap,
// a dollar coin and a payment card. Everything else stays a Feather name.

export type GlyphPaths = readonly string[];

export const CUSTOM_GLYPHS: Record<string, GlyphPaths> = {
  // Destination of a local transfer: an institution, bank or payment wallet.
  bank: ['M2.4 9.6 12 4.4 21.6 9.6Z', 'M6.6 12v5.4M12 12v5.4M17.4 12v5.4', 'M4.2 17.4h15.6', 'M2.8 20.2h18.4'],
  // A wallet outside Confío. The flap keeps it from reading as a card.
  wallet: [
    'M3.2 8.4h15.2a2.4 2.4 0 0 1 2.4 2.4v7.2a2.4 2.4 0 0 1-2.4 2.4H5.6a2.4 2.4 0 0 1-2.4-2.4z',
    'M3.2 10.6V7.4a1.8 1.8 0 0 1 1.4-1.76l10.2-2.2a1.2 1.2 0 0 1 1.5 1.17V8.4',
    'M17.2 14.4h.02',
  ],
  // Two arrows passing: a conversion, not Feather's looping `repeat`, which
  // reads as "recurring" and was doing duty for ramps at the same time.
  swap: ['M4 9.2h12.6', 'M13.8 6.4 16.8 9.2 13.8 12', 'M20 15.2H7.4', 'M10.2 12.4 7.4 15.2 10.2 18'],
  // A dollar coin: the stablecoin itself moving, as opposed to a payment.
  coin: [
    'M12 3.2a8.8 8.8 0 1 1 0 17.6 8.8 8.8 0 0 1 0-17.6Z',
    'M14.4 9.4a2.7 2.7 0 0 0-2.4-1.2c-1.5 0-2.6.8-2.6 1.9 0 2.5 5.2 1.4 5.2 3.9 0 1.2-1.2 2-2.6 2a3 3 0 0 1-2.6-1.2',
    'M12 6.6v1.4M12 16v1.4',
  ],
  // The card rail: buying or selling against fiat.
  card: [
    'M4.6 6.2h14.8a2.2 2.2 0 0 1 2.2 2.2v7.2a2.2 2.2 0 0 1-2.2 2.2H4.6a2.2 2.2 0 0 1-2.2-2.2V8.4a2.2 2.2 0 0 1 2.2-2.2Z',
    'M2.4 10.2h19.2',
    'M5.6 14.2h3.4',
  ],
};

// State marks for the corner badge. Drawn heavier than the main glyph because
// they render at 10px inside a 17px circle.
export type BadgeName = 'pending' | 'done' | 'returned' | 'failed' | 'review' | 'incoming';

export const BADGE_GLYPHS: Record<BadgeName, GlyphPaths> = {
  pending: ['M12 7v5l3 2'],
  done: ['M5 12.5 10 17.5 19 7.5'],
  returned: ['M4 8h9a6 6 0 0 1 0 12H7', 'M8 4 4 8l4 4'],
  failed: ['M6.5 6.5 17.5 17.5M17.5 6.5 6.5 17.5'],
  review: ['M12 6.5v7', 'M12 17.4v.01'],
  incoming: ['M12 5v13', 'M6.5 12.5 12 18l5.5-5.5'],
};

// The clock badge needs its face; every other badge is strokes alone.
export const BADGE_RINGED: BadgeName[] = ['pending'];
