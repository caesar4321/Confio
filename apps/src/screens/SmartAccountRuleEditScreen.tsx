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
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_RULES } from '../components/smartAccount/help';
import { SA, HIT } from '../components/smartAccount/tokens';
import {
  centsToDecimal, centsToInput, cryptoBuyAllowed, frequencyEvery, frequencyLabel, railLabel, shortDate, toCents, typedCents, usd,
} from '../components/smartAccount/format';
import {
  SMART_FREQUENCIES, fetchSmartAccount, fetchSmartAccountBuyableAssets, fetchSmartAccountOffer,
  fetchSmartAccountPayoutMethods, prepareSmartAccountBuyRule, prepareSmartAccountCancelRule,
  prepareSmartAccountPayoutRule, prepareSmartAccountSendRule,
  type SmartAccountBuyableAsset, type SmartAccountPayoutMethod, type SmartFrequency, type SmartRuleKind,
} from '../services/smartAccount';
import type { MainStackParamList } from '../types/navigation';

const TITLES: Record<SmartRuleKind, string> = {
  send: 'Enviar a alguien',
  payout: 'Pagar a una cuenta',
  buy: 'Invertir',
};

const ASSET_ROW = 68;

// Bitcoin and gold are offered only where the build AND the server say so
// (shared with the offer, which must not promise them either).
export { cryptoBuyAllowed };

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

