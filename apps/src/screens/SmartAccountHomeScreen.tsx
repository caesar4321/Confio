// Cuenta inteligente: the account's home (spec 8.2).
//
// The same component is the Home tab when the active context is the smart
// account (`asTab`), and a stack screen when it is opened from the wallet row
// on Inicio. Every read is the viewer's own account from the JWT.
//
// Layout, top to bottom:
//   - the account's deep emerald field: "Total en tu cuenta", the one big
//     number, the plan line, and the two moves (in, out);
//   - a billing or cancellation banner, only when there is something to say;
//   - "Tu dinero": the one Confío dollar, then each investment, a calm list
//     (my money on the right, the asset's name small on the left, no deltas);
//   - "Automatización": how many rules run and the next one;
//   - "Beneficiario": its state in one card;
//   - "Tu plan": the plan row and the account's assistant.
// The asset list is the FlatList itself, so every holding is reachable and
// virtualised; the sections above and below are its header and footer.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import CuentaInteligenteMark from '../components/svg/CuentaInteligenteMark';
import { AccountSwitcherHost, useReturnToPersonal } from '../components/smartAccount/AccountSwitcherHost';
import { AssetMark } from '../components/smartAccount/AssetMark';
import {
  ActionButton, Card, Empty, IconDisc, LoadError, Notice, Row, ScreenSkeleton, SectionTitle, SmartScreen,
} from '../components/smartAccount/kit';
import { helpAccount } from '../components/smartAccount/help';
import { SA, cardShadow } from '../components/smartAccount/tokens';
import {
  assetTitle, daysLabel, daysUntil, dollarName, isDollarAsset, planLabel, ruleTitle, shortDate, toCents, usd,
  viewerDollarKey,
} from '../components/smartAccount/format';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { useRememberDirectClaim } from '../components/smartAccount/useRememberDirectClaim';
import { useOfflineDesignations } from '../hooks/useSmartAccountEntry';
import { HIDDEN_AMOUNT, useBalanceHidden } from '../components/smartAccount/useBalanceHidden';
import { useHeader } from '../contexts/HeaderContext';
import {
  fetchBeneficiaryDesignations, fetchSmartAccount, fetchSmartAccountBeneficiaryEnabled, fetchSmartAccountOffer,
  hasOwnSmartAccount, isSmartAccountOpen, isSmartAccountOpening,
  type SmartAccount, type SmartAccountAsset, type SmartAccountBilling,
} from '../services/smartAccount';

const ASSET_ROW_HEIGHT = 72;

/** The banner under the hero: null when the plan is simply current. */
export function billingBanner(account: SmartAccount): {
  tone: 'notice' | 'neutral'; icon: string; title: string; body: string;
  target: 'SmartAccountBilling' | 'SmartAccountCancel' | 'SmartAccountOffer';
  actionLabel?: string;
} | null {
  const b: SmartAccountBilling | null = account.billing;
  if (!b) {
    return null;
  }
  if (b.cancelRequested || account.status === 'cancel_pending') {
    return {
      tone: 'neutral',
      icon: 'calendar',
      title: b.returnsAt ? `Tu cuenta se cierra el ${shortDate(b.returnsAt)}` : 'Tu cuenta se va a cerrar',
      body: 'Ese día todo vuelve a tu billetera. Puedes deshacerlo antes.',
      target: 'SmartAccountCancel',
    };
  }
  if (account.status === 'expired') {
    // Still returning while something is left; once it is all back, the way
    // forward is subscribing again.
    const left = toCents(account.totalUsd);
    if (left !== null && left > 0n) {
      return {
        tone: 'neutral',
        icon: 'corner-up-left',
        title: 'Tu plan terminó',
        body: 'Estamos devolviendo todo a tu billetera.',
        target: 'SmartAccountBilling',
      };
    }
    return {
      tone: 'neutral',
      icon: 'check-circle',
      title: 'Tu plan terminó',
      body: 'Todo ya volvió a tu billetera personal.',
      target: 'SmartAccountOffer',
      actionLabel: 'Volver a suscribirte',
    };
  }
  if (b.status === 'current') {
    return null;
  }
  if (!b.shortfallUsd && (b.status === 'payment_due' || b.status === 'notice' || b.status === 'sale_allowed')) {
    // The dollars in the account already cover the fee: nothing to add and
    // nothing to sell; the charge is on its way.
    return {
      tone: 'neutral',
      icon: 'clock',
      title: 'Estamos cobrando tu plan.',
      body: 'Tus dólares en la cuenta cubren el plan. No tienes que hacer nada.',
      target: 'SmartAccountBilling',
    };
  }
  const short = b.shortfallUsd ? `Faltan ${usd(b.shortfallUsd)} para tu plan` : 'Tu plan está por cobrarse';
  if (b.status === 'sale_allowed' || b.status === 'notice') {
    const when = b.saleAllowedAt ? ` desde el ${shortDate(b.saleAllowedAt)}` : '';
    return {
      tone: 'notice',
      icon: 'alert-circle',
      title: short,
      body: `Tus reglas están en pausa. Si no agregas dólares, se vende parte de tus inversiones${when}.`,
      target: 'SmartAccountBilling',
    };
  }
  return {
    tone: 'notice',
    icon: 'alert-circle',
    title: short,
    body: 'Tus reglas están en pausa hasta que agregues dólares.',
    target: 'SmartAccountBilling',
  };
}

