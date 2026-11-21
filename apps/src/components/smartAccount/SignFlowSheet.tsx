// What the user sees while a Cuenta inteligente action is prepared, confirmed,
// signed and settled. One component for every flow, so the wording of the
// three endings never drifts:
//
//   executed  "Listo"
//   unknown   "Estamos confirmando" (it may have gone through: no retry here)
//   failed    "No se realizó" + "No se movió nada"
//
// The confirm step shows the server's summary lines verbatim: they describe
// the exact batch that will be signed, prices and amounts included, so no
// number in it comes from this client.
import React from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../common/AppText';
import { LoadingOverlay } from '../LoadingOverlay';
import { ActionButton, Sheet } from './kit';
import { SA } from './tokens';
import type { SignFlow } from './useSignFlow';

export interface SignFlowCopy {
  /** Sheet title of the confirm step, e.g. "Revisa antes de firmar". */
  confirmTitle?: string;
  /** The signing button, e.g. "Firmar y abrir cuenta". */
  confirmLabel?: string;
  /** A line under the summary (what the signature means). */
  confirmNote?: string;
  /** Loading message while signing, e.g. "Abriendo tu cuenta…". */
  signingMessage?: string;
  successTitle?: string;
  successBody?: string;
  successLabel?: string;
}

export function SignFlowSheet({ flow, copy = {}, onDone, onUnknownDone }: {
  flow: SignFlow;
  copy?: SignFlowCopy;
  /** After the user closes the success state. */
  onDone?: () => void;
  /** After the user closes the "confirming" state. Defaults to onDone. */
  onUnknownDone?: () => void;
}) {
  const { state, confirm, reset } = flow;
  const { phase } = state;
  const sheetVisible = phase === 'preparing' || phase === 'confirm' || phase === 'executed'
    || phase === 'unknown' || phase === 'failed';
  const close = () => {
    const was = phase;
    reset();
    if (was === 'executed') {
      onDone?.();
    } else if (was === 'unknown') {
      (onUnknownDone ?? onDone)?.();
    }
  };
  const stepLine = state.steps > 1 ? `Firma ${state.step} de ${state.steps}` : '';

  return (
    <>
      {/* The app-wide loading modal, like the trade and send flows. */}
      <LoadingOverlay
        visible={phase === 'signing'}
        message={[copy.signingMessage || 'Firmando y enviando…', stepLine].filter(Boolean).join('\n')}
      />
      <Sheet
        visible={sheetVisible}
        onClose={close}
        dismissable={phase !== 'preparing'}
        testID="sign-flow-sheet"
      >
        {phase === 'preparing' ? (
          <View style={styles.center} accessibilityLiveRegion="polite">
            <ActivityIndicator size="large" color={SA.deep} />
            <Text style={styles.title}>Preparando…</Text>
          </View>
        ) : null}

        {phase === 'confirm' ? (
          <View>
            <Text style={styles.sheetTitle} accessibilityRole="header">
              {copy.confirmTitle || 'Revisa antes de firmar'}
            </Text>
            <View style={styles.summary}>
              {state.summary.length > 0 ? state.summary.map((line, i) => (
                <View key={`${i}-${line}`} style={[styles.summaryLine, i > 0 && styles.summaryDivider]}>
                  <Icon name="check" size={16} color={SA.deep} style={styles.summaryIcon} />
                  <Text style={styles.summaryText}>{line}</Text>
                </View>
              )) : (
                <Text style={styles.summaryText}>Vas a firmar esta operación con tu billetera.</Text>
              )}
            </View>
            {state.steps > 1 ? (
              <Text style={styles.note}>
                {`Son ${state.steps} firmas seguidas. Te mostramos el avance de cada una.`}
              </Text>
            ) : null}
            {copy.confirmNote ? <Text style={styles.note}>{copy.confirmNote}</Text> : null}
            <ActionButton
              label={copy.confirmLabel || 'Firmar'}
              onPress={confirm}
              style={styles.primary}
              testID="sign-confirm"
            />
            <ActionButton label="Ahora no" variant="quiet" onPress={close} />
          </View>
        ) : null}

        {phase === 'executed' ? (
          <View style={styles.center} accessibilityLiveRegion="polite">
            <View style={[styles.badge, styles.badgeDone]}><Icon name="check" size={30} color={SA.onDeep} /></View>
            <Text style={styles.title}>{copy.successTitle || 'Listo'}</Text>
            {copy.successBody ? <Text style={styles.body}>{copy.successBody}</Text> : null}
            <ActionButton label={copy.successLabel || 'Continuar'} onPress={close} style={styles.wide} testID="sign-done" />
          </View>
        ) : null}

        {phase === 'unknown' ? (
          <View style={styles.center} accessibilityLiveRegion="polite">
            <View style={[styles.badge, styles.badgeWait]}><Icon name="clock" size={28} color={SA.deep} /></View>
            <Text style={styles.title}>Estamos confirmando</Text>
            <Text style={styles.body}>
              Tu operación se envió y todavía no vemos el resultado. No la repitas: revisa tu cuenta en unos minutos.
            </Text>
            <ActionButton label="Entendido" onPress={close} style={styles.wide} testID="sign-unknown-done" />
          </View>
        ) : null}

        {phase === 'failed' ? (
          <View style={styles.center} accessibilityLiveRegion="polite">
            <View style={[styles.badge, styles.badgeFail]}><Icon name="x" size={28} color={SA.muted} /></View>
            <Text style={styles.title}>No se realizó</Text>
            <Text style={styles.body}>{state.error}</Text>
            <ActionButton label="Cerrar" variant="secondary" onPress={close} style={styles.wide} testID="sign-failed-close" />
          </View>
        ) : null}
      </Sheet>
    </>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: 'center', paddingVertical: 16 },
  sheetTitle: { fontSize: 20, fontWeight: '700', color: SA.text, marginBottom: 12 },
  title: { fontSize: 20, fontWeight: '700', color: SA.text, marginTop: 16, textAlign: 'center' },
  body: { fontSize: 15, lineHeight: 22, color: SA.muted, marginTop: 8, textAlign: 'center' },
  summary: { backgroundColor: SA.mint, borderRadius: 16, paddingHorizontal: 14, paddingVertical: 4 },
  summaryLine: { flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 12 },
  summaryDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: SA.mintLine },
  summaryIcon: { marginRight: 10, marginTop: 3 },
  summaryText: { flex: 1, fontSize: 16, lineHeight: 22, fontWeight: '600', color: SA.deep },
  note: { fontSize: 14, lineHeight: 20, color: SA.muted, marginTop: 12 },
  primary: { marginTop: 20 },
  wide: { marginTop: 20, alignSelf: 'stretch' },
  badge: { width: 64, height: 64, borderRadius: 32, alignItems: 'center', justifyContent: 'center' },
  badgeDone: { backgroundColor: SA.deep },
  badgeWait: { backgroundColor: SA.mint },
  badgeFail: { backgroundColor: '#F3F4F6' },
});
