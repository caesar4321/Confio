// Full movement history for Ahorros e Inversiones (cUSD+ world).
//
// The hub shows only the most recent few movements so the sections below it
// (partnership, education) stay reachable; the unbounded list lives here.
// FlatList carries the house pagination config; when the backend lands,
// onEndReached fetches the next page from the same wiring point
// (useAhorrosPortfolio.movements → paginated GraphQL query).

import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  FlatList,
  StatusBar,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { colors } from '../config/theme';
import { useAhorrosPortfolio, AhorroMovement } from '../hooks/useAhorrosPortfolio';
import { MovementRow } from '../components/MovementRow';

export const AhorrosMovimientosScreen = () => {
  const navigation = useNavigation();
  const { movements } = useAhorrosPortfolio();

  const renderItem = ({ item, index }: { item: AhorroMovement; index: number }) => (
    <MovementRow movement={item} topBorder={index > 0} />
  );

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Movimientos</Text>
          <View style={styles.headerIconBtn} />
        </View>
      </SafeAreaView>

      <FlatList
        data={movements}
        keyExtractor={(m) => m.id}
        renderItem={renderItem}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Icon name="clock" size={26} color={colors.text.light} />
            <Text style={styles.emptyText}>
              Aquí verás tus ahorros, retiros, compras y el rendimiento que ganas.
            </Text>
          </View>
        }
        initialNumToRender={20}
        maxToRenderPerBatch={10}
        windowSize={21}
        // TODO(cusd+): onEndReached → fetchMore next page once the movements
        // query is server-backed.
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 16,
  },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },

  listContent: {
    padding: 16,
    paddingBottom: 40,
    backgroundColor: '#fff',
    borderRadius: 16,
    margin: 16,
  },

  empty: { alignItems: 'center', paddingVertical: 32, gap: 10 },
  emptyText: {
    fontSize: 12,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 17,
    paddingHorizontal: 24,
  },
});
