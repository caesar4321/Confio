// Emergency exit, phase 2: the outage-status Worker, the ban route's
// server confirmation + Confío Face, and a ban flag that can no longer
// unlock anything while Confío is unreachable.

import { ed25519 } from '@noble/curves/ed25519.js';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils';
import {
  classifyReachability,
  OUTAGE_IMMEDIATE_SECONDS,
  OUTAGE_STATUS_FRESH_SECONDS,
} from '../emergencyExit/reachability';
import { fetchOutageStatus, parseSignedStatus } from '../emergencyExit/outageStatus';
import { apiOrigin, confirmBannedExit } from '../emergencyExit/emergencyFace';

const T0 = 1_800_000_000;

const workerKey = ed25519.utils.randomSecretKey();
const WORKER_PUBLIC_HEX = bytesToHex(ed25519.getPublicKey(workerKey));

const signed = (fields: object, key = workerKey) => {
  const payload = JSON.stringify({ v: 1, ...fields });
  const signature = Buffer.from(ed25519.sign(utf8ToBytes(payload), key)).toString('base64');
  return { payload, signature };
};

describe('classifyReachability with the outage Worker', () => {
  const unreachable = { confioOk: false, chainOk: true, prevOutageStartSec: T0 - 100, chainNowSec: T0 };

  it('Confío hidden from the phone but up per the Worker is a local block, not an outage', () => {
    const r = classifyReachability({
      ...unreachable,
      outageStatus: { checkedAtSec: T0 - 60, lastUpAtSec: T0 - 60, downSinceSec: null },
    });
    expect(r.state).toBe('blocked');
    expect(r.immediate).toBe(false);
    expect(r.outageStartSec).toBeNull(); // no outage window runs
  });

  it('a confirmed outage runs from when the Worker first saw it', () => {
    const since = T0 - OUTAGE_IMMEDIATE_SECONDS;
    const r = classifyReachability({
      ...unreachable,
      prevOutageStartSec: null,
      outageStatus: { checkedAtSec: T0 - 60, lastUpAtSec: since - 300, downSinceSec: since },
    });
    expect(r.state).toBe('outage');
    expect(r.outageStartSec).toBe(since);
    expect(r.immediate).toBe(true);
  });

  it('a stale Worker statement is ignored (the phone\'s own window runs)', () => {
    const r = classifyReachability({
      ...unreachable,
      outageStatus: {
        checkedAtSec: T0 - OUTAGE_STATUS_FRESH_SECONDS - 1, lastUpAtSec: T0 - 99_999, downSinceSec: null,
      },
    });
    expect(r.state).toBe('outage');
    expect(r.outageStartSec).toBe(T0 - 100);
  });

  it('no Worker answer keeps the local 72h rule', () => {
    const r = classifyReachability({ ...unreachable, outageStatus: null });
    expect(r.state).toBe('outage');
    expect(r.immediate).toBe(false);
  });

  it('a ban flag counts only while Confío answers', () => {
    expect(classifyReachability({
      confioOk: true, chainOk: true, prevOutageStartSec: null, chainNowSec: T0, banned: true,
    }).state).toBe('banned');
    // A faked 403 plus a blocked domain must not unlock anything.
    const r = classifyReachability({ ...unreachable, banned: true });
    expect(r.state).toBe('outage');
    expect(r.immediate).toBe(false);
  });
});

