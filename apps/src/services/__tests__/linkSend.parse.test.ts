import { buildLinkUrl, parseLinkUrl } from '../linkSend';

const REF = '1b4e28ba-2fa1-11d2-883f-0016d3cca427';
const KEY = 'ab'.repeat(32);

describe('link send URLs', () => {
  it('round-trips a link the sender built, in either form the app can receive', () => {
    // protects=the receiver gets exactly the key the sender escrowed under; fails_when=the https or confio:// form loses the key; no_claim=signing
    expect(parseLinkUrl(buildLinkUrl(REF, KEY))).toEqual({ publicRef: REF, keyHex: KEY });
    expect(parseLinkUrl(`confio://r/${REF}#${KEY}`)).toEqual({ publicRef: REF, keyHex: KEY });
    expect(parseLinkUrl(`confio://r/${REF}?k=${KEY}`)).toEqual({ publicRef: REF, keyHex: KEY });
  });

  it('refuses a link whose key was cut off or that points elsewhere', () => {
    // protects=a truncated WhatsApp paste or a look-alike host never reaches the claim screen; fails_when=a partial key or other domain parses; no_claim=none beyond protects
    expect(parseLinkUrl(`https://confio.lat/r/${REF}#${KEY.slice(0, 40)}`)).toBeNull();
    expect(parseLinkUrl(`https://confio.lat/r/${REF}`)).toBeNull();
    expect(parseLinkUrl(`https://confio.lat.evil.com/r/${REF}#${KEY}`)).toBeNull();
  });
});
