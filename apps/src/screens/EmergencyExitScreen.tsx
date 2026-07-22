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
// Stage 1 status/wait → stage 2 destination+checklist → stage 3 progress.
// Gas top-up cards appear only when a chain is actually short.
//
// Execution is Direct mode always (user gas, public RPCs): it works in
// every server state. A fee-free Sponsored mode for the explicit-ban case
// layers on when the backend ships a ban signal. The exit moves USER
// ASSETS ONLY — no close-outs, no native sweeps (engine invariants).

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, Alert, StatusBar,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { colors } from '../config/theme';
import { API_URL } from '../config/env';
import { useAccountManager } from '../hooks/useAccountManager';
import { evmAccountKey, getEvmAddressForDisplay, getActiveEvmWallet } from '../services/secureDeterministicWallet';
import algorandService from '../services/algorandService';
import { biometricAuthService } from '../services/biometricAuthService';
import { emergencyStore } from '../services/emergencyExit/store';
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

const CHECKLIST = [
  'Estoy solo/a. Nadie me está mirando ni guiándome.',
  'No estoy en una llamada ni compartiendo pantalla.',
  'Nadie — ni una financiera, ni "soporte de Confío", ni un familiar — me pidió hacer esto.',
  'La billetera de destino es MÍA y yo controlo sus claves.',
];

// Human names for engine step ids — raw ids are for support, not users.
const STEP_NAMES: Record<string, string> = {
  burnCusd: 'Canjear cUSD por USDC',
  [`assetTransfer_${CUSD_ASSET_ID}`]: 'Enviar cUSD',
  [`assetTransfer_${USDC_ASSET_ID}`]: 'Enviar USDC',
  redeemCusdPlus: 'Canjear tu ahorro por USDT',
  transferUsdt: 'Enviar USDT',
};
const stepName = (id: string): string =>
  STEP_NAMES[id] ?? (id.startsWith('assetTransfer_') ? `Enviar activo ${id.split('_')[1]}` : id);

const fmtRemaining = (sec: number): string => {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
};

type EmState = (ReachabilityResult & { chainNowSec: number | null }) | null;