export function SmartAccountRuleEditScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'SmartAccountRuleEdit'>>();
  const ruleId = route.params?.ruleId ?? null;

  const account = useSmartRead(fetchSmartAccount);
  const offer = useSmartRead(fetchSmartAccountOffer);
  const existing = ruleId ? (account.data?.rules ?? []).find((r) => String(r.id) === ruleId) ?? null : null;
  const kind = ((existing?.kind ?? route.params?.kind ?? 'send') as SmartRuleKind);
  const methods = useSmartRead(fetchSmartAccountPayoutMethods, { skip: kind !== 'payout' });
  const flow = useSignFlow();
  const [stopping, setStopping] = useState(false);

  const [person, setPerson] = useState<PickedPerson | null>(null);
  const [method, setMethod] = useState<SmartAccountPayoutMethod | null>(null);
  const [asset, setAsset] = useState<SmartAccountBuyableAsset | null>(null);
  const [amount, setAmount] = useState<string | null>(null);
  const [frequency, setFrequency] = useState<SmartFrequency | null>(null);
  const [picker, setPicker] = useState(false);
  const [touched, setTouched] = useState(false);

  const rails = offer.data?.payoutRails ?? [];
  const usableMethods = useMemo(
    () => (methods.data ?? []).filter((m) => rails.includes(m.rail)),
    [methods.data, rails],
  );
  const allowCrypto = cryptoBuyAllowed(offer.data?.investingCryptoEnabled);

  // An existing rule fills the form until the user changes a field.
  const destination: { label: string; sub?: string } | null = (() => {
    if (kind === 'send') {
      if (person) { return { label: person.name }; }
      if (existing?.payeeHandle) { return { label: existing.payeeName || `@${existing.payeeHandle.replace(/^@/, '')}` }; }
      return null;
    }
    if (kind === 'payout') {
      if (method) { return { label: method.label, sub: `${railLabel(method.rail)} · ${method.holderName}` }; }
      if (existing?.payoutMethodId) { return { label: existing.payoutLabel || railLabel(existing.payoutRail) }; }
      return null;
    }
    if (asset) { return { label: asset.name, sub: asset.symbol }; }
    if (existing?.assetKey) { return { label: existing.assetName || existing.assetSymbol || '' , sub: existing.assetSymbol || undefined }; }
    return null;
  })();

  const existingCents = toCents(existing?.amountUsd);
  const text = amount ?? (existingCents !== null ? centsToInput(existingCents) : '');
  const cents = typedCents(text);
  const freq = (frequency ?? (existing?.frequency as SmartFrequency | undefined) ?? 'monthly');
  const amountError = cents === null || cents <= 0n ? 'Escribe un monto.' : '';
  const destinationError = destination ? '' : 'Elige un destino.';
  const amountUsd = cents !== null ? centsToDecimal(cents) : '';

  const sentence = destination && cents !== null && cents > 0n
    ? kind === 'buy'
      ? `Tu cuenta invierte ${usd(amountUsd)} en ${destination.label} ${frequencyEvery(freq)}.`
      : `Tu cuenta ${kind === 'send' ? 'envía' : 'paga'} ${usd(amountUsd)} a ${destination.label} ${frequencyEvery(freq)}.`
    : '';

  const onReview = () => {
    setTouched(true);
    if (amountError || destinationError || cents === null) {
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
            ruleId, payeeHandle: person?.handle ?? existing?.payeeHandle ?? '', amountUsd, frequency: freq,
          });
        }
        if (kind === 'payout') {
          return prepareSmartAccountPayoutRule({
            ruleId, payoutMethodId: method?.payoutMethodId ?? existing?.payoutMethodId ?? '', amountUsd, frequency: freq,
          });
        }
        return prepareSmartAccountBuyRule({
          ruleId, assetKey: asset?.assetKey ?? existing?.assetKey ?? '', amountUsd, frequency: freq,
        });
      },
    });
  };

  const onStop = () => {
    if (!ruleId) {
      return;
    }
    setStopping(true);
    void flow.start({ prepare: () => prepareSmartAccountCancelRule(ruleId) });
  };

  const loading = (!!ruleId && account.loading && !account.data) || (offer.loading && !offer.data);
  const failed = (!!ruleId && account.failed && !account.data) || (offer.failed && !offer.data);
  const missingRule = !!ruleId && !!account.data && !existing;
  // Only when CREATING: an existing payout rule always keeps its form and
  // "Detener esta regla", even if no bank method is usable today.
  const noMethods = !ruleId && kind === 'payout' && !methods.loading && !methods.failed && usableMethods.length === 0;

  return (
    <SmartScreen
      title={existing ? 'Tu regla' : TITLES[kind]}
      help={HELP_RULES}
      footer={!loading && !failed && !missingRule && !noMethods ? (
        <ActionButton label="Revisar" onPress={onReview} testID="rule-review" />
      ) : undefined}
    >
      {loading ? <ScreenSkeleton /> : failed ? (
        <LoadError onRetry={() => { void account.reload(); void offer.reload(); }} />
      ) : missingRule ? (
        <Empty icon="repeat" title="Esta regla ya no existe" actionLabel="Volver" onAction={() => navigation.goBack()} />
      ) : noMethods ? (
        <Empty
          icon="home"
          title="Aún no guardaste una cuenta bancaria"
          body={rails.length > 0
            ? `Guarda primero una cuenta ${rails.map(railLabel).join(' o ')} desde Enviar. Después podrás pagarle de forma automática.`
            : 'Los pagos automáticos a cuenta bancaria todavía no están disponibles para ti.'}
        />
      ) : (
        <View style={kitStyles.pad}>
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
          {touched && destinationError ? <Text style={styles.fieldError}>{destinationError}</Text> : null}

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

          {existing ? (
            <ActionButton label="Detener esta regla" variant="danger" onPress={onStop} style={styles.stop} testID="rule-stop" />
          ) : null}
        </View>
      )}

      {kind === 'send' ? (
        <ConfioContactPicker
          visible={picker}
          title="¿A quién le envías?"
          onClose={() => setPicker(false)}
          onPick={(p) => { setPerson(p); setPicker(false); }}
        />
      ) : null}
      {kind === 'payout' ? (
        <Sheet visible={picker} onClose={() => setPicker(false)} title="Tus cuentas guardadas">
          {methods.loading && !methods.data ? <RowsSkeleton rows={2} /> : methods.failed && !methods.data ? (
            <LoadError onRetry={methods.reload} />
          ) : usableMethods.length === 0 ? (
            <Text style={kitStyles.small} testID="payout-no-methods">
              {rails.length > 0
                ? `Guarda primero una cuenta ${rails.map(railLabel).join(' o ')} desde Enviar. Después podrás elegirla aquí.`
                : 'Los pagos automáticos a cuenta bancaria todavía no están disponibles para ti.'}
            </Text>
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
        </Sheet>
      ) : null}
      {kind === 'buy' ? (
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
          successBody: 'Te avisamos cada vez que se ejecute.',
        }}
        onDone={() => navigation.goBack()}
      />
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  next: { marginBottom: -8 },
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
