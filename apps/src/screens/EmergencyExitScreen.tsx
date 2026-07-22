// Salida de emergencia — server-independent full exit
// (docs/plans/salida-de-emergencia-design.md).
//
// Always reachable from Seguridad; server state only changes prominence
// and wait: ban / 24h-persistent outage ⇒ immediate, normal ⇒ 24h local
// cooloff, full offline ⇒ visible but not executable. Every judgment is
// client-local (reachability.ts) and chain-timed (chainClock.ts) — the
// server can never delay, extend or cancel an exit.
//
// UI is a STAGED flow, not a wall of forms: the screen's job is calm in
// the worst moment (the outage state is the narrative's proof moment).
// Stage 1 is the wait/status surface; once eligible, a 4-step WIZARD
// (one decision per screen, internal step state — never separate routes:
// this screen lives in BOTH stacks and shares selection/dest/check state):
// Paso 1 cuenta+comisiones (with a beginner intro to gas/ALGO/BNB) →
// Paso 2 destino → Paso 3 checklist → Paso 4 resumen+ejecución.
//
// Execution is Direct mode always (user gas, public RPCs): it works in
// every server state. A fee-free Sponsored mode for the explicit-ban case
// layers on when the backend ships a ban signal. The exit moves USER
// ASSETS ONLY — no close-outs, no native sweeps (engine invariants).

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, Alert, StatusBar, Modal, KeyboardAvoidingView, Platform, Linking,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { colors } from '../config/theme';
import { API_URL, CONFIO_ASSET_ID } from '../config/env';
import Clipboard from '@react-native-clipboard/clipboard';
import { AddressScannerModal } from '../components/AddressScannerModal';
import { evmAccountKey, getEvmAddressForDisplay, getActiveEvmWallet } from '../services/secureDeterministicWallet';
import algorandService from '../services/algorandService';
import { biometricAuthService } from '../services/biometricAuthService';
import { emergencyStore } from '../services/emergencyExit/store';
import {
  RosterAccount, rosterAccountKey, getAccountRoster, exitableAccounts,
} from '../services/emergencyExit/accountRoster';
import {
  evaluateEmergencyState, getExitEligibility, requestExitCooloff, cancelExitCooloff,
  devElapseCooloff, ReachabilityResult, ExitEligibility, NORMAL_COOLOFF_SECONDS,
} from '../services/emergencyExit/reachability';
import {
  executeAlgorandExit, fetchAlgoAccount, AlgoExitResult,
  CUSD_ASSET_ID, USDC_ASSET_ID,
} from '../services/emergencyExit/algorandExit';
import {
  executeBscExit, planBscExit, estimateBscExitGasWei,
  installEmergencyBscTransport, BUNDLED_VAULT_ADDRESS, BscExitResult,
} from '../services/emergencyExit/bscExit';

const ALGO_ADDR_RE = /^[A-Z2-7]{58}$/;
const EVM_ADDR_RE = /^0x[0-9a-fA-F]{40}$/;

// Wizard step headers — the ONE decision each screen asks for.
const WIZARD_STEPS = [
  { title: 'Tu cuenta y las comisiones', sub: 'Elige qué cuenta retiras y revisa que cada red tenga para su comisión.' },
  { title: '¿A dónde va tu dinero?', sub: 'Una billetera que sea tuya, en la red correcta.' },
  { title: 'Confirma que estás a salvo', sub: 'Cuatro confirmaciones. Tómate tu tiempo.' },
  { title: 'Revisa y mueve tu dinero', sub: 'Último paso — cada envío se firma con tu biometría.' },
];

const CHECKLIST = [
  'Estoy solo/a. Nadie me está mirando ni guiándome.',
  'No estoy en una llamada ni compartiendo pantalla.',
  'Nadie — ni una financiera, ni "soporte de Confío", ni un familiar — me pidió hacer esto.',
  'La billetera de destino es MÍA y yo controlo sus claves.',
];

