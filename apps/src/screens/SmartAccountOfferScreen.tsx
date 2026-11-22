// Cuenta inteligente: the sign-up entry (spec 8.2 "Subscribe", 8.3).
//
// Everything that can change is the server's: benefit titles and lines and
// their order, both prices, which plan is preselected, the six disclosures,
// and whether this person may subscribe at all. This screen only lays it
// out. Every Cuenta inteligente door of this build lands here (never the old
// waitlist probe), so the whole pitch always shows; someone the server does
// not let sign yet sees why next to a disabled button.
//
// Layout (founder 2026-11-21: Herencia is the key feature, the page must be
// optimistic): the account's deep emerald field carries the inheritance
// promise as its hero (picture, short headline, one supporting line), and a
// white "Así funciona" card of three steps rises over it. Then the rest of
// the account as one calm list (every benefit the same mint icon disc), the
// two plans as selectable cards (annual first, with its saving computed from
// the server's prices), and "Antes de firmar": the six disclosures and ONE
// explicit acceptance. The action bar is pinned. Tapping the button without
// accepting scrolls to the acceptance and marks it, instead of a dead
// disabled button. Without the beneficiary feature there is no Herencia
// hero: the automation headline leads instead.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, ScrollView, StatusBar, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../components/common/AppText';
import CuentaInteligenteMark from '../components/svg/CuentaInteligenteMark';
import { Rise } from '../components/tuMes/motion';
import {
  AcceptRow, ActionButton, Card, HelpButton, IconDisc, LoadError, Notice, NumberedList, ScreenSkeleton, kitStyles,
} from '../components/smartAccount/kit';
import { DeepField, HerenciaArt } from '../components/smartAccount/HerenciaArt';
import { PlanPicker, defaultPlanKey, orderPlans, planSummary } from '../components/smartAccount/PlanPicker';
import { SA, HIT, cardShadow } from '../components/smartAccount/tokens';
import { helpAccount } from '../components/smartAccount/help';
import { cryptoBuyAllowed } from '../components/smartAccount/format';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import {
  fetchBeneficiaryDesignations, fetchSmartAccountEntry, fetchSmartAccountOffer, isSmartAccountOpen, isSmartAccountOpening,
  type SmartAccountBenefit, type SmartAccountOffer,
} from '../services/smartAccount';
import { DEX_TRADING_UI_ENABLED } from '../config/features';
import { logOfferStep, logSmartAccountFunnel } from '../services/paidOffers';
import type { MainStackParamList } from '../types/navigation';

export { orderPlans } from '../components/smartAccount/PlanPicker';

/** One icon family for every benefit: Feather, inside the same mint disc. */
const BENEFIT_ICONS: Record<string, string> = {
  beneficiary: 'heart',
  payments: 'repeat',
  investing: 'trending-up',
  assistant: 'message-circle',
  ownership: 'shield',
};

/** The hero copy: Herencia when the beneficiary feature is on, else automation. */
export const HERO_COPY = {
  inheritance: {
    eyebrow: 'Herencia Digital',
    headline: 'Lo tuyo, para los tuyos.',
    supporting: 'Elige quién recibirá tu cuenta. Mientras la uses, todo sigue siendo tuyo.',
  },
  automation: {
    eyebrow: '',
    headline: 'Tu dinero trabaja con tus reglas.',
    supporting: 'Pagos, envíos e inversiones que se hacen solos, como tú los programas.',
  },
} as const;

/** "Así funciona": the inheritance promise in three facts (spec 6, decision 9). */
export const HERENCIA_STEPS: { icon: string; title: string; body: string }[] = [
  {
    icon: 'user-plus',
    title: 'Eliges a una persona',
    body: 'Alguien de tu confianza, verificado en Confío, que acepta tu invitación. Puedes cambiarla cuando quieras.',
  },
  {
    icon: 'home',
    title: 'Todo sigue siendo tuyo',
    body: 'Usas tu cuenta como siempre. Mientras la uses, nadie más puede tomarla.',
  },
  {
    icon: 'heart',
    title: 'Llega a quien elegiste',
    body: 'Solo si dejas de usarla durante todo el plazo que eliges, pasa a tu beneficiario. Cualquier acción que firmes en tu cuenta en ese plazo lo cancela.',
  },
];

const BLOCKED_FALLBACK = 'Todavía no puedes abrir tu Cuenta inteligente.';

const STOCKS_ONLY_INVESTING = 'Compra acciones automáticamente, cada día, semana, quincena o mes.';

