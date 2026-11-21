// "Hacerlo sin Confío": the beneficiary's direct on-chain path (spec 6.7).
//
// Layered: when Confío's server cannot be reached it is offered plainly; when
// it can, it sits behind a quiet "¿Confío no responde?" disclosure. The sheet
// reads the account from the chain itself, says what the next step is, checks
// the person has a little BNB to pay the network (and shows their own address
// to receive it when they do not), and signs on this phone. No amounts in
// token units: assets are named, the dollars are "Confío Dollar".
import React, { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, Platform, StyleSheet, View } from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { Text } from '../common/AppText';
import { ActionButton, Card, Fact, Notice, Sheet, kitStyles } from './kit';
import { SA } from './tokens';
import { shortAddress, shortDate } from './format';
import {
  loadDirectEntry, loadInheritedDirectEntry, ownWalletAddress, readDirectSituation, runDirectStep,
  type DirectRevertName, type DirectSituation,
} from '../../services/smartAccountDirect';

type Phase =
  | { kind: 'closed' }
  | { kind: 'loading' }
  | { kind: 'no_account' }
  | { kind: 'no_wallet' }
  | { kind: 'error' }
  | { kind: 'ready'; s: DirectSituation }
  | { kind: 'sending'; s: DirectSituation }
  | { kind: 'done'; s: DirectSituation }
  | { kind: 'unknown'; done: number; total: number }
  | { kind: 'failed'; s: DirectSituation; message: string };

const REVERT_COPY: Record<DirectRevertName, string> = {
  NotBeneficiary: 'Tu billetera no es la beneficiaria de esta cuenta.',
  BadState: 'La cuenta no está activa, así que ahora no se puede pedir ni recibir.',
  ClaimAlreadyPending: 'Ya hay un pedido en curso.',
  Cooldown: 'Un pedido anterior se canceló hace poco. Todavía no puedes pedirla de nuevo.',
  TooEarly: 'Todavía no termina el plazo.',
  NotOwner: 'Esta cuenta no está a tu nombre.',
  NotInherited: 'Esta cuenta todavía no está a tu nombre.',
  BadDestination: 'Solo puedes mover lo que tiene a tu propia billetera.',
  IsInherited: 'Esta cuenta ya pasó a otra persona.',
  BadToken: 'Uno de los activos no se puede mover.',
  BadAmount: 'Uno de los activos no se puede mover.',
};

export const directRevertMessage = (e: DirectRevertName | null): string =>
  (e && REVERT_COPY[e]) || 'La red no aceptó la operación. No se movió nada.';

const DATE = (sec: number) => shortDate(new Date(sec * 1000).toISOString());

