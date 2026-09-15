import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Linking, SafeAreaView, ScrollView, StatusBar, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect, useNavigation } from '@react-navigation/native';

import { colors } from '../../config/theme';
import { useAccount } from '../../contexts/AccountContext';
import { useAuth } from '../../contexts/AuthContext';
import { RampActionBar } from '../ramps/RampActionBar';
import { RampHero } from '../ramps/RampHero';
import { RampReveal } from '../ramps/RampReveal';
import { RampStepHeader } from '../ramps/RampStepHeader';
import { rampFlowStyles as styles } from '../ramps/rampFlowStyles';
import {
  BREB_PERMISSION_ERROR,
  brebLocationPassRemainingMs,
  brebLocationPassValid,
  onBrebLocationPassChange,
  brebLocationSupported,
  hasBrebLocationPermission,
  verifyBrebLocation,
} from '../../services/brebLocation';

type GateState = 'checking' | 'ok' | 'intro' | 'denied' | 'failed' | 'unsupported';

const HOW_IT_WORKS: [string, string, string][] = [
  ['map-pin', 'Disponible donde estás', 'Confirmamos que Bre-B está disponible en tu ubicación antes de abrir tu cuenta y al usarlo.'],
  ['crosshair', 'Ubicación precisa al usar Bre-B', 'La verificamos al activar Bre-B y cuando hace falta al usarlo. No rastreamos tu ubicación en segundo plano.'],
  ['shield', 'Tu app, verificada', 'Usamos la verificación de Apple o Google para proteger esta solicitud.'],
  ['file-text', 'Un registro de cada verificación', 'Guardamos el resultado y la ubicación de cada verificación como registro de cumplimiento. Nunca para otro fin.'],
];

/** The user/account context a location pass belongs to (never shared across accounts). */
export function useBrebLocationScope(): string {
  const {activeAccount} = useAccount();
  const {profileData, accountContextTick, isAuthenticated} = useAuth();
  const userId = profileData?.userProfile?.id;
  return isAuthenticated && userId && activeAccount ? `${userId}:${activeAccount.id}:${accountContextTick}` : '';
}

/**
 * Whether this user/account has a current Bre-B location pass, for screens
 * that show a key: refreshed on focus and followed to its expiry (re-armed
 * from the current deadline, so a renewed pass is followed too).
 */
export function useBrebLocationPass(enabled = true): boolean {
  const scope = useBrebLocationScope();
  const [ok, setOk] = useState(() => enabled && brebLocationPassValid(scope));
  useFocusEffect(useCallback(() => {
    if (enabled) setOk(brebLocationPassValid(scope));
  }, [enabled, scope]));
  // A pass granted, renewed or forgotten anywhere (e.g. a refused operation)
  // shows or hides the key at once.
  useEffect(() => {
    if (!enabled) return undefined;
    return onBrebLocationPassChange(() => setOk(brebLocationPassValid(scope)));
  }, [enabled, scope]);
  useEffect(() => {
    if (!enabled) return undefined;
    setOk(brebLocationPassValid(scope));
    let timer: ReturnType<typeof setTimeout>;
    const check = () => {
      const valid = brebLocationPassValid(scope);
      setOk(valid);
      if (valid) timer = setTimeout(check, Math.max(brebLocationPassRemainingMs(scope), 0) + 1000);
    };
    timer = setTimeout(check, Math.max(brebLocationPassRemainingMs(scope), 0) + 1000);
    return () => clearTimeout(timer);
  }, [enabled, scope, ok]);
  return enabled && ok;
}

/**
 * Bre-B is usable from anywhere except Venezuela. This is the location step of
 * a Bre-B application (and of renewing a lapsed check before showing a key):
 * the permission screen the first time, a silent check afterwards, and a
 * recent pass skips it. The server refuses every Bre-B operation without one.
 */
export function BrebLocationGate({ enabled = true, force = false, children }: {
  enabled?: boolean;
  /** Always verify again (a recovery entry point): never trust the cached pass. */
  force?: boolean;
  children: React.ReactNode;
}) {
  const scope = useBrebLocationScope();
  return <ScopedBrebLocationGate key={scope} scope={scope} enabled={enabled} force={force}>{children}</ScopedBrebLocationGate>;
}

