/**
 * Confío Face: the step-up the server asks for before money moves.
 *
 * Framed like Face ID rather than a compliance check: one tap, look at the
 * camera, done. Mounted once at the app root; anything (screens or plain
 * services) triggers it through ensureFaceCheck/withFaceStepUp.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  Easing,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';
import Icon from 'react-native-vector-icons/Feather';
import {
  FaceCheckBackend,
  FaceCheckPurpose,
  registerFaceCheckPresenter,
  runFaceCapture,
} from '../services/faceStepUp';

const EMERALD = '#10B981';
const EMERALD_LIGHT = '#D1FAE5';
const INK = '#111827';
const MUTED = '#6B7280';
const DANGER = '#DC2626';

type Stage = 'intro' | 'capturing' | 'grading' | 'passed' | 'failed' | 'unavailable';

const PURPOSE_COPY: Record<FaceCheckPurpose, string> = {
  app_unlock: 'Confirma con tu rostro que eres tú para abrir Confío.',
  on_ramp: 'Antes de crear tu recarga, confirma con tu rostro que eres tú.',
  withdrawal: 'Solo tú puedes mover tu dinero. Confirma con tu rostro para continuar.',
  emergency_exit: 'Para proteger tu salida de emergencia, confirma con tu rostro que eres tú.',
  payin_release: 'Tienes dinero por recibir. Confirma con tu rostro que eres tú para recibirlo.',
};

const FaceGlyph = ({ color, spinning }: { color: string; spinning: boolean }) => {
  const rotate = useRef(new Animated.Value(0)).current;
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = spinning
      ? Animated.loop(Animated.timing(rotate, {
          toValue: 1, duration: 1100, easing: Easing.linear, useNativeDriver: true,
        }))
      : Animated.loop(Animated.sequence([
          Animated.timing(pulse, { toValue: 1, duration: 1200, useNativeDriver: true }),
          Animated.timing(pulse, { toValue: 0, duration: 1200, useNativeDriver: true }),
        ]));
    loop.start();
    return () => loop.stop();
  }, [spinning, rotate, pulse]);

  const spin = rotate.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  const scale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.08] });

  return (
    <View style={styles.glyphWrap}>
      <Animated.View style={[styles.halo, { transform: [{ scale }] }]} />
      {spinning && (
        <Animated.View style={[StyleSheet.absoluteFill, styles.center, { transform: [{ rotate: spin }] }]}>
          <Svg width={132} height={132} viewBox="0 0 132 132">
            <Circle cx={66} cy={66} r={62} stroke={color} strokeWidth={4} strokeDasharray="90 300"
              strokeLinecap="round" fill="none" />
          </Svg>
        </Animated.View>
      )}
      <Svg width={84} height={84} viewBox="0 0 84 84">
        {/* Face ID-style corner brackets */}
        <Path d="M4 24V14C4 8.5 8.5 4 14 4H24M60 4H70C75.5 4 80 8.5 80 14V24M80 60V70C80 75.5 75.5 80 70 80H60M24 80H14C8.5 80 4 75.5 4 70V60"
          stroke={color} strokeWidth={5} strokeLinecap="round" fill="none" />
        <Path d="M30 32V38M54 32V38" stroke={color} strokeWidth={5} strokeLinecap="round" />
        <Path d="M42 34V48H38" stroke={color} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <Path d="M30 57C34 61 38 62.5 42 62.5C46 62.5 50 61 54 57" stroke={color} strokeWidth={5}
          strokeLinecap="round" fill="none" />
      </Svg>
    </View>
  );
};

