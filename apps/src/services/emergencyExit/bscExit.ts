// BSC leg of the emergency exit (docs/plans/salida-de-emergencia-design.md).
//
// Direct mode: user pays gas, transactions go straight to public BSC RPCs
// with failover — zero GraphQL, zero relay. This intentionally REPLACES
// the app's server-relay transport (bscServerRpc) for the duration of the
// exit: routing an emergency through Confío infrastructure would defeat
// its purpose.
//
// Redeem-first policy: "permissionless ≠ accessible" — external wallets
// have no UI for redeemToUsdt, so the default exit converts cUSD+ into
// plain USDT-BSC before it leaves. redeemToUsdt(shares, minOut, to) pays
// USDT DIRECTLY to the destination (verified permissionless, only the
// raw-USDY redeem is owner-gated). Fallback when the Ondo leg is dead:
// raw cUSD+ transfer, flagged to the caller so the screen can warn.
//
// Resumable: every completed step records its tx hash in the injected KV
// store; re-running skips completed steps and re-reads live balances so
// a crash mid-exit never double-spends or strands a leg.

import {
  bscBnbBalance,
  bscGasPrice,
  bscEthCall,
  sendCall,
  selector,
  encodeUint,
  encodeAddress,
  setBscTransport,
  DerivedEvmWallet,
} from '../evmWallet';
import { USDT_BSC } from '../cusdPlusVault';
import { CHAIN_ENDPOINTS } from './chainClock';
import type { KVStore } from './reachability';

// Bundled chain wiring (design doc: "token addresses/ABIs ship in the app
// bundle") — in an outage the config query that normally serves the vault
// address is dead. Verified against config/settings.py default AND
// contracts/cusd_plus/DEPLOYMENT.md (ERC1967 proxy) on 2026-07-22.
export const BUNDLED_VAULT_ADDRESS = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1';

// ── Direct failover transport ───────────────────────────────────────────

