// The pitch behind the paid-offer probes (Confío IA+, Cuenta inteligente).
// A waitlist only: nothing is sold, charged or unlocked here. "¡Anotado!"
// appears only after the server confirms the join (never optimistically), and
// the price is the server's value. Design: docs/designs/cuenta-inteligente-fake-door.md.
//
// Layout: a mint hero that carries the offer's own mark (the app's emerald
// language, like Inicio and Tu mes), a white card of benefits rising in, the
// price with "nothing is charged today", and a pinned action bar so the
// answer is always one tap away on any phone size.
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StatusBar, StyleSheet, View } from 'react-native';
import { useMutation } from '@apollo/client';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../components/common/AppText';
import CuentaInteligenteMark from '../components/svg/CuentaInteligenteMark';
import { Rise } from '../components/tuMes/motion';
import type { MainStackParamList } from '../types/navigation';
import {
  ANSWER_PAID_OFFER,
  GET_PAID_OFFERS,
  JOIN_PAID_OFFER_WAITLIST,
  logOfferStep,
  usePaidOffers,
  type PaidOfferKey,
} from '../services/paidOffers';

const HERO = '#34D399'; // colors.heroField
const ON_HERO = '#064E3B'; // colors.onHeroField (deep text on mint, 5.1:1)
const EMERALD = '#10B981';
const DEEP = '#065F46';
const TEXT = '#1F2937';
const MUTED = '#6B7280';
const LINE = '#E5E7EB';
const MINT_SURFACE = '#ECFDF5';
const BACK_SIZE = 40;

type Benefit = { icon: string; name: string; line: string };

