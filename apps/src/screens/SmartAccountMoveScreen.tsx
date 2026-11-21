// Cuenta inteligente: move assets in or out (spec 3.3, 3.4, 8.2).
//
// Two directions, one layout. The server's preview is the list: what moves,
// what does NOT move and why, and how many signatures "Mover todo" takes.
//   - "Mover todo": the whole included list, in `batches` signatures, with a
//     running "Firma 2 de 3".
//   - One asset: tap its row. In: a deposit of that asset. Out: a withdrawal.
//     The Confío dollar asks for an amount; anything else moves whole.
// Moving between the wallet and the account is a transfer between the
// viewer's own two places, so nothing here quotes a conversion.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, StyleSheet, View } from 'react-native';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import { AmountField } from '../components/smartAccount/AmountField';
import { AssetMark } from '../components/smartAccount/AssetMark';
import {
  ActionButton, Chip, Empty, LoadError, Row, RowsSkeleton, Sheet, SmartScreen, kitStyles,
} from '../components/smartAccount/kit';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_MOVE } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import {
  assetTitle, centsToInput, isDollarAsset, isZeroUnits, toCents, typedCents, unitsForUsd, usd, viewerDollarKey,
} from '../components/smartAccount/format';
import {
  fetchSmartAccountMovePreview, fetchSmartAccountOffer, prepareSmartAccountDeposit, prepareSmartAccountMoveEverything,
  prepareSmartAccountWithdraw,
  type SmartAccountMoveAsset, type SmartMoveDirection,
} from '../services/smartAccount';
import type { MainStackParamList } from '../types/navigation';

type Item =
  | { type: 'heading'; id: string; title: string; note?: string }
  | { type: 'asset'; id: string; asset: SmartAccountMoveAsset };

