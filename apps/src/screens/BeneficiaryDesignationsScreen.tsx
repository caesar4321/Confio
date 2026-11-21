// Cuenta inteligente: every account the viewer was named on as beneficiary,
// when there are two or more (the Inicio row opens this instead of picking
// one). One row each; a row opens that designation's invitation, claim or
// claim status. Nothing is signed from here.
import React, { useEffect } from 'react';
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import { Empty, IconDisc, LoadError, Row, ScreenSkeleton, SmartScreen } from '../components/smartAccount/kit';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import { HELP_DESIGNATED } from '../components/smartAccount/help';
import { SA } from '../components/smartAccount/tokens';
import { daysLabel, daysUntil, shortDate } from '../components/smartAccount/format';
import { designationScreen, distinctOpenDesignations } from '../hooks/useSmartAccountEntry';
import { fetchBeneficiaryDesignations, type BeneficiaryDesignation } from '../services/smartAccount';

/** The quiet line under the owner's name: where this designation stands. */
export function designationStatus(d: BeneficiaryDesignation, now: number = Date.now()): string {
  if (d.state === 'pending_acceptance') {
    return 'Te invitó como beneficiario. Responde la invitación.';
  }
  const claim = d.claim;
  if (claim && claim.state === 'executable') {
    return 'Ya puedes recibir la cuenta.';
  }
  if (claim && claim.state === 'pending') {
    const days = daysUntil(claim.executableAt, now);
    return days !== null && days > 0
      ? `Pediste la cuenta. Faltan ${daysLabel(days)}.`
      : `Pediste la cuenta. Disponible el ${shortDate(claim.executableAt)}.`;
  }
  if (d.canClaim) {
    return 'Puedes pedir la cuenta.';
  }
  return 'Eres beneficiario.';
}

export function BeneficiaryDesignationsScreen() {
  const navigation = useNavigation<any>();
  const list = useSmartRead(fetchBeneficiaryDesignations);
  const rows = distinctOpenDesignations(list.data ?? []);

  useEffect(() => {
    const unsubscribe = navigation?.addListener?.('focus', () => { void list.reload(); });
    return typeof unsubscribe === 'function' ? unsubscribe : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigation]);

  const open = (d: BeneficiaryDesignation) => {
    navigation.navigate(designationScreen(d), { designationId: d.designationId });
  };

  return (
    <SmartScreen title="Eres beneficiario" help={HELP_DESIGNATED} scroll={false}>
      {list.loading && !list.data ? <ScreenSkeleton /> : list.failed && !list.data ? (
        <LoadError onRetry={list.reload} busy={list.loading} />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => item.designationId}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          // No getItemLayout: a row grows with the system font size. No
          // onEndReached: the designations read returns every row at once.
          contentContainerStyle={styles.list}
          refreshControl={(
            <RefreshControl refreshing={list.loading} onRefresh={list.reload} tintColor={SA.deep} colors={[SA.deep]} />
          )}
          ListHeaderComponent={(
            <Text style={styles.intro}>
              Te eligieron en más de una Cuenta inteligente. Toca una para verla.
            </Text>
          )}
          ListEmptyComponent={(
            <Empty icon="inbox" title="No tienes designaciones" body="Cuando alguien te elija como beneficiario, aparecerá aquí." />
          )}
          renderItem={({ item }) => (
            <View style={styles.rowBox}>
              <Row
                left={<IconDisc icon={item.state === 'pending_acceptance' ? 'mail' : 'shield'} />}
                title={`Cuenta de ${item.ownerName}`}
                subtitle={item.ownerHandle ? `@${item.ownerHandle}` : undefined}
                note={designationStatus(item)}
                chevron
                onPress={() => open(item)}
                testID={`designation-${item.designationId}`}
              />
            </View>
          )}
        />
      )}
    </SmartScreen>
  );
}

const styles = StyleSheet.create({
  list: { paddingBottom: 24 },
  intro: { fontSize: 15, lineHeight: 22, color: SA.text, marginHorizontal: 20, marginTop: 16, marginBottom: 8 },
  rowBox: { marginHorizontal: 16, marginTop: 8, paddingHorizontal: 16, backgroundColor: SA.card, borderRadius: 16 },
});
