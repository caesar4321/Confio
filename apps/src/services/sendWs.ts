/* Lightweight WS client for send flow (prepare + submit) */
import appCheck from '@react-native-firebase/app-check';

type PrepareArgs = {
  amount: number;
  assetType?: string; // CUSD/CONFIO
  note?: string;
  recipientAddress?: string;
  recipientUserId?: string | number;
  recipientPhone?: string;
};

type SendPreparePack = {
  transactions: any[]; // index 0 sponsor (signed), index 1 user (unsigned)
  user_signing_indexes?: number[];
  group_id?: string;
  gross_amount?: number; net_amount?: number; fee_amount?: number;
};

type SubmitResult = {
  transaction_id?: string; transactionId?: string;
  internal_id?: string; internalId?: string;
  confirmed_round?: number; confirmedRound?: number;
};

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
  } catch (e) {
    console.log('[sendWs] token error', e);
  }
  return null;
}

export class SendWsSession {
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

        // Fetch App Check token for connection security
        let appCheckToken = '';
        try {
          const { token } = await appCheck().getToken();
          if (token) appCheckToken = token;
        } catch (e) { console.log('[sendWs] App Check token error', e); }

        const wsUrl = `${getWsBase()}ws/send_session?token=${encodeURIComponent(token)}&app_check_token=${encodeURIComponent(appCheckToken)}`;
        console.log('[sendWs] Opening', wsUrl.replace(token, '***').replace(appCheckToken, '***'));
        const ws = new WebSocket(wsUrl);
        this.ws = ws;
        const timeout = setTimeout(() => { console.log('[sendWs] open timeout'); reject(new Error('open_timeout')); }, 15000);
        ws.onopen = () => { clearTimeout(timeout); console.log('[sendWs] open'); resolve(); };
        ws.onerror = (e) => { clearTimeout(timeout); console.log('[sendWs] error', e); if (!this.closeRequested) reject(e); };
        ws.onclose = (e) => {
          console.log('[sendWs] close', e.code, e.reason);
          if (!this.closeRequested) {
            Object.keys(this.pendingRejectors).forEach((k) => this.pendingRejectors[k](new Error('ws_closed')));
            this.pendingRejectors = {}; this.pendingResolvers = {};
          }
        };
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            console.log('[sendWs] message', msg?.type);
            if (msg.type === 'prepare_ready') {
              this.resolve('prepare', msg.pack);
            } else if (msg.type === 'submit_ok') {
              this.resolve('submit', msg);
            } else if (msg.type === 'error') {
              console.log('[sendWs] server error', msg?.message);
              this.rejectAll(new Error(msg.message || 'ws_error'));
            }
          } catch { }
        };
      } catch (e) {
        console.log('[sendWs] open failed', e);
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

  async prepare(args: PrepareArgs, timeoutMs = 8000): Promise<SendPreparePack> {
    await this.open();
    if (!this.ws) throw new Error('not_open');



    return new Promise<SendPreparePack>((resolve, reject) => {
      this.pendingResolvers['prepare'] = resolve as any;
      this.pendingRejectors['prepare'] = reject as any;
      const t = setTimeout(() => {
        if (this.pendingRejectors['prepare']) {
          console.log('[sendWs] prepare timeout');
          this.pendingRejectors['prepare'](new Error('prepare_timeout'));
          delete this.pendingRejectors['prepare']; delete this.pendingResolvers['prepare'];
        }
      }, timeoutMs);
      try {
        console.log('[sendWs] -> prepare_request');
        this.ws!.send(JSON.stringify({ type: 'prepare_request', amount: args.amount, asset_type: args.assetType, note: args.note, recipient_address: args.recipientAddress, recipient_user_id: args.recipientUserId, recipient_phone: args.recipientPhone }));
      } catch (e) {
        clearTimeout(t);
        reject(e);
      }
    });
  }

  async submit(signedUserTxn: string, sponsorTxn: string, timeoutMs = 10000): Promise<SubmitResult> {
    await this.open();
    if (!this.ws) throw new Error('not_open');
    return new Promise<SubmitResult>((resolve, reject) => {
      this.pendingResolvers['submit'] = resolve as any;
      this.pendingRejectors['submit'] = reject as any;
      const t = setTimeout(() => {
        if (this.pendingRejectors['submit']) {
          console.log('[sendWs] submit timeout');
          this.pendingRejectors['submit'](new Error('submit_timeout'));
          delete this.pendingRejectors['submit']; delete this.pendingResolvers['submit'];
        }
      }, timeoutMs);
      try {
        console.log('[sendWs] -> submit_request');
        this.ws!.send(JSON.stringify({ type: 'submit_request', signed_transactions: [{ index: 1, transaction: signedUserTxn }], signed_sponsor_txn: sponsorTxn }));
      } catch (e) {
        clearTimeout(t);
        reject(e);
      }
    });
  }

  close() {
    this.closeRequested = true;
    try { console.log('[sendWs] closing'); this.ws?.close(1000, 'flow_end'); } catch { }
    this.ws = null;
  }
}

export async function prepareSendViaWs(args: PrepareArgs): Promise<SendPreparePack> {
  const s = new SendWsSession();
  try {
    await s.open();
    const pack = await s.prepare(args);
    s.close();
    return pack;
  } catch (e) {
    try { s.close(); } catch { }
    throw e;
  }
}

export async function submitSendViaWs(signedUserTxn: string, sponsorTxn: string): Promise<SubmitResult> {
  const s = new SendWsSession();
  try {
    await s.open();
    const res = await s.submit(signedUserTxn, sponsorTxn);
    s.close();
    return res;
  } catch (e) {
    try { s.close(); } catch { }
    throw e;
  }
}
