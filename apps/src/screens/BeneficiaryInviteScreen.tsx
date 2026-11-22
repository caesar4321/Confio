// Cuenta inteligente: the named person's side of a designation (spec 6.1, 8.2).
//
// Before accepting: who named them, what it means in four numbered
// sentences, the window, and two answers (accept and sign, or decline).
// After accepting: the account address and the chain, shown in full and
// copyable, because they are this person's own record of the account.
import React, { useRef, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import { HerenciaArt } from '../components/smartAccount/HerenciaArt';
import {
  ActionButton, Card, Empty, Fact, LoadError, Notice, NumberedList, ScreenSkeleton, SectionTitle, Sheet,
  SmartScreen, kitStyles,
} from '../components/smartAccount/kit';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useRememberDirectClaim } from '../components/smartAccount/useRememberDirectClaim';
import { POLICY_COPY, useSignFlow } from '../components/smartAccount/useSignFlow';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_DESIGNATED } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { daysLabel, shortDate } from '../components/smartAccount/format';
import {
  declineBeneficiaryDesignation, fetchBeneficiaryDesignations, prepareBeneficiaryAcceptance,
} from '../services/smartAccount';
import type { MainStackParamList } from '../types/navigation';

const DECLINE_COPY: Record<string, string> = {
  designation_acceptance_in_progress: POLICY_COPY.designation_acceptance_in_progress,
  designation_already_accepted: POLICY_COPY.designation_already_accepted,
};

export function inviteMeaning(owner: string, days: number): string[] {
  return [
    'Aceptar no mueve dinero ni te cuesta nada.',
    `Si ${owner} deja de usar su cuenta, tú puedes pedirla desde Confío.`,
    `Desde tu pedido corre un plazo de ${daysLabel(days)}. Si ${owner} firma una acción en su Cuenta inteligente o una operación desde su cuenta personal en ese plazo, el pedido se cancela.`,
    'Si el plazo termina sin ninguna firma suya, recibes la cuenta y lo que tenga.',
  ];
}

