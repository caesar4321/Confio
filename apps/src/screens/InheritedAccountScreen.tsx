// An inherited Cuenta inteligente (spec 6.6, 8.2): a withdraw-only box.
//
// What it holds and two actions, nothing else: move everything to my wallet,
// or to my own Cuenta inteligente when I have one. No plan, no rules, no
// beneficiary, no trading, and no deadline. Also the Home tab when the active
// context is an inherited account (`asTab`).
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import { AccountSwitcherHost, useReturnToPersonal } from '../components/smartAccount/AccountSwitcherHost';
import { AssetMark } from '../components/smartAccount/AssetMark';
import { ActionButton, Empty, LoadError, Row, ScreenSkeleton, SmartScreen } from '../components/smartAccount/kit';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_INHERITED } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { assetTitle, shortDate, usd } from '../components/smartAccount/format';
import { useAccount } from '../contexts/AccountContext';
import { useHeader } from '../contexts/HeaderContext';
import { indexInherited } from '../utils/smartAccounts';
import { useRememberDirectClaim } from '../components/smartAccount/useRememberDirectClaim';
import { DirectClaimPanel } from '../components/smartAccount/DirectClaimPanel';
import { HIDDEN_AMOUNT, useBalanceHidden } from '../components/smartAccount/useBalanceHidden';
import {
  fetchInheritedAccounts, prepareInheritedWithdraw, type InheritedDestination, type SmartAccountPreparedBatch,
} from '../services/smartAccount';

const REGISTERING_RETRY_MS = 4000;

/**
 * The most assets one withdraw signature may carry. Mirrors the server's
 * MAX_WITHDRAW_ALL_TOKENS (smart_account/services.py): more than this and
 * prepareInheritedWithdraw refuses with `too_many_assets`.
 */
export const MAX_ASSETS_PER_WITHDRAW = 12;

/**
 * Prepares withdraw batch `index`: the first batch takes the assets already on
 * screen; every later one re-reads the account so it only names what is still
 * there, and never a key an earlier (executed) batch already moved, even when
 * the read lags the chain. Nothing left = `nothing_to_move`, which the sign
 * flow treats as "the earlier signatures covered it".
 */
export function inheritedWithdrawPreparer(
  inheritedAccountId: string,
  initialKeys: string[],
  destination: InheritedDestination,
) {
  const sent = new Set<string>();
  return async (index: number): Promise<SmartAccountPreparedBatch> => {
    let keys = initialKeys;
    if (index > 0) {
      const fresh = await fetchInheritedAccounts();
      if (!fresh.ok) {
        throw new Error('inherited_read_failed');
      }
      const now = fresh.data.find((a) => a.inheritedAccountId === inheritedAccountId);
      keys = (now?.assets ?? []).map((a) => a.key);
    }
    const chunk = keys.filter((k) => !sent.has(k)).slice(0, MAX_ASSETS_PER_WITHDRAW);
    if (chunk.length === 0) {
      return {
        success: false, errorCode: 'nothing_to_move', errorMessage: null,
        requestId: null, calls: null, notAfter: null, summary: null,
      };
    }
    const batch = await prepareInheritedWithdraw(inheritedAccountId, chunk, destination);
    if (batch.success) {
      // A later prepare only runs after this batch executed.
      chunk.forEach((k) => sent.add(k));
    }
    return batch;
  };
}

