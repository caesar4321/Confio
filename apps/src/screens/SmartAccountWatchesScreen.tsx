// Cuenta inteligente: the owner's alerts (Confío IA+, spec decision 34).
//
// Alerts are created by talking to the assistant ("avísame si TSLA baja 5%");
// here they are listed and deleted. The sentence of each one is the server's.
// An alert only tells the owner: a buy they attached is shown, prefilled, for
// them to review and sign. Nothing here moves money.
import React, { useEffect, useState } from 'react';
import { Alert, FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { Empty, IconDisc, LoadError, Row, RowsSkeleton, SmartScreen, kitStyles } from '../components/smartAccount/kit';
import { HELP_WATCHES } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { shortDate } from '../components/smartAccount/format';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { deleteSmartAccountWatch, fetchSmartAccountWatches, type SmartAccountWatch } from '../services/smartAccount';

export function watchSubtitle(watch: SmartAccountWatch): string | undefined {
  return watch.lastTriggeredAt ? `Último aviso: ${shortDate(watch.lastTriggeredAt)}` : undefined;
}

export function SmartAccountWatchesScreen() {
  const navigation = useNavigation<any>();
  const watches = useSmartRead(fetchSmartAccountWatches);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const unsubscribe = navigation.addListener?.('focus', () => { void watches.reload(); });
    return typeof unsubscribe === 'function' ? unsubscribe : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigation]);

  const remove = (watch: SmartAccountWatch) => {
    Alert.alert('Borrar alerta', watch.text, [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Borrar',
        style: 'destructive',
        onPress: async () => {
          setBusy(watch.watchId);
          const out = await deleteSmartAccountWatch(watch.watchId);
          setBusy(null);
          if (!out.success) {
            Alert.alert('No se pudo borrar', out.errorMessage || 'Inténtalo de nuevo.');
          }
          void watches.reload();
        },
      },
    ]);
  };

  const items = watches.data ?? [];
  const loading = watches.loading && !watches.data;
  const failed = watches.failed && !watches.data;

  return (
    <SmartScreen title="Alertas" help={HELP_WATCHES} scroll={false}>
      {loading ? (
        <View style={kitStyles.pad}><RowsSkeleton rows={3} /></View>
      ) : failed ? (
        <LoadError onRetry={watches.reload} busy={watches.loading} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(item) => item.watchId}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          // No getItemLayout: the sentence wraps with the system font size.
          // No onEndReached: at most 10 alerts, all in one read.
          contentContainerStyle={styles.list}
          refreshControl={(
            <RefreshControl refreshing={watches.loading} onRefresh={watches.reload} tintColor={SA.deep} colors={[SA.deep]} />
          )}
          ListEmptyComponent={(
            <Empty
              icon="bell"
              title="Aún no tienes alertas"
              body="Pídele a Confío IA+ que te avise cuando un precio llegue al nivel que tú elijas."
            />
          )}
          renderItem={({ item }) => (
            <View style={styles.rowBox}>
              <Row
                left={<IconDisc icon="bell" tone="mint" />}
                title={item.text}
                subtitle={watchSubtitle(item)}
                value={busy === item.watchId ? '…' : 'Borrar'}
                onPress={() => remove(item)}
                accessibilityLabel={`${item.text} Borrar`}
                testID={`watch-${item.watchId}`}
              />
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
});