function ScopedBrebLocationGate({scope, enabled, force, children}: {
  scope: string; enabled: boolean; force: boolean; children: React.ReactNode;
}) {
  const navigation = useNavigation<any>();
  // A forced check skips the cached pass: the server may no longer accept it
  // (another network or IP), which is exactly why the person is here.
  const [state, setState] = useState<GateState>(() => (
    !enabled || (!force && brebLocationPassValid(scope)) ? 'ok' : 'checking'));
  const [message, setMessage] = useState('');
  const running = useRef(false);
  // Force one fresh check per visit, including a result received while blurred.
  const verifiedThisVisit = useRef(false);
  const focused = useRef(false);

  const verify = useCallback(async (requestPermission = false) => {
    if (running.current || !focused.current) return;
    running.current = true;
    setState('checking');
    try {
      await verifyBrebLocation(scope, requestPermission);
      verifiedThisVisit.current = true;
      if (focused.current) setState('ok');
    } catch (error: any) {
      if (!focused.current) return;
      setMessage(error?.message || 'No pudimos confirmar tu ubicación.');
      // Only a refused system permission means "open Settings"; a server or
      // device-check failure after it was granted is a plain retry.
      setState(error?.code === BREB_PERMISSION_ERROR ? 'denied' : 'failed');
    } finally {
      running.current = false;
    }
  }, [scope]);

  useFocusEffect(
    useCallback(() => {
      focused.current = true;
      // Permission answers belong to this focus interval, not a later visit.
      let active = true;
      if (!enabled || ((!force || verifiedThisVisit.current) && brebLocationPassValid(scope))) {
        setState('ok');
      } else if (!brebLocationSupported()) {
        setState('unsupported');
      } else {
        hasBrebLocationPermission()
          .then(allowed => {
            if (!active) return;
            if (allowed) verify(); else setState('intro');
          })
          .catch(() => { if (active) setState('intro'); });
      }
      return () => { active = false; focused.current = false; };
    }, [enabled, force, verify, scope]),
  );

  if (state === 'ok') return <>{children}</>;

  const problem = state === 'failed' || state === 'denied';
  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <RampReveal delay={0}>
          <RampHero
            eyebrow="Bre-B"
            title="Confirma tu ubicación"
            subtitle="Confío usa tu ubicación precisa para verificar que puedes activar y usar Bre-B desde tu ubicación actual."
            onBack={() => navigation.goBack()}
          />
        </RampReveal>

        {state === 'checking' ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} />
            <Text style={styles.loadingText}>Confirmando tu ubicación…{'\n'}Toma unos segundos.</Text>
          </View>
        ) : state === 'unsupported' ? (
          <View style={styles.emptyStateCard}>
            <View style={styles.emptyStateIconWrap}>
              <Icon name="download" size={22} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyStateTitle}>Actualiza la app</Text>
            <Text style={styles.emptyStateText}>
              Usa la versión más reciente de Confío en un Android compatible o un iPhone con iOS 15 o posterior y App Attest disponible.
            </Text>
          </View>
        ) : (
          <RampReveal delay={80}>
            <View style={styles.section}>
              <RampStepHeader
                number={1}
                title="Así lo confirmamos"
                accentColor={colors.primaryDark}
                accentBackground={colors.primaryLight}
                titleColor={colors.dark}
              />
              <View style={styles.inputCard}>
                {HOW_IT_WORKS.map(([icon, title, body]) => (
                  <View key={title} style={[styles.reviewRow, { alignItems: 'center' }]}>
                    <View style={styles.methodIcon}>
                      <Icon name={icon} size={18} color={colors.primary} />
                    </View>
                    <View style={styles.methodCopy}>
                      <Text style={styles.methodTitle}>{title}</Text>
                      <Text style={styles.methodText}>{body}</Text>
                    </View>
                  </View>
                ))}
              </View>
              {problem ? (
                <View style={styles.warningCard}>
                  <Icon name="alert-triangle" size={18} color={colors.warning.icon} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.warningTitle}>
                      {state === 'denied' ? 'Falta el permiso de ubicación' : 'No pudimos confirmar tu ubicación'}
                    </Text>
                    <Text style={styles.warningText}>
                      {state === 'denied'
                        ? 'Permite la ubicación precisa para usar Bre-B. Si la negaste antes, actívala en Ajustes.'
                        : message}
                    </Text>
                  </View>
                </View>
              ) : null}
            </View>
          </RampReveal>
        )}

        {state === 'intro' || problem ? (
          <RampActionBar
            primaryLabel={state === 'intro' ? 'Permitir ubicación y continuar' : 'Intentar de nuevo'}
            onPrimaryPress={() => verify(true)}
            primaryIconName="map-pin"
            secondaryLabel={state === 'denied' ? 'Abrir Ajustes' : 'Ahora no'}
            onSecondaryPress={state === 'denied' ? () => { Linking.openSettings().catch(() => {}); } : () => navigation.goBack()}
          />
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
