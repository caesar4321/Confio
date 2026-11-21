// Cuenta inteligente: the plan and its charges (spec 5, 8.2 "Payment problem").
//
// When a payment is short the top of the screen is the whole story in order:
// how much is missing, since when the notices run, what would be sold and
// from which day, and the one action that fixes it (add dollars). When the
// plan is current that block is absent and the screen is the plan, a way to
// change it, and the charges: a bounded preview with "Ver todos".
import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import {
  ActionButton, Card, Empty, Fact, IconDisc, LoadError, Notice, Row, RowsSkeleton, ScreenSkeleton, SectionTitle,
  SmartScreen, kitStyles,
} from '../components/smartAccount/kit';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_BILLING } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { DEX_TRADING_UI_ENABLED } from '../config/features';
import { planLabel, planName, planPeriod, shortDate, usd } from '../components/smartAccount/format';
import {
  fetchSmartAccount, fetchSmartAccountCharges, fetchSmartAccountOffer, prepareSmartAccountPlanChange,
  type SmartAccountBilling, type SmartAccountCharge,
} from '../services/smartAccount';

const PREVIEW = 5;

const PAID_WITH: Record<string, string> = {
  cusd: 'Con Confío Dollar',
  cusd_plus: 'Con Confío Dollar+',
  mixed: 'Con tus dólares',
  sale: 'Con una venta de inversiones',
};

export const chargeTitle = (c: SmartAccountCharge): string => `${planLabel(c.plan)} · ${shortDate(c.chargedAt)}`;
export const chargeSubtitle = (c: SmartAccountCharge): string =>
  [PAID_WITH[c.paidWith] ?? '', `hasta el ${shortDate(c.periodEnd)}`].filter(Boolean).join(' · ');

const BITCOIN_OR_GOLD = /^(crypto:|.*\b(btcb?|wbtc|xaut|paxg|bitcoin|oro|gold)\b)/i;

/**
 * The sale order as this build can name it. A build without Oro y Bitcoin
 * (iOS) does not name those assets, but never hides that they may be sold:
 * they appear once, in their place, as "otras inversiones de tu cuenta".
 */
export function saleCandidateLabels(candidates: readonly string[], dexUi: boolean = DEX_TRADING_UI_ENABLED): string[] {
  const out: string[] = [];
  let generic = false;
  for (const c of candidates) {
    if (!c) {
      continue;
    }
    if (!dexUi && BITCOIN_OR_GOLD.test(c)) {
      if (!generic) {
        out.push('otras inversiones de tu cuenta');
        generic = true;
      }
      continue;
    }
    out.push(c);
  }
  return out;
}

/** What the payment-problem block says, or null when the plan is current. */
export function billingProblem(b: SmartAccountBilling, dexUi: boolean = DEX_TRADING_UI_ENABLED): { title: string; facts: { label: string; value: string }[]; sale: string } | null {
  if (b.status === 'current') {
    return null;
  }
  const facts = [{ label: 'Monto del plan', value: usd(b.feeUsd) }];
  if (b.shortfallUsd) {
    facts.push({ label: 'Te falta', value: usd(b.shortfallUsd) });
  }
  if (b.noticeStartedAt) {
    facts.push({ label: 'Avisos desde el', value: shortDate(b.noticeStartedAt) });
  }
  if (b.saleAllowedAt) {
    facts.push({ label: 'Venta posible desde el', value: shortDate(b.saleAllowedAt) });
  }
  const candidates = saleCandidateLabels(b.saleCandidates ?? [], dexUi);
  const sale = candidates.length === 0
    ? ''
    : `Si no agregas dólares, se vende lo necesario para un período, en este orden: ${candidates.join(', ')}. Lo que sobre se queda en tu cuenta.`;
  return {
    title: b.shortfallUsd ? `Faltan ${usd(b.shortfallUsd)} para tu plan` : 'Tu plan está por cobrarse',
    facts,
    sale,
  };
}

