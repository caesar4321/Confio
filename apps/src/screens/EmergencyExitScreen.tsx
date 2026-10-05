// Salida de emergencia — move everything to the user's own wallet if Confío
// stops operating (docs/plans/salida-de-emergencia-design.md § Phase 3).
//
// ONE trigger: the on-chain ConfioHeartbeat. Confío beats daily; once the
// chain has gone silenceRequired (14 days) without a beat, the exit opens for
// everyone. No ban route, no Confío Face, no waiting periods, no client-judged
// outages. The screen only READS the heartbeat (heartbeat.ts); enforcement is
// on-chain — every exit transaction runs assertSilent() first, in the same
// atomic batch (gatedTx.ts), so nothing here can move money early.
//
// While Confío beats, the screen explains the safeguard and how to prepare.
// Once open, a 4-step WIZARD (one decision per screen, internal state — this
// screen lives in BOTH stacks and the recovery-only boot route):
// Paso 1 cuenta+comisión → Paso 2 destino → Paso 3 checklist → Paso 4
// resumen+ejecución.
//
// Execution is Direct mode (user gas, public RPCs, zero GraphQL) and moves
// USER ASSETS ONLY — no close-outs, no native sweeps (engine invariants).
// BSC only: Algorand balances are not part of the exit.

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  StatusBar,
  Modal,
  KeyboardAvoidingView,
  Platform,
  Linking,
  Alert,
} from 'react-native';
import { Text, TextInput } from '../components/common/AppText';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { colors } from '../config/theme';
import Clipboard from '@react-native-clipboard/clipboard';
import { AddressScannerModal } from '../components/AddressScannerModal';
import { evmAccountKey, getEvmAddressForDisplay, getActiveEvmWallet } from '../services/secureDeterministicWallet';
import { biometricAuthService } from '../services/biometricAuthService';
import { emergencyStore } from '../services/emergencyExit/store';
import { wrongNetworkMessage } from '../utils/addressNetwork';
import {
  RosterAccount, rosterAccountKey, getAccountRoster, exitableAccounts,
} from '../services/emergencyExit/accountRoster';
import {
  readHeartbeat, HeartbeatStatus, isConfioAlive,
} from '../services/emergencyExit/heartbeat';
import {
  executeBscExit, planBscExit, estimateBscExitGasWei,
  installEmergencyBscTransport, BUNDLED_VAULT_ADDRESS, BUNDLED_CUSD_ADDRESS, BscExitResult, BscExitStep,
} from '../services/emergencyExit/bscExit';
import { isOutcomeUnknown } from '../services/evmWallet';
import { LoadingOverlay } from '../components/LoadingOverlay';
import { formatDecimal } from '../utils/numberLocale';
import { formatLocalDateTime } from '../utils/dateUtils';

const EVM_ADDR_RE = /^0x[0-9a-fA-F]{40}$/;

// Wizard step headers — the ONE decision each screen asks for.
const WIZARD_STEPS = [
  { title: 'Tu cuenta y la comisión', sub: 'Elige qué cuenta retiras y revisa que tengas para la comisión de red.' },
  { title: '¿A dónde va tu dinero?', sub: 'Una billetera que sea tuya, en BNB Smart Chain.' },
  { title: 'Confirma que estás a salvo', sub: 'Cuatro confirmaciones. Tómate tu tiempo.' },
  { title: 'Revisa y mueve tu dinero', sub: 'Último paso — el envío se firma con tu biometría.' },
];

const CHECKLIST = [
  'Estoy solo/a. Nadie me está mirando ni guiándome.',
  'No estoy en una llamada ni compartiendo pantalla.',
  'Nadie — ni una financiera, ni "soporte de Confío", ni un familiar — me pidió hacer esto.',
  'La billetera de destino es MÍA y yo controlo sus claves.',
];

// Human names for engine step ids — raw ids are for support, not users.
const STEP_NAMES: Record<string, string> = {
  redeemCusdPlus: 'Canjear tu ahorro por USDT',
  redeemCusd: 'Canjear tus dólares por USDT',
  transferUsdt: 'Enviar USDT',
  transferConfio: 'Enviar CONFIO',
};
const stockSymbolFromStep = (id: string): string | null =>
  id.startsWith('ondoStock:') ? (id.split(':')[1] || 'Ondo Stock') : null;
const stepName = (id: string): string => {
  const symbol = stockSymbolFromStep(id);
  return symbol ? `Enviar ${symbol}` : STEP_NAMES[id] ?? id;
};

// What the blocking overlay says while each send is in flight. The exit is
// multiple transactions on public RPCs — silence here is what made the first
// drill feel broken.
const STEP_WAIT: Record<string, string> = {
  redeemCusdPlus: 'Canjeando tu ahorro por USDT…',
  redeemCusd: 'Canjeando tus dólares por USDT…',
  transferUsdt: 'Enviando tu USDT…',
  transferConfio: 'Enviando tu CONFIO…',
};
const stepWait = (step: BscExitStep): string => {
  const symbol = stockSymbolFromStep(step);
  return symbol ? `Enviando tus acciones ${symbol}…` : STEP_WAIT[step] ?? 'Enviando tus fondos…';
};

// USDT-BSC is 18 decimals. Two decimals is the app's dollar grammar.
const fmtUsdt = (wei: string): string =>
  formatDecimal(Number(BigInt(wei) / 10n ** 12n) / 1e6);

// Durations in the app's plain Spanish: "9 días y 3 h", "5 h", "menos de 1 h".
const fmtDuration = (sec: number): string => {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  if (d > 0) return h > 0 ? `${d} ${d === 1 ? 'día' : 'días'} y ${h} h` : `${d} ${d === 1 ? 'día' : 'días'}`;
  return h > 0 ? `${h} h` : 'menos de 1 h';
};
const fmtChainDate = (sec: number): string => formatLocalDateTime(new Date(sec * 1000).toISOString());

const truncAddr = (a: string): string => (a.length > 20 ? `${a.slice(0, 8)}…${a.slice(-6)}` : a);