/** How long a just-signed subscribe is waited for before a manual retry,
 * and how often it is re-read meanwhile (mutable for tests only). */
export const OPENING_TIMING = { waitMs: 120_000, pollMs: 4_000 };

/**
 * While `active`, re-reads every few seconds for a bounded time; then stops
 * (`timedOut`) until `restart`.
 */
function useOpeningWatch(active: boolean, reload: () => void): { timedOut: boolean; restart: () => void } {
  const [round, setRound] = useState(0);
  const [timedOut, setTimedOut] = useState(false);
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  useEffect(() => {
    if (!active) {
      return undefined;
    }
    setTimedOut(false);
    const started = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - started >= OPENING_TIMING.waitMs) {
        clearInterval(timer);
        setTimedOut(true);
        return;
      }
      reloadRef.current();
    }, OPENING_TIMING.pollMs);
    return () => clearInterval(timer);
  }, [active, round]);
  return { timedOut, restart: () => { setRound((r) => r + 1); reloadRef.current(); } };
}

export function SmartAccountHomeScreen({ asTab = false }: { asTab?: boolean }) {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const justSubscribed = !asTab && route?.params?.justSubscribed === true;
  const { profileMenu } = useHeader();
  const account = useSmartRead(fetchSmartAccount);
  // SmartAccount.beneficiaryEnabled, read on its own: an older server fails
  // only this read, and the offer's flag is used instead.
  const beneficiaryFlag = useSmartRead(fetchSmartAccountBeneficiaryEnabled);
  const designations = useSmartRead(fetchBeneficiaryDesignations);
  const { returnToPersonal, switching } = useReturnToPersonal();
  const balanceHidden = useBalanceHidden();
  useRememberDirectClaim(designations.data, (x) => (x.contractAddress && x.state === 'active'
    ? { account: x.contractAddress, designationId: x.designationId, ownerName: x.ownerName, chainName: x.chainName || undefined }
    : null));

  const data = account.data ?? null;
  // The dollar the account itself names: the only dollar holding a balance.
  const heldDollarKey = useMemo(() => viewerDollarKey(null, data?.assets ?? []), [data]);
  const flagKnown = typeof beneficiaryFlag.data === 'boolean';
  // The offer is read only for what the account itself cannot answer: the
  // beneficiary flag on an older server, or which dollar to name when the
  // account alone does not say (no dollar held, or more than one).
  const needOffer = beneficiaryFlag.failed || beneficiaryFlag.data === null
    || (account.data !== undefined && !heldDollarKey);
  const offer = useSmartRead(fetchSmartAccountOffer, { skip: !needOffer });

  const reloadAll = useCallback(() => {
    void account.reload();
    void beneficiaryFlag.reload();
    if (needOffer) {
      void offer.reload();
    }
    void designations.reload();
  }, [account, beneficiaryFlag, offer, designations, needOffer]);

  // Coming back from a signed action: show the new state.
  useEffect(() => {
    const unsubscribe = navigation.addListener?.('focus', () => { void account.reload(); });
    return typeof unsubscribe === 'function' ? unsubscribe : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigation]);

  // An expired account still has a home: its assets coming back, or the way
  // to subscribe again.
  const open = hasOwnSmartAccount(data?.status);

  // Just signed, or the server says the subscribe is out and not reconciled
  // yet: wait for the account (bounded, then a manual retry), never send the
  // person back to the sign-up. Re-subscribing after expiry waits too.
  const status = data?.status;
  const opening = !isSmartAccountOpen(status) && (justSubscribed || isSmartAccountOpening(status));
  const watch = useOpeningWatch(opening, () => { void account.reload(); });

  // Opened from Inicio by someone without an account: the offer is the entry.
  useEffect(() => {
    if (!asTab && !opening && account.data !== undefined && !account.failed && !open) {
      navigation.replace('SmartAccountOffer', { door: 'billeteras' });
    }
  }, [asTab, opening, account.data, account.failed, open, navigation]);

  const holdings = useMemo(() => (data?.assets ?? []).filter((a) => !isDollarAsset(a)), [data]);
  // The viewer's dollar (the server's answer first), never just the first
  // dollar row the account happens to list.
  const dollarKey = viewerDollarKey(offer.data?.dollar, data?.assets ?? []) ?? 'cusd';
  const dollar = (data?.assets ?? []).find((a) => isDollarAsset(a) && a.key === dollarKey) ?? null;
  const banner = data && open ? billingBanner(data) : null;
  const activeRules = (data?.rules ?? []).filter((r) => r.active);
  const nextRule = [...activeRules]
    .filter((r) => r.nextRunAt)
    .sort((a, b) => Date.parse(a.nextRunAt as string) - Date.parse(b.nextRunAt as string))[0];
  const beneficiaryEnabled = flagKnown ? beneficiaryFlag.data === true : !!offer.data?.beneficiaryEnabled;
  const beneficiaryVisible = beneficiaryEnabled || !!data?.beneficiary || !!data?.pendingBeneficiary;
  const invite = (designations.data ?? []).find((d) => d.state === 'pending_acceptance');
  const namedOn = (designations.data ?? []).filter((d) => d.state === 'active');
  // The list could not be read: the accounts this phone remembers being named
  // on still open their claim, where the direct path is offered plainly.
  const offlineNamedOn = useOfflineDesignations(designations.failed && designations.data === undefined);

  const screenProps = {
    title: 'Cuenta inteligente',
    help: helpAccount(beneficiaryVisible),
    tone: 'deep' as const,
    isHome: asTab,
    onProfilePress: asTab ? profileMenu.openProfileMenu : undefined,
    avatar: 'C',
    scroll: false,
  };

  if (opening) {
    return (
      <SmartScreen {...screenProps}>
        <View style={styles.openingBox} testID="smart-opening">
          {watch.timedOut ? null : <ActivityIndicator color={SA.deep} size="large" />}
          <Text style={styles.openingTitle}>Abriendo tu cuenta…</Text>
          <Text style={styles.openingBody}>
            {watch.timedOut
              ? 'Está tardando más de lo normal. Tu pago no se repite: vuelve a consultar en un momento.'
              : 'Estamos confirmando tu firma en la red. Puede tardar un minuto.'}
          </Text>
          {watch.timedOut ? (
            <ActionButton label="Reintentar" onPress={watch.restart} style={styles.openingButton} testID="smart-opening-retry" />
          ) : null}
        </View>
        {asTab ? <AccountSwitcherHost /> : null}
      </SmartScreen>
    );
  }

  if (account.loading && !data) {
    return (
      <SmartScreen {...screenProps}>
        <View style={styles.heroLoading} />
        <View style={styles.lift}><ScreenSkeleton /></View>
        {asTab ? <AccountSwitcherHost /> : null}
      </SmartScreen>
    );
  }
  if (account.failed && !data) {
    return (
      <SmartScreen {...screenProps}>
        <LoadError onRetry={reloadAll} busy={account.loading} />
        {asTab ? <AccountSwitcherHost /> : null}
      </SmartScreen>
    );
  }
  if (!data || !open) {
    // Only reachable as the tab: the context is a smart account that is gone
    // (returned after expiry). The way out is the personal wallet.
    return (
      <SmartScreen {...screenProps}>
        <Empty
          icon="corner-up-left"
          title="Esta cuenta ya no está abierta"
          body="Lo que tenía volvió a tu billetera personal."
        />
        <View style={styles.side}>
          <ActionButton label="Ir a mi billetera" onPress={() => { void returnToPersonal(); }} busy={switching} />
        </View>
        {asTab ? <AccountSwitcherHost /> : null}
      </SmartScreen>
    );
  }

  const paidLine = data.billing?.paidUntil
    ? `${planLabel(data.billing.plan)} · pagado hasta el ${shortDate(data.billing.paidUntil)}`
    : data.billing ? planLabel(data.billing.plan) : '';

  const header = (
    <View>
      <View style={styles.hero}>
        <View style={styles.heroTop}>
          <View
            style={styles.heroText}
            accessible
            accessibilityLabel={`Total en tu cuenta: ${balanceHidden ? 'saldo oculto' : usd(data.totalUsd)}`}
          >
            <Text style={styles.heroLabel}>Total en tu cuenta</Text>
            <Text style={styles.heroAmount} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5} testID="home-total">
              {balanceHidden ? HIDDEN_AMOUNT : usd(data.totalUsd)}
            </Text>
          </View>
          <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            <CuentaInteligenteMark size={44} />
          </View>
        </View>
        {paidLine ? <Text style={styles.heroLine}>{paidLine}</Text> : null}
        <View style={styles.heroActions}>
          {data.status === 'expired' ? null : (
            // An ended plan takes no deposits: whatever arrives is returned
            // to the personal wallet.
            <ActionButton
              label="Agregar dinero"
              icon="arrow-down-left"
              variant="onDeep"
              onPress={() => navigation.navigate('SmartAccountMove', { direction: 'in' })}
              style={styles.heroButton}
              accessibilityLabel="Agregar dinero desde mi billetera"
            />
          )}
          <ActionButton
            label="Mover a mi billetera"
            icon="arrow-up-right"
            variant="onDeep"
            onPress={() => navigation.navigate('SmartAccountMove', { direction: 'out' })}
            style={styles.heroButton}
          />
        </View>
      </View>

      <View style={styles.side}>
        {banner ? (
          <Notice
            tone={banner.tone}
            icon={banner.icon}
            title={banner.title}
            body={banner.body}
            actionLabel={banner.actionLabel ?? 'Ver detalle'}
            onPress={() => (banner.target === 'SmartAccountOffer'
              ? navigation.navigate('SmartAccountOffer', { door: 'billeteras' })
              : navigation.navigate(banner.target))}
            style={[styles.banner, cardShadow]}
            testID="billing-banner"
          />
        ) : null}
        {invite ? (
          <Notice
            icon="user-check"
            title={`${invite.ownerName} te eligió como beneficiario`}
            body="Mira qué significa y decide si aceptas."
            actionLabel="Ver invitación"
            onPress={() => navigation.navigate('BeneficiaryInvite', { designationId: invite.designationId })}
            style={styles.banner}
          />
        ) : null}

        <SectionTitle>Tu dinero</SectionTitle>
        <Card style={holdings.length > 0 ? styles.cardTop : undefined}>
          <Row
            left={<AssetMark asset={{ key: dollarKey, symbol: '' }} />}
            title={dollarName(dollarKey)}
            subtitle="Tus dólares en la cuenta"
            value={usd(data.dollarsUsd ?? dollar?.valueUsd ?? '0')}
            testID="home-dollar"
          />
        </Card>
      </View>
    </View>
  );

  const footer = (
    <View style={styles.side}>
      {holdings.length > 0 ? <View style={styles.cardBottomCap} /> : null}

      <SectionTitle>Automatización</SectionTitle>
      <Card>
        <Row
          left={<IconDisc icon="repeat" />}
          title={activeRules.length === 0
            ? 'Aún no tienes reglas'
            : activeRules.length === 1 ? '1 regla activa' : `${activeRules.length} reglas activas`}
          subtitle={nextRule
            ? `Próxima: ${ruleTitle(nextRule)} · ${shortDate(nextRule.nextRunAt)}`
            : activeRules.length === 0 ? 'Envía, paga o invierte de forma automática.' : undefined}
          onPress={() => navigation.navigate('SmartAccountRules')}
          chevron
          testID="home-rules"
        />
        {data.assistantPlus ? (
          <Row
            divider
            left={<IconDisc icon="bell" />}
            title="Alertas"
            subtitle="Las que le pediste al asistente."
            onPress={() => navigation.navigate('SmartAccountWatches')}
            chevron
            testID="home-watches"
          />
        ) : null}
      </Card>

      {beneficiaryVisible ? (
        <>
          <SectionTitle>Beneficiario</SectionTitle>
          <Card>
            {data.beneficiary ? (
              <Row
                left={<IconDisc icon="user-check" />}
                title={data.beneficiary.name}
                subtitle={data.beneficiary.claim && data.beneficiary.claim.state !== 'cancelled'
                  ? 'Pidió recibir tu cuenta'
                  : `Activo · plazo de ${daysLabel(data.beneficiary.windowDays)}`}
                note={data.pendingBeneficiary ? `Cambio pendiente: ${data.pendingBeneficiary.name} aún no acepta.` : undefined}
                onPress={() => navigation.navigate('BeneficiaryStatus')}
                chevron
                testID="home-beneficiary"
              />
            ) : data.pendingBeneficiary ? (
              <Row
                left={<IconDisc icon="clock" tone="neutral" />}
                title={data.pendingBeneficiary.name}
                subtitle="Esperando que acepte"
                onPress={() => navigation.navigate('BeneficiaryStatus')}
                chevron
                testID="home-beneficiary"
              />
            ) : (
              <Row
                left={<IconDisc icon="user-plus" />}
                title="Elige a tu beneficiario"
                subtitle="La persona que recibe esta cuenta si dejas de usarla."
                onPress={() => navigation.navigate('BeneficiarySetup')}
                chevron
                testID="home-beneficiary"
              />
            )}
          </Card>
        </>
      ) : null}

      {namedOn.length === 0 && offlineNamedOn.length > 0 ? (
        <>
          <SectionTitle>Te eligieron</SectionTitle>
          <Card>
            {offlineNamedOn.map((e, i) => (
              <Row
                key={e.account}
                divider={i > 0}
                left={<IconDisc icon="users" tone="neutral" />}
                title={e.ownerName ? `Cuenta de ${e.ownerName}` : 'Cuenta en la que eres beneficiario'}
                subtitle="Sin conexión con Confío"
                onPress={() => navigation.navigate('BeneficiaryClaim', { designationId: e.designationId, account: e.account })}
                chevron
                testID={`home-offline-designation-${e.designationId}`}
              />
            ))}
          </Card>
        </>
      ) : null}

      {namedOn.length > 0 ? (
        <>
          <SectionTitle>Te eligieron</SectionTitle>
          <Card>
            {namedOn.map((d, i) => (
              <Row
                key={d.designationId}
                divider={i > 0}
                left={<IconDisc icon="users" tone="neutral" />}
                title={`Cuenta de ${d.ownerName}`}
                subtitle={d.claim && d.claim.state !== 'cancelled' && d.claim.state !== 'executed'
                  ? `Pedido en curso · ${daysLabel(daysUntil(d.claim.executableAt) ?? 0)} restantes`
                  : 'Eres su beneficiario'}
                onPress={() => navigation.navigate(
                  d.claim && (d.claim.state === 'pending' || d.claim.state === 'executable')
                    ? 'BeneficiaryClaimStatus' : 'BeneficiaryClaim',
                  { designationId: d.designationId },
                )}
                chevron
              />
            ))}
          </Card>
        </>
      ) : null}

      <SectionTitle>Tu plan</SectionTitle>
      <Card>
        <Row
          left={<IconDisc icon="credit-card" />}
          title={data.billing ? planLabel(data.billing.plan) : 'Plan'}
          subtitle={data.billing?.cancelRequested
            ? `Termina el ${shortDate(data.billing.returnsAt || data.billing.paidUntil)}`
            : data.billing?.paidUntil ? `Se renueva el ${shortDate(data.billing.paidUntil)}` : undefined}
          value={data.billing ? usd(data.billing.feeUsd) : undefined}
          onPress={() => navigation.navigate('SmartAccountBilling')}
          chevron
          testID="home-plan"
        />
        {data.assistantPlus ? (
          <Row
            divider
            left={<IconDisc icon="message-circle" />}
            title="El asistente de tu cuenta"
            subtitle="Pídele por chat crear o cambiar tus reglas. Tú confirmas cada cambio."
          />
        ) : null}
      </Card>
      {asTab ? (
        <ActionButton
          label="Ir a mi billetera personal"
          variant="quiet"
          onPress={() => { void returnToPersonal(); }}
          busy={switching}
          style={styles.backToWallet}
        />
      ) : null}
    </View>
  );

  return (
    <SmartScreen {...screenProps}>
      <FlatList
        data={holdings}
        keyExtractor={(item) => item.key}
        ListHeaderComponent={header}
        ListFooterComponent={footer}
        renderItem={({ item, index }: { item: SmartAccountAsset; index: number }) => (
          <View style={[styles.assetRow, index === holdings.length - 1 && styles.assetRowLast]}>
            <Row
              divider
              left={<AssetMark asset={item} />}
              title={assetTitle(item)}
              subtitle={item.symbol}
              value={usd(item.valueUsd)}
            />
          </View>
        )}
        // No getItemLayout: a row grows with the system font size (text wraps,
        // amounts never truncate), so its height is not fixed.
        initialNumToRender={20}
        maxToRenderPerBatch={10}
        windowSize={21}
        contentContainerStyle={styles.listContent}
        refreshControl={(
          <RefreshControl refreshing={account.loading} onRefresh={reloadAll} tintColor={SA.deep} colors={[SA.deep]} />
        )}
      />
      {asTab ? <AccountSwitcherHost /> : null}
    </SmartScreen>
  );
}

