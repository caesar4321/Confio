// The pitch behind the paid-offer probes (Confío IA+, Cuenta inteligente).
// A waitlist only: nothing is sold, charged or unlocked here. "¡Anotado!"
// appears only after the server confirms the join (never optimistically), and
// the price is the server's value. Design: docs/designs/cuenta-inteligente-fake-door.md.
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useMutation } from '@apollo/client';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { Header } from '../navigation/Header';
import { Text } from '../components/common/AppText';
import type { MainStackParamList } from '../types/navigation';
import {
  ANSWER_PAID_OFFER,
  GET_PAID_OFFERS,
  JOIN_PAID_OFFER_WAITLIST,
  logOfferStep,
  priceLabel,
  usePaidOffers,
  type PaidOfferKey,
} from '../services/paidOffers';

const EMERALD = '#10B981';
const TEXT = '#1F2937';
const MUTED = '#6B7280';

type Benefit = { name: string; line: string };

// Matched copy: five benefits each, same price (design review + eng review D7).
const OFFERS: Record<PaidOfferKey, { title: string; headline: string; benefits: Benefit[] }> = {
  ia_plus: {
    title: 'Confío IA+',
    headline: 'Tu asistente financiero personal.',
    benefits: [
      { name: 'Respuestas más avanzadas', line: 'Modelos de IA más capaces para tus preguntas de dinero.' },
      { name: 'Conversación por voz', line: 'Habla con Confío IA en lugar de escribir.' },
      { name: 'Más uso de Confío IA', line: 'Más preguntas y análisis cada día.' },
      { name: 'Análisis de tus gastos, ahorros e inversiones', line: 'Con tus números reales.' },
      { name: 'Seguimiento personalizado', line: 'De tus metas y de cómo se mueve tu dinero.' },
    ],
  },
  smart_account: {
    title: 'Cuenta inteligente',
    headline: 'Tu dinero se mueve según tus reglas.',
    benefits: [
      { name: 'Pagos automáticos', line: 'A Pix, Bre-B, CLABE y Alias, que tú autorizas y cancelas cuando quieras.' },
      { name: 'Suscripciones con comercios', line: 'Con el monto y la frecuencia que tú apruebas.' },
      { name: 'Transferencias programadas', line: 'A tu familia y a tus propias cuentas.' },
      { name: 'Control de débitos', line: 'Tú apruebas cada permiso y lo puedes quitar.' },
      { name: 'Aviso antes de cada cobro', line: 'Y si un cobro viene más alto de lo normal.' },
    ],
  },
};

const VOLUMES: { key: string; label: string }[] = [
  { key: 'lt_100', label: 'Menos de US$100' },
  { key: '100_500', label: 'US$100 a 500' },
  { key: '500_2000', label: 'US$500 a 2.000' },
  { key: 'gt_2000', label: 'Más de US$2.000' },
];

function shortDate(iso: string | null | undefined) {
  if (!iso) {
    return '';
  }
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('es', { day: 'numeric', month: 'short' });
}

