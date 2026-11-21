// Cuenta inteligente: a claim in progress, from the beneficiary's side
// (spec 6.3, 6.5, 8.2).
//
// One number carries the screen: the days left. Under it, the fixed date
// (it never moves once the claim is signed), a plain progress bar from the
// day of the claim to that date, and, when the date arrives, the one action:
// receive the account. A cancelled claim says who cancelled it and when a
// new one is possible; an executed one leads to the account.
import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import {
  ActionButton, Card, Empty, Fact, LoadError, Notice, ScreenSkeleton, SmartScreen, kitStyles,
} from '../components/smartAccount/kit';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { DirectClaimPanel } from '../components/smartAccount/DirectClaimPanel';
import { useRememberDirectClaim } from '../components/smartAccount/useRememberDirectClaim';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_DESIGNATED } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { daysUntil, shortDate } from '../components/smartAccount/format';
import {
  fetchBeneficiaryDesignations, fetchInheritedAccounts, prepareBeneficiaryClaimExecute,
} from '../services/smartAccount';
import { loadDirectEntry } from '../services/smartAccountDirect';
import type { MainStackParamList } from '../types/navigation';

/** 0..1 of the window already elapsed. */
export function claimProgress(initiatedAt: string, executableAt: string, now: number = Date.now()): number {
  const start = Date.parse(initiatedAt);
  const end = Date.parse(executableAt);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    return 0;
  }
  return Math.min(1, Math.max(0, (now - start) / (end - start)));
}

export function BeneficiaryClaimStatusScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'BeneficiaryClaimStatus'>>();
  const designationId = route.params?.designationId;
  const list = useSmartRead(fetchBeneficiaryDesignations);
  const flow = useSignFlow();

  useEffect(() => {
    const unsubscribe = navigation.addListener?.('focus', () => { void list.reload(); });
    return typeof unsubscribe === 'function' ? unsubscribe : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigation]);

  const d = (list.data ?? []).find((x) => x.designationId === designationId) ?? null;
  useRememberDirectClaim(list.data, (x) => (x.contractAddress && (x.state === 'active' || x.claim)
    ? { account: x.contractAddress, designationId: x.designationId, ownerName: x.ownerName, chainName: x.chainName || undefined }
    : null));
  const claim = d?.claim ?? null;
  const canExecute = !!d?.canExecute && (claim?.state === 'executable' || claim?.state === 'pending');
  const days = claim ? daysUntil(claim.executableAt) : null;
  const progress = claim ? claimProgress(claim.initiatedAt, claim.executableAt) : 0;
  // The received account is opened by its address: the inherited list may
  // already hold other accounts, and this one may not be registered yet.
  const inheritedParams = d?.contractAddress ? { contractAddress: d.contractAddress } : undefined;

  // The server lists only designations with a pending claim (or none): after
  // an execution the designation is gone. The account it was is known from
  // this phone's direct-claim record; it was received when that record says
  // so (an inherited id) or the inherited list holds that address.
  const designationGone = !!list.data && !d;
  const [deviceEntry, setDeviceEntry] = useState<{ account: string; inherited: boolean } | null>(null);
  useEffect(() => {
    if (!designationGone || !designationId) {
      return;
    }
    let live = true;
    loadDirectEntry({ designationId })
      .then((e) => { if (live) { setDeviceEntry(e ? { account: e.account, inherited: !!e.inheritedAccountId } : null); } })
      .catch(() => {});
    return () => { live = false; };
  }, [designationGone, designationId]);
  const inherited = useSmartRead(fetchInheritedAccounts, { skip: !designationGone || !deviceEntry });
  const receivedAddress = designationGone && deviceEntry && (deviceEntry.inherited
    || (inherited.data ?? []).some((a) => a.contractAddress?.toLowerCase() === deviceEntry.account))
    ? deviceEntry.account : null;
  // Cancelled by the owner: the claim is no longer listed, but the
  // designation carries the cooldown it started.
  const cooldownActive = !!d && !claim && !!d.cooldownUntil && Date.parse(d.cooldownUntil) > Date.now();

  return (
    <SmartScreen
      title="Tu pedido"
      help={HELP_DESIGNATED}
      onRefresh={list.reload}
      refreshing={list.loading && !!list.data}
      footer={canExecute ? (
        <ActionButton
          label="Recibir la cuenta"
          onPress={() => { void flow.start({ prepare: () => prepareBeneficiaryClaimExecute(d!.designationId) }); }}
          testID="claim-execute"
        />
      ) : undefined}
    >
      {list.loading && !list.data ? <ScreenSkeleton /> : list.failed && !list.data ? (
        <View>
          <LoadError onRetry={list.reload} busy={list.loading} />
          <View style={kitStyles.pad}>
            <DirectClaimPanel designationId={designationId} serverDown onDone={() => { void list.reload(); }} />
          </View>
        </View>
      ) : receivedAddress ? (
        <View style={kitStyles.pad}>
          <Notice icon="check-circle" title="La cuenta ya es tuya" body="Ya la recibiste. Puedes mover lo que tiene cuando quieras." testID="claim-received" />
          <ActionButton
            label="Ver la cuenta"
            onPress={() => navigation.navigate('InheritedAccount', { contractAddress: receivedAddress })}
            style={kitStyles.gap}
            testID="claim-view-account"
          />
        </View>
      ) : cooldownActive ? (
        <View style={kitStyles.pad}>
          <Notice
            tone="neutral"
            icon="x-circle"
            title={`${d!.ownerName} canceló el pedido.`}
            body={`Puedes pedirlo de nuevo desde el ${shortDate(d!.cooldownUntil)}.`}
            testID="claim-cancelled"
          />
        </View>
      ) : !d || !claim ? (
        <Empty
          icon="clock"
          title="No hay un pedido en curso"
          actionLabel="Volver"
          onAction={() => navigation.goBack()}
        />
      ) : claim.state === 'cancelled' ? (
        <View style={kitStyles.pad}>
          <Notice
            tone="neutral"
            icon="x-circle"
            title={`${d.ownerName} canceló el pedido`}
            body={`Lo canceló el ${shortDate(claim.cancelledAt)}. Su cuenta sigue siendo suya.`}
            testID="claim-cancelled"
          />
          {d.cooldownUntil ? (
            <Card style={kitStyles.gap}><Fact label="Podrás pedirla de nuevo desde el" value={shortDate(d.cooldownUntil)} /></Card>
          ) : null}
        </View>
      ) : claim.state === 'executed' ? (
        <View style={kitStyles.pad}>
          <Notice icon="check-circle" title="La cuenta ya es tuya" body={`La recibiste el ${shortDate(claim.executedAt)}.`} />
          <ActionButton label="Ver la cuenta" onPress={() => navigation.navigate('InheritedAccount', inheritedParams)} style={kitStyles.gap} />
        </View>
      ) : (
        <View style={kitStyles.pad}>
          <Card style={styles.hero}>
            <Text style={styles.label}>{`Cuenta de ${d.ownerName}`}</Text>
            {canExecute ? (
              <Text style={styles.big} accessibilityRole="header">Ya puedes recibirla</Text>
            ) : (
              <Text style={styles.big} accessibilityRole="header" testID="claim-days">
                {days === 1 ? 'Falta 1 día' : `Faltan ${days ?? '—'} días`}
              </Text>
            )}
            <View
              style={styles.track}
              accessible
              accessibilityRole="progressbar"
              accessibilityValue={{ min: 0, max: 100, now: Math.round(progress * 100) }}
              accessibilityLabel="Avance del plazo"
            >
              <View style={[styles.fill, { width: `${Math.round(progress * 100)}%` }]} />
            </View>
            <Fact label="Lo pediste el" value={shortDate(claim.initiatedAt)} />
            <Fact divider label={canExecute ? 'Disponible desde el' : 'Podrás recibirla el'} value={shortDate(claim.executableAt)} />
          </Card>
          <Text style={[kitStyles.small, styles.under]}>
            {canExecute
              ? 'Al recibirla, la cuenta pasa a tu nombre. Después puedes mover lo que tenga a tu billetera.'
              : `La fecha es fija. Si ${d.ownerName} firma una acción en su Cuenta inteligente o una operación desde su cuenta personal antes, el pedido se cancela y te avisamos.`}
          </Text>
          <DirectClaimPanel designationId={d.designationId} serverDown={false} ownerName={d.ownerName} onDone={() => { void list.reload(); }} />
        </View>
      )}
      <SignFlowSheet
        flow={flow}
        copy={{
          confirmLabel: 'Firmar y recibir',
          signingMessage: 'Pasando la cuenta a tu nombre…',
          successTitle: 'La cuenta ya es tuya',
          successBody: 'Puedes mover lo que tiene cuando quieras.',
          successLabel: 'Ver la cuenta',
        }}
        onDone={() => navigation.replace('InheritedAccount', inheritedParams)}
      />
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  hero: { paddingTop: 20, paddingBottom: 4 },
  label: { fontSize: 15, color: SA.muted },
  big: { fontSize: 34, lineHeight: 40, fontWeight: '700', color: SA.text, marginTop: 4 },
  track: { height: 8, borderRadius: 4, backgroundColor: SA.mint, marginTop: 16, marginBottom: 8, overflow: 'hidden' },
  fill: { height: 8, borderRadius: 4, backgroundColor: SA.deep },
  under: { marginTop: 12, marginHorizontal: 4 },
});