// Human names for engine step ids — raw ids are for support, not users.
// The exit sweeps EVERY funded ASA (the engine iterates account.assets),
// so name the known ones; unknown ids keep the raw fallback.
const ASSET_NAMES: Record<number, string> = {
  [CUSD_ASSET_ID]: 'cUSD',
  [USDC_ASSET_ID]: 'USDC',
  [CONFIO_ASSET_ID]: 'CONFIO',
};
const assetName = (id: number): string => ASSET_NAMES[id] ?? `activo ${id}`;
const STEP_NAMES: Record<string, string> = {
  burnCusd: 'Canjear cUSD por USDC',
  redeemCusdPlus: 'Canjear tu ahorro por USDT',
  transferUsdt: 'Enviar USDT',
};
const stepName = (id: string): string =>
  STEP_NAMES[id] ?? (id.startsWith('assetTransfer_') ? `Enviar ${assetName(Number(id.split('_')[1]))}` : id);

const fmtRemaining = (sec: number): string => {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
};

const truncAddr = (a: string): string => (a.length > 20 ? `${a.slice(0, 8)}…${a.slice(-6)}` : a);

type EmState = (ReachabilityResult & { chainNowSec: number | null }) | null;

export const EmergencyExitScreen: React.FC = () => {
  const navigation = useNavigation<any>();
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
  const [algorandAddress, setAlgorandAddress] = useState('');

  const [es, setEs] = useState<EmState>(null);
  const [elig, setElig] = useState<ExitEligibility | null>(null);
  const [evaluating, setEvaluating] = useState(true);

  const [evmAddress, setEvmAddress] = useState<string | null>(null);
  // Gas shortfalls, null = still reading. Cards render only when short.
  const [algoFeeShortMicro, setAlgoFeeShortMicro] = useState<bigint | null>(null);
  const [bscGasShortWei, setBscGasShortWei] = useState<bigint | null>(null);
  // What the SOURCE account actually holds (funded ASA ids) — drives the
  // proactive destination opt-in check on the destino step.
  const [srcFundedAssetIds, setSrcFundedAssetIds] = useState<number[]>([]);
  // Destination opt-in preflight: which required ASAs the dest is missing.
  type DestOptIns =
    | { kind: 'checking' }
    | { kind: 'ok' }
    | { kind: 'missing'; assets: number[] }
    | { kind: 'unfunded' }   // address not on chain yet (no ALGO)
    | { kind: 'unknown' };   // RPC unreachable — execution still guards
  const [destOptIns, setDestOptIns] = useState<DestOptIns | null>(null);

  const [algDest, setAlgDest] = useState('');
  const [bscDest, setBscDest] = useState('');
  const [scanTarget, setScanTarget] = useState<'algo' | 'bsc' | null>(null);
  // ONE QR at a time, on demand: two codes side by side scan ambiguously
  // (the camera grabs whichever decodes first — wrong-chain top-ups).
  const [qrModal, setQrModal] = useState<{ chain: string; address: string } | null>(null);
  const [checks, setChecks] = useState<boolean[]>(CHECKLIST.map(() => false));

  const [algRunning, setAlgRunning] = useState(false);
  const [bscRunning, setBscRunning] = useState(false);
  const [algResult, setAlgResult] = useState<AlgoExitResult | null>(null);
  const [bscResult, setBscResult] = useState<BscExitResult | null>(null);
  const [algError, setAlgError] = useState<string | null>(null);
  const [bscError, setBscError] = useState<string | null>(null);

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
      const state = await evaluateEmergencyState(emergencyStore, API_URL);
      setEs(state);
      // Immediate states (ban, 24h outage) don't touch the per-account
      // cooloff key, so don't gate them on the account being loaded — a
      // banned user's account hydration is best-effort and the exit must
      // not wait for it. Non-immediate paths still need the real key
      // (cooloffs are per account).
      if (accountKey || state.immediate) {
        setElig(await getExitEligibility(emergencyStore, accountKey || 'no_account', state));
      }
    } finally {
      setEvaluating(false);
    }
  }, [accountKey]);

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

  // Resolve the SELECTED account's addresses (local V2 derivation, with the
  // per-account stored addresses as legacy fallback), then read live gas
  // status from public RPCs (all must work exactly when Confío doesn't).
  useEffect(() => {
    if (!selCtx) return;
    let stale = false;
    (async () => {
      setAccountKey(rosterAccountKey(selCtx));
      setAlgorandAddress('');
      setEvmAddress(null);
      setAlgoFeeShortMicro(null);
      setBscGasShortWei(null);
      setSrcFundedAssetIds([]);
      setDestOptIns(null);
      // Results/errors belong to the previously selected account.
      setAlgResult(null); setBscResult(null); setAlgError(null); setBscError(null);
      try {
        const ctx = { type: selCtx.type, index: selCtx.index, businessId: selCtx.businessId } as const;
        const { deriveAddressesForContext } = await import('../services/secureDeterministicWallet');
        const derived = await deriveAddressesForContext(ctx);

        let algoAddr = derived.algorand;
        if (!algoAddr) {
          const { AuthService } = await import('../services/authService');
          algoAddr = await AuthService.getInstance().getAlgorandAddress(ctx as any).catch(() => '');
        }
        if (stale) return;
        if (algoAddr) {
          setAlgorandAddress(algoAddr);
          fetchAlgoAccount(algoAddr)
            .then((a) => {
              const fundedAssets = a.assets.filter((x) => x.amountMicro > 0n);
              if (!stale) setSrcFundedAssetIds(fundedAssets.map((x) => x.id));
              // Fee budget: one min-fee per funded asset + 4× for the burn group.
              const budget = BigInt(fundedAssets.length + 5) * 1000n;
              const spendable = a.amountMicro - a.minBalanceMicro;
              if (!stale) setAlgoFeeShortMicro(spendable >= budget ? 0n : budget - spendable);
            })
            .catch(() => { if (!stale) setAlgoFeeShortMicro(null); });
        }

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
        if (evmAddr) {
          const restore = installEmergencyBscTransport();
          try {
            const plan = await planBscExit(evmAddr, BUNDLED_VAULT_ADDRESS);
            if (!plan.steps.length) { if (!stale) setBscGasShortWei(0n); return; }
            const need = await estimateBscExitGasWei(plan);
            if (!stale) setBscGasShortWei(plan.bnbWei >= need ? 0n : need - plan.bnbWei);
          } catch { /* status shows as unverified; execution re-checks anyway */ } finally {
            restore();
          }
        }
      } catch (e) {
        console.warn('[EmergencyExit] address resolution failed', e);
      }
    })();
    return () => { stale = true; };
  }, [selCtx]);

  const allChecked = checks.every(Boolean);
  const algDestValid = ALGO_ADDR_RE.test(algDest.trim()) && algDest.trim() !== algorandAddress;

  // Proactive destination opt-in preflight (public algod, no server): the
  // moment a valid Algorand destination is typed, tell the user which of
  // THEIR assets that wallet doesn't accept yet — before execution, not
  // after. Execution keeps its own guard (never sends unaccepted assets).
  useEffect(() => {
    const dest = algDest.trim();
    if (!ALGO_ADDR_RE.test(dest) || dest === algorandAddress) {
      setDestOptIns(null);
      return;
    }
    let stale = false;
    setDestOptIns({ kind: 'checking' });
    const t = setTimeout(async () => {
      try {
        const destAcct = await fetchAlgoAccount(dest);
        if (stale) return;
        const destOpted = new Set(destAcct.assets.map((a) => a.id));
        // Required: everything the source holds; plus USDC when cUSD is
        // funded (the redeem-first path outputs USDC to send onward).
        const required = new Set(srcFundedAssetIds);
        if (required.has(CUSD_ASSET_ID)) required.add(USDC_ASSET_ID);
        const missing = [...required].filter((id) => !destOpted.has(id));
        setDestOptIns(missing.length ? { kind: 'missing', assets: missing } : { kind: 'ok' });
      } catch (e: any) {
        if (stale) return;
        // algod embeds the HTTP status in the error message: 404 ⇒ the
        // address has never been funded (not on chain yet).
        setDestOptIns(String(e?.message ?? '').includes('http 404')
          ? { kind: 'unfunded' }
          : { kind: 'unknown' });
      }
    }, 600);
    return () => { stale = true; clearTimeout(t); };
  }, [algDest, algorandAddress, srcFundedAssetIds]);
  const bscDestValid =
    EVM_ADDR_RE.test(bscDest.trim()) &&
    bscDest.trim().toLowerCase() !== (evmAddress ?? '').toLowerCase();
  const eligible = !!elig?.eligible;
  const offline = es?.state === 'offline';
  // Destination gate: at least one chain filled, and nothing invalid left
  // behind (a half-typed address must block, not silently be skipped).
  const destsOk =
    (algDestValid || bscDestValid) &&
    (!algDest.trim() || algDestValid) &&
    (!bscDest.trim() || bscDestValid);

  const startCooloff = async () => {
    const ok = await biometricAuthService.authenticate(
      'Iniciar espera de seguridad para la salida de emergencia',
    );
    if (!ok) return;
    await requestExitCooloff(emergencyStore, accountKey);
    await evaluate();
  };

  const cancelCooloff = async () => {
    await cancelExitCooloff(emergencyStore, accountKey);
    await evaluate();
  };

  const runAlgorand = async () => {
    const ok = await biometricAuthService.authenticate('Confirmar salida de emergencia (Algorand)');
    if (!ok) return;
    setAlgRunning(true); setAlgError(null);
    try {
      const result = await executeAlgorandExit({
        address: algorandAddress,
        dest: algDest.trim(),
        sign: (b) => algorandService.signTransactionBytes(
          b,
          selCtx ? { type: selCtx.type, index: selCtx.index, businessId: selCtx.businessId } : undefined,
        ),
        accountKey,
        store: emergencyStore,
      });
      setAlgResult(result);
      if (result.degraded.length) {
        Alert.alert(
          'Atención',
          'Tus cUSD no pudieron canjearse por USDC y se enviaron tal cual. Para canjearlos por dólares necesitarás una herramienta externa de canje.',
        );
      }
    } catch (e: any) {
      setAlgError(e?.message || String(e));
    } finally {
      setAlgRunning(false);
    }
  };

  const runBsc = async () => {
    const ok = await biometricAuthService.authenticate('Confirmar salida de emergencia (BNB Smart Chain)');
    if (!ok) return;
    setBscRunning(true); setBscError(null);
    try {
      const wallet = await getActiveEvmWallet(
        selCtx ? { type: selCtx.type, index: selCtx.index, businessId: selCtx.businessId } : undefined,
      );
      const result = await executeBscExit({
        wallet,
        dest: bscDest.trim(),
        vaultAddress: BUNDLED_VAULT_ADDRESS,
        minUsdtOutWei: 0n, // oracle guard + fully-backed assert protect pricing; IM has no book
        accountKey,
        store: emergencyStore,
      });
      setBscResult(result);
      if (result.degraded.length) {
        Alert.alert(
          'Atención',
          'Tu ahorro no pudo canjearse por USDT (servicio de Ondo no disponible). Se enviaron los tokens cUSD+ tal cual: para canjearlos necesitarás una herramienta externa.',
        );
      }
    } catch (e: any) {
      setBscError(e?.message || String(e));
    } finally {
      setBscRunning(false);
    }
  };

  // ── Hero state: the emotional core of the screen ──────────────────────
  const hero = (() => {
    if (evaluating || !es) {
      return { label: 'Verificando…', sub: 'Consultando la blockchain', tone: 'neutral' as const };
    }
    switch (es.state) {
      case 'banned':
        return {
          label: 'Tu dinero sigue siendo tuyo',
          sub: 'Confío bloqueó tu cuenta, pero no puede bloquear tus fondos. Puedes retirarlos ahora mismo.',
          tone: 'alert' as const,
        };
      case 'outage':
        return es.immediate
          ? {
              label: 'Tu dinero está a salvo',
              sub: 'Los servidores de Confío llevan más de 24 horas sin responder. Tu dinero nunca estuvo en ellos: está en la blockchain, y desde aquí puedes moverlo sin nosotros.',
              tone: 'alert' as const,
            }
          : {
              label: 'Sin conexión con Confío',
              sub: `Interrupción de ${fmtRemaining(es.outageSeconds)}. Si supera las 24 horas, la salida se habilita de inmediato. Tu dinero está en la blockchain, intacto.`,
              tone: 'warn' as const,
            };
      case 'offline':
        return {
          label: 'Sin internet',
          sub: 'Tu dinero sigue en la blockchain. Conéctate a la red para poder moverlo.',
          tone: 'neutral' as const,
        };
      default:
        if (elig?.reason === 'cooloff_pending') {
          return {
            label: 'Todo funciona con normalidad',
            sub: 'Tu salida está en espera de seguridad. Puedes cancelarla en cualquier momento — y tu dinero sigue disponible con los envíos normales.',
            tone: 'ok' as const,
          };
        }
        return {
          label: 'Todo funciona con normalidad',
          sub: 'Esta salida existe para emergencias: mueve todo tu dinero a otra billetera sin pedirnos permiso. Hoy también puedes usar los envíos normales.',
          tone: 'ok' as const,
        };
    }
  })();

  // ── Stage: 1 = wait/status, 2 = destination+confirm, 3 = done-ish ─────
  const anyResult = !!(algResult || bscResult);
  const stage = eligible || anyResult ? 2 : 1;

  const renderWaitCard = () => {
    if (!es || es.immediate || es.state === 'offline') return null;
    if (!elig) return null;
    if (elig.reason === 'no_request') {
      return (
        <View style={styles.card}>
          <View style={styles.stepHeader}>
            <View style={styles.stepBadge}><Text style={styles.stepBadgeText}>1</Text></View>
            <Text style={styles.cardTitle}>Espera de seguridad</Text>
          </View>
          <Text style={styles.bodyText}>
            Para protegerte de estafas, la salida completa se habilita 24 horas
            después de solicitarla. El tiempo se mide en la blockchain — ni
            Confío puede acortarlo, extenderlo ni cancelarlo.
          </Text>
          <TouchableOpacity style={styles.primaryBtn} onPress={startCooloff}>
            <Icon name="clock" size={16} color={colors.white} />
            <Text style={styles.primaryBtnText}>Iniciar espera de 24 horas</Text>
          </TouchableOpacity>
        </View>
      );
    }
    if (elig.reason === 'cooloff_pending') {
      return (
        <View style={styles.card}>
          <View style={styles.stepHeader}>
            <View style={styles.stepBadge}><Icon name="clock" size={13} color={colors.white} /></View>
            <Text style={styles.cardTitle}>Espera en curso</Text>
          </View>
          <Text style={styles.countdownText}>
            {fmtRemaining(elig.remainingSec ?? NORMAL_COOLOFF_SECONDS)}
          </Text>
          <Text style={styles.bodyText}>restantes para habilitar la salida.</Text>
          <View style={styles.scamBox}>
            <Icon name="alert-triangle" size={15} color={colors.warning.text} />
            <Text style={styles.scamBoxText}>
              ¿Alguien te pidió hacer esto? Cancela ahora: es una estafa.
            </Text>
          </View>
          <TouchableOpacity style={styles.ghostBtn} onPress={cancelCooloff}>
            <Text style={styles.ghostBtnText}>Cancelar la salida</Text>
          </TouchableOpacity>
          {__DEV__ && (
            <TouchableOpacity
              style={styles.ghostBtn}
              onPress={async () => { await devElapseCooloff(emergencyStore, accountKey); await evaluate(); }}
            >
              <Text style={[styles.ghostBtnText, { color: colors.text.light }]}>(dev) saltar espera</Text>
            </TouchableOpacity>
          )}
        </View>
      );
    }
    return null;
  };

  // Destination opt-in preflight UI (Algorand only — EVM needs no opt-ins).
  const renderDestOptIns = () => {
    if (!destOptIns) return null;
    if (destOptIns.kind === 'checking') {
      return (
        <View style={styles.chainWarnRow}>
          <ActivityIndicator size="small" color={colors.text.secondary} />
          <Text style={[styles.chainWarnText, { color: colors.text.secondary }]}>
            Verificando qué activos acepta esta billetera…
          </Text>
        </View>
      );
    }
    if (destOptIns.kind === 'ok') {
      return (
        <View style={styles.chainWarnRow}>
          <Icon name="check-circle" size={13} color={colors.primaryDark} />
          <Text style={[styles.chainWarnText, { color: colors.primaryDark }]}>
            Esta billetera acepta todos tus activos.
          </Text>
        </View>
      );
    }
    if (destOptIns.kind === 'missing') {
      return (
        <View style={styles.scamBox}>
          <Icon name="alert-triangle" size={15} color={colors.warning.text} />
          <Text style={styles.scamBoxText}>
            Esta billetera aún no acepta: {destOptIns.assets.map(assetName).join(', ')}.
            {'\n'}En Pera: toca «+» en Activos, busca cada uno y actívalo
            (opt-in). Lo que no acepte quedará bloqueado — no se pierde,
            puedes reintentar después de activarlo.
          </Text>
        </View>
      );
    }
    if (destOptIns.kind === 'unfunded') {
      return (
        <View style={styles.scamBox}>
          <Icon name="alert-triangle" size={15} color={colors.warning.text} />
          <Text style={styles.scamBoxText}>
            Esta dirección aún no está activada en Algorand (no tiene ALGO).
            Deposita un poco de ALGO allí y activa (opt-in) tus activos antes
            de continuar.
          </Text>
        </View>
      );
    }
    return (
      <View style={styles.chainWarnRow}>
        <Icon name="help-circle" size={13} color={colors.text.secondary} />
        <Text style={[styles.chainWarnText, { color: colors.text.secondary }]}>
          No se pudo verificar esta billetera — si no acepta algún activo, la
          salida lo bloqueará por sí sola (nada se pierde).
        </Text>
      </View>
    );
  };

  const gasStatusLine = (short: bigint | null, fmt: (v: bigint) => string) => {
    if (short === null) return { icon: 'help-circle', color: colors.text.secondary, text: 'No se pudo verificar — si un envío falla por comisiones, deposita un poco aquí.' };
    if (short === 0n) return { icon: 'check-circle', color: colors.primaryDark, text: 'Comisiones listas' };
    return { icon: 'alert-circle', color: colors.warning.text, text: `Falta ≈ ${fmt(short)}` };
  };

  // ALWAYS visible: these addresses are the user's lifeline in Direct
  // mode. Hiding them when balances look sufficient proved too clever —
  // and under a ban the reads can fail entirely, which must not make the
  // addresses vanish. But QRs render ONE at a time, in a modal: two codes
  // side by side scan ambiguously, and a wrong-chain top-up is lost money.
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
    const algo = gasStatusLine(algoFeeShortMicro, (v) => `${(Number(v) / 1e6).toFixed(3)} ALGO`);
    const bsc = gasStatusLine(bscGasShortWei, (v) => `${(Number(v) / 1e18).toFixed(5)} BNB`);
    return (
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Comisiones de red</Text>
        <Text style={styles.bodyText}>
          Cada red de blockchain cobra una pequeña comisión por enviar — como
          una estampilla postal. Y cada red la cobra en su propia moneda:
          ALGO en la red Algorand, BNB en BNB Smart Chain.
        </Text>
        <Text style={styles.bodyText}>
          Normalmente Confío paga esas comisiones por ti. Sin nuestros
          servidores, salen de TUS direcciones. Si a una red le falta,
          deposita esa moneda aquí:
        </Text>
        {!!algorandAddress && renderChainGasRow('Red Algorand (ALGO)', algorandAddress, algo)}
        {!!evmAddress && renderChainGasRow('Red BNB Smart Chain (BNB)', evmAddress, bsc)}
        {!algorandAddress && !evmAddress && (
          <Text style={styles.bodyText}>Cargando tus direcciones…</Text>
        )}
      </View>
    );
  };

  const renderProgress = (
    result: { txids: Record<string, string>; degraded?: string[] } | null,
    error: string | null,
    running: boolean,
    explorerUrl: (tx: string) => string,
  ) => {
    if (!result && !error && !running) return null;
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
        {running && (
          <View style={styles.progressRow}>
            <ActivityIndicator size="small" color={colors.primaryDark} />
            <Text style={styles.progressText}>Firmando y enviando…</Text>
          </View>
        )}
        {error && (
          <View style={styles.progressRow}>
            <Icon name="x-circle" size={15} color={colors.error.text} />
            <Text style={[styles.progressText, { color: colors.error.text }]}>
              {error} — puedes reintentar; los pasos completados no se repiten.
            </Text>
          </View>
        )}
      </View>
    );
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <BrandFieldBackground id="emergencyField" ringCy="30%" />
          <View style={styles.headerInner}>
            <View style={styles.headerTopRow}>
              <TouchableOpacity
                onPress={() => {
                  // Inside the wizard, ← walks the steps before leaving.
                  if (eligible && wStep > 0) goToStep(wStep - 1);
                  else navigation.goBack();
                }}
                style={styles.headerIconBtn}
              >
                <Icon name="arrow-left" size={24} color={colors.white} />
              </TouchableOpacity>
              <Text style={styles.headerTitle}>Salida de emergencia</Text>
              <TouchableOpacity onPress={evaluate} style={styles.headerIconBtn} disabled={evaluating}>
                <Icon name="refresh-cw" size={18} color={colors.white} />
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
        {/* The permanent promise, verbatim in every state */}
        <View style={styles.promiseRow}>
          <Icon name="anchor" size={14} color={colors.primaryDark} />
          <Text style={styles.promiseText}>
            Confío no puede aprobar, rechazar ni bloquear esta operación.
          </Text>
        </View>

        {/* Account sweep: one account at a time, every OWNED account listed
            (local roster mirror — works without the server). Employee
            businesses are excluded: their keys are the owner's. Shown while
            waiting (cooloffs are per account) and on wizard Paso 1. */}
        {roster.length > 1 && (stage === 1 || wStep === 0) && (
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
            {renderWaitCard()}
            {/* How it works — shown while waiting, so the flow is never a surprise */}
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Cómo funciona</Text>
              {[
                ['map-pin', 'Eliges la billetera de destino — una que sea tuya.'],
                ['send', 'Tu dinero sale como USDC y USDT, directo por la blockchain.'],
                ['zap', 'En una emergencia real (Confío inaccesible por más de 24 horas), no hay espera: la salida es inmediata.'],
              ].map(([icon, text], i) => (
                <View key={i} style={styles.howRow}>
                  <Icon name={icon as string} size={16} color={colors.primaryDark} />
                  <Text style={styles.howText}>{text}</Text>
                </View>
              ))}
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
                  style={[styles.primaryBtn, !algorandAddress && !evmAddress && styles.execBtnDisabled]}
                  disabled={!algorandAddress && !evmAddress}
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
              <Text style={styles.bodyText}>
                Puedes llenar una sola red y volver luego por la otra.
              </Text>
              <Text style={styles.inputLabel}>Billetera Algorand (Pera)</Text>
              <View style={styles.inputRow}>
                <TextInput
                  style={[styles.input, styles.inputFlex, !!algDest && !algDestValid && styles.inputBad]}
                  value={algDest} onChangeText={setAlgDest} autoCapitalize="characters"
                  autoCorrect={false} placeholder="Dirección de 58 caracteres"
                  placeholderTextColor={colors.text.light}
                />
                <TouchableOpacity
                  style={styles.pasteBtn}
                  onPress={async () => {
                    try { const t = await Clipboard.getString(); if (t) setAlgDest(t.trim()); } catch {}
                  }}
                  accessibilityLabel="Pegar dirección Algorand"
                >
                  <Icon name="clipboard" size={15} color={colors.primaryDark} />
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.pasteBtn}
                  onPress={() => setScanTarget('algo')}
                  accessibilityLabel="Escanear dirección Algorand"
                >
                  <Icon name="camera" size={15} color={colors.primaryDark} />
                </TouchableOpacity>
              </View>
              {renderDestOptIns()}
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
                  onPress={() => setScanTarget('bsc')}
                  accessibilityLabel="Escanear dirección BNB Smart Chain"
                >
                  <Icon name="camera" size={15} color={colors.primaryDark} />
                </TouchableOpacity>
              </View>
              {bscDestValid && (
                <View style={styles.chainWarnRow}>
                  <Icon name="check-circle" size={13} color={colors.primaryDark} />
                  <Text style={[styles.chainWarnText, { color: colors.primaryDark }]}>
                    En BNB Smart Chain no hay que activar nada — el USDT llega directo.
                  </Text>
                </View>
              )}
              <View style={styles.chainWarnRow}>
                <Icon name="alert-triangle" size={13} color={colors.warning.text} />
                <Text style={styles.chainWarnText}>
                  Cada dirección debe ser de SU red. Lo enviado a la red
                  equivocada no se puede recuperar.
                </Text>
              </View>
            </View>
                <TouchableOpacity
                  style={[styles.primaryBtn, !destsOk && styles.execBtnDisabled]}
                  disabled={!destsOk}
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
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Resumen</Text>
              <View style={styles.summaryRow}>
                <Icon name={selCtx?.type === 'personal' ? 'user' : 'briefcase'} size={14} color={colors.text.secondary} />
                <Text style={styles.summaryText}>Cuenta: {selCtx?.name ?? 'Personal'}</Text>
              </View>
              {algDestValid && (
                <View style={styles.summaryRow}>
                  <Icon name="send" size={14} color={colors.text.secondary} />
                  <Text style={styles.summaryText}>Dólares (Algorand) → {truncAddr(algDest.trim())}</Text>
                </View>
              )}
              {bscDestValid && (
                <View style={styles.summaryRow}>
                  <Icon name="send" size={14} color={colors.text.secondary} />
                  <Text style={styles.summaryText}>Ahorro (BNB Smart Chain) → {truncAddr(bscDest.trim())}</Text>
                </View>
              )}
            </View>

            <View style={styles.card}>
              <TouchableOpacity
                style={[styles.execBtn, (!eligible || !allChecked || !algDestValid || !algorandAddress || algRunning || offline) && styles.execBtnDisabled]}
                disabled={!eligible || !allChecked || !algDestValid || !algorandAddress || algRunning || offline}
                onPress={runAlgorand}
              >
                <Icon name="send" size={16} color={colors.white} />
                <Text style={styles.execBtnText}>Mis dólares (Algorand)</Text>
              </TouchableOpacity>
              {!!algResult?.destMissingOptIns.length && (
                <View style={styles.chainWarnRow}>
                  <Icon name="pause-circle" size={13} color={colors.warning.text} />
                  <Text style={styles.chainWarnText}>
                    Tu billetera de destino aún no acepta{' '}
                    {algResult.destMissingOptIns.map(assetName).join(', ')}.
                    Actívalos allí (opt-in) y reintenta — nunca enviaremos a
                    donde no los acepten.
                  </Text>
                </View>
              )}
              {renderProgress(algResult, algError, algRunning,
                (tx) => `https://explorer.perawallet.app/tx/${tx}/`)}

              <TouchableOpacity
                style={[styles.execBtn, (!eligible || !allChecked || !bscDestValid || bscRunning || offline) && styles.execBtnDisabled]}
                disabled={!eligible || !allChecked || !bscDestValid || bscRunning || offline}
                onPress={runBsc}
              >
                <Icon name="send" size={16} color={colors.white} />
                <Text style={styles.execBtnText}>Mi ahorro (BNB Smart Chain)</Text>
              </TouchableOpacity>
              {renderProgress(bscResult, bscError, bscRunning,
                (tx) => `https://bscscan.com/tx/${tx}`)}
            </View>

            {anyResult && roster.length > 1 && (
              <TouchableOpacity style={styles.primaryBtn} onPress={() => goToStep(0)}>
                <Icon name="repeat" size={16} color={colors.white} />
                <Text style={styles.primaryBtnText}>Retirar otra cuenta</Text>
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

      <AddressScannerModal
        visible={scanTarget !== null}
        onClose={() => setScanTarget(null)}
        onScanned={(addr: string) => {
          if (scanTarget === 'algo') setAlgDest(addr.trim());
          if (scanTarget === 'bsc') setBscDest(addr.trim());
          setScanTarget(null);
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
  header: { backgroundColor: colors.primary, overflow: 'hidden' },
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
  progressRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start' },
  progressText: { flex: 1, fontSize: 14, lineHeight: 19, color: colors.text.primary },
  progressSkipped: { color: colors.text.light },
  futureRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', paddingHorizontal: 6, marginTop: 6 },
  futureText: { flex: 1, fontSize: 12.5, lineHeight: 18, color: colors.text.secondary },
});

export default EmergencyExitScreen;
