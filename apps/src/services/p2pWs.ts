/* Lightweight WS client for P2P flows (prepare + submit) */

type PrepareArgs = {
  action: 'create'|'accept'|'mark_paid'|'confirm_received'|'cancel'|'open_dispute'|string;
  tradeId: string | number;
  amount?: number;
  assetType?: string; // CUSD/CONFIO/USDC
  paymentRef?: string;
  reason?: string;
};

type PreparedPack = {
  user_transactions?: string[];
  sponsor_transactions?: { txn: string; index: number }[];
  group_id?: string;
  trade_id?: string;
};

type SubmitArgs = {
  action: PrepareArgs['action'];
  tradeId: string | number;
  signedUserTxns?: string[];      // for create
  signedUserTxn?: string;         // for accept/mark_paid/confirm_received/cancel/open_dispute
  sponsorTransactions?: (string|{txn:string;index:number})[];
};

type SubmitResult = { txid?: string; transaction_id?: string };

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
    console.log('[p2pWs] token error', e);
  }
  return null;
}

export class P2PWsSession {
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
        const wsUrl = `${getWsBase()}ws/p2p_session?token=${encodeURIComponent(token)}`;
        console.log('[p2pWs] Opening', wsUrl.replace(token, '***'));
        const ws = new WebSocket(wsUrl);
        this.ws = ws;
        const timeout = setTimeout(() => { console.log('[p2pWs] open timeout'); reject(new Error('open_timeout')); }, 3000);
        ws.onopen = () => { clearTimeout(timeout); console.log('[p2pWs] open'); resolve(); };
        ws.onerror = (e) => { clearTimeout(timeout); console.log('[p2pWs] error', e); if (!this.closeRequested) reject(e); };
        ws.onclose = (e) => {
          console.log('[p2pWs] close', e.code, e.reason);
          if (!this.closeRequested) {
            Object.keys(this.pendingRejectors).forEach((k) => this.pendingRejectors[k](new Error('ws_closed')));
            this.pendingRejectors = {}; this.pendingResolvers = {};
          }
        };
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            console.log('[p2pWs] message', msg?.type, msg?.action);
            if (msg.type === 'prepare_ready') {
              this.resolve(`prepare:${msg.action}`, msg.pack);
            } else if (msg.type === 'submit_ok') {
              this.resolve(`submit:${msg.action}`, msg);
            } else if (msg.type === 'error') {
              console.log('[p2pWs] server error', msg?.message);
              this.rejectAll(new Error(msg.message || 'ws_error'));
            }
          } catch {}
        };
      } catch (e) {
        console.log('[p2pWs] open failed', e);
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

  async prepare(args: PrepareArgs, timeoutMs = 8000): Promise<PreparedPack> {
    await this.open();
    if (!this.ws) throw new Error('not_open');
    return new Promise<PreparedPack>((resolve, reject) => {
      const key = `prepare:${args.action}`;
      this.pendingResolvers[key] = resolve as any;
      this.pendingRejectors[key] = reject as any;
      const t = setTimeout(() => {
        if (this.pendingRejectors[key]) {
          console.log('[p2pWs] prepare timeout');
          this.pendingRejectors[key](new Error('prepare_timeout'));
          delete this.pendingRejectors[key]; delete this.pendingResolvers[key];
        }
      }, timeoutMs);
      try {
        console.log('[p2pWs] -> prepare', args.action);
        const payload: any = { type: 'prepare', action: args.action, trade_id: String(args.tradeId) };
        if (args.amount != null) payload.amount = args.amount;
        if (args.assetType) payload.asset_type = args.assetType;
        if (args.paymentRef) payload.payment_ref = args.paymentRef;
        if (args.reason) payload.reason = args.reason;
        this.ws!.send(JSON.stringify(payload));
      } catch (e) {
        clearTimeout(t);
        reject(e);
      }
    });
  }

  async submit(args: SubmitArgs, timeoutMs = 10000): Promise<SubmitResult> {
    await this.open();
    if (!this.ws) throw new Error('not_open');
    return new Promise<SubmitResult>((resolve, reject) => {
      const key = `submit:${args.action}`;
      this.pendingResolvers[key] = resolve as any;
      this.pendingRejectors[key] = reject as any;
      const t = setTimeout(() => {
        if (this.pendingRejectors[key]) {
          console.log('[p2pWs] submit timeout');
          this.pendingRejectors[key](new Error('submit_timeout'));
          delete this.pendingRejectors[key]; delete this.pendingResolvers[key];
        }
      }, timeoutMs);
      try {
        console.log('[p2pWs] -> submit', args.action);
        const payload: any = { type: 'submit', action: args.action, trade_id: String(args.tradeId) };
        if (args.signedUserTxns) payload.signed_user_txns = args.signedUserTxns;
        if (args.signedUserTxn) payload.signed_user_txn = args.signedUserTxn;
        if (args.sponsorTransactions) payload.sponsor_transactions = args.sponsorTransactions;
        this.ws!.send(JSON.stringify(payload));
      } catch (e) {
        clearTimeout(t);
        reject(e);
      }
    });
  }
}

export function toJSONStringArray(arr: any[]): string[] {
  return (arr || []).map((e) => (typeof e === 'string' ? e : JSON.stringify(e)));
}

