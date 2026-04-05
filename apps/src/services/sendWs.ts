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
  }
  return null;
}

export class SendWsSession {
  private ws: WebSocket | null = null;
  private openPromise: Promise<void> | null = null;
  private pendingResolvers: { [k: string]: (v: any) => void } = {};
  private pendingRejectors: { [k: string]: (e: any) => void } = {};
  private closeRequested = false;
  private isOpenResolved = false;

  async open(): Promise<void> {
    if (this.openPromise) return this.openPromise;
    this.isOpenResolved = false;
    this.openPromise = new Promise(async (resolve, reject) => {
      try {
        const token = await getJwtToken();
        if (!token) throw new Error('no_token');

        // Fetch App Check token for connection security
        let appCheckToken = '';
        try {
          const { token } = await appCheck().getToken();
          if (token) appCheckToken = token;
        } catch (e) { }

        const wsUrl = `${getWsBase()}ws/send_session?token=${encodeURIComponent(token)}&app_check_token=${encodeURIComponent(appCheckToken)}`;        const ws = new WebSocket(wsUrl);
        this.ws = ws;
        const timeout = setTimeout(() => {          reject(new Error('open_timeout'));
        }, 15000);
        const resolveOpen = () => {
          if (this.isOpenResolved) return;
          this.isOpenResolved = true;
          clearTimeout(timeout);
          resolve();
        };
        ws.onopen = () => {          resolveOpen();
        };
        ws.onerror = (e) => {
          clearTimeout(timeout);          if (!this.closeRequested) reject(e);
        };
        ws.onclose = (e) => {
          clearTimeout(timeout);          if (!this.closeRequested) {
            Object.keys(this.pendingRejectors).forEach((k) => this.pendingRejectors[k](new Error('ws_closed')));
            this.pendingRejectors = {}; this.pendingResolvers = {};
          }
        };
        ws.onmessage = (ev) => {
          try {
            resolveOpen();
            const msg = JSON.parse(ev.data);            if (msg.type === 'prepare_ready') {
              this.resolve('prepare', msg.pack);
            } else if (msg.type === 'submit_ok') {
              this.resolve('submit', msg);
            } else if (msg.type === 'error') {
              this.rejectAll(new Error(msg.message || 'ws_error'));
            }
          } catch { }
        };
      } catch (e) {
        reject(e);
      }
    });
    return this.openPromise;
  }

  private resolve(key: string, value: any) {
    const r = this.pendingResolvers[key];
    if (r) {
      r(value);
      delete this.pendingResolvers[key];
      delete this.pendingRejectors[key];
    }
  }
  private rejectAll(err: any) {
    Object.keys(this.pendingRejectors).forEach((k) => this.pendingRejectors[k](err));
    this.pendingRejectors = {}; this.pendingResolvers = {};
  }

  async prepare(args: PrepareArgs, timeoutMs = 8000): Promise<SendPreparePack> {
    await this.open();
    if (!this.ws) throw new Error('not_open');

    return new Promise<SendPreparePack>((resolve, reject) => {
      const t = setTimeout(() => {
        if (this.pendingRejectors['prepare']) {
          this.pendingRejectors['prepare'](new Error('prepare_timeout'));
          delete this.pendingRejectors['prepare']; delete this.pendingResolvers['prepare'];
        }
      }, timeoutMs);
      this.pendingResolvers['prepare'] = ((value: SendPreparePack) => {
        clearTimeout(t);
        resolve(value);
      }) as any;
      this.pendingRejectors['prepare'] = ((err: any) => {
        clearTimeout(t);
        reject(err);
      }) as any;
      try {
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
      const t = setTimeout(() => {
        if (this.pendingRejectors['submit']) {
          this.pendingRejectors['submit'](new Error('submit_timeout'));
          delete this.pendingRejectors['submit']; delete this.pendingResolvers['submit'];
        }
      }, timeoutMs);
      this.pendingResolvers['submit'] = ((value: SubmitResult) => {
        clearTimeout(t);
        resolve(value);
      }) as any;
      this.pendingRejectors['submit'] = ((err: any) => {
        clearTimeout(t);
        reject(err);
      }) as any;
      try {
        this.ws!.send(JSON.stringify({ type: 'submit_request', signed_transactions: [{ index: 1, transaction: signedUserTxn }], signed_sponsor_txn: sponsorTxn }));
      } catch (e) {
        clearTimeout(t);
        reject(e);
      }
    });
  }

  close() {
    this.closeRequested = true;
    try { this.ws?.close(1000, 'flow_end'); } catch { }
    this.ws = null;
    this.openPromise = null;
    this.isOpenResolved = false;
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