// Matched copy: five benefits each, same price (design review + eng review D7).
const OFFERS: Record<PaidOfferKey, { title: string; headline: string; benefits: Benefit[] }> = {
  ia_plus: {
    title: 'Confío IA+',
    headline: 'Tu asistente financiero personal.',
    benefits: [
      { icon: 'message-circle', name: 'Respuestas más avanzadas', line: 'Modelos de IA más capaces para tus preguntas de dinero.' },
      { icon: 'mic', name: 'Conversación por voz', line: 'Habla con Confío IA en lugar de escribir.' },
      { icon: 'zap', name: 'Más uso de Confío IA', line: 'Más preguntas y análisis cada día.' },
      { icon: 'pie-chart', name: 'Análisis de tus gastos, ahorros e inversiones', line: 'Con tus números reales.' },
      { icon: 'target', name: 'Seguimiento personalizado', line: 'De tus metas y de cómo se mueve tu dinero.' },
    ],
  },
  smart_account: {
    title: 'Cuenta inteligente',
    headline: 'Tu dinero se mueve según tus reglas.',
    benefits: [
      { icon: 'repeat', name: 'Pagos automáticos', line: 'A Pix, Bre-B, CLABE y Alias, que tú autorizas y cancelas cuando quieras.' },
      { icon: 'credit-card', name: 'Suscripciones con comercios', line: 'Con el monto y la frecuencia que tú apruebas.' },
      { icon: 'calendar', name: 'Transferencias programadas', line: 'A tu familia y a tus propias cuentas.' },
      { icon: 'shield', name: 'Control de débitos', line: 'Tú apruebas cada permiso y lo puedes quitar.' },
      { icon: 'bell', name: 'Aviso antes de cada cobro', line: 'Y si un cobro viene más alto de lo normal.' },
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

function OfferMark({ offer }: { offer: PaidOfferKey }) {
  if (offer === 'smart_account') {
    return <CuentaInteligenteMark size={64} />;
  }
  // Confío IA+: the same deep emerald disc family, with its name as the glyph
  // (never a sparkle or violet, which read as an AI unlock).
  return (
    <View style={styles.iaMark}>
      <Text style={styles.iaMarkText}>IA+</Text>
    </View>
  );
}

export function PaidOfferScreen() {
  const navigation = useNavigation<any>();
  const insets = useSafeAreaInsets();
  const route = useRoute<RouteProp<MainStackParamList, 'PaidOffer'>>();
  const offer: PaidOfferKey = route.params?.offer === 'smart_account' ? 'smart_account' : 'ia_plus';
  const door = route.params?.door ?? 'chip';
  const trigger = route.params?.trigger ?? '';
  const copy = OFFERS[offer];
  const state = usePaidOffers()[offer];
  const price = state?.monthlyPriceUsd ?? null;

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
  const scroll = useRef<ScrollView>(null);
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (scrollTimer.current) {
      clearTimeout(scrollTimer.current);
    }
  }, []);

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
        // The question appears under the price: bring it into view.
        scrollTimer.current = setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 150);
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
      <StatusBar barStyle="dark-content" backgroundColor={HERO} />
      {/* Fixed while the page scrolls: the mint strip behind the status bar
          and the way back, first in the tree so a screen reader starts here. */}
      <View style={[styles.statusBackdrop, { height: insets.top }]} pointerEvents="none" />
      <Pressable
        onPress={() => navigation.goBack()}
        style={[styles.back, { top: insets.top + 8 }]}
        accessibilityRole="button"
        accessibilityLabel="Volver"
        hitSlop={8}
      >
        <Icon name="arrow-left" size={22} color={ON_HERO} />
      </Pressable>

      <ScrollView ref={scroll} contentContainerStyle={styles.scrollContent} bounces={false}>
        <View style={[styles.hero, { paddingTop: insets.top + 8 + BACK_SIZE }]}>
          <Rise index={0} style={styles.heroBody}>
            <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
              <OfferMark offer={offer} />
            </View>
            <View style={styles.soonTag}>
              <Text style={styles.soonTagText}>Próximamente</Text>
            </View>
            <Text style={styles.title} accessibilityRole="header">{copy.title}</Text>
            <Text style={styles.headline}>{copy.headline}</Text>
          </Rise>
        </View>

        <Rise index={1} style={styles.card}>
          {copy.benefits.map((b, i) => (
            <View
              key={b.name}
              style={[styles.benefit, i > 0 && styles.benefitDivider]}
              accessible
              accessibilityLabel={`${b.name}. ${b.line}`}
            >
              <Icon name={b.icon} size={22} color={EMERALD} style={styles.benefitIcon} />
              <View style={styles.benefitText}>
                <Text style={styles.benefitName}>{b.name}</Text>
                <Text style={styles.benefitLine}>{b.line}</Text>
              </View>
            </View>
          ))}
        </Rise>

        <Rise index={2} style={styles.priceCard}>
          {price ? (
            <View style={styles.priceRow} accessible accessibilityLabel={`${price} dólares al mes al lanzar`}>
              <Text style={styles.priceAmount}>{`US$${price}`}</Text>
              <Text style={styles.pricePer}>/mes al lanzar</Text>
            </View>
          ) : (
            <Text style={styles.priceAmount}>Muy pronto</Text>
          )}
          <View style={styles.freeRow}>
            <Icon name="check-circle" size={16} color={DEEP} />
            <Text style={styles.freeText}>Hoy no se cobra nada: solo te anotas en la lista.</Text>
          </View>
        </Rise>

        {askWouldPay ? (
          <View style={styles.question}>
            <Text style={styles.questionText}>
              {price
                ? `Si estuviera disponible hoy por US$${price}/mes, ¿te suscribirías?`
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

      <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, 12) }]}>
        {onList ? (
          <View style={styles.listed} accessibilityLiveRegion="polite">
            <Icon name="check-circle" size={20} color={DEEP} />
            <Text style={styles.listedText}>
              {joinedAt && !alreadyListed
                ? '¡Anotado! Te avisamos cuando esté.'
                : `Ya estás en la lista${listedAt ? ` · desde ${shortDate(listedAt)}` : ''}`}
            </Text>
          </View>
        ) : (
          <>
            {joinError ? (
              <Text style={[styles.error, styles.barError]} accessibilityLiveRegion="polite">{joinError}</Text>
            ) : null}
            <Pressable
              onPress={onJoin}
              disabled={joining}
              style={({ pressed }) => [styles.primary, (pressed || joining) && styles.primaryPressed]}
              accessibilityRole="button"
              accessibilityLabel="Sí, avísame"
              accessibilityState={{ busy: joining }}
            >
              {joining ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.primaryText}>Sí, avísame</Text>}
            </Pressable>
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
      </View>
    </View>
  );
}

function Answer({ label, onPress, quiet }: { label: string; onPress: () => void; quiet?: boolean }) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.answer, quiet && styles.answerQuiet, pressed && styles.answerPressed]}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={4}
    >
      <Text style={[styles.answerText, quiet && styles.answerQuietText]}>{label}</Text>
    </Pressable>
  );
}