export const EmergencyExitScreen: React.FC<{ onClose?: () => void }> = ({ onClose }) => {
  const navigation = useNavigation<any>();
  const leaveScreen = () => {
    if (onClose) onClose();
    else navigation.goBack();
  };
  // Account context comes from the KEYCHAIN (AuthService) and the local
  // roster mirror (accountRoster), never from server-hydrated accounts: a
  // banned user's GetUserAccounts 403s, so anything depending on
  // activeAccount would silently never render — exactly what hid the gas
  // card during the first ban drill. The roster lets the user sweep EVERY
  // owned account (personal + businesses), one at a time; V2 derivation
  // makes each context's keys fully local.
  const [roster, setRoster] = useState<RosterAccount[]>([]);
  const [selCtx, setSelCtx] = useState<RosterAccount | null>(null);
  const [accountKey, setAccountKey] = useState('');

  // On-chain heartbeat — the only thing that opens the exit.
  const [hb, setHb] = useState<HeartbeatStatus | null>(null);
  const [evaluating, setEvaluating] = useState(true);

  const [evmAddress, setEvmAddress] = useState<string | null>(null);
  // Gas shortfall, null = still reading.
  const [bscGasShortWei, setBscGasShortWei] = useState<bigint | null>(null);
  const [gasChecking, setGasChecking] = useState(false);
  // Address the in-flight gas read belongs to (account switches race it).
  const gasAddrRef = useRef<string | null>(null);

  const [bscDest, setBscDest] = useState('');
  const [scanVisible, setScanVisible] = useState(false);
  // QR on demand, in a modal — a big code scans reliably.
  const [qrModal, setQrModal] = useState<{ chain: string; address: string } | null>(null);
  const [checks, setChecks] = useState<boolean[]>(CHECKLIST.map(() => false));

  const [bscRunning, setBscRunning] = useState(false);
  const [bscResult, setBscResult] = useState<BscExitResult | null>(null);
  const [bscError, setBscError] = useState<string | null>(null);
  const [bscPending, setBscPending] = useState(false);
  const [bscPendingTx, setBscPendingTx] = useState<string | null>(null);
  // What the overlay is currently waiting on (null = generic).
  const [bscPhase, setBscPhase] = useState<string | null>(null);
  // Destination as it was at execution time — the result card must not
  // re-read the editable input.
  const [sentTo, setSentTo] = useState<string | null>(null);
  // The gate closed mid-exit AFTER some legs already moved (Confío beat again).
  const [closedMidway, setClosedMidway] = useState(false);

  // Wizard step within the eligible flow (0..3). Internal state, not
  // routes — one decision per screen without any navigation plumbing.
  const [wStep, setWStep] = useState(0);
  const scrollRef = useRef<ScrollView>(null);
  const goToStep = (s: number) => {
    setWStep(s);
    scrollRef.current?.scrollTo({ y: 0, animated: false });
  };

  const evaluate = useCallback(async () => {
    setEvaluating(true);
    try {
      setHb(await readHeartbeat().catch((): HeartbeatStatus => ({ state: 'unreachable' })));
    } finally {
      setEvaluating(false);
    }
  }, []);

  useEffect(() => { evaluate(); }, [evaluate]);

  // Load the exitable-account roster (local mirror) and select the active
  // context — or personal, when the active context is an employee business
  // this device can't exit.
  useEffect(() => {
    (async () => {
      try {
        const { AuthService } = await import('../services/authService');
        const ctx = await AuthService.getInstance().getActiveAccountContext();
        const list = exitableAccounts(await getAccountRoster(emergencyStore));
        setRoster(list);
        const activeKey = rosterAccountKey({ type: ctx.type ?? 'personal', businessId: ctx.businessId, index: ctx.index ?? 0 });
        setSelCtx(list.find((a) => rosterAccountKey(a) === activeKey) ?? list[0]);
      } catch (e) {
        console.warn('[EmergencyExit] roster load failed', e);
        setSelCtx({ type: 'personal', index: 0, name: 'Personal' });
      }
    })();
  }, []);

  // Live gas status for one address, off public RPCs (all of this must work
  // exactly when Confío doesn't). Deliberately SEPARATE from the
  // account-change effect: depositing BNB is the one action the user takes
  // while sitting on this screen, so ↻ has to be able to turn "te falta"
  // into "listo" without switching accounts or leaving.
  const refreshGas = useCallback(async (address?: string | null) => {
    const addr = address ?? evmAddress;
    if (!addr) return;
    setGasChecking(true);
    const restore = installEmergencyBscTransport();
    try {
      const plan = await planBscExit(addr, BUNDLED_VAULT_ADDRESS, BUNDLED_CUSD_ADDRESS);
      // A late reply for a since-abandoned account must not overwrite the
      // current one's status.
      if (gasAddrRef.current !== addr) return;
      if (!plan.steps.length) { setBscGasShortWei(0n); return; }
      const need = await estimateBscExitGasWei(plan);
      if (gasAddrRef.current !== addr) return;
      setBscGasShortWei(plan.bnbWei >= need ? 0n : need - plan.bnbWei);
    } catch { /* status shows as unverified; execution re-checks anyway */ } finally {
      restore();
      // Always clear: a guarded clear can strand the spinner forever when
      // the next account has no address to read.
      setGasChecking(false);
    }
  }, [evmAddress]);

  // Resolve the SELECTED account's address (local V2 derivation, with the
  // per-account stored address as legacy fallback), then read its gas.
  useEffect(() => {
    if (!selCtx) return;
    let stale = false;
    (async () => {
      setAccountKey(rosterAccountKey(selCtx));
      setEvmAddress(null);
      setBscGasShortWei(null);
      gasAddrRef.current = null;
      // Results/errors belong to the previously selected account.
      setBscResult(null); setBscError(null); setBscPending(false); setBscPendingTx(null); setSentTo(null); setClosedMidway(false);
      try {
        const ctx = { type: selCtx.type, index: selCtx.index, businessId: selCtx.businessId } as const;
        const { deriveAddressesForContext } = await import('../services/secureDeterministicWallet');
        const derived = await deriveAddressesForContext(ctx);

        let evmAddr = derived.evm;
        if (!evmAddr) {
          evmAddr = await getEvmAddressForDisplay(evmAccountKey({
            accountType: selCtx.type,
            accountIndex: selCtx.index,
            businessId: selCtx.businessId,
          }));
        }
        if (stale) return;
        setEvmAddress(evmAddr);
        gasAddrRef.current = evmAddr;
        if (evmAddr) await refreshGas(evmAddr);
      } catch (e) {
        console.warn('[EmergencyExit] address resolution failed', e);
      }
    })();
    return () => { stale = true; };
    // refreshGas is intentionally omitted: it closes over evmAddress, which
    // this effect sets — including it would re-derive on every read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selCtx]);

  const allChecked = checks.every(Boolean);
  const bscDestValid =
    EVM_ADDR_RE.test(bscDest.trim()) &&
    bscDest.trim().toLowerCase() !== (evmAddress ?? '').toLowerCase();
  const eligible = hb?.state === 'open';
  const offline = hb?.state === 'unreachable';

  const runBsc = async () => {
    // The phone's own biometric guards the send. Nothing server-side is asked:
    // by definition Confío is gone when this runs.
    if (!(await biometricAuthService.authenticateEmergencyExit(
      'Confirmar salida de emergencia (BNB Smart Chain)'))) return;
    const exitCtx = selCtx ? { type: selCtx.type, index: selCtx.index, businessId: selCtx.businessId } : undefined;
    const dest = bscDest.trim();
    setBscRunning(true); setBscError(null); setBscPending(false); setBscPendingTx(null); setBscPhase(null); setSentTo(dest);
    setClosedMidway(false);
    try {
      const wallet = await getActiveEvmWallet(exitCtx);
      const result = await executeBscExit({
        wallet,
        dest,
        vaultAddress: BUNDLED_VAULT_ADDRESS,
        cusdAddress: BUNDLED_CUSD_ADDRESS,
        minUsdtOutWei: 0n, // oracle guard + fully-backed assert protect pricing; IM has no book
        accountKey,
        store: emergencyStore,
        onStep: (step: BscExitStep) => setBscPhase(stepWait(step)),
      });
      setBscResult(result);
      // The result card carries the degraded case (headline + explanation);
      // an Alert on top of it would just be a second thing to dismiss.
    } catch (e: any) {
      if (isConfioAlive(e)) {
        const partial = (e as any)?.partialResult as BscExitResult | undefined;
        const gateState = (e as any)?.status?.state;
        const confioBack = gateState === 'alive' || gateState === 'quiet';
        if (partial?.sentNow.length && !confioBack) {
          // The heartbeat could not be READ (e.g. the phone lost data) after
          // some legs landed. Nothing says Confío is back: show what moved
          // and keep the retry — it re-reads the gate before every send.
          setBscResult(partial);
          setBscError('No pudimos leer la señal de Confío en la blockchain. Lo que ya se envió está abajo; revisa tu conexión');
        } else if (partial?.sentNow.length) {
          // Some legs landed before the gate closed: show exactly those
          // receipts under a "closed midway" headline — never "Listo".
          setBscResult(partial);
          setClosedMidway(true);
        } else {
          // Nothing moved: drop back to the live (closed) state, no result card.
          setBscResult(null);
          Alert.alert(
            gateState === 'alive' || gateState === 'quiet' ? 'La salida se cerró' : 'No pudimos verificar la salida',
            gateState === 'alive' || gateState === 'quiet'
              ? 'Confío volvió a publicar su señal, así que la blockchain no permite la salida. No se movió nada; tu dinero sigue en tu cuenta.'
              : 'No pudimos leer la señal de Confío en la blockchain. No se movió nada. Revisa tu conexión e inténtalo de nuevo.',
          );
        }
        await evaluate();
      } else if (isOutcomeUnknown(e)) {
        if (e?.partialResult) setBscResult(e.partialResult as BscExitResult);
        setBscPending(true);
        setBscPendingTx(typeof e?.txHash === 'string' ? e.txHash : null);
        setBscError('La transacción fue enviada, pero la red aún no confirmó el resultado.');
      } else {
        if (e?.partialResult) setBscResult(e.partialResult as BscExitResult);
        setBscError(e?.message || String(e));
      }
    } finally {
      setBscRunning(false);
      setBscPhase(null);
      // Land on the outcome, not on the button that produced it.
      scrollRef.current?.scrollTo({ y: 0, animated: true });
    }
  };

  // ── Hero state: the emotional core of the screen ──────────────────────
  const hero = (() => {
    if (evaluating && !hb) {
      return { label: 'Verificando…', sub: 'Consultando la blockchain', tone: 'neutral' as const };
    }
    const since = hb?.lastBeatSec != null && hb.chainNowSec != null ? hb.chainNowSec - hb.lastBeatSec : 0;
    switch (hb?.state) {
      case 'open':
        return {
          label: 'La salida está abierta',
          sub: `Confío no publica su señal desde el ${fmtChainDate(hb.lastBeatSec!)}. Tu dinero está en la blockchain, y desde aquí puedes moverlo a una billetera tuya.`,
          tone: 'alert' as const,
        };
      case 'quiet':
        return {
          label: 'Confío no da señales',
          sub: `Hace ${fmtDuration(since)} que Confío no publica su señal. Si llega a ${fmtDuration(hb.silenceSec!)}, esta salida se abre para todos. Tu dinero está en la blockchain, intacto.`,
          tone: 'warn' as const,
        };
      case 'unreachable':
        return {
          label: 'Sin conexión con la blockchain',
          sub: 'No pudimos leer la señal de Confío. Revisa tu conexión e inténtalo de nuevo.',
          tone: 'neutral' as const,
        };
      case 'invalid':
      case 'not_configured':
        return {
          label: 'Salida de emergencia',
          sub: 'Esta versión de la app no puede verificar la señal de Confío. Actualiza la app para ver el estado.',
          tone: 'neutral' as const,
        };
      case 'alive':
        return {
          label: 'Tu respaldo si Confío deja de operar',
          sub: 'Confío funciona con normalidad. Esta salida solo se abre si Confío deja de operar.',
          tone: 'ok' as const,
        };
      default:
        // Nothing read yet: never claim Confío is fine without the chain saying so.
        return { label: 'Verificando…', sub: 'Consultando la blockchain', tone: 'neutral' as const };
    }
  })();

  // ── Stage: 1 = closed (explain + prepare), 2 = open wizard / outcome ──
  const anyResult = !!bscResult || bscPending;
  // Silence period as the CHAIN states it (owner-tunable), 14 days at launch.
  const silenceText = fmtDuration(hb?.silenceSec ?? 14 * 86400);
  const stage = eligible || anyResult ? 2 : 1;

  // The heartbeat itself, in plain words: when Confío last signalled and
  // when the exit would open if it never does again.
  const renderSignalCard = () => {
    if (!hb || hb.lastBeatSec == null || hb.opensAtSec == null || hb.chainNowSec == null) return null;
    const quiet = hb.state === 'quiet';
    return (
      <View style={styles.card}>
        <View style={styles.stepHeader}>
          <View style={styles.stepBadge}>
            <Icon name={quiet ? 'clock' : 'activity'} size={13} color={colors.white} />
          </View>
          <Text style={styles.cardTitle}>Señal de Confío</Text>
        </View>
        <View style={styles.summaryRow}>
          <Icon name="radio" size={14} color={colors.text.secondary} />
          <Text style={styles.summaryText}>
            Última señal: {fmtChainDate(hb.lastBeatSec)} (hace {fmtDuration(hb.chainNowSec - hb.lastBeatSec)})
          </Text>
        </View>
        {quiet ? (
          <>
            <Text style={styles.countdownText}>{fmtDuration(hb.opensAtSec - hb.chainNowSec)}</Text>
            <Text style={styles.bodyText}>
              para que la salida se abra, el {fmtChainDate(hb.opensAtSec)}, si Confío no
              vuelve a dar señales.
            </Text>
          </>
        ) : (
          <Text style={styles.bodyText}>
            Confío publica esta señal todos los días. Mientras siga llegando, la
            salida permanece cerrada.
          </Text>
        )}
      </View>
    );
  };

  const gasStatusLine = (short: bigint | null, fmt: (v: bigint) => string) => {
    if (gasChecking) return { icon: 'refresh-cw', color: colors.text.secondary, text: 'Verificando tu saldo para la comisión…' };
    if (short === null) return { icon: 'help-circle', color: colors.text.secondary, text: 'No se pudo verificar — si un envío falla por comisiones, deposita un poco aquí.' };
    if (short === 0n) return { icon: 'check-circle', color: colors.primaryDark, text: 'Comisiones listas' };
    return { icon: 'alert-circle', color: colors.warning.text, text: `Falta ≈ ${fmt(short)}` };
  };

  // ALWAYS visible: this address is the user's lifeline in Direct mode.
  // Hiding it when the balance looks sufficient proved too clever — and
  // under a ban the reads can fail entirely, which must not make the
  // address vanish. The QR renders on demand, in a modal, where a big
  // code scans reliably.
  const renderChainGasRow = (
    chain: string,
    address: string,
    status: { icon: string; color: string; text: string },
  ) => (
    <View style={styles.gasChainBlock}>
      {/* Chain name and status stacked — side by side they fight for width
          and the status shatters into a one-word-per-line column. */}
      <Text style={styles.gasChain}>{chain}</Text>
      <View style={styles.gasStatusRow}>
        <Icon name={status.icon} size={14} color={status.color} style={{ marginTop: 2 }} />
        <Text style={[styles.gasAmount, { color: status.color }]}>{status.text}</Text>
      </View>
      <View style={styles.addrRow}>
        <Text style={[styles.addrText, { flex: 1, fontSize: 12 }]} numberOfLines={1}>
          {truncAddr(address)}
        </Text>
        <TouchableOpacity style={styles.copyBtn} onPress={() => Clipboard.setString(address)}>
          <Icon name="copy" size={12} color={colors.primaryDark} />
          <Text style={styles.copyBtnText}>Copiar</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.copyBtn} onPress={() => setQrModal({ chain, address })}>
          <Icon name="grid" size={12} color={colors.primaryDark} />
          <Text style={styles.copyBtnText}>QR</Text>
        </TouchableOpacity>
      </View>
    </View>
  );

  const renderGasCards = () => {
    const bsc = gasStatusLine(bscGasShortWei, (v) => `${formatDecimal(Number(v) / 1e18, { decimals: 5 })} BNB`);
    return (
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Comisión de red</Text>
        <Text style={styles.bodyText}>
          Si conviertes cUSD o cUSD+ a USDT, el contrato descuenta además la
          comisión de conversión de Confío, actualmente de hasta 0,9%. Esta
          comisión es distinta del gas de la red.
        </Text>
        <Text style={styles.bodyText}>
          La red de blockchain cobra una pequeña comisión por enviar — como
          una estampilla postal — y la cobra en su propia moneda: BNB, la
          moneda de BNB Smart Chain.
        </Text>
        <Text style={styles.bodyText}>
          Normalmente Confío paga esa comisión por ti. Sin nuestros
          servidores, sale de TU dirección. Si te falta, deposita BNB aquí:
        </Text>
        {!!evmAddress && renderChainGasRow('Red BNB Smart Chain (BNB)', evmAddress, bsc)}
        {!evmAddress && (
          <Text style={styles.bodyText}>Cargando tu dirección…</Text>
        )}
        {/* Depositing BNB happens in ANOTHER app, so the user comes back
            needing exactly this. The header ↻ also does it, but nobody
            hunts for a header icon after pasting an address elsewhere. */}
        {!!evmAddress && (
          <TouchableOpacity
            style={styles.gasRecheck}
            onPress={() => refreshGas()}
            disabled={gasChecking}
          >
            <Icon name="refresh-cw" size={13} color={colors.primaryDark} />
            <Text style={styles.gasRecheckText}>
              {gasChecking ? 'Verificando…' : 'Ya deposité — verificar de nuevo'}
            </Text>
          </TouchableOpacity>
        )}
      </View>
    );
  };

  // ── Outcome ───────────────────────────────────────────────────────────
  // A blocking overlay covers the run, so whatever renders here is FINAL.
  // The exit's whole promise is "you don't have to trust us", which fails
  // if the user can't tell what happened — so the answer is a headline,
  // not a list of hashes. Explorer links stay, demoted to verification.
  // Read sentNow, NEVER txids: txids can replay hashes from an interrupted
  // earlier attempt, and a headline built on those claimed "tu dinero
  // salió" for a run that broadcast nothing at all.
  const outcome: 'none' | 'error' | 'pending' | 'closed' | 'partial' | 'empty' | 'already' | 'degraded' | 'ok' = (() => {
    if (closedMidway) return 'closed';
    if (bscPending) return 'pending';
    if (bscError) return 'error';
    if (!bscResult) return 'none';
    if (bscResult.unresolved.length) return 'partial';
    if (!bscResult.sentNow.length) {
      // Nothing broadcast now. Either the account was empty, or this is a
      // re-tap on an attempt whose sends already went through — those are
      // different facts and must not share a headline.
      const done = Object.values(bscResult.txids).some((t) => !t.startsWith('skipped'));
      return done ? 'already' : 'empty';
    }
    return bscResult.degraded.length ? 'degraded' : 'ok';
  })();

  const OUTCOME_COPY = {
    closed: {
      icon: 'alert-triangle', tone: colors.warning.text,
      title: 'La salida se cerró a mitad',
    },
    ok: {
      icon: 'check-circle', tone: colors.primaryDark,
      title: 'Listo. Tu dinero salió de Confío',
    },
    degraded: {
      icon: 'alert-circle', tone: colors.warning.text,
      title: 'Tu dinero salió, pero sin canjear',
    },
    partial: {
      icon: 'alert-triangle', tone: colors.warning.text,
      title: 'Parte del saldo sigue en esta cuenta',
    },
    empty: {
      icon: 'info', tone: colors.text.secondary,
      title: 'No había nada que mover',
    },
    already: {
      icon: 'check-circle', tone: colors.text.secondary,
      title: 'Ya se había enviado',
    },
    error: {
      icon: 'x-circle', tone: colors.error.text,
      title: 'No se pudo completar',
    },
    pending: {
      icon: 'clock', tone: colors.warning.text,
      title: 'La transacción sigue pendiente',
    },
  } as const;

  const outcomeSub = (): string => {
    const to = truncAddr(sentTo ?? bscDest.trim());
    switch (outcome) {
      case 'ok': {
        // '0' means this run proved no amount (resumed run, or the chain
        // didn't log a credit) — say what moved without inventing a number.
        const wei = bscResult?.usdtToDest ?? '0';
        const stocksSent = bscResult?.sentNow.some((step) => step.startsWith('ondoStock:'));
        const stocks = stocksSent ? ' y tus acciones Ondo' : '';
        return wei !== '0'
          ? `Enviamos $${fmtUsdt(wei)} USDT${stocks} a ${to}. Puede tardar un minuto en aparecer en tu billetera.`
          : `Enviamos tu saldo${stocks} a ${to}. Puede tardar un minuto en aparecer en tu billetera.`;
      }
      case 'degraded': {
        const stocksSent = bscResult?.sentNow.some((step) => step.startsWith('ondoStock:'));
        const plus = bscResult?.degraded.includes('redeemCusdPlus');
        const cusd = bscResult?.degraded.includes('redeemCusd');
        const raw = plus && cusd ? 'cUSD+ y cUSD' : plus ? 'cUSD+' : 'cUSD';
        const reason = plus ? 'el canje no respondió' : 'el contrato no permitió el canje';
        return `Tus dólares no pudieron canjearse por USDT (${reason}), así que enviamos ${raw} sin canjear${stocksSent ? ' junto con tus acciones Ondo' : ''} a ${to}. Son tuyos: para canjearlos necesitarás una herramienta externa.`;
      }
      case 'partial':
        return `Enviamos todo lo que la red permitió, pero ${bscResult?.unresolved.join(', ')} sigue en esta cuenta. Reintenta: los envíos ya confirmados no se repetirán.`;
      case 'already':
        return bscResult?.degraded.includes('redeemCusdPlus') || bscResult?.degraded.includes('redeemCusd')
          ? 'El intento anterior envió parte de tus dólares sin canjear. No se repitió el envío; puedes comprobarlo abajo.'
          : 'Los envíos de este intento ya se habían hecho, así que no se repitieron. Puedes comprobarlos abajo.';
      case 'empty':
        return 'Esta cuenta no tenía saldo en BNB Smart Chain. No se envió ninguna transacción y no se cobró ninguna comisión.';
      case 'closed':
        return `Confío volvió a publicar su señal y la blockchain detuvo la salida. Lo que se alcanzó a enviar llegó a ${to} (compruébalo abajo); el resto sigue en tu cuenta.`;
      case 'pending':
        return 'La red recibió la transacción, pero no confirmó el resultado a tiempo. Compruébala en BscScan antes de volver a intentar para no enviar dos veces.';
      default:
        return `${bscError} — puedes reintentar; los pasos completados no se repiten.`;
    }
  };

  // Retry after an error doesn't wait for a fresh "open" read (see the button).
  const canRun = outcome === 'error' || (eligible && !offline);

  // Nothing left to send for this account+destination.
  const exitDone = outcome === 'ok' || outcome === 'degraded' || outcome === 'already' || outcome === 'pending' || outcome === 'closed';

  const renderOutcome = () => {
    if (outcome === 'none') return null;
    const copy = OUTCOME_COPY[outcome];
    return (
      <View style={styles.card}>
        <View style={styles.outcomeHead}>
          <Icon name={copy.icon} size={40} color={copy.tone} />
          <Text style={[styles.outcomeTitle, { color: copy.tone }]}>{copy.title}</Text>
          <Text style={styles.outcomeSub}>{outcomeSub()}</Text>
        </View>
        {!!bscResult && outcome !== 'empty' && (
          <>
            <Text style={styles.verifyLabel}>Compruébalo tú mismo</Text>
            {renderProgress(bscResult, (tx) => `https://bscscan.com/tx/${tx}`)}
          </>
        )}
        {outcome === 'pending' && bscPendingTx && (
          <TouchableOpacity
            style={styles.progressRow}
            onPress={() => Linking.openURL(`https://bscscan.com/tx/${bscPendingTx}`).catch(() => {})}
          >
            <Icon name="external-link" size={15} color={colors.primaryDark} />
            <Text style={styles.progressText}>Ver transacción pendiente en BscScan</Text>
          </TouchableOpacity>
        )}
      </View>
    );
  };

  // Per-step explorer links. Progress/failure narration moved to the
  // overlay and the outcome card — this is now purely the receipt.
  const renderProgress = (
    result: { txids: Record<string, string>; degraded?: string[] } | null,
    explorerUrl: (tx: string) => string,
  ) => {
    if (!result) return null;
    return (
      <View style={styles.progressBox}>
        {result && Object.entries(result.txids).map(([step, tx]) => {
          const skipped = tx.startsWith('skipped');
          const deg = result.degraded?.includes(step);
          const row = (
            <>
              <Icon
                name={skipped ? 'minus-circle' : deg ? 'alert-circle' : 'check-circle'}
                size={15}
                color={skipped ? colors.text.light : deg ? colors.warning.text : colors.primaryDark}
              />
              <Text style={[styles.progressText, skipped && styles.progressSkipped]}>
                {stepName(step)}{skipped ? ' — sin saldo' : deg ? ' — enviado sin canjear' : ''}
              </Text>
              {!skipped && <Icon name="external-link" size={14} color={colors.primaryDark} />}
            </>
          );
          // Every real send is verifiable on a public explorer — the whole
          // point of the exit is that the user doesn't have to trust us.
          return skipped ? (
            <View key={step} style={styles.progressRow}>{row}</View>
          ) : (
            <TouchableOpacity
              key={step}
              style={styles.progressRow}
              onPress={() => Linking.openURL(explorerUrl(tx)).catch(() => {})}
            >
              {row}
            </TouchableOpacity>
          );
        })}
      </View>
    );
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.heroField }}>
        <View style={styles.header}>
          <BrandFieldBackground id="emergencyField" ringCy="30%" />
          <View style={styles.headerInner}>
            <View style={styles.headerTopRow}>
              <TouchableOpacity
                onPress={() => {
                  // Inside the wizard, ← walks the steps before leaving.
                  if (eligible && wStep > 0) goToStep(wStep - 1);
                  else leaveScreen();
                }}
                style={styles.headerIconBtn}
              >
                <Icon name="arrow-left" size={24} color={colors.white} />
              </TouchableOpacity>
              <Text style={styles.headerTitle}>Salida de emergencia</Text>
              {/* ↻ re-checks BOTH halves of "can I exit right now?": the
                  server/chain state AND the gas balance. */}
              <TouchableOpacity
                onPress={() => { evaluate(); refreshGas(); }}
                style={styles.headerIconBtn}
                disabled={evaluating || gasChecking}
                accessibilityLabel="Actualizar estado y comisión"
              >
                {evaluating || gasChecking
                  ? <ActivityIndicator size="small" color={colors.white} />
                  : <Icon name="refresh-cw" size={18} color={colors.white} />}
              </TouchableOpacity>
            </View>
            <View style={styles.heroWrap}>
              <View style={[styles.heroIconRing, hero.tone === 'alert' && styles.heroIconRingAlert]}>
                <Icon
                  name={hero.tone === 'ok' ? 'shield' : hero.tone === 'warn' ? 'wifi-off' : hero.tone === 'alert' ? 'unlock' : 'loader'}
                  size={26} color={colors.white}
                />
              </View>
              <Text style={styles.heroTitle}>{hero.label}</Text>
              <Text style={styles.heroSub}>{hero.sub}</Text>
            </View>
          </View>
        </View>
      </SafeAreaView>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        {/* The rule, verbatim in every state */}
        <View style={styles.promiseRow}>
          <Icon name="anchor" size={14} color={colors.primaryDark} />
          <Text style={styles.promiseText}>
            La blockchain decide cuándo se abre: {silenceText} sin señal de Confío.
          </Text>
        </View>

        {/* Account sweep: one account at a time, every OWNED account listed
            (local roster mirror — works without the server). Employee
            businesses are excluded: their keys are the owner's. Only on
            wizard Paso 1 — there is nothing to choose while the exit is closed. */}
        {roster.length > 1 && stage === 2 && wStep === 0 && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>¿Qué cuenta retiras?</Text>
            <Text style={styles.bodyText}>
              La salida mueve una cuenta a la vez — cada cuenta tiene sus
              propias direcciones. Repite el proceso para cada una.
            </Text>
            <View style={styles.acctChipsRow}>
              {roster.map((a) => {
                const k = rosterAccountKey(a);
                const sel = selCtx ? rosterAccountKey(selCtx) === k : false;
                return (
                  <TouchableOpacity
                    key={k}
                    style={[styles.acctChip, sel && styles.acctChipSel]}
                    onPress={() => setSelCtx(a)}
                  >
                    <Icon
                      name={a.type === 'personal' ? 'user' : 'briefcase'}
                      size={13}
                      color={sel ? colors.white : colors.primaryDark}
                    />
                    <Text style={[styles.acctChipText, sel && styles.acctChipTextSel]}>{a.name}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>
          </View>
        )}

        {stage === 1 && (
          <>
            {renderSignalCard()}
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Cómo funciona</Text>
              {[
                ['radio', 'Confío publica una señal en la blockchain todos los días.'],
                ['calendar', `Si pasan ${silenceText} sin señal, esta salida se abre para todos los usuarios de Confío.`],
                ['send', 'Entonces mueves tu dinero a una billetera tuya: tu ahorro sale como USDT y tus acciones Ondo se transfieren tal cual.'],
              ].map(([icon, text], i) => (
                <View key={i} style={styles.howRow}>
                  <Icon name={icon as string} size={16} color={colors.primaryDark} />
                  <Text style={styles.howText}>{text}</Text>
                </View>
              ))}
            </View>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Mientras tanto</Text>
              {[
                ['arrow-up-right', 'Para mover tu dinero hoy, usa Enviar como siempre.'],
                ['briefcase', 'Si quieres estar preparado, ten una billetera propia en BNB Smart Chain (por ejemplo, MetaMask). Es donde recibirías tu dinero.'],
                ['info', 'La salida mueve tus saldos en BNB Smart Chain. Los saldos antiguos en Algorand no forman parte de ella.'],
              ].map(([icon, text], i) => (
                <View key={i} style={styles.howRow}>
                  <Icon name={icon as string} size={16} color={colors.primaryDark} />
                  <Text style={styles.howText}>{text}</Text>
                </View>
              ))}
              <View style={styles.scamBox}>
                <Icon name="shield-off" size={15} color={colors.error.text} />
                <Text style={[styles.scamBoxText, { color: colors.error.text }]}>
                  Ni soporte ni nadie puede abrirte esta salida antes de
                  tiempo. Si alguien te ofrece hacerlo, es una estafa.
                </Text>
              </View>
            </View>
          </>
        )}

        {stage === 2 && (
          <>
            {/* Wizard hero: segmented progress + the step's single question. */}
            <View style={styles.stepHero}>
              <View style={styles.progressTrack}>
                {[0, 1, 2, 3].map((i) => (
                  <View key={i} style={[styles.progressSeg, i <= wStep && styles.progressSegDone]} />
                ))}
              </View>
              <Text style={styles.stepKicker}>{`PASO ${wStep + 1} DE 4`}</Text>
              <Text style={styles.stepTitle}>{WIZARD_STEPS[wStep].title}</Text>
              <Text style={styles.stepSub}>{WIZARD_STEPS[wStep].sub}</Text>
            </View>

            {/* ── Paso 1: cuenta + comisiones (beginner-friendly) ───────── */}
            {wStep === 0 && (
              <>
                {renderGasCards()}
                <TouchableOpacity
                  style={[styles.primaryBtn, !evmAddress && styles.execBtnDisabled]}
                  disabled={!evmAddress}
                  onPress={() => goToStep(1)}
                >
                  <Text style={styles.primaryBtnText}>Continuar</Text>
                  <Icon name="arrow-right" size={16} color={colors.white} />
                </TouchableOpacity>
              </>
            )}

            {/* ── Paso 2: destino ───────────────────────────────────────── */}
            {wStep === 1 && (
              <>
            <View style={styles.card}>
              <Text style={styles.inputLabel}>Billetera BNB Smart Chain (MetaMask)</Text>
              <View style={styles.inputRow}>
                <TextInput
                  style={[styles.input, styles.inputFlex, !!bscDest && !bscDestValid && styles.inputBad]}
                  value={bscDest} onChangeText={setBscDest} autoCapitalize="none"
                  autoCorrect={false} placeholder="0x…"
                  placeholderTextColor={colors.text.light}
                />
                <TouchableOpacity
                  style={styles.pasteBtn}
                  onPress={async () => {
                    try { const t = await Clipboard.getString(); if (t) setBscDest(t.trim()); } catch {}
                  }}
                  accessibilityLabel="Pegar dirección BNB Smart Chain"
                >
                  <Icon name="clipboard" size={15} color={colors.primaryDark} />
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.pasteBtn}
                  onPress={() => setScanVisible(true)}
                  accessibilityLabel="Escanear dirección BNB Smart Chain"
                >
                  <Icon name="camera" size={15} color={colors.primaryDark} />
                </TouchableOpacity>
              </View>
              {!!bscDest && !bscDestValid && wrongNetworkMessage(bscDest, 'bsc') && (
                <View style={styles.chainWarnRow}>
                  <Icon name="alert-triangle" size={13} color={colors.warning.text} />
                  <Text style={styles.chainWarnText}>
                    {wrongNetworkMessage(bscDest, 'bsc')}
                  </Text>
                </View>
              )}
              {bscDestValid && (
                <View style={styles.chainWarnRow}>
                  <Icon name="check-circle" size={13} color={colors.primaryDark} />
                  <Text style={[styles.chainWarnText, { color: colors.primaryDark }]}>
                    En BNB Smart Chain no hay que activar nada — el USDT y las acciones Ondo llegan directo.
                  </Text>
                </View>
              )}
              <View style={styles.chainWarnRow}>
                <Icon name="alert-triangle" size={13} color={colors.warning.text} />
                <Text style={styles.chainWarnText}>
                  La dirección debe ser de la red BNB Smart Chain. Lo enviado
                  a la red equivocada no se puede recuperar.
                </Text>
              </View>
            </View>
                <TouchableOpacity
                  style={[styles.primaryBtn, !bscDestValid && styles.execBtnDisabled]}
                  disabled={!bscDestValid}
                  onPress={() => goToStep(2)}
                >
                  <Text style={styles.primaryBtnText}>Continuar</Text>
                  <Icon name="arrow-right" size={16} color={colors.white} />
                </TouchableOpacity>
              </>
            )}

            {/* ── Paso 3: confirmación anti-estafa ──────────────────────── */}
            {wStep === 2 && (
              <>
            <View style={styles.card}>
              {CHECKLIST.map((item, i) => (
                <TouchableOpacity
                  key={i} style={styles.checkRow}
                  onPress={() => setChecks((c) => c.map((v, j) => (j === i ? !v : v)))}
                >
                  <Icon
                    name={checks[i] ? 'check-square' : 'square'} size={22}
                    color={checks[i] ? colors.primaryDark : colors.text.light}
                  />
                  <Text style={styles.checkText}>{item}</Text>
                </TouchableOpacity>
              ))}
              <View style={styles.scamBox}>
                <Icon name="shield-off" size={15} color={colors.error.text} />
                <Text style={[styles.scamBoxText, { color: colors.error.text }]}>
                  Nadie de Confío, ninguna financiera ni ningún proveedor te
                  pedirá jamás hacer esta operación.
                </Text>
              </View>
            </View>
                <TouchableOpacity
                  style={[styles.primaryBtn, !allChecked && styles.execBtnDisabled]}
                  disabled={!allChecked}
                  onPress={() => goToStep(3)}
                >
                  <Text style={styles.primaryBtnText}>Continuar</Text>
                  <Icon name="arrow-right" size={16} color={colors.white} />
                </TouchableOpacity>
              </>
            )}

            {/* ── Paso 4: resumen + ejecución ───────────────────────────── */}
            {wStep === 3 && (
              <>
            {renderOutcome()}

            {!exitDone && (
              <>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Resumen</Text>
              <View style={styles.summaryRow}>
                <Icon name={selCtx?.type === 'personal' ? 'user' : 'briefcase'} size={14} color={colors.text.secondary} />
                <Text style={styles.summaryText}>Cuenta: {selCtx?.name ?? 'Personal'}</Text>
              </View>
              {bscDestValid && (
                <View style={styles.summaryRow}>
                  <Icon name="send" size={14} color={colors.text.secondary} />
                  <Text style={styles.summaryText}>Mi dinero (BNB Smart Chain) → {truncAddr(bscDest.trim())}</Text>
                </View>
              )}
            </View>

            <View style={styles.card}>
              {/* After an error, retry is always tappable: it re-reads the
                  heartbeat first, and the gate is enforced again inside every
                  transaction — so a stale "unreachable" read can't strand the
                  user behind a disabled button. */}
              <TouchableOpacity
                style={[styles.execBtn, (!canRun || !allChecked || !bscDestValid || bscRunning) && styles.execBtnDisabled]}
                disabled={!canRun || !allChecked || !bscDestValid || bscRunning}
                onPress={async () => {
                  if (outcome === 'error') await evaluate();
                  await runBsc();
                }}
              >
                <Icon name="send" size={16} color={colors.white} />
                <Text style={styles.execBtnText}>
                  {outcome === 'error' ? 'Reintentar' : 'Mover mi dinero'}
                </Text>
              </TouchableOpacity>
            </View>
              </>
            )}

            {anyResult && roster.length > 1 && (
              <TouchableOpacity style={styles.primaryBtn} onPress={() => goToStep(0)}>
                <Icon name="repeat" size={16} color={colors.white} />
                <Text style={styles.primaryBtnText}>Retirar otra cuenta</Text>
              </TouchableOpacity>
            )}

            {exitDone && (
              <TouchableOpacity style={styles.ghostBtn} onPress={leaveScreen}>
                <Text style={styles.doneBtnText}>Volver</Text>
              </TouchableOpacity>
            )}

            <View style={styles.futureRow}>
              <Icon name="corner-down-right" size={14} color={colors.text.secondary} />
              <Text style={styles.futureText}>
                Esta salida mueve tu saldo actual, pero no redirige pagos
                futuros. Si compartiste tu QR o tu dirección de cobro,
                actualízalos.
              </Text>
            </View>
              </>
            )}
          </>
        )}
      </ScrollView>
      </KeyboardAvoidingView>

      {/* Same blocking overlay every other transaction in the app uses —
          it names the step in flight and, critically, keeps the user from
          tapping "Mover mi dinero" twice while two sends are pending. */}
      <LoadingOverlay visible={bscRunning} message={bscPhase ?? 'Moviendo tu dinero…'} />

      <AddressScannerModal
        network="bsc"
        visible={scanVisible}
        onClose={() => setScanVisible(false)}
        onScanned={(addr: string) => {
          setBscDest(addr.trim());
          setScanVisible(false);
        }}
      />

      {/* One large QR at a time — the only scannable-by-design state. */}
      <Modal
        visible={!!qrModal}
        transparent
        animationType="fade"
        onRequestClose={() => setQrModal(null)}
      >
        <View style={styles.qrModalBackdrop}>
          <View style={styles.qrModalCard}>
            <Text style={styles.cardTitle}>{qrModal?.chain}</Text>
            <Text style={[styles.bodyText, { textAlign: 'center' }]}>
              Envía SOLO por esta red a esta dirección.
            </Text>
            <View style={styles.qrModalQr}>
              {!!qrModal && <QRCode value={qrModal.address} size={240} />}
            </View>
            <Text style={[styles.addrText, styles.qrModalAddr]} selectable>
              {qrModal?.address}
            </Text>
            <TouchableOpacity
              style={styles.primaryBtn}
              onPress={() => { if (qrModal) Clipboard.setString(qrModal.address); }}
            >
              <Icon name="copy" size={16} color={colors.white} />
              <Text style={styles.primaryBtnText}>Copiar dirección</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.ghostBtn} onPress={() => setQrModal(null)}>
              <Text style={styles.qrModalClose}>Cerrar</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  header: { backgroundColor: colors.heroField, overflow: 'hidden' },
  headerInner: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 24 },
  headerTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  headerIconBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  headerTitle: { fontSize: 17, fontWeight: '700', color: colors.white },
  heroWrap: { alignItems: 'center', marginTop: 10, paddingHorizontal: 12 },
  heroIconRing: {
    width: 56, height: 56, borderRadius: 28, borderWidth: 2, borderColor: 'rgba(255,255,255,0.55)',
    alignItems: 'center', justifyContent: 'center', marginBottom: 10,
  },
  heroIconRingAlert: { borderColor: colors.white, backgroundColor: 'rgba(255,255,255,0.15)' },
  heroTitle: { fontSize: 22, fontWeight: 'bold', color: colors.white, textAlign: 'center' },
  heroSub: {
    fontSize: 13, lineHeight: 19, color: colors.white, opacity: 0.92,
    textAlign: 'center', marginTop: 6,
  },
  scroll: { padding: 20, paddingBottom: 56 },
  promiseRow: {
    flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center',
    marginBottom: 14, paddingHorizontal: 8,
  },
  promiseText: { fontSize: 12.5, fontWeight: '600', color: colors.primaryDark, flexShrink: 1 },
  card: {
    backgroundColor: colors.white, borderRadius: 20, borderWidth: 1,
    borderColor: '#EDF1F4', padding: 20, marginBottom: 14,
    shadowColor: '#000', shadowOpacity: 0.05, shadowRadius: 10,
    shadowOffset: { width: 0, height: 3 }, elevation: 2,
  },
  stepHeader: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 8 },
  stepBadge: {
    width: 24, height: 24, borderRadius: 12, backgroundColor: colors.primaryDark,
    alignItems: 'center', justifyContent: 'center',
  },
  stepBadgeText: { color: colors.white, fontWeight: '700', fontSize: 13 },
  cardTitle: { fontSize: 16.5, fontWeight: '700', color: colors.text.primary },
  bodyText: { fontSize: 14.5, lineHeight: 21, color: colors.text.secondary, marginTop: 4 },
  countdownText: {
    fontSize: 34, fontWeight: 'bold', color: colors.text.primary,
    textAlign: 'center', marginTop: 10,
  },
  acctChipsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 14 },
  acctChip: {
    flexDirection: 'row', alignItems: 'center', gap: 7,
    borderWidth: 1.5, borderColor: colors.primaryDark, borderRadius: 22,
    paddingVertical: 10, paddingHorizontal: 16,
  },
  acctChipSel: { backgroundColor: colors.primaryDark },
  acctChipText: { fontSize: 14, fontWeight: '600', color: colors.primaryDark },
  acctChipTextSel: { color: colors.white },
  stepHero: { marginBottom: 18, paddingHorizontal: 2 },
  progressTrack: { flexDirection: 'row', gap: 6, marginBottom: 16 },
  progressSeg: { flex: 1, height: 4, borderRadius: 2, backgroundColor: colors.border ?? '#E5E7EB' },
  progressSegDone: { backgroundColor: colors.primaryDark },
  stepKicker: {
    fontSize: 11.5, fontWeight: '700', color: colors.text.secondary,
    letterSpacing: 1.2, marginBottom: 4,
  },
  stepTitle: { fontSize: 21, fontWeight: 'bold', color: colors.text.primary },
  stepSub: { fontSize: 14.5, lineHeight: 20, color: colors.text.secondary, marginTop: 5 },
  summaryRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 10 },
  summaryText: { fontSize: 14.5, color: colors.text.primary, fontWeight: '600', flexShrink: 1 },
  howRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', marginTop: 10 },
  howText: { flex: 1, fontSize: 13.5, lineHeight: 20, color: colors.text.secondary },
  gasChainBlock: {
    marginTop: 12, padding: 14, gap: 8,
    backgroundColor: colors.neutral, borderRadius: 14,
  },
  gasChain: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  gasStatusRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 6 },
  gasAmount: { flex: 1, fontSize: 13.5, lineHeight: 19, fontWeight: '600' },
  addrRow: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  copyBtn: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingVertical: 4 },
  copyBtnText: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },
  qrModalBackdrop: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.55)',
    alignItems: 'center', justifyContent: 'center', padding: 24,
  },
  qrModalCard: {
    backgroundColor: colors.white, borderRadius: 20, padding: 20,
    alignItems: 'stretch', width: '100%', maxWidth: 340,
  },
  qrModalQr: { alignSelf: 'center', marginVertical: 16, padding: 10, backgroundColor: colors.white },
  qrModalAddr: { textAlign: 'center', fontSize: 11 },
  qrModalClose: { fontSize: 14, fontWeight: '600', color: colors.text.secondary },
  inputRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  inputFlex: { flex: 1 },
  pasteBtn: {
    width: 46, height: 46, borderRadius: 12, borderWidth: 1, borderColor: colors.border,
    alignItems: 'center', justifyContent: 'center', backgroundColor: colors.white,
  },
  addrText: { fontSize: 10, color: colors.text.secondary },
  inputLabel: { fontSize: 13.5, fontWeight: '600', color: colors.text.primary, marginTop: 16, marginBottom: 7 },
  input: {
    borderWidth: 1, borderColor: colors.border ?? '#E5E7EB', borderRadius: 12,
    paddingHorizontal: 14, paddingVertical: 14, fontSize: 15, color: colors.text.primary,
    backgroundColor: colors.neutral,
  },
  inputBad: { borderColor: colors.error.text },
  chainWarnRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', marginTop: 12 },
  chainWarnText: { flex: 1, fontSize: 12.5, lineHeight: 18, color: colors.warning.text },
  checkRow: { flexDirection: 'row', gap: 12, alignItems: 'flex-start', paddingVertical: 10 },
  checkText: { flex: 1, fontSize: 15, lineHeight: 22, color: colors.text.primary },
  scamBox: {
    flexDirection: 'row', gap: 8, alignItems: 'flex-start', marginTop: 12,
    backgroundColor: colors.warning?.background ?? '#FEF3C7', borderRadius: 12, padding: 12,
  },
  scamBoxText: { flex: 1, fontSize: 13, lineHeight: 19, fontWeight: '600', color: colors.warning.text },
  primaryBtn: {
    flexDirection: 'row', gap: 8, backgroundColor: colors.primaryDark, borderRadius: 14,
    paddingVertical: 16, alignItems: 'center', justifyContent: 'center', marginTop: 18,
  },
  primaryBtnText: { color: colors.white, fontWeight: '700', fontSize: 16 },
  ghostBtn: { alignSelf: 'center', marginTop: 12, paddingVertical: 8, paddingHorizontal: 16 },
  ghostBtnText: { color: colors.error.text, fontWeight: '700', fontSize: 14 },
  execBtn: {
    flexDirection: 'row', gap: 8, backgroundColor: colors.primaryDark, borderRadius: 12,
    paddingVertical: 15, alignItems: 'center', justifyContent: 'center', marginTop: 12,
  },
  execBtnDisabled: { opacity: 0.35 },
  execBtnText: { color: colors.white, fontWeight: '700', fontSize: 15 },
  progressBox: {
    marginTop: 10, backgroundColor: colors.neutral,
    borderRadius: 10, padding: 12, gap: 8,
  },
  gasRecheck: {
    flexDirection: 'row', alignItems: 'center', gap: 7, alignSelf: 'flex-start',
    marginTop: 12, paddingVertical: 6,
  },
  gasRecheckText: { color: colors.primaryDark, fontWeight: '700', fontSize: 13.5 },
  outcomeHead: { alignItems: 'center', gap: 10, paddingVertical: 4 },
  outcomeTitle: { fontSize: 19, fontWeight: '700', textAlign: 'center' },
  outcomeSub: {
    fontSize: 14.5, lineHeight: 21, color: colors.text.secondary, textAlign: 'center',
  },
  verifyLabel: {
    fontSize: 12, fontWeight: '700', color: colors.text.secondary,
    letterSpacing: 0.4, textTransform: 'uppercase', marginTop: 18,
  },
  doneBtnText: { color: colors.primaryDark, fontWeight: '700', fontSize: 14 },
  progressRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start' },
  progressText: { flex: 1, fontSize: 14, lineHeight: 19, color: colors.text.primary },
  progressSkipped: { color: colors.text.light },
  futureRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', paddingHorizontal: 6, marginTop: 6 },
  futureText: { flex: 1, fontSize: 12.5, lineHeight: 18, color: colors.text.secondary },
});

export default EmergencyExitScreen;