export function InheritedAccountScreen({ asTab = false }: { asTab?: boolean }) {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { activeAccount } = useAccount();
  const { profileMenu } = useHeader();
  const list = useSmartRead(fetchInheritedAccounts);
  const flow = useSignFlow({ onExecuted: () => { void list.reload(); } });
  const { returnToPersonal, switching } = useReturnToPersonal();
  const [destination, setDestination] = useState<InheritedDestination>('wallet');
  const balanceHidden = useBalanceHidden();

  const indexed = indexInherited(list.data ?? []);
  const ordered = indexed.map((x) => x.entry);
  useRememberDirectClaim(list.data, (a) => ({
    account: a.contractAddress,
    inheritedAccountId: a.inheritedAccountId,
    ownerName: a.fromName,
    tokens: a.assets.map((x) => x.address),
  }));
  const wantedId: string | undefined = route.params?.inheritedAccountId
    ?? (asTab ? activeAccount?.smart?.inheritedAccountId : undefined);
  // As the tab, the context's index picks the account when the id is not known
  // yet: the server's accountIndex when it sends one, else the order received.
  const byIndex = asTab && activeAccount?.type === 'smart' && activeAccount.index > 0
    ? indexed.find((x) => x.index === activeAccount.index)?.entry : undefined;
  // Opened right after receiving an account: match its address, and never
  // fall back to another account while it is still being registered.
  const wantedContract: string | undefined = route.params?.contractAddress?.toLowerCase() || undefined;
  const account = wantedContract
    ? ordered.find((a) => a.contractAddress?.toLowerCase() === wantedContract)
    : (wantedId ? ordered.find((a) => a.inheritedAccountId === wantedId) : undefined)
      ?? byIndex ?? (asTab ? undefined : ordered[0]);
  const registering = !!wantedContract && !account && !!list.data;
  // While it is being registered, ask again on its own every few seconds.
  useEffect(() => {
    if (!registering || list.loading) {
      return;
    }
    const timer = setTimeout(() => { void list.reload(); }, REGISTERING_RETRY_MS);
    return () => clearTimeout(timer);
  }, [registering, list.loading, list.reload]);

  const move = (to: InheritedDestination) => {
    if (!account) {
      return;
    }
    setDestination(to);
    const keys = account.assets.map((a) => a.key);
    // One signature per MAX_ASSETS_PER_WITHDRAW assets ("Firma 1 de N").
    const batches = Math.max(1, Math.ceil(keys.length / MAX_ASSETS_PER_WITHDRAW));
    void flow.start({ prepare: inheritedWithdrawPreparer(account.inheritedAccountId, keys, to), batches });
  };

  const screenProps = {
    title: 'Cuenta heredada',
    help: HELP_INHERITED,
    tone: 'deep' as const,
    isHome: asTab,
    onProfilePress: asTab ? profileMenu.openProfileMenu : undefined,
    avatar: activeAccount?.avatar || 'C',
    scroll: false,
  };
  const empty = !!account && account.assets.length === 0;

  return (
    <SmartScreen
      {...screenProps}
      footer={account && !empty ? (
        <>
          <ActionButton label="Mover a mi billetera" onPress={() => move('wallet')} testID="inherited-to-wallet" />
          {account.canMoveToSmartAccount ? (
            <ActionButton
              label="Mover a mi Cuenta inteligente"
              variant="secondary"
              onPress={() => move('smart_account')}
              style={styles.second}
              testID="inherited-to-smart"
            />
          ) : null}
        </>
      ) : undefined}
    >
      {list.loading && !list.data ? <ScreenSkeleton /> : list.failed && !list.data ? (
        <View>
          <LoadError onRetry={list.reload} busy={list.loading} />
          {/* Confío cannot be reached: the account is still the person's, and
              this phone remembers its address. Withdraw to the own wallet
              directly on the network. */}
          <View style={styles.side}>
            <DirectClaimPanel
              inheritedAccountId={wantedId ?? ''}
              serverDown
              onDone={() => { void list.reload(); }}
            />
          </View>
        </View>
      ) : registering ? (
        <View style={styles.registering} testID="inherited-registering" accessibilityLiveRegion="polite">
          <ActivityIndicator color={SA.deep} />
          <Text style={styles.registeringText}>Estamos terminando de registrar la cuenta…</Text>
          <ActionButton label="Reintentar" variant="secondary" onPress={list.reload} busy={list.loading} style={styles.side} />
        </View>
      ) : !account ? (
        <View>
          <Empty icon="inbox" title="No encontramos esta cuenta" body="Puede que ya no tenga nada." />
          {asTab ? (
            <View style={styles.side}>
              <ActionButton label="Ir a mi billetera" onPress={() => { void returnToPersonal(); }} busy={switching} />
            </View>
          ) : null}
        </View>
      ) : (
        <FlatList
          data={account.assets}
          keyExtractor={(item) => item.key}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          // No getItemLayout: a row grows with the system font size (text
          // wraps, amounts never truncate), so its height is not fixed. No
          // onEndReached: the inherited read returns every asset at once.
          contentContainerStyle={styles.list}
          refreshControl={(
            <RefreshControl refreshing={list.loading} onRefresh={list.reload} tintColor={SA.deep} colors={[SA.deep]} />
          )}
          ListHeaderComponent={(
            <View style={styles.hero}>
              <View style={styles.tag}><Text style={styles.tagText}>Heredada</Text></View>
              <Text style={styles.heroLabel}>{`Cuenta de ${account.fromName}`}</Text>
              <Text
                style={styles.heroAmount}
                numberOfLines={1}
                adjustsFontSizeToFit
                minimumFontScale={0.5}
                accessibilityLabel={`Total: ${balanceHidden ? 'saldo oculto' : usd(account.totalUsd)}`}
                testID="inherited-total"
              >
                {balanceHidden ? HIDDEN_AMOUNT : usd(account.totalUsd)}
              </Text>
              <Text style={styles.heroLine}>{`La recibiste el ${shortDate(account.inheritedAt)}. Muévela cuando quieras.`}</Text>
            </View>
          )}
          ListEmptyComponent={(
            <View>
              <Empty icon="check-circle" title="Ya moviste todo" body="Esta cuenta está vacía." />
              {asTab ? (
                <View style={styles.side}>
                  <ActionButton label="Ir a mi billetera" onPress={() => { void returnToPersonal(); }} busy={switching} />
                </View>
              ) : null}
            </View>
          )}
          renderItem={({ item }) => (
            <View style={styles.rowBox}>
              <Row left={<AssetMark asset={item} />} title={assetTitle(item)} subtitle={item.symbol} value={usd(item.valueUsd)} />
            </View>
          )}
        />
      )}
      <SignFlowSheet
        flow={flow}
        copy={{
          confirmLabel: 'Firmar y mover',
          signingMessage: 'Moviendo…',
          successTitle: 'Movimiento completo',
          successBody: destination === 'wallet' ? 'Ya está en tu billetera.' : 'Ya está en tu Cuenta inteligente.',
        }}
        onDone={asTab ? undefined : () => navigation.goBack()}
      />
      {asTab ? <AccountSwitcherHost /> : null}
    </SmartScreen>
  );
}

