// Cuenta inteligente: the beneficiary starts a claim (spec 6.2, 8.2).
//
// Says what starting does before it is signed: the owner is told at once and
// for the whole window, any signature of theirs cancels it, and the date the
// account could be received is fixed from the moment of signing. When the
// claim cannot be started (a cooldown after a cancelled one), the date it
// can is shown instead of the button.
import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import {
  ActionButton, Card, Empty, Fact, LoadError, Notice, NumberedList, ScreenSkeleton, SectionTitle, SmartScreen,
  kitStyles,
} from '../components/smartAccount/kit';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { DirectClaimPanel } from '../components/smartAccount/DirectClaimPanel';
import { useRememberDirectClaim } from '../components/smartAccount/useRememberDirectClaim';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_DESIGNATED } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { daysLabel, shortAddress, shortDate } from '../components/smartAccount/format';
import { fetchBeneficiaryDesignations, prepareBeneficiaryClaim } from '../services/smartAccount';
import type { MainStackParamList } from '../types/navigation';

export function claimMeaning(owner: string, days: number): string[] {
  return [
    `Le avisamos a ${owner} de inmediato y durante todo el plazo, por todos los medios.`,
    `Si ${owner} firma una acción en su Cuenta inteligente o una operación desde su cuenta personal, el pedido se cancela.`,
    `Si pasan ${daysLabel(days)} sin ninguna firma suya, puedes recibir la cuenta y lo que tenga.`,
  ];
}

export function BeneficiaryClaimScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'BeneficiaryClaim'>>();
  const designationId = route.params?.designationId;
  const storedAccount = route.params?.account;
  const list = useSmartRead(fetchBeneficiaryDesignations);
  const flow = useSignFlow();
  const d = (list.data ?? []).find((x) => x.designationId === designationId) ?? null;
  useRememberDirectClaim(list.data, (x) => (x.contractAddress && (x.state === 'active' || x.claim)
    ? { account: x.contractAddress, designationId: x.designationId, ownerName: x.ownerName, chainName: x.chainName || undefined }
    : null));
  const inFlight = !!d?.claim && (d.claim.state === 'pending' || d.claim.state === 'executable');

  useEffect(() => {
    if (inFlight) {
      navigation.replace('BeneficiaryClaimStatus', { designationId });
    }
  }, [inFlight, navigation, designationId]);

  const canStart = !!d && d.state === 'active' && d.canClaim;

  return (
    <SmartScreen
      title="Pedir la cuenta"
      help={HELP_DESIGNATED}
      footer={canStart ? (
        <ActionButton
          label="Pedir la cuenta"
          onPress={() => { void flow.start({ prepare: () => prepareBeneficiaryClaim(d!.designationId) }); }}
          testID="claim-start"
        />
      ) : undefined}
    >
      {list.loading && !list.data ? <ScreenSkeleton /> : list.failed && !list.data ? (
        <View>
          <LoadError onRetry={list.reload} busy={list.loading} />
          <View style={kitStyles.pad}>
            <DirectClaimPanel designationId={designationId} account={storedAccount} serverDown onDone={() => { void list.reload(); }} />
          </View>
        </View>
      ) : !d || d.state !== 'active' ? (
        <Empty icon="user-x" title="Ya no eres beneficiario de esta cuenta" actionLabel="Volver" onAction={() => navigation.goBack()} />
      ) : (
        <View style={kitStyles.pad}>
          <Text style={styles.title} accessibilityRole="header">{`Cuenta de ${d.ownerName}`}</Text>
          <Text style={kitStyles.body}>Pídela solo si su dueño dejó de usarla.</Text>
          <SectionTitle>Qué pasa cuando la pides</SectionTitle>
          <Card style={styles.list}><NumberedList items={claimMeaning(d.ownerName, d.windowDays)} /></Card>
          <Card style={kitStyles.gap}>
            <Fact label="Plazo" value={daysLabel(d.windowDays)} />
            <Fact divider label="Aceptaste el" value={shortDate(d.acceptedAt) || '—'} />
            {d.contractAddress ? <Fact divider label="Cuenta" value={shortAddress(d.contractAddress)} /> : null}
          </Card>
          {!d.canClaim ? (
            <Notice
              tone="neutral"
              icon="clock"
              title="Todavía no puedes pedirla"
              body={d.cooldownUntil
                ? `Un pedido anterior se canceló. Podrás pedirla de nuevo desde el ${shortDate(d.cooldownUntil)}.`
                : 'Por ahora esta cuenta no admite un pedido.'}
              style={kitStyles.gap}
              testID="claim-blocked"
            />
          ) : null}
          <DirectClaimPanel designationId={d.designationId} serverDown={false} ownerName={d.ownerName} onDone={() => { void list.reload(); }} />
        </View>
      )}
      <SignFlowSheet
        flow={flow}
        copy={{
          confirmLabel: 'Firmar y pedir',
          confirmNote: 'El plazo empieza al firmar y su fecha final ya no cambia.',
          signingMessage: 'Enviando tu pedido…',
          successTitle: 'Pedido enviado',
          successBody: 'Te mostramos cuánto falta.',
          successLabel: 'Ver el plazo',
        }}
        onDone={() => navigation.replace('BeneficiaryClaimStatus', { designationId })}
      />
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 24, lineHeight: 31, fontWeight: '700', color: SA.text, marginBottom: 6 },
  list: { paddingVertical: 8 },
});