const CTA_LABEL = 'Abrir mi Cuenta inteligente';

/**
 * The hero and the benefits this app can keep. The hero is always Herencia
 * (founder 2026-11-21: inheritance is the key feature and launches with the
 * account), and the beneficiary line moves out of the list into it. Where
 * crypto buys are not offered (an iOS build, or the server's flag off)
 * investing promises stocks only. The rest of the list keeps the server's
 * order.
 */
export function offerPitch(
  data: Pick<SmartAccountOffer, 'headline' | 'benefits' | 'beneficiaryEnabled' | 'investingCryptoEnabled'> | null | undefined,
  dexUi: boolean = DEX_TRADING_UI_ENABLED,
): {
  inheritance: boolean; eyebrow: string; headline: string; supporting: string; benefits: SmartAccountBenefit[];
} {
  const inheritance = true;
  const crypto = cryptoBuyAllowed(data?.investingCryptoEnabled, dexUi);
  const benefits = (data?.benefits ?? [])
    .filter((b) => b.key !== 'beneficiary')
    .map((b) => (b.key === 'investing' && !crypto ? { ...b, body: STOCKS_ONLY_INVESTING } : b));
  const copy = inheritance ? HERO_COPY.inheritance : HERO_COPY.automation;
  return {
    inheritance,
    ...copy,
    benefits,
  };
}