export function DirectClaimPanel({ designationId, account, inheritedAccountId, serverDown, ownerName, onDone }: {
  designationId?: string;
  /** The device-stored account address, when known (opened without the server). */
  account?: string;
  /** An inherited account (withdraw to the own wallet): its device record. */
  inheritedAccountId?: string;
  /** The server could not be reached: offer the path plainly, not behind help. */
  serverDown: boolean;
  ownerName?: string;
  onDone?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: 'closed' });
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setPhase({ kind: 'loading' });
    setCopied(false);
    try {
      const entry = inheritedAccountId !== undefined
        ? await loadInheritedDirectEntry(inheritedAccountId || null)
        : await loadDirectEntry(account ? { designationId, account } : { designationId });
      if (!entry) {
        setPhase({ kind: 'no_account' });
        return;
      }
      const me = await ownWalletAddress();
      if (!me) {
        setPhase({ kind: 'no_wallet' });
        return;
      }
      setPhase({ kind: 'ready', s: await readDirectSituation(entry, me) });
    } catch {
      setPhase({ kind: 'error' });
    }
  }, [designationId, account, inheritedAccountId]);

  // Synchronous guard: two taps in the same frame both run before the
  // 'sending' phase re-renders the button away, and each would sign.
  const busyRef = useRef(false);
  const send = async (s: DirectSituation) => {
    if (busyRef.current) {
      return;
    }
    busyRef.current = true;
    setPhase({ kind: 'sending', s });
    let out;
    try {
      out = await runDirectStep(s);
    } catch {
      setPhase({ kind: 'failed', s, message: 'No pudimos enviar la operación. No se movió nada.' });
      return;
    } finally {
      busyRef.current = false;
    }
    if (out.status === 'cancelled') {
      setPhase({ kind: 'ready', s });
    } else if (out.status === 'executed') {
      setPhase({ kind: 'done', s });
    } else if (out.status === 'unknown') {
      setPhase({ kind: 'unknown', done: out.done, total: out.total });
    } else {
      const earlier = out.done > 0 ? ` Ya se movieron ${out.done} de ${out.total}.` : ' No se movió nada.';
      const base = out.needBnb
        ? `Te falta BNB para pagar la red: envía al menos ${out.needBnb} BNB a tu billetera.`
        : directRevertMessage(out.error).replace(/ No se movió nada\.$/, '');
      setPhase({ kind: 'failed', s, message: `${base}${earlier}` });
    }
  };

  const close = () => {
    const wasDone = phase.kind === 'done';
    setPhase({ kind: 'closed' });
    if (wasDone) {
      onDone?.();
    }
  };

  const open = () => { void load(); };

  return (
    <View style={kitStyles.gap}>
      {serverDown ? (
        <Notice
          tone="notice"
          icon="wifi-off"
          title="No pudimos conectar con Confío"
          body="Puedes hacerlo directamente en la red, desde tu billetera. Pagas tú la comisión de la red, en BNB."
          onPress={open}
          actionLabel="Hacerlo sin Confío"
          testID="direct-offer"
        />
      ) : (
        <>
          <ActionButton
            label="¿Confío no responde?"
            variant="quiet"
            icon={expanded ? 'chevron-up' : 'chevron-down'}
            onPress={() => setExpanded((v) => !v)}
            testID="direct-help"
          />
          {expanded ? (
            <Card style={styles.help}>
              <Text style={kitStyles.body}>
                Si algún día no puedes usar Confío, puedes hacer este paso directamente en la red, desde tu propia billetera. Necesitas un poco de BNB en tu billetera para pagar la red.
              </Text>
              <ActionButton label="Hacerlo sin Confío" variant="secondary" onPress={open} style={kitStyles.gap} testID="direct-open" />
            </Card>
          ) : null}
        </>
      )}

      <Sheet
        visible={phase.kind !== 'closed'}
        onClose={close}
        dismissable={phase.kind !== 'sending'}
        title="Sin Confío"
        testID="direct-sheet"
      >
        {phase.kind === 'loading' || phase.kind === 'sending' ? (
          <View style={styles.center} accessibilityLiveRegion="polite">
            <ActivityIndicator size="large" color={SA.deep} />
            <Text style={styles.centerText}>{phase.kind === 'loading' ? 'Revisando la cuenta en la red…' : 'Enviando a la red…'}</Text>
          </View>
        ) : null}

        {phase.kind === 'no_account' ? (
          <Notice
            tone="neutral"
            body="Este teléfono no tiene guardada la dirección de la cuenta. Se guarda cuando abres esta pantalla con conexión a Confío."
            testID="direct-no-account"
          />
        ) : null}
        {phase.kind === 'no_wallet' ? (
          <Notice tone="neutral" body="No encontramos tu billetera en este teléfono." testID="direct-no-wallet" />
        ) : null}
        {phase.kind === 'error' ? (
          <>
            <Notice tone="neutral" icon="wifi-off" body="No pudimos leer la red. Revisa tu conexión e inténtalo de nuevo." testID="direct-error" />
            <ActionButton label="Reintentar" variant="secondary" onPress={open} style={kitStyles.gap} />
          </>
        ) : null}

        {phase.kind === 'ready' ? (
          <ReadyBody
            s={phase.s}
            ownerName={ownerName}
            copied={copied}
            onCopy={() => { Clipboard.setString(phase.s.me); setCopied(true); }}
            onRecheck={open}
            onSend={() => { void send(phase.s); }}
          />
        ) : null}

        {phase.kind === 'done' ? (
          <View style={styles.center} accessibilityLiveRegion="polite">
            <Text style={styles.title}>Listo</Text>
            <Text style={styles.centerText}>{doneCopy(phase.s)}</Text>
            <ActionButton label="Continuar" onPress={close} style={styles.wide} testID="direct-done" />
          </View>
        ) : null}
        {phase.kind === 'unknown' ? (
          <View style={styles.center} accessibilityLiveRegion="polite">
            <Text style={styles.title}>Estamos confirmando</Text>
            <Text style={styles.centerText} testID="direct-unknown-body">{unknownCopy(phase.done, phase.total)}</Text>
            <ActionButton label="Revisar de nuevo" variant="secondary" onPress={open} style={styles.wide} testID="direct-unknown-recheck" />
            <ActionButton label="Entendido" variant="quiet" onPress={close} style={styles.wide} testID="direct-unknown" />
          </View>
        ) : null}
        {phase.kind === 'failed' ? (
          <View style={styles.center} accessibilityLiveRegion="polite">
            <Text style={styles.title}>No se realizó</Text>
            <Text style={styles.centerText} testID="direct-failed">{phase.message}</Text>
            <ActionButton label="Revisar de nuevo" variant="secondary" onPress={open} style={styles.wide} />
          </View>
        ) : null}
      </Sheet>
    </View>
  );
}

/** Sent, verdict not seen: never invite a blind repeat. */
export function unknownCopy(done: number, total: number): string {
  const earlier = total > 1 && done > 0 ? `Ya se movieron ${done} de ${total}. ` : '';
  const rest = total > done + 1 ? ' No firmamos los que siguen.' : '';
  return `${earlier}La última operación se envió y todavía no vemos el resultado.${rest} Espera unos minutos y revisa de nuevo antes de repetirla.`;
}

