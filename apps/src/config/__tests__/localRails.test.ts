import {
  countryFlag,
  countryName,
  getReceiveRails,
  getSendRails,
  COMING_SOON_NOTE,
  RECEIVE_ROW_SUBTITLE,
  SEND_ROW_SUBTITLE,
  toIso2,
} from '../localRails';

// The country-code seam is the whole reason this file has tests. The backend
// (`payment_accounts`) stores ISO-3 while the app's country table is ISO-2, so
// a raw comparison fails SILENTLY: no flag renders, and a corridor the user
// already owns still lists as "not available yet", inviting them to ask for
// what they already have.
describe('toIso2', () => {
  it('maps the backend ISO-3 codes to the app ISO-2 codes', () => {
    expect(toIso2('COL')).toBe('CO');
    expect(toIso2('MEX')).toBe('MX');
    expect(toIso2('VEN')).toBe('VE');
  });

  it('passes ISO-2 through and normalizes case and padding', () => {
    expect(toIso2('CO')).toBe('CO');
    expect(toIso2(' co ')).toBe('CO');
  });

  it('returns empty for unknown or absent codes instead of guessing', () => {
    expect(toIso2(null)).toBe('');
    expect(toIso2(undefined)).toBe('');
    expect(toIso2('')).toBe('');
    expect(toIso2('ZZZ')).toBe('');
  });
});

describe('country display helpers', () => {
  it('resolves flag and name from either code width', () => {
    expect(countryFlag('CO')).toBe(countryFlag('COL'));
    expect(countryFlag('CO')).not.toBe('');
    expect(countryName('MEX')).toBe(countryName('MX'));
  });

  it('never renders a broken flag for an unknown country', () => {
    expect(countryFlag('ZZZ')).toBe('');
  });
});

describe('rail ordering', () => {
  it("puts the user's own country first", () => {
    expect(getSendRails('MX')[0].country).toBe('MX');
    expect(getReceiveRails('CO')[0].country).toBe('CO');
  });

  it('accepts an ISO-3 country just as well as ISO-2', () => {
    expect(getSendRails('MEX')[0].country).toBe('MX');
  });

  it('keeps the default order when the country is unknown or unsupported', () => {
    // Unresolved country must degrade to the default list, never to an empty
    // one: `useRampCountry` returns null until the profile loads, and a
    // blank picker at that moment reads as "nothing available in my country".
    const fallback = getSendRails(null);
    expect(fallback.length).toBeGreaterThan(0);
    expect(getSendRails('ZZ')).toEqual(fallback);
    // Ecuador is a real country with no corridor listed — the case that
    // matters, since an unlisted country must not reorder anything.
    expect(getSendRails('EC')).toEqual(fallback);
  });

  it('drops no rails and duplicates none when hoisting', () => {
    const base = getSendRails(null);
    const ordered = getSendRails('CO');
    expect(ordered).toHaveLength(base.length);
    expect(new Set(ordered.map(rail => rail.id)).size).toBe(base.length);
  });
});

// SEPA is a currency area, not a country. It has no ISO-2 entry in the app's
// country table, so without a pseudo-entry the picker rendered a blank flag
// and the literal string "EU" where a country name belongs.
describe('the SEPA pseudo-region', () => {
  it('renders a flag and a readable name', () => {
    expect(countryFlag('EU')).toBe('🇪🇺');
    expect(countryName('EU')).toBe('Zona euro');
  });

  it('is offered in both directions and orders like any other row', () => {
    expect(getSendRails(null).some(r => r.country === 'EU')).toBe(true);
    expect(getReceiveRails('EU')[0].country).toBe('EU');
  });
});

