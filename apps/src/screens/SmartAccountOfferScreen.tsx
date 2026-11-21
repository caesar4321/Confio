// Cuenta inteligente: the sign-up entry (spec 8.2 "Subscribe", 8.3).
//
// Everything that can change is the server's: benefits and their order (the
// headline benefit first), both prices, which plan is preselected, the six
// disclosures, and whether this person may subscribe at all. This screen
// only lays it out. Every Cuenta inteligente door of this build lands here
// (never the old waitlist probe), so the whole pitch always shows; someone
// the server does not let sign yet sees why next to a disabled Continuar.
//
// Layout: the account's deep emerald field with its mark, a white card of
// benefits rising over it (the first one, the headline, set larger), the two
// plans as one radio group (annual first), then "Antes de firmar": the six
// disclosures as a numbered, full-size list and ONE explicit acceptance. The
// action bar is pinned. Tapping "Continuar" without accepting scrolls to the
// acceptance and marks it, instead of a dead disabled button.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, ScrollView, StatusBar, StyleSheet, View } from 'react-native';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../components/common/AppText';
import CuentaInteligenteMark from '../components/svg/CuentaInteligenteMark';
import { Rise } from '../components/tuMes/motion';
import {
  AcceptRow, ActionButton, Card, HelpButton, LoadError, Notice, NumberedList, ScreenSkeleton, kitStyles,
} from '../components/smartAccount/kit';
import { SA, HIT, cardShadow } from '../components/smartAccount/tokens';
import { helpAccount } from '../components/smartAccount/help';
import { centsToDecimal, cryptoBuyAllowed, planName, planPeriod, shortDate, toCents, usd } from '../components/smartAccount/format';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import {
  fetchBeneficiaryDesignations, fetchSmartAccountEntry, fetchSmartAccountOffer, isSmartAccountOpen, isSmartAccountOpening,
  type SmartAccountBenefit, type SmartAccountOffer, type SmartAccountPlan,
} from '../services/smartAccount';
import { DEX_TRADING_UI_ENABLED } from '../config/features';
import { logOfferStep, logSmartAccountFunnel } from '../services/paidOffers';
import type { MainStackParamList } from '../types/navigation';

const BENEFIT_ICONS: Record<string, string> = {
  beneficiary: 'users',
  payments: 'repeat',
  investing: 'trending-up',
  assistant: 'message-circle',
};

const HEADLINES: Record<string, string> = {
  beneficiary_first: 'Tu dinero sigue tus reglas y llega a quien tú elijas.',
  automation_first: 'Tu dinero se mueve según tus reglas.',
};

const BLOCKED_FALLBACK = 'Todavía no puedes abrir tu Cuenta inteligente.';

const STOCKS_ONLY_INVESTING = 'Compra acciones automáticamente, cada día, semana, quincena o mes.';

/**
 * The headline and benefits this app can keep. The server always lists the
 * beneficiary and may lead with it, and its investing line names bitcoin and
 * gold: without the beneficiary feature that benefit is dropped (and the
 * automation headline used), and where crypto buys are not offered (an iOS
 * build, or the server's flag off) investing promises stocks only.
 */
export function offerPitch(
  data: Pick<SmartAccountOffer, 'headline' | 'benefits' | 'beneficiaryEnabled' | 'investingCryptoEnabled'> | null | undefined,
  dexUi: boolean = DEX_TRADING_UI_ENABLED,
): { headline: string; benefits: SmartAccountBenefit[] } {
  const beneficiary = !!data?.beneficiaryEnabled;
  const crypto = cryptoBuyAllowed(data?.investingCryptoEnabled, dexUi);
  const key = beneficiary ? data?.headline ?? '' : 'automation_first';
  const benefits = (data?.benefits ?? [])
    .filter((b) => beneficiary || b.key !== 'beneficiary')
    .map((b) => (b.key === 'investing' && !crypto ? { ...b, body: STOCKS_ONLY_INVESTING } : b));
  return { headline: HEADLINES[key] ?? HEADLINES.automation_first, benefits };
}

/** Annual first, then the rest in the server's order. */
export function orderPlans(plans: SmartAccountPlan[]): SmartAccountPlan[] {
  return [...plans].sort((a, b) => (a.key === 'annual' ? -1 : 0) - (b.key === 'annual' ? -1 : 0));
}