export function PaidOfferScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'PaidOffer'>>();
  const offer: PaidOfferKey = route.params?.offer === 'smart_account' ? 'smart_account' : 'ia_plus';
  const door = route.params?.door ?? 'chip';
  const trigger = route.params?.trigger ?? '';
  const copy = OFFERS[offer];
  const state = usePaidOffers()[offer];
  const price = priceLabel(state?.monthlyPriceUsd);

  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState('');
  const [joinedAt, setJoinedAt] = useState<string | null>(null);
  // The server said this person was already on the list (the query hadn't
  // loaded yet when they tapped): say so, never "¡Anotado!".
  const [alreadyListed, setAlreadyListed] = useState(false);
  // Refs, not state: two taps in the same frame must still send once.
  const joiningRef = useRef(false);
  const answeringRef = useRef(false);
  const [answerError, setAnswerError] = useState('');
  const [wouldPay, setWouldPay] = useState<'yes' | 'no' | 'skipped' | null>(null);
  const [volume, setVolume] = useState<string | 'skipped' | null>(null);
  const logged = useRef(false);

  const refetch = { refetchQueries: [{ query: GET_PAID_OFFERS }] };
  const [join] = useMutation(JOIN_PAID_OFFER_WAITLIST, refetch);
  const [answer] = useMutation(ANSWER_PAID_OFFER, refetch);

  useEffect(() => {
    if (!logged.current) {
      logged.current = true;
      logOfferStep(offer, 'detail_opened', door, trigger);
    }
  }, [offer, door, trigger]);

  const onList = !!joinedAt || !!state?.onWaitlist;
  const listedAt = joinedAt ?? state?.waitlistedAt ?? null;
  const paidAnswer = wouldPay ?? state?.wouldPay ?? null;
  const volumeAnswer = volume ?? state?.volumeRange ?? null;
  const askWouldPay = onList && !paidAnswer;
  const askVolume = onList && offer === 'smart_account' && !!paidAnswer && !volumeAnswer;
  // Thanks only for answers given on this visit (a skip isn't an answer).
  const answeredNow = wouldPay === 'yes' || wouldPay === 'no' || (volume !== null && volume !== 'skipped');

  const onJoin = async () => {
    if (joiningRef.current || onList) {
      return;
    }
    joiningRef.current = true;
    setJoining(true);
    setJoinError('');
    try {
      const { data } = await join({ variables: { product: offer, door, trigger } });
      const result = data?.joinPaidOfferWaitlist;
      if (result?.success) {
        setAlreadyListed(!!result.alreadyListed);
        setJoinedAt(result.waitlistedAt ?? new Date().toISOString());
      } else {
        setJoinError(result?.error || 'No pudimos guardar tu aviso. Intenta de nuevo.');
      }
    } catch {
      setJoinError('No pudimos guardar tu aviso. Intenta de nuevo.');
    } finally {
      joiningRef.current = false;
      setJoining(false);
    }
  };

  const onSoloMiraba = () => {
    logOfferStep(offer, 'solo_miraba', door, trigger);
    navigation.goBack();
  };

  const sendAnswer = async (vars: { wouldPay?: 'yes' | 'no'; volumeRange?: string }) => {
    if (answeringRef.current) {
      return; // a double tap sends one answer
    }
    answeringRef.current = true;
    setAnswerError('');
    try {
      const { data } = await answer({ variables: { product: offer, ...vars } });
      if (!data?.answerPaidOffer?.success) {
        throw new Error(data?.answerPaidOffer?.error || 'failed');
      }
      if (vars.wouldPay) {
        setWouldPay(vars.wouldPay);
      }
      if (vars.volumeRange) {
        setVolume(vars.volumeRange);
      }
    } catch {
      setAnswerError('No pudimos guardar tu respuesta. Intenta de nuevo.');
    } finally {
      answeringRef.current = false;
    }
  };

  return (
    <View style={styles.screen}>
      <Header navigation={navigation} title={copy.title} showBackButton />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.headline}>{copy.headline}</Text>
        {copy.benefits.map((b) => (
          <View key={b.name} style={styles.benefit} accessible>
            <Icon name="check" size={16} color={EMERALD} style={styles.check} accessibilityElementsHidden />
            <View style={styles.benefitText}>
              <Text style={styles.benefitName}>{b.name}</Text>
              <Text style={styles.benefitLine}>{b.line}</Text>
            </View>
          </View>
        ))}
        <Text style={styles.price}>{price ? `Próximamente · ${price} al lanzar` : 'Próximamente'}</Text>

        {onList ? (
          <View style={styles.listed} accessibilityRole="text" accessibilityLiveRegion="polite">
            <Icon name="check-circle" size={18} color={EMERALD} />
            <Text style={styles.listedText}>
              {joinedAt && !alreadyListed
                ? '¡Anotado! Te avisamos cuando esté.'
                : `Ya estás en la lista${listedAt ? ` · desde ${shortDate(listedAt)}` : ''}`}
            </Text>
          </View>
        ) : (
          <>
            <Pressable
              onPress={onJoin}
              disabled={joining}
              style={[styles.primary, joining && styles.primaryBusy]}
              accessibilityRole="button"
              accessibilityLabel="Sí, avísame"
              accessibilityState={{ busy: joining }}
            >
              {joining ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.primaryText}>Sí, avísame</Text>}
            </Pressable>
            {joinError ? (
              <Text style={styles.error} accessibilityLiveRegion="polite">{joinError}</Text>
            ) : null}
            <Pressable
              onPress={onSoloMiraba}
              style={styles.secondary}
              accessibilityRole="button"
              accessibilityLabel="Solo miraba"
              hitSlop={8}
            >
              <Text style={styles.secondaryText}>Solo miraba</Text>
            </Pressable>
          </>
        )}

        {askWouldPay ? (
          <View style={styles.question}>
            <Text style={styles.questionText}>
              {price
                ? `Si estuviera disponible hoy por ${price}, ¿te suscribirías?`
                : 'Si estuviera disponible hoy, ¿te suscribirías?'}
            </Text>
            <View style={styles.answers}>
              <Answer label="Sí" onPress={() => sendAnswer({ wouldPay: 'yes' })} />
              <Answer label="No" onPress={() => sendAnswer({ wouldPay: 'no' })} />
              <Answer label="Omitir" quiet onPress={() => setWouldPay('skipped')} />
            </View>
          </View>
        ) : null}

        {askVolume ? (
          <View style={styles.question}>
            <Text style={styles.questionText}>¿Cuánto moverías o guardarías al mes en Confío?</Text>
            <View style={styles.answers}>
              {VOLUMES.map((v) => (
                <Answer key={v.key} label={v.label} onPress={() => sendAnswer({ volumeRange: v.key })} />
              ))}
              <Answer label="Omitir" quiet onPress={() => setVolume('skipped')} />
            </View>
          </View>
        ) : null}

        {answerError ? (
          <Text style={styles.error} accessibilityLiveRegion="polite">{answerError}</Text>
        ) : null}
        {onList && answeredNow && !askWouldPay && !askVolume ? (
          <Text style={styles.done} accessibilityLiveRegion="polite">Listo. Gracias por contarnos.</Text>
        ) : null}
      </ScrollView>
    </View>
  );
}