export function SmartAccountBillingScreen() {
  const navigation = useNavigation<any>();
  const account = useSmartRead(fetchSmartAccount);
  const offer = useSmartRead(fetchSmartAccountOffer);
  const charges = useSmartRead(() => fetchSmartAccountCharges(PREVIEW + 1));
  const flow = useSignFlow({ onExecuted: () => { void account.reload(); } });
  const [target, setTarget] = useState('');

  useEffect(() => {
    const unsubscribe = navigation.addListener?.('focus', () => { void account.reload(); });
    return typeof unsubscribe === 'function' ? unsubscribe : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigation]);

  const data = account.data ?? null;
  const billing = data?.billing ?? null;
  const problem = billing ? billingProblem(billing) : null;
  const otherPlan = billing
    ? (offer.data?.plans ?? []).find((p) => p.key !== billing.plan && p.key !== billing.nextPlan) ?? null
    : null;
  const items = charges.data?.items ?? [];
  const hasMore = items.length > PREVIEW || !!charges.data?.hasNextPage;

  return (
    <SmartScreen
      title="Tu plan"
      help={HELP_BILLING}
      onRefresh={() => { void account.reload(); void charges.reload(); }}
      refreshing={account.loading && !!data}
    >
      {account.loading && !data ? <ScreenSkeleton /> : account.failed && !data ? (
        <LoadError onRetry={account.reload} busy={account.loading} />
      ) : !billing ? (
        <Empty icon="credit-card" title="No hay un plan activo" actionLabel="Volver" onAction={() => navigation.goBack()} />
      ) : (
        <View style={kitStyles.pad}>
          {problem ? (
            <Card style={styles.problem}>
              <Notice tone="notice" icon="alert-circle" title={problem.title} body="Tus reglas están en pausa hasta que tu plan esté al día." testID="billing-problem" />
              {problem.facts.map((f, i) => <Fact key={f.label} label={f.label} value={f.value} divider={i > 0} />)}
              {problem.sale ? <Text style={styles.sale}>{problem.sale}</Text> : null}
              <ActionButton
                label="Agregar dólares"
                icon="arrow-down-left"
                onPress={() => navigation.navigate('SmartAccountMove', { direction: 'in' })}
                style={styles.problemButton}
                testID="billing-add"
              />
            </Card>
          ) : null}

          <SectionTitle>Plan</SectionTitle>
          <Card>
            <Row
              left={<IconDisc icon="credit-card" />}
              title={planLabel(billing.plan)}
              subtitle={billing.cancelRequested
                ? `Termina el ${shortDate(billing.returnsAt || billing.paidUntil)}`
                : billing.paidUntil ? `Se renueva el ${shortDate(billing.paidUntil)}` : undefined}
              value={usd(billing.feeUsd)}
              valueNote="próximo cobro"
              testID="billing-plan"
            />
            {billing.nextPlan && billing.nextPlan !== billing.plan ? (
              <Fact divider label="Desde la próxima renovación" value={planLabel(billing.nextPlan)} />
            ) : null}
          </Card>
          <Text style={[kitStyles.small, styles.under]}>
            Se cobra de los dólares de tu cuenta y se renueva al precio vigente ese día.
          </Text>
          {billing.nextPlan && billing.nextPlan !== billing.plan && !billing.cancelRequested ? (
            // Naming the plan in force withdraws the pending change
            // (ConfioSmartAccount.changePlan).
            <ActionButton
              label={`Mantener plan ${planName(billing.plan).toLowerCase()}`}
              variant="secondary"
              onPress={() => {
                setTarget(billing.plan);
                void flow.start({ prepare: () => prepareSmartAccountPlanChange(billing.plan) });
              }}
              accessibilityLabel={`Mantener plan ${planName(billing.plan).toLowerCase()} y no cambiar en la próxima renovación`}
              style={kitStyles.gap}
              testID="billing-keep"
            />
          ) : null}
          {otherPlan && !billing.cancelRequested ? (
            <ActionButton
              label={`Cambiar a plan ${planName(otherPlan.key).toLowerCase()}`}
              variant="secondary"
              onPress={() => {
                setTarget(otherPlan.key);
                void flow.start({ prepare: () => prepareSmartAccountPlanChange(otherPlan.key) });
              }}
              accessibilityLabel={`Cambiar a plan ${planName(otherPlan.key).toLowerCase()}, ${usd(otherPlan.priceUsd)} ${planPeriod(otherPlan.key)}`}
              style={kitStyles.gap}
              testID="billing-change"
            />
          ) : null}

          <SectionTitle action={hasMore ? { label: 'Ver todos', onPress: () => navigation.navigate('SmartAccountCharges'), accessibilityLabel: 'Ver todos los cobros' } : undefined}>
            Cobros
          </SectionTitle>
          <Card>
            {charges.loading && !charges.data ? <RowsSkeleton rows={2} /> : charges.failed && !charges.data ? (
              <LoadError onRetry={charges.reload} busy={charges.loading} message="No pudimos cargar tus cobros." />
            ) : items.length === 0 ? (
              <Text style={styles.none}>Todavía no hay cobros.</Text>
            ) : items.slice(0, PREVIEW).map((c, i) => (
              <Row key={c.id} divider={i > 0} title={chargeTitle(c)} subtitle={chargeSubtitle(c)} value={usd(c.feeUsd)} />
            ))}
          </Card>

          {!billing.cancelRequested ? (
            <ActionButton
              label="Cancelar suscripción"
              variant="quiet"
              onPress={() => navigation.navigate('SmartAccountCancel')}
              style={styles.cancel}
              testID="billing-cancel"
            />
          ) : (
            <ActionButton
              label="Ver la cancelación"
              variant="quiet"
              onPress={() => navigation.navigate('SmartAccountCancel')}
              style={styles.cancel}
            />
          )}
        </View>
      )}
      <SignFlowSheet
        flow={flow}
        copy={{
          confirmTitle: 'Cambiar de plan',
          confirmLabel: 'Firmar el cambio',
          confirmNote: 'El cambio aplica desde tu próxima renovación.',
          signingMessage: 'Guardando el cambio…',
          successTitle: target ? `Pasas a plan ${planName(target).toLowerCase()}` : 'Plan actualizado',
          successBody: 'Aplica desde tu próxima renovación.',
        }}
      />
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  problem: { paddingVertical: 16 },
  problemButton: { marginTop: 8 },
  sale: { fontSize: 14, lineHeight: 20, color: SA.muted, paddingVertical: 10 },
  under: { marginTop: 10, marginHorizontal: 4 },
  none: { fontSize: 15, color: SA.muted, paddingVertical: 18 },
  cancel: { marginTop: 24 },
});