export function SmartAccountMoveScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'SmartAccountMove'>>();
  const [direction, setDirection] = useState<SmartMoveDirection>(route.params?.direction === 'out' ? 'out' : 'in');
  const preview = useSmartRead(() => fetchSmartAccountMovePreview(direction));
  // Only to know which Confío dollar is the viewer's; the list never waits on it.
  const offer = useSmartRead(fetchSmartAccountOffer);
  const flow = useSignFlow({ onExecuted: () => { void preview.reload(); } });
  const [picked, setPicked] = useState<SmartAccountMoveAsset | null>(null);
  const [amount, setAmount] = useState('');
  const [all, setAll] = useState(false);

  // A new direction is a new list.
  const firstDirection = useRef(true);
  useEffect(() => {
    if (firstDirection.current) {
      firstDirection.current = false; // the hook already loaded the first one
      return;
    }
    void preview.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [direction]);

  const fresh = preview.data && preview.data.direction === direction ? preview.data : null;
  const dollarKey = viewerDollarKey(offer.data?.dollar, fresh?.assets ?? []);
  // The viewer's dollar is THE dollar row, first. The other Confío dollar
  // (an edge case) is just another asset, by its name, and only if nonzero.
  const isMyDollar = (a: SmartAccountMoveAsset) => isDollarAsset(a) && (!dollarKey || a.key === dollarKey);
  const included = useMemo(() => {
    const list = (fresh?.assets ?? []).filter((a) => a.included && !isZeroUnits(a.units));
    return [...list.filter(isMyDollar), ...list.filter((a) => !isMyDollar(a))];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fresh, dollarKey]);
  const excluded = useMemo(
    () => (fresh?.assets ?? []).filter((a) => !a.included && !(isDollarAsset(a) && !isMyDollar(a) && isZeroUnits(a.units))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fresh, dollarKey],
  );
  const items = useMemo<Item[]>(() => {
    const out: Item[] = [];
    if (included.length > 0) {
      out.push({
        type: 'heading', id: 'h-in',
        title: direction === 'in' ? 'En tu billetera' : 'En tu cuenta',
        note: 'Toca uno para moverlo solo.',
      });
      included.forEach((asset) => out.push({ type: 'asset', id: `i-${asset.key}`, asset }));
    }
    if (excluded.length > 0) {
      out.push({ type: 'heading', id: 'h-out', title: 'No se mueve' });
      excluded.forEach((asset) => out.push({ type: 'asset', id: `x-${asset.key}`, asset }));
    }
    return out;
  }, [included, excluded, direction]);

  const batches = Math.max(1, fresh?.batches ?? 1);
  const where = direction === 'in' ? 'a tu Cuenta inteligente' : 'a tu billetera';

  const moveAll = () => {
    setAll(true);
    void flow.start({
      // The server rebuilds the list from live balances on each prepare, so
      // after a batch moves, what was batch 1 is now batch 0: always ask for
      // index 0 (useSignFlow stops on `nothing_to_move`).
      prepare: () => prepareSmartAccountMoveEverything(direction, 0),
      batches,
      repeatFirst: true,
    });
  };

  const openAsset = (asset: SmartAccountMoveAsset) => {
    setAmount(centsToInput(toCents(asset.valueUsd) ?? 0n));
    setPicked(asset);
  };

  const pickedCents = picked ? typedCents(amount) : null;
  const pickedMax = toCents(picked?.valueUsd) ?? 0n;
  const pickedIsDollar = !!picked && isMyDollar(picked);
  const pickedError = !pickedIsDollar ? ''
    : pickedCents === null || pickedCents <= 0n ? 'Escribe un monto.'
      : pickedCents > pickedMax ? `Tienes ${usd(picked?.valueUsd)} disponibles.` : '';

  const moveOne = () => {
    if (!picked || pickedError) {
      return;
    }
    const asset = picked;
    const units = pickedIsDollar && pickedCents !== null ? unitsForUsd(pickedCents, asset) : 'max';
    if (!units) {
      return;
    }
    setPicked(null);
    setAll(false);
    void flow.start({
      prepare: () => (direction === 'in'
        ? prepareSmartAccountDeposit([{ assetKey: asset.key, units }])
        : prepareSmartAccountWithdraw(asset.key, units)),
    });
  };

  const loading = preview.loading && !fresh;
  const failed = preview.failed && !fresh;
  // The server answered with no preview at all: that is an error, not "empty".
  const missing = !loading && !failed && preview.data === null;

  return (
    <SmartScreen
      title="Mover"
      help={HELP_MOVE}
      scroll={false}
      footer={!loading && !failed && !missing && included.length > 0 ? (
        <>
          <ActionButton
            label={`Mover todo ${where}`}
            onPress={moveAll}
            accessibilityLabel={`Mover todo ${where}, ${usd(fresh?.totalUsd)}`}
            testID="move-all"
          />
          <Text style={styles.footNote}>
            {batches > 1
              ? `${usd(fresh?.totalUsd)} · ${batches} firmas`
              : `${usd(fresh?.totalUsd)} · una firma`}
          </Text>
        </>
      ) : undefined}
    >
      <View style={styles.tabs} accessibilityRole="radiogroup">
        <Chip label="A mi cuenta" selected={direction === 'in'} onPress={() => setDirection('in')} accessibilityLabel="Mover a mi Cuenta inteligente" />
        <Chip label="A mi billetera" selected={direction === 'out'} onPress={() => setDirection('out')} accessibilityLabel="Mover a mi billetera" />
      </View>
      {loading ? (
        <View style={kitStyles.pad}><RowsSkeleton rows={4} /></View>
      ) : failed ? (
        <LoadError onRetry={preview.reload} busy={preview.loading} />
      ) : missing ? (
        <LoadError
          onRetry={preview.reload}
          busy={preview.loading}
          message="No pudimos leer qué se puede mover. Tu dinero no cambió. Inténtalo de nuevo."
        />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(item) => item.id}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          // No getItemLayout: headings and asset rows differ in height and a
          // row grows with the system font size (a refusal note wraps). No
          // onEndReached: the preview is one complete server read, not paged.
          contentContainerStyle={styles.list}
          ListEmptyComponent={(
            <Empty
              icon="inbox"
              title={direction === 'in' ? 'No hay nada que mover' : 'Tu cuenta está vacía'}
              body={direction === 'in' ? 'Tu billetera no tiene nada que la cuenta admita.' : 'Agrega dinero desde tu billetera.'}
            />
          )}
          renderItem={({ item }) => (item.type === 'heading' ? (
            <View style={styles.heading}>
              <Text style={styles.headingTitle} accessibilityRole="header">{item.title}</Text>
              {item.note ? <Text style={kitStyles.small}>{item.note}</Text> : null}
            </View>
          ) : (
            <View style={styles.rowBox}>
              <Row
                left={<AssetMark asset={item.asset} />}
                title={assetTitle(item.asset)}
                subtitle={item.asset.included ? item.asset.symbol : undefined}
                note={item.asset.included ? undefined : (item.asset.reason || 'La cuenta no lo admite.')}
                value={usd(item.asset.valueUsd)}
                onPress={item.asset.included ? () => openAsset(item.asset) : undefined}
                chevron={item.asset.included}
                testID={`move-${item.asset.key}`}
              />
            </View>
          ))}
        />
      )}

      <Sheet visible={!!picked} onClose={() => setPicked(null)} title={picked ? `Mover ${assetTitle(picked)}` : ''}>
        {picked ? (
          <View>
            {pickedIsDollar ? (
              <AmountField
                label={`Disponible: ${usd(picked.valueUsd)}`}
                value={amount}
                onChange={setAmount}
                error={pickedError}
                testID="move-amount"
              />
            ) : (
              <Text style={kitStyles.lead}>
                {`Se mueve toda tu posición (${usd(picked.valueUsd)}) ${where}.`}
              </Text>
            )}
            <ActionButton label="Revisar" onPress={moveOne} style={styles.sheetButton} testID="move-one" />
          </View>
        ) : null}
      </Sheet>

      <SignFlowSheet
        flow={flow}
        copy={{
          confirmLabel: all && batches > 1 ? `Firmar (${batches} firmas)` : 'Firmar y mover',
          confirmNote: all ? 'Lo que aparece en "No se mueve" se queda donde está.' : undefined,
          signingMessage: 'Moviendo…',
          successTitle: 'Movimiento completo',
          successBody: direction === 'in' ? 'Ya está en tu Cuenta inteligente.' : 'Ya está en tu billetera.',
        }}
        onDone={() => navigation.goBack()}
      />
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  tabs: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 16, paddingTop: 16 },
  list: { paddingBottom: 24 },
  heading: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 6 },
  headingTitle: { fontSize: 18, fontWeight: '700', color: SA.text },
  rowBox: { marginHorizontal: 16, marginTop: 8, paddingHorizontal: 16, backgroundColor: SA.card, borderRadius: 16 },
  footNote: { fontSize: 13, color: SA.muted, textAlign: 'center', marginTop: 8 },
  sheetButton: { marginTop: 20 },
});
