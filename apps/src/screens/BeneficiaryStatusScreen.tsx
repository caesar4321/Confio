// Cuenta inteligente: the owner's view of the beneficiary (spec 6.1, 6.4, 8.2).
//
// States: nobody named; named and waiting for acceptance; active (both dates
// shown: when the owner named them, when they accepted); a claim pending on
// the account; and the designation no longer valid (declined, lapsed, or the
// person's wallet changed). Actions are the owner's four: change the window
// or the person (a new designation the person accepts again), withdraw a
// pending invitation, remove the beneficiary, cancel a pending claim.
import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import {
  AcceptRow, ActionButton, Card, Chip, Empty, NumberedList, Fact, IconDisc, LoadError, Notice, Row, ScreenSkeleton, SectionTitle, Sheet,
  SmartScreen, kitStyles,
} from '../components/smartAccount/kit';
import { SignFlowSheet, type SignFlowCopy } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_BENEFICIARY } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { daysLabel, shortDate } from '../components/smartAccount/format';
import { riskDisclosureLines } from './BeneficiarySetupScreen';
import {
  fetchBeneficiaryRiskDisclosure, fetchSmartAccount, prepareBeneficiaryDesignationWithdrawal, prepareBeneficiaryRemoval,
  prepareBeneficiaryWindowChange, prepareClaimCancel, type SmartAccountBeneficiary,
} from '../services/smartAccount';

const STALE: Record<string, string> = {
  declined: 'No aceptó ser tu beneficiario. Puedes elegir a otra persona.',
  lapsed: 'La invitación venció sin respuesta. Puedes enviarla de nuevo.',
  stale_address: 'Su billetera cambió. Vuelve a nombrarla para que siga siendo tu beneficiario.',
};

type Action = 'withdraw' | 'remove' | 'cancelClaim' | 'window';

/** What changing the window means: the person accepts again (contract rule). */
export function windowChangeNote(name: string, currentDays: number): string {
  return `${name} tendrá que aceptar de nuevo. Hasta que acepte, sigue valiendo el plazo de ${daysLabel(currentDays)}.`;
}

const COPY: Record<Action, SignFlowCopy> = {
  window: {
    confirmTitle: 'Cambiar el plazo', confirmLabel: 'Firmar', signingMessage: 'Enviando el nuevo plazo…',
    successTitle: 'Plazo enviado', successBody: 'Te avisamos cuando lo acepte.',
  },
  withdraw: {
    confirmTitle: 'Retirar la invitación', confirmLabel: 'Firmar y retirar', signingMessage: 'Retirando la invitación…',
    successTitle: 'Invitación retirada',
  },
  remove: {
    confirmTitle: 'Quitar a tu beneficiario', confirmLabel: 'Firmar y quitar', signingMessage: 'Quitando a tu beneficiario…',
    confirmNote: 'Tu cuenta queda sin beneficiario hasta que elijas a otra persona.',
    successTitle: 'Ya no tienes beneficiario',
  },
  cancelClaim: {
    confirmTitle: 'Cancelar el pedido', confirmLabel: 'Firmar y cancelar', signingMessage: 'Cancelando el pedido…',
    successTitle: 'Pedido cancelado', successBody: 'Tu cuenta sigue siendo tuya.',
  },
};

