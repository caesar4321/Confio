import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import { biometricAuthService } from '../../services/biometricAuthService';
import { getActiveEvmWallet } from '../../services/secureDeterministicWallet';
import {
  HyperCoreExitPlan,
  HyperCoreExitResult,
  HyperCoreStep,
  executeHyperCoreExit,
  planHyperCoreExit,
} from '../../services/emergencyExit/hyperCoreExit';
import { isConfioAlive } from '../../services/emergencyExit/heartbeat';
import { formatDecimal } from '../../utils/numberLocale';

const STEP_TEXT: Record<HyperCoreStep, string> = {
  close: 'Cerrando tus posiciones…',
  gather: 'Juntando tu saldo…',
  withdraw: 'Retirando a tu billetera…',
};

/**
 * The Futuros part of the Salida de emergencia: shown only when the member
 * has something on Hyperliquid. Same destination address as the BSC legs,
 * received on Arbitrum as USDC (Hyperliquid's own bridge).
 */
export function HyperCoreExitCard({
  eligible,
  address,
  dest,
  destValid,
  exitCtx,
}: {
  eligible: boolean;
  address: string | null;
  dest: string;
  destValid: boolean;
  exitCtx?: { type: string; index: number; businessId?: string };
}) {
  const [plan, setPlan] = useState<HyperCoreExitPlan | null>(null);
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState<HyperCoreStep | null>(null);
  const [result, setResult] = useState<HyperCoreExitResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lookupFailed, setLookupFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!eligible || !address) return;
    let live = true;
    setLookupFailed(false);
    planHyperCoreExit(address)
      .then((p) => { if (live) setPlan(p); })
      // Unknown is not "nothing there": say so and offer to look again.
      .catch(() => { if (live) setLookupFailed(true); });
    return () => { live = false; };
  }, [eligible, address, result, attempt]);

  if (!eligible) return null;
  if (!plan && lookupFailed) {
    return (
      <View style={styles.card}>
        <View style={styles.head}>
          <Icon name="trending-up" size={16} color={colors.text.primary} />
          <Text style={styles.title}>Tus futuros en Hyperliquid</Text>
        </View>
        <Text style={styles.body}>No pudimos consultar Hyperliquid ahora. Si tienes futuros, tu dinero sigue ahí, a tu nombre.</Text>
        <TouchableOpacity style={styles.btn} onPress={() => setAttempt((n) => n + 1)} accessibilityRole="button">
          <Text style={styles.btnText}>Volver a consultar</Text>
        </TouchableOpacity>
      </View>
    );
  }
  if (!plan || (plan.positions.length === 0 && plan.estimatedOutUsd <= 0 && plan.otherCollateral.length === 0
      && !result)) return null;

  const run = async () => {
    if (!(await biometricAuthService.authenticateEmergencyExit('Confirmar salida de emergencia (Hyperliquid)'))) return;
    setRunning(true);
    setError(null);
    try {
      const wallet = await getActiveEvmWallet(exitCtx as any);
      setResult(await executeHyperCoreExit({ wallet, dest: dest.trim(), onStep: setStep }));
    } catch (e: any) {
      // Only a heartbeat actually read as live means Confío is back; an
      // unreachable or unreadable one is said as such.
      setError(isConfioAlive(e)
        ? (e.status.state === 'unreachable' || e.status.state === 'invalid'
          ? 'No pudimos leer la señal de Confío en la red ahora. Por seguridad no se movió nada más; inténtalo de nuevo.'
          : 'Confío volvió a publicar su señal: la salida se cerró. No se movió nada más.')
        : e?.message || String(e));
    } finally {
      setRunning(false);
      setStep(null);
    }
  };

  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <Icon name="trending-up" size={16} color={colors.text.primary} />
        <Text style={styles.title}>Tus futuros en Hyperliquid</Text>
      </View>
      {result ? (
        <>
          <Text style={styles.body}>
            {result.withdrawnUsd != null
              ? `Listo: unos $${formatDecimal(result.withdrawnUsd)} en USDC van a tu billetera en Arbitrum (la misma dirección).`
              : result.closed.length > 0
                ? 'Cerramos tus posiciones. No quedó saldo suficiente para retirar (Hyperliquid cobra $1).'
                : 'No había saldo en USDC para retirar.'}
          </Text>
          {plan.otherCollateral.length > 0 && (
            <Text style={styles.note}>
              {`Siguen abiertas tus posiciones en ${plan.otherCollateral.join(', ')} (otra moneda de garantía): esta salida no las cierra ni las retira. Están a tu nombre en Hyperliquid.`}
            </Text>
          )}
        </>
      ) : (
        <>
          <Text style={styles.body}>
            {plan.positions.length > 0
              ? `Tienes ${plan.positions.length} ${plan.positions.length === 1 ? 'posición abierta' : 'posiciones abiertas'}. Las cerramos al precio del momento y retiramos todo.`
              : 'Tienes saldo en Hyperliquid listo para retirar.'}
          </Text>
          <Text style={styles.note}>
            {`Llega como USDC a la misma dirección, en la red Arbitrum (unos $${formatDecimal(plan.estimatedOutUsd)} si los precios no cambian). Hyperliquid cobra $1 por el retiro; no necesitas gas.`}
          </Text>
          {plan.otherCollateral.length > 0 && (
            <Text style={styles.note}>
              {`También tienes saldo en otra moneda de garantía (${plan.otherCollateral.join(', ')}). Esta salida retira solo USDC; ese saldo sigue a tu nombre en Hyperliquid.`}
            </Text>
          )}
          <TouchableOpacity style={[styles.btn, (!destValid || running) && styles.btnOff]} disabled={!destValid || running}
            onPress={run} accessibilityRole="button">
            {running ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.btnText}>Cerrar y retirar mis futuros</Text>}
          </TouchableOpacity>
          {step ? <Text style={styles.note}>{STEP_TEXT[step]}</Text> : null}
        </>
      )}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: '#FFFFFF', borderRadius: 16, padding: 16, marginBottom: 12 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { fontSize: 15, fontWeight: '800', color: colors.text.primary },
  body: { fontSize: 14, lineHeight: 20, color: colors.text.primary, marginTop: 10 },
  note: { fontSize: 12, lineHeight: 17, color: colors.text.secondary, marginTop: 8 },
  btn: { backgroundColor: '#0F172A', borderRadius: 14, paddingVertical: 14, alignItems: 'center', marginTop: 12 },
  btnOff: { opacity: 0.45 },
  btnText: { color: '#FFFFFF', fontSize: 15, fontWeight: '800' },
  error: { fontSize: 13, color: '#DC2626', marginTop: 10, lineHeight: 18 },
});