export const EmergencyExitScreen: React.FC = () => {
  const navigation = useNavigation<any>();
  const { activeAccount } = useAccountManager();

  const accountKey = useMemo(() => {
    if (!activeAccount) return '';
    const type = activeAccount.type === 'business' ? 'business' : 'personal';
    return `${type}_${activeAccount.business?.id ?? ''}_${activeAccount.index ?? 0}`;
  }, [activeAccount]);

  const [es, setEs] = useState<EmState>(null);
  const [elig, setElig] = useState<ExitEligibility | null>(null);
  const [evaluating, setEvaluating] = useState(true);

  const [evmAddress, setEvmAddress] = useState<string | null>(null);
  // Gas shortfalls, null = still reading. Cards render only when short.
  const [algoFeeShortMicro, setAlgoFeeShortMicro] = useState<bigint | null>(null);
  const [bscGasShortWei, setBscGasShortWei] = useState<bigint | null>(null);

  const [algDest, setAlgDest] = useState('');
  const [bscDest, setBscDest] = useState('');
  const [checks, setChecks] = useState<boolean[]>(CHECKLIST.map(() => false));

  const [algRunning, setAlgRunning] = useState(false);
  const [bscRunning, setBscRunning] = useState(false);
  const [algResult, setAlgResult] = useState<AlgoExitResult | null>(null);
  const [bscResult, setBscResult] = useState<BscExitResult | null>(null);
  const [algError, setAlgError] = useState<string | null>(null);
  const [bscError, setBscError] = useState<string | null>(null);

  const evaluate = useCallback(async () => {
    setEvaluating(true);
    try {
      const state = await evaluateEmergencyState(emergencyStore, API_URL);
      setEs(state);
      if (accountKey) setElig(await getExitEligibility(emergencyStore, accountKey, state));
    } finally {
      setEvaluating(false);
    }
  }, [accountKey]);

  useEffect(() => { evaluate(); }, [evaluate]);

  const algorandAddress: string = (activeAccount as any)?.algorandAddress || '';

  // Gas readiness — public-RPC reads (they must work exactly when Confío
  // doesn't). Each chain's top-up card appears only if it is short.
  useEffect(() => {
    if (!activeAccount) return;
    if (algorandAddress) {
      fetchAlgoAccount(algorandAddress)
        .then((a) => {
          // Fee budget: one min-fee per funded asset + 4× for the burn group.
          const funded = a.assets.filter((x) => x.amountMicro > 0n).length;
          const budget = BigInt(funded + 5) * 1000n;
          const spendable = a.amountMicro - a.minBalanceMicro;
          setAlgoFeeShortMicro(spendable >= budget ? 0n : budget - spendable);
        })
        .catch(() => setAlgoFeeShortMicro(null));
    }
    const key = evmAccountKey({
      accountType: activeAccount.type === 'business' ? 'business' : 'personal',
      accountIndex: activeAccount.index ?? 0,
      businessId: activeAccount.business?.id,
    });
    getEvmAddressForDisplay(key).then(async (addr) => {
      setEvmAddress(addr);
      if (!addr) return;
      const restore = installEmergencyBscTransport();
      try {
        const plan = await planBscExit(addr, BUNDLED_VAULT_ADDRESS);
        if (!plan.steps.length) { setBscGasShortWei(0n); return; }
        const need = await estimateBscExitGasWei(plan);
        setBscGasShortWei(plan.bnbWei >= need ? 0n : need - plan.bnbWei);
      } catch { /* card stays hidden; execution re-checks anyway */ } finally {
        restore();
      }
    });
  }, [activeAccount, algorandAddress]);

  const allChecked = checks.every(Boolean);
  const algDestValid = ALGO_ADDR_RE.test(algDest.trim()) && algDest.trim() !== algorandAddress;
  const bscDestValid =
    EVM_ADDR_RE.test(bscDest.trim()) &&
    bscDest.trim().toLowerCase() !== (evmAddress ?? '').toLowerCase();
  const eligible = !!elig?.eligible;
  const offline = es?.state === 'offline';

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
        sign: (b) => algorandService.signTransactionBytes(b),
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
      const wallet = await getActiveEvmWallet();
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

  const renderGasCards = () => {
    const showAlgo = algoFeeShortMicro !== null && algoFeeShortMicro > 0n;
    const showBsc = bscGasShortWei !== null && bscGasShortWei > 0n;
    if (!showAlgo && !showBsc) return null;
    return (
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Te falta un poco para las comisiones</Text>
        <Text style={styles.bodyText}>
          Sin los servidores de Confío, cada red cobra su pequeña comisión desde
          tu propia dirección. Envía lo que falta y vuelve aquí:
        </Text>
        {showAlgo && (
          <View style={styles.gasRow}>
            <QRCode value={algorandAddress} size={92} />
            <View style={styles.gasInfo}>
              <Text style={styles.gasChain}>Red Algorand</Text>
              <Text style={styles.gasAmount}>
                Falta ≈ {(Number(algoFeeShortMicro) / 1e6).toFixed(3)} ALGO
              </Text>
              <Text style={styles.addrText} selectable>{algorandAddress}</Text>
            </View>
          </View>
        )}
        {showBsc && !!evmAddress && (
          <View style={styles.gasRow}>
            <QRCode value={evmAddress} size={92} />
            <View style={styles.gasInfo}>
              <Text style={styles.gasChain}>Red BNB Smart Chain</Text>
              <Text style={styles.gasAmount}>
                Falta ≈ {(Number(bscGasShortWei) / 1e18).toFixed(5)} BNB
              </Text>
              <Text style={styles.addrText} selectable>{evmAddress}</Text>
            </View>
          </View>
        )}
      </View>
    );
  };

  const renderProgress = (
    result: { txids: Record<string, string>; degraded?: string[] } | null,
    error: string | null,
    running: boolean,
  ) => {
    if (!result && !error && !running) return null;
    return (
      <View style={styles.progressBox}>
        {result && Object.entries(result.txids).map(([step, tx]) => {
          const skipped = tx.startsWith('skipped');
          const deg = result.degraded?.includes(step);
          return (
            <View key={step} style={styles.progressRow}>
              <Icon
                name={skipped ? 'minus-circle' : deg ? 'alert-circle' : 'check-circle'}
                size={15}
                color={skipped ? colors.text.light : deg ? colors.warning.text : colors.primaryDark}
              />
              <Text style={[styles.progressText, skipped && styles.progressSkipped]}>
                {stepName(step)}{skipped ? ' — sin saldo' : deg ? ' — enviado sin canjear' : ''}
              </Text>
            </View>
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
              <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn}>
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

      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        {/* The permanent promise, verbatim in every state */}
        <View style={styles.promiseRow}>
          <Icon name="anchor" size={14} color={colors.primaryDark} />
          <Text style={styles.promiseText}>
            Confío no puede aprobar, rechazar ni bloquear esta operación.
          </Text>
        </View>

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
            {renderGasCards()}

            <View style={styles.card}>
              <View style={styles.stepHeader}>
                <View style={styles.stepBadge}><Text style={styles.stepBadgeText}>1</Text></View>
                <Text style={styles.cardTitle}>¿A dónde va tu dinero?</Text>
              </View>
              <Text style={styles.inputLabel}>Billetera Algorand (Pera)</Text>
              <TextInput
                style={[styles.input, !!algDest && !algDestValid && styles.inputBad]}
                value={algDest} onChangeText={setAlgDest} autoCapitalize="characters"
                autoCorrect={false} placeholder="Dirección de 58 caracteres"
                placeholderTextColor={colors.text.light}
              />
              <Text style={styles.inputLabel}>Billetera BNB Smart Chain (MetaMask)</Text>
              <TextInput
                style={[styles.input, !!bscDest && !bscDestValid && styles.inputBad]}
                value={bscDest} onChangeText={setBscDest} autoCapitalize="none"
                autoCorrect={false} placeholder="0x…"
                placeholderTextColor={colors.text.light}
              />
              <View style={styles.chainWarnRow}>
                <Icon name="alert-triangle" size={13} color={colors.warning.text} />
                <Text style={styles.chainWarnText}>
                  Cada dirección debe ser de SU red. Lo enviado a la red
                  equivocada no se puede recuperar.
                </Text>
              </View>
            </View>

            <View style={styles.card}>
              <View style={styles.stepHeader}>
                <View style={styles.stepBadge}><Text style={styles.stepBadgeText}>2</Text></View>
                <Text style={styles.cardTitle}>Confirma que estás a salvo</Text>
              </View>
              {CHECKLIST.map((item, i) => (
                <TouchableOpacity
                  key={i} style={styles.checkRow}
                  onPress={() => setChecks((c) => c.map((v, j) => (j === i ? !v : v)))}
                >
                  <Icon
                    name={checks[i] ? 'check-square' : 'square'} size={20}
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

            <View style={styles.card}>
              <View style={styles.stepHeader}>
                <View style={styles.stepBadge}><Text style={styles.stepBadgeText}>3</Text></View>
                <Text style={styles.cardTitle}>Mover mi dinero</Text>
              </View>

              <TouchableOpacity
                style={[styles.execBtn, (!eligible || !allChecked || !algDestValid || algRunning || offline) && styles.execBtnDisabled]}
                disabled={!eligible || !allChecked || !algDestValid || algRunning || offline}
                onPress={runAlgorand}
              >
                <Icon name="send" size={16} color={colors.white} />
                <Text style={styles.execBtnText}>Mis dólares (Algorand)</Text>
              </TouchableOpacity>
              {!!algResult?.destMissingOptIns.length && (
                <View style={styles.chainWarnRow}>
                  <Icon name="pause-circle" size={13} color={colors.warning.text} />
                  <Text style={styles.chainWarnText}>
                    Tu billetera de destino aún no acepta los activos{' '}
                    {algResult.destMissingOptIns.join(', ')}. Actívalos allí
                    (opt-in) y reintenta — nunca enviaremos a donde no los acepten.
                  </Text>
                </View>
              )}
              {renderProgress(algResult, algError, algRunning)}

              <TouchableOpacity
                style={[styles.execBtn, (!eligible || !allChecked || !bscDestValid || bscRunning || offline) && styles.execBtnDisabled]}
                disabled={!eligible || !allChecked || !bscDestValid || bscRunning || offline}
                onPress={runBsc}
              >
                <Icon name="send" size={16} color={colors.white} />
                <Text style={styles.execBtnText}>Mi ahorro (BNB Smart Chain)</Text>
              </TouchableOpacity>
              {renderProgress(bscResult, bscError, bscRunning)}
            </View>

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
      </ScrollView>
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
  scroll: { padding: 16, paddingBottom: 48 },
  promiseRow: {
    flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center',
    marginBottom: 14, paddingHorizontal: 8,
  },
  promiseText: { fontSize: 12.5, fontWeight: '600', color: colors.primaryDark, flexShrink: 1 },
  card: {
    backgroundColor: colors.white, borderRadius: 16, borderWidth: 1,
    borderColor: colors.border ?? '#E5E7EB', padding: 16, marginBottom: 12,
  },
  stepHeader: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 8 },
  stepBadge: {
    width: 24, height: 24, borderRadius: 12, backgroundColor: colors.primaryDark,
    alignItems: 'center', justifyContent: 'center',
  },
  stepBadgeText: { color: colors.white, fontWeight: '700', fontSize: 13 },
  cardTitle: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  bodyText: { fontSize: 13.5, lineHeight: 20, color: colors.text.secondary, marginTop: 4 },
  countdownText: {
    fontSize: 34, fontWeight: 'bold', color: colors.text.primary,
    textAlign: 'center', marginTop: 10,
  },
  howRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', marginTop: 10 },
  howText: { flex: 1, fontSize: 13.5, lineHeight: 20, color: colors.text.secondary },
  gasRow: { flexDirection: 'row', gap: 14, alignItems: 'center', marginTop: 14 },
  gasInfo: { flex: 1, gap: 2 },
  gasChain: { fontSize: 13, fontWeight: '700', color: colors.text.primary },
  gasAmount: { fontSize: 14, fontWeight: '600', color: colors.primaryDark },
  addrText: { fontSize: 10, color: colors.text.secondary },
  inputLabel: { fontSize: 13, fontWeight: '600', color: colors.text.primary, marginTop: 12, marginBottom: 5 },
  input: {
    borderWidth: 1, borderColor: colors.border ?? '#E5E7EB', borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 11, fontSize: 13, color: colors.text.primary,
    backgroundColor: colors.neutral,
  },
  inputBad: { borderColor: colors.error.text },
  chainWarnRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', marginTop: 10 },
  chainWarnText: { flex: 1, fontSize: 12, lineHeight: 17, color: colors.warning.text },
  checkRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', paddingVertical: 8 },
  checkText: { flex: 1, fontSize: 13.5, lineHeight: 20, color: colors.text.primary },
  scamBox: {
    flexDirection: 'row', gap: 8, alignItems: 'flex-start', marginTop: 10,
    backgroundColor: colors.warning?.background ?? '#FEF3C7', borderRadius: 10, padding: 10,
  },
  scamBoxText: { flex: 1, fontSize: 12.5, lineHeight: 18, fontWeight: '600', color: colors.warning.text },
  primaryBtn: {
    flexDirection: 'row', gap: 8, backgroundColor: colors.primaryDark, borderRadius: 10,
    paddingVertical: 13, alignItems: 'center', justifyContent: 'center', marginTop: 14,
  },
  primaryBtnText: { color: colors.white, fontWeight: '700', fontSize: 14.5 },
  ghostBtn: { alignSelf: 'center', marginTop: 10, paddingVertical: 6, paddingHorizontal: 16 },
  ghostBtnText: { color: colors.error.text, fontWeight: '700', fontSize: 14 },
  execBtn: {
    flexDirection: 'row', gap: 8, backgroundColor: colors.primaryDark, borderRadius: 10,
    paddingVertical: 13, alignItems: 'center', justifyContent: 'center', marginTop: 10,
  },
  execBtnDisabled: { opacity: 0.35 },
  execBtnText: { color: colors.white, fontWeight: '700', fontSize: 14 },
  progressBox: {
    marginTop: 10, backgroundColor: colors.neutral,
    borderRadius: 10, padding: 12, gap: 8,
  },
  progressRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start' },
  progressText: { flex: 1, fontSize: 13, lineHeight: 18, color: colors.text.primary },
  progressSkipped: { color: colors.text.light },
  futureRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', paddingHorizontal: 6, marginTop: 2 },
  futureText: { flex: 1, fontSize: 12, lineHeight: 18, color: colors.text.secondary },
});

export default EmergencyExitScreen;
