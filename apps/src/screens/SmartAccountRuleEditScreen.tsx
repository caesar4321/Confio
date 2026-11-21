// Cuenta inteligente: create or change one rule (spec 8.2 "Automation").
//
// Three kinds, one form: where the money goes, how much, how often. Under the
// form the rule is written out as one sentence, so what gets signed can be
// read back in plain words. The signature binds exactly that: Confío can only
// run this rule as written.
//
//   send    -> someone on Confío (contacts or @usuario; the server resolves)
//   payout  -> a bank destination the viewer already saved, on a rail the
//              server lists. The dollar amount is fixed; the local-currency
//              amount follows the day's rate, and the screen says so.
//   buy     -> a stock, or bitcoin / gold where this build and the server
//              both offer them (iOS builds compile without those surfaces).
//
// Confío IA+ (spec decision 34) opens this screen with a proposal: `prefill`
// fills the form (every field stays editable), `stop` opens the stop
// confirmation of `ruleId`, and `next` holds the proposal's further steps,
// opened one after another once this one is signed. Params are data from the
// server, never authority: the prepare re-validates everything.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, View } from 'react-native';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { Text, TextInput } from '../components/common/AppText';
import { AmountField } from '../components/smartAccount/AmountField';
import { AssetMark } from '../components/smartAccount/AssetMark';
import { ConfioContactPicker, type PickedPerson } from '../components/smartAccount/ConfioContactPicker';
import {
  ActionButton, Card, Chip, Empty, IconDisc, LoadError, Notice, Row, RowsSkeleton, ScreenSkeleton, SectionTitle,
  Sheet, SmartScreen, kitStyles,
} from '../components/smartAccount/kit';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { useRailLabels } from '../components/smartAccount/useRailLabels';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_RULES } from '../components/smartAccount/help';
import { SA, HIT } from '../components/smartAccount/tokens';
import {
  cardPeriodDays, cardPeriodLabel, centsToDecimal, centsToInput, cryptoBuyAllowed, frequencyEvery, frequencyLabel, railLabel,
  railsPhrase, ruleTitle, shortDate, toCents, typedCents, usd,
} from '../components/smartAccount/format';
import {
  SMART_FREQUENCIES, fetchSmartAccount, fetchSmartAccountBuyableAssets, fetchSmartAccountCardRules, fetchSmartAccountOffer,
  fetchSmartAccountPayoutMethods, isEditableRuleKind, prepareSmartAccountBuyRule, prepareSmartAccountCancelRule,
  prepareSmartAccountPayoutRule, prepareSmartAccountSendRule,
  type SmartAccountBuyableAsset, type SmartAccountPayoutMethod, type SmartAccountRule, type SmartFrequency, type SmartRuleKind,
} from '../services/smartAccount';
import type { MainStackParamList } from '../types/navigation';
import { DEX_TRADING_UI_ENABLED } from '../config/features';
import { PagoMovilDestinationForm } from '../components/smartAccount/PagoMovilDestinationForm';

/** The rail whose destination can be added right here (Venezuela). */
export const PAGO_MOVIL_RAIL = 've_pagomovil';

/**
 * Why there is no bank account to pick, and where to get one: a Pago Móvil
 * account is added here; the other rails' accounts are saved from Enviar.
 */
export function payoutEmptyCopy(rails: string[]): string {
  if (rails.length === 0) {
    return 'Los pagos automáticos a cuenta bancaria todavía no están disponibles para ti.';
  }
  if (!rails.includes(PAGO_MOVIL_RAIL)) {
    return `Guarda primero una cuenta ${railsPhrase(rails)} desde Enviar. Después podrás pagarle de forma automática.`;
  }
  const others = rails.filter((r) => r !== PAGO_MOVIL_RAIL);
  return others.length > 0
    ? `Agrega aquí una cuenta Pago Móvil. Las cuentas ${railsPhrase(others)} se guardan desde Enviar.`
    : 'Agrega una cuenta Pago Móvil y podrás pagarle de forma automática.';
}

/** The pending-step notice: the IA+ sentence only when there is a plan to go back to. */
export const pendingStepBody = (fromProposal: boolean): string => (fromProposal
  ? 'No lo repitas. Cuando aparezca en tus reglas, vuelve a abrir la propuesta de Confío IA+ para seguir con el resto del plan.'
  : 'No lo repitas. Cuando aparezca en tus reglas, ya está lista.');

const TITLES: Record<SmartRuleKind, string> = {
  send: 'Enviar a alguien',
  payout: 'Pagar a una cuenta',
  buy: 'Invertir',
};

const ASSET_ROW = 68;