export function SmartAccountOfferScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'SmartAccountOffer'>>();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const door = route.params?.door ?? 'chip';
  const trigger = route.params?.trigger ?? '';

  const offer = useSmartRead(fetchSmartAccountOffer);
  const entry = useSmartRead(fetchSmartAccountEntry);
  const designations = useSmartRead(fetchBeneficiaryDesignations);

  const plans = useMemo(() => orderPlans(offer.data?.plans ?? []), [offer.data]);
  const [picked, setPicked] = useState<string | null>(null);
  const selected = picked ?? defaultPlanKey(plans);
  const selectedPlan = plans.find((p) => p.key === selected) ?? null;
  const [accepted, setAccepted] = useState(false);
  const [missing, setMissing] = useState(false);
  const scroll = useRef<ScrollView>(null);
  const acceptY = useRef(0);
  const logged = useRef(false);

  useEffect(() => {
    if (!logged.current) {
      logged.current = true;
      logOfferStep('smart_account', 'detail_opened', door, trigger);
      logSmartAccountFunnel('subscribe_opened');
    }
  }, [door, trigger]);

  // Someone who already has the account never sees the pitch again, nor
  // does someone whose subscribe is out and not reconciled yet ('opening': a
  // second subscribe must not be invited). An expired one (cancelled and
  // returned) is not open: it may subscribe again.
  const hasAccount = isSmartAccountOpen(entry.data?.status) || isSmartAccountOpening(entry.data?.status);
  useEffect(() => {
    if (hasAccount) {
      navigation.replace('SmartAccountHome');
    }
  }, [hasAccount, navigation]);

  const data = offer.data;
  const pitch = offerPitch(data);
  const canSubscribe = !!data?.available && !!data?.canSubscribe && plans.length > 0;
  const pendingInvite = (designations.data ?? []).find((d) => d.state === 'pending_acceptance');
  // The picture scales with the screen and never crowds a small phone.
  const artWidth = Math.min(260, Math.max(180, width - 120));

  const onContinue = () => {
    if (!selected || !canSubscribe) {
      return;
    }
    if (!accepted) {
      setMissing(true);
      scroll.current?.scrollTo({ y: Math.max(0, acceptY.current - 120), animated: true });
      return;
    }
    navigation.navigate('SmartAccountFund', { plan: selected });
  };

  return (
    <View style={styles.screen}>
      <StatusBar barStyle="light-content" backgroundColor={SA.deep} />
      <View style={[styles.statusBackdrop, { height: insets.top }]} pointerEvents="none" />
      <View style={[styles.topBar, { top: insets.top + 4 }]}>
        <Pressable
          onPress={() => navigation.goBack()}
          style={styles.back}
          hitSlop={6}
          accessibilityRole="button"
          accessibilityLabel="Volver"
        >
          <Icon name="arrow-left" size={22} color={SA.onDeep} />
        </Pressable>
        <HelpButton help={helpAccount(!!data?.beneficiaryEnabled)} onDark />
      </View>

      <ScrollView ref={scroll} contentContainerStyle={styles.scrollContent} bounces={false}>
        <View style={[styles.hero, { paddingTop: insets.top + 4 + HIT + 4 }]}>
          <DeepField />
          <Rise index={0}>
            <View style={styles.brand}>
              <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
                <CuentaInteligenteMark size={28} />
              </View>
              <Text style={styles.brandName} accessibilityRole="header">Cuenta inteligente</Text>
            </View>
            {pitch.inheritance ? (
              <HerenciaArt width={artWidth} style={styles.art} />
            ) : null}
            {pitch.eyebrow ? (
              <View style={styles.eyebrow}>
                <Text style={styles.eyebrowText}>{pitch.eyebrow}</Text>
              </View>
            ) : null}
            <Text style={styles.headline} testID="offer-headline">{pitch.headline}</Text>
            <Text style={styles.supporting}>{pitch.supporting}</Text>
          </Rise>
        </View>

        {offer.loading && !data ? (
          <View style={styles.lift}><ScreenSkeleton /></View>
        ) : offer.failed && !data ? (
          <View style={[styles.lift, styles.side]}><Card><LoadError onRetry={offer.reload} busy={offer.loading} /></Card></View>
        ) : !data ? (
          <View style={[styles.lift, kitStyles.pad]}>
            <Card style={styles.padded}>
              <Text style={kitStyles.lead}>{BLOCKED_FALLBACK}</Text>
            </Card>
          </View>
        ) : (
          <>
            {pitch.inheritance ? (
              <Rise index={1} style={[styles.side, styles.lift]} testID="herencia-steps">
                <Card style={styles.steps}>
                  <Text style={styles.cardTitle} accessibilityRole="header">Así funciona</Text>
                  {HERENCIA_STEPS.map((s, i) => (
                    <View
                      key={s.title}
                      style={[styles.step, i > 0 && styles.divider]}
                      accessible
                      accessibilityLabel={`${i + 1}. ${s.title}. ${s.body}`}
                    >
                      <IconDisc icon={s.icon} size={40} />
                      <View style={styles.itemText}>
                        <Text style={styles.itemTitle}>{s.title}</Text>
                        <Text style={styles.itemBody}>{s.body}</Text>
                      </View>
                    </View>
                  ))}
                </Card>
              </Rise>
            ) : null}

            {pendingInvite ? (
              <View style={[styles.side, pitch.inheritance ? styles.gap : styles.lift]}>
                <Notice
                  icon="user-check"
                  title={`${pendingInvite.ownerName} te eligió como beneficiario`}
                  body="Mira qué significa y decide si aceptas."
                  actionLabel="Ver invitación"
                  onPress={() => navigation.navigate('BeneficiaryInvite', { designationId: pendingInvite.designationId })}
                  style={cardShadow}
                />
              </View>
            ) : null}

            {pitch.benefits.length > 0 ? (
              <>
                {pitch.inheritance || pendingInvite ? (
                  <Text style={styles.section} accessibilityRole="header">También incluye</Text>
                ) : null}
                <Rise
                  index={2}
                  style={[styles.side, !pitch.inheritance && !pendingInvite ? styles.lift : null]}
                >
                  <Card style={styles.benefits}>
                    {pitch.benefits.map((b, i) => (
                      <View
                        key={b.key}
                        style={[styles.benefit, i > 0 && styles.divider]}
                        accessible
                        accessibilityLabel={`${b.title}. ${b.body}`}
                      >
                        <IconDisc icon={BENEFIT_ICONS[b.key] ?? 'check'} size={40} />
                        <View style={styles.itemText}>
                          <Text style={styles.itemTitle}>{b.title}</Text>
                          <Text style={styles.itemBody}>{b.body}</Text>
                        </View>
                      </View>
                    ))}
                  </Card>
                </Rise>
              </>
            ) : null}

            {plans.length > 0 ? (
              <>
                <Text style={styles.section} accessibilityRole="header">Elige tu plan</Text>
                <View style={styles.side}>
                  <PlanPicker plans={plans} selected={selected} onSelect={setPicked} />
                </View>
              </>
            ) : null}

            {data.disclosures.length > 0 ? (
              <>
                <Text style={styles.section} accessibilityRole="header">Antes de firmar</Text>
                <View style={styles.side}>
                  <Text style={styles.sectionLead}>Lo importante, en claro.</Text>
                  <Card flat style={styles.disclosures}>
                    <NumberedList items={data.disclosures} />
                  </Card>
                  {canSubscribe ? (
                    <View onLayout={(e) => { acceptY.current = e.nativeEvent.layout.y; }} style={styles.acceptBox}>
                      <AcceptRow
                        checked={accepted}
                        onToggle={() => { setAccepted((v) => !v); setMissing(false); }}
                        label="Leí estas condiciones y las acepto"
                        highlight={missing}
                        testID="accept-disclosures"
                      />
                      {missing && !accepted ? (
                        <Text style={styles.missing} accessibilityLiveRegion="polite">
                          Marca la casilla para continuar.
                        </Text>
                      ) : null}
                    </View>
                  ) : null}
                </View>
              </>
            ) : null}
          </>
        )}
      </ScrollView>

      {data ? (
        <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, 12) }]}>
          {canSubscribe ? null : (
            <Notice
              tone="neutral"
              body={data.blockedReason || BLOCKED_FALLBACK}
              style={styles.blockedNote}
              testID="offer-blocked"
            />
          )}
          {canSubscribe && selectedPlan ? (
            <Text style={styles.barSummary} testID="offer-summary">{planSummary(selectedPlan)}</Text>
          ) : null}
          <ActionButton label={CTA_LABEL} onPress={onContinue} disabled={!canSubscribe} testID="offer-continue" />
          {canSubscribe ? <Text style={styles.barNote}>No se cobra nada hasta que firmes.</Text> : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: SA.page },
  scrollContent: { paddingBottom: 28 },
  statusBackdrop: { position: 'absolute', top: 0, left: 0, right: 0, backgroundColor: SA.deep, zIndex: 2, elevation: 4 },
  topBar: {
    position: 'absolute', left: 8, right: 8, zIndex: 3, elevation: 5,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
  },
  back: {
    width: HIT, height: HIT, borderRadius: HIT / 2, alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.14)',
  },
  hero: {
    backgroundColor: SA.deep, paddingHorizontal: 24, paddingBottom: 64, overflow: 'hidden',
    borderBottomLeftRadius: 28, borderBottomRightRadius: 28,
  },
  brand: { flexDirection: 'row', alignItems: 'center' },
  brandName: { fontSize: 16, fontWeight: '700', color: SA.onDeep, marginLeft: 10 },
  art: { alignSelf: 'center', marginTop: 8 },
  eyebrow: {
    alignSelf: 'flex-start', marginTop: 12, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.14)',
  },
  eyebrowText: { fontSize: 13, fontWeight: '700', color: SA.onDeepMuted, letterSpacing: 0.3 },
  headline: { fontSize: 30, lineHeight: 36, fontWeight: '700', color: SA.onDeep, marginTop: 12 },
  supporting: { fontSize: 17, lineHeight: 25, color: SA.onDeepMuted, marginTop: 8 },
  lift: { marginTop: -40 },
  gap: { marginTop: 16 },
  side: { paddingHorizontal: 16 },
  padded: { paddingVertical: 20 },
  cardTitle: { fontSize: 18, fontWeight: '700', color: SA.text, paddingTop: 18, paddingBottom: 4 },
  steps: { paddingHorizontal: 18, paddingBottom: 4 },
  step: { flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 14 },
  benefits: { paddingHorizontal: 18 },
  benefit: { flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 16 },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: SA.line },
  itemText: { flex: 1, marginLeft: 14 },
  itemTitle: { fontSize: 16, lineHeight: 22, fontWeight: '700', color: SA.text },
  itemBody: { fontSize: 14, lineHeight: 20, color: SA.muted, marginTop: 2 },
  section: { fontSize: 20, fontWeight: '700', color: SA.text, marginTop: 32, marginBottom: 12, paddingHorizontal: 20 },
  sectionLead: { fontSize: 15, lineHeight: 21, color: SA.muted, marginTop: -6, marginBottom: 12, paddingHorizontal: 4 },
  disclosures: { paddingVertical: 8, borderWidth: StyleSheet.hairlineWidth, borderColor: SA.line },
  acceptBox: { marginTop: 12 },
  missing: { fontSize: 14, color: SA.noticeText, marginTop: 8, marginLeft: 4 },
  blockedNote: { marginBottom: 12 },
  bar: {
    paddingHorizontal: 16, paddingTop: 12, backgroundColor: SA.card,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: SA.line,
  },
  barSummary: { fontSize: 14, fontWeight: '600', color: SA.text, textAlign: 'center', marginBottom: 10 },
  barNote: { fontSize: 13, color: SA.muted, textAlign: 'center', marginTop: 8 },
});
