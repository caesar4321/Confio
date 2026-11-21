// Cuenta inteligente: name the beneficiary (spec 6.1, 8.2, 8.3 disclosure 7).
//
// Three decisions on one screen, in the order they are made: who, how long
// the owner has to cancel a claim, and the one thing that can go wrong. The
// residual risk is not fine print: it is three plain sentences in their own
// card, written with the chosen name and the chosen number of days, and it
// must be accepted before anything is signed. The person named is told and
// must accept; the server checks that they can be a beneficiary and says so
// plainly when they cannot.
import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import { ConfioContactPicker, type PickedPerson } from '../components/smartAccount/ConfioContactPicker';
import {
  AcceptRow, ActionButton, Card, Chip, Empty, IconDisc, LoadError, Notice, NumberedList, Row, ScreenSkeleton,
  SectionTitle, SmartScreen, kitStyles,
} from '../components/smartAccount/kit';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_BENEFICIARY } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { daysLabel } from '../components/smartAccount/format';
import {
  fetchBeneficiaryRiskDisclosure, fetchSmartAccount, fetchSmartAccountOffer, prepareBeneficiaryDesignation,
} from '../services/smartAccount';
import type { MainStackParamList } from '../types/navigation';

/** Disclosure 7 of spec 8.3, with the owner's own choices written in. */
export function residualRiskLines(name: string, days: number): string[] {
  const who = name || 'tu beneficiario';
  return [
    `Si ${who} pide tu cuenta, tienes ${daysLabel(days)} para cancelarlo.`,
    'Cualquier acción que firmes en tu Cuenta inteligente lo cancela. Confío agrega una automáticamente a cada operación que firmas desde tu cuenta personal. Las operaciones de una cuenta de negocio no lo cancelan.',
    `Si no firmas nada de eso durante ${daysLabel(days)}, ${who} pasa a ser dueño de la cuenta y de todo lo que tenga. Te avisamos durante todo ese plazo.`,
    'Si en todo ese plazo no firmas nada ni ves ningún aviso, pierdes la cuenta aunque sigas con vida.',
  ];
}

/**
 * The server's wording of disclosure 7 (`beneficiaryRiskDisclosure`), with
 * {name} and {days} filled in; the app's own lines when the server sends
 * none (an older server, or a failed read). {days} is the bare number: the
 * server's sentences already say "días".
 */
export function riskDisclosureLines(serverLines: string[] | null | undefined, name: string, days: number): string[] {
  const usable = (serverLines ?? []).filter((l) => typeof l === 'string' && l.trim().length > 0);
  if (usable.length === 0) {
    return residualRiskLines(name, days);
  }
  const who = name || 'tu beneficiario';
  return usable.map((l) => l.split('{name}').join(who).split('{days}').join(String(days)));
}

