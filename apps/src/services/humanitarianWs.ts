import { Platform } from 'react-native';

type DonationPreparePack = {
  donation_id?: string;
  donationId?: string;
  transactions?: any[];
  sponsor_transactions?: any[];
  user_signing_indexes?: number[];
  group_id?: string;
};

type SubmitResult = { transaction_id?: string };

function getWsBase(): string {
  const { getApiUrl } = require('../config/env');
  const api: string = getApiUrl();
  return api.replace('http://', 'ws://').replace('https://', 'wss://').replace(/\/graphql\/?$/, '/');
}

async function getJwtToken(): Promise<string | null> {
  try {
    const Keychain = require('react-native-keychain');
    const { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } = require('../apollo/client');
    const credentials = await Keychain.getGenericPassword({ service: AUTH_KEYCHAIN_SERVICE, username: AUTH_KEYCHAIN_USERNAME });
    if (credentials) {
      const tokens = JSON.parse(credentials.password);
      return tokens.accessToken || null;
    }
  } catch (e) { }
  return null;
}

export class HumanitarianWsSession {
  private ws: WebSocket | null = null;
  private openPromise: Promise<void> | null = null;
  private resolvers: Record<string, (v: any) => void> = {};
  private rejectors: Record<string, (e: any) => void> = {};
  private closed = false;

  async open(): Promise<void> {
    if (this.openPromise) return this.openPromise;
    this.openPromise = new Promise(async (resolve, reject) => {
      try {
        const token = await getJwtToken();
        if (!token) throw new Error('no_token');
        const wsUrl = `${getWsBase()}ws/humanitarian_session?token=${encodeURIComponent(token)}`;
        const ws = new WebSocket(wsUrl);
        this.ws = ws;
        const t = setTimeout(() => reject(new Error('open_timeout')), 15000);
        ws.onopen = () => { clearTimeout(t); resolve(); };
        ws.onerror = (e) => { clearTimeout(t); if (!this.closed) reject(e); };
        ws.onclose = () => { if (!this.closed) Object.values(this.rejectors).forEach(r => r(new Error('ws_closed'))); };
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            if (msg.type === 'prepare_ready') this.resolve('prepare', msg.pack);
            else if (msg.type === 'submit_ok') this.resolve('submit', msg);
            else if (msg.type === 'error') this.rejectAll(new Error(msg.message || 'ws_error'));
          } catch { }
        };
      } catch (e) { reject(e); }
    });
    return this.openPromise;
  }

  close() {
    this.closed = true;
    try { this.ws?.close(); } catch { }
  }

  private resolve(key: string, v: any) {
    const r = this.resolvers[key];
    if (r) {
      r(v);
      delete this.resolvers[key];
      delete this.rejectors[key];
    }
  }

  private rejectAll(err: any) {
    Object.values(this.rejectors).forEach(r => r(err));
    this.resolvers = {};
    this.rejectors = {};
  }

  async prepareDonation(campaignSlug: string, amount: string | number, timeout = 15000): Promise<DonationPreparePack> {
    await this.open();
    if (!this.ws) throw new Error('not_open');
    return new Promise((resolve, reject) => {
      this.resolvers.prepare = resolve as any;
      this.rejectors.prepare = reject as any;
      const t = setTimeout(() => {
        if (this.rejectors.prepare) {
          this.rejectors.prepare(new Error('prepare_timeout'));
          delete this.rejectors.prepare;
          delete this.resolvers.prepare;
        }
      }, timeout);
      try {
        this.ws!.send(JSON.stringify({
          type: 'donation_prepare',
          campaign_slug: campaignSlug,
          amount: String(amount),
          platform: Platform.OS,
        }));
      } catch (e) {
        clearTimeout(t);
        reject(e);
      }
    });
  }

  async submitDonation(
    donationId: string,
    signedUserTxn: string,
    sponsorTransactions: (string | { txn: string; signed?: string; index: number })[],
    timeout = 20000
  ): Promise<SubmitResult> {
    await this.open();
    if (!this.ws) throw new Error('not_open');
    return new Promise((resolve, reject) => {
      this.resolvers.submit = resolve as any;
      this.rejectors.submit = reject as any;
      const t = setTimeout(() => {
        if (this.rejectors.submit) {
          this.rejectors.submit(new Error('submit_timeout'));
          delete this.rejectors.submit;
          delete this.resolvers.submit;
        }
      }, timeout);
      try {
        const sponsors = (sponsorTransactions || []).map((entry: any) => (
          typeof entry === 'string' ? entry : JSON.stringify(entry)
        ));
        this.ws!.send(JSON.stringify({
          type: 'donation_submit',
          donation_id: donationId,
          signed_transactions: [{ index: 0, transaction: signedUserTxn }],
          sponsor_transactions: sponsors,
        }));
      } catch (e) {
        clearTimeout(t);
        reject(e);
      }
    });
  }
}
