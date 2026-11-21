// Cuenta inteligente: every charge of the plan ("Ver todos" from Tu plan).
// A paginated FlatList: pages are fetched by cursor as the list nears its end.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { Empty, LoadError, Row, RowsSkeleton, SmartScreen, kitStyles } from '../components/smartAccount/kit';
import { SA } from '../components/smartAccount/tokens';
import { usd } from '../components/smartAccount/format';
import { fetchSmartAccountCharges, type SmartAccountCharge } from '../services/smartAccount';
import { chargeSubtitle, chargeTitle } from './SmartAccountBillingScreen';

const PAGE = 20;

export function SmartAccountChargesScreen() {
  const [items, setItems] = useState<SmartAccountCharge[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const cursor = useRef<string | null>(null);
  const more = useRef(false);
  const busy = useRef(false);
  const mounted = useRef(true);

  const loadFirst = useCallback(async (asRefresh = false) => {
    if (busy.current) {
      return;
    }
    busy.current = true;
    if (asRefresh) { setRefreshing(true); } else { setState('loading'); }
    const result = await fetchSmartAccountCharges(PAGE);
    busy.current = false;
    if (!mounted.current) {
      return;
    }
    setRefreshing(false);
    if (!result.ok) {
      // A failed refresh keeps the list already on screen.
      setState((prev) => (asRefresh && prev === 'ready' ? 'ready' : 'failed'));
      return;
    }
    setItems(result.data.items);
    cursor.current = result.data.endCursor;
    more.current = result.data.hasNextPage;
    setState('ready');
  }, []);

  useEffect(() => {
    mounted.current = true;
    void loadFirst();
    return () => {
      mounted.current = false;
    };
  }, [loadFirst]);

  const loadMore = async () => {
    if (busy.current || !more.current || !cursor.current) {
      return;
    }
    busy.current = true;
    setLoadingMore(true);
    const result = await fetchSmartAccountCharges(PAGE, cursor.current);
    busy.current = false;
    if (!mounted.current) {
      return;
    }
    setLoadingMore(false);
    if (!result.ok) {
      return; // the next scroll to the end tries again
    }
    setItems((prev) => {
      const seen = new Set(prev.map((c) => c.id));
      return [...prev, ...result.data.items.filter((c) => !seen.has(c.id))];
    });
    cursor.current = result.data.endCursor;
    more.current = result.data.hasNextPage;
  };

  return (
    <SmartScreen title="Cobros" scroll={false}>
      {state === 'loading' ? (
        <View style={kitStyles.pad}><RowsSkeleton rows={5} /></View>
      ) : state === 'failed' ? (
        <LoadError onRetry={() => { void loadFirst(); }} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(item) => String(item.id)}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          // No getItemLayout: a row grows with the system font size (title,
          // subtitle and amount wrap, never truncate), so its height is not
          // fixed. Paginated by cursor: onEndReached loads the next page.
          onEndReached={() => { void loadMore(); }}
          onEndReachedThreshold={0.5}
          contentContainerStyle={styles.list}
          refreshControl={(
            <RefreshControl refreshing={refreshing} onRefresh={() => { void loadFirst(true); }} tintColor={SA.deep} colors={[SA.deep]} />
          )}
          ListEmptyComponent={<Empty icon="credit-card" title="Todavía no hay cobros" />}
          ListFooterComponent={loadingMore ? <ActivityIndicator color={SA.deep} style={styles.more} /> : null}
          renderItem={({ item }) => (
            <View style={styles.rowBox}>
              <Row title={chargeTitle(item)} subtitle={chargeSubtitle(item)} value={usd(item.feeUsd)} testID={`charge-${item.id}`} />
            </View>
          )}
        />
      )}
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  list: { paddingTop: 8, paddingBottom: 24 },
  rowBox: { marginHorizontal: 16, marginTop: 8, paddingHorizontal: 16, backgroundColor: SA.card, borderRadius: 16 },
  more: { paddingVertical: 16 },
});
