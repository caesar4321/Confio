// Edit, then a separate confirmation of exactly what will be sent.
import React, { useState } from 'react';
import { Linking, View } from 'react-native';
import { useMutation } from '@apollo/client';

import { Text, TextInput } from '../../components/common/AppText';
import { SEND_DRAFT, UPDATE_DRAFT, type MailDraft } from './api';
import { Action, Link, styles } from './ui';

type Props = {
  initial: MailDraft;
  onBack: () => void;
  onSent: () => void;
  /** Before the request leaves: a remount must not offer this mail again. */
  onSending?: () => void;
  onNotSent?: () => void;
  onEdit?: (edit: Partial<MailDraft>) => void;
  onUnknown?: (notice: string) => void;
};

const UNKNOWN = 'No sé si el correo salió. Revisa tu carpeta Enviados antes de repetirlo.';

export default function MailDraftView({ initial, onBack, onSent, onSending, onNotSent, onEdit, onUnknown }: Props) {
  const [to, setTo] = useState(initial.to);
  const [subject, setSubject] = useState(initial.subject);
  const [body, setBody] = useState(initial.body);
  // What the server stored, with its hash: only this is shown and sent on the confirmation.
  const [confirmed, setConfirmed] = useState<MailDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [closed, setClosed] = useState(false);
  const [update] = useMutation(UPDATE_DRAFT, { fetchPolicy: 'no-cache' });
  const [send] = useMutation(SEND_DRAFT, { fetchPolicy: 'no-cache' });

  const attempt = async (task: () => Promise<void>, failure: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await task();
    } catch {
      setMessage(failure);
    } finally {
      setBusy(false);
    }
  };

  const review = () => attempt(async () => {
    const { data } = await update({ variables: { id: initial.id, to, subject, body } });
    const result = data?.updateAssistantMailDraft;
    if (result?.success && result.draft) {
      setConfirmed(result.draft);
    } else {
      setMessage(result?.error || 'No pude guardar el borrador.');
    }
  }, 'No pude guardar el borrador.');

  const sendNow = () => attempt(async () => {
    if (!confirmed) {
      return;
    }
    let result;
    onSending?.();
    try {
      const { data } = await send({ variables: { id: confirmed.id, displayHash: confirmed.displayHash } });
      result = data?.sendAssistantMailDraft;
    } catch {
      // The request may have arrived: never offer a second send.
      setClosed(true);
      setMessage(UNKNOWN);
      onUnknown?.(UNKNOWN);
      return;
    }
    if (result?.success) {
      onSent();
      return;
    }
    if (result?.errorCode === 'sent_unknown' || result?.errorCode === 'not_found') {
      setClosed(true);
      onUnknown?.(result?.error || UNKNOWN);
    } else {
      onNotSent?.();
    }
    setMessage(result?.error || 'No pude enviar el correo.');
  }, 'No pude enviar el correo.');

  const openComposer = () => attempt(async () => {
    const query = `subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    await Linking.openURL(`mailto:${encodeURIComponent(to.trim())}?${query}`);
  }, 'No encontré una app de correo en este teléfono.');

  // Shown on both steps: without send permission the confirmation never appears.
  const warning = (confirmed ?? initial).replyToDiffers ? (
    <Text style={styles.warning}>
      Ojo: la respuesta no va a la dirección que te escribió. El correo pidió que respondas a esta otra.
    </Text>
  ) : null;
  const notice = message ? <Text style={styles.message} accessibilityLiveRegion="polite">{message}</Text> : null;

  if (confirmed) {
    return (
      <View>
        <Text style={styles.heading}>Confirma el envío</Text>
        <Text style={styles.label}>De</Text>
        <Text style={styles.value} selectable>{confirmed.sender}</Text>
        <Text style={styles.label}>Para</Text>
        <Text style={styles.recipient} selectable>{confirmed.to}</Text>
        {warning}
        <Text style={styles.label}>Asunto</Text>
        <Text style={styles.value}>{confirmed.subject}</Text>
        <Text style={styles.label}>Mensaje</Text>
        <Text style={styles.value}>{confirmed.body}</Text>
        {notice}
        {closed ? null : <Action label="Enviar este correo" onPress={sendNow} disabled={busy} />}
        <Link
          label={closed ? 'Volver' : 'Seguir editando'}
          onPress={closed ? onBack : () => setConfirmed(null)}
          disabled={busy}
        />
      </View>
    );
  }

  const canSend = !!initial.id && initial.canSend;
  return (
    <View>
      <Text style={styles.heading}>Borrador</Text>
      <Text style={styles.label}>Para</Text>
      {initial.isReply ? (
        <>
          <Text style={styles.recipient} selectable>{initial.to}</Text>
          {warning}
        </>
      ) : (
        <TextInput
          style={styles.input}
          value={to}
          onChangeText={(value: string) => { setTo(value); onEdit?.({ to: value }); }}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          accessibilityLabel="Para"
        />
      )}
      <Text style={styles.label}>Asunto</Text>
      {initial.isReply ? (
        <Text style={styles.value}>{initial.subject}</Text>
      ) : (
        <TextInput style={styles.input} value={subject} onChangeText={(value: string) => { setSubject(value); onEdit?.({ subject: value }); }} maxLength={200} accessibilityLabel="Asunto" />
      )}
      <Text style={styles.label}>Mensaje</Text>
      <TextInput
        style={[styles.input, styles.multiline]}
        value={body}
        onChangeText={(value: string) => { setBody(value); onEdit?.({ body: value }); }}
        multiline
        maxLength={8000}
        accessibilityLabel="Mensaje"
      />
      {notice}
      {canSend ? (
        <Action label="Revisar y enviar" onPress={review} disabled={busy || !body.trim()} />
      ) : (
        <Action label="Abrir en mi app de correo" onPress={openComposer} disabled={busy || !body.trim()} />
      )}
      <Link label="Volver" onPress={onBack} disabled={busy} />
    </View>
  );
}