// Bitcoin and gold are offered only where the build AND the server say so
// (shared with the offer, which must not promise them either).
export { cryptoBuyAllowed };

// Why a bitcoin / gold buy cannot be signed. A build without those surfaces
// (iOS) never names them; otherwise the server / country gate says so.
export const cryptoBlockedMessage = (dexUi: boolean = DEX_TRADING_UI_ENABLED): string => (dexUi
  ? 'Oro y Bitcoin no están disponibles para tu cuenta. Elige otra inversión.'
  : 'Esa inversión no está disponible en esta versión de la app. Elige otra.');

function BuyAssetPicker({ visible, allowCrypto, onClose, onPick }: {
  visible: boolean; allowCrypto: boolean; onClose: () => void; onPick: (asset: SmartAccountBuyableAsset) => void;
}) {
  const insets = useSafeAreaInsets();
  const [search, setSearch] = useState('');
  const [items, setItems] = useState<SmartAccountBuyableAsset[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const seq = useRef(0);
  const loadingMore = useRef(false);
  const [fetchingMore, setFetchingMore] = useState(false);
  // Pages fetched in a row that showed nothing (crypto filtered out here).
  const emptyRun = useRef(0);

  const load = useCallback(async (text: string) => {
    const mine = ++seq.current;
    setState('loading');
    const result = await fetchSmartAccountBuyableAssets({ search: text.trim() || undefined, first: 30 });
    if (mine !== seq.current) {
      return;
    }
    if (!result.ok) {
      setState('failed');
      return;
    }
    emptyRun.current = 0;
    setItems(result.data.items);
    setCursor(result.data.endCursor);
    setMore(result.data.hasNextPage);
    setState('ready');
  }, []);

  useEffect(() => {
    if (!visible) {
      return;
    }
    const timer = setTimeout(() => { void load(search); }, search ? 300 : 0);
    return () => clearTimeout(timer);
  }, [visible, search, load]);

  const loadMore = async () => {
    if (!more || !cursor || loadingMore.current || state !== 'ready') {
      return;
    }
    loadingMore.current = true;
    setFetchingMore(true);
    const mine = seq.current;
    const result = await fetchSmartAccountBuyableAssets({ search: search.trim() || undefined, first: 30, after: cursor });
    loadingMore.current = false;
    setFetchingMore(false);
    if (mine !== seq.current || !result.ok) {
      return;
    }
    const visibleNew = allowCrypto ? result.data.items : result.data.items.filter((a) => a.kind !== 'crypto');
    emptyRun.current = visibleNew.length === 0 ? emptyRun.current + 1 : 0;
    setItems((prev) => {
      const seen = new Set(prev.map((p) => p.assetKey));
      return [...prev, ...result.data.items.filter((n) => !seen.has(n.assetKey))];
    });
    setCursor(result.data.endCursor);
    setMore(result.data.hasNextPage);
  };

  const shown = useMemo(
    () => (allowCrypto ? items : items.filter((a) => a.kind !== 'crypto')),
    [items, allowCrypto],
  );

  // Crypto is filtered out on this device: a page can come back with nothing
  // to show while the server has more. Keep fetching on its own (a few pages
  // in a row at most), then offer a manual "Buscar más"; never "Sin
  // resultados" while more pages exist.
  const AUTO_PAGES = 5;
  useEffect(() => {
    if (visible && state === 'ready' && more && shown.length < 10 && emptyRun.current < AUTO_PAGES) {
      void loadMore();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, state, more, cursor, shown.length]);

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={[styles.modal, { paddingTop: insets.top }]}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.modalHeader}>
          <Pressable onPress={onClose} style={styles.modalClose} hitSlop={6} accessibilityRole="button" accessibilityLabel="Cerrar">
            <Icon name="x" size={24} color={SA.text} />
          </Pressable>
          <Text style={styles.modalTitle} accessibilityRole="header">¿En qué inviertes?</Text>
        </View>
        <View style={styles.search}>
          <Icon name="search" size={18} color={SA.muted} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="Buscar"
            placeholderTextColor={SA.faint}
            autoCorrect={false}
            style={styles.searchInput}
            accessibilityLabel="Buscar una inversión"
          />
        </View>
        {state === 'loading' && items.length === 0 ? (
          <View style={kitStyles.pad}><RowsSkeleton rows={5} /></View>
        ) : state === 'failed' ? (
          <LoadError onRetry={() => { void load(search); }} />
        ) : (
          <FlatList
            data={shown}
            keyExtractor={(item) => item.assetKey}
            keyboardShouldPersistTaps="handled"
            initialNumToRender={20}
            maxToRenderPerBatch={10}
            windowSize={21}
            getItemLayout={(_, index) => ({ length: ASSET_ROW, offset: ASSET_ROW * index, index })}
            onEndReached={() => { void loadMore(); }}
            onEndReachedThreshold={0.5}
            contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}
            ListEmptyComponent={more ? (
              fetchingMore ? (
                <View style={kitStyles.pad}><RowsSkeleton rows={3} /></View>
              ) : (
                <Empty
                  icon="search"
                  title="Seguimos buscando"
                  body="Hay más inversiones por revisar."
                  actionLabel="Buscar más"
                  onAction={() => { emptyRun.current = 0; void loadMore(); }}
                />
              )
            ) : <Empty icon="search" title="Sin resultados" body="Prueba con otro nombre." />}
            renderItem={({ item }) => (
              <Pressable
                onPress={() => onPick(item)}
                style={({ pressed }) => [styles.assetRow, pressed && styles.pressed]}
                accessibilityRole="button"
                accessibilityLabel={`${item.name}, ${item.symbol}`}
              >
                <AssetMark asset={{ key: item.assetKey, kind: item.kind, symbol: item.symbol }} />
                <View style={styles.assetText}>
                  <Text style={styles.assetName} numberOfLines={1}>{item.name}</Text>
                  <Text style={styles.assetSymbol} numberOfLines={1}>{item.symbol}</Text>
                </View>
                <Icon name="chevron-right" size={20} color={SA.faint} />
              </Pressable>
            )}
          />
        )}
      </KeyboardAvoidingView>
    </Modal>
  );
}