describe('parseSignedStatus', () => {
  it('accepts a status signed by the bundled key', () => {
    expect(parseSignedStatus(signed({ checkedAt: T0, lastUpAt: T0, downSince: null }), WORKER_PUBLIC_HEX))
      .toEqual({ checkedAtSec: T0, lastUpAtSec: T0, downSinceSec: null });
  });

  it('rejects a forged "Confío is down"', () => {
    const forged = signed({ checkedAt: T0, lastUpAt: null, downSince: T0 - 999_999 },
      ed25519.utils.randomSecretKey());
    expect(parseSignedStatus(forged, WORKER_PUBLIC_HEX)).toBeNull();
  });

  it('rejects a tampered payload', () => {
    const good = signed({ checkedAt: T0, lastUpAt: T0, downSince: null });
    const tampered = { ...good, payload: good.payload.replace('"downSince":null', `"downSince":${T0 - 999_999}`) };
    expect(parseSignedStatus(tampered, WORKER_PUBLIC_HEX)).toBeNull();
  });

  it('is off until a public key is configured', async () => {
    const fetchSpy = jest.fn();
    (global as any).fetch = fetchSpy;
    await expect(fetchOutageStatus(['https://worker.example/v1/status'], '')).resolves.toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('falls through to the next URL when one is unreachable', async () => {
    const body = signed({ checkedAt: T0, lastUpAt: T0, downSince: null });
    (global as any).fetch = jest.fn()
      .mockRejectedValueOnce(new Error('blocked'))
      .mockResolvedValueOnce({ ok: true, json: async () => body });
    await expect(fetchOutageStatus(['https://a.example', 'https://b.example'], WORKER_PUBLIC_HEX))
      .resolves.toMatchObject({ downSinceSec: null });
  });
});

describe('confirmBannedExit', () => {
  const wallet = { address: '0xAbCdEf0000000000000000000000000000000001', privKeyHex: '11'.repeat(32) };
  const API = 'https://confio.example/graphql/';

  const serverWith = (session: object, face?: { start?: object; complete?: object }) => {
    const calls: { url: string; body: any; headers: any }[] = [];
    const fetchImpl = jest.fn(async (url: string, init: any) => {
      const body = JSON.parse(init.body);
      calls.push({ url, body, headers: init.headers });
      const path = url.replace('https://confio.example', '');
      const reply: Record<string, object> = {
        '/api/emergency-exit/challenge/': { success: true, nonce: 'n-1', message: 'sign me' },
        '/api/emergency-exit/session/': session,
        '/api/emergency-exit/face/start/': face?.start ?? { success: true, sessionId: 's-1' },
        '/api/emergency-exit/face/complete/': face?.complete ?? { success: true, passed: true },
      };
      return { json: async () => reply[path] } as any;
    });
    return { calls, fetchImpl: fetchImpl as unknown as typeof fetch };
  };

  const deps = (fetchImpl: typeof fetch, presentFace = jest.fn(async () => true)) => ({
    fetchImpl,
    presentFace,
    getAppCheckToken: async () => 'app-check-token',
    sign: (message: string) => `sig(${message})`,
  });

  it('derives the REST origin from the GraphQL URL', () => {
    expect(apiOrigin('https://confio.lat/graphql/')).toBe('https://confio.lat');
    expect(apiOrigin('https://confio.lat/graphql')).toBe('https://confio.lat');
  });

  it('signs the challenge with the account key, attests the device, and needs a face', async () => {
    const { calls, fetchImpl } = serverWith({ success: true, banned: true, faceRequired: true, token: 't-1' });
    const presentFace = jest.fn(async (backend: any) => {
      await backend.start('emergency_exit');
      await backend.complete('s-1');
      return true;
    });
    await expect(confirmBannedExit(wallet, API, deps(fetchImpl, presentFace))).resolves.toEqual({ outcome: 'passed' });
    expect(calls[0].body).toEqual({ address: wallet.address.toLowerCase() });
    expect(calls[1].body).toEqual({ address: wallet.address.toLowerCase(), nonce: 'n-1', signature: 'sig(sign me)' });
    expect(calls[1].headers['X-Firebase-AppCheck']).toBe('app-check-token');
    expect(calls[2].body).toEqual({ token: 't-1' });
    expect(calls[2].headers['X-Firebase-AppCheck']).toBe('app-check-token');
    expect(calls[3].body).toEqual({ token: 't-1', sessionId: 's-1' });
    // Never a JWT on this route: the middleware would refuse a banned user.
    calls.forEach(c => expect(c.headers.Authorization).toBeUndefined());
  });

  it('refuses the exit when the face check does not pass', async () => {
    const { fetchImpl } = serverWith({ success: true, banned: true, faceRequired: true, token: 't-1' });
    const result = await confirmBannedExit(wallet, API, deps(fetchImpl, jest.fn(async () => false)));
    expect(result.outcome).toBe('failed');
  });

  it('sends a healthy account back to the normal route', async () => {
    const { fetchImpl } = serverWith({ success: true, banned: false, faceRequired: false, token: '' });
    const presentFace = jest.fn();
    await expect(confirmBannedExit(wallet, API, deps(fetchImpl, presentFace))).resolves.toEqual({ outcome: 'not_banned' });
    expect(presentFace).not.toHaveBeenCalled();
  });

  it('sends a banned account without KYC to the waiting period, never straight out', async () => {
    const { fetchImpl } = serverWith({ success: true, banned: true, faceRequired: false, waitRequired: true, token: '' });
    const presentFace = jest.fn();
    await expect(confirmBannedExit(wallet, API, deps(fetchImpl, presentFace))).resolves.toEqual({ outcome: 'wait' });
    expect(presentFace).not.toHaveBeenCalled();
  });

  it('passes without a face while the server does not enforce it', async () => {
    const { fetchImpl } = serverWith({ success: true, banned: true, faceRequired: false, token: '' });
    await expect(confirmBannedExit(wallet, API, deps(fetchImpl))).resolves.toEqual({ outcome: 'passed' });
  });

  it('fails closed when Confío cannot be reached', async () => {
    const fetchImpl = jest.fn(async () => { throw new Error('network'); }) as unknown as typeof fetch;
    const result = await confirmBannedExit(wallet, API, deps(fetchImpl));
    expect(result.outcome).toBe('failed');
  });
});
