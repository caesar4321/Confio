import { futuresShareContent } from '../futuresShare';
import { SHARE_LINKS } from '../../config/shareLinks';

const base: any = {
  id: '7', coin: 'xyz:TSLA', ticker: 'TSLA', name: 'Tesla', assetClass: 'stock', side: 'long', leverage: 5,
  marginUsd: 10, state: 'open', size: 0.1, entryPx: 400, markPx: 410, unrealizedPnlUsd: 1, returnOnEquity: 0.1,
  marginUsedUsd: 10, liquidation: null, resultUsd: null, putInUsd: 10,
};

describe('Futuros share card', () => {
  it('an open position: percent on the margin, live when a price is given, no dollars by default', () => {
    const c = futuresShareContent(base, 'position', false, 420)!;
    expect(c.headline).toMatch(/^\+20[.,]00%$/); // (420 − 400) × 0.1 = $2 on $10 of margin
    expect(c.sideLine).toBe('Largo 5x');
    expect(c.usdLine).toBeNull();
    expect(c.message).not.toMatch(/US\$/);
    expect(c.rows.map((r) => r.label)).toEqual(['Entrada', 'Precio actual']);
  });

  it('the current price falls back like the screen (live, server mark, market mark)', () => {
    const c = futuresShareContent({ ...base, markPx: null }, 'position', false, null, 415)!;
    expect(c.rows[1].value).toMatch(/415/);
  });

  it('dollars only when the member turns them on', () => {
    const c = futuresShareContent(base, 'position', true, 420)!;
    expect(c.usdLine).toMatch(/^\+US\$2[.,]00$/);
    expect(c.message).toContain(c.usdLine!);
  });

  it('a closed position: its realized result over what was put in, with all costs', () => {
    const closed = { ...base, state: 'done', resultUsd: -2.5, putInUsd: 10, side: 'short' };
    const c = futuresShareContent(closed, 'result', false)!;
    expect(c.headlineValue).toBe(-25);
    expect(c.headline).toMatch(/^−25[.,]00%$/);
    expect(c.sideLine).toBe('Corto 5x');
    expect(c.caption).toBe('resultado con todos los costos');
    expect(c.liquidated).toBe(false);
    const liquidated = futuresShareContent({ ...closed, liquidation: 'liquidated' }, 'result', false)!;
    expect(liquidated.liquidated).toBe(true);
    expect(liquidated.message).toMatch(/^Me liquidaron TSLA/);
    expect(c.message).toMatch(/^Cerré TSLA/);
  });

  it('shows nothing it cannot back with a figure', () => {
    expect(futuresShareContent({ ...base, unrealizedPnlUsd: null, returnOnEquity: null, marginUsedUsd: null }, 'position', true))
      .toBeNull();
    expect(futuresShareContent({ ...base, state: 'done', resultUsd: null }, 'result', true)).toBeNull();
  });

  it('carries exactly the five official hashtags and the site link', () => {
    const { message } = futuresShareContent(base, 'position', false)!;
    expect(message).toContain(SHARE_LINKS.hashtags);
    expect(message.match(/#\w+/g)).toEqual(['#Confio', '#RetoConfio', '#LogroConfio', '#AppDeDolares', '#DolarDigital']);
    expect(message).toContain('https://confio.lat');
  });
});
