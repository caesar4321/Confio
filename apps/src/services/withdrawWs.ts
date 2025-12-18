/* Lightweight WS client for USDC withdrawals (prepare + submit) */

type PrepareArgs = {
  amount: string | number;
  destinationAddress: string;
};

type PreparePack = {
  internal_id?: string;
  transactions?: string[]; // base64 unsigned user txns
  sponsor_transactions?: string[]; // JSON strings with {txn,signed?,index}
  group_id?: string;
};

type SubmitArgs = {
  internalId: string;
  signedUserTransactions: string[]; // base64 signed user txns
  sponsorTransactions: (string | { txn: string; signed?: string; index: number })[];
};

type SubmitResult = { txid?: string; internalId?: string; internal_id?: string; };

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
    console.log('[withdrawWs] token error', e);
  }
  return null;
}

export class WithdrawWsSession {
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
        const wsUrl = `${getWsBase()}ws/withdraw_session?token=${encodeURIComponent(token)}`;
        console.log('[withdrawWs] Opening', wsUrl.replace(token, '***'));
        const ws = new WebSocket(wsUrl);
        this.ws = ws;
        const timeout = setTimeout(() => { console.log('[withdrawWs] open timeout'); reject(new Error('open_timeout')); }, 3000);
        ws.onopen = () => { clearTimeout(timeout); console.log('[withdrawWs] open'); resolve(); };
        ws.onerror = (e) => { clearTimeout(timeout); console.log('[withdrawWs] error', e); if (!this.closeRequested) reject(e); };
        ws.onclose = (e) => {
          console.log('[withdrawWs] close', e.code, e.reason);
          if (!this.closeRequested) {
            Object.keys(this.pendingRejectors).forEach((k) => this.pendingRejectors[k](new Error('ws_closed')));
            this.pendingRejectors = {}; this.pendingResolvers = {};
          }
        };
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            console.log('[withdrawWs] message', msg?.type);
            if (msg.type === 'prepare_ready') {
              this.resolve('prepare', msg.pack);
            } else if (msg.type === 'submit_ok') {
              this.resolve('submit', msg);
            } else if (msg.type === 'error') {
              console.log('[withdrawWs] server error', msg?.message);
              this.rejectAll(new Error(msg.message || 'ws_error'));
            }
          } catch { }
        };
      } catch (e) {
        console.log('[withdrawWs] open failed', e);
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

  async prepare(args: PrepareArgs, timeoutMs = 8000): Promise<PreparePack> {
    await this.open();
    if (!this.ws) throw new Error('not_open');
    return new Promise<PreparePack>((resolve, reject) => {
      this.pendingResolvers['prepare'] = resolve as any;
      this.pendingRejectors['prepare'] = reject as any;
      const t = setTimeout(() => {
        if (this.pendingRejectors['prepare']) {
          console.log('[withdrawWs] prepare timeout');
          this.pendingRejectors['prepare'](new Error('prepare_timeout'));
          delete this.pendingRejectors['prepare']; delete this.pendingResolvers['prepare'];
        }
      }, timeoutMs);
      try {
        console.log('[withdrawWs] -> prepare', args.amount, args.destinationAddress);
        this.ws!.send(JSON.stringify({ type: 'prepare', amount: String(args.amount), destination_address: args.destinationAddress }));
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
      this.pendingResolvers['submit'] = resolve as any;
      this.pendingRejectors['submit'] = reject as any;
      const t = setTimeout(() => {
        if (this.pendingRejectors['submit']) {
          console.log('[withdrawWs] submit timeout');
          this.pendingRejectors['submit'](new Error('submit_timeout'));
          delete this.pendingRejectors['submit']; delete this.pendingResolvers['submit'];
        }
      }, timeoutMs);
      try {
        console.log('[withdrawWs] -> submit', args.internalId);
        const sponsors = (args.sponsorTransactions || []).map((e: any) => (typeof e === 'string' ? e : JSON.stringify(e)));
        this.ws!.send(JSON.stringify({
          type: 'submit',
          internal_id: args.internalId,
          signed_transactions: args.signedUserTransactions,
          sponsor_transactions: sponsors,
        }));
      } catch (e) {
        clearTimeout(t);
        reject(e);
      }
    });
  }
}

