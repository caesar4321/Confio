// The owner-side claim alert (spec 8.2 "Claim pending", 6.4).
//
// While the named beneficiary has a claim pending on the viewer's Cuenta
// inteligente, this sits over EVERY screen of the app, in every account
// context: a full-screen modal with one button that signs `cancelClaim`.
// It cannot be dismissed by tapping outside or by the back button. "Ahora
// no" only steps it aside for a short while (the owner may need the app to
// reach someone), and it comes back on its own, on the next app open and on
// every return to the foreground, until the claim is cancelled.
//
// Its read is one isolated query; a failed read changes nothing (an alert
// that is showing keeps showing).
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Modal, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text } from '../common/AppText';
import CuentaInteligenteMark from '../svg/CuentaInteligenteMark';
import { useAuth } from '../../contexts/AuthContext';
import {
  fetchSmartAccountClaimAlert,
  prepareClaimCancel,
  type SmartAccountClaimAlert,
} from '../../services/smartAccount';
import { noteOwnPendingClaim } from '../../services/ownClaimCancel';
import { ActionButton, Fact } from './kit';
import { SignFlowSheet } from './SignFlowSheet';
import { useSignFlow } from './useSignFlow';
import { SA } from './tokens';
import { daysLabel, daysUntil, shortDate } from './format';

const POLL_MS = 5 * 60 * 1000;
const SNOOZE_MS = 10 * 60 * 1000;

export function SmartAccountClaimAlertHost() {
  const { isAuthenticated } = useAuth();
  const insets = useSafeAreaInsets();
  const [shownAlert, setAlert] = useState<SmartAccountClaimAlert | null>(null);
  const [snoozedUntil, setSnoozedUntil] = useState(0);
  const [, setTick] = useState(0);
  const mounted = useRef(true);
  const alertRef = useRef<SmartAccountClaimAlert | null>(null);
  alertRef.current = shownAlert;
  // The claim (by initiatedAt) whose cancel was just executed. A lagging read
  // may still report it; it stays hidden until the server reports no claim
  // or a DIFFERENT claim (which always shows).
  const [cancelledClaim, setCancelledClaim] = useState<string | null>(null);

  const check = useCallback(async () => {
    const result = await fetchSmartAccountClaimAlert();
    // Only an ANSWER may clear the alert. A failed read keeps what is shown.
    if (result.ok) {
      // Shared with the personal sends (spec 6.4 trailing cancelClaim): a
      // "no claim" answer spares them a lookup until the next poll.
      noteOwnPendingClaim(!!result.data);
    }
    if (mounted.current && result.ok) {
      const data = result.data;
      setCancelledClaim((prev) => (data && data.initiatedAt === prev ? prev : null));
      setAlert(data);
    }
  }, []);

  const flow = useSignFlow({
    onExecuted: () => {
      const cancelled = alertRef.current?.initiatedAt;
      if (cancelled) setCancelledClaim(cancelled);
      void check();
    },
  });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!isAuthenticated) {
      setAlert(null);
      return;
    }
    void check();
    const timer = setInterval(() => { void check(); }, POLL_MS);
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        // Coming back to the app always brings the alert back.
        setSnoozedUntil(0);
        void check();
      }
    });
    return () => {
      clearInterval(timer);
      sub.remove();
    };
  }, [isAuthenticated, check]);

  // Re-show when the snooze runs out.
  useEffect(() => {
    if (!snoozedUntil) {
      return;
    }
    const timer = setTimeout(() => setTick((t) => t + 1), Math.max(0, snoozedUntil - Date.now()) + 50);
    return () => clearTimeout(timer);
  }, [snoozedUntil]);

  const idle = flow.state.phase === 'idle';
  const alert = shownAlert && shownAlert.initiatedAt === cancelledClaim ? null : shownAlert;
  // The result of the signature outlives the alert: once the claim is gone
  // the server answers "no alert", and "Pedido cancelado" must still be read.
  if (!alert && idle) {
    return null;
  }
  const visible = Date.now() >= snoozedUntil;
  const days = alert ? daysUntil(alert.executableAt) : null;

  return (
    <>
      {alert ? (
      <Modal
        visible={visible && idle}
        animationType="fade"
        statusBarTranslucent
        // Android back does nothing: the alert is answered, not dismissed.
        onRequestClose={() => {}}
      >
        <View style={[styles.root, { paddingTop: insets.top + 24, paddingBottom: Math.max(insets.bottom, 16) }]} testID="claim-alert">
          <ScrollView contentContainerStyle={styles.content} bounces={false}>
            <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
              <CuentaInteligenteMark size={56} />
            </View>
            <Text style={styles.title} accessibilityRole="header">
              {`${alert.beneficiaryName} pidió recibir tu Cuenta inteligente`}
            </Text>
            <Text style={styles.body}>
              Si eres tú quien usa esta cuenta, confírmalo ahora. Con tu firma el pedido se cancela y tu cuenta sigue igual.
            </Text>
            <View style={styles.card}>
              <Fact label="Pedido el" value={shortDate(alert.initiatedAt)} />
              <Fact
                label="Si no firmas, la cuenta pasa el"
                value={days === null ? shortDate(alert.executableAt) : `${shortDate(alert.executableAt)} · en ${daysLabel(days)}`}
                divider
              />
            </View>
            <Text style={styles.small}>
              También se cancela con las operaciones que firmes desde tu cuenta personal en Confío. Para estar seguro, usa este botón.
            </Text>
          </ScrollView>
          <View style={styles.bar}>
            <ActionButton
              label="Sigo aquí: cancelar el pedido"
              onPress={() => flow.start({ prepare: () => prepareClaimCancel(), skipConfirm: true })}
              testID="claim-alert-cancel"
            />
            <ActionButton
              label="Ahora no"
              variant="quiet"
              onPress={() => setSnoozedUntil(Date.now() + SNOOZE_MS)}
              accessibilityLabel="Ahora no. El aviso vuelve en unos minutos"
            />
          </View>
        </View>
      </Modal>
      ) : null}
      <SignFlowSheet
        flow={flow}
        copy={{
          signingMessage: 'Cancelando el pedido…',
          successTitle: 'Pedido cancelado',
          successBody: 'Tu Cuenta inteligente sigue siendo tuya. No cambió nada más.',
          successLabel: 'Listo',
        }}
        onUnknownDone={() => setSnoozedUntil(Date.now() + SNOOZE_MS)}
      />
    </>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: SA.page, paddingHorizontal: 20 },
  content: { paddingBottom: 24 },
  title: { fontSize: 26, lineHeight: 32, fontWeight: '700', color: SA.text, marginTop: 20 },
  body: { fontSize: 16, lineHeight: 24, color: SA.text, marginTop: 12 },
  card: { backgroundColor: SA.card, borderRadius: 20, paddingHorizontal: 16, marginTop: 20 },
  small: { fontSize: 14, lineHeight: 20, color: SA.muted, marginTop: 16 },
  bar: { paddingTop: 12 },
});