// Opening this screen while it is already focused (another Confío IA+
// proposal, the next rule) only swaps its params. Every new params object is
// a new proposal or rule: it gets a fresh form, never the previous one's
// person, amount, pending step or stop confirmation.
export function SmartAccountRuleEditScreen() {
  const route = useRoute<RouteProp<MainStackParamList, 'SmartAccountRuleEdit'>>();
  const params = route.params;
  const generation = useRef<{ params: unknown; n: number }>({ params, n: 0 });
  if (generation.current.params !== params) {
    generation.current = { params, n: generation.current.n + 1 };
  }
  return <RuleEditForm key={generation.current.n} />;
}

function RuleEditForm() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'SmartAccountRuleEdit'>>();
  const ruleId = route.params?.ruleId ?? null;
  const prefill = route.params?.prefill;
  const nextSteps = route.params?.next ?? [];

  const account = useSmartRead(fetchSmartAccount);
  const offer = useSmartRead(fetchSmartAccountOffer);
  useRailLabels();
  const existing = ruleId ? (account.data?.rules ?? []).find((r) => String(r.id) === ruleId) ?? null : null;
  // A card allowance (decision 35) or a kind this build does not know: shown
  // read-only, with only "Detener esta regla". Never opened as another kind.
  const readOnly = !!existing && !isEditableRuleKind(existing.kind);
  const kind = (readOnly ? 'send' : (existing?.kind ?? route.params?.kind ?? 'send')) as SmartRuleKind;
  const methods = useSmartRead(fetchSmartAccountPayoutMethods, { skip: readOnly || kind !== 'payout' });
  const cardRules = useSmartRead(fetchSmartAccountCardRules, { skip: existing?.kind !== 'card' });
  const flow = useSignFlow();
  const [stopping, setStopping] = useState(false);

  const [person, setPerson] = useState<PickedPerson | null>(() => (prefill?.payeeHandle
    ? { handle: prefill.payeeHandle, name: prefill.payeeName || `@${prefill.payeeHandle.replace(/^@/, '')}` }
    : null));
  const [method, setMethod] = useState<SmartAccountPayoutMethod | null>(null);
  const [asset, setAsset] = useState<SmartAccountBuyableAsset | null>(() => (prefill?.assetKey
    ? {
      assetKey: prefill.assetKey,
      kind: prefill.assetKey.startsWith('crypto:') ? 'crypto' : 'stock',
      symbol: prefill.assetName || prefill.assetKey.replace(/^[a-z]+:/, ''),
      name: prefill.assetName || prefill.assetKey.replace(/^[a-z]+:/, ''),
    }
    : null));
  const [amount, setAmount] = useState<string | null>(() => {
    const c = toCents(prefill?.amountUsd);
    return c !== null ? centsToInput(c) : null;
  });
  const [frequency, setFrequency] = useState<SmartFrequency | null>(prefill?.frequency ?? null);
  const [firstRunAt, setFirstRunAt] = useState<string | null>(prefill?.firstRunAt ?? null);
  const stopOpened = useRef(false);
  const [picker, setPicker] = useState(false);
  // The payout picker shows the "Agregar cuenta Pago Móvil" form instead of the list.
  const [addingPagoMovil, setAddingPagoMovil] = useState(false);
  const [touched, setTouched] = useState(false);
  // A step of a multi-step proposal whose outcome is still unknown: the rest
  // of the plan must not open on top of it (it may not have gone through).
  const [pendingStep, setPendingStepState] = useState(false);
  const pendingRef = useRef(false);
  const setPendingStep = (v: boolean) => {
    pendingRef.current = v;
    setPendingStepState(v);
  };
  // A stop proposal is signed with "Detener esta regla", never as an update.
  const stopProposal = !!route.params?.stop;
  // The Confío IA+ proposal step this screen signs (message id + stepIndex):
  // sent with this step's own prepare only, never when unset.
  const proposalMessageId = route.params?.proposalMessageId;
  const proposalStep = route.params?.proposalStep;
  const proposalTag = proposalMessageId && typeof proposalStep === 'number'
    ? { proposalMessageId, proposalStep }
    : null;

  const rails = offer.data?.payoutRails ?? [];
  const usableMethods = useMemo(
    () => (methods.data ?? []).filter((m) => rails.includes(m.rail)),
    [methods.data, rails],
  );
  const allowCrypto = cryptoBuyAllowed(offer.data?.investingCryptoEnabled);
  // A bitcoin / gold buy where this build or the server does not offer them:
  // never signed; the owner picks another investment. Either a proposed /
  // picked asset, or (none picked) the existing rule's own crypto asset, e.g.
  // opened from the Rules list or an amount-only update proposal.
  const cryptoBlocked = kind === 'buy' && !allowCrypto && (asset
    ? asset.kind === 'crypto'
    : !!existing?.assetKey?.startsWith('crypto:'));
  const pickedAsset = cryptoBlocked ? null : asset;

  // A proposed bank account is picked once the saved list is known (only one
  // that is the viewer's and usable here).
  useEffect(() => {
    if (!method && prefill?.payoutMethodId) {
      const found = usableMethods.find((m) => m.payoutMethodId === prefill.payoutMethodId && m.available);
      if (found) {
        setMethod(found);
      }
    }
  }, [method, prefill?.payoutMethodId, usableMethods]);

  // A proposed bank account must be the one signed, never silently swapped
  // for the rule's current one. Once the saved list is known and it is not
  // there (deleted, rail off), the owner picks a destination explicitly.
  const proposedMethodId = kind === 'payout' ? prefill?.payoutMethodId : undefined;
  const proposedGone = !!proposedMethodId && !method && !!methods.data && !!offer.data
    && !usableMethods.some((m) => m.payoutMethodId === proposedMethodId && m.available);
  // The proposal's sentence names its account: shown only while that account
  // is the one selected.
  const proposalMatchesForm = !cryptoBlocked && (!proposedMethodId || method?.payoutMethodId === proposedMethodId);

  // An existing rule fills the form until the user changes a field.
  const destination: { label: string; sub?: string } | null = (() => {
    if (kind === 'send') {
      if (person) { return { label: person.name }; }
      if (existing?.payeeHandle) { return { label: existing.payeeName || `@${existing.payeeHandle.replace(/^@/, '')}` }; }
      return null;
    }
    if (kind === 'payout') {
      if (method) { return { label: method.label, sub: `${railLabel(method.rail)} · ${method.holderName}` }; }
      if (existing?.payoutMethodId && !proposedMethodId) { return { label: existing.payoutLabel || railLabel(existing.payoutRail) }; }
      return null;
    }
    if (cryptoBlocked) { return null; }
    if (pickedAsset) { return { label: pickedAsset.name, sub: pickedAsset.symbol }; }
    if (existing?.assetKey) { return { label: existing.assetName || existing.assetSymbol || '' , sub: existing.assetSymbol || undefined }; }
    return null;
  })();

  const existingCents = toCents(existing?.amountUsd);
  const text = amount ?? (existingCents !== null ? centsToInput(existingCents) : '');
  const cents = typedCents(text);
  const freq = (frequency ?? (existing?.frequency as SmartFrequency | undefined) ?? 'monthly');
  // A daily rule has no start day (the server refuses one).
  const startAt = freq === 'daily' ? null : firstRunAt;
  const amountError = cents === null || cents <= 0n ? 'Escribe un monto.' : '';
  const destinationError = cryptoBlocked
    ? cryptoBlockedMessage()
    : proposedGone
    ? 'Esa cuenta ya no está disponible. Elige un destino.'
    : destination ? '' : 'Elige un destino.';
  const amountUsd = cents !== null ? centsToDecimal(cents) : '';

  const sentence = destination && cents !== null && cents > 0n
    ? kind === 'buy'
      ? `Tu cuenta invierte ${usd(amountUsd)} en ${destination.label} ${frequencyEvery(freq)}.`
      : `Tu cuenta ${kind === 'send' ? 'envía' : 'paga'} ${usd(amountUsd)} a ${destination.label} ${frequencyEvery(freq)}.`
    : '';

  const onReview = () => {
    setTouched(true);
    if (readOnly || pendingRef.current || stopProposal || amountError || destinationError || cents === null) {
      return;
    }
    setStopping(false);
    void flow.start({
      // A send or bank payment rule moves money to someone else with nobody
      // present: the server asks Confío Face, as for a personal send.
      faceStepUp: kind === 'send' || kind === 'payout',
      prepare: () => {
        if (kind === 'send') {
          return prepareSmartAccountSendRule({
            ruleId, payeeHandle: person?.handle ?? existing?.payeeHandle ?? '', amountUsd, frequency: freq, firstRunAt: startAt,
            ...proposalTag,
          });
        }
        if (kind === 'payout') {
          return prepareSmartAccountPayoutRule({
            ruleId, payoutMethodId: method?.payoutMethodId ?? existing?.payoutMethodId ?? '', amountUsd, frequency: freq,
            firstRunAt: startAt, ...proposalTag,
          });
        }
        return prepareSmartAccountBuyRule({
          ruleId, assetKey: pickedAsset?.assetKey ?? existing?.assetKey ?? '', amountUsd, frequency: freq, firstRunAt: startAt,
          ...proposalTag,
        });
      },
    });
  };

  const onStop = () => {
    // A step whose outcome is unknown: nothing else is signed on top of it.
    if (!ruleId || pendingRef.current) {
      return;
    }
    setStopping(true);
    // Tagged only when this step IS the proposal's stop (not a manual
    // "Detener esta regla" on an update step).
    const stopTag = stopProposal ? proposalTag : null;
    void flow.start({
      prepare: () => (stopTag ? prepareSmartAccountCancelRule(ruleId, stopTag) : prepareSmartAccountCancelRule(ruleId)),
    });
  };

  // A "detener / pausar" proposal opens the stop confirmation once the rule is known.
  useEffect(() => {
    if (route.params?.stop && existing && !stopOpened.current) {
      stopOpened.current = true;
      onStop();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.params?.stop, existing]);

  // The proposal's next step, carrying its own params (and proposal tags).
  const openNextStep = () => {
    const [following, ...rest] = nextSteps;
    navigation.replace('SmartAccountRuleEdit', rest.length ? { ...following, next: rest } : following);
  };

  // After a signed step, the proposal's next step (if any), else back.
  const afterSigned = () => {
    if (pendingRef.current) {
      return;  // the rest of the plan never opens over an unconfirmed step
    }
    if (nextSteps.length > 0) {
      openNextStep();
      return;
    }
    navigation.goBack();
  };

  // This step's rule is still confirming (signed earlier, not on chain yet):
  // the screen turns into the pending-step notice, so nothing else of the
  // plan is signed on top of it.
  const duplicatePending = flow.state.phase === 'failed' && flow.state.errorCode === 'rule_duplicate_pending';
  useEffect(() => {
    if (duplicatePending && !pendingRef.current) {
      setPendingStep(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [duplicatePending]);

  // This step was refused as a duplicate of an ACTIVE rule: nothing to sign
  // here, so the owner moves on with the plan, or to their rules when this
  // was the last step. Never over an unconfirmed step, and only for this one
  // refusal.
  const duplicateAction = duplicatePending
    ? { label: 'Ir a tus reglas', onPress: () => navigation.popTo('SmartAccountRules'), testID: 'rule-duplicate-pending-rules' }
    : flow.state.phase === 'failed' && flow.state.errorCode === 'rule_duplicate' && !pendingStep
    ? nextSteps.length > 0
      ? {
        label: 'Seguir con el plan',
        onPress: () => { if (!pendingRef.current) { openNextStep(); } },
        testID: 'rule-duplicate-continue',
      }
      : { label: 'Ir a tus reglas', onPress: () => navigation.popTo('SmartAccountRules'), testID: 'rule-duplicate-rules' }
    : null;

  // An unknown outcome on a step with more to come: stay here, never open the
  // next step on top of one that may not have gone through.
  const afterUnknown = nextSteps.length > 0 ? () => setPendingStep(true) : undefined;

  // A rule saved from an alert's prepared purchase (or any proposed buy): it
  // repeats, so say so plainly.
  const proposedBuy = kind === 'buy' && !existing && !!route.params?.proposal;

  const loading = (!!ruleId && account.loading && !account.data) || (offer.loading && !offer.data);
  const failed = (!!ruleId && account.failed && !account.data) || (offer.failed && !offer.data);
  const missingRule = !!ruleId && !!account.data && !existing;
  // Only when CREATING: an existing payout rule always keeps its form and
  // "Detener esta regla", even if no bank method is usable today.
  const noMethods = !ruleId && kind === 'payout' && !methods.loading && !methods.failed && usableMethods.length === 0
    && !method;
  const canAddPagoMovil = rails.includes(PAGO_MOVIL_RAIL);
  const openAddPagoMovil = () => {
    setAddingPagoMovil(true);
    setPicker(true);
  };
  const closePicker = () => {
    setPicker(false);
    setAddingPagoMovil(false);
  };
  const onPagoMovilSaved = (saved: SmartAccountPayoutMethod) => {
    if (saved.available) {
      setMethod(saved);
    }
    closePicker();
    void methods.reload();
  };

  return (
    <SmartScreen
      title={existing ? 'Tu regla' : TITLES[kind]}
      help={HELP_RULES}
      footer={!loading && !failed && !missingRule && !noMethods && !pendingStep && !stopProposal && !cryptoBlocked && !readOnly ? (
        <ActionButton label="Revisar" onPress={onReview} testID="rule-review" />
      ) : undefined}
    >
      {loading ? <ScreenSkeleton /> : failed ? (
        <LoadError onRetry={() => { void account.reload(); void offer.reload(); }} />
      ) : missingRule ? (
        <Empty icon="repeat" title="Esta regla ya no existe" actionLabel="Volver" onAction={() => navigation.goBack()} />
      ) : readOnly && existing ? (
        <ReadOnlyRule
          rule={existing}
          card={(cardRules.data ?? []).find((c) => c.ruleId === String(existing.id)) ?? null}
          pending={pendingStep}
          onStop={onStop}
        />
      ) : noMethods ? (
        <Empty
          icon="home"
          title="Aún no guardaste una cuenta bancaria"
          body={payoutEmptyCopy(rails)}
          actionLabel={canAddPagoMovil ? 'Agregar cuenta Pago Móvil' : undefined}
          onAction={canAddPagoMovil ? openAddPagoMovil : undefined}
        />
      ) : (
        <View style={kitStyles.pad}>
          {pendingStep ? (
            <Notice
              icon="clock"
              tone="notice"
              title="Este paso todavía se está confirmando"
              body={pendingStepBody(!!route.params?.proposal || nextSteps.length > 0)}
              actionLabel="Ir a tus reglas"
              onPress={() => navigation.popTo('SmartAccountRules')}
              style={styles.proposal}
              testID="rule-step-pending"
            />
          ) : route.params?.proposal ? (
            <Notice
              icon="message-circle"
              title={nextSteps.length > 0 ? `Propuesta de Confío IA+ · quedan ${nextSteps.length} más` : 'Propuesta de Confío IA+'}
              body={proposalMatchesForm
                ? `${route.params.proposal} Revisa y cambia lo que quieras: nada cambia hasta que firmes.`
                : 'Revisa y cambia lo que quieras: nada cambia hasta que firmes.'}
              style={styles.proposal}
              testID="rule-proposal"
            />
          ) : null}
          {existing && existing.nextRunAt && existing.active ? (
            <Notice icon="calendar" body={`Próxima ejecución: ${shortDate(existing.nextRunAt)}`} style={styles.next} />
          ) : null}

          <SectionTitle>¿A dónde va el dinero?</SectionTitle>
          <Card>
            <Row
              left={<IconDisc icon={kind === 'send' ? 'user' : kind === 'payout' ? 'home' : 'trending-up'} tone={destination ? 'mint' : 'neutral'} />}
              title={destination?.label || (kind === 'send' ? 'Elegir persona' : kind === 'payout' ? 'Elegir cuenta bancaria' : 'Elegir inversión')}
              subtitle={destination?.sub}
              onPress={() => setPicker(true)}
              chevron
              accessibilityLabel={destination ? `Destino: ${destination.label}. Cambiar` : 'Elegir destino'}
              testID="rule-destination"
            />
          </Card>
          {(touched || proposedGone || cryptoBlocked) && destinationError ? (
            <Text style={styles.fieldError} testID="rule-destination-error">{destinationError}</Text>
          ) : null}

          <SectionTitle>¿Cuánto?</SectionTitle>
          <AmountField
            label="Monto de cada vez"
            value={text}
            onChange={setAmount}
            error={touched ? amountError : ''}
            hint="Sale de los dólares de tu Cuenta inteligente."
            testID="rule-amount"
          />

          <SectionTitle>¿Cada cuánto?</SectionTitle>
          <View style={styles.chips} accessibilityRole="radiogroup">
            {SMART_FREQUENCIES.map((f) => (
              <Chip key={f} label={frequencyLabel(f)} selected={freq === f} onPress={() => setFrequency(f)} />
            ))}
          </View>

          {startAt ? (
            <Notice
              icon="calendar"
              body={`Primera ejecución: ${shortDate(startAt)}`}
              actionLabel="Quitar"
              onPress={() => setFirstRunAt(null)}
              style={styles.gap}
              testID="rule-first-run"
            />
          ) : null}

          {kind === 'payout' ? (
            <Notice
              icon="info"
              body="El monto en dólares es fijo. Lo que llega en moneda local depende del tipo de cambio de ese día."
              style={styles.gap}
              testID="payout-fx-note"
            />
          ) : null}

          {sentence ? (
            <Card flat style={styles.sentence}>
              <Text style={styles.sentenceText}>{sentence}</Text>
              <Text style={kitStyles.small}>Si un día no alcanza el saldo, esa vez se omite y te avisamos.</Text>
            </Card>
          ) : null}

          {existing && !pendingStep ? (
            <ActionButton label="Detener esta regla" variant="danger" onPress={onStop} style={styles.stop} testID="rule-stop" />
          ) : null}
        </View>
      )}

      {kind === 'send' && !readOnly ? (
        <ConfioContactPicker
          visible={picker}
          title="¿A quién le envías?"
          onClose={() => setPicker(false)}
          onPick={(p) => { setPerson(p); setPicker(false); }}
        />
      ) : null}
      {kind === 'payout' && !readOnly ? (
        <Sheet
          visible={picker}
          onClose={closePicker}
          title={addingPagoMovil ? 'Agregar cuenta Pago Móvil' : 'Tus cuentas guardadas'}
        >
          {addingPagoMovil ? (
            <PagoMovilDestinationForm onSaved={onPagoMovilSaved} onCancel={() => setAddingPagoMovil(false)} />
          ) : methods.loading && !methods.data ? <RowsSkeleton rows={2} /> : methods.failed && !methods.data ? (
            <LoadError onRetry={methods.reload} />
          ) : usableMethods.length === 0 ? (
            <Text style={kitStyles.small} testID="payout-no-methods">{payoutEmptyCopy(rails)}</Text>
          ) : usableMethods.map((m, i) => (
            <Row
              key={m.payoutMethodId}
              divider={i > 0}
              left={<IconDisc icon="home" tone={m.available ? 'mint' : 'neutral'} />}
              title={m.label}
              subtitle={`${railLabel(m.rail)} · ${m.holderName}`}
              note={m.available ? undefined : 'Todavía no admite pagos automáticos.'}
              onPress={m.available ? () => { setMethod(m); setPicker(false); } : undefined}
              chevron
            />
          ))}
          {!addingPagoMovil && canAddPagoMovil && !(methods.loading && !methods.data) ? (
            <Row
              divider={usableMethods.length > 0}
              left={<IconDisc icon="plus" tone="mint" />}
              title="Agregar cuenta Pago Móvil"
              subtitle="Banco, teléfono y cédula de quien recibe."
              onPress={() => setAddingPagoMovil(true)}
              chevron
              testID="payout-add-pagomovil"
            />
          ) : null}
        </Sheet>
      ) : null}
      {kind === 'buy' && !readOnly ? (
        <BuyAssetPicker
          visible={picker}
          allowCrypto={allowCrypto}
          onClose={() => setPicker(false)}
          onPick={(a) => { setAsset(a); setPicker(false); }}
        />
      ) : null}

      <SignFlowSheet
        flow={flow}
        copy={stopping ? {
          confirmTitle: 'Detener la regla',
          confirmLabel: 'Firmar y detener',
          signingMessage: 'Deteniendo la regla…',
          successTitle: 'Regla detenida',
          successBody: 'No se va a ejecutar más.',
        } : {
          confirmLabel: 'Firmar la regla',
          confirmNote: 'Confío solo puede ejecutar esta regla tal como la firmas. Puedes detenerla cuando quieras.',
          signingMessage: 'Guardando tu regla…',
          successTitle: existing ? 'Regla actualizada' : 'Regla creada',
          successBody: proposedBuy
            ? `Quedó guardada como regla: se repite ${frequencyEvery(freq)} hasta que la detengas. Si solo querías una compra, detenla después de la primera.`
            : 'Te avisamos cada vez que se ejecute.',
        }}
        onDone={afterSigned}
        onUnknownDone={afterUnknown}
        failedAction={duplicateAction}
      />
    </SmartScreen>
  );
}

/**
 * A rule the form does not edit. A card allowance (decision 35): the card
 * uses the account when you pay with it, up to the limit per period; the
 * period's room comes from its own read and is simply left out if that read
 * fails. Any other unknown kind: its title and the stop button only.
 */
export function ReadOnlyRule({ rule, card, pending, onStop }: {
  rule: SmartAccountRule;
  card: { spenderLabel: string; capUsd: string; spentUsd: string; remainingUsd: string; periodDays: number;
    periodEnd: string | null; recentPulls: Array<{ pulledAt: string; usdSpent: string }> } | null;
  pending: boolean;
  onStop: () => void;
}) {
  const isCard = rule.kind === 'card';
  const period = cardPeriodLabel(card?.periodDays ?? cardPeriodDays(rule.frequency));
  return (
    <View style={kitStyles.pad}>
      <Card>
        <Row
          left={<IconDisc icon={isCard ? 'credit-card' : 'repeat'} tone={rule.active ? 'mint' : 'neutral'} />}
          title={ruleTitle(rule)}
          subtitle={isCard ? `Límite ${period}` : (rule.active ? 'Activa' : 'Detenida')}
          testID="rule-readonly"
        />
      </Card>
      {isCard ? (
        <Notice
          icon="credit-card"
          body={`Cuando pagas con ${card?.spenderLabel || rule.payeeName || 'tu tarjeta'}, se usa el saldo de tu Cuenta inteligente, hasta ${usd(rule.amountUsd)} ${period}. Cada pago incluye la comisión de salida de 0,9% dentro de ese límite.`}
          style={styles.gap}
          testID="card-rule-note"
        />
      ) : (
        <Notice
          icon="info"
          body="Esta regla no se puede cambiar desde esta versión de la app. Puedes detenerla cuando quieras."
          style={styles.gap}
          testID="rule-unknown-note"
        />
      )}
      {isCard && card ? (
        <Card style={styles.gap}>
          <Row title="Usado en este período" value={usd(card.spentUsd)} testID="card-spent" />
          <Row divider title="Disponible" value={usd(card.remainingUsd)} testID="card-remaining" />
          {card.periodEnd ? (
            <Row divider title="Se renueva" value={shortDate(card.periodEnd)} testID="card-period-end" />
          ) : null}
          {card.recentPulls.slice(0, 5).map((p, i) => (
            <Row key={`${p.pulledAt}-${i}`} divider title={`Pago con tarjeta · ${shortDate(p.pulledAt)}`} value={usd(p.usdSpent)} />
          ))}
        </Card>
      ) : null}
      {rule.active && !pending ? (
        <ActionButton label="Detener esta regla" variant="danger" onPress={onStop} style={styles.stop} testID="rule-stop" />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  next: { marginBottom: -8 },
  proposal: { marginBottom: 8 },
  gap: { marginTop: 12 },
  chips: { flexDirection: 'row', flexWrap: 'wrap' },
  fieldError: { fontSize: 13, color: SA.noticeText, marginTop: 8, marginLeft: 4 },
  sentence: { marginTop: 20, paddingVertical: 16, backgroundColor: SA.mint },
  sentenceText: { fontSize: 17, lineHeight: 24, fontWeight: '600', color: SA.deep, marginBottom: 6 },
  stop: { marginTop: 28 },
  modal: { flex: 1, backgroundColor: SA.card },
  modalHeader: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, minHeight: 56 },
  modalClose: { width: HIT, height: HIT, alignItems: 'center', justifyContent: 'center' },
  modalTitle: { flex: 1, fontSize: 20, fontWeight: '700', color: SA.text, marginLeft: 4 },
  search: {
    flexDirection: 'row', alignItems: 'center', marginHorizontal: 16, marginBottom: 8, paddingHorizontal: 14,
    minHeight: 48, borderRadius: 14, backgroundColor: SA.page, borderWidth: 1, borderColor: SA.line,
  },
  searchInput: { flex: 1, marginLeft: 10, fontSize: 16, color: SA.text, paddingVertical: 10 },
  assetRow: { height: ASSET_ROW, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16 },
  pressed: { opacity: 0.7 },
  assetText: { flex: 1, marginLeft: 14 },
  assetName: { fontSize: 16, fontWeight: '600', color: SA.text },
  assetSymbol: { fontSize: 14, color: SA.muted, marginTop: 2 },
});
