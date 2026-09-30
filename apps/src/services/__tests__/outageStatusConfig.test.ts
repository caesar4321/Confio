import { fetchOutageStatus } from '../emergencyExit/outageStatus';
import { OUTAGE_STATUS_PUBLIC_KEY_HEX, OUTAGE_STATUS_URLS } from '../emergencyExit/outageStatusConfig';

describe('production outage monitor configuration', () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = originalFetch; });

  it('bundles an independent HTTPS endpoint and an Ed25519 public key', () => {
    expect(OUTAGE_STATUS_PUBLIC_KEY_HEX).toMatch(/^[a-f0-9]{64}$/);
    expect(OUTAGE_STATUS_URLS.length).toBeGreaterThan(0);
    for (const value of OUTAGE_STATUS_URLS) {
      const url = new URL(value);
      expect(url.protocol).toBe('https:');
      expect(url.hostname).toBe('confio-outage-status.julianmoon.workers.dev');
      expect(url.pathname).toBe('/v1/status');
    }
  });

  it('uses the bundled endpoint by default and safely handles unavailable status', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: false });
    globalThis.fetch = fetchMock;
    await expect(fetchOutageStatus()).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(OUTAGE_STATUS_URLS[0], expect.objectContaining({ signal: expect.anything() }));
  });
});
