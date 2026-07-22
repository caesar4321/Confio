// Salida de emergencia — server-independent full exit
// (docs/plans/salida-de-emergencia-design.md).
//
// Always reachable from Seguridad; server state only changes prominence
// and wait: ban / 24h-persistent outage ⇒ immediate, normal ⇒ 24h local
// cooloff, full offline ⇒ visible but not executable. Every judgment is
// client-local (reachability.ts) and chain-timed (chainClock.ts) — the
// server can never delay, extend or cancel an exit.
//
// Execution is Direct mode always (user gas, public RPCs): it works in
// every server state, so v1 ships one engine. A fee-free Sponsored mode
// for the explicit-ban case can layer on once the backend emits a ban
// signal (none exists today).
//
// The exit moves USER ASSETS ONLY — no close-outs, no native sweeps
// (engine-level invariant, see algorandExit.ts/bscExit.ts headers).

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';
import { colors } from '../config/theme';
import { API_URL } from '../config/env';
import { useAccountManager } from '../hooks/useAccountManager';
import { evmAccountKey, getEvmAddressForDisplay, getActiveEvmWallet } from '../services/secureDeterministicWallet';
import algorandService from '../services/algorandService';
import { biometricAuthService } from '../services/biometricAuthService';
import { emergencyStore } from '../services/emergencyExit/store';
import {
  evaluateEmergencyState, getExitEligibility, requestExitCooloff, cancelExitCooloff,
  ReachabilityResult, ExitEligibility, NORMAL_COOLOFF_SECONDS,
} from '../services/emergencyExit/reachability';
import { executeAlgorandExit, AlgoExitResult } from '../services/emergencyExit/algorandExit';
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

