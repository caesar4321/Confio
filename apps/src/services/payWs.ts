/* Lightweight WS client for payment flow (prepare + submit) with fallback hooks */

type PrepareRequest = {
  amount: number;
  assetType?: string;
  paymentId?: string;
  note?: string;
  recipientBusinessId?: string | number;
};

type PreparePack = {
  transactions: any[];
  user_signing_indexes?: number[];
  userSigningIndexes?: number[];
  group_id?: string;
  groupId?: string;
  gross_amount?: number; net_amount?: number; fee_amount?: number;
  grossAmount?: number; netAmount?: number; feeAmount?: number;
  payment_id?: string; paymentId?: string;
};

type SubmitResult = {
  transaction_id?: string; transactionId?: string;
  confirmed_round?: number; confirmedRound?: number;
  net_amount?: number; netAmount?: number;
  fee_amount?: number; feeAmount?: number;
};

function getWsBase(): string {
  const { getApiUrl } = require('../config/env');
  const api: string = getApiUrl();
  // http(s)://host[:port]/graphql -> ws(s)://host[:port]/
  return api.replace('http://', 'ws://').replace('https://', 'wss://').replace(/\/graphql\/?$/, '/');
}

async function getJwtToken(): Promise<string | null> {
  try {
    const Keychain = require('react-native-keychain');
    const { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } = require('../apollo/client');
    const credentials = await Keychain.getGenericPassword({
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME
    });
    if (credentials) {
      const tokens = JSON.parse(credentials.password);
      return tokens.accessToken || null;
    }
  } catch (e) {
    console.log('[payWs] token error', e);
  }
  return null;
}

export class PayWsSession {
  private ws: WebSocket | null = null;
  private openPromise: Promise<void> | null = null;
  private pendingResolvers: { [k: string]: (v: any) => void } = {};
  private pendingRejectors: { [k: string]: (e: any) => void } = {};
  private closeRequested = false;

  async open(): Promise<void> {
    if (this.openPromise) return this.openPromise;
    this.openPromise = new Promise(async (resolve, reject) => {
      try {
        const token = await getJwtToken();
        if (!token) throw new Error('no_token');
        const wsUrl = `${getWsBase()}ws/pay_session?token=${encodeURIComponent(token)}`;
        console.log('[payWs] Opening', wsUrl.replace(token, '***'));
        const ws = new WebSocket(wsUrl);
        this.ws = ws;
        const timeout = setTimeout(() => {
          console.log('[payWs] open timeout');
          reject(new Error('open_timeout'));
        }, 2500);
        ws.onopen = () => { clearTimeout(timeout); console.log('[payWs] open'); resolve(); };
        ws.onerror = (e) => { clearTimeout(timeout); console.log('[payWs] error', e); if (!this.closeRequested) reject(e); };
        ws.onclose = (e) => {
          console.log('[payWs] close', e.code, e.reason);
          if (!this.closeRequested) {
            // reject all pending
            Object.keys(this.pendingRejectors).forEach((k) => this.pendingRejectors[k](new Error('ws_closed')));
            this.pendingRejectors = {}; this.pendingResolvers = {};
          }
        };
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            console.log('[payWs] message', msg?.type);
            if (msg.type === 'prepare_ready') {
              this.resolve('prepare', msg.pack);
            } else if (msg.type === 'submit_ok') {
              this.resolve('submit', msg);
            } else if (msg.type === 'error') {
              console.log('[payWs] server error', msg?.message);
              this.rejectAll(new Error(msg.message || 'ws_error'));
            }
          } catch {}
        };
      } catch (e) {
        console.log('[payWs] open failed', e);
        reject(e);
      }
    });
    return this.openPromise;
  }

  private resolve(key: string, value: any) {
    const r = this.pendingResolvers[key];
    if (r) { r(value); delete this.pendingResolvers[key]; delete this.pendingRejectors[key]; }
  }
  private rejectAll(err: any) {
    Object.keys(this.pendingRejectors).forEach((k) => this.pendingRejectors[k](err));
    this.pendingRejectors = {}; this.pendingResolvers = {};
  }

  async prepare(req: PrepareRequest, timeoutMs = 8000): Promise<PreparePack> {
    await this.open();
    if (!this.ws) throw new Error('not_open');
    return new Promise<PreparePack>((resolve, reject) => {
      this.pendingResolvers['prepare'] = resolve as any;
      this.pendingRejectors['prepare'] = reject as any;
      const t = setTimeout(() => {
        if (this.pendingRejectors['prepare']) {
          console.log('[payWs] prepare timeout');
          this.pendingRejectors['prepare'](new Error('prepare_timeout'));
          delete this.pendingRejectors['prepare']; delete this.pendingResolvers['prepare'];
        }
      }, timeoutMs);
      try {
        console.log('[payWs] -> prepare_request');
        this.ws!.send(JSON.stringify({ type: 'prepare_request', amount: req.amount, asset_type: req.assetType, payment_id: req.paymentId, note: req.note, recipient_business_id: req.recipientBusinessId }));
      } catch (e) {
        clearTimeout(t);
        reject(e);
      }
    });
  }

  async submit(signedTransactions: any, paymentId?: string, timeoutMs = 10000): Promise<SubmitResult> {
    await this.open();
    if (!this.ws) throw new Error('not_open');
    return new Promise<SubmitResult>((resolve, reject) => {
      this.pendingResolvers['submit'] = resolve as any;
      this.pendingRejectors['submit'] = reject as any;
      const t = setTimeout(() => {
        if (this.pendingRejectors['submit']) {
          console.log('[payWs] submit timeout');
          this.pendingRejectors['submit'](new Error('submit_timeout'));
          delete this.pendingRejectors['submit']; delete this.pendingResolvers['submit'];
        }
      }, timeoutMs);
      try {
        console.log('[payWs] -> submit_request');
        this.ws!.send(JSON.stringify({ type: 'submit_request', signed_transactions: signedTransactions, payment_id: paymentId }));
      } catch (e) {
        clearTimeout(t);
        reject(e);
      }
    });
  }

  close() {
    this.closeRequested = true;
    try { console.log('[payWs] closing'); this.ws?.close(1000, 'flow_end'); } catch {}
    this.ws = null;
  }
}

export async function prepareViaWs(req: PrepareRequest): Promise<PreparePack | null> {
  const s = new PayWsSession();
  try {
    await s.open();
    const pack = await s.prepare(req);
    s.close();
    return pack;
  } catch (e) {
    try { s.close(); } catch {}
    return null;
  }
}

export async function submitViaWs(signedTransactions: any, paymentId?: string): Promise<SubmitResult | null> {
  const s = new PayWsSession();
  try {
    await s.open();
    const res = await s.submit(signedTransactions, paymentId);
    s.close();
    return res;
  } catch (e) {
    try { s.close(); } catch {}
    return null;
  }
}
