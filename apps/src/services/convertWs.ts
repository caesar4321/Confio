/* Lightweight WS client for cUSD <> USDC conversion (prepare + submit) */

type PrepareArgs = {
  direction: 'usdc_to_cusd' | 'cusd_to_usdc';
  amount: string | number;
};

type PreparePack = {
  conversion_id?: string;
  transactions?: string[]; // base64 unsigned user txns
  sponsor_transactions?: string[]; // JSON strings with {txn,signed,index}
  group_id?: string;
};

type SubmitArgs = {
  conversionId: string;
  signedUserTransactions: string[]; // base64 signed user txns
  sponsorTransactions: (string | { txn: string; signed?: string; index: number })[];
};

type SubmitResult = {
  txid?: string;
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
    console.log('[convertWs] token error', e);
  }
  return null;
}

export class ConvertWsSession {
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
        const wsUrl = `${getWsBase()}ws/convert_session?token=${encodeURIComponent(token)}`;
        console.log('[convertWs] Opening', wsUrl.replace(token, '***'));
        const ws = new WebSocket(wsUrl);
        this.ws = ws;
        const timeout = setTimeout(() => { console.log('[convertWs] open timeout'); reject(new Error('open_timeout')); }, 3000);
        ws.onopen = () => { clearTimeout(timeout); console.log('[convertWs] open'); resolve(); };
        ws.onerror = (e) => { clearTimeout(timeout); console.log('[convertWs] error', e); if (!this.closeRequested) reject(e); };
        ws.onclose = (e) => {
          console.log('[convertWs] close', e.code, e.reason);
          if (!this.closeRequested) {
            Object.keys(this.pendingRejectors).forEach((k) => this.pendingRejectors[k](new Error('ws_closed')));
            this.pendingRejectors = {}; this.pendingResolvers = {};
          }
        };
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            console.log('[convertWs] message', msg?.type);
            if (msg.type === 'prepare_ready') {
              this.resolve('prepare', msg.pack);
            } else if (msg.type === 'submit_ok') {
              this.resolve('submit', msg);
            } else if (msg.type === 'error') {
              console.log('[convertWs] server error', msg?.message);
              this.rejectAll(new Error(msg.message || 'ws_error'));
            }
          } catch {}
        };
      } catch (e) {
        console.log('[convertWs] open failed', e);
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
          console.log('[convertWs] prepare timeout');
          this.pendingRejectors['prepare'](new Error('prepare_timeout'));
          delete this.pendingRejectors['prepare']; delete this.pendingResolvers['prepare'];
        }
      }, timeoutMs);
      try {
        console.log('[convertWs] -> prepare', args.direction, args.amount);
        this.ws!.send(JSON.stringify({ type: 'prepare', direction: args.direction, amount: String(args.amount) }));
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
          console.log('[convertWs] submit timeout');
          this.pendingRejectors['submit'](new Error('submit_timeout'));
          delete this.pendingRejectors['submit']; delete this.pendingResolvers['submit'];
        }
      }, timeoutMs);
      try {
        console.log('[convertWs] -> submit', args.conversionId);
        // Normalize sponsorTransactions to strings
        const sponsors = (args.sponsorTransactions || []).map((e: any) => (typeof e === 'string' ? e : JSON.stringify(e)));
        this.ws!.send(JSON.stringify({
          type: 'submit',
          conversion_id: args.conversionId,
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