const fmtRemaining = (sec: number): string => {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
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
  const [bscGasNeedWei, setBscGasNeedWei] = useState<bigint | null>(null);

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

  // Own addresses + Direct-mode gas needs (public-RPC reads: they must
  // work exactly when Confío doesn't, so ride the emergency transport).
  useEffect(() => {
    if (!activeAccount) return;
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
        setBscGasNeedWei(plan.steps.length ? await estimateBscExitGasWei(plan) : 0n);
      } catch { /* gas card just shows guidance */ } finally {
        restore();
      }
    });
  }, [activeAccount]);

  const algorandAddress: string = (activeAccount as any)?.algorandAddress || '';
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

  const stateBanner = () => {
    if (evaluating || !es) return { icon: 'loader', color: colors.text.secondary, text: 'Verificando conexión…' };
    switch (es.state) {
      case 'banned':
        return { icon: 'alert-octagon', color: '#DC2626', text: 'Tu cuenta fue bloqueada por Confío. Puedes retirar tus fondos ahora mismo — no podemos impedirlo.' };
      case 'outage':
        return es.immediate
          ? { icon: 'alert-triangle', color: '#DC2626', text: 'No podemos conectar con los servidores de Confío desde hace más de 24 horas. Tu dinero no está en nuestros servidores: está en la blockchain y sigue siendo tuyo. Puedes moverlo ahora.' }
          : { icon: 'wifi-off', color: '#D97706', text: `Sin conexión con Confío (${fmtRemaining(es.outageSeconds)}). Si la interrupción supera 24 horas, la salida se habilita de inmediato.` };
      case 'offline':
        return { icon: 'cloud-off', color: colors.text.secondary, text: 'Sin internet. Conéctate a la red para poder ejecutar la salida — la blockchain debe estar accesible.' };
      default:
        return { icon: 'check-circle', color: colors.primaryDark, text: 'Confío funciona con normalidad. Para mover fondos hoy usa las funciones de envío normales; esta salida existe para emergencias y requiere una espera de seguridad de 24 horas.' };
    }
  };
  const banner = stateBanner();

  const renderEligibility = () => {
    if (!es || es.state === 'offline') return null;
    if (es.immediate) return null; // banner already says "now"
    if (!elig) return null;
    if (elig.reason === 'no_request') {
      return (
        <TouchableOpacity style={styles.secondaryBtn} onPress={startCooloff}>
          <Icon name="clock" size={16} color={colors.primaryDark} />
          <Text style={styles.secondaryBtnText}>Iniciar espera de seguridad (24 h)</Text>
        </TouchableOpacity>
      );
    }
    if (elig.reason === 'cooloff_pending') {
      return (
        <View>
          <Text style={styles.pendingText}>
            Espera de seguridad en curso — disponible en {fmtRemaining(elig.remainingSec ?? NORMAL_COOLOFF_SECONDS)}.
            {'\n'}Si alguien te pidió hacer esto, cancela ahora: es una estafa.
          </Text>
          <TouchableOpacity style={styles.cancelBtn} onPress={cancelCooloff}>
            <Text style={styles.cancelBtnText}>Cancelar la salida</Text>
          </TouchableOpacity>
        </View>
      );
    }
    return <Text style={styles.readyText}>Espera cumplida — puedes ejecutar la salida.</Text>;
  };

  const renderResult = (result: { txids: Record<string, string> } | null, error: string | null) => {
    if (error) return <Text style={styles.errorText}>Error: {error}. Puedes reintentar — los pasos completados no se repiten.</Text>;
    if (!result) return null;
    return (
      <View style={styles.resultBox}>
        {Object.entries(result.txids).map(([step, tx]) => (
          <Text key={step} style={styles.resultLine}>
            {tx.startsWith('skipped') ? '○' : '✓'} {step}{tx.startsWith('skipped') ? ' (sin saldo)' : ''}
          </Text>
        ))}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Icon name="arrow-left" size={22} color={colors.text.primary} />
        </TouchableOpacity>
        <Text style={styles.title}>Salida de emergencia</Text>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Standing description — always the same, every state */}
        <View style={styles.card}>
          <Text style={styles.standingText}>
            Si Confío no está disponible, puedes mover tus fondos directamente
            desde la blockchain. Confío no puede aprobar, rechazar ni bloquear
            esta operación.
          </Text>
        </View>

        {/* State + eligibility */}
        <View style={styles.card}>
          <View style={styles.bannerRow}>
            <Icon name={banner.icon} size={20} color={banner.color} />
            <Text style={[styles.bannerText, { color: banner.color }]}>{banner.text}</Text>
          </View>
          {renderEligibility()}
          <TouchableOpacity style={styles.linkBtn} onPress={evaluate} disabled={evaluating}>
            <Text style={styles.linkBtnText}>{evaluating ? 'Verificando…' : 'Volver a verificar'}</Text>
          </TouchableOpacity>
        </View>

        {/* Direct-mode gas info */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Comisiones de red (modo directo)</Text>
          <Text style={styles.helpText}>
            Sin los servidores de Confío, las comisiones se pagan desde tu propia
            dirección. Si te falta saldo, envía un poco a estas direcciones:
          </Text>
          <View style={styles.gasRow}>
            <View style={styles.gasCol}>
              <Text style={styles.gasLabel}>ALGO para comisiones</Text>
              {!!algorandAddress && <QRCode value={algorandAddress} size={110} />}
              <Text style={styles.addrText} selectable>{algorandAddress}</Text>
              <Text style={styles.gasNeed}>≈ 0.001 ALGO por activo</Text>
            </View>
            <View style={styles.gasCol}>
              <Text style={styles.gasLabel}>BNB para comisiones</Text>
              {!!evmAddress && <QRCode value={evmAddress} size={110} />}
              <Text style={styles.addrText} selectable>{evmAddress ?? '—'}</Text>
              <Text style={styles.gasNeed}>
                {bscGasNeedWei === null ? 'calculando…'
                  : bscGasNeedWei === 0n ? 'sin pasos pendientes'
                  : `≈ ${(Number(bscGasNeedWei) / 1e18).toFixed(5)} BNB`}
              </Text>
            </View>
          </View>
        </View>

        {/* Destinations */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Billetera de destino</Text>
          <Text style={styles.inputLabel}>Dirección Algorand (Pera)</Text>
          <TextInput
            style={[styles.input, !!algDest && !algDestValid && styles.inputBad]}
            value={algDest} onChangeText={setAlgDest} autoCapitalize="characters"
            autoCorrect={false} placeholder="58 caracteres, A–Z y 2–7"
          />
          <Text style={styles.inputLabel}>Dirección BNB Smart Chain (MetaMask)</Text>
          <TextInput
            style={[styles.input, !!bscDest && !bscDestValid && styles.inputBad]}
            value={bscDest} onChangeText={setBscDest} autoCapitalize="none"
            autoCorrect={false} placeholder="0x + 40 caracteres"
          />
          <Text style={styles.helpText}>
            Verifica que cada dirección corresponda a SU red. Los fondos enviados
            a la red equivocada no se pueden recuperar.
          </Text>
        </View>

        {/* Social-engineering gate */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Antes de continuar</Text>
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
          <Text style={styles.scamText}>
            Nadie de Confío, ninguna financiera ni ningún proveedor te pedirá
            jamás hacer esta operación. Si alguien te lo pidió, detente: es una estafa.
          </Text>
        </View>

        {/* Execution */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Ejecutar</Text>
          <TouchableOpacity
            style={[styles.execBtn, (!eligible || !allChecked || !algDestValid || algRunning || offline) && styles.execBtnDisabled]}
            disabled={!eligible || !allChecked || !algDestValid || algRunning || offline}
            onPress={runAlgorand}
          >
            {algRunning ? <ActivityIndicator color="#fff" /> : (
              <Text style={styles.execBtnText}>Mover mis dólares (Algorand)</Text>
            )}
          </TouchableOpacity>
          {!!algResult?.destMissingOptIns.length && (
            <Text style={styles.warnText}>
              Activos bloqueados: el destino aún no acepta los assets {algResult.destMissingOptIns.join(', ')}.
              Ábrelos (opt-in) en tu billetera de destino y reintenta — nunca enviaremos a un destino que no los acepte.
            </Text>
          )}
          {renderResult(algResult, algError)}

          <TouchableOpacity
            style={[styles.execBtn, (!eligible || !allChecked || !bscDestValid || bscRunning || offline) && styles.execBtnDisabled]}
            disabled={!eligible || !allChecked || !bscDestValid || bscRunning || offline}
            onPress={runBsc}
          >
            {bscRunning ? <ActivityIndicator color="#fff" /> : (
              <Text style={styles.execBtnText}>Mover mi ahorro (BNB Smart Chain)</Text>
            )}
          </TouchableOpacity>
          {renderResult(bscResult, bscError)}
        </View>

        {/* Future-deposit warning */}
        <View style={[styles.card, styles.futureCard]}>
          <Icon name="info" size={16} color={colors.text.secondary} />
          <Text style={styles.futureText}>
            Esta salida mueve tu saldo actual, pero no redirige pagos futuros.
            Si compartiste tu QR o tu dirección de cobro, actualízalos: lo que
            llegue después quedará en tu dirección anterior.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12 },
  backBtn: { marginRight: 12 },
  title: { fontSize: 18, fontWeight: '700', color: colors.text.primary },
  scroll: { padding: 16, paddingBottom: 48 },
  card: { backgroundColor: '#fff', borderRadius: 12, padding: 16, marginBottom: 12 },
  standingText: { fontSize: 14, lineHeight: 21, color: colors.text.primary },
  bannerRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  bannerText: { flex: 1, fontSize: 14, lineHeight: 20 },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: colors.text.primary, marginBottom: 8 },
  helpText: { fontSize: 13, lineHeight: 19, color: colors.text.secondary, marginTop: 4 },
  gasRow: { flexDirection: 'row', gap: 12, marginTop: 12 },
  gasCol: { flex: 1, alignItems: 'center', gap: 6 },
  gasLabel: { fontSize: 13, fontWeight: '600', color: colors.text.primary },
  addrText: { fontSize: 10, color: colors.text.secondary, textAlign: 'center' },
  gasNeed: { fontSize: 12, color: colors.text.secondary },
  inputLabel: { fontSize: 13, fontWeight: '600', color: colors.text.primary, marginTop: 10, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 8, paddingHorizontal: 12,
    paddingVertical: 10, fontSize: 13, color: colors.text.primary,
  },
  inputBad: { borderColor: '#DC2626' },
  checkRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', paddingVertical: 8 },
  checkText: { flex: 1, fontSize: 13, lineHeight: 19, color: colors.text.primary },
  scamText: { fontSize: 13, lineHeight: 19, color: '#DC2626', marginTop: 8, fontWeight: '600' },
  secondaryBtn: {
    flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: colors.primaryDark, borderRadius: 8, paddingVertical: 10, marginTop: 12,
  },
  secondaryBtnText: { color: colors.primaryDark, fontWeight: '600', fontSize: 14 },
  pendingText: { fontSize: 13, lineHeight: 19, color: colors.text.primary, marginTop: 12 },
  cancelBtn: { alignSelf: 'center', marginTop: 8, paddingVertical: 6, paddingHorizontal: 16 },
  cancelBtnText: { color: '#DC2626', fontWeight: '700', fontSize: 14 },
  readyText: { fontSize: 13, color: colors.primaryDark, fontWeight: '600', marginTop: 12 },
  linkBtn: { alignSelf: 'flex-end', marginTop: 8 },
  linkBtnText: { fontSize: 12, color: colors.text.secondary },
  execBtn: {
    backgroundColor: colors.primaryDark, borderRadius: 8, paddingVertical: 13,
    alignItems: 'center', marginTop: 10,
  },
  execBtnDisabled: { opacity: 0.4 },
  execBtnText: { color: '#fff', fontWeight: '700', fontSize: 14 },
  warnText: { fontSize: 12, lineHeight: 18, color: '#D97706', marginTop: 8 },
  errorText: { fontSize: 12, lineHeight: 18, color: '#DC2626', marginTop: 8 },
  resultBox: { marginTop: 8, backgroundColor: '#F9FAFB', borderRadius: 8, padding: 10 },
  resultLine: { fontSize: 12, color: colors.text.primary, lineHeight: 18 },
  futureCard: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  futureText: { flex: 1, fontSize: 12, lineHeight: 18, color: colors.text.secondary },
});

export default EmergencyExitScreen;