export function BeneficiaryInviteScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'BeneficiaryInvite'>>();
  const designationId = route.params?.designationId;
  const list = useSmartRead(fetchBeneficiaryDesignations);
  // An acceptance that executed hides the footer for that designation until
  // the server stops reporting it pending (the list may lag the chain).
  const [acceptedIds, setAcceptedIds] = useState<ReadonlySet<string>>(new Set());
  const accepting = useRef<string | null>(null);
  const flow = useSignFlow({
    onExecuted: () => {
      const id = accepting.current;
      if (id) {
        setAcceptedIds((prev) => new Set(prev).add(id));
      }
      void list.reload();
    },
  });
  const [declining, setDeclining] = useState(false);
  const [declineBusy, setDeclineBusy] = useState(false);
  const [declineError, setDeclineError] = useState('');
  const [copied, setCopied] = useState(false);

  const d = (list.data ?? []).find((x) => x.designationId === designationId) ?? null;
  // The address shown after accepting is also kept on this phone for the
  // direct claim path (spec 6.7).
  useRememberDirectClaim(list.data, (x) => (x.contractAddress && (x.state === 'active' || x.claim)
    ? { account: x.contractAddress, designationId: x.designationId, ownerName: x.ownerName, chainName: x.chainName || undefined }
    : null));

  const decline = async () => {
    if (!d || declineBusy) {
      return;
    }
    setDeclineBusy(true);
    setDeclineError('');
    const result = await declineBeneficiaryDesignation(d.designationId);
    setDeclineBusy(false);
    if (!result.success) {
      // A decline that races this person's own acceptance has its own
      // sentence (no "try again": retrying would be refused the same way).
      setDeclineError((result.errorCode && DECLINE_COPY[result.errorCode])
        || result.errorMessage || 'No pudimos guardar tu respuesta. Inténtalo de nuevo.');
      if (result.errorCode === 'designation_already_accepted') {
        void list.reload();
      }
      return;
    }
    setDeclining(false);
    void list.reload();
  };

  const pending = d?.state === 'pending_acceptance';
  const justAccepted = !!d && acceptedIds.has(d.designationId);

  return (
    <SmartScreen
      title="Beneficiario"
      help={HELP_DESIGNATED}
      footer={pending && !justAccepted ? (
        <>
          <ActionButton
            label="Aceptar y firmar"
            onPress={() => {
              accepting.current = d!.designationId;
              void flow.start({ prepare: () => prepareBeneficiaryAcceptance(d!.designationId) });
            }}
            testID="invite-accept"
          />
          <ActionButton label="No acepto" variant="quiet" onPress={() => setDeclining(true)} testID="invite-decline" />
        </>
      ) : undefined}
    >
      {list.loading && !list.data ? <ScreenSkeleton /> : list.failed && !list.data ? (
        <LoadError onRetry={list.reload} busy={list.loading} />
      ) : !d ? (
        <Empty icon="user-x" title="Esta invitación ya no está" body="Puede que la hayan retirado." actionLabel="Volver" onAction={() => navigation.goBack()} />
      ) : pending ? (
        <View style={kitStyles.pad}>
          <HerenciaArt width={168} variant="onLight" style={styles.art} />
          <Text style={styles.title} accessibilityRole="header">
            {`${d.ownerName} te eligió como beneficiario de su Cuenta inteligente`}
          </Text>
          <SectionTitle>Qué significa</SectionTitle>
          {justAccepted ? (
            <Notice
              icon="check-circle"
              title="Aceptaste"
              body="Estamos confirmando tu firma. En unos minutos verás aquí los datos de la cuenta."
              style={kitStyles.gap}
              testID="invite-accepted-pending"
            />
          ) : null}
          <Card style={styles.list}><NumberedList items={inviteMeaning(d.ownerName, d.windowDays)} /></Card>
          <Card style={kitStyles.gap}>
            <Fact label="Plazo" value={daysLabel(d.windowDays)} />
            <Fact divider label="Te eligió el" value={shortDate(d.designatedAt)} />
            {d.expiresAt ? <Fact divider label="Puedes responder hasta el" value={shortDate(d.expiresAt)} /> : null}
          </Card>
        </View>
      ) : d.state === 'active' ? (
        <View style={kitStyles.pad}>
          <Notice icon="check-circle" title={`Eres beneficiario de la cuenta de ${d.ownerName}`} body={`Aceptaste el ${shortDate(d.acceptedAt)}.`} />
          <SectionTitle>Guarda estos datos</SectionTitle>
          <Card>
            <View style={styles.address} accessible accessibilityLabel={`Dirección de la cuenta: ${d.contractAddress || ''}`}>
              <Text style={styles.addressLabel}>Dirección de la cuenta</Text>
              <Text style={styles.addressValue} selectable testID="invite-address">{d.contractAddress || '—'}</Text>
            </View>
            <Fact divider label="Red" value={d.chainName || '—'} />
            <Fact divider label="Plazo" value={daysLabel(d.windowDays)} />
          </Card>
          <Text style={[kitStyles.small, styles.under]}>
            Son tu registro de la cuenta de la que eres beneficiario. Guárdalos en un lugar seguro.
          </Text>
          {d.contractAddress ? (
            <ActionButton
              label={copied ? 'Dirección copiada' : 'Copiar dirección'}
              icon={copied ? 'check' : 'copy'}
              variant="secondary"
              onPress={() => { Clipboard.setString(d.contractAddress as string); setCopied(true); }}
              style={kitStyles.gap}
              testID="invite-copy"
            />
          ) : null}
          <ActionButton label="Listo" onPress={() => navigation.goBack()} style={kitStyles.gap} />
        </View>
      ) : (
        <Empty
          icon="user-x"
          title={d.state === 'declined' ? 'No aceptaste esta invitación' : 'Esta invitación venció'}
          body={`${d.ownerName} puede volver a elegirte cuando quiera.`}
          actionLabel="Volver"
          onAction={() => navigation.goBack()}
        />
      )}

      <Sheet visible={declining} onClose={() => setDeclining(false)} title="¿No aceptas?" dismissable={!declineBusy}>
        <Text style={kitStyles.lead}>
          {`Le avisamos a ${d?.ownerName || 'esa persona'} que no aceptaste. No cambia nada en tu cuenta.`}
        </Text>
        {declineError ? <Text style={[kitStyles.errorText, styles.declineError]}>{declineError}</Text> : null}
        <ActionButton label="No acepto" variant="danger" onPress={() => { void decline(); }} busy={declineBusy} style={styles.sheetButton} testID="invite-decline-confirm" />
        <ActionButton label="Volver" variant="quiet" onPress={() => setDeclining(false)} />
      </Sheet>
      <SignFlowSheet
        flow={flow}
        copy={{
          confirmLabel: 'Firmar y aceptar',
          signingMessage: 'Guardando tu respuesta…',
          successTitle: 'Aceptaste',
          successBody: 'Ahora te mostramos los datos de la cuenta para que los guardes.',
          successLabel: 'Ver datos',
        }}
      />
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  art: { alignSelf: 'center' },
  title: { fontSize: 22, lineHeight: 29, fontWeight: '700', color: SA.text, marginTop: 8, textAlign: 'center' },
  list: { paddingVertical: 8 },
  address: { paddingVertical: 14 },
  addressLabel: { fontSize: 15, color: SA.muted },
  addressValue: { fontSize: 15, lineHeight: 22, fontWeight: '600', color: SA.text, marginTop: 4, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  under: { marginTop: 10, marginHorizontal: 4 },
  sheetButton: { marginTop: 20 },
  declineError: { marginTop: 12, marginBottom: 0 },
});
