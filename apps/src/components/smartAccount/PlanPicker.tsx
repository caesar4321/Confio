// "Elige tu plan": the two plans as two selectable cards, side by side (one
// above the other on very narrow screens), annual first and preselected
// unless the server says otherwise. Every number is derived from the
// server's own prices with integer cents: the monthly equivalent of the
// annual plan and what it saves against twelve monthly payments. A saving is
// shown only when it is real, and "N meses gratis" only when the numbers
// give at least two whole months.
import React from 'react';
import { Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../common/AppText';
import { SA } from './tokens';
import { centsToDecimal, planName, planPeriod, shortDate, toCents, usd } from './format';
import type { SmartAccountPlan } from '../../services/smartAccount';

/** Annual first, then the rest in the server's order. */
export function orderPlans(plans: SmartAccountPlan[]): SmartAccountPlan[] {
  return [...plans].sort((a, b) => (a.key === 'annual' ? -1 : 0) - (b.key === 'annual' ? -1 : 0));
}

/** The server's default; without one, annual; then whatever comes first. */
export function defaultPlanKey(plans: SmartAccountPlan[]): string | null {
  return plans.find((p) => p.isDefault)?.key
    ?? plans.find((p) => p.key === 'annual')?.key
    ?? plans[0]?.key
    ?? null;
}

/** The annual price per month, to the nearest cent ("12.50"); null otherwise. */
export function perMonth(plan: SmartAccountPlan): string | null {
  const cents = toCents(plan.priceUsd);
  if (plan.key !== 'annual' || cents === null) {
    return null;
  }
  return centsToDecimal((cents + 6n) / 12n);
}

/**
 * What the annual plan saves against twelve monthly payments, from the
 * server's current prices. null when either price is missing or the annual
 * plan does not save anything.
 */
export function annualSavings(plans: SmartAccountPlan[]): { usd: string; freeMonths: number } | null {
  const annual = toCents(plans.find((p) => p.key === 'annual')?.priceUsd);
  const monthly = toCents(plans.find((p) => p.key === 'monthly')?.priceUsd);
  if (annual === null || monthly === null || annual <= 0n || monthly <= 0n) {
    return null;
  }
  const saved = monthly * 12n - annual;
  if (saved <= 0n) {
    return null;
  }
  return { usd: centsToDecimal(saved), freeMonths: Number(saved / monthly) };
}

/** The badge on the annual card: "2 meses gratis" only when true, else "Ahorras US$X". */
export function savingsBadge(plans: SmartAccountPlan[]): string | null {
  const s = annualSavings(plans);
  if (!s) {
    return null;
  }
  return s.freeMonths >= 2 ? `${s.freeMonths} meses gratis` : `Ahorras ${usd(s.usd)}`;
}

/** One line for the action bar: "US$149.99 por año · US$12.50 al mes". */
export function planSummary(plan: SmartAccountPlan | null | undefined): string {
  if (!plan) {
    return '';
  }
  const monthly = perMonth(plan);
  return [`${usd(plan.priceUsd)} ${planPeriod(plan.key)}`.trim(), monthly ? `${usd(monthly)} al mes` : '']
    .filter(Boolean).join(' · ');
}

/** Under this width the two cards stack. */
const STACK_BELOW = 340;

export function PlanPicker({ plans, selected, onSelect }: {
  plans: SmartAccountPlan[]; selected: string | null; onSelect: (key: string) => void;
}) {
  const { width } = useWindowDimensions();
  const stacked = width < STACK_BELOW;
  const badge = savingsBadge(plans);
  return (
    <View style={[styles.group, stacked && styles.groupStacked]} accessibilityRole="radiogroup">
      {plans.map((plan, i) => {
        const on = plan.key === selected;
        const monthly = perMonth(plan);
        const planBadge = plan.key === 'annual' ? badge : null;
        const next = plan.nextPriceUsd
          ? `Desde el ${shortDate(plan.nextPriceEffectiveAt)}: ${usd(plan.nextPriceUsd)}`
          : '';
        return (
          <Pressable
            key={plan.key}
            onPress={() => onSelect(plan.key)}
            style={({ pressed }) => [
              styles.card,
              stacked ? styles.cardStacked : i > 0 && styles.cardGap,
              on && styles.cardOn,
              pressed && styles.pressed,
            ]}
            accessibilityRole="radio"
            accessibilityState={{ selected: on }}
            accessibilityLabel={[
              `Plan ${planName(plan.key)}`, `${usd(plan.priceUsd)} ${planPeriod(plan.key)}`,
              monthly ? `Equivale a ${usd(monthly)} al mes` : '', planBadge ?? '', next,
            ].filter(Boolean).join('. ')}
            testID={`plan-${plan.key}`}
          >
            {planBadge ? (
              <View style={[styles.badge, on && styles.badgeOn]} testID="plan-savings">
                <Text style={[styles.badgeText, on && styles.badgeTextOn]} numberOfLines={1}>{planBadge}</Text>
              </View>
            ) : null}
            <View style={styles.head}>
              <Text style={styles.name}>{planName(plan.key)}</Text>
              <View style={[styles.radio, on && styles.radioOn]}>
                {on ? <Icon name="check" size={14} color={SA.onDeep} /> : null}
              </View>
            </View>
            <Text style={styles.price} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>
              {usd(plan.priceUsd)}
            </Text>
            <Text style={styles.per}>{planPeriod(plan.key)}</Text>
            {monthly ? <Text style={styles.note}>{`${usd(monthly)} al mes`}</Text> : null}
            {next ? <Text style={styles.next}>{next}</Text> : null}
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  group: { flexDirection: 'row', alignItems: 'stretch', paddingTop: 12 },
  groupStacked: { flexDirection: 'column' },
  card: {
    flex: 1, minHeight: 132, borderRadius: 20, borderWidth: 1.5, borderColor: SA.line, backgroundColor: SA.card,
    paddingHorizontal: 16, paddingTop: 18, paddingBottom: 16,
  },
  cardGap: { marginLeft: 12 },
  cardStacked: { flex: 0, marginBottom: 20 },
  cardOn: { borderColor: SA.deep, borderWidth: 2, backgroundColor: SA.mint },
  pressed: { opacity: 0.8 },
  badge: {
    position: 'absolute', top: -12, left: 14, maxWidth: '90%', minHeight: 24, borderRadius: 12, paddingHorizontal: 10,
    justifyContent: 'center', backgroundColor: SA.mint, borderWidth: 1, borderColor: SA.mintLine,
  },
  badgeOn: { backgroundColor: SA.deep, borderColor: SA.deep },
  badgeText: { fontSize: 12, fontWeight: '700', color: SA.deep },
  badgeTextOn: { color: SA.onDeep },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 24 },
  name: { fontSize: 16, fontWeight: '700', color: SA.text, flexShrink: 1 },
  radio: {
    width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: SA.faint,
    alignItems: 'center', justifyContent: 'center', marginLeft: 8,
  },
  radioOn: { backgroundColor: SA.deep, borderColor: SA.deep },
  price: { fontSize: 26, fontWeight: '700', color: SA.text, marginTop: 12 },
  per: { fontSize: 14, color: SA.muted, marginTop: 1 },
  note: { fontSize: 14, fontWeight: '600', color: SA.mintText, marginTop: 8 },
  next: { fontSize: 12, lineHeight: 17, color: SA.muted, marginTop: 6 },
});