const shadow = {
  shadowColor: '#064E3B',
  shadowOffset: { width: 0, height: 6 },
  shadowOpacity: 0.08,
  shadowRadius: 16,
  elevation: 3,
};

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#F9FAFB' },
  scrollContent: { paddingBottom: 24 },
  hero: {
    backgroundColor: HERO,
    paddingHorizontal: 24,
    paddingBottom: 56,
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
  },
  back: {
    position: 'absolute',
    left: 12,
    width: BACK_SIZE,
    height: BACK_SIZE,
    borderRadius: BACK_SIZE / 2,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.9)',
    zIndex: 2,
    elevation: 4,
  },
  statusBackdrop: { position: 'absolute', top: 0, left: 0, right: 0, backgroundColor: HERO, zIndex: 2, elevation: 4 },
  heroBody: { marginTop: 8 },
  iaMark: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: DEEP,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iaMarkText: { fontSize: 20, fontWeight: '700', color: '#FCD34D' },
  soonTag: {
    alignSelf: 'flex-start',
    marginTop: 16,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: 'rgba(255,255,255,0.85)',
  },
  soonTagText: { fontSize: 12, fontWeight: '700', color: ON_HERO, letterSpacing: 0.3 },
  title: { fontSize: 32, fontWeight: '700', color: ON_HERO, marginTop: 10 },
  headline: { fontSize: 18, color: ON_HERO, marginTop: 6, lineHeight: 25 },
  card: {
    backgroundColor: '#FFFFFF',
    marginHorizontal: 16,
    marginTop: -32,
    borderRadius: 20,
    paddingHorizontal: 18,
    ...shadow,
  },
  benefit: { flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 16 },
  benefitDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: LINE },
  benefitIcon: { marginTop: 1, marginRight: 14 },
  benefitText: { flex: 1 },
  benefitName: { fontSize: 16, fontWeight: '600', color: TEXT },
  benefitLine: { fontSize: 14, color: MUTED, marginTop: 3, lineHeight: 20 },
  priceCard: {
    marginHorizontal: 16,
    marginTop: 16,
    borderRadius: 20,
    padding: 18,
    backgroundColor: MINT_SURFACE,
  },
  priceRow: { flexDirection: 'row', alignItems: 'baseline', flexWrap: 'wrap' },
  priceAmount: { fontSize: 28, fontWeight: '700', color: DEEP },
  pricePer: { fontSize: 15, color: DEEP, marginLeft: 6 },
  freeRow: { flexDirection: 'row', alignItems: 'center', marginTop: 8 },
  freeText: { fontSize: 14, color: DEEP, marginLeft: 6, flexShrink: 1 },
  question: {
    marginHorizontal: 16,
    marginTop: 16,
    borderRadius: 20,
    padding: 18,
    backgroundColor: '#FFFFFF',
    ...shadow,
  },
  questionText: { fontSize: 16, fontWeight: '600', color: TEXT, marginBottom: 12, lineHeight: 22 },
  answers: { flexDirection: 'row', flexWrap: 'wrap' },
  answer: {
    minHeight: 44,
    paddingHorizontal: 18,
    borderRadius: 22,
    backgroundColor: MINT_SURFACE,
    borderWidth: 1,
    borderColor: '#A7F3D0',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
    marginBottom: 8,
  },
  answerPressed: { backgroundColor: '#D1FAE5' },
  answerQuiet: { backgroundColor: 'transparent', borderColor: 'transparent' },
  answerText: { fontSize: 15, fontWeight: '600', color: DEEP },
  answerQuietText: { color: MUTED },
  error: { fontSize: 14, color: '#B91C1C', marginTop: 12, textAlign: 'center', marginHorizontal: 16 },
  barError: { marginTop: 0, marginBottom: 8 },
  done: { fontSize: 15, color: MUTED, marginTop: 16, textAlign: 'center' },
  bar: {
    paddingHorizontal: 16,
    paddingTop: 12,
    backgroundColor: '#FFFFFF',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: LINE,
  },
  primary: {
    minHeight: 54,
    borderRadius: 16,
    backgroundColor: EMERALD,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryPressed: { backgroundColor: '#059669' },
  primaryText: { fontSize: 17, fontWeight: '700', color: '#FFFFFF' },
  secondary: { minHeight: 44, alignItems: 'center', justifyContent: 'center', marginTop: 4 },
  secondaryText: { fontSize: 15, fontWeight: '600', color: MUTED },
  listed: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 54,
    borderRadius: 16,
    backgroundColor: MINT_SURFACE,
    paddingHorizontal: 16,
    marginBottom: 4,
  },
  listedText: { fontSize: 16, fontWeight: '600', color: DEEP, marginLeft: 8, flexShrink: 1 },
});
