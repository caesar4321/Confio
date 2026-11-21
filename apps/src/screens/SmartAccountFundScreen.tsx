// Cuenta inteligente: choose what to move in and open the account
// (spec 8.2 "Subscribe", step 2).
//
// One signature creates the account, moves the chosen assets and pays the
// first period. The first period is paid from inside the account, so at least
// the chosen plan's price (never less than the server's `minFirstDepositUsd`)
// of the viewer's Confío dollar has to go in: that is the
// one required field. Everything else the wallet holds is optional, one row
// each, moved whole.
//
// Nothing is signed from this screen's numbers: "Revisar" asks the server for
// the batch, and the confirm sheet shows the server's own summary lines.
import React, { useMemo, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import { AmountField } from '../components/smartAccount/AmountField';
import { AssetMark } from '../components/smartAccount/AssetMark';
import {
  ActionButton, Card, Chip, Fact, LoadError, Notice, Row, ScreenSkeleton, SectionTitle, SmartScreen, kitStyles,
} from '../components/smartAccount/kit';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { logSmartAccountFunnel } from '../services/paidOffers';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_MOVE } from '../components/smartAccount/help';
import {
  assetTitle, centsToInput, dollarName, isDollarAsset, isZeroUnits, planLabel, planPeriod, toCents, typedCents, usd, centsToDecimal,
  depositUnitsForUsd, mayFallShort, viewerDollarKey,
} from '../components/smartAccount/format';
import {
  fetchSmartAccountMovePreview, fetchSmartAccountOffer, prepareSmartAccountSubscribe,
  type SmartAccountDepositInput, type SmartAccountMoveAsset,
} from '../services/smartAccount';
import type { MainStackParamList } from '../types/navigation';

/**
 * The dollar the first deposit is made in: the one the person actually holds.
 * Holding exactly one Confío dollar, that one; holding both, the offer's
 * dollar when it covers the minimum, else the other one when it does; else
 * (or holding none) the offer's dollar. Never names a dollar the person does
 * not hold while they hold the other.
 */
export function fundingDollarKey(
  assets: ReadonlyArray<SmartAccountMoveAsset>,
  offerDollar: string | null | undefined,
  minCents: bigint,
): string {
  const usable = assets.filter((a) => a.included);
  const held = viewerDollarKey(null, usable);
  if (held) {
    return held;
  }
  const covering = usable.filter((a) => isDollarAsset(a) && (toCents(a.valueUsd) ?? 0n) >= minCents && minCents > 0n);
  const pick = covering.find((a) => a.key === offerDollar) ?? covering[0];
  return pick?.key ?? offerDollar ?? 'cusd';
}