/** The Home tab while the active context is an inherited account. */
export function InheritedAccountTab() {
  return <InheritedAccountScreen asTab />;
}

const styles = StyleSheet.create({
  list: { paddingBottom: 24 },
  side: { paddingHorizontal: 16 },
  registering: { alignItems: 'center', paddingHorizontal: 24, paddingTop: 48 },
  registeringText: { fontSize: 16, lineHeight: 24, color: SA.text, textAlign: 'center', marginTop: 16, marginBottom: 16 },
  second: { marginTop: 10 },
  hero: {
    backgroundColor: SA.deep, paddingHorizontal: 20, paddingTop: 8, paddingBottom: 24, marginBottom: 8,
    borderBottomLeftRadius: 28, borderBottomRightRadius: 28,
  },
  tag: {
    alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999,
    backgroundColor: 'rgba(255,255,255,0.16)', marginBottom: 10,
  },
  tagText: { fontSize: 12, fontWeight: '700', color: SA.onDeep, letterSpacing: 0.3 },
  heroLabel: { fontSize: 15, color: SA.onDeepMuted },
  heroAmount: { fontSize: 40, fontWeight: '700', color: SA.onDeep, marginTop: 2 },
  heroLine: { fontSize: 14, lineHeight: 20, color: SA.onDeepMuted, marginTop: 6 },
  rowBox: { marginHorizontal: 16, marginTop: 8, paddingHorizontal: 16, backgroundColor: SA.card, borderRadius: 16 },
});
