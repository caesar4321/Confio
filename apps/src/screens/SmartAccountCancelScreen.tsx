// Cuenta inteligente: cancel the subscription, or undo it (spec 8.2 "Cancel").
//
// Cancelling is stated as four consequences with their date, not as a
// warning: when the account closes, that everything in it returns to the
// personal wallet that day, that the rules stop, and that the beneficiary no
// longer applies. While the cancellation is pending the same screen shows the
// return date and one action: undo.
import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import {
  ActionButton, Card, Empty, Fact, IconDisc, LoadError, Row, ScreenSkeleton, SmartScreen, kitStyles,
} from '../components/smartAccount/kit';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_BILLING } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { planLabel, shortDate } from '../components/smartAccount/format';
import {
  fetchSmartAccount, isSmartAccountOpen, prepareSmartAccountCancel, prepareSmartAccountUndoCancel,
  type SmartAccount,
} from '../services/smartAccount';

const isFuture = (iso: string | null | undefined, now: number): boolean => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) && t > now;
};

/**
 * Whether cancelling (or a scheduled cancellation) closes the account now:
 * no paid period ahead (billing not current, or paid until a past date), and
 * no future return date already scheduled. Then there is no date to give.
 */
export function cancelClosesNow(account: Pick<SmartAccount, 'status' | 'billing'>, now: number = Date.now()): boolean {
  const b = account.billing;
  const pending = !!b?.cancelRequested || account.status === 'cancel_pending';
  if (pending && isFuture(b?.returnsAt, now)) {
    return false;
  }
  return !b || b.status !== 'current' || !isFuture(b.paidUntil, now);
}

export function SmartAccountCancelScreen() {
  const navigation = useNavigation<any>();
  const account = useSmartRead(fetchSmartAccount);
  const flow = useSignFlow({ onExecuted: () => { void account.reload(); } });
  // Which action the sheet is for: fixed when it starts, so the wording does
  // not flip when the account reloads under an open sheet.
  const [undoing, setUndoing] = useState(false);
  const data = account.data ?? null;
  const billing = data?.billing ?? null;
  const pending = !!billing?.cancelRequested || data?.status === 'cancel_pending';
  const endDate = shortDate(billing?.returnsAt || billing?.paidUntil);
  const hasBeneficiary = !!data?.beneficiary || !!data?.pendingBeneficiary;
  const hasRules = (data?.rules ?? []).some((r) => r.active);
  const ready = !!data && isSmartAccountOpen(data.status);
  const now = !!data && cancelClosesNow(data);

  return (
    <SmartScreen
      title={pending ? 'Cancelación programada' : 'Cancelar suscripción'}
      help={HELP_BILLING}
      footer={!ready ? undefined : pending ? (
        <ActionButton
          label="Deshacer la cancelación"
          onPress={() => { setUndoing(true); void flow.start({ prepare: () => prepareSmartAccountUndoCancel() }); }}
          testID="cancel-undo"
        />
      ) : (
        <>
          <ActionButton
            label="Cancelar suscripción"
            variant="danger"
            onPress={() => { setUndoing(false); void flow.start({ prepare: () => prepareSmartAccountCancel() }); }}
            testID="cancel-confirm"
          />
          <ActionButton label="Seguir con mi cuenta" variant="quiet" onPress={() => navigation.goBack()} />
        </>
      )}
    >
      {account.loading && !data ? <ScreenSkeleton /> : account.failed && !data ? (
        <LoadError onRetry={account.reload} busy={account.loading} />
      ) : !ready ? (
        <Empty icon="corner-up-left" title="No hay una suscripción activa" actionLabel="Volver" onAction={() => navigation.goBack()} />
      ) : (
        <View style={kitStyles.pad}>
          <Text style={styles.title} accessibilityRole="header">
            {now
              ? (pending ? 'Tu cuenta se está cerrando' : 'Si cancelas, tu cuenta se cierra ahora')
              : pending
                ? `Tu cuenta se cierra el ${endDate}`
                : `Si cancelas, tu cuenta sigue activa hasta el ${endDate}`}
          </Text>
          <Card style={kitStyles.gap}>
            <Row
              left={<IconDisc icon="corner-up-left" />}
              title="Todo vuelve a tu billetera"
              subtitle={now
                ? 'Cada cosa que tenga la cuenta regresa ahora a tu billetera personal.'
                : `El ${endDate}, cada cosa que tenga la cuenta regresa a tu billetera personal.`}
            />
            <Row
              divider
              left={<IconDisc icon="repeat" tone="neutral" />}
              title="La automatización se detiene"
              subtitle={hasRules
                ? (now ? 'Tus reglas dejan de ejecutarse.' : 'Tus reglas dejan de ejecutarse ese día.')
                : 'Ya no se podrán crear reglas.'}
            />
            <Row
              divider
              left={<IconDisc icon="users" tone="neutral" />}
              title="Tu beneficiario deja de aplicar"
              subtitle={hasBeneficiary
                ? 'Lo que vuelve a tu billetera ya no está cubierto por tu beneficiario.'
                : 'La cuenta ya no tendrá beneficiario.'}
            />
          </Card>
          <Card style={kitStyles.gap}>
            <Fact label="Plan" value={billing ? planLabel(billing.plan) : '—'} />
            {now ? null : <Fact divider label="Pagado hasta el" value={shortDate(billing?.paidUntil) || '—'} />}
          </Card>
          <Text style={[kitStyles.small, styles.under]}>
            {now
              ? 'No queda un período pagado: la cuenta se cierra y todo vuelve a tu billetera personal.'
              : pending
                ? 'Puedes deshacerla hasta ese día y tu cuenta sigue como estaba.'
                : 'El período ya pagado no se reembolsa. Puedes deshacer la cancelación hasta ese día.'}
          </Text>
        </View>
      )}
      <SignFlowSheet
        flow={flow}
        copy={undoing ? {
          confirmLabel: 'Firmar y seguir con mi cuenta',
          signingMessage: 'Deshaciendo la cancelación…',
          successTitle: 'Tu cuenta sigue activa',
        } : {
          confirmTitle: 'Cancelar suscripción',
          confirmLabel: 'Firmar y cancelar',
          signingMessage: 'Programando la cancelación…',
          successTitle: now ? 'Tu cuenta se está cerrando' : 'Cancelación programada',
          successBody: now
            ? 'Todo vuelve a tu billetera personal.'
            : `Tu cuenta sigue activa hasta el ${endDate}.`,
        }}
      />
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 22, lineHeight: 29, fontWeight: '700', color: SA.text },
  under: { marginTop: 12, marginHorizontal: 4 },
});