function Answer({ label, onPress, quiet }: { label: string; onPress: () => void; quiet?: boolean }) {
  return (
    <Pressable
      onPress={onPress}
      style={[styles.answer, quiet && styles.answerQuiet]}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={4}
    >
      <Text style={[styles.answerText, quiet && styles.answerQuietText]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#FFFFFF' },
  content: { padding: 24, paddingBottom: 48 },
  headline: { fontSize: 24, fontWeight: '700', color: TEXT, marginBottom: 24 },
  benefit: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 16 },
  check: { marginTop: 3, marginRight: 12 },
  benefitText: { flex: 1 },
  benefitName: { fontSize: 16, fontWeight: '600', color: TEXT },
  benefitLine: { fontSize: 14, color: MUTED, marginTop: 2 },
  price: { fontSize: 15, color: TEXT, marginTop: 8, marginBottom: 24 },
  primary: {
    minHeight: 52,
    borderRadius: 14,
    backgroundColor: EMERALD,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryBusy: { opacity: 0.8 },
  primaryText: { fontSize: 17, fontWeight: '700', color: '#FFFFFF' },
  secondary: { minHeight: 44, alignItems: 'center', justifyContent: 'center', marginTop: 8 },
  secondaryText: { fontSize: 15, fontWeight: '600', color: MUTED },
  error: { fontSize: 14, color: '#B91C1C', marginTop: 10, textAlign: 'center' },
  listed: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 52,
    borderRadius: 14,
    backgroundColor: '#D1FAE5',
    paddingHorizontal: 16,
  },
  listedText: { fontSize: 16, fontWeight: '600', color: '#065F46', marginLeft: 8, flexShrink: 1 },
  question: { marginTop: 28 },
  questionText: { fontSize: 16, fontWeight: '600', color: TEXT, marginBottom: 12 },
  answers: { flexDirection: 'row', flexWrap: 'wrap' },
  answer: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: EMERALD,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
    marginBottom: 8,
  },
  answerQuiet: { borderColor: 'transparent' },
  answerText: { fontSize: 15, fontWeight: '600', color: '#065F46' },
  answerQuietText: { color: MUTED },
  done: { fontSize: 15, color: MUTED, marginTop: 16 },
});
