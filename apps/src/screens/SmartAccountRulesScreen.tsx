// Cuenta inteligente: the rules list (spec 8.2 "Automation").
//
// Each rule is one row that answers four things without opening it: what it
// does and for how much (the title), how often, when it runs next, and, if
// the last run did not happen, why. "Nueva regla" is pinned; the kinds it
// offers are the ones the server says exist for this person (bank payments
// only where a rail is live).
import React, { useEffect, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import {
  ActionButton, Empty, IconDisc, LoadError, Notice, Row, RowsSkeleton, Sheet, SmartScreen, kitStyles,
} from '../components/smartAccount/kit';
import { HELP_RULES } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { cardPeriodDays, cardPeriodLabel, frequencyLabel, railsPhrase, ruleTitle, shortDate } from '../components/smartAccount/format';
import { useRailLabels } from '../components/smartAccount/useRailLabels';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { fetchSmartAccount, fetchSmartAccountOffer, isEditableRuleKind, type SmartAccountRule } from '../services/smartAccount';

export const RULE_ICONS: Record<string, string> = { send: 'send', payout: 'home', buy: 'trending-up', card: 'credit-card' };

export function ruleSubtitle(rule: SmartAccountRule): string {
  if (rule.kind === 'card') {
    // Pulled by the card when you pay with it: a limit per period, no runs.
    return rule.active ? `Límite ${cardPeriodLabel(cardPeriodDays(rule.frequency))}` : 'detenida';
  }
  if (!isEditableRuleKind(rule.kind)) {
    return rule.active ? 'activa' : 'detenida';
  }
  const parts = [frequencyLabel(rule.frequency)];
  if (!rule.active) {
    parts.push('detenida');
  } else if (rule.nextRunAt) {
    parts.push(`próxima: ${shortDate(rule.nextRunAt)}`);
  }
  return parts.join(' · ');
}

/**
 * Run-side reasons (smart_account automation/payouts) for when the server
 * gives a run its code but no sentence. The server writes a Spanish message
 * today; a bare code in its place is translated, never shown raw.
 */
export const RULE_RUN_COPY: Record<string, string> = {
  authorization_mismatch: 'Esta regla se detuvo porque cambió. Créala de nuevo para confirmar con tu rostro.',
  review_amount_cap: 'No se ejecutó porque el monto supera el límite de tu cuenta. Edita la regla con un monto menor.',
};

const BARE_CODE = /^[a-z][a-z0-9_]{0,63}$/;

export function ruleNote(rule: SmartAccountRule & { lastRunReason?: string | null }): string | undefined {
  if (rule.lastRunStatus === 'skipped' || rule.lastRunStatus === 'failed') {
    const message = (rule.lastRunMessage || '').trim();
    if (message && !BARE_CODE.test(message)) {
      return message;
    }
    const code = message || rule.lastRunReason || '';
    return RULE_RUN_COPY[code]
      || (rule.lastRunStatus === 'skipped' ? 'La última vez no se ejecutó.' : 'La última vez no se pudo completar.');
  }
  return undefined;
}

/** The bank-rule choice: a Pago Móvil account can be added on the next screen. */
export function payoutKindSubtitle(rails: string[]): string {
  const names = railsPhrase(rails, ',');
  return rails.includes('ve_pagomovil')
    ? `A una cuenta guardada o a una Pago Móvil que agregues: ${names}.`
    : `A una cuenta que ya guardaste: ${names}.`;
}

export function SmartAccountRulesScreen() {
  const navigation = useNavigation<any>();
  const account = useSmartRead(fetchSmartAccount);
  const offer = useSmartRead(fetchSmartAccountOffer);
  useRailLabels();
  const [choosing, setChoosing] = useState(false);

  useEffect(() => {
    const unsubscribe = navigation.addListener?.('focus', () => { void account.reload(); });
    return typeof unsubscribe === 'function' ? unsubscribe : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigation]);

  const rules = account.data?.rules ?? [];
  const paused = !!account.data?.billing && account.data.billing.status !== 'current';
  const rails = offer.data?.payoutRails ?? [];
  const loading = account.loading && !account.data;
  const failed = account.failed && !account.data;

  const create = (kind: 'send' | 'payout' | 'buy') => {
    setChoosing(false);
    navigation.navigate('SmartAccountRuleEdit', { kind });
  };

  return (
    <SmartScreen
      title="Reglas"
      help={HELP_RULES}
      scroll={false}
      footer={!loading && !failed ? (
        <ActionButton label="Nueva regla" icon="plus" onPress={() => setChoosing(true)} testID="rules-new" />
      ) : undefined}
    >
      {loading ? (
        <View style={kitStyles.pad}><RowsSkeleton rows={3} /></View>
      ) : failed ? (
        <LoadError onRetry={account.reload} busy={account.loading} />
      ) : (
        <FlatList
          data={rules}
          keyExtractor={(item) => String(item.id)}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          // No getItemLayout: a row grows with the system font size (the
          // title, subtitle and run note wrap), so its height is not fixed.
          // No onEndReached: the account read returns every rule at once.
          contentContainerStyle={styles.list}
          refreshControl={(
            <RefreshControl refreshing={account.loading} onRefresh={account.reload} tintColor={SA.deep} colors={[SA.deep]} />
          )}
          ListHeaderComponent={paused ? (
            <Notice
              tone="notice"
              icon="pause-circle"
              title="Tus reglas están en pausa"
              body="Vuelven a ejecutarse cuando tu plan esté al día."
              actionLabel="Ver mi plan"
              onPress={() => navigation.navigate('SmartAccountBilling')}
              style={styles.notice}
            />
          ) : null}
          ListEmptyComponent={(
            <Empty
              icon="repeat"
              title="Aún no tienes reglas"
              body="Crea una y tu cuenta la repite por ti: enviar, pagar o invertir."
            />
          )}
          renderItem={({ item }) => (
            <View style={styles.rowBox}>
              <Row
                left={<IconDisc icon={RULE_ICONS[item.kind] ?? 'repeat'} tone={item.active ? 'mint' : 'neutral'} />}
                title={ruleTitle(item)}
                subtitle={ruleSubtitle(item)}
                note={ruleNote(item)}
                onPress={() => navigation.navigate('SmartAccountRuleEdit', { ruleId: String(item.id) })}
                chevron
                testID={`rule-${item.id}`}
              />
            </View>
          )}
        />
      )}

      <Sheet visible={choosing} onClose={() => setChoosing(false)} title="¿Qué quieres automatizar?">
        <Row
          left={<IconDisc icon={RULE_ICONS.send} />}
          title="Enviar a alguien de Confío"
          subtitle="A tu familia o a quien tú elijas."
          onPress={() => create('send')}
          chevron
          testID="new-send"
        />
        {rails.length > 0 ? (
          <Row
            divider
            left={<IconDisc icon={RULE_ICONS.payout} />}
            title="Pagar a una cuenta bancaria"
            subtitle={payoutKindSubtitle(rails)}
            onPress={() => create('payout')}
            chevron
            testID="new-payout"
          />
        ) : null}
        <Row
          divider
          left={<IconDisc icon={RULE_ICONS.buy} />}
          title="Invertir automáticamente"
          subtitle="Compra un poco cada cierto tiempo."
          onPress={() => create('buy')}
          chevron
          testID="new-buy"
        />
      </Sheet>
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  list: { paddingTop: 8, paddingBottom: 24 },
  notice: { marginHorizontal: 16, marginTop: 8 },
  rowBox: { marginHorizontal: 16, marginTop: 8, paddingHorizontal: 16, backgroundColor: SA.card, borderRadius: 16 },
});