export const FaceCheckProvider = ({ children }: { children: React.ReactNode }) => {
  const [purpose, setPurpose] = useState<FaceCheckPurpose | null>(null);
  const [stage, setStage] = useState<Stage>('intro');
  const [message, setMessage] = useState<string | undefined>();
  const settle = useRef<((passed: boolean) => void) | null>(null);
  const openPurpose = useRef<FaceCheckPurpose | null>(null);
  const openBackend = useRef<FaceCheckBackend | undefined>(undefined);
  const requestId = useRef(0);
  const captureBusy = useRef(false);
  const successTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  type Waiting = { purpose: FaceCheckPurpose; backend?: FaceCheckBackend; resolve: (passed: boolean) => void };
  const queue = useRef<Waiting[]>([]);
  const presentRef = useRef<((purpose: FaceCheckPurpose, backend?: FaceCheckBackend) => Promise<boolean>) | null>(null);

  const close = useCallback((passed: boolean) => {
    if (successTimer.current) clearTimeout(successTimer.current);
    successTimer.current = null;
    requestId.current += 1;
    captureBusy.current = false;
    const done = settle.current;
    settle.current = null;
    openPurpose.current = null;
    openBackend.current = undefined;
    setPurpose(null);
    done?.(passed);
    const waiting = queue.current.shift();
    if (waiting && presentRef.current) {
      // Advance in place; no delayed callback may settle another request.
      void presentRef.current(waiting.purpose, waiting.backend).then(waiting.resolve);
    }
  }, []);

  useEffect(() => {
    const present = (next: FaceCheckPurpose, backend?: FaceCheckBackend) => new Promise<boolean>(resolve => {
      // A second request for the same purpose (and server) joins the open
      // check. The server grades purposes differently (a deposit spends its
      // own check), so anything else waits its turn instead of sharing an
      // outcome.
      if (settle.current) {
        if (openPurpose.current === next && openBackend.current === backend) {
          const previous = settle.current;
          settle.current = passed => { previous(passed); resolve(passed); };
        } else {
          queue.current.push({ purpose: next, backend, resolve });
        }
        return;
      }
      openPurpose.current = next;
      requestId.current += 1;
      openBackend.current = backend;
      settle.current = resolve;
      setMessage(undefined);
      setStage('intro');
      setPurpose(next);
    });
    presentRef.current = present;
    registerFaceCheckPresenter(present);
    return () => {
      registerFaceCheckPresenter(null);
      presentRef.current = null;
      requestId.current += 1;
      if (successTimer.current) clearTimeout(successTimer.current);
      successTimer.current = null;
      settle.current?.(false);
      settle.current = null;
      queue.current.splice(0).forEach(waiting => waiting.resolve(false));
    };
  }, []);

  const start = useCallback(async () => {
    if (!purpose || captureBusy.current) return;
    captureBusy.current = true;
    const id = requestId.current;
    setMessage(undefined);
    setStage('capturing');
    const result = await runFaceCapture(purpose, () => {
      if (id === requestId.current) setStage('grading');
    }, openBackend.current);
    if (id !== requestId.current) return;
    if (result.outcome === 'passed') {
      setStage('passed');
      successTimer.current = setTimeout(() => {
        if (id === requestId.current) close(true);
      }, 900);
    } else if (result.outcome === 'cancelled') {
      captureBusy.current = false;
      setStage('intro');
    } else {
      captureBusy.current = false;
      setMessage(result.message);
      setStage(result.outcome === 'unavailable' ? 'unavailable' : 'failed');
    }
  }, [purpose, close]);

  const busy = stage === 'capturing' || stage === 'grading' || stage === 'passed';

  return (
    <>
      {children}
      <Modal visible={purpose !== null} transparent animationType="slide"
        onRequestClose={() => { if (!captureBusy.current) close(false); }}>
        <View style={styles.backdrop}>
          <View style={styles.sheet}>
            {stage === 'passed' ? (
              <View style={styles.center}>
                <View style={[styles.resultBadge, { backgroundColor: EMERALD }]}>
                  <Icon name="check" size={44} color="#FFFFFF" />
                </View>
                <Text style={styles.title}>¡Listo, eres tú!</Text>
              </View>
            ) : stage === 'failed' || stage === 'unavailable' ? (
              <View style={styles.center}>
                <View style={[styles.resultBadge, { backgroundColor: '#FEE2E2' }]}>
                  <Icon name={stage === 'failed' ? 'x' : 'alert-circle'} size={40} color={DANGER} />
                </View>
                <Text style={styles.title}>
                  {stage === 'failed' ? 'No pudimos confirmar que eres tú' : 'Verificación no disponible'}
                </Text>
                {!!message && <Text style={styles.body}>{message}</Text>}
                {stage === 'failed' && (
                  <Pressable style={styles.primary} onPress={start}>
                    <Text style={styles.primaryText}>Intentar de nuevo</Text>
                  </Pressable>
                )}
                <Pressable style={styles.secondary} onPress={() => close(false)}>
                  <Text style={styles.secondaryText}>{stage === 'failed' ? 'Cancelar' : 'Entendido'}</Text>
                </Pressable>
              </View>
            ) : (
              <View style={styles.center}>
                <FaceGlyph color={EMERALD} spinning={busy} />
                <Text style={styles.eyebrow}>CONFÍO FACE</Text>
                <Text style={styles.title}>{busy ? 'Verificando…' : 'Confirma que eres tú'}</Text>
                {!busy && (
                  <>
                    <Text style={styles.body}>{purpose ? PURPOSE_COPY[purpose] : ''}</Text>
                    <View style={styles.tips}>
                      <Tip icon="sun" text="Busca buena luz y mira de frente a la cámara." />
                      <Tip icon="eye" text="Sin gafas oscuras, gorra ni mascarilla." />
                      <Tip icon="alert-triangle"
                        text="La pantalla mostrará luces de colores unos segundos. Si eres sensible a luces intermitentes, no continúes." />
                    </View>
                    <Pressable style={styles.primary} onPress={start}>
                      <Text style={styles.primaryText}>Confirmar con mi rostro</Text>
                    </Pressable>
                    <Pressable style={styles.secondary} onPress={() => close(false)}>
                      <Text style={styles.secondaryText}>Ahora no</Text>
                    </Pressable>
                  </>
                )}
                {busy && <ActivityIndicator color={EMERALD} style={{ marginTop: 12 }} />}
              </View>
            )}
          </View>
        </View>
      </Modal>
    </>
  );
};