describe('corridor coverage', () => {
  // Every country Infinia can open an account in must be offered for receive
  // (PROVIDER_ACCOUNT_SHAPES in payment_accounts/services.py), so the picker
  // never silently omits a corridor the backend already supports.
  const RECEIVABLE = ['AR', 'BO', 'BR', 'CL', 'CO', 'MX', 'PE', 'PY', 'UY', 'US', 'EU', 'GB'];

  it('offers receive for every openable country', () => {
    const offered = new Set(getReceiveRails(null).map(r => r.country));
    expect(RECEIVABLE.filter(c => !offered.has(c))).toEqual([]);
  });

  it('offers send everywhere it offers receive', () => {
    const send = new Set(getSendRails(null).map(r => r.country));
    expect(RECEIVABLE.filter(c => !send.has(c))).toEqual([]);
  });

  it('keeps every rail id unique across both directions', () => {
    const ids = [...getSendRails(null), ...getReceiveRails(null)].map(r => r.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('ships nothing as live until its provider flag and flow exist', () => {
    // A `live` row navigates into a flow that is not built. Flipping one
    // requires the server flag AND a destination type — UY and US have
    // neither on the send side today.
    const all = [...getSendRails(null), ...getReceiveRails(null)];
    expect(all.filter(r => r.status === 'live')).toEqual([]);
  });
});

// Legal titling is a stronger claim than personalisation and we cannot back it
// everywhere: Infinia documents only Argentina B2C as a "Named account", and
// Cobre balances are omnibus subledgers. The copy promises permanence and
// exclusivity instead — this test stops "a tu nombre" creeping back in.
describe('receive copy never claims the account is titled to the user', () => {
  it('promises a personal identifier, not legal ownership', () => {
    for (const rail of getReceiveRails(null)) {
      expect(rail.subtitle).not.toMatch(/a tu nombre/i);
      expect(rail.subtitle).toMatch(/tu propi|tus propi/i);
    }
  });

  it('says so on the menu row too, without over-claiming', () => {
    // The row is the only place many users will read before sharing a key.
    expect(RECEIVE_ROW_SUBTITLE).toMatch(/tu propia/i);
    expect(RECEIVE_ROW_SUBTITLE).not.toMatch(/a tu nombre/i);
    expect(SEND_ROW_SUBTITLE).not.toMatch(/a tu nombre/i);
  });

  it('names whose account is at the far end of each row', () => {
    // The pair has to read as opposites at a glance: mine vs theirs. If both
    // rows ever describe the same owner, the Enviar/Retirar boundary blurs —
    // Retirar is the same-owner cash-out, Enviar is the third-party payout.
    expect(RECEIVE_ROW_SUBTITLE).toMatch(/tu propia/i);
    expect(SEND_ROW_SUBTITLE).toMatch(/otra persona|negocio/i);
    expect(SEND_ROW_SUBTITLE).not.toMatch(/tu propia|tu cuenta/i);
  });
});

describe('ISO-3 codes the backend stores for the newer corridors', () => {
  it('maps GBR and USA, and presents the Luxembourg euro account as EU', () => {
    expect(toIso2('GBR')).toBe('GB');
    expect(toIso2('USA')).toBe('US');
    // Infinia opens the euro account in Luxembourg; the product is the euro
    // area, so a LUX account must dedupe against the EU row, not sit beside it.
    expect(toIso2('LUX')).toBe('EU');
  });
});

// App Store Guideline 2.1 rejects placeholder/temporary content and 2.3.1
// rejects UI implying functionality the app lacks. The defence is that these
// rows are a published roadmap with a waitlist opt-in, not unfinished buttons
// — and that reading depends entirely on the wording, so it is pinned here.
describe('unavailable-rail wording survives app review', () => {
  it('frames the state as a roadmap entry, not a failure', () => {
    expect(COMING_SOON_NOTE).toMatch(/^Próximamente/);
  });

  it('never implies something is broken or switched off', () => {
    // "Aún no disponible" reads as an un-enabled or broken control, which is
    // exactly what Guideline 2.1 targets.
    expect(COMING_SOON_NOTE).not.toMatch(/no disponible|no funciona|error/i);
  });

  it('tells the user what tapping does, so the row is never a dead end', () => {
    expect(COMING_SOON_NOTE).toMatch(/aviso|avisar|avisamos/i);
  });
});