export function SmartAccountFundScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<MainStackParamList, 'SmartAccountFund'>>();
  const planKey = route.params?.plan ?? 'annual';
  // Signed (or maybe signed): the account row appears only after the server
  // reconciles the chain, so the account screen waits for it instead of
  // offering the sign-up again.
  const openingDone = () => navigation.reset({
    index: 1,
    routes: [{ name: 'BottomTabs' }, { name: 'SmartAccountHome', params: { justSubscribed: true } }],
  });

  const offer = useSmartRead(fetchSmartAccountOffer);
  const preview = useSmartRead(() => fetchSmartAccountMovePreview('in'));
  // Logged once the subscribe batch is signed and executed on-chain; the
  // server records `subscribed` itself from the reconciled event.
  const flow = useSignFlow({ onExecuted: () => logSmartAccountFunnel('subscribe_signed', planKey) });

  const [amount, setAmount] = useState<string | null>(null);
  const [extras, setExtras] = useState<Record<string, boolean>>({});
  const [touched, setTouched] = useState(false);

  const plan = offer.data?.plans.find((p) => p.key === planKey) ?? null;
  const assets = preview.data?.assets ?? [];

  // The server's minFirstDepositUsd is the cheapest plan's first period; the
  // plan chosen on the offer (annual by default) can cost more, and the
  // server refuses a first deposit under it (`first_fee_short`). The minimum
  // is whichever is larger, used for the gate, the prefill, the chip and the copy.
  const serverMinCents = toCents(offer.data?.minFirstDepositUsd) ?? 0n;
  const planCents = toCents(plan?.priceUsd) ?? 0n;
  const minCents = planCents > serverMinCents ? planCents : serverMinCents;

  const dollarKey = fundingDollarKey(assets, offer.data?.dollar, minCents);
  const dollar = assets.find((a) => a.key === dollarKey && a.included) ?? null;
  // Only the viewer's dollar is the dollar row. The other Confío dollar (an
  // edge case) is listed with the other assets by its name, and zero rows
  // are never shown.
  const others = useMemo(
    () => assets.filter((a) => a.included && a.key !== dollarKey && !isZeroUnits(a.units)),
    [assets, dollarKey],
  );
  const notMoved = useMemo(
    () => assets.filter((a) => !a.included && !(isDollarAsset(a) && a.key !== dollarKey && isZeroUnits(a.units))),
    [assets, dollarKey],
  );

  const minUsd = usd(centsToDecimal(minCents));
  const availableCents = toCents(dollar?.valueUsd) ?? 0n;
  const enough = availableCents >= minCents && minCents > 0n;
  // Prefilled with the minimum: the smallest amount that opens the account.
  const text = amount ?? (enough ? centsToInput(minCents) : '');
  const cents = typedCents(text);

  let amountError = '';
  if (cents === null) {
    amountError = 'Escribe un monto.';
  } else if (cents < minCents) {
    amountError = `El mínimo es ${minUsd}: cubre tu primer período.`;
  } else if (cents > availableCents) {
    amountError = `Tienes ${usd(dollar?.valueUsd)} disponibles.`;
  }

  const loading = (offer.loading && !offer.data) || (preview.loading && !preview.data);
  const failed = (offer.failed && !offer.data) || (preview.failed && !preview.data);

  const onReview = () => {
    setTouched(true);
    if (amountError || cents === null || !dollar) {
      return;
    }
    const units = depositUnitsForUsd(cents, minCents, dollar);
    if (!units) {
      return;
    }
    const deposits: SmartAccountDepositInput[] = [
      { assetKey: dollar.key, units },
      ...others.filter((a) => extras[a.key]).map((a) => ({ assetKey: a.key, units: 'max' })),
    ];
    void flow.start({ prepare: () => prepareSmartAccountSubscribe(planKey, deposits, true) });
  };

  return (
    <SmartScreen
      title="Agrega dinero"
      help={HELP_MOVE}
      footer={!loading && !failed && enough ? (
        <ActionButton label="Revisar" onPress={onReview} testID="fund-review" />
      ) : undefined}
    >
      {loading ? <ScreenSkeleton /> : failed ? (
        <LoadError onRetry={() => { void offer.reload(); void preview.reload(); }} />
      ) : (
        <View style={kitStyles.pad}>
          <Card>
            <Fact
              label={planLabel(planKey)}
              value={plan ? `${usd(plan.priceUsd)} ${planPeriod(planKey)}` : '—'}
            />
            <Text style={styles.cardNote}>Se cobra del dinero que muevas a la cuenta, al firmar.</Text>
          </Card>

          {!enough ? (
            <View style={kitStyles.gapLarge}>
              <Notice
                tone="notice"
                icon="arrow-down-circle"
                title={`Necesitas ${minUsd} en ${dollarName(dollarKey)}`}
                body={`Hoy tienes ${usd(dollar?.valueUsd ?? '0')} en tu billetera. Recarga y vuelve para abrir tu cuenta.`}
                testID="fund-short"
              />
              <ActionButton
                label="Volver a Inicio"
                variant="secondary"
                onPress={() => navigation.navigate('BottomTabs', { screen: 'Home' })}
                style={kitStyles.gap}
              />
            </View>
          ) : (
            <>
              <SectionTitle>{`¿Cuánto ${dollarName(dollarKey)} mueves?`}</SectionTitle>
              <AmountField
                label={`Disponible en tu billetera: ${usd(dollar?.valueUsd)}`}
                value={text}
                onChange={(t) => { setAmount(t); setTouched(true); }}
                hint={`Mínimo ${minUsd}: cubre tu primer período.`}
                error={touched ? amountError : ''}
                testID="fund-amount"
              />
              {mayFallShort(minCents, dollar) ? (
                <Text style={styles.under} testID="fund-may-fall-short">
                  {`Tu ${dollarName(dollarKey)} apenas llega a ${minUsd} y su valor se redondea al centavo: puede no alcanzar para el primer período. Si no alcanza, recarga un poco más.`}
                </Text>
              ) : null}
              <View style={styles.chips}>
                <Chip
                  label="Mínimo"
                  selected={cents === minCents}
                  onPress={() => setAmount(centsToInput(minCents))}
                  accessibilityLabel={`Mínimo, ${minUsd}`}
                />
                <Chip
                  label="Todo"
                  selected={cents === availableCents}
                  onPress={() => setAmount(centsToInput(availableCents))}
                  accessibilityLabel={`Todo, ${usd(dollar?.valueUsd)}`}
                />
              </View>

              {others.length > 0 ? (
                <>
                  <SectionTitle>También puedes mover</SectionTitle>
                  <Card>
                    {others.map((a, i) => (
                      <Row
                        key={a.key}
                        divider={i > 0}
                        left={<AssetMark asset={a} />}
                        title={assetTitle(a)}
                        subtitle={a.symbol}
                        value={usd(a.valueUsd)}
                        selected={!!extras[a.key]}
                        onPress={() => setExtras((prev) => ({ ...prev, [a.key]: !prev[a.key] }))}
                        testID={`fund-extra-${a.key}`}
                      />
                    ))}
                  </Card>
                  <Text style={[kitStyles.small, styles.under]}>
                    Lo que marques se mueve completo. Puedes devolverlo a tu billetera cuando quieras.
                  </Text>
                </>
              ) : null}

              {notMoved.length > 0 ? (
                <>
                  <SectionTitle>Se queda en tu billetera</SectionTitle>
                  <Card flat>
                    {notMoved.map((a, i) => (
                      <Row
                        key={a.key}
                        divider={i > 0}
                        left={<AssetMark asset={a} />}
                        title={assetTitle(a)}
                        note={a.reason || 'La cuenta no lo admite.'}
                        value={usd(a.valueUsd)}
                      />
                    ))}
                  </Card>
                </>
              ) : null}
            </>
          )}
        </View>
      )}

      <SignFlowSheet
        flow={flow}
        copy={{
          confirmLabel: 'Firmar y abrir mi cuenta',
          confirmNote: 'Con tu firma se abre la cuenta, se mueve tu dinero y se paga el primer período. No hay reembolsos.',
          signingMessage: 'Abriendo tu cuenta…',
          successTitle: 'Tu Cuenta inteligente está abierta',
          successBody: 'Ya puedes crear tus reglas.',
          successLabel: 'Ir a mi cuenta',
        }}
        onDone={openingDone}
        onUnknownDone={openingDone}
      />
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  cardNote: { fontSize: 14, lineHeight: 20, color: '#6B7280', paddingBottom: 14 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 12 },
  under: { marginTop: 10, marginHorizontal: 4 },
});