const rpcCall = async (rpc: string, method: string, params: unknown[]): Promise<any> => {
  const res = await fetch(rpc, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  if (!res.ok) throw new Error(`bsc rpc http ${res.status}`);
  const json = await res.json();
  if (json.error) throw new Error(`bsc rpc: ${json.error.message}`);
  return json.result;
};

const failover = async (method: string, params: unknown[]): Promise<any> => {
  let lastErr: unknown;
  for (const rpc of CHAIN_ENDPOINTS.BSC_RPCS) {
    try {
      return await rpcCall(rpc, method, params);
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error('all BSC RPCs failed');
};

/**
 * Install the emergency transport (public RPCs, failover). Returns a
 * restore function — call it after the exit so normal app flows go back
 * to the server relay.
 */
export const installEmergencyBscTransport = (): (() => void) => {
  setBscTransport({
    read: failover,
    submit: (rawTx: string) => failover('eth_sendRawTransaction', [rawTx]),
  });
  return () => setBscTransport(null); // null = evmWallet's direct default; relay reinstalls on next savings use
};

// ── Balances / plan ─────────────────────────────────────────────────────

const erc20Balance = async (token: string, addr: string): Promise<bigint> => {
  const ret = await bscEthCall(token, selector('balanceOf(address)') + encodeAddress(addr));
  return BigInt(ret === '0x' ? 0 : ret);
};

export interface BscExitPlan {
  cusdPlusShares: bigint;
  usdtWei: bigint;
  bnbWei: bigint;
  steps: Array<'redeemCusdPlus' | 'transferUsdt'>;
}

export const planBscExit = async (address: string, vaultAddress: string): Promise<BscExitPlan> => {
  const [cusdPlusShares, usdtWei, bnbWei] = await Promise.all([
    erc20Balance(vaultAddress, address),
    erc20Balance(USDT_BSC, address),
    bscBnbBalance(address),
  ]);
  const steps: BscExitPlan['steps'] = [];
  if (cusdPlusShares > 0n) steps.push('redeemCusdPlus');
  // USDT step re-reads the live balance at execution time, so it also
  // carries whatever the redeem just delivered if redeem paid the user
  // (it pays the destination directly — this step covers pre-held USDT).
  if (usdtWei > 0n) steps.push('transferUsdt');
  // Deliberately NO BNB sweep (decision 2026-07-22, mirrors Algorand):
  // user BNB ≈ sponsor dust + a Direct-mode gas top-up's leftover cents.
  // Sweeping would leak sponsor dust through polished UI and strip the
  // account of gas it may need for stray future deposits to the old
  // address. Zero native outflow ⇒ zero farming-detector interaction.
  return { cusdPlusShares, usdtWei, bnbWei, steps };
};

/** BNB the user must hold for Direct-mode gas, for the top-up screen. */
export const estimateBscExitGasWei = async (plan: BscExitPlan): Promise<bigint> => {
  let gasPrice = await bscGasPrice();
  if (gasPrice < 100_000_000n) gasPrice = 100_000_000n;
  gasPrice = (gasPrice * 12n) / 10n;
  let units = 0n;
  if (plan.steps.includes('redeemCusdPlus')) units += 700_000n; // IM redeem path, measured-class budget
  if (plan.steps.includes('transferUsdt')) units += 80_000n;
  return gasPrice * units;
};

// ── Execution ───────────────────────────────────────────────────────────

export interface BscExitResult {
  completed: string[];
  txids: Record<string, string>;
  /** Steps skipped because their leg is dead (screen must warn + offer raw fallback). */
  degraded: string[];
}

const ckKey = (accountKey: string, dest: string) =>
  `confio_emergency_bsc_ck_v1_${accountKey}_${dest.toLowerCase()}`;

const loadCk = async (store: KVStore, key: string): Promise<Record<string, string>> => {
  const raw = await store.get(key);
  try { return raw ? JSON.parse(raw) : {}; } catch { return {}; }
};

export const executeBscExit = async (params: {
  wallet: DerivedEvmWallet;
  dest: string;
  vaultAddress: string;
  /** Slippage floor for the IM redeem; caller derives from displayed value. */
  minUsdtOutWei: bigint;
  accountKey: string;
  store: KVStore;
}): Promise<BscExitResult> => {
  const { wallet, dest, vaultAddress, store, accountKey } = params;
  if (!/^0x[0-9a-fA-F]{40}$/.test(dest)) throw new Error('bad destination address');
  if (dest.toLowerCase() === wallet.address.toLowerCase()) throw new Error('destination is own address');

  const restore = installEmergencyBscTransport();
  const key = ckKey(accountKey, dest);
  const ck = await loadCk(store, key);
  const completed: string[] = [];
  const degraded: string[] = [];

  const record = async (step: string, txid: string) => {
    ck[step] = txid;
    await store.set(key, JSON.stringify(ck));
    completed.push(step);
  };

  try {
    // 1. cUSD+ → USDT paid straight to the destination.
    if (!ck.redeemCusdPlus) {
      const shares = await erc20Balance(vaultAddress, wallet.address);
      if (shares > 0n) {
        try {
          const receipt = await sendCall({
            from: wallet.address,
            privKeyHex: wallet.privKeyHex,
            to: vaultAddress,
            data:
              selector('redeemToUsdt(uint256,uint256,address)') +
              encodeUint(shares) +
              encodeUint(params.minUsdtOutWei) +
              encodeAddress(dest),
            gasLimit: 700_000n,
          });
          await record('redeemCusdPlus', receipt.transactionHash);
        } catch (e) {
          // Ondo leg dead (paused vault, tripped guard, IM outage): fall
          // back to a raw share transfer so value at least MOVES, and
          // surface the degradation for the screen's warning.
          const receipt = await sendCall({
            from: wallet.address,
            privKeyHex: wallet.privKeyHex,
            to: vaultAddress,
            data: selector('transfer(address,uint256)') + encodeAddress(dest) + encodeUint(shares),
            gasLimit: 120_000n,
          });
          await record('redeemCusdPlus', receipt.transactionHash);
          degraded.push('redeemCusdPlus');
        }
      } else {
        await record('redeemCusdPlus', 'skipped_zero');
      }
    }

    // 2. Pre-held USDT (live re-read — never trust the plan snapshot).
    if (!ck.transferUsdt) {
      const usdt = await erc20Balance(USDT_BSC, wallet.address);
      if (usdt > 0n) {
        const receipt = await sendCall({
          from: wallet.address,
          privKeyHex: wallet.privKeyHex,
          to: USDT_BSC,
          data: selector('transfer(address,uint256)') + encodeAddress(dest) + encodeUint(usdt),
          gasLimit: 80_000n,
        });
        await record('transferUsdt', receipt.transactionHash);
      } else {
        await record('transferUsdt', 'skipped_zero');
      }
    }

  } finally {
    restore();
  }

  return { completed, txids: ck, degraded };
};