export function BeneficiaryStatusScreen() {
  const navigation = useNavigation<any>();
  const account = useSmartRead(fetchSmartAccount);
  const flow = useSignFlow({ onExecuted: () => { void account.reload(); } });
  const [action, setAction] = useState<Action>('withdraw');
  const [windowSheet, setWindowSheet] = useState(false);
  const [newWindow, setNewWindow] = useState<number | null>(null);
  // The residual-risk disclosure for the NEW window, accepted explicitly
  // before anything is prepared (same sentences as the setup screen).
  const disclosure = useSmartRead(fetchBeneficiaryRiskDisclosure);
  const [windowAccepted, setWindowAccepted] = useState(false);
  const [windowTouched, setWindowTouched] = useState(false);

  useEffect(() => {
    const unsubscribe = navigation.addListener?.('focus', () => { void account.reload(); });
    return typeof unsubscribe === 'function' ? unsubscribe : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigation]);

  const data = account.data ?? null;
  const active = data?.beneficiary ?? null;
  const pending = data?.pendingBeneficiary ?? null;
  const claim = active?.claim && (active.claim.state === 'pending' || active.claim.state === 'executable')
    ? active.claim : null;

  const run = (which: 'withdraw' | 'remove' | 'cancelClaim') => {
    setAction(which);
    void flow.start({
      prepare: () => (which === 'withdraw' ? prepareBeneficiaryDesignationWithdrawal()
        : which === 'remove' ? prepareBeneficiaryRemoval() : prepareClaimCancel()),
    });
  };
  const change = (b: SmartAccountBeneficiary) => navigation.navigate('BeneficiarySetup', {
    handle: b.handle || undefined, name: b.name, windowDays: b.windowDays,
  });
  const windowOptions = (data?.windowOptionsDays ?? []).filter((d) => d !== active?.windowDays);
  const openWindowSheet = () => {
    setNewWindow(windowOptions[0] ?? null);
    setWindowAccepted(false);
    setWindowTouched(false);
    setWindowSheet(true);
  };
  const pickWindow = (d: number) => {
    if (d !== newWindow) {
      setWindowAccepted(false); // the acceptance covers the sentences for one window
    }
    setNewWindow(d);
  };
  const changeWindow = () => {
    setWindowTouched(true);
    if (!newWindow || !windowAccepted) {
      return;
    }
    const days = newWindow;
    setWindowSheet(false);
    setAction('window');
    void flow.start({ faceStepUp: true, prepare: () => prepareBeneficiaryWindowChange(days) });
  };

  return (
    <SmartScreen title="Tu beneficiario" help={HELP_BENEFICIARY} onRefresh={account.reload} refreshing={account.loading && !!data}>
      {account.loading && !data ? <ScreenSkeleton /> : account.failed && !data ? (
        <LoadError onRetry={account.reload} busy={account.loading} />
      ) : !active && !pending ? (
        <Empty
          icon="user-plus"
          title="Aún no elegiste a nadie"
          body="Elige a la persona que recibe esta cuenta si dejas de usarla."
          actionLabel="Elegir beneficiario"
          onAction={() => navigation.navigate('BeneficiarySetup')}
        />
      ) : (
        <View style={kitStyles.pad}>
          {claim ? (
            <Card style={kitStyles.gap}>
              <Notice
                tone="notice"
                icon="alert-circle"
                title={`${active?.name} pidió recibir tu cuenta`}
                body={`Lo pidió el ${shortDate(claim.initiatedAt)}. Lo cancela cualquier acción que firmes en tu Cuenta inteligente o una operación desde tu cuenta personal; las de una cuenta de negocio no. Si no, la cuenta pasa a su nombre el ${shortDate(claim.executableAt)}.`}
                style={kitStyles.gap}
                testID="status-claim"
              />
              <ActionButton label="Sigo aquí: cancelar el pedido" onPress={() => run('cancelClaim')} style={kitStyles.gap} testID="status-cancel-claim" />
              <View style={kitStyles.gap} />
            </Card>
          ) : null}

          {active ? (
            <>
              <SectionTitle>Activo</SectionTitle>
              <Card>
                <Row left={<IconDisc icon="user-check" />} title={active.name} subtitle={active.handle ? `@${active.handle.replace(/^@/, '')}` : 'Tu beneficiario'} />
                <Fact divider label="Lo nombraste el" value={shortDate(active.designatedAt)} />
                <Fact divider label="Aceptó el" value={shortDate(active.acceptedAt) || '—'} />
                <Fact divider label="Plazo para cancelar un pedido" value={daysLabel(active.windowDays)} />
                {active.cooldownUntil ? (
                  <Fact divider label="No puede volver a pedirla hasta el" value={shortDate(active.cooldownUntil)} />
                ) : null}
              </Card>
              {STALE[active.state] ? <Notice tone="notice" body={STALE[active.state]} style={kitStyles.gap} /> : null}
              {windowOptions.length > 0 ? (
                <ActionButton label="Cambiar plazo" variant="secondary" onPress={openWindowSheet} style={kitStyles.gap} testID="status-change-window" />
              ) : null}
              <ActionButton label="Cambiar persona" variant="secondary" onPress={() => change(active)} style={kitStyles.gap} testID="status-change" />
              <ActionButton label="Quitar beneficiario" variant="danger" onPress={() => run('remove')} style={kitStyles.gap} testID="status-remove" />
            </>
          ) : null}

          {pending ? (
            <>
              <SectionTitle>Esperando respuesta</SectionTitle>
              <Card>
                <Row
                  left={<IconDisc icon="clock" tone="neutral" />}
                  title={pending.name}
                  subtitle={STALE[pending.state] ?? 'Todavía no acepta'}
                  testID="status-pending"
                />
                <Fact divider label="Invitación enviada el" value={shortDate(pending.designatedAt)} />
                {pending.expiresAt ? <Fact divider label="Vence el" value={shortDate(pending.expiresAt)} /> : null}
                <Fact divider label="Plazo elegido" value={daysLabel(pending.windowDays)} />
              </Card>
              {!active ? (
                <Notice body="Hasta que acepte, tu cuenta no tiene beneficiario." style={kitStyles.gap} />
              ) : null}
              <ActionButton label="Retirar invitación" variant="secondary" onPress={() => run('withdraw')} style={kitStyles.gap} testID="status-withdraw" />
            </>
          ) : null}
        </View>
      )}
      <Sheet visible={windowSheet} onClose={() => setWindowSheet(false)} title="Cambiar el plazo" testID="window-sheet">
        <Text style={kitStyles.lead}>
          Es el tiempo que tienes para cancelar un pedido de tu cuenta.
        </Text>
        <View style={styles.chips} accessibilityRole="radiogroup">
          {windowOptions.map((d) => (
            <Chip key={d} label={daysLabel(d)} selected={d === newWindow} onPress={() => pickWindow(d)} />
          ))}
        </View>
        {active ? (
          <Notice icon="info" body={windowChangeNote(active.name, active.windowDays)} style={kitStyles.gap} testID="window-note" />
        ) : null}
        {active && newWindow ? (
          <View testID="window-risk">
            <Card style={[styles.risk, kitStyles.gap]}>
              <NumberedList items={riskDisclosureLines(disclosure.data, active.name, newWindow)} />
            </Card>
            <View style={kitStyles.gap}>
              <AcceptRow
                checked={windowAccepted}
                onToggle={() => setWindowAccepted((v) => !v)}
                label="Lo entiendo y lo acepto"
                highlight={windowTouched}
                testID="window-accept"
              />
              {windowTouched && !windowAccepted ? (
                <Text style={styles.fieldError} accessibilityLiveRegion="polite">Marca la casilla para continuar.</Text>
              ) : null}
            </View>
          </View>
        ) : null}
        <ActionButton label="Revisar" onPress={changeWindow} disabled={!newWindow} style={styles.sheetButton} testID="window-review" />
        <ActionButton label="Ahora no" variant="quiet" onPress={() => setWindowSheet(false)} />
      </Sheet>
      <SignFlowSheet
        flow={flow}
        copy={action === 'window' && active
          ? { ...COPY.window, confirmNote: windowChangeNote(active.name, active.windowDays) }
          : COPY[action]}
      />
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 12 },
  sheetButton: { marginTop: 20 },
  risk: { paddingVertical: 8 },
  fieldError: { fontSize: 13, color: SA.noticeText, marginTop: 8, marginLeft: 4 },
});
