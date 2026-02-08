/* WebSocket client for Presale (prepare + submit + app opt-in) */

import { Platform } from 'react-native';

type PreparePurchasePack = {
  internal_id?: string;
  purchase_id?: string; // Legacy, for backward compatibility
  purchaseId?: string;  // Legacy camelCase variant
  transactions?: any[]; // objects: {index,type,transaction,signed,needs_signature}
  sponsor_transactions?: any[]; // same objects or JSON strings
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

export class PresaleWsSession {
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
        const wsUrl = `${getWsBase()}ws/presale_session?token=${encodeURIComponent(token)}`;
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

  private resolve(key: string, v: any) { const r = this.resolvers[key]; if (r) { r(v); delete this.resolvers[key]; delete this.rejectors[key]; } }
  private rejectAll(err: any) { Object.values(this.rejectors).forEach(r => r(err)); this.resolvers = {}; this.rejectors = {}; }

  async preparePurchase(amount: string | number, timeout = 15000): Promise<PreparePurchasePack> {
    await this.open(); if (!this.ws) throw new Error('not_open');
    return new Promise((resolve, reject) => {
      this.resolvers['prepare'] = resolve as any; this.rejectors['prepare'] = reject as any;
      const t = setTimeout(() => { if (this.rejectors['prepare']) { this.rejectors['prepare'](new Error('prepare_timeout')); delete this.rejectors['prepare']; delete this.resolvers['prepare']; } }, timeout);
      try { this.ws!.send(JSON.stringify({ type: 'prepare_request', amount: String(amount), platform: Platform.OS })); } catch (e) { clearTimeout(t); reject(e); }
    });
  }

  async submitPurchase(internalId: string, signedUserTxn: string, sponsorTransactions: (string | { txn: string; signed?: string; index: number })[], timeout = 20000): Promise<SubmitResult> {
    await this.open(); if (!this.ws) throw new Error('not_open');
    return new Promise((resolve, reject) => {
      this.resolvers['submit'] = resolve as any; this.rejectors['submit'] = reject as any;
      const t = setTimeout(() => { if (this.rejectors['submit']) { this.rejectors['submit'](new Error('submit_timeout')); delete this.rejectors['submit']; delete this.resolvers['submit']; } }, timeout);
      try {
        const sponsors = (sponsorTransactions || []).map((e: any) => (typeof e === 'string' ? e : JSON.stringify(e)));
        this.ws!.send(JSON.stringify({ type: 'submit_request', internal_id: internalId, signed_transactions: [{ index: 1, transaction: signedUserTxn }], sponsor_transactions: sponsors }));
      } catch (e) { clearTimeout(t); reject(e); }
    });
  }

  async optinPrepare(timeout = 15000): Promise<PreparePurchasePack> {
    await this.open(); if (!this.ws) throw new Error('not_open');
    return new Promise((resolve, reject) => {
      this.resolvers['prepare'] = resolve as any; this.rejectors['prepare'] = reject as any;
      const t = setTimeout(() => { if (this.rejectors['prepare']) { this.rejectors['prepare'](new Error('prepare_timeout')); delete this.rejectors['prepare']; delete this.resolvers['prepare']; } }, timeout);
      try { this.ws!.send(JSON.stringify({ type: 'optin_prepare', platform: Platform.OS })); } catch (e) { clearTimeout(t); reject(e); }
    });
  }

  async optinSubmit(signedUserTxn: string, sponsorTransactions: (string | { txn: string; signed?: string; index: number })[], timeout = 20000): Promise<SubmitResult> {
    await this.open(); if (!this.ws) throw new Error('not_open');
    return new Promise((resolve, reject) => {
      this.resolvers['submit'] = resolve as any; this.rejectors['submit'] = reject as any;
      const t = setTimeout(() => { if (this.rejectors['submit']) { this.rejectors['submit'](new Error('submit_timeout')); delete this.rejectors['submit']; delete this.resolvers['submit']; } }, timeout);
      try {
        const sponsors = (sponsorTransactions || []).map((e: any) => (typeof e === 'string' ? e : JSON.stringify(e)));
        this.ws!.send(JSON.stringify({ type: 'optin_submit', signed_transactions: [{ index: 1, transaction: signedUserTxn }], sponsor_transactions: sponsors }));
      } catch (e) { clearTimeout(t); reject(e); }
    });
  }

  async claimPrepare(timeout = 15000): Promise<PreparePurchasePack> {
    await this.open(); if (!this.ws) throw new Error('not_open');
    return new Promise((resolve, reject) => {
      this.resolvers['prepare'] = resolve as any; this.rejectors['prepare'] = reject as any;
      const t = setTimeout(() => { if (this.rejectors['prepare']) { this.rejectors['prepare'](new Error('prepare_timeout')); delete this.rejectors['prepare']; delete this.resolvers['prepare']; } }, timeout);
      try { this.ws!.send(JSON.stringify({ type: 'claim_prepare' })); } catch (e) { clearTimeout(t); reject(e); }
    });
  }

  async claimSubmit(signedUserTxn: string, sponsorTransactions: (string | { txn: string; signed?: string; index: number })[], timeout = 20000): Promise<SubmitResult> {
    await this.open(); if (!this.ws) throw new Error('not_open');
    return new Promise((resolve, reject) => {
      this.resolvers['submit'] = resolve as any; this.rejectors['submit'] = reject as any;
      const t = setTimeout(() => { if (this.rejectors['submit']) { this.rejectors['submit'](new Error('submit_timeout')); delete this.rejectors['submit']; delete this.resolvers['submit']; } }, timeout);
      try {
        const sponsors = (sponsorTransactions || []).map((e: any) => (typeof e === 'string' ? e : JSON.stringify(e)));
        this.ws!.send(JSON.stringify({ type: 'claim_submit', signed_transactions: [{ index: 0, transaction: signedUserTxn }], sponsor_transactions: sponsors }));
      } catch (e) { clearTimeout(t); reject(e); }
    });
  }
}