function doneCopy(s: DirectSituation): string {
  switch (s.step.kind) {
    case 'initiate': return 'Tu pedido quedó en la red. El plazo empezó y su fecha final ya no cambia.';
    case 'execute': return 'La cuenta ya está a tu nombre.';
    case 'withdraw': return 'Lo que tenía la cuenta ya está en tu billetera.';
    default: return '';
  }
}

function ReadyBody({ s, ownerName, copied, onCopy, onRecheck, onSend }: {
  s: DirectSituation; ownerName?: string; copied: boolean;
  onCopy: () => void; onRecheck: () => void; onSend: () => void;
}) {
  const step = s.step;
  let title = '';
  let body = '';
  let action = '';
  if (step.kind === 'initiate') {
    title = 'Pedir la cuenta';
    body = `${ownerName ? `Le avisaremos a ${ownerName} cuando Confío vuelva. ` : ''}Si su dueño firma una acción en su Cuenta inteligente o una operación desde su cuenta personal durante el plazo, el pedido se cancela.`;
    action = 'Firmar y pedir la cuenta';
  } else if (step.kind === 'execute') {
    title = 'Recibir la cuenta';
    body = 'El plazo terminó. Al firmar, la cuenta pasa a tu nombre.';
    action = 'Firmar y recibir la cuenta';
  } else if (step.kind === 'withdraw') {
    title = 'Mover a tu billetera';
    body = s.holdings.length === 0
      ? 'La cuenta no tiene nada que mover.'
      : `Se mueve todo a tu billetera: ${s.holdings.map((h) => h.label).join(', ')}.${s.holdings.length > 1 ? ` Son ${s.holdings.length} firmas, una por activo.` : ''}`;
    action = s.holdings.length > 0 ? 'Firmar y mover a mi billetera' : '';
  } else if (step.kind === 'wait') {
    title = 'Tu pedido está en curso';
    body = `Podrás recibir la cuenta el ${DATE(step.executableAt)}.`;
  } else if (step.kind === 'cooldown') {
    title = 'Todavía no puedes pedirla';
    body = `Un pedido anterior se canceló. Podrás pedirla de nuevo desde el ${DATE(step.until)}.`;
  } else if (step.kind === 'not_beneficiary') {
    title = 'No eres el beneficiario';
    body = 'Según la red, tu billetera no es la beneficiaria de esta cuenta.';
  } else {
    title = 'La cuenta no está activa';
    body = 'Según la red, esta cuenta no está activa, así que no se puede pedir.';
  }
  const short = s.gas.kind === 'short';
  return (
    <View>
      <Text style={styles.stepTitle} accessibilityRole="header">{title}</Text>
      <Text style={kitStyles.body}>{body}</Text>
      <Card style={kitStyles.gap}>
        <Fact label="Cuenta" value={shortAddress(s.account)} />
        <Fact divider label="Red" value="BNB Smart Chain" />
      </Card>
      {s.gas.kind === 'refused' ? (
        <Notice tone="neutral" body={directRevertMessage(s.gas.error)} style={kitStyles.gap} testID="direct-refused" />
      ) : null}
      {short ? (
        <View style={kitStyles.gap} testID="direct-needs-bnb">
          <Notice
            tone="notice"
            icon="alert-circle"
            title="Necesitas un poco de BNB"
            body={`Sin Confío, la comisión de la red la pagas tú, en BNB. Envía al menos ${s.gas.kind === 'short' ? s.gas.needBnb : ''} BNB por la red BNB Smart Chain a tu billetera:`}
          />
          <View style={styles.address} accessible accessibilityLabel={`Tu billetera: ${s.me}`}>
            <Text style={styles.addressValue} selectable testID="direct-own-address">{s.me}</Text>
          </View>
          <ActionButton
            label={copied ? 'Dirección copiada' : 'Copiar mi dirección'}
            icon={copied ? 'check' : 'copy'}
            variant="secondary"
            onPress={onCopy}
            testID="direct-copy"
          />
          <ActionButton label="Ya envié BNB: revisar" variant="quiet" onPress={onRecheck} testID="direct-recheck" />
        </View>
      ) : null}
      {action && s.gas.kind === 'enough' ? (
        <>
          <Text style={[kitStyles.small, kitStyles.gap]}>Lo firmas en este teléfono y pagas una pequeña comisión de la red en BNB.</Text>
          <ActionButton label={action} onPress={onSend} style={kitStyles.gap} testID="direct-send" />
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  help: { paddingVertical: 14 },
  center: { alignItems: 'center', paddingVertical: 16 },
  centerText: { fontSize: 15, lineHeight: 22, color: SA.muted, marginTop: 8, textAlign: 'center' },
  title: { fontSize: 20, fontWeight: '700', color: SA.text, textAlign: 'center' },
  stepTitle: { fontSize: 20, fontWeight: '700', color: SA.text, marginBottom: 6 },
  wide: { marginTop: 20, alignSelf: 'stretch' },
  address: { paddingVertical: 12 },
  addressValue: {
    fontSize: 15, lineHeight: 22, fontWeight: '600', color: SA.text,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
});