const Tip = ({ icon, text }: { icon: string; text: string }) => (
  <View style={styles.tip}>
    <View style={styles.tipIcon}><Icon name={icon} size={16} color={EMERALD} /></View>
    <Text style={styles.tipText}>{text}</Text>
  </View>
);

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(17,24,39,0.45)', justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: '#FFFFFF', borderTopLeftRadius: 28, borderTopRightRadius: 28,
    paddingHorizontal: 24, paddingTop: 28, paddingBottom: 40,
  },
  center: { alignItems: 'center', justifyContent: 'center' },
  glyphWrap: { width: 132, height: 132, alignItems: 'center', justifyContent: 'center', marginBottom: 16 },
  halo: {
    position: 'absolute', width: 124, height: 124, borderRadius: 62, backgroundColor: EMERALD_LIGHT,
  },
  eyebrow: { fontSize: 12, letterSpacing: 2, fontWeight: '700', color: EMERALD, marginBottom: 6 },
  title: { fontSize: 22, fontWeight: '700', color: INK, textAlign: 'center', marginBottom: 8 },
  body: { fontSize: 15, lineHeight: 21, color: MUTED, textAlign: 'center', marginBottom: 18 },
  tips: { alignSelf: 'stretch', marginBottom: 22 },
  tip: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 10 },
  tipIcon: {
    width: 28, height: 28, borderRadius: 14, backgroundColor: EMERALD_LIGHT,
    alignItems: 'center', justifyContent: 'center', marginRight: 12,
  },
  tipText: { flex: 1, fontSize: 14, lineHeight: 20, color: INK },
  primary: {
    alignSelf: 'stretch', backgroundColor: EMERALD, borderRadius: 16, paddingVertical: 16, alignItems: 'center',
  },
  primaryText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
  secondary: { alignSelf: 'stretch', paddingVertical: 14, alignItems: 'center', marginTop: 4 },
  secondaryText: { color: MUTED, fontSize: 15, fontWeight: '600' },
  resultBadge: {
    width: 88, height: 88, borderRadius: 44, alignItems: 'center', justifyContent: 'center', marginBottom: 16,
  },
});
