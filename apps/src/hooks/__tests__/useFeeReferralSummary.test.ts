jest.mock('@apollo/client', () => ({ gql: (s: TemplateStringsArray) => s.join(''), useQuery: jest.fn() }));

import { commissionPercents, windowLabel } from '../useFeeReferralSummary';
import { buildReferralShareMessage } from '../../utils/inviteLinks';

describe('fee referral copy helpers', () => {
  it('derives the percentages from the server numbers', () => {
    expect(commissionPercents({ shareBps: 5000, feeBps: 90 })).toEqual({
      sharePct: '50%', volumePct: '0.45%', feePct: '0.9%',
    });
    expect(commissionPercents({ shareBps: 2500, feeBps: 90 }).volumePct).toBe('0.225%');
  });

  it('names the window in plain words', () => {
    expect(windowLabel(365)).toBe('1 año');
    expect(windowLabel(730)).toBe('2 años');
    expect(windowLabel(90)).toBe('90 días');
  });
});

describe('WhatsApp referral message', () => {
  it('carries the link, the friend benefit and the transparency line', () => {
    const text = buildReferralShareMessage('julian');
    expect(text).toContain('https://confio.lat/invite/JULIAN?source=whatsapp');
    expect(text).not.toContain('US$5');
    const link = text.indexOf('https://confio.lat/invite/JULIAN');
    expect(text.indexOf('verifica tu identidad')).toBeGreaterThan(link);
    expect(text).toContain('*A ti no te cuesta nada extra.*');
    expect(text.trim().endsWith('Código: JULIAN')).toBe(true);
    // Formatting never touches a URL (it must stay tappable in WhatsApp).
    for (const line of text.split('\n').filter((l) => l.includes('http'))) {
      expect(line).not.toMatch(/[*_~]/);
    }
    expect(text).not.toMatch(/#\w+/); // WhatsApp invite carries no hashtags
  });
});