/** The annual price per month, from the server's own price (integer cents). */
function perMonth(plan: SmartAccountPlan): string | null {
  const cents = toCents(plan.priceUsd);
  if (plan.key !== 'annual' || cents === null) {
    return null;
  }
  return centsToDecimal((cents + 6n) / 12n); // to the nearest cent
}

export function SmartAccountOfferScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'SmartAccountOffer'>>();
  const insets = useSafeAreaInsets();
  const door = route.params?.door ?? 'chip';
  const trigger = route.params?.trigger ?? '';

  const offer = useSmartRead(fetchSmartAccountOffer);
  const entry = useSmartRead(fetchSmartAccountEntry);
  const designations = useSmartRead(fetchBeneficiaryDesignations);

  const plans = useMemo(() => orderPlans(offer.data?.plans ?? []), [offer.data]);
  const [picked, setPicked] = useState<string | null>(null);
  const selected = picked ?? plans.find((p) => p.isDefault)?.key ?? plans[0]?.key ?? null;
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
          <Icon name="arrow-left" size={22} color={SA.deep} />
        </Pressable>
        <HelpButton help={helpAccount(!!data?.beneficiaryEnabled)} onDark />
      </View>

      <ScrollView ref={scroll} contentContainerStyle={styles.scrollContent} bounces={false}>
        <View style={[styles.hero, { paddingTop: insets.top + 4 + HIT + 8 }]}>
          <Rise index={0}>
            <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
              <CuentaInteligenteMark size={64} />
            </View>
            <Text style={styles.title} accessibilityRole="header">Cuenta inteligente</Text>
            <Text style={styles.headline}>
              {pitch.headline}
            </Text>
          </Rise>
        </View>

        {offer.loading && !data ? (
          <View style={styles.lift}><ScreenSkeleton /></View>
        ) : offer.failed && !data ? (
          <View style={styles.lift}><Card><LoadError onRetry={offer.reload} busy={offer.loading} /></Card></View>
        ) : !data ? (
          <View style={[styles.lift, kitStyles.pad]}>
            <Card style={styles.padded}>
              <Text style={kitStyles.lead}>{BLOCKED_FALLBACK}</Text>
            </Card>
          </View>
        ) : (
          <>
            {pendingInvite ? (
              <View style={[styles.lift, styles.side]}>
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

            <Rise index={1} style={[styles.benefits, pendingInvite ? styles.afterNotice : styles.lift]}>
              {pitch.benefits.map((b, i) => (
                <View
                  key={b.key}
                  style={[styles.benefit, i > 0 && styles.benefitDivider]}
                  accessible
                  accessibilityLabel={`${b.title}. ${b.body}`}
                >
                  <View style={[styles.benefitIcon, i === 0 && styles.benefitIconLead]}>
                    <Icon name={BENEFIT_ICONS[b.key] ?? 'check'} size={i === 0 ? 22 : 20} color={i === 0 ? SA.onDeep : SA.deep} />
                  </View>
                  <View style={styles.benefitText}>
                    <Text style={[styles.benefitName, i === 0 && styles.benefitNameLead]}>{b.title}</Text>
                    <Text style={styles.benefitLine}>{b.body}</Text>
                  </View>
                </View>
              ))}
            </Rise>

            {plans.length > 0 ? (
              <>
                <Text style={styles.section} accessibilityRole="header">Elige tu plan</Text>
                <View style={styles.side} accessibilityRole="radiogroup">
                  {plans.map((plan) => {
                    const on = plan.key === selected;
                    const monthly = perMonth(plan);
                    const next = plan.nextPriceUsd
                      ? `Desde el ${shortDate(plan.nextPriceEffectiveAt)}: ${usd(plan.nextPriceUsd)}`
                      : '';
                    return (
                      <Pressable
                        key={plan.key}
                        onPress={() => setPicked(plan.key)}
                        style={({ pressed }) => [styles.plan, on && styles.planOn, pressed && styles.pressed]}
                        accessibilityRole="radio"
                        accessibilityState={{ selected: on }}
                        accessibilityLabel={[
                          `Plan ${planName(plan.key)}`, `${usd(plan.priceUsd)} ${planPeriod(plan.key)}`,
                          monthly ? `Equivale a ${usd(monthly)} al mes` : '', next,
                        ].filter(Boolean).join('. ')}
                        testID={`plan-${plan.key}`}
                      >
                        <Icon name={on ? 'check-circle' : 'circle'} size={24} color={on ? SA.deep : SA.faint} />
                        <View style={styles.planText}>
                          <Text style={styles.planName}>{planName(plan.key)}</Text>
                          {monthly ? <Text style={styles.planNote}>{`Equivale a ${usd(monthly)} al mes`}</Text> : null}
                          {next ? <Text style={styles.planNote}>{next}</Text> : null}
                        </View>
                        <View style={styles.planPriceBox}>
                          <Text style={styles.planPrice} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>
                            {usd(plan.priceUsd)}
                          </Text>
                          <Text style={styles.planPer}>{planPeriod(plan.key)}</Text>
                        </View>
                      </Pressable>
                    );
                  })}
                </View>
              </>
            ) : null}

            {data.disclosures.length > 0 ? (
              <>
                <Text style={styles.section} accessibilityRole="header">Antes de firmar</Text>
                <View style={styles.side}>
                  <Card style={styles.disclosures}>
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
          <ActionButton label="Continuar" onPress={onContinue} disabled={!canSubscribe} testID="offer-continue" />
          {canSubscribe ? <Text style={styles.barNote}>No se cobra nada hasta que firmes.</Text> : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: SA.page },
  scrollContent: { paddingBottom: 24 },
  statusBackdrop: { position: 'absolute', top: 0, left: 0, right: 0, backgroundColor: SA.deep, zIndex: 2, elevation: 4 },
  topBar: {
    position: 'absolute', left: 12, right: 8, zIndex: 3, elevation: 5,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
  },
  back: {
    width: HIT, height: HIT, borderRadius: HIT / 2, alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.92)',
  },
  hero: {
    backgroundColor: SA.deep, paddingHorizontal: 24, paddingBottom: 60,
    borderBottomLeftRadius: 28, borderBottomRightRadius: 28,
  },
  title: { fontSize: 32, fontWeight: '700', color: SA.onDeep, marginTop: 14 },
  headline: { fontSize: 18, lineHeight: 26, color: SA.onDeepMuted, marginTop: 6 },
  lift: { marginTop: -36 },
  afterNotice: { marginTop: 12 },
  side: { paddingHorizontal: 16 },
  padded: { paddingVertical: 20 },
  benefits: { backgroundColor: SA.card, marginHorizontal: 16, borderRadius: 20, paddingHorizontal: 18, ...cardShadow },
  benefit: { flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 16 },
  benefitDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: SA.line },
  benefitIcon: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: SA.mint,
    alignItems: 'center', justifyContent: 'center', marginRight: 14,
  },
  benefitIconLead: { backgroundColor: SA.deep },
  benefitText: { flex: 1 },
  benefitName: { fontSize: 16, fontWeight: '600', color: SA.text },
  benefitNameLead: { fontSize: 19, fontWeight: '700' },
  benefitLine: { fontSize: 14, lineHeight: 20, color: SA.muted, marginTop: 3 },
  section: { fontSize: 20, fontWeight: '700', color: SA.text, marginTop: 28, marginBottom: 12, paddingHorizontal: 20 },
  plan: {
    flexDirection: 'row', alignItems: 'center', minHeight: 76, borderRadius: 18, borderWidth: 1.5,
    borderColor: SA.line, backgroundColor: SA.card, paddingHorizontal: 16, paddingVertical: 14, marginBottom: 10,
  },
  planOn: { borderColor: SA.deep, backgroundColor: SA.mint },
  pressed: { opacity: 0.75 },
  planText: { flex: 1, marginLeft: 12 },
  planName: { fontSize: 17, fontWeight: '700', color: SA.text },
  planNote: { fontSize: 13, lineHeight: 18, color: SA.muted, marginTop: 2 },
  planPriceBox: { alignItems: 'flex-end', marginLeft: 12, maxWidth: '48%' },
  planPrice: { fontSize: 22, fontWeight: '700', color: SA.text },
  planPer: { fontSize: 13, color: SA.muted, marginTop: 1 },
  disclosures: { paddingVertical: 8 },
  acceptBox: { marginTop: 12 },
  missing: { fontSize: 14, color: SA.noticeText, marginTop: 8, marginLeft: 4 },
  blockedNote: { marginBottom: 12 },
  bar: {
    paddingHorizontal: 16, paddingTop: 12, backgroundColor: SA.card,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: SA.line,
  },
  barNote: { fontSize: 13, color: SA.muted, textAlign: 'center', marginTop: 8 },
});