/** The Home tab while the active context is the Cuenta inteligente. */
export function SmartAccountHomeTab() {
  return <SmartAccountHomeScreen asTab />;
}

const styles = StyleSheet.create({
  listContent: { paddingBottom: 40 },
  openingBox: { alignItems: 'center', paddingHorizontal: 32, paddingTop: 72 },
  openingTitle: { fontSize: 20, fontWeight: '700', color: SA.text, marginTop: 18, textAlign: 'center' },
  openingBody: { fontSize: 15, lineHeight: 22, color: SA.muted, marginTop: 8, textAlign: 'center' },
  openingButton: { marginTop: 20, alignSelf: 'stretch' },
  side: { paddingHorizontal: 16 },
  lift: { marginTop: -28 },
  heroLoading: { height: 150, backgroundColor: SA.deep, borderBottomLeftRadius: 28, borderBottomRightRadius: 28 },
  hero: {
    backgroundColor: SA.deep, paddingHorizontal: 20, paddingTop: 8, paddingBottom: 24,
    borderBottomLeftRadius: 28, borderBottomRightRadius: 28,
  },
  heroTop: { flexDirection: 'row', alignItems: 'flex-start' },
  heroText: { flex: 1, marginRight: 12 },
  heroLabel: { fontSize: 15, color: SA.onDeepMuted },
  heroAmount: { fontSize: 40, fontWeight: '700', color: SA.onDeep, marginTop: 2 },
  heroLine: { fontSize: 14, lineHeight: 20, color: SA.onDeepMuted, marginTop: 6 },
  heroActions: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 18, marginHorizontal: -4 },
  heroButton: { flexGrow: 1, flexBasis: 140, minHeight: 48, marginHorizontal: 4, marginBottom: 8, borderRadius: 14 },
  banner: { marginTop: 16 },
  // The dollar row and the holdings read as ONE card: the header draws its
  // top, each list row its middle, the footer cap its rounded bottom.
  cardTop: { borderBottomLeftRadius: 0, borderBottomRightRadius: 0 },
  assetRow: { minHeight: ASSET_ROW_HEIGHT, marginHorizontal: 16, paddingHorizontal: 16, backgroundColor: SA.card, justifyContent: 'center' },
  assetRowLast: {},
  cardBottomCap: { height: 12, backgroundColor: SA.card, borderBottomLeftRadius: 20, borderBottomRightRadius: 20 },
  backToWallet: { marginTop: 16 },
});