export function BeneficiarySetupScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'BeneficiarySetup'>>();
  const account = useSmartRead(fetchSmartAccount);
  const offer = useSmartRead(fetchSmartAccountOffer);
  // Isolated: an older server without the field fails only this read.
  const disclosure = useSmartRead(fetchBeneficiaryRiskDisclosure);
  const flow = useSignFlow();

  const preset = route.params?.handle ? { handle: route.params.handle, name: route.params.name || route.params.handle } : null;
  const [person, setPerson] = useState<PickedPerson | null>(preset);
  const [picker, setPicker] = useState(false);
  const [windowDays, setWindowDays] = useState<number | null>(route.params?.windowDays ?? null);
  const [accepted, setAccepted] = useState(false);
  const [touched, setTouched] = useState(false);

  const data = account.data ?? null;
  const options = data?.windowOptionsDays ?? [];
  const days = windowDays ?? data?.defaultWindowDays ?? options[0] ?? 0;
  const current = data?.beneficiary ?? null;
  // Waits for the disclosure read too, so the sentences never swap under the reader.
  const loading = (account.loading && !data) || (offer.loading && !offer.data)
    || (disclosure.loading && disclosure.data === undefined);
  const failed = (account.failed && !data) || (offer.failed && !offer.data);
  const enabled = !!offer.data?.beneficiaryEnabled;

  // The acceptance covers the sentences shown for THIS person and THIS
  // window: a change to either asks for it again.
  const acceptedFor = useRef(`${person?.handle ?? ''}|${days}`);
  useEffect(() => {
    const key = `${person?.handle ?? ''}|${days}`;
    if (acceptedFor.current !== key) {
      acceptedFor.current = key;
      setAccepted(false);
    }
  }, [person?.handle, days]);

  const onReview = () => {
    setTouched(true);
    if (!person || !accepted || !days) {
      return;
    }
    void flow.start({ faceStepUp: true, prepare: () => prepareBeneficiaryDesignation(person.handle, days, true) });
  };

  return (
    <SmartScreen
      title="Tu beneficiario"
      help={HELP_BENEFICIARY}
      footer={!loading && !failed && enabled ? (
        <ActionButton label="Revisar" onPress={onReview} testID="beneficiary-review" />
      ) : undefined}
    >
      {loading ? <ScreenSkeleton /> : failed ? (
        <LoadError onRetry={() => { void account.reload(); void offer.reload(); }} />
      ) : !enabled ? (
        <Empty icon="users" title="Todavía no está disponible" body="Te avisamos cuando puedas elegir a tu beneficiario." />
      ) : (
        <View style={kitStyles.pad}>
          <Text style={kitStyles.lead}>
            Elige a la persona que recibe esta cuenta si dejas de usarla. Solo cubre lo que está dentro de tu Cuenta inteligente.
          </Text>

          {current ? (
            <Notice
              tone="neutral"
              icon="user-check"
              body={`Hoy tu beneficiario es ${current.name}. Lo sigue siendo hasta que la nueva persona acepte.`}
              style={kitStyles.gap}
            />
          ) : null}

          <SectionTitle>¿Quién?</SectionTitle>
          <Card>
            <Row
              left={<IconDisc icon="user" tone={person ? 'mint' : 'neutral'} />}
              title={person?.name || 'Elegir persona'}
              subtitle={person ? 'Debe aceptar para ser tu beneficiario' : 'Una persona verificada en Confío'}
              onPress={() => setPicker(true)}
              chevron
              accessibilityLabel={person ? `Beneficiario: ${person.name}. Cambiar` : 'Elegir persona'}
              testID="beneficiary-person"
            />
          </Card>
          {touched && !person ? <Text style={styles.fieldError}>Elige a una persona.</Text> : null}

          <SectionTitle>¿Cuánto plazo tienes para cancelar?</SectionTitle>
          <View style={styles.chips} accessibilityRole="radiogroup">
            {options.map((d) => (
              <Chip key={d} label={daysLabel(d)} selected={d === days} onPress={() => setWindowDays(d)} />
            ))}
          </View>
          <Text style={kitStyles.small}>
            Es el tiempo que pasa desde que esa persona pide la cuenta hasta que la recibe.
          </Text>

          <SectionTitle>Léelo con calma</SectionTitle>
          <Card style={styles.risk}>
            <NumberedList items={riskDisclosureLines(disclosure.data, person?.name || '', days)} />
          </Card>
          <View style={kitStyles.gap}>
            <AcceptRow
              checked={accepted}
              onToggle={() => setAccepted((v) => !v)}
              label="Lo entiendo y lo acepto"
              highlight={touched}
              testID="beneficiary-accept"
            />
            {touched && !accepted ? (
              <Text style={styles.fieldError} accessibilityLiveRegion="polite">Marca la casilla para continuar.</Text>
            ) : null}
          </View>
        </View>
      )}

      <ConfioContactPicker
        visible={picker}
        title="¿Quién es tu beneficiario?"
        onClose={() => setPicker(false)}
        onPick={(p) => { setPerson(p); setPicker(false); }}
      />
      <SignFlowSheet
        flow={flow}
        copy={{
          confirmLabel: 'Firmar',
          confirmNote: 'Le avisamos a esa persona. Será tu beneficiario cuando acepte.',
          signingMessage: 'Guardando tu beneficiario…',
          successTitle: 'Invitación enviada',
          successBody: 'Te avisamos cuando acepte.',
        }}
        onDone={() => navigation.replace('BeneficiaryStatus')}
      />
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap' },
  risk: { paddingVertical: 8 },
  fieldError: { fontSize: 13, color: SA.noticeText, marginTop: 8, marginLeft: 4 },
});
